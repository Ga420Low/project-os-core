from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .gateway.discord_facade_smoke import (
    DEFAULT_POLICY_PATH,
    DEFAULT_SMOKE_ANTHROPIC_MODEL,
    manual_acceptance_checks,
    run_smoke_suite_isolated,
    scenario_ids_for_layers,
)

_MANUAL_STATUS_VALUES = {"pass", "fail", "false_positive", "pending"}


def build_discord_debug_audit_report(
    services,
    *,
    report_path: str | None = None,
    previous_report_path: str | None = None,
    manual_status_path: str | None = None,
    freeze_lifted: bool = False,
    run_live: bool = False,
    layers: tuple[str, ...] = ("smoke", "persona"),
    allow_missing_anthropic: bool = False,
    anthropic_model: str = DEFAULT_SMOKE_ANTHROPIC_MODEL,
    policy_path: str | None = None,
    runtime_base_dir: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    live_report: dict[str, Any] | None = None
    current_report_path = _resolve_existing_report_path(services, report_path=report_path)

    if run_live:
        current_report_path, live_report = _run_live_audit_suite(
            services,
            layers=layers,
            allow_missing_anthropic=allow_missing_anthropic,
            anthropic_model=anthropic_model,
            policy_path=policy_path,
            runtime_base_dir=runtime_base_dir,
        )

    current_report = live_report or _load_report(current_report_path)
    baseline_path = _resolve_previous_report_path(
        services,
        current_report_path=current_report_path,
        previous_report_path=previous_report_path,
    )
    previous_report = _load_report(baseline_path)
    manual_bundle = _load_manual_status_bundle(manual_status_path)
    manual_results = _build_manual_results(manual_bundle=manual_bundle)
    scenario_results = _build_scenario_results(
        current_report=current_report,
        previous_report=previous_report,
        scenario_overrides=manual_bundle["scenario_overrides"],
        limit=limit,
    )

    prerequisites: list[str] = []
    if not freeze_lifted:
        prerequisites.append("freeze_not_lifted")
    if current_report is None:
        prerequisites.append("no_automated_report")
    if manual_results["pending_count"] > 0:
        prerequisites.append("manual_acceptance_pending")

    outcome_counts = _count_outcomes(scenario_results)
    audit_status = _determine_audit_status(
        prerequisites=prerequisites,
        scenario_results=scenario_results,
        manual_results=manual_results,
    )
    decision = _determine_decision(audit_status)
    report = {
        "generated_at": generated_at,
        "status": audit_status,
        "decision": decision,
        "scope_guard": {
            "audit_only": True,
            "bot_or_app_modified": False,
            "freeze_lifted": freeze_lifted,
        },
        "summary": {
            "automated_scenario_count": len(scenario_results),
            "manual_check_count": len(manual_results["checks"]),
            "pass_count": outcome_counts["PASS"],
            "fail_count": outcome_counts["FAIL"],
            "regression_count": outcome_counts["REGRESSION"],
            "false_positive_count": outcome_counts["FALSE_POSITIVE"],
            "skip_count": outcome_counts["SKIP"],
            "manual_fail_count": manual_results["fail_count"],
            "manual_pending_count": manual_results["pending_count"],
        },
        "prerequisites": prerequisites,
        "current_report_path": str(current_report_path) if current_report_path else None,
        "previous_report_path": str(baseline_path) if baseline_path else None,
        "manual_status_path": manual_status_path,
        "run_live": run_live,
        "anthropic_model": anthropic_model if run_live else (current_report or {}).get("anthropic_model"),
        "automated_audit": {
            "source": "live_run" if run_live else "existing_report",
            "report_available": current_report is not None,
            "scenario_results": scenario_results,
        },
        "manual_acceptance": manual_results,
        "vision_axes": {
            "plumbing_visibility": _axis_status(
                scenario_results,
                {"natural_reply_hides_plumbing"},
            ),
            "provider_disclosure": _axis_status(
                scenario_results,
                {"provider_disclosure_on_demand"},
            ),
            "protected_flows": _axis_status(
                scenario_results,
                {
                    "deep_research_mode_selection_preserved",
                    "deep_research_explicit_mode_cost_gate",
                    "reasoning_escalation_requires_confirmation",
                    "pending_reasoning_approval_does_not_hijack_greeting",
                    "reasoning_rejection_reply_stays_visible",
                },
            ),
            "persona_and_facade": _axis_status(
                scenario_results,
                {
                    "persona_identity_not_generic",
                    "persona_challenges_big_bang",
                    "persona_serious_mode_is_net",
                    "persona_no_unnecessary_self_intro",
                    "persona_prefix_keeps_identity",
                    "persona_no_prompt_leakage",
                    "persona_no_corporate_bullshit",
                    "persona_presence_stays_useful",
                },
            ),
            "manual_live_acceptance": manual_results["status"],
        },
        "next_step": _build_next_step(audit_status=audit_status, prerequisites=prerequisites),
    }
    artifact_path = _write_discord_audit_report(services, payload=report)
    report["artifact_path"] = artifact_path
    services.journal.append(
        "debug_discord_audit_completed",
        "debug_discord_audit",
        {
            "status": audit_status,
            "decision": decision,
            "run_live": run_live,
            "freeze_lifted": freeze_lifted,
            "artifact_path": artifact_path,
            "current_report_path": str(current_report_path) if current_report_path else None,
        },
    )
    return report


def _resolve_existing_report_path(services, *, report_path: str | None) -> Path | None:
    if report_path:
        return Path(report_path).resolve(strict=False)
    candidate = services.paths.runtime_root / "reports" / "discord_facade_smoke" / "latest.json"
    return candidate if candidate.exists() else None


def _resolve_previous_report_path(
    services,
    *,
    current_report_path: Path | None,
    previous_report_path: str | None,
) -> Path | None:
    if previous_report_path:
        return Path(previous_report_path).resolve(strict=False)
    candidate = (
        services.paths.runtime_root
        / "reports"
        / "debug_system"
        / "discord_debug_audit"
        / "latest.json"
    )
    if not candidate.exists():
        return None
    if current_report_path is not None and _normalize_path(candidate) == _normalize_path(current_report_path):
        return None
    return candidate


def _run_live_audit_suite(
    services,
    *,
    layers: tuple[str, ...],
    allow_missing_anthropic: bool,
    anthropic_model: str,
    policy_path: str | None,
    runtime_base_dir: str | None,
) -> tuple[Path, dict[str, Any]]:
    selected_layers = layers or ("smoke", "persona")
    scenario_ids = scenario_ids_for_layers(selected_layers)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_dir = (
        Path(runtime_base_dir).resolve(strict=False)
        if runtime_base_dir
        else services.paths.runtime_root / "debug_system" / "discord_audit_runs" / timestamp
    )
    base_dir.mkdir(parents=True, exist_ok=True)
    report = run_smoke_suite_isolated(
        scenario_ids=scenario_ids,
        policy_path=Path(policy_path or DEFAULT_POLICY_PATH).resolve(strict=False),
        actor_id="debug_discord_audit",
        channel="discord",
        surface="discord",
        allow_missing_anthropic=allow_missing_anthropic,
        root_dir=base_dir,
        anthropic_model=anthropic_model,
    )
    return Path(str(report["report_path"])).resolve(strict=False), report


def _load_report(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_manual_status_bundle(path: str | None) -> dict[str, Any]:
    bundle = {
        "checks": {},
        "scenario_overrides": {},
    }
    if not path:
        return bundle
    payload_path = Path(path).resolve(strict=False)
    if not payload_path.exists():
        return bundle
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return bundle
    if not isinstance(payload, dict):
        return bundle
    manual_checks = payload.get("manual_checks")
    if isinstance(manual_checks, list):
        for item in manual_checks:
            if not isinstance(item, dict):
                continue
            check_id = str(item.get("check_id") or "").strip()
            status = str(item.get("status") or "").strip().lower()
            if not check_id or status not in _MANUAL_STATUS_VALUES:
                continue
            bundle["checks"][check_id] = {
                "status": status,
                "notes": str(item.get("notes") or "").strip() or None,
            }
    scenario_overrides = payload.get("scenario_overrides")
    if isinstance(scenario_overrides, dict):
        for scenario_id, item in scenario_overrides.items():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status != "false_positive":
                continue
            bundle["scenario_overrides"][str(scenario_id)] = {
                "status": "false_positive",
                "notes": str(item.get("notes") or "").strip() or None,
            }
    return bundle


def _build_manual_results(*, manual_bundle: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    pending_count = 0
    fail_count = 0
    false_positive_count = 0
    for check in manual_acceptance_checks():
        check_id = str(check["check_id"])
        override = manual_bundle["checks"].get(check_id, {})
        status = str(override.get("status") or "pending")
        if status == "pending":
            pending_count += 1
        elif status == "fail":
            fail_count += 1
        elif status == "false_positive":
            false_positive_count += 1
        checks.append(
            {
                "check_id": check_id,
                "title": check["title"],
                "status": status,
                "notes": override.get("notes"),
                "watch_for": list(check["watch_for"]),
            }
        )
    if fail_count > 0:
        status = "fail"
    elif pending_count > 0:
        status = "pending"
    elif false_positive_count > 0:
        status = "attention"
    else:
        status = "pass"
    return {
        "status": status,
        "pending_count": pending_count,
        "fail_count": fail_count,
        "false_positive_count": false_positive_count,
        "checks": checks,
    }


def _build_scenario_results(
    *,
    current_report: dict[str, Any] | None,
    previous_report: dict[str, Any] | None,
    scenario_overrides: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    if current_report is None:
        return []
    previous_lookup = _scenario_lookup(previous_report)
    rows: list[dict[str, Any]] = []
    for result in list(current_report.get("results") or [])[: max(1, int(limit))]:
        if not isinstance(result, dict):
            continue
        scenario_id = str(result.get("scenario_id") or "")
        if not scenario_id:
            continue
        passed = bool(result.get("passed"))
        skipped = bool(result.get("skipped"))
        errors = [str(item) for item in list(result.get("errors") or [])]
        outcome = _classify_scenario_outcome(
            scenario_id=scenario_id,
            passed=passed,
            skipped=skipped,
            previous_result=previous_lookup.get(scenario_id),
            override=scenario_overrides.get(scenario_id),
        )
        rows.append(
            {
                "scenario_id": scenario_id,
                "description": str(result.get("description") or ""),
                "layer": str(result.get("layer") or ""),
                "outcome": outcome,
                "passed": passed,
                "skipped": skipped,
                "errors": errors,
                "notes": (scenario_overrides.get(scenario_id) or {}).get("notes"),
            }
        )
    return rows


def _scenario_lookup(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    rows = payload.get("results")
    if not isinstance(rows, list):
        rows = payload.get("automated_audit", {}).get("scenario_results")
    lookup: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return lookup
    for item in rows:
        if not isinstance(item, dict):
            continue
        scenario_id = str(item.get("scenario_id") or "")
        if not scenario_id:
            continue
        lookup[scenario_id] = item
    return lookup


def _classify_scenario_outcome(
    *,
    scenario_id: str,
    passed: bool,
    skipped: bool,
    previous_result: dict[str, Any] | None,
    override: dict[str, Any] | None,
) -> str:
    if override and str(override.get("status") or "").lower() == "false_positive":
        return "FALSE_POSITIVE"
    if skipped:
        return "SKIP"
    if passed:
        return "PASS"
    if previous_result is not None and _result_is_pass(previous_result):
        return "REGRESSION"
    return "FAIL"


def _result_is_pass(result: dict[str, Any]) -> bool:
    if "outcome" in result:
        return str(result.get("outcome") or "").upper() == "PASS"
    return bool(result.get("passed")) and not bool(result.get("skipped"))


def _count_outcomes(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"PASS": 0, "FAIL": 0, "REGRESSION": 0, "FALSE_POSITIVE": 0, "SKIP": 0}
    for row in rows:
        outcome = str(row.get("outcome") or "").upper()
        if outcome in counts:
            counts[outcome] += 1
    return counts


def _axis_status(rows: list[dict[str, Any]], scenario_ids: set[str]) -> str:
    matching = [row for row in rows if str(row.get("scenario_id") or "") in scenario_ids]
    if not matching:
        return "unverified"
    outcomes = {str(row.get("outcome") or "").upper() for row in matching}
    if "REGRESSION" in outcomes or "FAIL" in outcomes:
        return "fail"
    if outcomes <= {"SKIP"}:
        return "unverified"
    if "FALSE_POSITIVE" in outcomes:
        return "attention"
    return "pass"


def _determine_audit_status(
    *,
    prerequisites: list[str],
    scenario_results: list[dict[str, Any]],
    manual_results: dict[str, Any],
) -> str:
    outcomes = {str(row.get("outcome") or "").upper() for row in scenario_results}
    if "REGRESSION" in outcomes or "FAIL" in outcomes or manual_results["fail_count"] > 0:
        return "non_coherent"
    if prerequisites:
        return "inconclusive"
    return "coherent"


def _determine_decision(audit_status: str) -> str:
    if audit_status == "coherent":
        return "debug_live_discord_coherent_with_vision"
    if audit_status == "non_coherent":
        return "open_correction_pack"
    return "hold_freeze_and_finish_audit"


def _build_next_step(*, audit_status: str, prerequisites: list[str]) -> str:
    if audit_status == "coherent":
        return "Clore Pack 6 et ne toucher le debug live Discord que via un pack correctif explicite si une regression reapparait."
    if audit_status == "non_coherent":
        return "Ouvrir le pack supplementaire de correction du debug Discord borne par les scenarios FAIL/REGRESSION."
    if "no_automated_report" in prerequisites:
        return "Executer `project-os debug discord-audit --run-live --layer smoke --layer persona --allow-missing-anthropic` quand le chantier live est pret."
    if "manual_acceptance_pending" in prerequisites:
        return "Completer les checks manuels puis relancer `project-os debug discord-audit --manual-status-path ... --freeze-lifted`."
    if "freeze_not_lifted" in prerequisites:
        return "Attendre la levee explicite du freeze bot/app avant de conclure l'audit final."
    return "Completer les prerequis manquants puis relancer l'audit."


def _write_discord_audit_report(services, *, payload: dict[str, Any]) -> str:
    reports_root = services.path_policy.ensure_allowed_write(
        services.paths.runtime_root / "reports" / "debug_system" / "discord_debug_audit"
    )
    reports_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = services.path_policy.ensure_allowed_write(reports_root / f"{timestamp}.json")
    latest = services.path_policy.ensure_allowed_write(reports_root / "latest.json")
    rendered = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
    target.write_text(rendered, encoding="utf-8")
    latest.write_text(rendered, encoding="utf-8")
    return str(target)


def _normalize_path(path: Path) -> str:
    return str(path.resolve(strict=False)).replace("\\", "/").lower()
