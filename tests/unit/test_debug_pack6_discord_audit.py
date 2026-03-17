from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.cli import main
from project_os_core.debug_discord_audit import build_discord_debug_audit_report
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


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    return path


class Pack6DiscordAuditTests(unittest.TestCase):
    def test_discord_audit_classifies_regression_and_false_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, _ = _build_services(Path(tmp))
            try:
                current_report_path = _write_json(
                    Path(tmp) / "current_report.json",
                    {
                        "suite": "discord_facade_smoke",
                        "anthropic_model": "claude-haiku-4-5-20251001",
                        "results": [
                            {
                                "scenario_id": "natural_reply_hides_plumbing",
                                "description": "hide plumbing",
                                "layer": "smoke",
                                "passed": False,
                                "skipped": False,
                                "errors": ["resume visible contient un terme interdit"],
                            },
                            {
                                "scenario_id": "provider_disclosure_on_demand",
                                "description": "provider disclosure",
                                "layer": "smoke",
                                "passed": True,
                                "skipped": False,
                                "errors": [],
                            },
                            {
                                "scenario_id": "persona_no_corporate_bullshit",
                                "description": "persona anti corporate",
                                "layer": "persona",
                                "passed": False,
                                "skipped": False,
                                "errors": ["resume visible contient un terme interdit"],
                            },
                        ],
                    },
                )
                previous_report_path = _write_json(
                    Path(tmp) / "previous_report.json",
                    {
                        "suite": "discord_facade_smoke",
                        "results": [
                            {
                                "scenario_id": "natural_reply_hides_plumbing",
                                "passed": True,
                                "skipped": False,
                            }
                        ],
                    },
                )
                manual_status_path = _write_json(
                    Path(tmp) / "manual_status.json",
                    {
                        "manual_checks": [
                            {"check_id": "manual_presence_typing", "status": "pass"},
                            {"check_id": "manual_humor_calibration", "status": "pass"},
                            {"check_id": "manual_stress_response", "status": "pass"},
                            {"check_id": "manual_lane_identity", "status": "pass"},
                            {"check_id": "manual_thread_continuity_days", "status": "pass"},
                            {"check_id": "manual_cross_surface_resume", "status": "pass"},
                            {"check_id": "manual_cross_surface_return_to_discord", "status": "pass"},
                        ],
                        "scenario_overrides": {
                            "persona_no_corporate_bullshit": {
                                "status": "false_positive",
                                "notes": "guard trop strict pour ce lot",
                            }
                        },
                    },
                )

                report = build_discord_debug_audit_report(
                    services,
                    report_path=str(current_report_path),
                    previous_report_path=str(previous_report_path),
                    manual_status_path=str(manual_status_path),
                    freeze_lifted=True,
                )

                self.assertEqual(report["status"], "non_coherent")
                self.assertEqual(report["decision"], "open_correction_pack")
                self.assertEqual(report["summary"]["regression_count"], 1)
                self.assertEqual(report["summary"]["false_positive_count"], 1)
                self.assertEqual(report["manual_acceptance"]["status"], "pass")
                self.assertTrue(Path(str(report["artifact_path"])).exists())
            finally:
                services.close()

    def test_cli_discord_audit_reports_inconclusive_until_freeze_and_manual_are_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, config_path, policy_path = _build_services(Path(tmp))
            try:
                current_report_path = _write_json(
                    Path(tmp) / "current_report.json",
                    {
                        "suite": "discord_facade_smoke",
                        "anthropic_model": "claude-haiku-4-5-20251001",
                        "results": [
                            {
                                "scenario_id": "natural_reply_hides_plumbing",
                                "description": "hide plumbing",
                                "layer": "smoke",
                                "passed": True,
                                "skipped": False,
                                "errors": [],
                            },
                            {
                                "scenario_id": "persona_identity_not_generic",
                                "description": "persona identity",
                                "layer": "persona",
                                "passed": True,
                                "skipped": False,
                                "errors": [],
                            },
                        ],
                    },
                )
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
                        "discord-audit",
                        "--report-path",
                        str(current_report_path),
                    ]
                )
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "inconclusive")
            self.assertEqual(payload["decision"], "hold_freeze_and_finish_audit")
            self.assertIn("freeze_not_lifted", payload["prerequisites"])
            self.assertIn("manual_acceptance_pending", payload["prerequisites"])
            self.assertTrue(Path(str(payload["artifact_path"])).exists())

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--config-path",
                        str(config_path),
                        "--policy-path",
                        str(policy_path),
                        "debug",
                        "discord-audit",
                        "--report-path",
                        str(current_report_path),
                        "--strict",
                    ]
                )
            self.assertEqual(exit_code, 1)

    def test_discord_audit_can_use_patched_live_runner_without_touching_bot(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, policy_path = _build_services(Path(tmp))
            try:
                live_report_path = Path(tmp) / "live" / "aggregate" / "20260317T120000Z.json"
                fake_live_report = {
                    "suite": "discord_facade_smoke",
                    "anthropic_model": "claude-haiku-4-5-20251001",
                    "report_path": str(live_report_path),
                    "results": [
                        {
                            "scenario_id": "natural_reply_hides_plumbing",
                            "description": "hide plumbing",
                            "layer": "smoke",
                            "passed": True,
                            "skipped": False,
                            "errors": [],
                        }
                    ],
                }
                with patch(
                    "project_os_core.debug_discord_audit.run_smoke_suite_isolated",
                    return_value=fake_live_report,
                ):
                    report = build_discord_debug_audit_report(
                        services,
                        run_live=True,
                        freeze_lifted=False,
                        allow_missing_anthropic=True,
                        policy_path=str(policy_path),
                        runtime_base_dir=str(Path(tmp) / "discord_audit_live"),
                    )

                self.assertTrue(report["run_live"])
                self.assertEqual(report["current_report_path"], str(live_report_path.resolve(strict=False)))
                self.assertEqual(report["status"], "inconclusive")
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
