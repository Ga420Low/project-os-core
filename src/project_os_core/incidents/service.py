from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import CanonicalDatabase, dump_json
from ..models import (
    IncidentRecord,
    IncidentSeverity,
    IncidentStatus,
    TraceEntityKind,
    TraceRelationKind,
    new_id,
    to_jsonable,
)
from ..paths import PathPolicy, ProjectPaths
from ..runtime.journal import LocalJournal

_TERMINAL_INCIDENT_STATUSES = {
    IncidentStatus.CLOSED.value,
    IncidentStatus.NON_REPRODUCIBLE.value,
}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    IncidentStatus.OPEN.value: {IncidentStatus.TRIAGED.value, IncidentStatus.NON_REPRODUCIBLE.value},
    IncidentStatus.TRIAGED.value: {
        IncidentStatus.REPRO_READY.value,
        IncidentStatus.FIX_IN_PROGRESS.value,
        IncidentStatus.NON_REPRODUCIBLE.value,
    },
    IncidentStatus.REPRO_READY.value: {
        IncidentStatus.FIX_IN_PROGRESS.value,
        IncidentStatus.NON_REPRODUCIBLE.value,
    },
    IncidentStatus.FIX_IN_PROGRESS.value: {
        IncidentStatus.REPRO_READY.value,
        IncidentStatus.VERIFIED.value,
        IncidentStatus.NON_REPRODUCIBLE.value,
    },
    IncidentStatus.VERIFIED.value: {
        IncidentStatus.CLOSED.value,
        IncidentStatus.FIX_IN_PROGRESS.value,
    },
    IncidentStatus.NON_REPRODUCIBLE.value: {IncidentStatus.TRIAGED.value},
    IncidentStatus.CLOSED.value: set(),
}


class IncidentService:
    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        paths: ProjectPaths,
        path_policy: PathPolicy,
    ) -> None:
        self.database = database
        self.journal = journal
        self.paths = paths
        self.path_policy = path_policy

    @staticmethod
    def _enum_value(value: Any) -> Any:
        return value.value if hasattr(value, "value") else value

    def create_incident(
        self,
        *,
        severity: IncidentSeverity | str,
        summary: str,
        symptom: str,
        root_cause_hypothesis: str | None = None,
        fix_summary: str | None = None,
        source_ids: list[str] | None = None,
        verification_refs: list[str] | None = None,
        correlation_id: str | None = None,
        run_id: str | None = None,
        mission_run_id: str | None = None,
        dispatch_id: str | None = None,
        channel_event_id: str | None = None,
        replay_id: str | None = None,
        dead_letter_id: str | None = None,
        eval_case_id: str | None = None,
        latest_eval_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: IncidentStatus | str = IncidentStatus.OPEN,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        normalized_severity = IncidentSeverity(
            severity.value if isinstance(severity, IncidentSeverity) else str(severity)
        )
        normalized_status = IncidentStatus(
            status.value if isinstance(status, IncidentStatus) else str(status)
        )
        incident = IncidentRecord(
            incident_id=new_id("incident"),
            severity=normalized_severity,
            status=normalized_status,
            summary=summary.strip(),
            symptom=symptom.strip(),
            root_cause_hypothesis=root_cause_hypothesis.strip() if root_cause_hypothesis else None,
            fix_summary=fix_summary.strip() if fix_summary else None,
            source_ids=list(source_ids or []),
            verification_refs=list(verification_refs or []),
            correlation_id=str(correlation_id or "").strip() or None,
            run_id=str(run_id or "").strip() or None,
            mission_run_id=str(mission_run_id or "").strip() or None,
            dispatch_id=str(dispatch_id or "").strip() or None,
            channel_event_id=str(channel_event_id or "").strip() or None,
            replay_id=str(replay_id or "").strip() or None,
            dead_letter_id=str(dead_letter_id or "").strip() or None,
            eval_case_id=str(eval_case_id or "").strip() or None,
            latest_eval_run_id=str(latest_eval_run_id or "").strip() or None,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        self._persist_incident(incident)
        self._write_artifact(incident)
        self.journal.append(
            "incident_created",
            "incidents",
            {
                "incident_id": incident.incident_id,
                "severity": str(self._enum_value(incident.severity)),
                "status": str(self._enum_value(incident.status)),
                "correlation_id": incident.correlation_id,
                "dead_letter_id": incident.dead_letter_id or "",
            },
        )
        if incident.dead_letter_id:
            self.database.record_trace_edge(
                parent_id=incident.dead_letter_id,
                parent_kind=TraceEntityKind.DEAD_LETTER.value,
                child_id=incident.incident_id,
                child_kind=TraceEntityKind.INCIDENT.value,
                relation=TraceRelationKind.CAUSED.value,
                metadata={"severity": str(self._enum_value(incident.severity))},
            )
        if incident.replay_id:
            self.database.record_trace_edge(
                parent_id=incident.replay_id,
                parent_kind=TraceEntityKind.DEBUG_REPLAY.value,
                child_id=incident.incident_id,
                child_kind=TraceEntityKind.INCIDENT.value,
                relation=TraceRelationKind.CAUSED.value,
                metadata={},
            )
        return self.get_incident(incident.incident_id)

    def create_from_dead_letter(
        self,
        *,
        dead_letter_id: str,
        severity: IncidentSeverity | str = IncidentSeverity.P1,
        summary: str | None = None,
        symptom: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM dead_letter_records WHERE dead_letter_id = ?",
            (dead_letter_id,),
        )
        if row is None:
            raise KeyError(f"Unknown dead letter: {dead_letter_id}")
        dead_letter_metadata = self._loads(row["metadata_json"], {})
        return self.create_incident(
            severity=severity,
            summary=summary or f"Incident derive du dead letter {row['domain']}",
            symptom=symptom or str(row["error_message"] or row["domain"] or "Dead letter actif"),
            source_ids=[str(row["dead_letter_id"]), str(row["source_entity_id"])],
            correlation_id=str(row["correlation_id"]) if row["correlation_id"] else None,
            run_id=str(row["run_id"]) if row["run_id"] else None,
            mission_run_id=str(row["mission_run_id"]) if row["mission_run_id"] else None,
            dispatch_id=str(row["dispatch_id"]) if row["dispatch_id"] else None,
            channel_event_id=str(row["channel_event_id"]) if row["channel_event_id"] else None,
            dead_letter_id=str(row["dead_letter_id"]),
            metadata={
                **dead_letter_metadata,
                **dict(metadata or {}),
                "source_dead_letter_domain": str(row["domain"]),
                "source_entity_kind": str(row["source_entity_kind"]),
            },
        )

    def list_incidents(
        self,
        *,
        status: IncidentStatus | str | None = None,
        severity: IncidentSeverity | str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status.value if isinstance(status, IncidentStatus) else str(status))
        if severity:
            clauses.append("severity = ?")
            params.append(severity.value if isinstance(severity, IncidentSeverity) else str(severity))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.fetchall(
            f"""
            SELECT *
            FROM incident_records
            {where_sql}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (*params, max(1, int(limit))),
        )
        items = [self._row_to_payload(row) for row in rows]
        return {
            "count": len(items),
            "items": items,
            "status": str(self._enum_value(status)) if status else None,
            "severity": str(self._enum_value(severity)) if severity else None,
        }

    def get_incident(self, incident_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM incident_records WHERE incident_id = ?",
            (incident_id,),
        )
        if row is None:
            raise KeyError(f"Unknown incident: {incident_id}")
        return self._row_to_payload(row)

    def update_incident_status(
        self,
        *,
        incident_id: str,
        status: IncidentStatus | str,
        fix_summary: str | None = None,
        root_cause_hypothesis: str | None = None,
        verification_refs: list[str] | None = None,
        latest_eval_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM incident_records WHERE incident_id = ?",
            (incident_id,),
        )
        if row is None:
            raise KeyError(f"Unknown incident: {incident_id}")
        if isinstance(status, IncidentStatus):
            next_status = status
        else:
            next_status = IncidentStatus(str(status))
        current_status = str(row["status"])
        if next_status.value != current_status and next_status.value not in _ALLOWED_TRANSITIONS[current_status]:
            raise ValueError(f"Invalid incident transition: {current_status} -> {next_status.value}")
        current_refs = self._loads(row["verification_refs_json"], [])
        merged_refs = list(dict.fromkeys([*current_refs, *list(verification_refs or [])]))
        eval_run_id = str(latest_eval_run_id or row["latest_eval_run_id"] or "").strip() or None
        if next_status.value in {IncidentStatus.VERIFIED.value, IncidentStatus.CLOSED.value} and not (merged_refs or eval_run_id):
            raise ValueError("verified/closed incidents require verification_refs or latest_eval_run_id")
        if next_status.value in {IncidentStatus.VERIFIED.value, IncidentStatus.CLOSED.value} and eval_run_id:
            eval_row = self.database.fetchone(
                "SELECT status FROM eval_runs WHERE eval_run_id = ?",
                (eval_run_id,),
            )
            if eval_row is None:
                raise ValueError(f"Unknown eval run: {eval_run_id}")
            if str(eval_row["status"]) != "passed":
                raise ValueError(f"eval run must be passed before verification: {eval_run_id}")
        current_metadata = self._loads(row["metadata_json"], {})
        current_metadata.update(metadata or {})
        resolved_at = str(row["resolved_at"]) if row["resolved_at"] else None
        if next_status.value in _TERMINAL_INCIDENT_STATUSES or next_status.value == IncidentStatus.VERIFIED.value:
            resolved_at = datetime.now(timezone.utc).isoformat()
        updated_at = datetime.now(timezone.utc).isoformat()
        self.database.execute(
            """
            UPDATE incident_records
            SET status = ?, fix_summary = COALESCE(?, fix_summary),
                root_cause_hypothesis = COALESCE(?, root_cause_hypothesis),
                verification_refs_json = ?, latest_eval_run_id = COALESCE(?, latest_eval_run_id),
                metadata_json = ?, updated_at = ?, resolved_at = ?
            WHERE incident_id = ?
            """,
            (
                next_status.value,
                fix_summary,
                root_cause_hypothesis,
                dump_json(merged_refs),
                eval_run_id,
                dump_json(current_metadata),
                updated_at,
                resolved_at,
                incident_id,
            ),
        )
        if eval_run_id:
            self.database.record_trace_edge(
                parent_id=incident_id,
                parent_kind=TraceEntityKind.INCIDENT.value,
                child_id=eval_run_id,
                child_kind=TraceEntityKind.EVAL_RUN.value,
                relation=TraceRelationKind.VERIFIED_BY.value,
                metadata={"status": next_status.value},
            )
        self.journal.append(
            "incident_status_updated",
            "incidents",
            {
                "incident_id": incident_id,
                "previous_status": current_status,
                "status": next_status.value,
                "latest_eval_run_id": eval_run_id or "",
            },
        )
        incident = self.get_incident(incident_id)
        self._write_artifact_payload(incident)
        return incident

    def _persist_incident(self, incident: IncidentRecord) -> None:
        self.database.upsert(
            "incident_records",
            {
                "incident_id": incident.incident_id,
                "severity": str(self._enum_value(incident.severity)),
                "status": str(self._enum_value(incident.status)),
                "summary": incident.summary,
                "symptom": incident.symptom,
                "root_cause_hypothesis": incident.root_cause_hypothesis,
                "fix_summary": incident.fix_summary,
                "source_ids_json": dump_json(incident.source_ids),
                "verification_refs_json": dump_json(incident.verification_refs),
                "correlation_id": incident.correlation_id,
                "run_id": incident.run_id,
                "mission_run_id": incident.mission_run_id,
                "dispatch_id": incident.dispatch_id,
                "channel_event_id": incident.channel_event_id,
                "replay_id": incident.replay_id,
                "dead_letter_id": incident.dead_letter_id,
                "eval_case_id": incident.eval_case_id,
                "latest_eval_run_id": incident.latest_eval_run_id,
                "metadata_json": dump_json(incident.metadata),
                "created_at": incident.created_at,
                "updated_at": incident.updated_at,
                "resolved_at": incident.resolved_at,
            },
            conflict_columns="incident_id",
            immutable_columns=["created_at"],
        )

    def _write_artifact(self, incident: IncidentRecord) -> None:
        self._write_artifact_payload(to_jsonable(incident))

    def _write_artifact_payload(self, payload: dict[str, Any]) -> None:
        folder = self.path_policy.ensure_allowed_write(self.paths.runtime_root / "incidents")
        folder.mkdir(parents=True, exist_ok=True)
        destination = self.path_policy.ensure_allowed_write(folder / f"{payload['incident_id']}.json")
        destination.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _loads(raw: Any, default: Any) -> Any:
        if raw in (None, ""):
            return default
        try:
            return json.loads(str(raw))
        except Exception:
            return default

    def _row_to_payload(self, row) -> dict[str, Any]:
        return {
            "incident_id": str(row["incident_id"]),
            "severity": str(row["severity"]),
            "status": str(row["status"]),
            "summary": str(row["summary"]),
            "symptom": str(row["symptom"]),
            "root_cause_hypothesis": str(row["root_cause_hypothesis"]) if row["root_cause_hypothesis"] else None,
            "fix_summary": str(row["fix_summary"]) if row["fix_summary"] else None,
            "source_ids": self._loads(row["source_ids_json"], []),
            "verification_refs": self._loads(row["verification_refs_json"], []),
            "correlation_id": str(row["correlation_id"]) if row["correlation_id"] else None,
            "run_id": str(row["run_id"]) if row["run_id"] else None,
            "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
            "dispatch_id": str(row["dispatch_id"]) if row["dispatch_id"] else None,
            "channel_event_id": str(row["channel_event_id"]) if row["channel_event_id"] else None,
            "replay_id": str(row["replay_id"]) if row["replay_id"] else None,
            "dead_letter_id": str(row["dead_letter_id"]) if row["dead_letter_id"] else None,
            "eval_case_id": str(row["eval_case_id"]) if row["eval_case_id"] else None,
            "latest_eval_run_id": str(row["latest_eval_run_id"]) if row["latest_eval_run_id"] else None,
            "metadata": self._loads(row["metadata_json"], {}),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "resolved_at": str(row["resolved_at"]) if row["resolved_at"] else None,
        }
