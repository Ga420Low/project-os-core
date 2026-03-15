from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import MemoryCuratorConfig
from ..database import CanonicalDatabase, dump_json
from ..local_model import LocalModelClient
from ..models import CuratorRun, ThoughtMemoryStatus, new_id, utc_now_iso
from ..runtime.journal import LocalJournal
from ..secrets import SecretResolver
from .blocks import MemoryBlockStore
from .os_service import MemoryOSService
from .temporal_graph import TemporalGraphService
from .thoughts import ThoughtMemoryService


class SleeptimeCuratorService:
    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        config: MemoryCuratorConfig,
        blocks: MemoryBlockStore,
        memory_os: MemoryOSService,
        thoughts: ThoughtMemoryService,
        temporal_graph: TemporalGraphService,
        local_model_client: LocalModelClient,
        secret_resolver: SecretResolver,
        default_openai_model: str,
    ) -> None:
        self.database = database
        self.journal = journal
        self.config = config
        self.blocks = blocks
        self.memory_os = memory_os
        self.thoughts = thoughts
        self.temporal_graph = temporal_graph
        self.local_model_client = local_model_client
        self.secret_resolver = secret_resolver
        self.default_openai_model = default_openai_model

    def list_runs(self, *, limit: int = 20) -> list[CuratorRun]:
        rows = self.database.fetchall(
            "SELECT * FROM curator_runs ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        )
        return [self._row_to_run(row) for row in rows]

    def get_run(self, curator_run_id: str) -> CuratorRun:
        row = self.database.fetchone("SELECT * FROM curator_runs WHERE curator_run_id = ?", (curator_run_id,))
        if row is None:
            raise KeyError(f"Unknown curator run: {curator_run_id}")
        return self._row_to_run(row)

    def run_sleeptime(
        self,
        *,
        trigger: str,
        async_mode: bool | None = None,
        lookback_hours: int | None = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return {"status": "skipped", "reason": "disabled_by_config"}
        bounded_lookback = max(1, int(lookback_hours or self.config.lookback_hours))
        now = datetime.now(timezone.utc)
        window_end = now.isoformat()
        window_start = (now - timedelta(hours=bounded_lookback)).isoformat()
        sources = self._collect_sources(window_start=window_start, window_end=window_end)
        source_signature = self._source_signature(sources)
        existing = self._find_idempotent_run(source_signature)
        if existing is not None:
            return {
                "status": "skipped",
                "reason": "idempotent_window",
                "run": existing,
                "source_signature": source_signature,
            }
        run = CuratorRun(
            curator_run_id=new_id("curator_run"),
            status="running",
            trigger=trigger,
            window_start=window_start,
            window_end=window_end,
            llm_mode=self.config.llm_mode,
            model=None,
            summary=None,
            input_summary={"source_signature": source_signature, "counts": sources["counts"]},
            output_summary={},
            metadata={"source_signature": source_signature},
        )
        self._persist_run(run)
        self.memory_os.trace_operation(
            operation="curator_run_started",
            target_type="curator_run",
            target_id=run.curator_run_id,
            detail={"trigger": trigger, "window_start": window_start, "window_end": window_end},
        )
        use_async = self.config.async_enabled if async_mode is None else bool(async_mode)
        if use_async:
            worker = threading.Thread(
                target=self._execute_run,
                kwargs={"run_id": run.curator_run_id, "sources": sources},
                daemon=True,
                name=f"memory-curator-{run.curator_run_id}",
            )
            worker.start()
            return {"status": "running", "async": True, "run": run}
        return self._execute_run(run_id=run.curator_run_id, sources=sources)

    def _execute_run(self, *, run_id: str, sources: dict[str, Any]) -> dict[str, Any]:
        run = self.get_run(run_id)
        try:
            block_refresh = self.blocks.refresh_runtime_blocks()
            plan = self._llm_plan(sources)
            if plan is None:
                plan = self._deterministic_plan(sources)
            thought_results = self._apply_thoughts(plan.get("thoughts", []))
            block_results = self._apply_block_updates(plan.get("block_updates", []))
            graph_results = self._apply_graph_facts(plan.get("graph_facts", []))
            output_summary = {
                "thoughts_created": len(thought_results),
                "blocks_updated": len(block_results),
                "graph_facts_upserted": len(graph_results),
                "refreshed_blocks": block_refresh["updated_blocks"],
            }
            updated = CuratorRun(
                curator_run_id=run.curator_run_id,
                status="completed",
                trigger=run.trigger,
                window_start=run.window_start,
                window_end=run.window_end,
                llm_mode=run.llm_mode,
                model=plan.get("model"),
                summary=plan.get("summary") or f"Curated {len(thought_results)} thoughts and {len(block_results)} blocks.",
                input_summary=run.input_summary,
                output_summary=output_summary,
                metadata=run.metadata,
                created_at=run.created_at,
                updated_at=utc_now_iso(),
            )
            self._persist_run(updated)
            self.memory_os.trace_operation(
                operation="curator_run_completed",
                target_type="curator_run",
                target_id=run.curator_run_id,
                detail=output_summary,
                status="ok",
            )
            return {"status": "completed", "run": updated, "output_summary": output_summary}
        except Exception as exc:
            failed = CuratorRun(
                curator_run_id=run.curator_run_id,
                status="failed",
                trigger=run.trigger,
                window_start=run.window_start,
                window_end=run.window_end,
                llm_mode=run.llm_mode,
                model=run.model,
                summary=str(exc),
                input_summary=run.input_summary,
                output_summary=run.output_summary,
                metadata={**run.metadata, "error": str(exc)},
                created_at=run.created_at,
                updated_at=utc_now_iso(),
            )
            self._persist_run(failed)
            self.memory_os.trace_operation(
                operation="curator_run_failed",
                target_type="curator_run",
                target_id=run.curator_run_id,
                detail={"error": str(exc)},
                status="failed",
            )
            raise

    def _collect_sources(self, *, window_start: str, window_end: str) -> dict[str, Any]:
        sources: dict[str, Any] = {}
        sources["channel_events"] = self.database.fetchall(
            """
            SELECT event_id, channel, conversation_key, message_json, created_at
            FROM channel_events
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (window_start, window_end, self.config.max_items_per_source),
        )
        sources["gateway_dispatch_results"] = self.database.fetchall(
            """
            SELECT dispatch_id, channel_event_id, reply_json, metadata_json, created_at
            FROM gateway_dispatch_results
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (window_start, window_end, self.config.max_items_per_source),
        )
        sources["decision_records"] = self.database.fetchall(
            """
            SELECT decision_record_id, status, scope, summary, metadata_json, updated_at
            FROM decision_records
            WHERE updated_at >= ? AND updated_at <= ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (window_start, window_end, self.config.max_items_per_source),
        )
        sources["learning_signals"] = self.database.fetchall(
            """
            SELECT signal_id, kind, severity, summary, metadata_json, created_at
            FROM learning_signals
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (window_start, window_end, self.config.max_items_per_source),
        )
        sources["api_run_results"] = self.database.fetchall(
            """
            SELECT run_id, run_request_id, status, structured_output_json, metadata_json, updated_at
            FROM api_run_results
            WHERE updated_at >= ? AND updated_at <= ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (window_start, window_end, self.config.max_items_per_source),
        )
        sources["session_snapshots"] = self.database.fetchall(
            """
            SELECT snapshot_id, metadata_json, created_at
            FROM session_snapshots
            WHERE created_at >= ? AND created_at <= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (window_start, window_end, min(3, self.config.max_items_per_source)),
        )
        sources["counts"] = {
            key: len(value)
            for key, value in sources.items()
            if isinstance(value, list)
        }
        return sources

    def _llm_plan(self, sources: dict[str, Any]) -> dict[str, Any] | None:
        if self.config.llm_mode == "disabled":
            return None
        prompt = self._render_prompt(sources)
        if self.config.prefer_local_model and self.local_model_client.health().get("status") == "ready":
            try:
                response = self.local_model_client.chat(
                    message=prompt,
                    system=(
                        "Return strict JSON with keys summary, block_updates, thoughts, graph_facts. "
                        "Never include markdown fences."
                    ),
                )
                parsed = json.loads(response.content)
                if isinstance(parsed, dict):
                    parsed["model"] = response.model
                    return parsed
            except Exception:
                return None
        api_key = self.secret_resolver.get_optional("OPENAI_API_KEY")
        if api_key:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key)
                response = client.responses.create(
                    model=self.default_openai_model,
                    input=[
                        {
                            "role": "system",
                            "content": (
                                "You are the Project OS sleeptime curator. Return strict JSON only with "
                                "summary, block_updates, thoughts, graph_facts."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                )
                text = getattr(response, "output_text", "") or ""
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    parsed["model"] = self.default_openai_model
                    return parsed
            except Exception:
                return None
        return None

    def _render_prompt(self, sources: dict[str, Any]) -> str:
        payload = {
            "counts": sources["counts"],
            "decision_records": [
                {
                    "decision_record_id": str(row["decision_record_id"]),
                    "status": str(row["status"]),
                    "scope": str(row["scope"]),
                    "summary": str(row["summary"]),
                }
                for row in sources["decision_records"]
            ],
            "learning_signals": [
                {"signal_id": str(row["signal_id"]), "kind": str(row["kind"]), "summary": str(row["summary"])}
                for row in sources["learning_signals"]
            ],
            "gateway_dispatch_results": [
                {
                    "dispatch_id": str(row["dispatch_id"]),
                    "channel_event_id": str(row["channel_event_id"]),
                    "reply": json.loads(str(row["reply_json"])) if row["reply_json"] else {},
                }
                for row in sources["gateway_dispatch_results"]
            ],
            "api_run_results": [
                {
                    "run_id": str(row["run_id"]),
                    "status": str(row["status"]),
                    "metadata": json.loads(str(row["metadata_json"])) if row["metadata_json"] else {},
                }
                for row in sources["api_run_results"]
            ],
            "channel_events": [
                {
                    "event_id": str(row["event_id"]),
                    "channel": str(row["channel"]),
                    "conversation_key": str(row["conversation_key"]) if row["conversation_key"] else None,
                    "message": json.loads(str(row["message_json"])) if row["message_json"] else {},
                }
                for row in sources["channel_events"]
            ],
        }
        prompt = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        if len(prompt) > self.config.max_prompt_chars:
            return prompt[: self.config.max_prompt_chars]
        return prompt

    def _deterministic_plan(self, sources: dict[str, Any]) -> dict[str, Any]:
        thoughts: list[dict[str, Any]] = []
        graph_facts: list[dict[str, Any]] = []
        for row in sources["decision_records"]:
            decision_id = str(row["decision_record_id"])
            summary = str(row["summary"]).strip()
            if not summary:
                continue
            status = str(row["status"]).strip().lower()
            thoughts.append(
                {
                    "kind": "decision",
                    "summary": summary,
                    "content": f"Decision durable: {summary}",
                    "source_ids": [decision_id],
                    "confidence": 0.82,
                    "metadata": {"decision_scope": str(row["scope"]), "decision_status": status, "privacy_view": "clean"},
                }
            )
            graph_facts.append(
                {
                    "entity": str(row["scope"]),
                    "relation": "decision_" + status,
                    "value": summary,
                    "source_ref": decision_id,
                    "valid_at": str(row["updated_at"]),
                    "metadata": {"source": "curator_decision"},
                }
            )
        for row in sources["learning_signals"]:
            signal_id = str(row["signal_id"])
            summary = str(row["summary"]).strip()
            if not summary:
                continue
            thoughts.append(
                {
                    "kind": "signal",
                    "summary": summary,
                    "content": f"Signal a retenir: {summary}",
                    "source_ids": [signal_id],
                    "confidence": 0.68,
                    "metadata": {"severity": str(row["severity"]), "privacy_view": "clean"},
                }
            )
        block_updates = []
        recent_lines = ["# Recent Operating Context", ""]
        if thoughts:
            recent_lines.append("## Consolidated thoughts")
            for item in thoughts[:5]:
                recent_lines.append(f"- {item['summary']}")
        if sources["channel_events"]:
            recent_lines.extend(["", "## Recent messages"])
            for row in sources["channel_events"][:3]:
                message = json.loads(str(row["message_json"])) if row["message_json"] else {}
                recent_lines.append(f"- {str(message.get('text') or '').strip() or 'n/a'}")
        if sources["api_run_results"]:
            recent_lines.extend(["", "## Recent runs"])
            for row in sources["api_run_results"][:3]:
                metadata = json.loads(str(row["metadata_json"])) if row["metadata_json"] else {}
                branch_name = str(metadata.get("branch_name") or "n/a")
                recent_lines.append(f"- {row['status']} | branch={branch_name}")
        block_updates.append(
            {
                "block_name": "profiles/recent_operating_context.md",
                "content": "\n".join(recent_lines).strip() + "\n",
                "owner_role": "memory_curator",
                "updated_by_role": "memory_curator",
                "reason": "sleeptime_curator",
                "provenance": ["curator:sleeptime"],
            }
        )
        return {
            "summary": f"Deterministic curator plan with {len(thoughts)} thoughts.",
            "block_updates": block_updates,
            "thoughts": thoughts,
            "graph_facts": graph_facts,
        }

    def _apply_thoughts(self, thought_specs: list[dict[str, Any]]) -> list[str]:
        created_ids: list[str] = []
        for item in thought_specs:
            if float(item.get("confidence") or 0.0) < float(self.thoughts.thoughts_config.min_confidence):
                continue
            if self._thought_exists(kind=str(item.get("kind") or ""), summary=str(item.get("summary") or "")):
                continue
            thought = self.thoughts.create_thought(
                kind=str(item.get("kind") or "note"),
                summary=str(item.get("summary") or ""),
                content=str(item.get("content") or item.get("summary") or ""),
                source_ids=list(item.get("source_ids") or []),
                confidence=float(item.get("confidence") or 0.6),
                metadata=dict(item.get("metadata") or {}),
            )
            created_ids.append(thought.thought_id)
        return created_ids

    def _apply_block_updates(self, block_specs: list[dict[str, Any]]) -> list[str]:
        updated: list[str] = []
        for item in block_specs:
            block = self.blocks.upsert_block(
                block_name=str(item["block_name"]),
                content=str(item["content"]),
                owner_role=str(item.get("owner_role") or "memory_curator"),
                updated_by_role=str(item.get("updated_by_role") or "memory_curator"),
                updated_by_run_id=str(item.get("updated_by_run_id")) if item.get("updated_by_run_id") else None,
                reason=str(item.get("reason") or "curator_update"),
                provenance=list(item.get("provenance") or ["curator:sleeptime"]),
                surface="scheduler",
            )
            updated.append(block.block_name)
        return updated

    def _apply_graph_facts(self, fact_specs: list[dict[str, Any]]) -> list[str]:
        upserted: list[str] = []
        for item in fact_specs:
            fact = self.temporal_graph.upsert_fact(
                entity=str(item["entity"]),
                relation=str(item["relation"]),
                value=str(item["value"]),
                source_ref=str(item["source_ref"]),
                valid_at=str(item.get("valid_at") or utc_now_iso()),
                invalid_at=str(item["invalid_at"]) if item.get("invalid_at") else None,
                episode_id=str(item["episode_id"]) if item.get("episode_id") else None,
                metadata=dict(item.get("metadata") or {}),
            )
            self.memory_os.trace_operation(
                operation="graph_fact_upserted",
                target_type="temporal_graph_fact",
                target_id=fact["fact_id"],
                detail={"entity": fact["entity"], "relation": fact["relation"]},
            )
            upserted.append(fact["fact_id"])
        return upserted

    def _find_idempotent_run(self, source_signature: str) -> CuratorRun | None:
        rows = self.database.fetchall(
            """
            SELECT * FROM curator_runs
            WHERE status = 'completed'
            ORDER BY updated_at DESC
            LIMIT 10
            """
        )
        for row in rows:
            metadata = json.loads(str(row["metadata_json"])) if row["metadata_json"] else {}
            if metadata.get("source_signature") == source_signature:
                return self._row_to_run(row)
        return None

    @staticmethod
    def _source_signature(sources: dict[str, Any]) -> str:
        parts: list[str] = []
        for key, rows in sources.items():
            if key == "counts" or not isinstance(rows, list):
                continue
            for row in rows:
                values = dict(row)
                parts.append(json.dumps(values, ensure_ascii=True, sort_keys=True, default=str))
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def _persist_run(self, run: CuratorRun) -> None:
        self.database.upsert(
            "curator_runs",
            {
                "curator_run_id": run.curator_run_id,
                "status": run.status,
                "trigger": run.trigger,
                "window_start": run.window_start,
                "window_end": run.window_end,
                "llm_mode": run.llm_mode,
                "model": run.model,
                "summary": run.summary,
                "input_summary_json": dump_json(run.input_summary),
                "output_summary_json": dump_json(run.output_summary),
                "metadata_json": dump_json(run.metadata),
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            },
            conflict_columns="curator_run_id",
            immutable_columns=["created_at"],
        )

    def _row_to_run(self, row) -> CuratorRun:
        return CuratorRun(
            curator_run_id=str(row["curator_run_id"]),
            status=str(row["status"]),
            trigger=str(row["trigger"]),
            window_start=str(row["window_start"]),
            window_end=str(row["window_end"]),
            llm_mode=str(row["llm_mode"]),
            model=str(row["model"]) if row["model"] else None,
            summary=str(row["summary"]) if row["summary"] else None,
            input_summary=json.loads(str(row["input_summary_json"])) if row["input_summary_json"] else {},
            output_summary=json.loads(str(row["output_summary_json"])) if row["output_summary_json"] else {},
            metadata=json.loads(str(row["metadata_json"])) if row["metadata_json"] else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _thought_exists(self, *, kind: str, summary: str) -> bool:
        rows = self.database.fetchall(
            """
            SELECT thought_id, kind, summary FROM thought_memories
            WHERE status = ?
            ORDER BY updated_at DESC
            LIMIT 50
            """,
            (ThoughtMemoryStatus.ACTIVE.value,),
        )
        for row in rows:
            if str(row["kind"]) == kind and str(row["summary"]).strip().lower() == summary.strip().lower():
                return True
        return False
