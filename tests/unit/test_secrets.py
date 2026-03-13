from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.config import SecretConfig
from project_os_core.secrets import SecretResolver


class SecretResolverTests(unittest.TestCase):
    def test_local_fallback_is_used_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            secrets_path = tmp_path / "secrets.json"
            secrets_path.write_text(json.dumps({"PROJECT_OS_TEST_SECRET": "sk-test-secret"}), encoding="utf-8")
            resolver = SecretResolver(
                SecretConfig(
                    mode="infisical_first",
                    required_secret_names=["PROJECT_OS_TEST_SECRET"],
                    local_fallback_path=str(secrets_path),
                )
            )

            lookup = resolver.lookup("PROJECT_OS_TEST_SECRET")

            self.assertTrue(lookup.available)
            self.assertEqual(lookup.source, "local_fallback")
            self.assertEqual(resolver.mask(lookup.value), "sk-t...cret")

    def test_universal_auth_machine_credentials_enable_infisical_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_root = tmp_path / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / ".infisical.json").write_text('{"workspaceId":"workspace-test-123"}', encoding="utf-8")
            resolver = SecretResolver(
                SecretConfig(
                    mode="infisical_required",
                    required_secret_names=["OPENAI_API_KEY"],
                    local_fallback_path=str(tmp_path / "secrets.json"),
                ),
                repo_root=repo_root,
            )

            def fake_run(command, capture_output, text, check, timeout):
                if "login" in command:
                    return subprocess.CompletedProcess(command, 0, stdout="machine-access-token\n", stderr="")
                if "export" in command:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout='[{"key":"OPENAI_API_KEY","value":"sk-universal-secret"}]',
                        stderr="",
                    )
                raise AssertionError(f"Unexpected command: {command}")

            with mock.patch.dict(
                os.environ,
                {
                    "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID": "client-id-123",
                    "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET": "client-secret-456",
                },
                clear=False,
            ), mock.patch("project_os_core.secrets.shutil.which", return_value="C:/tools/infisical.exe"), mock.patch(
                "project_os_core.secrets.subprocess.run",
                side_effect=fake_run,
            ):
                report = resolver.source_report()
                lookup = resolver.lookup("OPENAI_API_KEY")

            self.assertTrue(report["infisical"]["machine_auth_ready"])
            self.assertEqual(report["infisical"]["auth_mode"], "universal_auth")
            self.assertEqual(report["infisical"]["active_token_source"], "universal_auth")
            self.assertTrue(report["infisical"]["resolution_ready"])
            self.assertTrue(lookup.available)
            self.assertEqual(lookup.source, "infisical")
            self.assertEqual(lookup.value, "sk-universal-secret")


if __name__ == "__main__":
    unittest.main()
