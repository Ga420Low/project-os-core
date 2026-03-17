from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.cli import main
from project_os_core.debug_health import build_debug_system_report
from project_os_core.models import IncidentSeverity, TraceEntityKind
from project_os_core.secrets import SecretLookup
from project_os_core.services import build_app_services


def _build_services(tmp_path: Path):
    storage_payload = {
        "runtime_root": str(tmp_path / "runtime"),
        "memory_hot_root": str(tmp_path / "memory_hot"),
        "memory_warm_root": str(tmp_path / "memory_warm"),
        "index_root": str(tmp_path / "indexes"),
        "session_root": str(tmp_path / "sessions"),
        "cache_root": str(tmp_path / "cache"),
        "archive_drive": "Z:",
        "archive_do_not_touch_root": str(tmp_path / "archive" / "DO_NOT_TOUCH"),
        "archive_root": str(tmp_path / "archive"),
        "archive_episodes_root": str(tmp_path / "archive" / "episodes"),
        "archive_evidence_root": str(tmp_path / "archive" / "evidence"),
        "archive_screens_root": str(tmp_path / "archive" / "screens"),
        "archive_reports_root": str(tmp_path / "archive" / "reports"),
        "archive_logs_root": str(tmp_path / "archive" / "logs"),
        "archive_snapshots_root": str(tmp_path / "archive" / "snapshots"),
    }
    config_path = tmp_path / "storage_roots.json"
    config_path.write_text(json.dumps(storage_payload), encoding="utf-8")

    policy_payload = {
        "secret_config": {
            "mode": "infisical_first",
            "required_secret_names": ["OPENAI_API_KEY"],
            "local_fallback_path": str(tmp_path / "secrets.json"),
        },
        "embedding_policy": {
            "provider_mode": "local_hash",
            "quality": "balanced",
            "local_model": "local-hash-v1",
            "local_dimensions": 64,
        },
        "api_dashboard_config": {
            "auto_start": False,
            "auto_open_browser": False,
            "require_visible_ui": False,
        },
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

    services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
    services.secret_resolver._from_infisical = lambda name: SecretLookup(
        value=None,
        source="test_infisical_disabled",
        available=False,
    )
    services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
    services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "anthropic-test-secret")
    return services, config_path, policy_path


class Pack4ObservabilityTests(unittest.TestCase):
    def test_observability_doctor_reports_breach_for_stale_debug_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, config_path, policy_path = _build_services(Path(tmp))
            try:
                stale_at = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
                quarantine_id = services.database.record_output_quarantine(
                    source_system="deep_research",
                    source_entity_kind=TraceEntityKind.MISSION_RUN.value,
                    source_entity_id="mission_run_stale",
                    reason_code="invalid_json",
                    payload={"raw_output": "broken"},
                    created_at=stale_at,
                )
                dead_letter_id = services.database.record_dead_letter(
                    domain="operator_delivery",
                    source_entity_kind=TraceEntityKind.API_RUN.value,
                    source_entity_id="api_run_dead_letter",
                    replayable=True,
                    artifact_path=str(Path(tmp) / "missing_dead_letter.json"),
                    created_at=stale_at,
                    updated_at=stale_at,
                )
                replay_id = services.database.record_debug_replay_run(
                    source_entity_kind=TraceEntityKind.CHANNEL_EVENT.value,
                    source_entity_id="channel_event_replay",
                    status="failed",
                    artifact_path=str(Path(tmp) / "missing_replay.json"),
                    created_at=stale_at,
                    updated_at=stale_at,
                )
                incident = services.incidents.create_incident(
                    severity=IncidentSeverity.P1,
                    summary="Incident critique de debug",
                    symptom="Le debug local garde un dead letter stale.",
                    dead_letter_id=dead_letter_id,
                    replay_id=replay_id,
                )

                report = build_debug_system_report(services, limit=5)

                self.assertEqual(report["status"], "breach")
                self.assertGreaterEqual(report["privacy_retention"]["ttl_breach_count"], 2)
                self.assertGreaterEqual(report["privacy_retention"]["artifact_missing_count"], 2)
                self.assertEqual(report["quarantine"]["recent_items"][0]["quarantine_id"], quarantine_id)
                self.assertEqual(report["incident_health"]["critical_open_count"], 1)
                self.assertEqual(report["replay_health"]["failed_count"], 1)
                self.assertEqual(incident["status"], "open")
            finally:
                services.close()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--config-path",
                        str(config_path),
                        "--policy-path",
                        str(policy_path),
                        "observability",
                        "doctor",
                        "--strict",
                    ]
                )
            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "breach")
            self.assertGreaterEqual(payload["gates"]["enforcing_count"], 3)

    def test_observability_doctor_report_exposes_gates_and_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, _ = _build_services(Path(tmp))
            try:
                report = build_debug_system_report(services, limit=3)
                self.assertIn("gates", report)
                self.assertIn("privacy_retention", report)
                self.assertEqual(report["gates"]["deferred_count"], 1)
                self.assertIn("policies", report["privacy_retention"])
            finally:
                services.close()
