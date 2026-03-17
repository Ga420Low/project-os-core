from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.models import ApiRunMode, ApiRunStatus, OperatorChannelHint, RunLifecycleEvent, RunLifecycleEventKind
from project_os_core.operator_visibility_policy import StandardReplyPolicy


class StandardReplyPolicyTests(unittest.TestCase):
    @staticmethod
    def _decision(*, provider: str, route_reason: str):
        return SimpleNamespace(
            model_route=SimpleNamespace(provider=provider),
            route_reason=route_reason,
        )

    def test_visible_case_matrix_contains_canonical_cases(self):
        case_ids = {case.case_id for case in StandardReplyPolicy.visible_case_matrix()}

        self.assertEqual(
            case_ids,
            {
                "question_normale",
                "approval_reel",
                "changement_de_modele",
                "deep_research_explicite",
                "reponse_moyenne",
                "incident_delivery",
            },
        )

    def test_decorate_inline_summary_keeps_label_for_explicit_local_route(self):
        decision = self._decision(provider="local", route_reason="operator_forced_local_route")

        rendered = StandardReplyPolicy.decorate_inline_summary("Je reste local.", decision)

        self.assertEqual(rendered, "[Local / Ollama] Je reste local.")

    def test_decorate_inline_summary_keeps_label_for_sensitive_local_route(self):
        decision = self._decision(provider="local", route_reason="s3_local_route")

        rendered = StandardReplyPolicy.decorate_inline_summary("Je reste local.", decision)

        self.assertEqual(rendered, "[Local S3 / Ollama] Je reste local.")

    def test_decorate_inline_summary_hides_label_for_implicit_local_route(self):
        decision = self._decision(provider="local", route_reason="local_inline_route")

        rendered = StandardReplyPolicy.decorate_inline_summary("Je reste local.", decision)

        self.assertEqual(rendered, "Je reste local.")

    def test_render_duplicate_ingress_reply_hides_openclaw_pipe_name(self):
        rendered = StandardReplyPolicy.render_duplicate_ingress_reply()

        self.assertEqual(rendered, "Message en double ignore. Rien n'est relance.")

    def test_render_standard_route_reply_hides_execution_mode_taxonomy(self):
        rendered = StandardReplyPolicy.render_standard_route_reply(
            allowed=True,
            worker_label="le worker navigateur",
        )

        self.assertEqual(rendered, "Je lance sur le worker navigateur.")

    def test_render_standard_route_reply_uses_human_block_message(self):
        rendered = StandardReplyPolicy.render_standard_route_reply(
            allowed=False,
            blocked_reason="une validation fondateur est obligatoire",
        )

        self.assertEqual(rendered, "Je ne peux pas lancer pour l'instant: une validation fondateur est obligatoire.")

    def test_summarize_standard_runtime_approval_hides_api_disclosure(self):
        rendered = StandardReplyPolicy.summarize_standard_runtime_approval(
            {
                "objective": "mettre a jour le changelog",
                "estimated_cost_eur": 1.23,
                "run_launched": True,
                "api_label": "Anthropic / claude-sonnet",
            }
        )

        self.assertEqual(rendered, "mettre a jour le changelog: validation prise en compte. Operation lancee (~1.23 EUR).")

    def test_summarize_standard_session_action_hides_guardian_wording(self):
        rendered = StandardReplyPolicy.summarize_standard_session_action(
            action="guardian_override",
            action_result={"branch_name": "codex/test-pack-2"},
        )

        self.assertEqual(rendered, "codex/test-pack-2: validation forcee prise en compte. Je relance.")

    def test_summarize_standard_session_action_humanizes_status_request(self):
        rendered = StandardReplyPolicy.summarize_standard_session_action(
            action="status_request",
            action_result={
                "snapshot": {
                    "active_runs": ["r1", "r2"],
                    "pending_clarifications": ["c1"],
                    "pending_contracts": [],
                    "daily_spend_eur": 2.5,
                    "daily_budget_limit_eur": 10.0,
                }
            },
        )

        self.assertEqual(
            rendered,
            "En ce moment: 2 runs actifs, 1 clarification en attente, 0 contrats en attente. Budget 2.50/10.00 EUR.",
        )

    def test_summarize_standard_session_action_hides_internal_action_names(self):
        rendered = StandardReplyPolicy.summarize_standard_session_action(
            action="internal_unhandled_case",
            action_result={"status": "ok"},
        )

        self.assertEqual(rendered, "C'est pris en compte.")

    def test_render_operator_delivery_text_preserves_existing_card_shape(self):
        event = RunLifecycleEvent(
            lifecycle_event_id="evt_1",
            run_id="run_1",
            run_request_id="req_1",
            kind=RunLifecycleEventKind.RUN_COMPLETED,
            title="Run termine",
            summary="Le patch est pret.",
            mode=ApiRunMode.GENERATE_PATCH,
            channel_hint=OperatorChannelHint.RUNS_LIVE,
            status=ApiRunStatus.COMPLETED,
            phase="review",
            branch_name="codex/project-os-test",
            blocking_question="faut-il lancer le merge ?",
            recommended_action="valider le patch",
            requires_reapproval=True,
        )

        rendered = StandardReplyPolicy.render_operator_delivery_text(event)

        self.assertIn("Run termine", rendered)
        self.assertIn("Le patch est pret.", rendered)
        self.assertIn("Branche: codex/project-os-test", rendered)
        self.assertIn("Question: faut-il lancer le merge ?", rendered)
        self.assertIn("Prochain pas: valider le patch", rendered)
        self.assertIn("Confirmation requise avant relance.", rendered)
        self.assertNotIn("Mode:", rendered)
        self.assertNotIn("Statut:", rendered)
        self.assertNotIn("Phase:", rendered)


if __name__ == "__main__":
    unittest.main()
