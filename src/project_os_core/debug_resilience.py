from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .database import dump_json
from .models import EvalRunStatus

_PROOF_STALE_AFTER_DAYS = 14


def scan_debug_orphans(services, *, limit: int = 50) -> dict[str, Any]:
    payload = _scan_artifact_consistency(services, limit=limit)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def build_resilience_report(services, *, limit: int = 20) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    pressure = _build_debug_pressure(services)
    crash_consistency = _scan_artifact_consistency(services, limit=limit)
    proof_freshness = _build_proof_freshness(services, now=now, limit=limit)
    repairability = _build_repairability(crash_consistency=crash_consistency, proof_freshness=proof_freshness)
    status = _merge_statuses(
        (
            pressure.get("status"),
            crash_consistency.get("status"),
            proof_freshness.get("status"),
            repairability.get("status"),
        )
    )
    return {
        "generated_at": now.isoformat(),
        "status": status,
        "debug_pressure": pressure,
        "crash_consistency": crash_consistency,
        "proof_freshness": proof_freshness,
        "repairability": repairability,
    }


def reconcile_debug_state(services, *, repair: bool = False, limit: int = 50) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    orphan_scan = _scan_artifact_consistency(services, limit=limit)
    proof_freshness = _build_proof_freshness(services, now=datetime.now(timezone.utc), limit=limit)
    actions: list[dict[str, Any]] = []
    repair_applied_count = 0
    manual_followup_count = 0

    for category in orphan_scan.get("categories", []):
        if not isinstance(category, dict):
            continue
        for item in category.get("missing_items", []):
            if not isinstance(item, dict):
                continue
            table_name = str(category.get("table_name") or "")
            entity_id = str(item.get("entity_id") or "")
            if not repair:
                actions.append(
                    {
                        "kind": "missing_artifact",
                        "table_name": table_name,
                        "entity_id": entity_id,
                        "repair_applied": False,
                    }
                )
                continue
            if table_name == "dead_letter_records":
                _mark_dead_letter_artifact_missing(services, dead_letter_id=entity_id, repaired_at=now)
                repair_applied_count += 1
            elif table_name == "debug_replay_runs":
                _mark_debug_replay_artifact_missing(services, replay_id=entity_id, repaired_at=now)
                repair_applied_count += 1
            else:
                manual_followup_count += 1
            actions.append(
                {
                    "kind": "missing_artifact",
                    "table_name": table_name,
                    "entity_id": entity_id,
                    "repair_applied": table_name in {"dead_letter_records", "debug_replay_runs"},
                }
            )
        manual_followup_count += int(category.get("orphan_count") or 0)

    for item in proof_freshness.get("stale_items", []):
        if not isinstance(item, dict):
            continue
        incident_id = str(item.get("incident_id") or "")
        if not repair:
            actions.append(
                {
                    "kind": "stale_proof",
                    "incident_id": incident_id,
                    "reason": str(item.get("reason") or ""),
                    "repair_applied": False,
                }
            )
            continue
        _mark_incident_needs_reverification(
            services,
            incident_id=incident_id,
            reason=str(item.get("reason") or "proof_stale"),
            repaired_at=now,
        )
        repair_applied_count += 1
        actions.append(
            {
                "kind": "stale_proof",
                "incident_id": incident_id,
                "reason": str(item.get("reason") or ""),
                "repair_applied": True,
            }
        )

    has_actionable_items = bool(actions) or manual_followup_count > 0
    report = {
        "generated_at": now,
        "status": "attention" if (has_actionable_items and not repair) or manual_followup_count > 0 else "ok",
        "repair_requested": repair,
        "repair_applied_count": repair_applied_count,
        "manual_followup_count": manual_followup_count,
        "actions": actions[: max(1, int(limit))],
        "orphan_scan": orphan_scan,
        "proof_freshness": proof_freshness,
    }
    artifact_path = _write_resilience_report(services, stem="reconcile", payload=report)
    report["artifact_path"] = artifact_path
    services.journal.append(
        "debug_reconcile_completed",
        "debug_resilience",
        {
            "repair_requested": repair,
            "repair_applied_count": repair_applied_count,
            "manual_followup_count": manual_followup_count,
            "artifact_path": artifact_path,
        },
    )
    return report


def _build_debug_pressure(services) -> dict[str, Any]:
    operator_delivery_row = services.database.fetchone(
        """
        SELECT COUNT(*) AS item_count
        FROM api_run_operator_deliveries
        WHERE status = 'pending'
        """
    )
    pending_operator_deliveries = int((operator_delivery_row["item_count"] if operator_delivery_row else 0) or 0)
    running_replays = _count_by_status(services, table_name="debug_replay_runs", status="running")
    running_evals = _count_by_status(services, table_name="eval_runs", status=EvalRunStatus.RUNNING.value)
    active_quarantines = _count_by_status(services, table_name="output_quarantine_records", status="active")
    operator_delivery_limit = max(1, int(getattr(services.config.execution_policy, "operator_delivery_max_pending", 64)))
    attention_threshold = max(1, int(operator_delivery_limit * 0.75))
    should_shed_debug_work = pending_operator_deliveries >= operator_delivery_limit
    suggested_actions: list[str] = []
    status = "ok"
    if should_shed_debug_work:
        status = "breach"
        suggested_actions.append("Suspendre les nouveaux replays et grosses evals jusqu'au retour du backlog live sous le seuil.")
    elif pending_operator_deliveries >= attention_threshold or running_replays > 2 or running_evals > 0:
        status = "attention"
        suggested_actions.append("Laisser le live prioritaire et limiter les jobs debug lourds aux besoins de triage reel.")
    if active_quarantines > 0:
        suggested_actions.append("Traiter les quarantines actives avant d'empiler de nouveaux lots de debug.")
    return {
        "status": status,
        "pending_operator_deliveries": pending_operator_deliveries,
        "operator_delivery_limit": operator_delivery_limit,
        "attention_threshold": attention_threshold,
        "running_debug_replays": running_replays,
        "running_eval_runs": running_evals,
        "active_quarantines": active_quarantines,
        "should_shed_debug_work": should_shed_debug_work,
        "suggested_actions": suggested_actions,
    }


def _scan_artifact_consistency(services, *, limit: int) -> dict[str, Any]:
    categories = [
        _scan_explicit_artifact_table(
            services,
            table_name="dead_letter_records",
            id_column="dead_letter_id",
            path_column="artifact_path",
            root=services.paths.api_runs_root / "operator_delivery_dead_letters",
            limit=limit,
        ),
        _scan_explicit_artifact_table(
            services,
            table_name="debug_replay_runs",
            id_column="replay_id",
            path_column="artifact_path",
            root=services.paths.runtime_root / "debug_replay" / "runs",
            limit=limit,
        ),
        _scan_deterministic_artifact_table(
            services,
            table_name="incident_records",
            id_column="incident_id",
            root=services.paths.runtime_root / "incidents",
            limit=limit,
        ),
        _scan_deterministic_artifact_table(
            services,
            table_name="eval_cases",
            id_column="eval_case_id",
            root=services.paths.runtime_root / "evals" / "cases",
            limit=limit,
        ),
        _scan_deterministic_artifact_table(
            services,
            table_name="eval_runs",
            id_column="eval_run_id",
            root=services.paths.runtime_root / "evals" / "runs",
            limit=limit,
        ),
    ]
    missing_db_artifact_count = sum(int(item.get("missing_count") or 0) for item in categories)
    orphan_artifact_count = sum(int(item.get("orphan_count") or 0) for item in categories)
    if missing_db_artifact_count > 0:
        status = "breach"
    elif orphan_artifact_count > 0:
        status = "attention"
    else:
        status = "ok"
    return {
        "status": status,
        "missing_db_artifact_count": missing_db_artifact_count,
        "orphan_artifact_count": orphan_artifact_count,
        "categories": categories,
    }


def _scan_explicit_artifact_table(
    services,
    *,
    table_name: str,
    id_column: str,
    path_column: str,
    root: Path,
    limit: int,
) -> dict[str, Any]:
    rows = services.database.fetchall(
        f"""
        SELECT {id_column} AS entity_id, {path_column} AS artifact_path
        FROM {table_name}
        """
    )
    referenced_paths: set[str] = set()
    missing_items: list[dict[str, Any]] = []
    for row in rows:
        artifact_path = str(row["artifact_path"] or "").strip()
        if not artifact_path:
            continue
        normalized_path = _normalize_path(artifact_path)
        referenced_paths.add(normalized_path)
        if not Path(artifact_path).exists():
            missing_items.append(
                {
                    "entity_id": str(row["entity_id"]),
                    "artifact_path": artifact_path,
                }
            )
    orphan_items = _orphan_files(root=root, referenced_paths=referenced_paths, limit=limit)
    return {
        "key": table_name,
        "table_name": table_name,
        "root": str(root),
        "missing_count": len(missing_items),
        "orphan_count": len(orphan_items),
        "missing_items": missing_items[: max(1, int(limit))],
        "orphan_items": orphan_items,
    }


def _scan_deterministic_artifact_table(
    services,
    *,
    table_name: str,
    id_column: str,
    root: Path,
    limit: int,
) -> dict[str, Any]:
    rows = services.database.fetchall(
        f"""
        SELECT {id_column} AS entity_id
        FROM {table_name}
        """
    )
    referenced_paths: set[str] = set()
    missing_items: list[dict[str, Any]] = []
    for row in rows:
        entity_id = str(row["entity_id"])
        artifact_path = root / f"{entity_id}.json"
        normalized_path = _normalize_path(artifact_path)
        referenced_paths.add(normalized_path)
        if not artifact_path.exists():
            missing_items.append(
                {
                    "entity_id": entity_id,
                    "artifact_path": str(artifact_path),
                }
            )
    orphan_items = _orphan_files(root=root, referenced_paths=referenced_paths, limit=limit)
    return {
        "key": table_name,
        "table_name": table_name,
        "root": str(root),
        "missing_count": len(missing_items),
        "orphan_count": len(orphan_items),
        "missing_items": missing_items[: max(1, int(limit))],
        "orphan_items": orphan_items,
    }


def _orphan_files(*, root: Path, referenced_paths: set[str], limit: int) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    candidates = sorted(root.glob("*.json"), key=lambda item: item.name)
    orphans: list[dict[str, Any]] = []
    for item in candidates:
        normalized_path = _normalize_path(item)
        if normalized_path in referenced_paths:
            continue
        orphans.append({"artifact_path": str(item)})
    return orphans[: max(1, int(limit))]


def _build_proof_freshness(services, *, now: datetime, limit: int) -> dict[str, Any]:
    cutoff = now - timedelta(days=_PROOF_STALE_AFTER_DAYS)
    rows = services.database.fetchall(
        """
        SELECT incident_id, status, latest_eval_run_id, metadata_json, verification_refs_json, updated_at
        FROM incident_records
        WHERE status IN ('verified', 'closed')
        ORDER BY updated_at DESC
        """
    )
    stale_items: list[dict[str, Any]] = []
    for row in rows:
        eval_run_id = str(row["latest_eval_run_id"] or "").strip()
        metadata = _loads(row["metadata_json"], {})
        reason = ""
        if not eval_run_id:
            verification_refs = _loads(row["verification_refs_json"], [])
            if not _loads_reference_list(verification_refs):
                reason = "missing_verification_reference"
        else:
            eval_row = services.database.fetchone(
                "SELECT updated_at, status FROM eval_runs WHERE eval_run_id = ?",
                (eval_run_id,),
            )
            if eval_row is None:
                reason = "missing_eval_run"
            else:
                updated_at = _parse_datetime(str(eval_row["updated_at"] or ""))
                if updated_at is None or updated_at < cutoff:
                    reason = "proof_stale"
                elif str(eval_row["status"] or "") != EvalRunStatus.PASSED.value:
                    reason = "verification_not_passed"
        if reason:
            stale_items.append(
                {
                    "incident_id": str(row["incident_id"]),
                    "status": str(row["status"] or ""),
                    "latest_eval_run_id": eval_run_id or None,
                    "reason": reason,
                }
            )
    return {
        "status": "attention" if stale_items else "ok",
        "stale_incident_count": len(stale_items),
        "stale_after_days": _PROOF_STALE_AFTER_DAYS,
        "stale_items": stale_items[: max(1, int(limit))],
    }


def _build_repairability(*, crash_consistency: dict[str, Any], proof_freshness: dict[str, Any]) -> dict[str, Any]:
    missing_artifacts = int(crash_consistency.get("missing_db_artifact_count") or 0)
    orphan_artifacts = int(crash_consistency.get("orphan_artifact_count") or 0)
    stale_proofs = int(proof_freshness.get("stale_incident_count") or 0)
    actionable_count = missing_artifacts + orphan_artifacts + stale_proofs
    status = "attention" if actionable_count > 0 else "ok"
    return {
        "status": status,
        "actionable_count": actionable_count,
        "commands": [
            "project-os debug orphan-scan",
            "project-os debug reconcile",
            "project-os debug reconcile --repair",
            "project-os observability doctor --repair",
        ],
    }


def _mark_dead_letter_artifact_missing(services, *, dead_letter_id: str, repaired_at: str) -> None:
    row = services.database.fetchone(
        "SELECT metadata_json FROM dead_letter_records WHERE dead_letter_id = ?",
        (dead_letter_id,),
    )
    metadata = _loads(row["metadata_json"] if row else None, {})
    repair_flags = set(_loads_reference_list(metadata.get("repair_flags")))
    repair_flags.add("artifact_missing")
    metadata["repair_flags"] = sorted(repair_flags)
    metadata["artifact_state"] = "missing"
    metadata["last_reconcile_at"] = repaired_at
    services.database.execute(
        """
        UPDATE dead_letter_records
        SET metadata_json = ?, updated_at = ?
        WHERE dead_letter_id = ?
        """,
        (dump_json(metadata), repaired_at, dead_letter_id),
    )


def _mark_debug_replay_artifact_missing(services, *, replay_id: str, repaired_at: str) -> None:
    row = services.database.fetchone(
        "SELECT metadata_json FROM debug_replay_runs WHERE replay_id = ?",
        (replay_id,),
    )
    metadata = _loads(row["metadata_json"] if row else None, {})
    repair_flags = set(_loads_reference_list(metadata.get("repair_flags")))
    repair_flags.add("artifact_missing")
    metadata["repair_flags"] = sorted(repair_flags)
    metadata["artifact_state"] = "missing"
    metadata["last_reconcile_at"] = repaired_at
    services.database.execute(
        """
        UPDATE debug_replay_runs
        SET metadata_json = ?, updated_at = ?
        WHERE replay_id = ?
        """,
        (dump_json(metadata), repaired_at, replay_id),
    )


def _mark_incident_needs_reverification(services, *, incident_id: str, reason: str, repaired_at: str) -> None:
    row = services.database.fetchone(
        "SELECT metadata_json FROM incident_records WHERE incident_id = ?",
        (incident_id,),
    )
    metadata = _loads(row["metadata_json"] if row else None, {})
    repair_flags = set(_loads_reference_list(metadata.get("repair_flags")))
    repair_flags.add("proof_stale")
    metadata["repair_flags"] = sorted(repair_flags)
    metadata["proof_state"] = "needs_reverification"
    metadata["proof_state_reason"] = reason
    metadata["proof_stale_detected_at"] = repaired_at
    metadata["last_reconcile_at"] = repaired_at
    services.database.execute(
        """
        UPDATE incident_records
        SET metadata_json = ?, updated_at = ?
        WHERE incident_id = ?
        """,
        (dump_json(metadata), repaired_at, incident_id),
    )


def _write_resilience_report(services, *, stem: str, payload: dict[str, Any]) -> str:
    folder = services.path_policy.ensure_allowed_write(services.paths.runtime_root / "debug_system" / "reports")
    folder.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = services.path_policy.ensure_allowed_write(folder / f"{stem}_{suffix}.json")
    destination.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    return str(destination)


def _count_by_status(services, *, table_name: str, status: str) -> int:
    row = services.database.fetchone(
        f"SELECT COUNT(*) AS item_count FROM {table_name} WHERE status = ?",
        (status,),
    )
    return int((row["item_count"] if row else 0) or 0)


def _normalize_path(path: str | Path) -> str:
    return str(Path(path).resolve(strict=False)).lower()


def _loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def _loads_reference_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _parse_datetime(value: str) -> datetime | None:
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
