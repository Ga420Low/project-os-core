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

    def _run_ingest_cli(self, config_path: Path, policy_path: Path, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
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
        return exit_code, json.loads(stdout.getvalue())

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
                "source": "openclaw",
                "surface": "discord",
                "event_type": "message.received",
                "event": {
                    "from": "discord-user-42",
                    "content": "Decision: keep OpenClaw as operator facade and route web tasks to the browser worker.",
                    "timestamp": 1770000000,
                    "metadata": {
                        "source": "openclaw",
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

            exit_code, parsed = self._run_ingest_cli(config_path, policy_path, payload)
            self.assertEqual(exit_code, 0)
            self.assertEqual(parsed["operator_reply"]["reply_kind"], "ack")
            self.assertEqual(len(parsed["promoted_memory_ids"]), 1)

    def test_openclaw_ingest_cli_deduplicates_same_message(self):
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
                "source": "openclaw",
                "surface": "discord",
                "event_type": "message.received",
                "event": {
                    "from": "discord-user-42",
                    "content": "Status: relance le navigateur et garde la derniere decision sur la facade OpenClaw.",
                    "timestamp": 1770000001,
                    "metadata": {
                        "source": "openclaw",
                        "senderId": "42",
                        "senderName": "Founder",
                        "messageId": "discord-message-dedup",
                        "threadId": "discord-thread-dedup",
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

            first_exit_code, first_parsed = self._run_ingest_cli(config_path, policy_path, payload)
            second_exit_code, second_parsed = self._run_ingest_cli(config_path, policy_path, payload)

            self.assertEqual(first_exit_code, 0)
            self.assertEqual(second_exit_code, 0)
            self.assertEqual(first_parsed["operator_reply"]["reply_kind"], "ack")
            self.assertTrue(second_parsed["metadata"]["duplicate_ingress"])

            reopened, _, _ = self._build_services(Path(tmp))
            try:
                channel_event_count = reopened.database.fetchone("SELECT COUNT(*) AS count FROM channel_events")
                candidate_count = reopened.database.fetchone("SELECT COUNT(*) AS count FROM conversation_memory_candidates")
                dispatch_count = reopened.database.fetchone("SELECT COUNT(*) AS count FROM gateway_dispatch_results")
                binding_count = reopened.database.fetchone("SELECT COUNT(*) AS count FROM discord_thread_bindings")
                self.assertEqual(channel_event_count["count"], 1)
                self.assertEqual(candidate_count["count"], 1)
                self.assertEqual(dispatch_count["count"], 1)
                self.assertEqual(binding_count["count"], 1)
            finally:
                reopened.close()

    def test_openclaw_ingest_cli_projects_discord_thread_binding(self):
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
                "source": "openclaw",
                "surface": "discord",
                "event_type": "message.received",
                "event": {
                    "from": "discord-user-42",
                    "content": "Audit rapide: garde ce thread lie au run navigateur.",
                    "timestamp": 1770000002,
                    "metadata": {
                        "source": "openclaw",
                        "senderId": "42",
                        "senderName": "Founder",
                        "messageId": "discord-message-thread-binding",
                        "threadId": "discord-thread-binding",
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

            exit_code, parsed = self._run_ingest_cli(config_path, policy_path, payload)
            self.assertEqual(exit_code, 0)
            self.assertIn("thread_binding_id", parsed["metadata"])
            self.assertEqual(parsed["metadata"]["thread_binding_kind"], "run")

            reopened, _, _ = self._build_services(Path(tmp))
            try:
                row = reopened.database.fetchone(
                    "SELECT * FROM discord_thread_bindings WHERE binding_id = ?",
                    (parsed["metadata"]["thread_binding_id"],),
                )
                self.assertIsNotNone(row)
                self.assertEqual(row["surface"], "discord")
                self.assertEqual(row["binding_kind"], "run")
                self.assertEqual(row["external_thread_id"], "123456")
                self.assertEqual(row["status"], "active")
            finally:
                reopened.close()

    def test_openclaw_ingest_cli_prepares_research_scaffold_for_deep_research(self):
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
                "source": "openclaw",
                "surface": "discord",
                "event_type": "message.received",
                "event": {
                    "from": "discord-user-42",
                    "content": "Deep research sur les meilleurs systemes de memoire pour le projet, regarde les forks et va chercher les pepites.",
                    "timestamp": 1770000003,
                    "metadata": {
                        "source": "openclaw",
                        "senderId": "42",
                        "senderName": "Founder",
                        "messageId": "discord-message-deep-research",
                        "threadId": "discord-thread-deep-research",
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

            scaffold_payload = {
                "path": "D:\\ProjectOS\\project-os-core\\docs\\systems\\MEMORY_SYSTEMS_DOSSIER.md",
                "kind": "system",
                "title": "Memory Systems",
                "keywords": ["deep research", "regarde les forks"],
                "recent_days": 30,
                "core_packages": ["memory", "learning"],
                "created": True,
            }
            with patch("project_os_core.gateway.service.scaffold_research", return_value=scaffold_payload):
                exit_code, parsed = self._run_ingest_cli(config_path, policy_path, payload)

            self.assertEqual(exit_code, 0)
            self.assertEqual(parsed["metadata"]["research_scaffold_title"], "Memory Systems")
            self.assertEqual(parsed["metadata"]["research_scaffold_kind"], "system")
            self.assertEqual(parsed["metadata"]["research_scaffold_doc_name"], "MEMORY_SYSTEMS_DOSSIER.md")
            self.assertEqual(parsed["operator_reply"]["reply_kind"], "clarification_required")
            self.assertEqual(parsed["metadata"]["approval_metadata"]["approval_type"], "deep_research_mode_selection")
            self.assertIn("profil recommande", parsed["operator_reply"]["summary"].lower())
            self.assertIn("intensite recommandee", parsed["operator_reply"]["summary"].lower())
            self.assertIn("MEMORY_SYSTEMS_DOSSIER.md", parsed["operator_reply"]["summary"])

    def test_openclaw_ingest_cli_detects_deep_research_with_common_typo(self):
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
                "source": "openclaw",
                "surface": "discord",
                "event_type": "message.received",
                "event": {
                    "from": "discord-user-42",
                    "content": "recherche appronfondie legeres sur les tomates",
                    "timestamp": 1770000004,
                    "metadata": {
                        "source": "openclaw",
                        "senderId": "42",
                        "senderName": "Founder",
                        "messageId": "discord-message-deep-research-typo",
                        "threadId": "discord-thread-deep-research-typo",
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

            scaffold_payload = {
                "path": "D:\\ProjectOS\\project-os-core\\docs\\audits\\LEGERES_SUR_LES_TOMATES_AUDIT_2026-03-15.md",
                "kind": "audit",
                "title": "Legeres Sur Les Tomates",
                "keywords": ["recherche approfondie"],
                "recent_days": 30,
                "core_packages": ["memory", "learning"],
                "created": True,
            }
            with patch("project_os_core.gateway.service.scaffold_research", return_value=scaffold_payload):
                exit_code, parsed = self._run_ingest_cli(config_path, policy_path, payload)

            self.assertEqual(exit_code, 0)
            self.assertEqual(parsed["metadata"]["research_scaffold_title"], "Legeres Sur Les Tomates")
            self.assertEqual(parsed["metadata"]["research_scaffold_kind"], "audit")
            self.assertEqual(parsed["operator_reply"]["reply_kind"], "clarification_required")
            self.assertEqual(parsed["metadata"]["approval_metadata"]["approval_type"], "deep_research_mode_selection")
            self.assertIn("profil recommande", parsed["operator_reply"]["summary"].lower())
            self.assertIn("intensite recommandee", parsed["operator_reply"]["summary"].lower())


if __name__ == "__main__":
    unittest.main()
