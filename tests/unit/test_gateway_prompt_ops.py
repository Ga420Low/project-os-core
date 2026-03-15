from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.gateway.context_builder import GatewayContextBuilder
from project_os_core.gateway.promotion import SelectiveSyncPromoter
from project_os_core.gateway.persona import load_persona_spec
from project_os_core.models import (
    ChannelEvent,
    ConversationThreadRef,
    OperatorAttachment,
    OperatorMessage,
    RuntimeState,
    RuntimeVerdict,
    new_id,
)
from project_os_core.services import build_app_services


class GatewayPromptOpsTests(unittest.TestCase):
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
                "required_secret_names": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
                "local_fallback_path": str(tmp_path / "secrets.json"),
            }
        }
        policy_path = tmp_path / "runtime_policy.json"
        policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
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

    def test_persona_spec_contains_golden_examples_for_identity_truth_and_tone(self):
        spec = load_persona_spec()

        titles = {example.title for example in spec.few_shot_examples}
        self.assertIn("Identity answer", titles)
        self.assertIn("Runtime truth", titles)
        self.assertIn("Light humor", titles)
        self.assertIn("Serious mode", titles)

        combined_good = "\n".join(example.good_reply for example in spec.few_shot_examples)
        combined_avoid = "\n".join(example.avoid_reply or "" for example in spec.few_shot_examples)
        self.assertIn("Project OS", combined_good)
        self.assertIn("Je n'utilise aucune API externe.", combined_avoid)
        self.assertIn("Theo", combined_avoid)

    def test_mood_classifier_covers_major_operator_modes(self):
        self.assertEqual(GatewayContextBuilder._classify_mood("ca marche pas et ca me saoule").mood, "frustrated")
        self.assertEqual(GatewayContextBuilder._classify_mood("c'est urgent, on est bloque").mood, "urgent")
        self.assertEqual(GatewayContextBuilder._classify_mood("brainstorm trois options d architecture").mood, "brainstorming")
        self.assertEqual(GatewayContextBuilder._classify_mood("lol petite blague au passage").mood, "casual")
        self.assertEqual(GatewayContextBuilder._classify_mood("sois serieux, il y a un risque de secret").mood, "serious")
        self.assertEqual(GatewayContextBuilder._classify_mood("fais un point propre sur ce sujet").mood, "focused")

    def test_query_scope_classifier_keeps_identity_and_runtime_truth_narrow(self):
        self.assertEqual(GatewayContextBuilder._classify_query_scope("test qui est tu"), "identity")
        self.assertEqual(
            GatewayContextBuilder._classify_query_scope("quelle api et quel modele tu utilises dans ce tour ?"),
            "runtime_truth",
        )
        self.assertEqual(
            GatewayContextBuilder._classify_query_scope(
                "quelle api utilise tu et il y a t-il des beug entre la connexion project os open claw claude ?"
            ),
            "contextual",
        )

    def test_selective_sync_classifier_keeps_recall_and_light_humor_in_chat(self):
        promoter = SelectiveSyncPromoter()

        recall_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="Rappelle-moi exactement les deux contraintes",
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
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
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
            ),
        )

        self.assertEqual(promoter.classify_message(recall_event).value, "chat")
        self.assertEqual(promoter.classify_message(humor_event).value, "chat")

    def test_intent_taxonomy_detects_implicit_and_explicit_directives(self):
        promoter = SelectiveSyncPromoter()

        implicit_prepare_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="j'aimerais qu'on garde une trace de ca dans un md",
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
            ),
        )
        implicit_execute_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="tu peux me poser un fichier test dans le repo pour verifier la boucle ?",
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
            ),
        )
        explicit_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="fais un fichier test.md dans le repo",
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
            ),
        )

        implicit_prepare = promoter.build_candidate(implicit_prepare_event)
        implicit_execute = promoter.build_candidate(implicit_execute_event)
        explicit = promoter.build_candidate(explicit_event)

        self.assertEqual(implicit_prepare.classification.value, "tasking")
        self.assertEqual(implicit_prepare.metadata["intent_kind"], "directive_implicit")
        self.assertEqual(implicit_prepare.metadata["delegation_level"], "prepare")
        self.assertEqual(implicit_prepare.metadata["interaction_state"], "directive")
        self.assertEqual(implicit_prepare.metadata["suggested_next_state"], "execution")

        self.assertEqual(implicit_execute.classification.value, "tasking")
        self.assertEqual(implicit_execute.metadata["intent_kind"], "directive_implicit")
        self.assertEqual(implicit_execute.metadata["delegation_level"], "execute")

        self.assertEqual(explicit.classification.value, "tasking")
        self.assertEqual(explicit.metadata["intent_kind"], "directive_explicit")
        self.assertEqual(explicit.metadata["delegation_level"], "execute")
        self.assertEqual(explicit.metadata["state_transition"], "directive->execution")

        implicit_detection = implicit_execute.metadata["directive_detection"]
        self.assertEqual(implicit_detection["directive_form"], "implicit")
        self.assertEqual(implicit_detection["strength"], "strong")
        self.assertTrue(implicit_detection["likely_directive"])
        self.assertIn("fichier", implicit_detection["output_hits"])
        self.assertIn("repo", implicit_detection["target_hits"])

    def test_directive_detection_avoids_capability_question_false_positive(self):
        promoter = SelectiveSyncPromoter()

        capability_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="Est-ce que tu peux modifier le repo directement depuis ici ?",
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
            ),
        )
        recall_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="tu peux me rappeler les deux contraintes ?",
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
            ),
        )

        capability_candidate = promoter.build_candidate(capability_event)
        recall_candidate = promoter.build_candidate(recall_event)

        self.assertEqual(capability_candidate.classification.value, "chat")
        self.assertEqual(capability_candidate.metadata["intent_kind"], "discussion")
        self.assertFalse(capability_candidate.metadata["directive_detection"]["likely_directive"])
        self.assertTrue(capability_candidate.metadata["directive_detection"]["capability_query"])

        self.assertEqual(recall_candidate.classification.value, "chat")
        self.assertEqual(recall_candidate.metadata["intent_kind"], "discussion")
        self.assertFalse(recall_candidate.metadata["directive_detection"]["likely_directive"])
        self.assertEqual(
            recall_candidate.metadata["directive_detection"]["blocked_reason"],
            "capability_query_without_deliverable",
        )

    def test_input_profile_classifier_marks_long_text_documents_and_transcripts(self):
        promoter = SelectiveSyncPromoter()

        long_text_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="plan " * 400,
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
            ),
        )
        document_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="Voici le brief.",
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
                attachments=[
                    OperatorAttachment(
                        attachment_id=new_id("attachment"),
                        name="brief.pdf",
                        kind="document",
                        mime_type="application/pdf",
                    )
                ],
            ),
        )
        transcript_event = ChannelEvent(
            event_id=new_id("channel_event"),
            surface="discord",
            event_type="message.created",
            message=OperatorMessage(
                message_id=new_id("message"),
                actor_id="founder",
                channel="discord",
                text="Transcript brut.",
                thread_ref=ConversationThreadRef(thread_id="thread_scope", channel="discord"),
                attachments=[
                    OperatorAttachment(
                        attachment_id=new_id("attachment"),
                        name="voice-note.m4a",
                        kind="audio",
                        mime_type="audio/mp4",
                    )
                ],
            ),
        )

        self.assertEqual(promoter.build_candidate(long_text_event).metadata["input_profile"], "long_text")
        self.assertEqual(promoter.build_candidate(document_event).metadata["input_profile"], "document")
        self.assertEqual(promoter.build_candidate(transcript_event).metadata["input_profile"], "transcript")

    def test_prompt_truth_layer_includes_runtime_provider_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                prompt = services.gateway._simple_chat_user_message(
                    "quelle api et quel modele tu utilises dans ce tour ?",
                    provider="anthropic",
                    model="claude-opus-4-1",
                    route_reason="operator_forced_opus_route",
                )
                system_prompt = services.gateway._simple_chat_system_prompt()

                self.assertIn("current_provider: anthropic", prompt)
                self.assertIn("current_model: claude-opus-4-1", prompt)
                self.assertIn("current_route_reason: operator_forced_opus_route", prompt)
                self.assertIn("<truth_rules>", system_prompt)
                self.assertIn("assistant numerique generique", system_prompt.lower())
                self.assertIn("je n'utilise aucune api externe.", system_prompt.lower())
            finally:
                services.close()

    def test_handoff_contract_keeps_raw_operator_text_while_route_uses_normalized_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
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
                        }
                    )
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
                        text="OPUS challenge mon idee de naming",
                        thread_ref=ConversationThreadRef(
                            thread_id="thread_prompt_ops",
                            channel="discord",
                            external_thread_id="channel:thread_prompt_ops",
                        ),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="core")

                self.assertEqual(captured[-1]["message"], "challenge mon idee de naming")
                handoff = dispatch.metadata["handoff_contract"]
                self.assertEqual(handoff["raw_user_intent"], "OPUS challenge mon idee de naming")
                self.assertEqual(handoff["target_model"], services.config.execution_policy.discord_opus_model)
                self.assertIn("requested_model_mode=opus", handoff["decisions_taken"])
            finally:
                services.close()
