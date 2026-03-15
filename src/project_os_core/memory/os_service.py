from __future__ import annotations

import math
import json
from datetime import datetime, timezone
from typing import Any

from ..config import MemoryConfig
from ..database import CanonicalDatabase, dump_json
from ..models import (
    MemCube,
    MemoryBlock,
    MemoryLayer,
    RecallPlan,
    RetrievalContext,
    SupersessionRecord,
    ThoughtMemory,
    new_id,
    utc_now_iso,
)
from ..paths import PathPolicy, ProjectPaths
from ..runtime.journal import LocalJournal
from .blocks import MemoryBlockStore
from .temporal_graph import TemporalGraphService


class MemoryOSService:
    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        config: MemoryConfig,
        blocks: MemoryBlockStore,
        temporal_graph: TemporalGraphService,
    ) -> None:
        self.database = database
        self.journal = journal
        self.paths = paths
        self.path_policy = path_policy
        self.config = config
        self.blocks = blocks
        self.temporal_graph = temporal_graph
        self.thoughts = None
        self.blocks.attach_tracer(self.trace_operation)
        if self.config.blocks.enabled and self.config.blocks.bootstrap_defaults:
            self.blocks.ensure_default_blocks()

    def attach_thought_service(self, thoughts) -> None:
        self.thoughts = thoughts

    def trace_operation(
        self,
        *,
        operation: str,
        target_type: str,
        target_id: str,
        detail: dict[str, Any] | None = None,
        status: str = "ok",
        routing_trace_id: str | None = None,
        run_id: str | None = None,
        decision_record_id: str | None = None,
        channel_event_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "trace_id": new_id("memory_trace"),
            "operation": operation,
            "target_type": target_type,
            "target_id": target_id,
            "status": status,
            "detail_json": dump_json(detail or {}),
            "routing_trace_id": routing_trace_id,
            "run_id": run_id,
            "decision_record_id": decision_record_id,
            "channel_event_id": channel_event_id,
            "created_at": utc_now_iso(),
        }
        self.database.upsert(
            "memory_operation_traces",
            payload,
            conflict_columns="trace_id",
            immutable_columns=["created_at"],
        )
        if self.config.tracing.enabled and self.config.tracing.emit_journal_events:
            self.journal.append(
                "memory_operation_trace",
                "memory_os",
                {
                    "trace_id": payload["trace_id"],
                    "operation": operation,
                    "target_type": target_type,
                    "target_id": target_id,
                    "status": status,
                },
            )
        if self.config.tracing.enabled and self.config.tracing.otel_hooks_enabled:
            self._emit_otel_hook(payload=payload, detail=detail or {})
        return payload

    def create_cube(
        self,
        *,
        payload: dict[str, Any],
        layer: MemoryLayer,
        kind: str,
        confidence: float = 1.0,
        supersedes: list[str] | None = None,
        sources: list[str] | None = None,
        access_scope: str = "clean",
        usage_stats: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemCube:
        cube = MemCube(
            cube_id=new_id("mem_cube"),
            payload=payload,
            layer=layer,
            kind=kind,
            confidence=max(0.0, min(1.0, float(confidence))),
            supersedes=list(supersedes or []),
            sources=list(sources or []),
            access_scope=access_scope,
            usage_stats=dict(usage_stats or {}),
            metadata=dict(metadata or {}),
        )
        self.database.upsert(
            "mem_cubes",
            {
                "cube_id": cube.cube_id,
                "layer": cube.layer.value,
                "kind": cube.kind,
                "payload_json": dump_json(cube.payload),
                "confidence": cube.confidence,
                "supersedes_json": dump_json(cube.supersedes),
                "sources_json": dump_json(cube.sources),
                "access_scope": cube.access_scope,
                "usage_stats_json": dump_json(cube.usage_stats),
                "metadata_json": dump_json(cube.metadata),
                "created_at": cube.created_at,
                "updated_at": cube.updated_at,
            },
            conflict_columns="cube_id",
            immutable_columns=["created_at"],
        )
        self.trace_operation(
            operation="cube_created",
            target_type="mem_cube",
            target_id=cube.cube_id,
            detail={"layer": cube.layer.value, "kind": cube.kind, "sources": cube.sources},
        )
        return cube

    def list_cubes(self, *, layer: MemoryLayer | None = None, kind: str | None = None, limit: int = 20) -> list[MemCube]:
        clauses: list[str] = []
        params: list[Any] = []
        if layer is not None:
            clauses.append("layer = ?")
            params.append(layer.value)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        sql = "SELECT * FROM mem_cubes"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        rows = self.database.fetchall(sql, tuple(params))
        return [self._row_to_cube(row) for row in rows]

    def build_recall_plan(self, *, context: RetrievalContext, reason: str) -> RecallPlan:
        needed_blocks = ["profiles/founder_stable_profile.md", "profiles/recent_operating_context.md"]
        if context.surface == "discord" or context.channel == "discord":
            needed_blocks.append("runtime/discord_state.md")
        if context.project_id or context.mission_id or context.branch_name:
            needed_blocks.append("runtime/mission_state.md")
        if context.requested_worker or (context.target_profile and "uefn" in context.target_profile.lower()):
            needed_blocks.append("runtime/uefn_state.md")
        if context.metadata.get("operator_language"):
            needed_blocks.append("system/founder.md")
        seen_blocks = []
        for item in needed_blocks:
            if item not in seen_blocks:
                seen_blocks.append(item)
        session_ids = self._recent_session_ids(context)
        search_terms = self._cube_search_terms(context)
        cube_rows: list[Any] = []
        if search_terms:
            where_parts: list[str] = []
            params: list[Any] = []
            for term in search_terms[:6]:
                where_parts.append("(sources_json LIKE '%' || ? || '%' OR payload_json LIKE '%' || ? || '%')")
                params.extend([term, term])
            params.append(1 if context.include_private_full else 0)
            params.append(5)
            cube_rows = self.database.fetchall(
                f"""
                SELECT cube_id FROM mem_cubes
                WHERE ({' OR '.join(where_parts)})
                  AND (access_scope != 'full' OR ? = 1)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            )
        plan = RecallPlan(
            recall_plan_id=new_id("recall_plan"),
            query=context.query,
            reason=reason,
            needed_blocks=seen_blocks,
            needed_cubes=[str(row["cube_id"]) for row in cube_rows],
            needed_sessions=session_ids,
            metadata={
                "surface": context.surface,
                "channel": context.channel,
                "thread_id": context.thread_id,
                "conversation_key": context.conversation_key,
            },
        )
        self.trace_operation(
            operation="recall_plan_built",
            target_type="recall_plan",
            target_id=plan.recall_plan_id,
            detail={
                "needed_blocks": plan.needed_blocks,
                "needed_cubes": plan.needed_cubes,
                "needed_sessions": plan.needed_sessions,
                "reason": reason,
            },
            channel_event_id=context.metadata.get("channel_event_id"),
            run_id=context.metadata.get("run_id"),
        )
        return plan

    def dual_layer_profile(self) -> dict[str, Any]:
        stable = self.blocks.get_block("profiles/founder_stable_profile.md")
        recent = self.blocks.get_block("profiles/recent_operating_context.md")
        return {
            "stable": stable.content,
            "recent": recent.content,
            "stable_version": stable.version,
            "recent_version": recent.version,
        }

    def record_supersession(
        self,
        *,
        superseded_type: str,
        superseded_id: str,
        superseding_type: str,
        superseding_id: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> SupersessionRecord:
        record = SupersessionRecord(
            supersession_record_id=new_id("supersession"),
            superseded_type=superseded_type,
            superseded_id=superseded_id,
            superseding_type=superseding_type,
            superseding_id=superseding_id,
            reason=reason,
            metadata=dict(metadata or {}),
        )
        self.database.upsert(
            "supersession_records",
            {
                "supersession_record_id": record.supersession_record_id,
                "superseded_type": record.superseded_type,
                "superseded_id": record.superseded_id,
                "superseding_type": record.superseding_type,
                "superseding_id": record.superseding_id,
                "reason": record.reason,
                "metadata_json": dump_json(record.metadata),
                "created_at": record.created_at,
            },
            conflict_columns="supersession_record_id",
            immutable_columns=["created_at"],
        )
        self.trace_operation(
            operation="cube_superseded" if superseded_type == "mem_cube" else "supersession_recorded",
            target_type=superseded_type,
            target_id=superseded_id,
            detail={
                "superseding_type": superseding_type,
                "superseding_id": superseding_id,
                "reason": reason,
            },
        )
        return record

    def enrich_search_results(self, *, context: RetrievalContext, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.config.thoughts.enabled or not self.config.thoughts.prefer_for_recall or self.thoughts is None:
            return hits[: context.limit]
        recall_plan = self.build_recall_plan(context=context, reason="memory.search")
        thought_hits = self.thoughts.search(
            query=context.query,
            limit=self.config.thoughts.max_results,
            include_private_full=context.include_private_full,
        )
        if not thought_hits:
            return hits[: context.limit]
        enriched: list[dict[str, Any]] = []
        for thought in thought_hits:
            enriched.append(self._thought_to_hit(thought, recall_plan))
        enriched.extend(hits)
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in enriched:
            key = str(item.get("memory_id") or item.get("_candidate_key") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped.sort(
            key=lambda item: (
                -self._result_score(item),
                str(item.get("memory_id") or item.get("_candidate_key") or ""),
            )
        )
        return deduped[: context.limit]

    def _recent_session_ids(self, context: RetrievalContext) -> list[str]:
        session_ids: list[str] = []
        thread_keys = [
            key
            for key in (
                context.conversation_key,
                context.external_thread_id,
                context.thread_id,
            )
            if key
        ]
        if context.channel and thread_keys:
            placeholders = ", ".join("?" for _ in thread_keys)
            params: list[Any] = [str(context.channel), *thread_keys, *thread_keys, *thread_keys]
            rows = self.database.fetchall(
                f"""
                SELECT ce.event_id
                FROM channel_events AS ce
                LEFT JOIN discord_thread_bindings AS dtb ON dtb.channel_event_id = ce.event_id
                WHERE ce.channel = ?
                  AND (
                    ce.conversation_key IN ({placeholders})
                    OR dtb.external_thread_id IN ({placeholders})
                    OR dtb.thread_id IN ({placeholders})
                  )
                ORDER BY ce.created_at DESC
                LIMIT 3
                """,
                tuple(params),
            )
            session_ids.extend(str(row["event_id"]) for row in rows)
        elif context.conversation_key:
            rows = self.database.fetchall(
                """
                SELECT event_id FROM channel_events
                WHERE conversation_key = ?
                ORDER BY created_at DESC
                LIMIT 3
                """,
                (context.conversation_key,),
            )
            session_ids.extend(str(row["event_id"]) for row in rows)
        if context.branch_name or context.target_profile:
            clauses: list[str] = []
            params = []
            if context.branch_name:
                clauses.append("req.branch_name = ?")
                params.append(context.branch_name)
            if context.target_profile:
                clauses.append("req.target_profile = ?")
                params.append(context.target_profile)
            params.append(2)
            rows = self.database.fetchall(
                """
                SELECT res.run_id
                FROM api_run_requests AS req
                LEFT JOIN api_run_results AS res ON res.run_request_id = req.run_request_id
                WHERE """ + " OR ".join(clauses) + """
                ORDER BY COALESCE(res.updated_at, req.updated_at) DESC
                LIMIT ?
                """,
                tuple(params),
            )
            session_ids.extend(str(row["run_id"]) for row in rows if row["run_id"])
        seen: list[str] = []
        for item in session_ids:
            if item not in seen:
                seen.append(item)
        return seen[:5]

    def _thought_to_hit(self, thought: ThoughtMemory, recall_plan: RecallPlan) -> dict[str, Any]:
        recency_boost = self._thought_recency_boost(thought.updated_at)
        final_score = max(thought.confidence, 0.0) + recency_boost
        return {
            "memory_id": thought.thought_id,
            "_candidate_key": thought.thought_id,
            "source": "thought_memory",
            "record": {
                "content": thought.content,
                "user_id": "project_os",
                "created_at": thought.updated_at,
                "metadata": {
                    "privacy_view": thought.metadata.get("privacy_view", "clean"),
                    "thought_kind": thought.kind,
                    "thought_summary": thought.summary,
                    "source_ids": list(thought.source_ids),
                    "recall_plan_id": recall_plan.recall_plan_id,
                },
            },
            "retrieval_trace": {
                "candidate_source": "thought_memory",
                "base_score": thought.confidence,
                "session_recall_boost": 0.0,
                "recency_boost": recency_boost,
                "diversity_penalty": 0.0,
                "final_score": final_score,
            },
        }

    @staticmethod
    def _result_score(item: dict[str, Any]) -> float:
        trace = item.get("retrieval_trace")
        if isinstance(trace, dict) and trace.get("final_score") is not None:
            try:
                return float(trace["final_score"])
            except (TypeError, ValueError):
                return 0.0
        distance = item.get("distance")
        if distance is not None:
            try:
                return 1.0 / (1.0 + max(float(distance), 0.0))
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    @staticmethod
    def _thought_recency_boost(updated_at: str) -> float:
        try:
            timestamp = datetime.fromisoformat(updated_at)
            now = datetime.now(timestamp.tzinfo or timezone.utc)
            age_hours = max(0.0, (now - timestamp).total_seconds() / 3600.0)
        except Exception:
            return 0.0
        return max(0.0, min(0.1, 0.1 * math.exp(-age_hours / 168.0)))

    @staticmethod
    def _cube_search_terms(context: RetrievalContext) -> list[str]:
        raw_values = [
            context.query,
            context.project_id or "",
            context.mission_id or "",
            context.branch_name or "",
            context.target_profile or "",
            context.requested_worker or "",
            context.channel or "",
            context.surface or "",
        ]
        terms: list[str] = []
        seen: set[str] = set()
        for value in raw_values:
            for token in str(value).replace("/", " ").replace(":", " ").split():
                normalized = token.strip().lower()
                if len(normalized) < 3 or normalized in seen:
                    continue
                seen.add(normalized)
                terms.append(normalized)
        return terms

    def _emit_otel_hook(self, *, payload: dict[str, Any], detail: dict[str, Any]) -> None:
        self.journal.append(
            "memory_operation_trace_otel_hook",
            "memory_os",
            {
                "trace_id": payload["trace_id"],
                "operation": payload["operation"],
                "target_type": payload["target_type"],
                "target_id": payload["target_id"],
                "detail": detail,
            },
        )

    @staticmethod
    def _row_to_cube(row) -> MemCube:
        return MemCube(
            cube_id=str(row["cube_id"]),
            payload=json.loads(str(row["payload_json"])) if row["payload_json"] else {},
            layer=MemoryLayer(str(row["layer"])),
            kind=str(row["kind"]),
            confidence=float(row["confidence"]),
            supersedes=json.loads(str(row["supersedes_json"])) if row["supersedes_json"] else [],
            sources=json.loads(str(row["sources_json"])) if row["sources_json"] else [],
            access_scope=str(row["access_scope"]),
            usage_stats=json.loads(str(row["usage_stats_json"])) if row["usage_stats_json"] else {},
            metadata=json.loads(str(row["metadata_json"])) if row["metadata_json"] else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
