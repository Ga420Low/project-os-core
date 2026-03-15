from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..database import CanonicalDatabase, dump_json
from ..memory.store import MemoryStore
from ..models import (
    DatasetCandidate,
    DecisionRecord,
    DecisionStatus,
    EvalCandidate,
    LearningSignal,
    LearningSignalKind,
    LoopSignal,
    MemoryTier,
    MemoryType,
    NoiseSignal,
    RefreshRecommendation,
    new_id,
    to_jsonable,
)
from ..paths import PathPolicy, ProjectPaths
from ..runtime.journal import LocalJournal


class LearningService:
    """Promotes durable project intelligence beyond raw memory storage."""

    _RUNBOOK_DEFERRED_BLOCK_RE = re.compile(
        r"```project-os-deferred[ \t]*\r?\n(.*?)```",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        memory: MemoryStore,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        auto_sync_runbook_deferred: bool = False,
        runbook_deferred_globs: list[str] | None = None,
    ) -> None:
        self.database = database
        self.journal = journal
        self.memory = memory
        self.paths = paths
        self.path_policy = path_policy
        self.auto_sync_runbook_deferred = auto_sync_runbook_deferred
        self.runbook_deferred_globs = list(runbook_deferred_globs or [])

    def gather_learning_context(
        self,
        *,
        mode: str,
        branch_name: str,
        objective: str,
        limit: int = 10,
        lookback_hours: int = 72,
    ) -> dict[str, Any]:
        """Collecte les lecons pertinentes pour un nouveau run sans appel API."""

        if self.auto_sync_runbook_deferred:
            self.sync_runbook_deferred_decisions()

        bounded_limit = max(1, min(int(limit), 10))
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))).isoformat()
        decision_sample_limit = max(24, bounded_limit * 8)
        decision_rows = self.database.fetchall(
            """
            SELECT decision_record_id, scope, summary, status, source_run_id, metadata_json, created_at, updated_at
            FROM decision_records
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cutoff, decision_sample_limit),
        )
        signal_rows = self.database.fetchall(
            """
            SELECT kind, summary, severity, created_at, metadata_json
            FROM learning_signals
            WHERE severity IN ('high', 'critical')
              AND created_at >= ?
              AND (summary LIKE '%' || ? || '%' OR metadata_json LIKE '%' || ? || '%')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cutoff, branch_name, branch_name, bounded_limit),
        )
        loop_rows = self.database.fetchall(
            """
            SELECT repeated_pattern, impacted_area, recommended_reset
            FROM loop_signals
            WHERE impacted_area LIKE '%' || ? || '%'
              AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT 3
            """,
            (branch_name, cutoff),
        )
        refresh_rows = self.database.fetchall(
            """
            SELECT cause, next_step
            FROM refresh_recommendations
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT 3
            """,
            (cutoff,),
        )

        match_terms = self._build_match_terms(mode=mode, branch_name=branch_name, objective=objective)
        recent_decisions: list[dict[str, Any]] = []
        scoped_deferred: list[dict[str, Any]] = []
        recent_deferred: list[dict[str, Any]] = []
        seen_deferred_ids: set[str] = set()
        seen_deferred_signatures: set[tuple[str, str, str]] = set()
        for row in decision_rows:
            metadata = self._load_json_object(row["metadata_json"])
            decision_payload = {
                "decision_record_id": str(row["decision_record_id"]),
                "scope": str(row["scope"]),
                "summary": str(row["summary"]),
                "status": str(row["status"]),
                "source_run_id": str(row["source_run_id"]) if row["source_run_id"] else None,
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "metadata": metadata,
            }
            is_deferred = metadata.get("classification") == "deferred"
            matches_context = self._matches_learning_terms(
                scope=decision_payload["scope"],
                summary=decision_payload["summary"],
                metadata=metadata,
                match_terms=match_terms,
            )
            if is_deferred:
                signature = self._deferred_signature(decision_payload)
                if signature in seen_deferred_signatures:
                    continue
                seen_deferred_signatures.add(signature)
                if matches_context and len(scoped_deferred) < bounded_limit:
                    scoped_deferred.append(decision_payload)
                    seen_deferred_ids.add(decision_payload["decision_record_id"])
                if len(recent_deferred) < bounded_limit:
                    recent_deferred.append(decision_payload)
                continue
            if matches_context and len(recent_decisions) < bounded_limit:
                recent_decisions.append(decision_payload)

        deferred_decisions = list(scoped_deferred)
        if mode == "audit":
            fallback_budget = min(3, bounded_limit)
            for item in recent_deferred:
                if len(deferred_decisions) >= fallback_budget:
                    break
                if item["decision_record_id"] in seen_deferred_ids:
                    continue
                deferred_decisions.append(item)
                seen_deferred_ids.add(item["decision_record_id"])

        learning_context = {
            "decisions": recent_decisions,
            "deferred_decisions": deferred_decisions,
            "high_severity_signals": [
                {
                    "kind": str(row["kind"]),
                    "summary": str(row["summary"]),
                    "severity": str(row["severity"]),
                    "created_at": str(row["created_at"]),
                    "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                }
                for row in signal_rows
            ],
            "detected_loops": [
                {
                    "pattern": str(row["repeated_pattern"]),
                    "area": str(row["impacted_area"]),
                    "recommended_reset": str(row["recommended_reset"]),
                }
                for row in loop_rows
            ],
            "refresh_recommendations": [
                {
                    "cause": str(row["cause"]),
                    "next_step": str(row["next_step"]),
                }
                for row in refresh_rows
            ],
        }
        if not any(learning_context.values()):
            return {}
        learning_context["summary"] = (
            f"{len(learning_context['decisions'])} decisions, "
            f"{len(learning_context['deferred_decisions'])} deferred gaps, "
            f"{len(learning_context['high_severity_signals'])} high signals, "
            f"{len(learning_context['detected_loops'])} loops, "
            f"{len(learning_context['refresh_recommendations'])} refresh recommendations "
            f"in last {max(1, int(lookback_hours))}h."
        )
        return learning_context

    def sync_runbook_deferred_decisions(
        self,
        *,
        glob_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        patterns = [item for item in (glob_patterns or self.runbook_deferred_globs) if str(item).strip()]
        if not patterns:
            return {
                "enabled": False,
                "glob_patterns": [],
                "files_scanned": 0,
                "items_discovered": 0,
                "created": 0,
                "updated": 0,
                "unchanged": 0,
                "invalid": 0,
            }

        files_scanned = 0
        items_discovered = 0
        created = 0
        updated = 0
        unchanged = 0
        invalid = 0
        for runbook_path in self._resolve_runbook_paths(patterns):
            files_scanned += 1
            for block in self._parse_runbook_deferred_blocks(runbook_path):
                items_discovered += 1
                outcome = self._upsert_runbook_deferred_block(runbook_path=runbook_path, block=block)
                if outcome == "created":
                    created += 1
                elif outcome == "updated":
                    updated += 1
                elif outcome == "unchanged":
                    unchanged += 1
                else:
                    invalid += 1
        if created or updated:
            self.journal.append(
                "runbook_deferred_sync",
                "learning",
                {
                    "files_scanned": files_scanned,
                    "items_discovered": items_discovered,
                    "created": created,
                    "updated": updated,
                    "unchanged": unchanged,
                    "invalid": invalid,
                },
            )
        return {
            "enabled": True,
            "glob_patterns": patterns,
            "files_scanned": files_scanned,
            "items_discovered": items_discovered,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "invalid": invalid,
        }

    def cleanup_duplicate_deferred_decisions(self, *, dry_run: bool = False) -> dict[str, Any]:
        rows = self.database.fetchall(
            """
            SELECT decision_record_id, status, scope, summary, source_run_id, metadata_json, created_at, updated_at
            FROM decision_records
            ORDER BY created_at ASC
            """
        )
        grouped: dict[tuple[str, str, str], list[Any]] = {}
        for row in rows:
            metadata = self._load_json_object(row["metadata_json"])
            if metadata.get("classification") != "deferred":
                continue
            signature = (
                str(row["scope"]),
                str(row["summary"]),
                str(metadata.get("next_trigger") or ""),
            )
            grouped.setdefault(signature, []).append(row)

        duplicates: list[dict[str, Any]] = []
        removed_ids: list[str] = []
        removed_artifacts: list[str] = []
        for signature, items in grouped.items():
            if len(items) <= 1:
                continue
            canonical = self._choose_canonical_deferred(items)
            duplicate_ids = [str(item["decision_record_id"]) for item in items if item["decision_record_id"] != canonical["decision_record_id"]]
            duplicates.append(
                {
                    "signature": {
                        "scope": signature[0],
                        "summary": signature[1],
                        "next_trigger": signature[2],
                    },
                    "canonical_id": str(canonical["decision_record_id"]),
                    "removed_ids": duplicate_ids,
                }
            )
            if dry_run:
                continue
            for duplicate_id in duplicate_ids:
                self.database.execute("DELETE FROM decision_records WHERE decision_record_id = ?", (duplicate_id,))
                removed_ids.append(duplicate_id)
                artifact_path = self.paths.learning_decision_records_root / f"{duplicate_id}.json"
                if artifact_path.exists():
                    artifact_path.unlink()
                    removed_artifacts.append(str(artifact_path))

        if not dry_run and removed_ids:
            self.journal.append(
                "deferred_decision_cleanup",
                "learning",
                {
                    "removed_ids": removed_ids,
                    "removed_artifact_count": len(removed_artifacts),
                },
            )
        return {
            "dry_run": dry_run,
            "duplicate_groups": len(duplicates),
            "removed_count": len(removed_ids),
            "removed_artifact_count": len(removed_artifacts),
            "groups": duplicates,
        }

    def list_deferred_decisions(
        self,
        *,
        scope_prefix: str | None = None,
        objective: str | None = None,
        limit: int = 10,
        lookback_hours: int = 24 * 90,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 50))
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))).isoformat()
        sample_limit = max(32, bounded_limit * 8)
        rows = self.database.fetchall(
            """
            SELECT decision_record_id, scope, summary, status, source_run_id, metadata_json, created_at, updated_at
            FROM decision_records
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cutoff, sample_limit),
        )
        match_terms = self._build_match_terms(mode=None, branch_name=scope_prefix or "", objective=objective or "")
        results: list[dict[str, Any]] = []
        seen_signatures: set[tuple[str, str, str]] = set()
        for row in rows:
            metadata = self._load_json_object(row["metadata_json"])
            if metadata.get("classification") != "deferred":
                continue
            scope = str(row["scope"])
            if scope_prefix and not scope.startswith(scope_prefix):
                continue
            if match_terms and not self._matches_learning_terms(
                scope=scope,
                summary=str(row["summary"]),
                metadata=metadata,
                match_terms=match_terms,
            ):
                continue
            payload = {
                "decision_record_id": str(row["decision_record_id"]),
                "scope": scope,
                "summary": str(row["summary"]),
                "status": str(row["status"]),
                "source_run_id": str(row["source_run_id"]) if row["source_run_id"] else None,
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "metadata": metadata,
            }
            signature = self._deferred_signature(payload)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            results.append(payload)
            if len(results) >= bounded_limit:
                break
        return results

    def record_decision(
        self,
        *,
        status: DecisionStatus,
        scope: str,
        summary: str,
        source_run_id: str | None = None,
        metadata: dict | None = None,
    ) -> DecisionRecord:
        record = DecisionRecord(
            decision_record_id=new_id("decision_record"),
            status=status,
            scope=scope,
            summary=summary,
            source_run_id=source_run_id,
            metadata=metadata or {},
        )
        self.database.upsert(
            "decision_records",
            {
                "decision_record_id": record.decision_record_id,
                "status": record.status.value,
                "scope": record.scope,
                "summary": record.summary,
                "source_run_id": record.source_run_id,
                "metadata_json": dump_json(record.metadata),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            },
            conflict_columns="decision_record_id",
            immutable_columns=["created_at"],
        )
        self.memory.remember(
            content=f"DECISION {record.status.value.upper()}: [{record.scope}] {record.summary}",
            user_id="project_os",
            memory_type=MemoryType.PROCEDURAL,
            tier=MemoryTier.WARM,
            tags=["decision_record", record.status.value, record.scope],
            metadata={
                **record.metadata,
                "decision_record_id": record.decision_record_id,
                "source_run_id": source_run_id,
            },
        )
        self.record_signal(
            kind=LearningSignalKind.DECISION_PROMOTED,
            severity="info",
            summary=f"{record.status.value}: {record.summary}",
            source_ids=[item for item in [record.decision_record_id, source_run_id] if item],
            metadata={"scope": record.scope},
        )
        self.journal.append(
            "decision_recorded",
            "learning",
            {
                "decision_record_id": record.decision_record_id,
                "status": record.status.value,
                "scope": record.scope,
                "source_run_id": source_run_id,
            },
        )
        self._write_decision_record_artifact(record)
        return record

    def record_deferred_decision(
        self,
        *,
        scope: str,
        summary: str,
        next_trigger: str | None = None,
        source_run_id: str | None = None,
        metadata: dict | None = None,
    ) -> DecisionRecord:
        payload = dict(metadata or {})
        payload["classification"] = "deferred"
        payload["deferred_at"] = datetime.now(timezone.utc).isoformat()
        if next_trigger:
            payload["next_trigger"] = next_trigger
        record = self.record_decision(
            status=DecisionStatus.CONFIRMED,
            scope=scope,
            summary=summary,
            source_run_id=source_run_id,
            metadata=payload,
        )
        self._append_deferred_decision_log(record)
        self.journal.append(
            "decision_deferred",
            "learning",
            {
                "decision_record_id": record.decision_record_id,
                "scope": record.scope,
                "next_trigger": next_trigger,
            },
        )
        return record

    def record_signal(
        self,
        *,
        kind: LearningSignalKind,
        severity: str,
        summary: str,
        source_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> LearningSignal:
        signal = LearningSignal(
            signal_id=new_id("learning_signal"),
            kind=kind,
            severity=severity,
            summary=summary,
            source_ids=list(source_ids or []),
            metadata=metadata or {},
        )
        self.database.upsert(
            "learning_signals",
            {
                "signal_id": signal.signal_id,
                "kind": signal.kind.value,
                "severity": signal.severity,
                "summary": signal.summary,
                "source_ids_json": dump_json(signal.source_ids),
                "metadata_json": dump_json(signal.metadata),
                "created_at": signal.created_at,
            },
            conflict_columns="signal_id",
            immutable_columns=["created_at"],
        )
        self.journal.append(
            "learning_signal_recorded",
            "learning",
            {
                "signal_id": signal.signal_id,
                "kind": signal.kind.value,
                "severity": signal.severity,
            },
        )
        return signal

    def record_loop_signal(
        self,
        *,
        repeated_pattern: str,
        impacted_area: str,
        recommended_reset: str,
        source_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> LoopSignal:
        signal = LoopSignal(
            loop_signal_id=new_id("loop_signal"),
            repeated_pattern=repeated_pattern,
            impacted_area=impacted_area,
            recommended_reset=recommended_reset,
            source_ids=list(source_ids or []),
            metadata=metadata or {},
        )
        self.database.upsert(
            "loop_signals",
            {
                "loop_signal_id": signal.loop_signal_id,
                "repeated_pattern": signal.repeated_pattern,
                "impacted_area": signal.impacted_area,
                "recommended_reset": signal.recommended_reset,
                "source_ids_json": dump_json(signal.source_ids),
                "metadata_json": dump_json(signal.metadata),
                "created_at": signal.created_at,
            },
            conflict_columns="loop_signal_id",
            immutable_columns=["created_at"],
        )
        self.record_signal(
            kind=LearningSignalKind.LOOP_DETECTED,
            severity="warning",
            summary=f"Loop detected in {impacted_area}: {repeated_pattern}",
            source_ids=[signal.loop_signal_id, *signal.source_ids],
            metadata={"recommended_reset": recommended_reset},
        )
        return signal

    def record_noise_signal(
        self,
        *,
        run_id: str,
        reason: str,
        evidence: dict | None = None,
    ) -> NoiseSignal:
        signal = NoiseSignal(
            noise_signal_id=new_id("noise_signal"),
            run_id=run_id,
            reason=reason,
            evidence=evidence or {},
        )
        self.database.upsert(
            "noise_signals",
            {
                "noise_signal_id": signal.noise_signal_id,
                "run_id": signal.run_id,
                "reason": signal.reason,
                "evidence_json": dump_json(signal.evidence),
                "created_at": signal.created_at,
            },
            conflict_columns="noise_signal_id",
            immutable_columns=["created_at"],
        )
        self.record_signal(
            kind=LearningSignalKind.NOISE_DETECTED,
            severity="medium",
            summary=f"Noise detected for run {run_id}: {reason}",
            source_ids=[signal.noise_signal_id, run_id],
            metadata=evidence or {},
        )
        return signal

    def _write_decision_record_artifact(self, record: DecisionRecord) -> Path:
        target = self.path_policy.ensure_allowed_write(
            self.paths.learning_decision_records_root / f"{record.decision_record_id}.json"
        )
        payload = to_jsonable(record)
        target.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        return target

    def _append_deferred_decision_log(self, record: DecisionRecord) -> Path:
        target = self.path_policy.ensure_allowed_write(self.paths.learning_deferred_log_path)
        payload = {
            "decision_record_id": record.decision_record_id,
            "scope": record.scope,
            "summary": record.summary,
            "status": record.status.value,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "metadata": record.metadata,
        }
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
        return target

    def _resolve_runbook_paths(self, patterns: list[str]) -> list[Path]:
        resolved: list[Path] = []
        seen: set[Path] = set()
        for pattern in patterns:
            candidate = Path(pattern)
            matches = []
            if candidate.is_absolute():
                if any(token in pattern for token in ("*", "?", "[")):
                    matches = [Path(item) for item in sorted(candidate.parent.glob(candidate.name))]
                elif candidate.exists():
                    matches = [candidate]
            else:
                matches = [Path(item) for item in sorted(self.paths.repo_root.glob(pattern))]
            for match in matches:
                normalized = match.resolve(strict=False)
                if normalized in seen or not normalized.is_file():
                    continue
                seen.add(normalized)
                resolved.append(normalized)
        return resolved

    def _parse_runbook_deferred_blocks(self, runbook_path: Path) -> list[dict[str, str]]:
        content = runbook_path.read_text(encoding="utf-8")
        blocks: list[dict[str, str]] = []
        for raw_block in self._RUNBOOK_DEFERRED_BLOCK_RE.findall(content):
            payload: dict[str, str] = {}
            for line in raw_block.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if ":" not in stripped:
                    continue
                key, value = stripped.split(":", 1)
                payload[key.strip().lower()] = value.strip()
            blocks.append(payload)
        return blocks

    def _upsert_runbook_deferred_block(self, *, runbook_path: Path, block: dict[str, str]) -> str:
        item_id = block.get("id", "").strip()
        scope = block.get("scope", "").strip()
        summary = block.get("summary", "").strip()
        if not item_id or not scope or not summary:
            return "invalid"
        next_trigger = block.get("next_trigger", "").strip() or None
        relative_path = self._display_runbook_path(runbook_path)
        sync_key = f"{relative_path}::{item_id}"
        sync_hash = hashlib.sha256(
            json.dumps(
                {
                    "scope": scope,
                    "summary": summary,
                    "next_trigger": next_trigger,
                },
                ensure_ascii=True,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        existing_row = self._find_existing_runbook_deferred(sync_key)
        if existing_row is None:
            existing_row = self._find_equivalent_deferred(
                scope=scope,
                summary=summary,
                next_trigger=next_trigger,
            )
        metadata = {
            "classification": "deferred",
            "source": "runbook_sync",
            "runbook_path": relative_path,
            "runbook_item_id": item_id,
            "runbook_sync_key": sync_key,
            "runbook_sync_hash": sync_hash,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        }
        if next_trigger:
            metadata["next_trigger"] = next_trigger
        if existing_row is None:
            self.record_deferred_decision(
                scope=scope,
                summary=summary,
                next_trigger=next_trigger,
                metadata=metadata,
            )
            return "created"

        existing_metadata = self._load_json_object(existing_row["metadata_json"])
        if existing_metadata.get("runbook_sync_hash") == sync_hash:
            return "unchanged"

        payload = {
            **existing_metadata,
            **metadata,
            "deferred_at": existing_metadata.get("deferred_at", datetime.now(timezone.utc).isoformat()),
        }
        updated_at = datetime.now(timezone.utc).isoformat()
        self.database.upsert(
            "decision_records",
            {
                "decision_record_id": str(existing_row["decision_record_id"]),
                "status": str(existing_row["status"]),
                "scope": scope,
                "summary": summary,
                "source_run_id": existing_row["source_run_id"],
                "metadata_json": dump_json(payload),
                "created_at": str(existing_row["created_at"]),
                "updated_at": updated_at,
            },
            conflict_columns="decision_record_id",
            immutable_columns=["created_at"],
        )
        record = DecisionRecord(
            decision_record_id=str(existing_row["decision_record_id"]),
            status=DecisionStatus(str(existing_row["status"])),
            scope=scope,
            summary=summary,
            source_run_id=str(existing_row["source_run_id"]) if existing_row["source_run_id"] else None,
            metadata=payload,
            created_at=str(existing_row["created_at"]),
            updated_at=updated_at,
        )
        self._write_decision_record_artifact(record)
        self._append_deferred_decision_log(record)
        self.journal.append(
            "decision_deferred_synced",
            "learning",
            {
                "decision_record_id": record.decision_record_id,
                "scope": record.scope,
                "runbook_path": relative_path,
                "runbook_item_id": item_id,
            },
        )
        return "updated"

    def _find_existing_runbook_deferred(self, sync_key: str):
        rows = self.database.fetchall(
            """
            SELECT decision_record_id, status, scope, summary, source_run_id, metadata_json, created_at, updated_at
            FROM decision_records
            WHERE metadata_json LIKE '%' || ? || '%'
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (sync_key,),
        )
        for row in rows:
            metadata = self._load_json_object(row["metadata_json"])
            if metadata.get("runbook_sync_key") == sync_key:
                return row
        return None

    def _find_equivalent_deferred(self, *, scope: str, summary: str, next_trigger: str | None):
        rows = self.database.fetchall(
            """
            SELECT decision_record_id, status, scope, summary, source_run_id, metadata_json, created_at, updated_at
            FROM decision_records
            WHERE scope = ?
            ORDER BY created_at ASC
            LIMIT 50
            """,
            (scope,),
        )
        for row in rows:
            if str(row["summary"]) != summary:
                continue
            metadata = self._load_json_object(row["metadata_json"])
            if metadata.get("classification") != "deferred":
                continue
            if (metadata.get("next_trigger") or None) != next_trigger:
                continue
            return row
        return None

    def _choose_canonical_deferred(self, rows: list[Any]):
        def _rank(row: Any) -> tuple[int, str]:
            metadata = self._load_json_object(row["metadata_json"])
            source = str(metadata.get("source") or "")
            has_sync = 0 if source == "runbook_sync" else 1
            created_at = str(row["created_at"])
            return (has_sync, created_at)

        return sorted(rows, key=_rank)[0]

    def _display_runbook_path(self, runbook_path: Path) -> str:
        normalized = runbook_path.resolve(strict=False)
        repo_root = self.paths.repo_root.resolve(strict=False)
        try:
            return normalized.relative_to(repo_root).as_posix()
        except ValueError:
            return normalized.as_posix()

    def _deferred_signature(self, payload: dict[str, Any]) -> tuple[str, str, str]:
        metadata = payload.get("metadata", {})
        next_trigger = ""
        if isinstance(metadata, dict):
            next_trigger = str(metadata.get("next_trigger") or "")
        return (
            str(payload.get("scope") or ""),
            str(payload.get("summary") or ""),
            next_trigger,
        )

    def _build_match_terms(self, *, mode: str | None, branch_name: str, objective: str) -> list[str]:
        terms: list[str] = []
        for raw in (mode, branch_name, objective):
            value = (raw or "").strip().lower()
            if value and value not in terms:
                terms.append(value)
            for token in self._tokenize_for_match(value):
                if token not in terms:
                    terms.append(token)
        return terms

    def _matches_learning_terms(
        self,
        *,
        scope: str,
        summary: str,
        metadata: dict[str, Any],
        match_terms: list[str],
    ) -> bool:
        if not match_terms:
            return True
        haystack = " ".join(
            [
                scope.lower(),
                summary.lower(),
                json.dumps(metadata, ensure_ascii=True, sort_keys=True).lower(),
            ]
        )
        return any(term in haystack for term in match_terms)

    def _tokenize_for_match(self, value: str) -> list[str]:
        if not value:
            return []
        raw_tokens = []
        token_buffer: list[str] = []
        for character in value:
            if character.isalnum() or character in ("-", "_", "/"):
                token_buffer.append(character)
                continue
            if token_buffer:
                raw_tokens.append("".join(token_buffer))
                token_buffer = []
        if token_buffer:
            raw_tokens.append("".join(token_buffer))
        return [token for token in raw_tokens if len(token) >= 4 or "/" in token or "-" in token]

    def _load_json_object(self, payload: Any) -> dict[str, Any]:
        if not payload:
            return {}
        if isinstance(payload, dict):
            return payload
        try:
            parsed = json.loads(str(payload))
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def recommend_refresh(
        self,
        *,
        cause: str,
        context_to_reload: list[str],
        next_step: str,
        source_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> RefreshRecommendation:
        recommendation = RefreshRecommendation(
            refresh_recommendation_id=new_id("refresh_rec"),
            cause=cause,
            context_to_reload=context_to_reload,
            next_step=next_step,
            source_ids=list(source_ids or []),
            metadata=metadata or {},
        )
        self.database.upsert(
            "refresh_recommendations",
            {
                "refresh_recommendation_id": recommendation.refresh_recommendation_id,
                "cause": recommendation.cause,
                "context_to_reload_json": dump_json(recommendation.context_to_reload),
                "next_step": recommendation.next_step,
                "source_ids_json": dump_json(recommendation.source_ids),
                "metadata_json": dump_json(recommendation.metadata),
                "created_at": recommendation.created_at,
            },
            conflict_columns="refresh_recommendation_id",
            immutable_columns=["created_at"],
        )
        self.record_signal(
            kind=LearningSignalKind.REFRESH_NEEDED,
            severity="warning",
            summary=f"Refresh recommended: {cause}",
            source_ids=[recommendation.refresh_recommendation_id, *recommendation.source_ids],
            metadata={"next_step": next_step},
        )
        return recommendation

    def record_dataset_candidate(
        self,
        *,
        source_type: str,
        quality_score: float,
        export_ready: bool,
        source_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> DatasetCandidate:
        candidate = DatasetCandidate(
            dataset_candidate_id=new_id("dataset_candidate"),
            source_type=source_type,
            quality_score=quality_score,
            export_ready=export_ready,
            source_ids=list(source_ids or []),
            metadata=metadata or {},
        )
        self.database.upsert(
            "dataset_candidates",
            {
                "dataset_candidate_id": candidate.dataset_candidate_id,
                "source_type": candidate.source_type,
                "quality_score": candidate.quality_score,
                "export_ready": 1 if candidate.export_ready else 0,
                "source_ids_json": dump_json(candidate.source_ids),
                "metadata_json": dump_json(candidate.metadata),
                "created_at": candidate.created_at,
            },
            conflict_columns="dataset_candidate_id",
            immutable_columns=["created_at"],
        )
        return candidate

    def record_eval_candidate(
        self,
        *,
        scenario: str,
        target_system: str,
        expected_behavior: str,
        source_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> EvalCandidate:
        candidate = EvalCandidate(
            eval_candidate_id=new_id("eval_candidate"),
            scenario=scenario,
            target_system=target_system,
            expected_behavior=expected_behavior,
            source_ids=list(source_ids or []),
            metadata=metadata or {},
        )
        self.database.upsert(
            "eval_candidates",
            {
                "eval_candidate_id": candidate.eval_candidate_id,
                "scenario": candidate.scenario,
                "target_system": candidate.target_system,
                "expected_behavior": candidate.expected_behavior,
                "source_ids_json": dump_json(candidate.source_ids),
                "metadata_json": dump_json(candidate.metadata),
                "created_at": candidate.created_at,
            },
            conflict_columns="eval_candidate_id",
            immutable_columns=["created_at"],
        )
        return candidate
