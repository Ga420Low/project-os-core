from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.models import (
    ChannelEvent,
    ConversationThreadRef,
    OperatorAttachment,
    OperatorMessage,
    RuntimeState,
    RuntimeVerdict,
    new_id,
)
from project_os_core.session.state import SessionSnapshot
from project_os_core.gateway.context_builder import ThreadTurn
from project_os_core.services import build_app_services


class GatewayContextBuilderTests(unittest.TestCase):
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
        policy_path = tmp_path / "runtime_policy.json"
        policy_path.write_text(json.dumps({"secret_config": {"mode": "infisical_first", "required_secret_names": []}}), encoding="utf-8")
        return build_app_services(config_path=str(config_path), policy_path=str(policy_path))

    @staticmethod
    def _mark_runtime_ready(services):
        session = services.runtime.open_session(profile_name="core", owner="founder")
        services.runtime.record_runtime_state(
            RuntimeState(
                runtime_state_id=new_id("runtime_state"),
                session_id=session.session_id,
                verdict=RuntimeVerdict.READY,
                active_profile="core",
            )
        )

    def test_context_builder_preserves_recent_thread_and_handoff_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
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
                            "context_bundle": context_bundle,
                            "rendered": services.gateway._simple_chat_user_message(
                                message,
                                provider="anthropic",
                                model=model,
                                route_reason=route_reason,
                                context_bundle=context_bundle,
                            ),
                        }
                    )
                    return "ok"

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]

                first = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="On garde le browser worker pour les formulaires.",
                        thread_ref=ConversationThreadRef(
                            thread_id="thread_ctx",
                            channel="discord",
                            external_thread_id="channel:thread_ctx",
                        ),
                    ),
                )
                services.gateway.dispatch_event(first, target_profile="core")

                second = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="OPUS brainstorm trois options d architecture",
                        thread_ref=ConversationThreadRef(
                            thread_id="thread_ctx",
                            channel="discord",
                            external_thread_id="channel:thread_ctx",
                        ),
                    ),
                )
                dispatch = services.gateway.dispatch_event(second, target_profile="core")

                self.assertEqual(dispatch.metadata["mood_hint"], "brainstorming")
                self.assertIsInstance(dispatch.metadata["handoff_contract"], dict)
                self.assertEqual(
                    dispatch.metadata["handoff_contract"]["target_model"],
                    services.config.execution_policy.discord_opus_model,
                )
                rendered = str(captured[-1]["rendered"])
                self.assertIn("Historique recent du thread:", rendered)
                self.assertIn("On garde le browser worker pour les formulaires.", rendered)
                self.assertIn('"raw_user_intent": "brainstorm trois options d architecture"', rendered)
                self.assertIn("Contexte session recent:", rendered)
                self.assertIn("detected_mood: brainstorming", rendered)
            finally:
                services.close()

    def test_identity_prompt_does_not_leak_pending_clarifications_or_thread_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
                captured: list[dict[str, object]] = []

                snapshot = SessionSnapshot(
                    pending_clarifications=[
                        {
                            "report_id": "clarif_1",
                            "question": "Confirme si je dois integrer sur l'etat sale actuel.",
                            "branch_name": "codex/api-runs-tui-live",
                        }
                    ],
                    pending_contracts=[
                        {
                            "contract_id": "contract_1",
                            "branch_name": "codex/api-runs-tui-live",
                            "objective": "Patch live",
                            "estimated_cost": 1.0,
                        }
                    ],
                    active_missions=[{"objective": "Lot historique", "status": "running"}],
                    last_founder_message_at="2026-03-15T18:12:55+00:00",
                )

                services.session_state.load = lambda: snapshot  # type: ignore[method-assign]
                services.gateway.context_builder._load_recent_thread_messages = lambda **_: (
                    ThreadTurn(
                        role="founder",
                        text="quelle api utilise tu est il y a t-il des beug entre la connexion project os open claw claude ?",
                        created_at="2026-03-15T18:12:55+00:00",
                    ),
                )
                services.gateway.context_builder._load_recent_operator_replies = lambda **_: (
                    ThreadTurn(
                        role="project_os",
                        text="Ancienne reponse bruitee avec une clarification en attente.",
                        created_at="2026-03-15T18:12:56+00:00",
                    ),
                )

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
                            "context_bundle": context_bundle,
                            "rendered": services.gateway._simple_chat_user_message(
                                message,
                                provider="anthropic",
                                model=model,
                                route_reason=route_reason,
                                context_bundle=context_bundle,
                            ),
                        }
                    )
                    return "ok"

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                services.gateway._should_inline_chat = lambda event, decision: True  # type: ignore[method-assign]

                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="test qui est tu",
                        thread_ref=ConversationThreadRef(
                            thread_id="thread_identity",
                            channel="discord",
                            external_thread_id="channel:thread_identity",
                        ),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.metadata["query_scope"], "identity")
                self.assertEqual(dispatch.operator_reply.metadata["query_scope"], "identity")
                self.assertEqual(dispatch.metadata["handoff_contract"]["pending_questions"], [])
                rendered = str(captured[-1]["rendered"])
                self.assertIn("query_scope: identity", rendered)
                self.assertIn("current_provider: anthropic", rendered)
                self.assertNotIn("Contexte session recent:", rendered)
                self.assertNotIn("Historique recent du thread:", rendered)
                self.assertNotIn("Confirme si je dois integrer sur l'etat sale actuel.", rendered)
                self.assertNotIn("Ancienne reponse bruitee", rendered)
                self.assertNotIn("active_missions=", rendered)
            finally:
                services.close()

    def test_long_context_prompt_uses_digest_and_renders_workflow_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)
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
                            "rendered": services.gateway._simple_chat_user_message(
                                message,
                                provider="anthropic",
                                model=model,
                                route_reason=route_reason,
                                context_bundle=context_bundle,
                            ),
                        }
                    )
                    return "ok"

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                services.gateway._should_inline_chat = lambda event, decision: True  # type: ignore[method-assign]

                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=(
                            "Decision: on garde Discord comme surface.\n"
                            "Action: corriger le pipeline long input.\n"
                            "Question: faut-il joindre un PDF pour revue ?\n\n"
                        )
                        + ("plan detaille a verifier " * 180),
                        thread_ref=ConversationThreadRef(
                            thread_id="thread_long_context",
                            channel="discord",
                            external_thread_id="channel:thread_long_context",
                        ),
                        attachments=[
                            OperatorAttachment(
                                attachment_id=new_id("attachment"),
                                name="founder-notes.pdf",
                                kind="document",
                                mime_type="application/pdf",
                            )
                        ],
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(dispatch.metadata["input_profile"], "document")
                self.assertIsNotNone(dispatch.metadata["long_context_workflow_id"])
                self.assertEqual(len(dispatch.metadata["long_context_artifact_ids"]), 2)
                compact_message = str(captured[-1]["message"])
                rendered = str(captured[-1]["rendered"])
                self.assertTrue(compact_message.startswith("Input long detecte."))
                self.assertIn("Workflow long-context:", rendered)
                self.assertIn("segment_count:", rendered)
                self.assertIn("actions:", rendered)
                self.assertIn("questions:", rendered)
                self.assertNotIn("plan detaille a verifier " * 12, rendered)
            finally:
                services.close()

    def test_long_response_is_materialized_as_artifact_first_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._mark_runtime_ready(services)

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    del message, model, route_reason, context_bundle
                    return (
                        "Decision: passer en artifact-first output.\n"
                        "Action: envoyer un resume Discord compact.\n"
                        "Action: joindre le document complet en markdown.\n"
                        "Question: faut-il ajouter un PDF plus tard ?\n\n"
                        + ("Plan detaille de validation " * 220)
                    )

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                services.gateway._should_inline_chat = lambda event, decision: True  # type: ignore[method-assign]

                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text=("audit et plan complet a relire " * 80),
                        thread_ref=ConversationThreadRef(
                            thread_id="thread_artifact_output",
                            channel="discord",
                            external_thread_id="channel:thread_artifact_output",
                        ),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                manifest = dispatch.operator_reply.response_manifest
                self.assertIsNotNone(manifest)
                assert manifest is not None
                self.assertEqual(manifest.delivery_mode, "artifact_summary")
                self.assertEqual(dispatch.metadata["response_delivery_mode"], "artifact_summary")
                self.assertTrue(manifest.review_artifact_id)
                self.assertTrue(manifest.decision_extract_artifact_id)
                self.assertTrue(manifest.action_extract_artifact_id)
                self.assertEqual(len(manifest.attachments), 1)
                self.assertIn("Document complet joint.", dispatch.operator_reply.summary)
                self.assertTrue(Path(manifest.attachments[0].path).exists())
                self.assertEqual(Path(manifest.attachments[0].path).suffix, ".md")
                review_text = Path(manifest.attachments[0].path).read_text(encoding="utf-8")
                self.assertIn("# Project OS Review Artifact", review_text)
                self.assertIn("## Full Response", review_text)
                artifact_rows = services.database.fetchall(
                    "SELECT artifact_kind FROM artifact_pointers WHERE owner_type = ? ORDER BY artifact_kind",
                    ("gateway_reply",),
                )
                artifact_kinds = {str(row["artifact_kind"]) for row in artifact_rows}
                self.assertTrue(
                    {
                        "response_action_extract",
                        "response_decision_extract",
                        "response_manifest",
                        "response_review_markdown",
                    }.issubset(artifact_kinds)
                )
            finally:
                services.close()
