from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import (
    DeadLetterStatus,
    DebugReplayStatus,
    EvalRunStatus,
    IncidentStatus,
    OutputQuarantineStatus,
)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    key: str
    table_name: str
    timestamp_column: str
    ttl_days: int
    privacy_view: str
    allowed_surfaces: tuple[str, ...]
    description: str
    where_sql: str | None = None


_CORRELATION_TABLES: tuple[tuple[str, str], ...] = (
    ("channel_events", "channel_events"),
    ("gateway_dispatch_results", "gateway_dispatch_results"),
    ("mission_intents", "mission_intents"),
    ("routing_decisions", "routing_decisions"),
    ("routing_decision_traces", "routing_decision_traces"),
    ("mission_runs", "mission_runs"),
)

_RETENTION_POLICIES: tuple[RetentionPolicy, ...] = (
    RetentionPolicy(
        key="output_quarantine",
        table_name="output_quarantine_records",
        timestamp_column="created_at",
        ttl_days=7,
        privacy_view="clean_only",
        allowed_surfaces=("debug_cli", "dashboard", "incident_artifact"),
        description="Sorties modele invalides conservees juste assez longtemps pour le triage et la preuve rouge.",
    ),
    RetentionPolicy(
        key="dead_letters",
        table_name="dead_letter_records",
        timestamp_column="updated_at",
        ttl_days=14,
        privacy_view="clean_only",
        allowed_surfaces=("debug_cli", "dashboard", "incident_artifact"),
        description="Dead letters de livraison et de runtime gardes pour replay et requeue.",
    ),
    RetentionPolicy(
        key="debug_replays",
        table_name="debug_replay_runs",
        timestamp_column="updated_at",
        ttl_days=14,
        privacy_view="clean_only",
        allowed_surfaces=("debug_cli", "dashboard"),
        description="Replays debug conserves localement avec leurs artefacts jusqu'au prochain cycle de verification.",
    ),
    RetentionPolicy(
        key="resolved_incidents",
        table_name="incident_records",
        timestamp_column="resolved_at",
        ttl_days=30,
        privacy_view="clean_only",
        allowed_surfaces=("debug_cli", "dashboard", "audit"),
        description="Incidents resolus gardes comme preuve locale, puis eligibles a purge.",
        where_sql="status IN ('verified', 'closed', 'non_reproducible')",
    ),
    RetentionPolicy(
        key="eval_runs",
        table_name="eval_runs",
        timestamp_column="updated_at",
        ttl_days=14,
        privacy_view="clean_only",
        allowed_surfaces=("debug_cli", "dashboard", "audit"),
        description="Runs d'eval gardes assez longtemps pour comparer les preuves vertes.",
    ),
)


def build_debug_system_report(services, *, limit: int = 8) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    correlation_spine = _build_correlation_spine(services)
    quarantine = _build_quarantine_health(services, now=now, limit=limit)
    replay_health = _build_replay_health(services, limit=limit)
    incident_health = _build_incident_health(services, limit=limit)
    eval_health = _build_eval_health(services, limit=limit)
    privacy_retention = _build_privacy_retention(services, now=now)
    gates = _build_gate_status(services)
    status = _merge_statuses(
        (
            correlation_spine.get("status"),
            quarantine.get("status"),
            replay_health.get("status"),
            incident_health.get("status"),
            eval_health.get("status"),
            privacy_retention.get("status"),
            gates.get("status"),
        )
    )
    return {
        "generated_at": now.isoformat(),
        "status": status,
        "summary": {
            "active_quarantines": int(quarantine.get("active_count") or 0),
            "failed_replays": int(replay_health.get("failed_count") or 0),
            "critical_open_incidents": int(incident_health.get("critical_open_count") or 0),
            "failed_eval_runs": int(eval_health.get("failed_or_mixed_count") or 0),
            "ttl_breach_count": int(privacy_retention.get("ttl_breach_count") or 0),
        },
        "correlation_spine": correlation_spine,
        "quarantine": quarantine,
        "replay_health": replay_health,
        "incident_health": incident_health,
        "eval_health": eval_health,
        "privacy_retention": privacy_retention,
        "gates": gates,
    }


def _build_correlation_spine(services) -> dict[str, Any]:
    coverage: list[dict[str, Any]] = []
    below_target: list[str] = []
    for table_name, label in _CORRELATION_TABLES:
        row = services.database.fetchone(
            f"""
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN correlation_id IS NOT NULL AND TRIM(correlation_id) <> '' THEN 1 ELSE 0 END) AS covered_count
            FROM {table_name}
            """
        )
        total_count = int((row["total_count"] if row else 0) or 0)
        covered_count = int((row["covered_count"] if row else 0) or 0)
        coverage_ratio = 1.0 if total_count <= 0 else covered_count / max(1, total_count)
        if total_count > 0 and coverage_ratio < 0.95:
            below_target.append(label)
        coverage.append(
            {
                "entity": label,
                "total_count": total_count,
                "covered_count": covered_count,
                "coverage_ratio": round(coverage_ratio, 4),
            }
        )
    min_ratio = min((float(item["coverage_ratio"]) for item in coverage), default=1.0)
    if min_ratio < 0.50:
        status = "breach"
    elif below_target:
        status = "attention"
    else:
        status = "ok"
    return {
        "status": status,
        "target_ratio": 0.95,
        "min_coverage_ratio": round(min_ratio, 4),
        "below_target": below_target,
        "coverage": coverage,
    }


def _build_quarantine_health(services, *, now: datetime, limit: int) -> dict[str, Any]:
    stale_cutoff = (now - timedelta(days=7)).isoformat()
    counts = _status_counts(services, table_name="output_quarantine_records")
    active_count = int(counts.get(OutputQuarantineStatus.ACTIVE.value, 0))
    stale_active_row = services.database.fetchone(
        """
        SELECT COUNT(*) AS stale_count
        FROM output_quarantine_records
        WHERE status = ? AND created_at < ?
        """,
        (OutputQuarantineStatus.ACTIVE.value, stale_cutoff),
    )
    stale_active_count = int((stale_active_row["stale_count"] if stale_active_row else 0) or 0)
    rows = services.database.fetchall(
        """
        SELECT quarantine_id, source_system, source_entity_kind, reason_code, status, created_at
        FROM output_quarantine_records
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    )
    status = "breach" if stale_active_count > 0 else ("attention" if active_count > 0 else "ok")
    return {
        "status": status,
        "active_count": active_count,
        "stale_active_count": stale_active_count,
        "status_counts": counts,
        "recent_items": [
            {
                "quarantine_id": str(row["quarantine_id"]),
                "source_system": str(row["source_system"] or ""),
                "source_entity_kind": str(row["source_entity_kind"] or ""),
                "reason_code": str(row["reason_code"] or ""),
                "status": str(row["status"] or ""),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ],
    }


def _build_replay_health(services, *, limit: int) -> dict[str, Any]:
    counts = _status_counts(services, table_name="debug_replay_runs")
    failed_count = int(counts.get(DebugReplayStatus.FAILED.value, 0))
    running_count = int(counts.get(DebugReplayStatus.RUNNING.value, 0))
    rows = services.database.fetchall(
        """
        SELECT replay_id, status, source_entity_kind, source_identifier, artifact_path, correlation_id, updated_at
        FROM debug_replay_runs
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    )
    status = "attention" if failed_count > 0 or running_count > 0 else "ok"
    return {
        "status": status,
        "failed_count": failed_count,
        "running_count": running_count,
        "status_counts": counts,
        "recent_replays": [
            {
                "replay_id": str(row["replay_id"]),
                "status": str(row["status"] or ""),
                "source_entity_kind": str(row["source_entity_kind"] or ""),
                "source_identifier": str(row["source_identifier"] or ""),
                "artifact_path": str(row["artifact_path"] or "") or None,
                "correlation_id": str(row["correlation_id"] or "") or None,
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ],
    }


def _build_incident_health(services, *, limit: int) -> dict[str, Any]:
    status_counts = _status_counts(services, table_name="incident_records")
    severity_rows = services.database.fetchall(
        """
        SELECT severity, COUNT(*) AS item_count
        FROM incident_records
        GROUP BY severity
        """
    )
    severity_counts = {str(row["severity"] or "unknown"): int(row["item_count"] or 0) for row in severity_rows}
    critical_open_row = services.database.fetchone(
        """
        SELECT COUNT(*) AS item_count
        FROM incident_records
        WHERE severity IN ('p0', 'p1') AND status NOT IN ('verified', 'closed')
        """
    )
    critical_open_count = int((critical_open_row["item_count"] if critical_open_row else 0) or 0)
    verification_gap_row = services.database.fetchone(
        """
        SELECT COUNT(*) AS item_count
        FROM incident_records
        WHERE status IN ('verified', 'closed')
          AND (
            (latest_eval_run_id IS NULL OR TRIM(latest_eval_run_id) = '')
            AND verification_refs_json = '[]'
          )
        """
    )
    verification_gap_count = int((verification_gap_row["item_count"] if verification_gap_row else 0) or 0)
    rows = services.database.fetchall(
        """
        SELECT incident_id, severity, status, summary, correlation_id, latest_eval_run_id, updated_at
        FROM incident_records
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    )
    openish_count = sum(
        int(status_counts.get(status_name, 0))
        for status_name in (
            IncidentStatus.OPEN.value,
            IncidentStatus.TRIAGED.value,
            IncidentStatus.REPRO_READY.value,
            IncidentStatus.FIX_IN_PROGRESS.value,
        )
    )
    if critical_open_count > 0 or verification_gap_count > 0:
        status = "breach"
    elif openish_count > 0:
        status = "attention"
    else:
        status = "ok"
    return {
        "status": status,
        "critical_open_count": critical_open_count,
        "verification_gap_count": verification_gap_count,
        "status_counts": status_counts,
        "severity_counts": severity_counts,
        "recent_incidents": [
            {
                "incident_id": str(row["incident_id"]),
                "severity": str(row["severity"] or ""),
                "status": str(row["status"] or ""),
                "summary": str(row["summary"] or ""),
                "correlation_id": str(row["correlation_id"] or "") or None,
                "latest_eval_run_id": str(row["latest_eval_run_id"] or "") or None,
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ],
    }


def _build_eval_health(services, *, limit: int) -> dict[str, Any]:
    case_rows = services.database.fetchall(
        """
        SELECT status, COUNT(*) AS item_count
        FROM eval_cases
        GROUP BY status
        """
    )
    case_status_counts = {str(row["status"] or "unknown"): int(row["item_count"] or 0) for row in case_rows}
    run_status_counts = _status_counts(services, table_name="eval_runs")
    failed_or_mixed_count = int(run_status_counts.get(EvalRunStatus.FAILED.value, 0)) + int(
        run_status_counts.get(EvalRunStatus.MIXED.value, 0)
    )
    rows = services.database.fetchall(
        """
        SELECT eval_run_id, suite_id, status, passed_count, failed_count, skipped_count, created_at
        FROM eval_runs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    )
    total_runs = sum(run_status_counts.values())
    status = "attention" if failed_or_mixed_count > 0 or total_runs == 0 else "ok"
    return {
        "status": status,
        "failed_or_mixed_count": failed_or_mixed_count,
        "total_run_count": total_runs,
        "case_status_counts": case_status_counts,
        "run_status_counts": run_status_counts,
        "recent_eval_runs": [
            {
                "eval_run_id": str(row["eval_run_id"]),
                "suite_id": str(row["suite_id"] or ""),
                "status": str(row["status"] or ""),
                "passed_count": int(row["passed_count"] or 0),
                "failed_count": int(row["failed_count"] or 0),
                "skipped_count": int(row["skipped_count"] or 0),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ],
    }


def _build_privacy_retention(services, *, now: datetime) -> dict[str, Any]:
    policies: list[dict[str, Any]] = []
    ttl_breach_count = 0
    over_ttl_items: list[dict[str, Any]] = []
    for policy in _RETENTION_POLICIES:
        where_sql = f"WHERE {policy.where_sql}" if policy.where_sql else ""
        total_row = services.database.fetchone(
            f"SELECT COUNT(*) AS item_count FROM {policy.table_name} {where_sql}"
        )
        cutoff = (now - timedelta(days=policy.ttl_days)).isoformat()
        ttl_clauses = [f"{policy.timestamp_column} IS NOT NULL", f"{policy.timestamp_column} < ?"]
        if policy.where_sql:
            ttl_clauses.insert(0, policy.where_sql)
        over_ttl_row = services.database.fetchone(
            f"SELECT COUNT(*) AS item_count FROM {policy.table_name} WHERE {' AND '.join(ttl_clauses)}",
            (cutoff,),
        )
        total_count = int((total_row["item_count"] if total_row else 0) or 0)
        over_ttl_count = int((over_ttl_row["item_count"] if over_ttl_row else 0) or 0)
        if over_ttl_count > 0:
            ttl_breach_count += over_ttl_count
            over_ttl_items.append(
                {
                    "key": policy.key,
                    "table_name": policy.table_name,
                    "over_ttl_count": over_ttl_count,
                    "ttl_days": policy.ttl_days,
                }
            )
        policies.append(
            {
                "key": policy.key,
                "table_name": policy.table_name,
                "ttl_days": policy.ttl_days,
                "privacy_view": policy.privacy_view,
                "allowed_surfaces": list(policy.allowed_surfaces),
                "description": policy.description,
                "total_count": total_count,
                "over_ttl_count": over_ttl_count,
            }
        )
    artifact_missing_count = _count_missing_artifacts(services)
    stale_proof_count = _count_stale_proofs(services, now=now)
    if ttl_breach_count > 0 or artifact_missing_count > 0:
        status = "breach"
    elif stale_proof_count > 0:
        status = "attention"
    else:
        status = "ok"
    return {
        "status": status,
        "ttl_breach_count": ttl_breach_count,
        "artifact_missing_count": artifact_missing_count,
        "stale_proof_count": stale_proof_count,
        "policies": policies,
        "over_ttl_items": over_ttl_items,
    }


def _build_gate_status(services) -> dict[str, Any]:
    privacy_guard_enabled = bool(services.config.execution_policy.privacy_guard_enabled)
    items = [
        {
            "gate": "structured_output_quarantine",
            "mode": "enforcing",
            "status": "ok",
            "note": "Les sorties structurees invalides sont mises en quarantine avant toute promotion.",
        },
        {
            "gate": "incident_closure_requires_proof",
            "mode": "enforcing",
            "status": "ok",
            "note": "Un incident ne peut pas etre verifie ou clos sans preuve de verification.",
        },
        {
            "gate": "privacy_guard",
            "mode": "enforcing",
            "status": "ok" if privacy_guard_enabled else "breach",
            "note": "Le guard privacy doit rester actif sur les surfaces live et debug.",
        },
        {
            "gate": "replay_required_for_p0_p1",
            "mode": "shadow",
            "status": "shadow",
            "note": "Le doctor audite la couverture replay sans encore bloquer tous les flux live.",
        },
        {
            "gate": "eval_case_required_for_bug_fix",
            "mode": "shadow",
            "status": "shadow",
            "note": "Le corpus d'evals est suivi, mais n'est pas encore un gate bloquant global.",
        },
        {
            "gate": "discord_live_debug_audit",
            "mode": "deferred_audit",
            "status": "deferred",
            "note": "Le debug live Discord en cours reste audite dans le pack final dedie.",
        },
    ]
    misconfigured_count = sum(1 for item in items if item["status"] == "breach")
    return {
        "status": "breach" if misconfigured_count > 0 else "ok",
        "enforcing_count": sum(1 for item in items if item["mode"] == "enforcing"),
        "shadow_count": sum(1 for item in items if item["mode"] == "shadow"),
        "deferred_count": sum(1 for item in items if item["mode"] == "deferred_audit"),
        "misconfigured_count": misconfigured_count,
        "items": items,
    }


def _status_counts(services, *, table_name: str) -> dict[str, int]:
    rows = services.database.fetchall(
        f"""
        SELECT status, COUNT(*) AS item_count
        FROM {table_name}
        GROUP BY status
        """
    )
    return {str(row["status"] or "unknown"): int(row["item_count"] or 0) for row in rows}


def _count_missing_artifacts(services) -> int:
    rows = services.database.fetchall(
        """
        SELECT artifact_path FROM dead_letter_records WHERE artifact_path IS NOT NULL AND TRIM(artifact_path) <> ''
        UNION ALL
        SELECT artifact_path FROM debug_replay_runs WHERE artifact_path IS NOT NULL AND TRIM(artifact_path) <> ''
        """
    )
    missing = 0
    for row in rows:
        artifact_path = Path(str(row["artifact_path"]))
        if not artifact_path.exists():
            missing += 1
    return missing


def _count_stale_proofs(services, *, now: datetime) -> int:
    cutoff = now - timedelta(days=14)
    rows = services.database.fetchall(
        """
        SELECT incident_id, latest_eval_run_id, status
        FROM incident_records
        WHERE status IN ('verified', 'closed')
        """
    )
    stale_count = 0
    for row in rows:
        eval_run_id = str(row["latest_eval_run_id"] or "").strip()
        if not eval_run_id:
            stale_count += 1
            continue
        eval_row = services.database.fetchone(
            "SELECT updated_at FROM eval_runs WHERE eval_run_id = ?",
            (eval_run_id,),
        )
        if eval_row is None:
            stale_count += 1
            continue
        updated_at = _safe_parse_datetime(str(eval_row["updated_at"] or ""))
        if updated_at is None or updated_at < cutoff:
            stale_count += 1
    return stale_count


def _safe_parse_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _merge_statuses(values: tuple[str | None, ...]) -> str:
    order = {"ok": 0, "attention": 1, "breach": 2}
    result = "ok"
    for value in values:
        normalized = str(value or "ok").strip().lower()
        if order.get(normalized, 0) > order.get(result, 0):
            result = normalized
    return result
