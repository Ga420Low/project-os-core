from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.services import build_app_services


class OpenClawLiveTests(unittest.TestCase):
    def _build_services(self, tmp_path: Path):
        repo_root = Path(__file__).resolve().parents[2]
        plugin_source = repo_root / "integrations" / "openclaw" / "project-os-gateway-adapter"

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
            "openclaw_config": {
                "runtime_root": str(tmp_path / "openclaw-runtime"),
                "state_root": str(tmp_path / "runtime" / "openclaw"),
                "plugin_source_path": str(plugin_source),
                "enabled_channels": ["discord", "webchat"],
                "send_ack_replies": False,
                "require_replay_before_live": True,
            },
        }
        policy_path = tmp_path / "runtime_policy.json"
        policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

        services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
        services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
        return services

    def test_openclaw_bootstrap_blocks_cleanly_when_binary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: None  # type: ignore[method-assign]
                report = services.openclaw.bootstrap()
                self.assertEqual(report.readiness, "bloque")
                self.assertIn("openclaw_binary_missing", report.blocking_reasons)
                self.assertEqual(report.plugin_status, "binary_missing")
            finally:
                services.close()

    def test_openclaw_doctor_blocks_cleanly_when_binary_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.openclaw._resolve_openclaw_binary = lambda: None  # type: ignore[method-assign]
                report = services.openclaw.doctor()
                self.assertEqual(report.verdict, "bloque")
                self.assertTrue(any("Installe OpenClaw" in item for item in report.actionable_fixes))
            finally:
                services.close()

    def test_openclaw_replay_all_fixtures_respects_router_and_selective_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                report = services.openclaw.replay(run_all=True)
                self.assertEqual(report["verdict"], "OK")
                self.assertEqual(report["failed"], 0)

                by_fixture = {item["fixture_id"]: item for item in report["results"]}
                self.assertEqual(by_fixture["simple_text"]["promoted_memory_count"], 1)
                self.assertEqual(by_fixture["with_attachment"]["promoted_memory_count"], 1)
                self.assertEqual(by_fixture["tasking_browser"]["promoted_memory_count"], 1)
                self.assertEqual(by_fixture["small_talk_skip"]["promoted_memory_count"], 0)
                self.assertTrue(by_fixture["small_talk_skip"]["passed"])
            finally:
                services.close()

    def test_openclaw_validate_live_stays_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                payload_file = str(Path(__file__).resolve().parents[2] / "fixtures" / "openclaw" / "simple_text.json")
                result = services.openclaw.validate_live(channel="discord", payload_file=payload_file)
                self.assertFalse(result.success)
                self.assertIn("Replay OpenClaw non valide", result.failure_reason or "")

                services.openclaw._write_json(  # type: ignore[attr-defined]
                    services.paths.openclaw_replay_report_path,
                    {"verdict": "OK", "total": 1, "passed": 1, "failed": 0, "results": []},
                )
                services.config.openclaw_config.enabled_channels = ["webchat"]
                result = services.openclaw.validate_live(channel="discord", payload_file=payload_file)
                self.assertFalse(result.success)
                self.assertIn("Canal non active", result.failure_reason or "")
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
