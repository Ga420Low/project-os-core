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
from project_os_core.project_review import build_project_review_report, render_project_review_markdown
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


def _write_checklist(path: Path) -> Path:
    path.write_text(
        """# Checklist

## Lots suivants

- [x] Foundation ready
- [ ] Lot Debug System v1
  - [x] Pack 0
  - [ ] Pack 6 - Audit final du debug live Discord
    - [ ] Execution live finale + checks manuels + decision explicite coherent
    - [ ] Rappel de cloture: relancer le runner en live apres levee du freeze puis repasser avec les checks manuels
- [ ] Lot 4 - Gateway + Mission Router adapter OpenClaw live
  - [ ] Preuve operateur manuelle depuis un vrai message Discord/WebChat amont
""",
        encoding="utf-8",
    )
    return path


class ProjectReviewTests(unittest.TestCase):
    def test_project_review_report_aggregates_done_partial_and_founder_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, _ = _build_services(Path(tmp))
            checklist_path = _write_checklist(Path(tmp) / "CHECKLIST.md")
            try:
                with patch(
                    "project_os_core.project_review.audit_docs",
                    return_value={"verdict": "a_corriger", "findings": [{"check": "missing_local_link"}]},
                ), patch(
                    "project_os_core.project_review.build_debug_system_report",
                    return_value={"status": "ok"},
                ), patch(
                    "project_os_core.project_review.build_resilience_report",
                    return_value={"status": "ok"},
                ), patch(
                    "project_os_core.project_review.build_discord_debug_audit_report",
                    return_value={
                        "status": "inconclusive",
                        "decision": "hold_freeze_and_finish_audit",
                        "next_step": "Completer les checks manuels et relancer l'audit.",
                    },
                ):
                    report = build_project_review_report(
                        services,
                        checklist_path=str(checklist_path),
                        limit=10,
                    )

                self.assertEqual(report["status"], "attention")
                self.assertEqual(report["summary"]["done_count"], 1)
                self.assertEqual(report["summary"]["partial_count"], 1)
                self.assertGreaterEqual(report["summary"]["forgotten_count"], 1)
                self.assertGreaterEqual(report["summary"]["non_verified_count"], 2)
                self.assertGreaterEqual(report["summary"]["founder_review_count"], 1)
                self.assertTrue(Path(str(report["artifact_json_path"])).exists())
                self.assertTrue(Path(str(report["artifact_markdown_path"])).exists())

                markdown = render_project_review_markdown(report)
                self.assertIn("# Project Review Loop", markdown)
                self.assertIn("## A revoir avec le fondateur", markdown)
            finally:
                services.close()

    def test_review_status_cli_supports_markdown_and_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, config_path, policy_path = _build_services(Path(tmp))
            checklist_path = _write_checklist(Path(tmp) / "CHECKLIST.md")
            try:
                with patch(
                    "project_os_core.project_review.audit_docs",
                    return_value={"verdict": "OK", "findings": []},
                ), patch(
                    "project_os_core.project_review.build_debug_system_report",
                    return_value={"status": "ok"},
                ), patch(
                    "project_os_core.project_review.build_resilience_report",
                    return_value={"status": "ok"},
                ), patch(
                    "project_os_core.project_review.build_discord_debug_audit_report",
                    return_value={
                        "status": "coherent",
                        "decision": "debug_live_discord_coherent_with_vision",
                        "next_step": "Clore Pack 6.",
                    },
                ):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "--config-path",
                                str(config_path),
                                "--policy-path",
                                str(policy_path),
                                "review",
                                "status",
                                "--checklist-path",
                                str(checklist_path),
                                "--markdown",
                            ]
                        )
                    rendered = stdout.getvalue()
                    self.assertEqual(exit_code, 0)
                    self.assertIn("# Project Review Loop", rendered)

                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(
                            [
                                "--config-path",
                                str(config_path),
                                "--policy-path",
                                str(policy_path),
                                "review",
                                "status",
                                "--checklist-path",
                                str(checklist_path),
                                "--strict",
                            ]
                        )
                    self.assertEqual(exit_code, 1)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
