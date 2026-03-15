from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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
    SensitivityClass,
    new_id,
)
from project_os_core.services import build_app_services


class StubLocalModelClient:
    def __init__(self, content: str = "Traite localement. Secret non reproduit.") -> None:
        self.content = content
        self.messages: list[str] = []

    def health(self, *, force: bool = False) -> dict[str, object]:
        return {
            "status": "ready",
            "reason": "model_ready",
            "provider": "ollama",
            "model": "qwen2.5:14b",
            "base_url": "http://127.0.0.1:11434",
        }

    def chat(self, *, message: str, system: str, model: str | None = None):
        self.messages.append(message)
        return SimpleNamespace(content=self.content)


class FailingLocalModelClient(StubLocalModelClient):
    def chat(self, *, message: str, system: str, model: str | None = None):
        self.messages.append(message)
        raise RuntimeError("local_runtime_down")


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

    def test_gateway_s2_sensitive_message_creates_full_and_clean_memory(self):
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
                captured_messages: list[str] = []

                def _stub_simple_chat(message: str, model: str = "claude-sonnet-4-20250514") -> str:
                    captured_messages.append(message)
                    return "ok"

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Salut, garde le bot token dans l'env et reviens vers founder@example.com.",
                        thread_ref=ConversationThreadRef(thread_id="thread_s2", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(dispatch.metadata["sensitivity_class"], SensitivityClass.S2.value)
                self.assertEqual(len(dispatch.promoted_memory_ids), 2)
                self.assertEqual(len(captured_messages), 1)
                self.assertNotIn("founder@example.com", captured_messages[0])
                self.assertNotIn("bot token", captured_messages[0].lower())
                records = [services.memory.get(memory_id) for memory_id in dispatch.promoted_memory_ids]
                full_record = next(record for record in records if record.metadata.get("privacy_view") == "full")
                clean_record = next(record for record in records if record.metadata.get("privacy_view") == "clean")
                self.assertIn("founder@example.com", full_record.content)
                self.assertIn("bot token", full_record.content.lower())
                self.assertNotIn("founder@example.com", clean_record.content)
                self.assertEqual(full_record.metadata.get("openmemory_enabled"), False)
                self.assertEqual(full_record.metadata.get("embedding_provider"), "local_hash")
            finally:
                services.close()

    def test_gateway_s3_sensitive_message_blocks_cloud_route_and_stores_local_only_memory(self):
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
                        text="Decision: OPENCLAW_GATEWAY_TOKEN=sk-super-secret-123456789",
                        thread_ref=ConversationThreadRef(thread_id="thread_s3", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "blocked")
                self.assertEqual(dispatch.metadata["sensitivity_class"], SensitivityClass.S3.value)
                self.assertEqual(len(dispatch.promoted_memory_ids), 1)
                record = services.memory.get(dispatch.promoted_memory_ids[0])
                self.assertEqual(record.metadata.get("privacy_view"), "full")
                self.assertEqual(record.metadata.get("openmemory_enabled"), False)
                self.assertEqual(record.metadata.get("embedding_provider"), "local_hash")
                self.assertIn("trop sensible pour le cloud", dispatch.operator_reply.summary)
            finally:
                services.close()

    def test_gateway_s3_sensitive_message_executes_locally_when_local_lane_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.config.execution_policy.local_model_enabled = True
                services.config.execution_policy.local_model_name = "qwen2.5:14b"
                services.router.execution_policy.local_model_enabled = True
                services.router.execution_policy.local_model_name = "qwen2.5:14b"
                stub_local = StubLocalModelClient(content="Secret recu. Garde-le hors cloud.")
                services.router.local_model_client = stub_local
                services.gateway.local_model_client = stub_local
                services.openclaw.local_model_client = stub_local
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
                        text="Decision: OPENCLAW_GATEWAY_TOKEN=sk-super-secret-123456789",
                        thread_ref=ConversationThreadRef(thread_id="thread_s3_local", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(dispatch.metadata["sensitivity_class"], SensitivityClass.S3.value)
                self.assertEqual(len(dispatch.promoted_memory_ids), 1)
                self.assertEqual(len(stub_local.messages), 1)
                self.assertIn("OPENCLAW_GATEWAY_TOKEN", stub_local.messages[0])
                self.assertNotIn("sk-super-secret-123456789", dispatch.operator_reply.summary)
                self.assertIn("hors cloud", dispatch.operator_reply.summary)
                record = services.memory.get(dispatch.promoted_memory_ids[0])
                self.assertEqual(record.metadata.get("privacy_view"), "full")
                self.assertEqual(record.metadata.get("openmemory_enabled"), False)
                self.assertEqual(record.metadata.get("embedding_provider"), "local_hash")
            finally:
                services.close()

    def test_gateway_s3_sensitive_message_stays_blocked_when_local_execution_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.config.execution_policy.local_model_enabled = True
                services.config.execution_policy.local_model_name = "qwen2.5:14b"
                services.router.execution_policy.local_model_enabled = True
                services.router.execution_policy.local_model_name = "qwen2.5:14b"
                failing_local = FailingLocalModelClient()
                services.router.local_model_client = failing_local
                services.gateway.local_model_client = failing_local
                services.openclaw.local_model_client = failing_local
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
                        text="Decision: OPENCLAW_GATEWAY_TOKEN=sk-super-secret-123456789",
                        thread_ref=ConversationThreadRef(thread_id="thread_s3_local_down", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "blocked")
                self.assertIn("Rien n'a ete envoye au cloud", dispatch.operator_reply.summary)
                self.assertEqual(len(failing_local.messages), 1)
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
