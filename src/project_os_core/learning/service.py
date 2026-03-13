from __future__ import annotations

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
        self.database.execute(
            """
            INSERT OR REPLACE INTO decision_records(
                decision_record_id, status, scope, summary, source_run_id, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.decision_record_id,
                record.status.value,
                record.scope,
                record.summary,
                record.source_run_id,
                dump_json(record.metadata),
                record.created_at,
                record.updated_at,
            ),
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO learning_signals(
                signal_id, kind, severity, summary, source_ids_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.signal_id,
                signal.kind.value,
                signal.severity,
                signal.summary,
                dump_json(signal.source_ids),
                dump_json(signal.metadata),
                signal.created_at,
            ),
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO loop_signals(
                loop_signal_id, repeated_pattern, impacted_area, recommended_reset,
                source_ids_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.loop_signal_id,
                signal.repeated_pattern,
                signal.impacted_area,
                signal.recommended_reset,
                dump_json(signal.source_ids),
                dump_json(signal.metadata),
                signal.created_at,
            ),
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO noise_signals(
                noise_signal_id, run_id, reason, evidence_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                signal.noise_signal_id,
                signal.run_id,
                signal.reason,
                dump_json(signal.evidence),
                signal.created_at,
            ),
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO refresh_recommendations(
                refresh_recommendation_id, cause, context_to_reload_json, next_step,
                source_ids_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation.refresh_recommendation_id,
                recommendation.cause,
                dump_json(recommendation.context_to_reload),
                recommendation.next_step,
                dump_json(recommendation.source_ids),
                dump_json(recommendation.metadata),
                recommendation.created_at,
            ),
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO dataset_candidates(
                dataset_candidate_id, source_type, quality_score, export_ready,
                source_ids_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.dataset_candidate_id,
                candidate.source_type,
                candidate.quality_score,
                1 if candidate.export_ready else 0,
                dump_json(candidate.source_ids),
                dump_json(candidate.metadata),
                candidate.created_at,
            ),
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO eval_candidates(
                eval_candidate_id, scenario, target_system, expected_behavior,
                source_ids_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.eval_candidate_id,
                candidate.scenario,
                candidate.target_system,
                candidate.expected_behavior,
                dump_json(candidate.source_ids),
                dump_json(candidate.metadata),
                candidate.created_at,
            ),
        )
        return candidate
