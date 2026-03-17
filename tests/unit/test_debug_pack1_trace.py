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
from project_os_core.models import ChannelEvent, ConversationThreadRef, OperatorMessage, RuntimeState, RuntimeVerdict, new_id
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


class Pack1TraceTests(unittest.TestCase):
    def test_gateway_dispatch_persists_correlation_id_across_core_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, _ = _build_services(Path(tmp))
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
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Decision: keep Discord as the private operator channel and use the browser worker for forms.",
                        thread_ref=ConversationThreadRef(
                            thread_id="thread_pack1",
                            channel="discord",
                            external_thread_id="discord-thread-pack1",
                        ),
                    ),
                )

                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="browser",
                    requested_worker="browser",
                )

                correlation_id = dispatch.correlation_id
                self.assertIsNotNone(correlation_id)
                assert correlation_id is not None

                rows = {
                    "channel_events": services.database.fetchone(
                        "SELECT correlation_id FROM channel_events WHERE event_id = ?",
                        (event.event_id,),
                    ),
                    "mission_intents": services.database.fetchone(
                        "SELECT correlation_id FROM mission_intents WHERE intent_id = ?",
                        (dispatch.intent_id,),
                    ),
                    "routing_decisions": services.database.fetchone(
                        "SELECT correlation_id FROM routing_decisions WHERE decision_id = ?",
                        (dispatch.decision_id,),
                    ),
                    "routing_decision_traces": services.database.fetchone(
                        "SELECT correlation_id FROM routing_decision_traces WHERE trace_id = ?",
                        (dispatch.metadata["routing_trace_id"],),
                    ),
                    "mission_runs": services.database.fetchone(
                        "SELECT correlation_id FROM mission_runs WHERE mission_run_id = ?",
                        (dispatch.mission_run_id,),
                    ),
                    "gateway_dispatch_results": services.database.fetchone(
                        "SELECT correlation_id FROM gateway_dispatch_results WHERE dispatch_id = ?",
                        (dispatch.dispatch_id,),
                    ),
                }
                for row in rows.values():
                    self.assertIsNotNone(row)
                    self.assertEqual(str(row["correlation_id"]), correlation_id)

                report = services.database.fetch_trace_report(correlation_id)
                self.assertTrue(report["found"])
                self.assertEqual(report["summary"]["channel_event_ids"], [event.event_id])
                self.assertEqual(report["summary"]["dispatch_ids"], [dispatch.dispatch_id])
                self.assertEqual(report["summary"]["intent_ids"], [dispatch.intent_id])
                self.assertEqual(report["summary"]["decision_ids"], [dispatch.decision_id])
                self.assertEqual(report["summary"]["mission_run_ids"], [dispatch.mission_run_id])
                self.assertEqual(report["summary"]["conversation_key"], "discord-thread-pack1")
            finally:
                services.close()

    def test_debug_trace_cli_renders_trace_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, config_path, policy_path = _build_services(Path(tmp))
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
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Decision: prepare the browser worker follow-up and keep Discord private.",
                        thread_ref=ConversationThreadRef(thread_id="thread_pack1_cli", channel="discord"),
                    ),
                )
                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="browser",
                    requested_worker="browser",
                )
                correlation_id = dispatch.correlation_id
                self.assertIsNotNone(correlation_id)
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
                        "trace",
                        str(correlation_id),
                    ]
                )
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["found"])
            self.assertEqual(payload["correlation_id"], correlation_id)
            self.assertEqual(payload["summary"]["counts"]["gateway_dispatches"], 1)
            self.assertEqual(payload["summary"]["counts"]["mission_intents"], 1)
            self.assertEqual(payload["summary"]["counts"]["routing_decisions"], 1)


if __name__ == "__main__":
    unittest.main()
