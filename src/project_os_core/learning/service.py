from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
)
from ..runtime.journal import LocalJournal


class LearningService:
    """Promotes durable project intelligence beyond raw memory storage."""

    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        memory: MemoryStore,
    ) -> None:
        self.database = database
        self.journal = journal
        self.memory = memory

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

        del objective
        bounded_limit = max(1, min(int(limit), 10))
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))).isoformat()
        decision_rows = self.database.fetchall(
            """
            SELECT scope, summary, status, created_at
            FROM decision_records
            WHERE (scope LIKE '%' || ? || '%' OR scope LIKE '%' || ? || '%')
              AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (mode, branch_name, cutoff, bounded_limit),
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

        learning_context = {
            "decisions": [
                {
                    "scope": str(row["scope"]),
                    "summary": str(row["summary"]),
                    "status": str(row["status"]),
                    "created_at": str(row["created_at"]),
                }
                for row in decision_rows
            ],
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
            f"{len(learning_context['high_severity_signals'])} high signals, "
            f"{len(learning_context['detected_loops'])} loops, "
            f"{len(learning_context['refresh_recommendations'])} refresh recommendations "
            f"in last {max(1, int(lookback_hours))}h."
        )
        return learning_context

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
