from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
        return services

    @staticmethod
    def _mark_runtime_ready(services, profile_name: str = "core"):
        session = services.runtime.open_session(profile_name=profile_name, owner="founder")
        services.runtime.record_runtime_state(
            RuntimeState(
                runtime_state_id=new_id("runtime_state"),
                session_id=session.session_id,
                verdict=RuntimeVerdict.READY,
                active_profile=profile_name,
            )
        )
        return session

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

    def test_gateway_keeps_recall_and_light_humor_questions_on_inline_chat_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                captured_messages: list[str] = []

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    captured_messages.append(message)
                    return "ok"

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]

                recall_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Rappelle-moi exactement les deux contraintes",
                        thread_ref=ConversationThreadRef(thread_id="thread_inline", channel="discord"),
                    ),
                )
                humor_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="petite blague avant de bosser: si je dis Theo, tu fais quoi ?",
                        thread_ref=ConversationThreadRef(thread_id="thread_inline", channel="discord"),
                    ),
                )

                recall_dispatch = services.gateway.dispatch_event(recall_event, target_profile="core")
                humor_dispatch = services.gateway.dispatch_event(humor_event, target_profile="core")

                self.assertEqual(recall_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(humor_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(recall_dispatch.metadata["model_provider"], "anthropic")
                self.assertEqual(humor_dispatch.metadata["model_provider"], "anthropic")
                self.assertEqual(len(captured_messages), 2)
            finally:
                services.close()

    def test_gateway_memory_question_now_triggers_mode_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                captured_messages: list[str] = []

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    captured_messages.append(message)
                    return "Reponse inline sur la memoire."

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]

                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=(
                            "Et donc si je te dis de regarder sur qui on s'inspire pour le gestion de memoire "
                            "tu repond quoi et en combien de temps ? Reponse longue demander + de 2000 caractere"
                        ),
                        thread_ref=ConversationThreadRef(thread_id="thread_inline_memory", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "approval_required")
                self.assertEqual(dispatch.metadata["classification"], "chat")
                self.assertEqual(dispatch.metadata["approval_metadata"]["approval_type"], "reasoning_escalation")
                self.assertIn("mode extreme", dispatch.operator_reply.summary.lower())
                ledger_row = services.database.fetchone(
                    "SELECT pending_approval_ids_json FROM thread_ledgers WHERE conversation_key = ?",
                    ("thread_inline_memory",),
                )
                self.assertIsNotNone(ledger_row)
                self.assertIn(dispatch.metadata["approval_id"], json.loads(str(ledger_row["pending_approval_ids_json"])))
                self.assertEqual(captured_messages, [])
            finally:
                services.close()

    def test_gateway_surfaces_intent_taxonomy_for_implicit_directive(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="j'aimerais qu'on garde une trace de ca dans un md",
                        thread_ref=ConversationThreadRef(thread_id="thread_manager_mode", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.metadata["classification"], "tasking")
                self.assertEqual(dispatch.metadata["intent_kind"], "directive_implicit")
                self.assertEqual(dispatch.metadata["delegation_level"], "prepare")
                self.assertEqual(dispatch.metadata["interaction_state"], "directive")
                self.assertEqual(dispatch.metadata["suggested_next_state"], "execution")
                self.assertEqual(dispatch.metadata["state_transition"], "directive->execution")
                self.assertTrue(dispatch.metadata["directive_detection"]["likely_directive"])
                self.assertEqual(dispatch.metadata["directive_detection"]["directive_form"], "implicit")
                self.assertEqual(dispatch.metadata["communication_mode"], "builder")
                self.assertEqual(dispatch.operator_reply.reply_kind, "ack")
            finally:
                services.close()

    def test_gateway_builds_action_contract_for_clear_directive(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="fais un fichier test.md dans le repo",
                        thread_ref=ConversationThreadRef(thread_id="thread_contract", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")
                contract = dispatch.metadata["action_contract"]

                self.assertEqual(contract["intent_kind"], "directive_explicit")
                self.assertEqual(contract["delegation_level"], "execute")
                self.assertEqual(contract["expected_output"], "markdown_document")
                self.assertEqual(contract["scope"], "repo")
                self.assertEqual(contract["risk_class"], "safe_write")
                self.assertTrue(contract["execution_ready"])
                self.assertFalse(contract["needs_clarification"])
                self.assertFalse(contract["needs_approval"])
                self.assertEqual(dispatch.operator_reply.reply_kind, "ack")
            finally:
                services.close()

    def test_gateway_asks_one_short_question_for_ambiguous_directive(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="on part la dessus, lance proprement",
                        thread_ref=ConversationThreadRef(thread_id="thread_contract", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")
                contract = dispatch.metadata["action_contract"]

                self.assertEqual(dispatch.operator_reply.reply_kind, "clarification_required")
                self.assertTrue(dispatch.metadata["clarification_gate"])
                self.assertTrue(contract["needs_clarification"])
                self.assertFalse(contract["execution_ready"])
                self.assertIn("livrable concret", dispatch.operator_reply.summary.lower())
                self.assertIsNone(dispatch.decision_id)
                self.assertIsNone(dispatch.mission_run_id)
            finally:
                services.close()

    def test_gateway_marks_destructive_directive_as_needing_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="supprime les anciens brouillons du repo",
                        thread_ref=ConversationThreadRef(thread_id="thread_contract", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")
                contract = dispatch.metadata["action_contract"]
                approval_rows = services.database.fetchall(
                    "SELECT approval_id, reason, status, payload_json FROM approval_records ORDER BY created_at DESC"
                )

                self.assertEqual(contract["risk_class"], "destructive")
                self.assertTrue(contract["needs_approval"])
                self.assertFalse(contract["execution_ready"])
                self.assertEqual(dispatch.operator_reply.reply_kind, "approval_required")
                self.assertIn("reponds go", dispatch.operator_reply.summary.lower())
                self.assertEqual(len(approval_rows), 1)
                self.assertIn("approval", str(approval_rows[0]["reason"]).lower())
            finally:
                services.close()

    def test_gateway_proposes_cost_confirmation_then_go_relaunches_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                launch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="fais un fichier audit_plan.md dans le repo",
                        thread_ref=ConversationThreadRef(thread_id="thread_cost_gate", channel="discord"),
                    ),
                )

                proposal_dispatch = services.gateway.dispatch_event(
                    launch_event,
                    target_profile="core",
                    metadata={"multi_worker": True},
                )
                approval_row = services.database.fetchone(
                    "SELECT approval_id, status, payload_json FROM approval_records ORDER BY created_at DESC LIMIT 1"
                )

                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "approval_required")
                self.assertIn("cout estime", proposal_dispatch.operator_reply.summary.lower())
                self.assertIn("temps estime", proposal_dispatch.operator_reply.summary.lower())
                self.assertIn("api utilisee", proposal_dispatch.operator_reply.summary.lower())
                self.assertIn("reponds go", proposal_dispatch.operator_reply.summary.lower())
                self.assertIsNotNone(approval_row)
                self.assertEqual(str(approval_row["status"]), "pending")

                go_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="go",
                        thread_ref=ConversationThreadRef(thread_id="thread_cost_gate", channel="discord"),
                    ),
                )

                go_dispatch = services.gateway.dispatch_event(go_event, target_profile="core")
                updated_approval = services.database.fetchone(
                    "SELECT status, payload_json FROM approval_records WHERE approval_id = ?",
                    (str(approval_row["approval_id"]),),
                )

                self.assertEqual(go_dispatch.metadata["resolved_action"], "approve_runtime_approval")
                self.assertEqual(go_dispatch.operator_reply.reply_kind, "ack")
                self.assertIn("operation lancee", go_dispatch.operator_reply.summary.lower())
                self.assertNotIn("api:", go_dispatch.operator_reply.summary.lower())
                self.assertIsNotNone(go_dispatch.mission_run_id)
                self.assertEqual(str(updated_approval["status"]), "approved")
            finally:
                services.close()

    def test_gateway_deep_research_requires_go_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services, profile_name="browser")
                launch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Deep research sur les meilleurs systemes de memoire pour le projet",
                        thread_ref=ConversationThreadRef(thread_id="thread_deep_research_gate", channel="discord"),
                    ),
                )
                scaffold_payload = {
                    "path": "D:\\ProjectOS\\project-os-core\\docs\\systems\\MEMORY_SYSTEMS_DOSSIER.md",
                    "relative_path": "docs/systems/MEMORY_SYSTEMS_DOSSIER.md",
                    "doc_name": "MEMORY_SYSTEMS_DOSSIER.md",
                    "kind": "system",
                    "title": "Memory Systems",
                    "keywords": ["deep research", "memoire", "forks"],
                    "recent_days": 30,
                    "created": True,
                }
                launch_payload = {
                    "job_id": "deep_research_123",
                    "job_path": "D:\\ProjectOS\\runtime\\deep_research\\deep_research_123\\request.json",
                    "launched": True,
                }
                launch_calls: list[dict[str, object]] = []

                def _fake_launch(*, event, scaffold):
                    launch_calls.append({"text": event.message.text, "scaffold": scaffold})
                    return launch_payload

                with patch("project_os_core.gateway.service.scaffold_research", return_value=scaffold_payload):
                    proposal_dispatch = services.gateway.dispatch_event(launch_event, target_profile="browser")
                approval_row = services.database.fetchone(
                    "SELECT approval_id, status, payload_json FROM approval_records ORDER BY created_at DESC LIMIT 1"
                )

                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "clarification_required")
                self.assertIn("profil recommande", proposal_dispatch.operator_reply.summary.lower())
                self.assertIn("intensite recommandee", proposal_dispatch.operator_reply.summary.lower())
                self.assertIn("component discovery", proposal_dispatch.operator_reply.summary.lower())
                self.assertIn("complexe", proposal_dispatch.operator_reply.summary.lower())
                self.assertEqual(proposal_dispatch.metadata["approval_metadata"]["approval_type"], "deep_research_mode_selection")
                self.assertEqual(str(approval_row["status"]), "pending")

                selection_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="component discovery + complexe",
                        thread_ref=ConversationThreadRef(thread_id="thread_deep_research_gate", channel="discord"),
                    ),
                )
                selection_dispatch = services.gateway.dispatch_event(selection_event, target_profile="browser")
                approval_after_selection = services.database.fetchone(
                    "SELECT approval_id, status, payload_json FROM approval_records WHERE approval_id = ?",
                    (str(approval_row["approval_id"]),),
                )
                approval_payload = json.loads(str(approval_after_selection["payload_json"]))

                self.assertEqual(selection_dispatch.metadata["resolved_action"], "update_runtime_approval_selection")
                self.assertEqual(selection_dispatch.operator_reply.reply_kind, "approval_required")
                self.assertIn("cout estime", selection_dispatch.operator_reply.summary.lower())
                self.assertIn("temps estime", selection_dispatch.operator_reply.summary.lower())
                self.assertIn("api utilisee", selection_dispatch.operator_reply.summary.lower())
                self.assertIn("reponds go", selection_dispatch.operator_reply.summary.lower())
                self.assertEqual(approval_payload["approval_type"], "deep_research_launch")
                self.assertEqual(approval_payload["research_profile"], "component_discovery")
                self.assertEqual(approval_payload["research_intensity"], "complex")

                go_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="go",
                        thread_ref=ConversationThreadRef(thread_id="thread_deep_research_gate", channel="discord"),
                    ),
                )
                with patch.object(services.deep_research, "launch_job_from_gateway", side_effect=_fake_launch):
                    go_dispatch = services.gateway.dispatch_event(go_event, target_profile="browser")
                updated_approval = services.database.fetchone(
                    "SELECT status FROM approval_records WHERE approval_id = ?",
                    (str(approval_row["approval_id"]),),
                )

                self.assertEqual(go_dispatch.metadata["resolved_action"], "approve_runtime_approval")
                self.assertEqual(go_dispatch.operator_reply.reply_kind, "ack")
                self.assertIn("recherche approfondie lancee", go_dispatch.operator_reply.summary.lower())
                self.assertIn("api:", go_dispatch.operator_reply.summary.lower())
                self.assertIn("pdf", go_dispatch.operator_reply.summary.lower())
                self.assertEqual(str(updated_approval["status"]), "approved")
                self.assertEqual(len(launch_calls), 1)
                self.assertEqual(launch_calls[0]["text"], launch_event.message.text)
                self.assertEqual(launch_calls[0]["scaffold"]["title"], "Memory Systems")
                self.assertEqual(launch_calls[0]["scaffold"]["research_profile"], "component_discovery")
                self.assertEqual(launch_calls[0]["scaffold"]["research_intensity"], "complex")
            finally:
                services.close()

    def test_gateway_deep_research_explicit_mode_skips_selection_and_goes_to_cost_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services, profile_name="browser")
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="deep research component discovery extreme sur les systemes de memoire pour le projet",
                        thread_ref=ConversationThreadRef(thread_id="thread_deep_research_explicit", channel="discord"),
                    ),
                )
                scaffold_payload = {
                    "path": "D:\\ProjectOS\\project-os-core\\docs\\systems\\MEMORY_SYSTEMS_DOSSIER.md",
                    "relative_path": "docs/systems/MEMORY_SYSTEMS_DOSSIER.md",
                    "doc_name": "MEMORY_SYSTEMS_DOSSIER.md",
                    "kind": "system",
                    "title": "Memory Systems",
                    "keywords": ["deep research", "memoire", "forks"],
                    "recent_days": 30,
                    "created": True,
                    "research_profile": "component_discovery",
                    "research_intensity": "extreme",
                    "recommended_profile": "component_discovery",
                    "recommended_intensity": "extreme",
                    "explicit_profile": "component_discovery",
                    "explicit_intensity": "extreme",
                }

                with patch("project_os_core.gateway.service.scaffold_research", return_value=scaffold_payload):
                    dispatch = services.gateway.dispatch_event(event, target_profile="browser")

                self.assertEqual(dispatch.operator_reply.reply_kind, "approval_required")
                self.assertIn("profil confirme", dispatch.operator_reply.summary.lower())
                self.assertIn("intensite confirmee", dispatch.operator_reply.summary.lower())
                self.assertIn("extreme", dispatch.operator_reply.summary.lower())
                self.assertIn("openai", dispatch.operator_reply.summary.lower())
                self.assertEqual(dispatch.metadata["approval_metadata"]["estimated_api_provider"], "openai")
                self.assertEqual(dispatch.metadata["approval_metadata"]["estimated_api_model"], "gpt-5")
                self.assertEqual(dispatch.metadata["approval_metadata"]["approval_type"], "deep_research_launch")
            finally:
                services.close()

    def test_gateway_deep_research_multi_profile_reply_stays_in_mode_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services, profile_name="browser")
                launch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="deep research extreme sur discord et openclaw",
                        thread_ref=ConversationThreadRef(thread_id="thread_deep_research_multi_profile", channel="discord"),
                    ),
                )
                scaffold_payload = {
                    "path": "D:\\ProjectOS\\project-os-core\\docs\\systems\\OPENCLAW_UPSTREAM_DOSSIER.md",
                    "relative_path": "docs/systems/OPENCLAW_UPSTREAM_DOSSIER.md",
                    "doc_name": "OPENCLAW_UPSTREAM_DOSSIER.md",
                    "kind": "system",
                    "title": "OpenClaw Upstream",
                    "keywords": ["deep research", "discord", "openclaw"],
                    "recent_days": 30,
                    "created": True,
                    "research_profile": "component_discovery",
                    "research_intensity": "extreme",
                    "recommended_profile": "component_discovery",
                    "recommended_intensity": "extreme",
                    "explicit_intensity": "extreme",
                }

                with patch("project_os_core.gateway.service.scaffold_research", return_value=scaffold_payload):
                    proposal_dispatch = services.gateway.dispatch_event(launch_event, target_profile="browser")

                selection_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="project audit, component discovery, domain audit",
                        thread_ref=ConversationThreadRef(thread_id="thread_deep_research_multi_profile", channel="discord"),
                    ),
                )
                selection_dispatch = services.gateway.dispatch_event(selection_event, target_profile="browser")
                approval_after_selection = services.database.fetchone(
                    "SELECT payload_json FROM approval_records ORDER BY created_at DESC LIMIT 1"
                )
                approval_payload = json.loads(str(approval_after_selection["payload_json"]))

                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "clarification_required")
                self.assertEqual(selection_dispatch.operator_reply.reply_kind, "clarification_required")
                self.assertIn("plusieurs profils", selection_dispatch.operator_reply.summary.lower())
                self.assertEqual(approval_payload["approval_type"], "deep_research_mode_selection")
                self.assertIsNone(approval_payload.get("selected_profile"))
            finally:
                services.close()

    def test_gateway_proposes_opus_for_serious_discussion_without_auto_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")
                calls: list[dict[str, str]] = []

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    calls.append({"message": message, "model": model, "route_reason": route_reason or ""})
                    return "Reponse inline."

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=(
                            "J'ai besoin d'une analyse architecture avec compromis pour la roadmap persona, "
                            "le cout et le niveau de challenge avant qu'on decide proprement."
                        ),
                        thread_ref=ConversationThreadRef(thread_id="thread_opus_escalation", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "approval_required")
                self.assertIn("mode simple", dispatch.operator_reply.summary.lower())
                self.assertIn("mode avance", dispatch.operator_reply.summary.lower())
                self.assertIn("mode extreme", dispatch.operator_reply.summary.lower())
                self.assertIn("mode recommande", dispatch.operator_reply.summary.lower())
                self.assertIn("cout estime", dispatch.operator_reply.summary.lower())
                self.assertIn("temps estime", dispatch.operator_reply.summary.lower())
                self.assertIn("api utilisee", dispatch.operator_reply.summary.lower())
                self.assertIn("simple/avance/extreme", dispatch.operator_reply.summary.lower())
                self.assertEqual(dispatch.metadata["approval_metadata"]["approval_type"], "reasoning_escalation")
                self.assertEqual(calls, [])
            finally:
                services.close()

    def test_gateway_reasoning_escalation_go_runs_opus_and_stop_keeps_sonnet(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")
                calls: list[dict[str, str]] = []

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    calls.append({"message": message, "model": model, "route_reason": route_reason or ""})
                    return "Opus a pris le relais."

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                serious_text = (
                    "Je veux une analyse architecture et compromis de la roadmap persona, "
                    "avec priorites et arbitrages de cout avant de trancher."
                )
                launch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=serious_text,
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_go", channel="discord"),
                    ),
                )

                proposal_dispatch = services.gateway.dispatch_event(launch_event, target_profile="core")
                approval_row = services.database.fetchone(
                    "SELECT approval_id, status FROM approval_records ORDER BY created_at DESC LIMIT 1"
                )

                stop_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="stop",
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_go", channel="discord"),
                    ),
                )
                stop_dispatch = services.gateway.dispatch_event(stop_event, target_profile="core")

                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "approval_required")
                self.assertEqual(stop_dispatch.metadata["resolved_action"], "reject_runtime_approval")
                self.assertEqual(stop_dispatch.operator_reply.reply_kind, "ack")
                self.assertIn("je ne lance pas", stop_dispatch.operator_reply.summary.lower())
                self.assertEqual(calls, [])

                relaunch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=serious_text,
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_go_2", channel="discord"),
                    ),
                )
                proposal_dispatch = services.gateway.dispatch_event(relaunch_event, target_profile="core")
                second_approval_row = services.database.fetchone(
                    "SELECT approval_id, status FROM approval_records ORDER BY created_at DESC LIMIT 1"
                )
                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "approval_required")

                go_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="go",
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_go_2", channel="discord"),
                    ),
                )
                go_dispatch = services.gateway.dispatch_event(go_event, target_profile="core")
                updated_approval = services.database.fetchone(
                    "SELECT status FROM approval_records WHERE approval_id = ?",
                    (str(second_approval_row["approval_id"]),),
                )

                self.assertEqual(go_dispatch.metadata["resolved_action"], "approve_runtime_approval")
                self.assertEqual(go_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertIn("opus a pris le relais", go_dispatch.operator_reply.summary.lower())
                self.assertGreaterEqual(len(calls), 1)
                self.assertEqual(calls[-1]["model"], services.config.execution_policy.discord_opus_model)
                self.assertEqual(calls[-1]["route_reason"], "operator_forced_opus_route")
                self.assertEqual(str(updated_approval["status"]), "approved")
            finally:
                services.close()

    def test_gateway_reasoning_escalation_can_switch_to_avance_before_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")
                calls: list[dict[str, str]] = []

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    calls.append({"message": message, "model": model, "route_reason": route_reason or ""})
                    return "Sonnet avance ok."

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                serious_text = (
                    "Et donc si je te dis de regarder sur qui on s'inspire pour la gestion memoire, "
                    "tu reponds quoi et en combien de temps ? Reponse longue demandee + de 2000 caracteres."
                )
                launch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=serious_text,
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_avance", channel="discord"),
                    ),
                )

                proposal_dispatch = services.gateway.dispatch_event(launch_event, target_profile="core")
                select_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="avance",
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_avance", channel="discord"),
                    ),
                )
                select_dispatch = services.gateway.dispatch_event(select_event, target_profile="core")
                go_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="go",
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_avance", channel="discord"),
                    ),
                )
                go_dispatch = services.gateway.dispatch_event(go_event, target_profile="core")

                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "approval_required")
                self.assertEqual(select_dispatch.metadata["resolved_action"], "update_runtime_approval_selection")
                self.assertIn("mode selectionne: mode avance", select_dispatch.operator_reply.summary.lower())
                self.assertEqual(go_dispatch.metadata["resolved_action"], "approve_runtime_approval")
                self.assertEqual(go_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertGreaterEqual(len(calls), 1)
                self.assertEqual(calls[-1]["model"], services.config.execution_policy.discord_simple_model)
                self.assertEqual(calls[-1]["route_reason"], "operator_forced_sonnet_route")
                self.assertIn("mode avance discord", calls[-1]["message"].lower())
            finally:
                services.close()

    def test_gateway_reasoning_escalation_accepts_go_plus_mode_in_one_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")
                calls: list[dict[str, str]] = []

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    calls.append({"message": message, "model": model, "route_reason": route_reason or ""})
                    return "Mode applique."

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                serious_text = (
                    "Et donc si je te dis de regarder sur qui on s'inspire pour la gestion memoire, "
                    "tu reponds quoi et en combien de temps ? Reponse longue demandee + de 2000 caracteres."
                )
                launch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=serious_text,
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_go_mode", channel="discord"),
                    ),
                )

                proposal_dispatch = services.gateway.dispatch_event(launch_event, target_profile="core")
                go_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="go avance",
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_go_mode", channel="discord"),
                    ),
                )
                go_dispatch = services.gateway.dispatch_event(go_event, target_profile="core")

                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "approval_required")
                self.assertEqual(go_dispatch.metadata["resolved_action"], "approve_runtime_approval")
                self.assertEqual(go_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertGreaterEqual(len(calls), 1)
                self.assertEqual(calls[-1]["model"], services.config.execution_policy.discord_simple_model)
                self.assertEqual(calls[-1]["route_reason"], "operator_forced_sonnet_route")
                self.assertIn("mode avance discord", calls[-1]["message"].lower())
            finally:
                services.close()

    def test_gateway_reasoning_escalation_longform_go_returns_pdf_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    return (
                        "Si tu me demandes de regarder sur qui on s'inspire pour la gestion memoire, "
                        "je commence par inspecter la doc, le code et les choix de persistance deja poses. "
                    ) * 8

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                serious_text = (
                    "Et donc si je te dis de regarder sur qui on s'inspire pour la gestion memoire, "
                    "tu reponds quoi et en combien de temps ? Reponse longue demandee + de 2000 caracteres."
                )
                launch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=serious_text,
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_pdf", channel="discord"),
                    ),
                )
                go_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="go",
                        thread_ref=ConversationThreadRef(thread_id="thread_reasoning_pdf", channel="discord"),
                    ),
                )

                proposal_dispatch = services.gateway.dispatch_event(launch_event, target_profile="core")
                go_dispatch = services.gateway.dispatch_event(go_event, target_profile="core")

                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "approval_required")
                self.assertEqual(go_dispatch.metadata["resolved_action"], "approve_runtime_approval")
                self.assertEqual(go_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertIsNotNone(go_dispatch.operator_reply.response_manifest)
                manifest = go_dispatch.operator_reply.response_manifest
                assert manifest is not None
                self.assertEqual(manifest.delivery_mode, "artifact_summary")
                self.assertEqual(go_dispatch.metadata["response_delivery_mode"], "artifact_summary")
                self.assertEqual(len(manifest.attachments), 1)
                self.assertEqual(manifest.attachments[0].mime_type, "application/pdf")
                self.assertIn("PDF joint", go_dispatch.operator_reply.summary)
                artifact_row = services.database.fetchone(
                    """
                    SELECT artifact_id, cold_artifact_id, cold_path
                    FROM artifact_ledger_entries
                    WHERE artifact_id = ?
                    """,
                    (manifest.review_artifact_id,),
                )
                self.assertIsNotNone(artifact_row)
                self.assertEqual(str(artifact_row["artifact_id"]), manifest.review_artifact_id)
                self.assertTrue(str(artifact_row["cold_artifact_id"] or "").strip())
                self.assertTrue(Path(str(artifact_row["cold_path"])).exists())
                thread_row = services.database.fetchone(
                    """
                    SELECT last_pdf_artifact_id
                    FROM thread_ledgers
                    WHERE conversation_key = ?
                    """,
                    ("thread_reasoning_pdf",),
                )
                self.assertIsNotNone(thread_row)
                self.assertEqual(str(thread_row["last_pdf_artifact_id"]), manifest.review_artifact_id)
                analysis_rows = services.database.fetchall(
                    """
                    SELECT object_type
                    FROM analysis_objects
                    WHERE conversation_key = ?
                    ORDER BY updated_at DESC
                    """,
                    ("thread_reasoning_pdf",),
                )
                self.assertTrue(any(str(row["object_type"]) == "source_pdf" for row in analysis_rows))
            finally:
                services.close()

    def test_gateway_followup_after_pdf_uses_stateful_brain_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")
                captured: list[dict[str, object]] = []

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    captured.append(
                        {
                            "message": message,
                            "route_reason": route_reason,
                            "rendered": services.gateway._simple_chat_user_message(
                                message,
                                provider="anthropic",
                                model=model,
                                route_reason=route_reason,
                                context_bundle=context_bundle,
                            ),
                        }
                    )
                    if "mode extreme discord" in message.lower():
                        return (
                            "Si tu me demandes de regarder sur qui on s'inspire pour la gestion memoire, "
                            "je commence par inspecter la doc, le code et les choix de persistance deja poses. "
                        ) * 8
                    return "Sans analyse profonde du code, je lui donnerais 6/10 pour l'intention et 4/10 en confiance factuelle."

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                serious_text = (
                    "Et donc si je te dis de regarder sur qui on s'inspire pour la gestion memoire, "
                    "tu reponds quoi et en combien de temps ? Reponse longue demandee + de 2000 caracteres."
                )
                launch_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=serious_text,
                        thread_ref=ConversationThreadRef(thread_id="thread_followup_pdf", channel="discord"),
                    ),
                )
                go_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="go",
                        thread_ref=ConversationThreadRef(thread_id="thread_followup_pdf", channel="discord"),
                    ),
                )
                followup_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="et tu lui donnerais une note de combien ?",
                        thread_ref=ConversationThreadRef(thread_id="thread_followup_pdf", channel="discord"),
                    ),
                )

                proposal_dispatch = services.gateway.dispatch_event(launch_event, target_profile="core")
                go_dispatch = services.gateway.dispatch_event(go_event, target_profile="core")
                followup_dispatch = services.gateway.dispatch_event(followup_event, target_profile="core")

                self.assertEqual(proposal_dispatch.operator_reply.reply_kind, "approval_required")
                self.assertEqual(go_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(followup_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(followup_dispatch.metadata["classification"], "chat")
                self.assertEqual(followup_dispatch.metadata["brain_resolution_kind"], "answer_about_last_pdf")
                self.assertIn("Ledger canonique du thread:", str(captured[-1]["rendered"]))
                self.assertIn("sujet actif:", str(captured[-1]["rendered"]).lower())
                self.assertIn("decision recente:", str(captured[-1]["rendered"]).lower())
                self.assertIn("Digests:", str(captured[-1]["rendered"]))
                self.assertIn("dernier pdf connu", str(captured[-1]["rendered"]).lower())
            finally:
                services.close()

    def test_gateway_ambiguous_short_followup_requests_clarification(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services, "core")
                call_count = {"chat": 0}

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    del message, model, route_reason, context_bundle
                    call_count["chat"] += 1
                    return (
                        "Je garde la facade Discord naturelle.\n"
                        "Prochain pas: verifier que le fallback PDF ne se declenche pas trop tot."
                    )

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                services.gateway._call_local_chat = lambda **kwargs: _stub_simple_chat(kwargs.get("message", ""))  # type: ignore[method-assign]
                services.gateway._should_inline_chat = lambda event, decision: True  # type: ignore[method-assign]

                first_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Explique-moi le nettoyage visible de la facade Discord.",
                        thread_ref=ConversationThreadRef(thread_id="thread_followup_clarify", channel="discord"),
                    ),
                )
                second_event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="et du coup ?",
                        thread_ref=ConversationThreadRef(thread_id="thread_followup_clarify", channel="discord"),
                    ),
                )

                first_dispatch = services.gateway.dispatch_event(first_event, target_profile="core")
                second_dispatch = services.gateway.dispatch_event(second_event, target_profile="core")

                self.assertEqual(first_dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(second_dispatch.operator_reply.reply_kind, "clarification_required")
                self.assertEqual(second_dispatch.metadata["brain_clarification"], True)
                self.assertEqual(second_dispatch.metadata["brain_resolution_kind"], "clarification_needed")
                self.assertIn("ma derniere reponse", second_dispatch.operator_reply.summary.lower())
                self.assertEqual(call_count["chat"], 1)
            finally:
                services.close()

    def test_gateway_persists_ingress_artifacts_for_long_text_and_attachments(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="plan detaille " * 450,
                        thread_ref=ConversationThreadRef(thread_id="thread_ingress", channel="discord"),
                        attachments=[
                            OperatorAttachment(
                                attachment_id=new_id("attachment"),
                                name="meeting-transcript.m4a",
                                kind="audio",
                                mime_type="audio/mp4",
                            ),
                            OperatorAttachment(
                                attachment_id=new_id("attachment"),
                                name="brief.pdf",
                                kind="document",
                                mime_type="application/pdf",
                            ),
                        ],
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                artifact_rows = services.database.fetchall(
                    "SELECT artifact_kind, owner_id, path FROM artifact_pointers WHERE owner_type = ? ORDER BY artifact_kind",
                    ("channel_event",),
                )
                self.assertEqual(len(artifact_rows), 6)
                artifact_kinds = [str(row["artifact_kind"]) for row in artifact_rows]
                self.assertIn("ingress_attachment_manifest", artifact_kinds)
                self.assertEqual(artifact_kinds.count("ingress_attachment_catalog"), 2)
                self.assertIn("ingress_input", artifact_kinds)
                self.assertIn("long_context_segments", artifact_kinds)
                self.assertIn("long_context_workflow", artifact_kinds)
                for row in artifact_rows:
                    self.assertTrue(Path(str(row["path"])).exists())

                candidate_row = services.database.fetchone(
                    "SELECT payload_json FROM conversation_memory_candidates WHERE candidate_id = ?",
                    (dispatch.memory_candidate_id,),
                )
                self.assertIsNotNone(candidate_row)
                payload = json.loads(str(candidate_row["payload_json"]))
                self.assertEqual(payload["input_profile"], "transcript")
                self.assertEqual(payload["source_artifact_count"], 4)
                self.assertEqual(len(payload["source_artifact_ids"]), 4)
                self.assertEqual(payload["long_context_phase_status"], "ready")
                self.assertTrue(payload["long_context_summary"].startswith("Input transcript traite"))
                self.assertEqual(len(payload["long_context_artifact_ids"]), 2)
                self.assertIn("workflow_id", payload["long_context_digest"])
                self.assertGreaterEqual(payload["long_context_digest"]["segment_count"], 2)
                self.assertEqual(dispatch.metadata["input_profile"], "transcript")
                self.assertEqual(len(dispatch.metadata["source_artifact_ids"]), 4)
                self.assertEqual(len(dispatch.metadata["long_context_artifact_ids"]), 2)
                self.assertEqual(dispatch.metadata["long_context_workflow_id"], payload["long_context_workflow_id"])
            finally:
                services.close()

    def test_gateway_ingests_local_pdf_attachments_as_source_objects_with_cold_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                tmp_path = Path(tmp)
                pdf_a = tmp_path / "a.pdf"
                pdf_b = tmp_path / "b.pdf"
                pdf_payload = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
                pdf_a.write_bytes(pdf_payload)
                pdf_b.write_bytes(pdf_payload)
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="voici deux pdf a garder en memoire",
                        thread_ref=ConversationThreadRef(thread_id="thread_local_pdfs", channel="discord"),
                        attachments=[
                            OperatorAttachment(
                                attachment_id=new_id("attachment"),
                                name="a.pdf",
                                kind="document",
                                mime_type="application/pdf",
                                path=str(pdf_a),
                            ),
                            OperatorAttachment(
                                attachment_id=new_id("attachment"),
                                name="b.pdf",
                                kind="document",
                                mime_type="application/pdf",
                                path=str(pdf_b),
                            ),
                        ],
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertGreaterEqual(len(dispatch.metadata["source_artifact_ids"]), 4)
                ledger_rows = services.database.fetchall(
                    """
                    SELECT artifact_kind, cold_artifact_id, cold_path
                    FROM artifact_ledger_entries
                    WHERE conversation_key = ?
                    ORDER BY created_at ASC
                    """,
                    ("thread_local_pdfs",),
                )
                pdf_rows = [row for row in ledger_rows if str(row["artifact_kind"]) == "ingress_attachment_pdf"]
                self.assertEqual(len(pdf_rows), 2)
                for row in pdf_rows:
                    self.assertTrue(str(row["cold_artifact_id"] or "").strip())
                    self.assertTrue(Path(str(row["cold_path"])).exists())
                analysis_rows = services.database.fetchall(
                    """
                    SELECT object_type
                    FROM analysis_objects
                    WHERE conversation_key = ?
                    ORDER BY updated_at DESC
                    """,
                    ("thread_local_pdfs",),
                )
                self.assertGreaterEqual(sum(1 for row in analysis_rows if str(row["object_type"]) == "source_pdf"), 2)
            finally:
                services.close()

    def test_stateful_artifact_registration_is_idempotent_for_same_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                tmp_path = Path(tmp)
                pdf_path = tmp_path / "single.pdf"
                pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="pdf unique",
                        thread_ref=ConversationThreadRef(thread_id="thread_idempotent_pdf", channel="discord"),
                    ),
                )
                pointer = services.gateway._write_gateway_binary_artifact(
                    owner_type="channel_event",
                    owner_id=event.event_id,
                    artifact_kind="ingress_attachment_pdf",
                    payload=pdf_path.read_bytes(),
                    suffix=".pdf",
                )

                services.gateway._register_stateful_artifact(
                    event=event,
                    pointer=pointer,
                    owner_type="channel_event",
                    owner_id=event.event_id,
                    object_type="source_pdf",
                    title="single.pdf",
                    summary_short="single pdf",
                    summary_full="single pdf",
                )
                services.gateway._register_stateful_artifact(
                    event=event,
                    pointer=pointer,
                    owner_type="channel_event",
                    owner_id=event.event_id,
                    object_type="source_pdf",
                    title="single.pdf",
                    summary_short="single pdf",
                    summary_full="single pdf",
                )

                artifact_rows = services.database.fetchall(
                    "SELECT artifact_id FROM artifact_ledger_entries WHERE artifact_id = ?",
                    (pointer.artifact_id,),
                )
                object_rows = services.database.fetchall(
                    "SELECT object_id FROM analysis_objects WHERE artifact_ids_json LIKE ?",
                    (f'%\"{pointer.artifact_id}\"%',),
                )
                self.assertEqual(len(artifact_rows), 1)
                self.assertEqual(len(object_rows), 1)
            finally:
                services.close()

    def test_gateway_backfill_stateful_recent_rebuilds_state_from_recent_discord_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                tmp_path = Path(tmp)
                pdf_path = tmp_path / "backfill.pdf"
                pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="garde ce pdf pour le backfill",
                        thread_ref=ConversationThreadRef(thread_id="thread_backfill_recent", channel="discord"),
                        attachments=[
                            OperatorAttachment(
                                attachment_id=new_id("attachment"),
                                name="backfill.pdf",
                                kind="document",
                                mime_type="application/pdf",
                                path=str(pdf_path),
                            )
                        ],
                    ),
                )

                services.gateway.dispatch_event(event, target_profile="core")
                services.database.execute("DELETE FROM artifact_ledger_entries")
                services.database.execute("DELETE FROM analysis_objects")
                services.database.execute("DELETE FROM thread_ledgers WHERE conversation_key = ?", ("thread_backfill_recent",))

                payload = services.gateway.backfill_stateful_recent(since_hours=24)

                self.assertEqual(payload["status"], "ok")
                self.assertGreaterEqual(payload["events_backfilled"], 1)
                thread_row = services.database.fetchone(
                    "SELECT thread_ledger_id FROM thread_ledgers WHERE conversation_key = ?",
                    ("thread_backfill_recent",),
                )
                self.assertIsNotNone(thread_row)
                analysis_rows = services.database.fetchall(
                    "SELECT object_type FROM analysis_objects WHERE conversation_key = ?",
                    ("thread_backfill_recent",),
                )
                self.assertTrue(any(str(row["object_type"]) == "source_pdf" for row in analysis_rows))
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

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
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
                self.assertTrue(dispatch.operator_reply.summary.startswith("[Local S3 / Ollama]"))
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

    def test_gateway_dispatch_handles_racy_duplicate_ingress_without_crashing(self):
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

                def _build_event(event_id: str) -> ChannelEvent:
                    return ChannelEvent(
                        event_id=event_id,
                        surface="discord",
                        event_type="message.created",
                        raw_payload={"source": "openclaw"},
                        message=OperatorMessage(
                            message_id=new_id("message"),
                            actor_id="founder",
                            channel="discord",
                            text="@ProjectOS test de doublon OpenClaw.",
                            thread_ref=ConversationThreadRef(
                                thread_id="thread_race",
                                channel="discord",
                                external_thread_id="channel:discord-thread-race",
                            ),
                            metadata={
                                "source": "openclaw",
                                "message_id": "discord-message-race",
                            },
                        ),
                    )

                first = services.gateway.dispatch_event(_build_event(new_id("channel_event")), target_profile="core")
                original_duplicate_lookup = services.gateway._duplicate_channel_event_id
                lookup_state = {"calls": 0}

                def _staged_duplicate_lookup(event):
                    lookup_state["calls"] += 1
                    if lookup_state["calls"] == 1:
                        return None
                    return original_duplicate_lookup(event)

                services.gateway._duplicate_channel_event_id = _staged_duplicate_lookup  # type: ignore[method-assign]
                second = services.gateway.dispatch_event(_build_event(new_id("channel_event")), target_profile="core")

                self.assertFalse(first.metadata.get("duplicate_ingress", False))
                self.assertTrue(second.metadata.get("duplicate_ingress"))
                self.assertEqual(second.operator_reply.reply_kind, "ack")

                channel_event_count = services.database.fetchone("SELECT COUNT(*) AS count FROM channel_events")
                dispatch_count = services.database.fetchone("SELECT COUNT(*) AS count FROM gateway_dispatch_results")
                self.assertEqual(channel_event_count["count"], 1)
                self.assertEqual(dispatch_count["count"], 1)
            finally:
                services.close()

    def test_simple_chat_prompt_preserves_project_os_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                system_prompt = services.gateway._simple_chat_system_prompt()
                anthropic_blocks = services.gateway._simple_chat_system_blocks()
                user_prompt = services.gateway._simple_chat_user_message(
                    "et tu connecter au projet vois tu les dossier ? quelle api utilise tu",
                    provider="anthropic",
                    model="claude-opus-4-1",
                    route_reason="operator_forced_opus_route",
                )

                self.assertIn("role: Voix operateur de Project OS", system_prompt)
                self.assertIn("Pote solide", system_prompt)
                self.assertIn("<truth_rules>", system_prompt)
                self.assertEqual(anthropic_blocks[0]["cache_control"], {"type": "ephemeral"})
                self.assertIn("managed_workspace: D:/ProjectOS/project-os-core", user_prompt)
                self.assertIn("current_provider: anthropic", user_prompt)
                self.assertIn("current_model: claude-opus-4-1", user_prompt)
                self.assertIn("Message fondateur pour ce tour:", user_prompt)
                self.assertIn("quelle api utilise tu", user_prompt)
            finally:
                services.close()

    def test_discord_prefix_claude_forces_anthropic_route_and_strips_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")
                captured: dict[str, str] = {}

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    captured["message"] = message
                    captured["model"] = model
                    captured["route_reason"] = route_reason or ""
                    return "Claude override ok."

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="CLAUDE qui est tu ?",
                        thread_ref=ConversationThreadRef(thread_id="thread_claude", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(dispatch.metadata["requested_provider"], "anthropic")
                self.assertEqual(dispatch.metadata["message_prefix_consumed"], "CLAUDE")
                self.assertEqual(dispatch.discord_run_card["metadata"]["route_reason"], "operator_forced_anthropic_route")
                self.assertEqual(captured["message"], "qui est tu ?")
                self.assertEqual(captured["model"], services.config.execution_policy.discord_simple_model)
                self.assertEqual(captured["route_reason"], "operator_forced_anthropic_route")
            finally:
                services.close()

    def test_discord_prefix_opus_forces_opus_model_and_strips_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")
                captured: dict[str, str] = {}

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    captured["message"] = message
                    captured["model"] = model
                    captured["route_reason"] = route_reason or ""
                    return "Opus override ok."

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="OPUS challenge mon idee de naming",
                        thread_ref=ConversationThreadRef(thread_id="thread_opus", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(dispatch.metadata["requested_provider"], "anthropic")
                self.assertEqual(dispatch.metadata["message_prefix_consumed"], "OPUS")
                self.assertEqual(dispatch.discord_run_card["metadata"]["route_reason"], "operator_forced_opus_route")
                self.assertEqual(dispatch.discord_run_card["metadata"]["model"], services.config.execution_policy.discord_opus_model)
                self.assertEqual(captured["message"], "challenge mon idee de naming")
                self.assertEqual(captured["model"], services.config.execution_policy.discord_opus_model)
                self.assertEqual(captured["route_reason"], "operator_forced_opus_route")
            finally:
                services.close()

    def test_discord_prefix_gpt_forces_openai_route_and_strips_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services, "core")
                captured: dict[str, str] = {}

                def _stub_openai_chat(
                    message: str,
                    *,
                    model: str | None,
                    reasoning_effort: str | None,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    captured["message"] = message
                    captured["model"] = model or ""
                    captured["reasoning_effort"] = reasoning_effort or ""
                    captured["route_reason"] = route_reason or ""
                    return "GPT override ok."

                services.gateway._call_openai_chat = _stub_openai_chat  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="GPT: propose trois options concretes",
                        thread_ref=ConversationThreadRef(thread_id="thread_gpt", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(dispatch.metadata["requested_provider"], "openai")
                self.assertEqual(dispatch.metadata["message_prefix_consumed"], "GPT")
                self.assertEqual(dispatch.discord_run_card["metadata"]["route_reason"], "operator_forced_openai_route")
                self.assertEqual(captured["message"], "propose trois options concretes")
                self.assertEqual(captured["model"], services.config.execution_policy.default_model)
                self.assertEqual(captured["route_reason"], "operator_forced_openai_route")
            finally:
                services.close()

    def test_discord_prefix_local_forces_local_route_when_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.config.execution_policy.local_model_enabled = True
                services.config.execution_policy.local_model_name = "qwen2.5:14b"
                services.router.execution_policy.local_model_enabled = True
                services.router.execution_policy.local_model_name = "qwen2.5:14b"
                stub_local = StubLocalModelClient(content="Je reste local et je ne repete rien de sensible.")
                services.router.local_model_client = stub_local
                services.gateway.local_model_client = stub_local
                services.openclaw.local_model_client = stub_local
                self._mark_runtime_ready(services, "core")
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="LOCAL parle moi de ce sujet",
                        thread_ref=ConversationThreadRef(thread_id="thread_local", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(dispatch.discord_run_card["metadata"]["route_reason"], "operator_forced_local_route")
                self.assertEqual(len(stub_local.messages), 1)
                self.assertIn("Message fondateur pour ce tour:\nparle moi de ce sujet", stub_local.messages[0])
                self.assertIn("Contexte session recent:", stub_local.messages[0])
                self.assertTrue(dispatch.operator_reply.summary.startswith("[Local / Ollama]"))
            finally:
                services.close()

    def test_discord_prefix_local_blocks_when_local_lane_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services, "core")
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="LOCAL explique ce point",
                        thread_ref=ConversationThreadRef(thread_id="thread_local_blocked", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "blocked")
                self.assertIn("voie locale demandee", dispatch.operator_reply.summary)
                self.assertEqual(dispatch.discord_run_card["metadata"]["route_reason"], "operator_forced_local_unavailable")
            finally:
                services.close()

    def test_s3_prefix_override_still_routes_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.config.execution_policy.local_model_enabled = True
                services.config.execution_policy.local_model_name = "qwen2.5:14b"
                services.router.execution_policy.local_model_enabled = True
                services.router.execution_policy.local_model_name = "qwen2.5:14b"
                stub_local = StubLocalModelClient(content="Secret garde localement. Rien ne sort.")
                services.router.local_model_client = stub_local
                services.gateway.local_model_client = stub_local
                services.openclaw.local_model_client = stub_local
                self._mark_runtime_ready(services, "core")
                openai_calls: list[str] = []

                def _stub_openai_chat(
                    message: str,
                    *,
                    model: str | None,
                    reasoning_effort: str | None,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    openai_calls.append(message)
                    return "should_not_happen"

                services.gateway._call_openai_chat = _stub_openai_chat  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="GPT OPENCLAW_GATEWAY_TOKEN=sk-super-secret-123456789",
                        thread_ref=ConversationThreadRef(thread_id="thread_s3_override", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "chat_response")
                self.assertEqual(dispatch.metadata["sensitivity_class"], SensitivityClass.S3.value)
                self.assertEqual(dispatch.discord_run_card["metadata"]["route_reason"], "s3_local_route")
                self.assertEqual(openai_calls, [])
                self.assertTrue(dispatch.operator_reply.summary.startswith("[Local S3 / Ollama]"))
            finally:
                services.close()

    def test_no_prefix_keeps_default_discord_simple_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
                self._mark_runtime_ready(services, "core")
                captured_messages: list[str] = []

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    captured_messages.append(message)
                    return "route par defaut"

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="qui est tu ?",
                        thread_ref=ConversationThreadRef(thread_id="thread_default", channel="discord"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.operator_reply.reply_kind, "chat_response")
                self.assertIsNone(dispatch.metadata["requested_provider"])
                self.assertEqual(dispatch.discord_run_card["metadata"]["route_reason"], "discord_simple_route")
                self.assertEqual(captured_messages, ["qui est tu ?"])
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
