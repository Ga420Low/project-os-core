from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.cli import main
from project_os_core.models import RuntimeState, RuntimeVerdict, new_id
from project_os_core.services import build_app_services


class OpenClawGatewayAdapterTests(unittest.TestCase):
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
        return services, config_path, policy_path

    def test_openclaw_ingest_cli_dispatches_and_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, config_path, policy_path = self._build_services(Path(tmp))
            try:
                session = services.runtime.open_session(profile_name="browser", owner="founder")
                services.runtime.record_runtime_state(
                    RuntimeState(
                        runtime_state_id=new_id("runtime_state"),
                        session_id=session.session_id,
                        verdict=RuntimeVerdict.READY,
                        active_profile="browser",
                    )
                )
            finally:
                services.close()

            payload = {
                "surface": "discord",
                "event_type": "message.received",
                "event": {
                    "from": "discord-user-42",
                    "content": "Decision: keep OpenClaw as operator facade and route web tasks to the browser worker.",
                    "timestamp": 1770000000,
                    "metadata": {
                        "senderId": "42",
                        "senderName": "Founder",
                        "messageId": "discord-message-1",
                        "threadId": "discord-thread-1",
                        "originatingChannel": "discord",
                        "originatingTo": "123456",
                        "channelName": "project-os",
                    },
                },
                "context": {
                    "channelId": "discord",
                    "accountId": "default",
                    "conversationId": "123456",
                },
                "config": {
                    "target_profile": "browser",
                    "requested_worker": "browser",
                    "metadata": {"source": "unit-test"},
                },
            }

            stdout = io.StringIO()
            original_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO(json.dumps(payload))
                with redirect_stdout(stdout):
                    exit_code = main(
                        [
                            "--config-path",
                            str(config_path),
                            "--policy-path",
                            str(policy_path),
                            "gateway",
                            "ingest-openclaw-event",
                            "--stdin",
                        ]
                    )
            finally:
                sys.stdin = original_stdin

            self.assertEqual(exit_code, 0)
            parsed = json.loads(stdout.getvalue())
            self.assertEqual(parsed["operator_reply"]["reply_kind"], "ack")
            self.assertEqual(len(parsed["promoted_memory_ids"]), 1)


if __name__ == "__main__":
    unittest.main()
