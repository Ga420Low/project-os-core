from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.api_runs.dashboard import build_dashboard_payload, render_dashboard_html
from project_os_core.models import ApiRunMode
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
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

    services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
    services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
    return services


class ApiRunDashboardTests(unittest.TestCase):
    def test_dashboard_payload_contains_preview_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                payload = services.api_runs.execute_run(
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Build the local dashboard for API runs.",
                    branch_name="codex/test-dashboard",
                    skill_tags=["patch_plan", "dashboard"],
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Build the local dashboard in a single lot.",
                                "why": "A visible interface improves supervision.",
                                "alternatives": ["Stay terminal-only."],
                                "files_to_change": ["src/project_os_core/api_runs/dashboard.py"],
                                "interfaces": ["ApiRunResult"],
                                "patch_outline": ["Add a local web server.", "Render current run and artifacts."],
                                "tests": ["Dashboard payload test."],
                                "risks": ["UI drift from runtime state."],
                                "acceptance_criteria": ["Current run is visible in a browser."],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 1000, "output_tokens": 500},
                    },
                )
                snapshot = build_dashboard_payload(services, limit=5)
                self.assertEqual(snapshot["snapshot"]["current_run"]["run_id"], payload["result"].run_id)
                self.assertEqual(snapshot["current_preview"]["decision"], "Build the local dashboard in a single lot.")
                self.assertGreaterEqual(len(snapshot["current_artifacts"]), 4)
            finally:
                services.close()

    def test_dashboard_html_contains_live_panels(self):
        html = render_dashboard_html(
            {
                "generated_at": "2026-03-13T12:00:00+00:00",
                "snapshot": {
                    "budget": {
                        "daily_spend_estimate_eur": 0.1,
                        "monthly_spend_estimate_eur": 0.4,
                        "daily_soft_limit_eur": 1.5,
                        "monthly_limit_eur": 50.0,
                    },
                    "current_run": None,
                    "latest_runs": [],
                },
                "current_artifacts": [],
                "current_preview": None,
                "status_counts": {},
                "review_counts": {},
                "lane_policy": {
                    "coding_lane": "repo_cli",
                    "desktop_lane": "future_computer_use",
                    "discord_surface": "mandatory",
                    "voice_mode": "future_ready",
                    "memory_sync": "selective_sync",
                },
            },
            refresh_seconds=5,
        )
        self.assertIn("Project OS Agent API", html)
        self.assertIn("Execution en cours", html)
        self.assertIn("Runs recents", html)
        self.assertIn("Apercu structure", html)
