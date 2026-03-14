from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - dependency is declared in pyproject but may be absent in local dev until installed
    Anthropic = None
from openai import OpenAI

from .api_runs.service import REVIEWER_MODEL, TRANSLATOR_MODEL
from .models import BootstrapState, HealthSnapshot, new_id, to_jsonable
from .observability import write_health_snapshot
from .services import build_app_services


def bootstrap_environment(strict: bool = False) -> dict[str, object]:
    services = build_app_services()
    try:
        checks = _collect_checks(services, strict=strict)
        state = _bootstrap_state(services, checks, strict=strict)
        _persist_bootstrap_state(services, state)
        services.logger.log(
            "info",
            "bootstrap_completed",
            strict=strict,
            status=state.status,
            secret_mode=services.config.secret_config.mode,
        )
        return {
            "repo_root": str(services.config.repo_root),
            "bootstrap_state": to_jsonable(state),
            "secret_migration": {
                "repo_env_present": (services.config.repo_root / ".env").exists(),
                "local_fallback_path": str(services.secret_resolver.local_fallback_path),
            },
            "database": services.database.status(),
            "embedding_strategy": {
                "provider": services.embedding_strategy.provider,
                "model": services.embedding_strategy.model,
                "dimensions": services.embedding_strategy.dimensions,
                "quality": services.embedding_strategy.quality,
                "source": services.embedding_strategy.source,
            },
            "forbidden_zone": str(services.paths.archive_do_not_touch_root),
            "forbidden_zone_enforced": services.path_policy.is_forbidden(services.paths.archive_do_not_touch_root),
        }
    finally:
        services.close()


def doctor_report(strict: bool = False) -> dict[str, object]:
    services = build_app_services()
    try:
        checks = _collect_checks(services, strict=strict)
        state = _bootstrap_state(services, checks, strict=strict)
        payload = {
            "storage_config": {
                "runtime_root": str(services.paths.runtime_root),
                "memory_hot_root": str(services.paths.memory_hot_root),
                "memory_warm_root": str(services.paths.memory_warm_root),
                "archive_root": str(services.paths.archive_root),
                "archive_do_not_touch_root": str(services.paths.archive_do_not_touch_root),
                "local_secret_fallback_path": str(services.secret_resolver.local_fallback_path),
            },
            "database": services.database.status(),
            "embedding_strategy": {
                "provider": services.embedding_strategy.provider,
                "model": services.embedding_strategy.model,
                "dimensions": services.embedding_strategy.dimensions,
                "quality": services.embedding_strategy.quality,
                "source": services.embedding_strategy.source,
            },
            "path_policy": {
                "forbidden_zone_enforced": services.path_policy.is_forbidden(services.paths.archive_do_not_touch_root),
                "runtime_root_managed": services.path_policy.is_managed(services.paths.runtime_root),
            },
            "openmemory": {
                "db_path": str(services.paths.openmemory_db_path),
                "provider": "openai" if services.embedding_strategy.provider == "openai" else "synthetic",
                "model": services.embedding_strategy.model if services.embedding_strategy.provider == "openai" else "synthetic",
            },
            "secrets": services.secret_resolver.source_report(),
            "journal_file": str(services.paths.journal_file_path),
            "bootstrap_state": to_jsonable(state),
        }
        services.logger.log("info", "doctor_report_generated", strict=strict, status=state.status)
        if strict and not state.strict_ready:
            raise RuntimeError("doctor --strict failed")
        return payload
    finally:
        services.close()


def health_snapshot() -> dict[str, Any]:
    services = build_app_services()
    try:
        checks = _collect_checks(services, strict=False)
        state = _bootstrap_state(services, checks, strict=False)
        snapshot = write_health_snapshot(
            database=services.database,
            paths=services.paths,
            path_policy=services.path_policy,
            overall_status=state.status,
            payload={
                "database": services.database.status(),
                "embedding_strategy": {
                    "provider": services.embedding_strategy.provider,
                    "model": services.embedding_strategy.model,
                    "dimensions": services.embedding_strategy.dimensions,
                    "source": services.embedding_strategy.source,
                },
                "secrets": services.secret_resolver.source_report(),
                "bootstrap_state": to_jsonable(state),
            },
        )
        services.logger.log("info", "health_snapshot_written", snapshot_id=snapshot.snapshot_id, status=snapshot.overall_status)
        return to_jsonable(snapshot)
    finally:
        services.close()


def _collect_checks(services, *, strict: bool) -> dict[str, Any]:
    roots_status = {
        "runtime_root_exists": services.paths.runtime_root.exists(),
        "archive_root_exists": services.paths.archive_root.exists(),
        "do_not_touch_exists": services.paths.archive_do_not_touch_root.exists(),
        "do_not_touch_forbidden": services.path_policy.is_forbidden(services.paths.archive_do_not_touch_root),
        "journal_root_exists": services.paths.journal_file_path.parent.exists(),
    }
    secrets_report = services.secret_resolver.source_report()
    required_secrets_ok = all(item["available"] for item in secrets_report["required"].values())
    database_status = services.database.status()
    openai_probe = _probe_openai_access(services, strict=strict)
    anthropic_reviewer_probe = _probe_anthropic_access(
        services,
        strict=strict,
        capability="reviewer",
        model_name=REVIEWER_MODEL,
    )
    anthropic_translator_probe = _probe_anthropic_access(
        services,
        strict=strict,
        capability="translator",
        model_name=TRANSLATOR_MODEL,
    )
    return {
        "roots": roots_status,
        "database": database_status,
        "embedding_provider": services.embedding_strategy.provider,
        "openai_probe": openai_probe,
        "anthropic_reviewer_probe": anthropic_reviewer_probe,
        "anthropic_translator_probe": anthropic_translator_probe,
        "openmemory_db_exists": services.paths.openmemory_db_path.parent.exists(),
        "secrets": secrets_report,
        "required_secrets_ok": required_secrets_ok,
        "strict": strict,
    }


def _bootstrap_state(services, checks: dict[str, Any], *, strict: bool) -> BootstrapState:
    failures: list[str] = []
    warnings: list[str] = []

    if not checks["roots"]["runtime_root_exists"]:
        failures.append("runtime_root_missing")
    if not checks["roots"]["archive_root_exists"]:
        failures.append("archive_root_missing")
    if not checks["roots"]["do_not_touch_exists"]:
        failures.append("do_not_touch_missing")
    if not checks["roots"]["do_not_touch_forbidden"]:
        failures.append("do_not_touch_not_enforced")
    if not checks["database"]["db_path"]:
        failures.append("database_missing")
    if not checks["required_secrets_ok"]:
        failures.append("required_secret_missing")
    if checks["embedding_provider"] == "openai" and checks["openai_probe"]["ok"] is False:
        failures.append("openai_provider_invalid")
    if checks["anthropic_reviewer_probe"]["ok"] is False:
        failures.append("anthropic_reviewer_invalid")
    if checks["anthropic_translator_probe"]["ok"] is False:
        failures.append("anthropic_translator_invalid")
    if checks["secrets"]["infisical"]["binary_present"] is False:
        warnings.append("infisical_cli_missing")
    if checks["secrets"]["infisical"]["auth_mode"] == "user_session_fallback":
        warnings.append("infisical_user_session_fallback")
    if checks["secrets"]["mode"] == "infisical_required":
        if checks["secrets"]["infisical"]["resolution_ready"] is False:
            failures.append("infisical_not_ready")
        for secret_name, secret_state in checks["secrets"]["required"].items():
            if secret_state["available"] is False or secret_state["source"] != "infisical":
                failures.append(f"infisical_required_for_{secret_name}")

    status = "ready" if not failures else "blocked"
    strict_ready = not failures
    if strict and warnings and strict_ready:
        status = "degraded"

    return BootstrapState(
        bootstrap_state_id=new_id("bootstrap"),
        strict_ready=strict_ready,
        status=status,
        failures=failures,
        warnings=warnings,
        checks=checks,
        roots={
            "runtime_root": str(services.paths.runtime_root),
            "archive_root": str(services.paths.archive_root),
            "do_not_touch_root": str(services.paths.archive_do_not_touch_root),
            "health_snapshot_path": str(services.paths.health_snapshot_path),
            "bootstrap_state_path": str(services.paths.bootstrap_state_path),
        },
    )


def _probe_openai_access(services, *, strict: bool) -> dict[str, Any]:
    if services.embedding_strategy.provider != "openai":
        return {"ok": None, "skipped": True, "reason": "embedding_provider_not_openai"}

    if not strict:
        return {"ok": None, "skipped": True, "reason": "strict_probe_only"}

    try:
        key = services.secret_resolver.get_required("OPENAI_API_KEY")
        client = OpenAI(api_key=key)
        response = client.embeddings.create(
            input="project os strict health probe",
            model=services.embedding_strategy.model,
            dimensions=services.embedding_strategy.dimensions,
        )
        return {
            "ok": True,
            "skipped": False,
            "provider": "openai",
            "model": services.embedding_strategy.model,
            "vector_length": len(response.data[0].embedding),
        }
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "provider": "openai",
            "model": services.embedding_strategy.model,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _probe_anthropic_access(
    services,
    *,
    strict: bool,
    capability: str,
    model_name: str,
) -> dict[str, Any]:
    if not strict:
        return {
            "ok": None,
            "skipped": True,
            "provider": "anthropic",
            "capability": capability,
            "model": model_name,
            "reason": "strict_probe_only",
        }

    if Anthropic is None:
        return {
            "ok": False,
            "skipped": False,
            "provider": "anthropic",
            "capability": capability,
            "model": model_name,
            "error_type": "ImportError",
            "error": "anthropic package is not installed",
        }

    try:
        api_key = services.secret_resolver.get_required("ANTHROPIC_API_KEY")
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            max_tokens=16,
            temperature=0,
            messages=[{"role": "user", "content": f"Strict health probe for Project OS {capability}. Reply with OK."}],
        )
        content = getattr(response, "content", None) or []
        return {
            "ok": True,
            "skipped": False,
            "provider": "anthropic",
            "capability": capability,
            "model": getattr(response, "model", model_name),
            "content_blocks": len(content),
        }
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "provider": "anthropic",
            "capability": capability,
            "model": model_name,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _persist_bootstrap_state(services, state: BootstrapState) -> None:
    services.paths.bootstrap_state_path.parent.mkdir(parents=True, exist_ok=True)
    services.paths.bootstrap_state_path.write_text(
        json.dumps(to_jsonable(state), ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    services.database.execute(
        """
        INSERT INTO bootstrap_states(
            bootstrap_state_id, strict_ready, status, failures_json, warnings_json, checks_json, roots_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            state.bootstrap_state_id,
            1 if state.strict_ready else 0,
            state.status,
            json.dumps(state.failures, ensure_ascii=True),
            json.dumps(state.warnings, ensure_ascii=True),
            json.dumps(state.checks, ensure_ascii=True, sort_keys=True),
            json.dumps(state.roots, ensure_ascii=True, sort_keys=True),
            state.created_at,
        ),
    )
