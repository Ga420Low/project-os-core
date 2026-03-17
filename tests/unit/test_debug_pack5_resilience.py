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
from project_os_core.debug_resilience import build_resilience_report, reconcile_debug_state, scan_debug_orphans
from project_os_core.models import IncidentSeverity, IncidentStatus, TraceEntityKind
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


class Pack5ResilienceTests(unittest.TestCase):
    def test_orphan_scan_and_reconcile_mark_missing_artifacts_and_stale_proofs(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, config_path, policy_path = _build_services(Path(tmp))
            try:
                stale_at = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
                dead_letter_id = services.database.record_dead_letter(
                    domain="operator_delivery",
                    source_entity_kind=TraceEntityKind.API_RUN.value,
                    source_entity_id="api_run_resilience",
                    replayable=True,
                    artifact_path=str(Path(tmp) / "missing_dead_letter.json"),
                    created_at=stale_at,
                    updated_at=stale_at,
                )
                replay_id = services.database.record_debug_replay_run(
                    source_entity_kind=TraceEntityKind.CHANNEL_EVENT.value,
                    source_entity_id="channel_event_resilience",
                    status="failed",
                    artifact_path=str(Path(tmp) / "missing_replay.json"),
                    created_at=stale_at,
                    updated_at=stale_at,
                )
                eval_case = services.evals.create_case(
                    suite_id="core-debug",
                    scenario="stale proof",
                    target_system="debug_system",
                    expected_behavior="incident must be reverified after stale proof",
                    runner_kind="manual_review",
                )
                eval_run = services.evals.run_suite(suite_id="core-debug")
                services.database.execute(
                    "UPDATE eval_runs SET updated_at = ?, status = ? WHERE eval_run_id = ?",
                    (stale_at, "passed", eval_run["eval_run_id"]),
                )
                incident = services.incidents.create_incident(
                    severity=IncidentSeverity.P1,
                    summary="Incident stale proof",
                    symptom="preuve verte trop ancienne",
                    dead_letter_id=dead_letter_id,
                    replay_id=replay_id,
                    eval_case_id=eval_case["eval_case_id"],
                    latest_eval_run_id=eval_run["eval_run_id"],
                    verification_refs=["eval:initial"],
                    status=IncidentStatus.VERIFIED,
                )
                orphan_folder = services.paths.runtime_root / "incidents"
                orphan_folder.mkdir(parents=True, exist_ok=True)
                orphan_path = orphan_folder / "incident_orphan.json"
                orphan_path.write_text(json.dumps({"orphan": True}, ensure_ascii=True), encoding="utf-8")

                orphan_scan = scan_debug_orphans(services, limit=20)
                self.assertEqual(orphan_scan["status"], "breach")
                self.assertGreaterEqual(orphan_scan["missing_db_artifact_count"], 2)
                self.assertGreaterEqual(orphan_scan["orphan_artifact_count"], 1)

                resilience = build_resilience_report(services, limit=20)
                self.assertIn(resilience["debug_pressure"]["status"], {"ok", "attention", "breach"})
                self.assertEqual(resilience["proof_freshness"]["stale_incident_count"], 1)

                reconcile = reconcile_debug_state(services, repair=True, limit=20)
                self.assertGreaterEqual(reconcile["repair_applied_count"], 3)
                self.assertTrue(Path(str(reconcile["artifact_path"])).exists())

                dead_letter_row = services.database.fetchone(
                    "SELECT metadata_json FROM dead_letter_records WHERE dead_letter_id = ?",
                    (dead_letter_id,),
                )
                replay_row = services.database.fetchone(
                    "SELECT metadata_json FROM debug_replay_runs WHERE replay_id = ?",
                    (replay_id,),
                )
                incident_row = services.database.fetchone(
                    "SELECT metadata_json FROM incident_records WHERE incident_id = ?",
                    (incident["incident_id"],),
                )
                self.assertEqual(json.loads(str(dead_letter_row["metadata_json"]))["artifact_state"], "missing")
                self.assertEqual(json.loads(str(replay_row["metadata_json"]))["artifact_state"], "missing")
                self.assertEqual(json.loads(str(incident_row["metadata_json"]))["proof_state"], "needs_reverification")
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
                        "debug",
                        "orphan-scan",
                        "--limit",
                        "20",
                    ]
                )
            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "breach")

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
                        "--repair",
                        "--strict",
                        "--limit",
                        "20",
                    ]
                )
            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertIn("resilience", payload)
            self.assertIn("repair", payload)
            self.assertGreaterEqual(payload["repair"]["repair_applied_count"], 0)
