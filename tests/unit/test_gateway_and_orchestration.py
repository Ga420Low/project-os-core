from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.models import (
    AgentRole,
    ChannelEvent,
    ConversationThreadRef,
    OperatorEnvelope,
    OperatorAttachment,
    OperatorMessage,
    RuntimeState,
    RuntimeVerdict,
    new_id,
)
from project_os_core.services import build_app_services


class GatewayAndOrchestrationTests(unittest.TestCase):
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
        return services

    def test_gateway_dispatch_promotes_decision_and_does_not_issue_worker_ticket(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
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
                            thread_id="thread_1",
                            channel="discord",
                            external_thread_id="discord-thread-1",
                        ),
                    ),
                )

                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="browser",
                    requested_worker="browser",
                )

                self.assertEqual(dispatch.operator_reply.reply_kind, "ack")
                self.assertEqual(len(dispatch.promoted_memory_ids), 1)
                records = services.database.fetchall("SELECT * FROM execution_tickets")
                self.assertEqual(records, [])
                candidates = services.database.fetchall("SELECT * FROM conversation_memory_candidates")
                self.assertEqual(len(candidates), 1)
                promotions = services.database.fetchall("SELECT * FROM promotion_decisions")
                self.assertEqual(len(promotions), 1)
            finally:
                services.close()

    def test_gateway_selective_sync_skips_small_talk(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                session = services.runtime.open_session(profile_name="core", owner="founder")
                services.runtime.record_runtime_state(
                    RuntimeState(
                        runtime_state_id=new_id("runtime_state"),
                        session_id=session.session_id,
                        verdict=RuntimeVerdict.READY,
                        active_profile="core",
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
                        text="Salut, ca va ? merci pour le check.",
                        thread_ref=ConversationThreadRef(thread_id="thread_2", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.promoted_memory_ids, [])
                promotion = services.database.fetchone(
                    "SELECT action FROM promotion_decisions WHERE promotion_decision_id = ?",
                    (dispatch.promotion_decision_id,),
                )
                self.assertIsNotNone(promotion)
                self.assertEqual(str(promotion["action"]), "skip")
            finally:
                services.close()

    def test_gateway_dispatch_survives_memory_provider_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
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
                services.memory.openmemory.add_record = lambda record: (_ for _ in ()).throw(RuntimeError("openmemory_down"))  # type: ignore[method-assign]
                services.memory.embedding_service.embed_text = lambda text: (_ for _ in ()).throw(RuntimeError("embedding_down"))  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Decision: keep browser automation enabled for web tasks.",
                        thread_ref=ConversationThreadRef(thread_id="thread_4", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="browser",
                    requested_worker="browser",
                )

                self.assertEqual(dispatch.operator_reply.reply_kind, "ack")
                self.assertEqual(len(dispatch.promoted_memory_ids), 1)
                record = services.memory.get(dispatch.promoted_memory_ids[0])
                self.assertIn("openmemory_warning", record.metadata)
                self.assertIn("embedding_fallback", record.metadata)
            finally:
                services.close()

    def test_canonical_graph_prepares_execution_ticket_with_six_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                session = services.runtime.open_session(profile_name="uefn", owner="founder")
                services.runtime.record_runtime_state(
                    RuntimeState(
                        runtime_state_id=new_id("runtime_state"),
                        session_id=session.session_id,
                        verdict=RuntimeVerdict.READY,
                        active_profile="uefn",
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
                        text="Please build the next UEFN mission plan and route it to the windows worker.",
                        thread_ref=ConversationThreadRef(thread_id="thread_3", channel="discord"),
                        attachments=[
                            OperatorAttachment(
                                attachment_id=new_id("attachment"),
                                name="brief.txt",
                                kind="file",
                            )
                        ],
                    ),
                )
                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="uefn",
                    requested_worker="windows",
                )
                decision_row = services.database.fetchone(
                    "SELECT * FROM routing_decisions WHERE decision_id = ?",
                    (dispatch.decision_id,),
                )
                self.assertIsNotNone(decision_row)
                mission_row = services.database.fetchone(
                    "SELECT * FROM mission_runs WHERE mission_run_id = ?",
                    (dispatch.mission_run_id,),
                )
                self.assertIsNotNone(mission_row)
                decision, _, mission_run = services.router.route_intent(
                    services.router.envelope_to_intent(
                        OperatorEnvelope(
                            envelope_id=new_id("envelope"),
                            actor_id="founder",
                            channel="discord",
                            objective=event.message.text,
                            target_profile="uefn",
                            requested_worker="windows",
                            metadata={"paths": []},
                        )
                    ),
                    persist=True,
                )
                prepared = services.orchestration.prepare_execution(mission_run=mission_run, decision=decision)

                self.assertEqual(len(prepared["handoffs"]), 6)
                self.assertEqual(prepared["graph_state"].active_role, AgentRole.EXECUTOR_COORDINATOR)
                self.assertEqual(prepared["ticket"].worker_kind, "windows")
                self.assertEqual(prepared["worker_dispatch_envelope"].metadata["issued_by"], AgentRole.EXECUTOR_COORDINATOR.value)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
