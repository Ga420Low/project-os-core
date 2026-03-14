from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.bootstrap import _bootstrap_state, _collect_checks
from project_os_core.config import SecretConfig, _runtime_policy_defaults
from project_os_core.secrets import SecretLookup
from project_os_core.services import build_app_services


class BootstrapTests(unittest.TestCase):
    def _build_services(self, tmp_path: Path):
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
        services.secret_resolver._from_infisical = lambda name: SecretLookup(  # type: ignore[method-assign]
            value=None,
            source="infisical_skipped",
            available=False,
        )
        return services

    def test_default_secret_policy_requires_openai_and_anthropic(self):
        self.assertEqual(SecretConfig().required_secret_names, ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"])
        self.assertEqual(
            _runtime_policy_defaults()["secret_config"]["required_secret_names"],
            ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        )

    def test_strict_checks_probe_reviewer_and_translator_models(self):
        calls: list[tuple[str, dict[str, object]]] = []

        class _FakeAnthropic:
            def __init__(self, *, api_key: str):
                self._api_key = api_key
                self.messages = self

            def create(self, **kwargs):
                calls.append((self._api_key, kwargs))
                return types.SimpleNamespace(model=kwargs["model"], content=[types.SimpleNamespace(type="text", text="OK")])

        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "anthropic-test-secret")

                with patch("project_os_core.bootstrap.Anthropic", _FakeAnthropic):
                    checks = _collect_checks(services, strict=True)

                self.assertTrue(checks["required_secrets_ok"])
                self.assertTrue(checks["anthropic_reviewer_probe"]["ok"])
                self.assertTrue(checks["anthropic_translator_probe"]["ok"])
                self.assertEqual(
                    {payload["model"] for _, payload in calls},
                    {"claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"},
                )
                self.assertEqual({api_key for api_key, _ in calls}, {"anthropic-test-secret"})
            finally:
                services.close()

    def test_strict_state_blocks_when_anthropic_secret_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")

                checks = _collect_checks(services, strict=True)
                state = _bootstrap_state(services, checks, strict=True)

                self.assertFalse(checks["required_secrets_ok"])
                self.assertFalse(state.strict_ready)
                self.assertIn("required_secret_missing", state.failures)
                self.assertIn("anthropic_reviewer_invalid", state.failures)
                self.assertIn("anthropic_translator_invalid", state.failures)
                self.assertEqual(checks["anthropic_reviewer_probe"]["error_type"], "RuntimeError")
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
