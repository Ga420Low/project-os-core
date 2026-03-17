from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.gateway.discord_facade_smoke import (
    DEFAULT_SMOKE_ANTHROPIC_MODEL,
    TurnExpectation,
    build_isolated_storage_config,
    evaluate_turn_payload,
    get_payload_path,
    main as smoke_main,
    manual_acceptance_checks,
    parse_args,
    scenario_catalog,
    scenario_ids_for_layers,
)


class DiscordFacadeSmokeTests(unittest.TestCase):
    def test_get_payload_path_reads_nested_values(self):
        payload = {"metadata": {"approval_metadata": {"approval_type": "deep_research_launch"}}}

        self.assertEqual(
            get_payload_path(payload, "metadata.approval_metadata.approval_type"),
            "deep_research_launch",
        )

    def test_evaluate_turn_payload_detects_forbidden_visible_plumbing(self):
        payload = {
            "metadata": {"model_provider": "anthropic"},
            "operator_reply": {
                "reply_kind": "chat_response",
                "summary": "API utilisee: Claude Sonnet. Route_reason=discord_simple_route.",
                "response_manifest": {"delivery_mode": "inline_text"},
            },
        }
        expectation = TurnExpectation(
            expected_reply_kind="chat_response",
            expected_provider="anthropic",
            expected_delivery_modes=("inline_text", "thread_chunked_text"),
            forbidden_summary_terms=("api utilisee", "route_reason"),
        )

        errors = evaluate_turn_payload(payload, expectation)

        self.assertEqual(len(errors), 2)
        self.assertIn("terme interdit", errors[0])

    def test_evaluate_turn_payload_accepts_required_paths_and_any_terms(self):
        payload = {
            "metadata": {
                "model_provider": "anthropic",
                "approval_metadata": {"approval_type": "reasoning_escalation"},
            },
            "operator_reply": {
                "reply_kind": "approval_required",
                "summary": "Mode recommande. Cout estime avant switch vers Claude Sonnet.",
                "response_manifest": {"delivery_mode": "inline_text"},
            },
        }
        expectation = TurnExpectation(
            expected_reply_kind="approval_required",
            expected_delivery_modes=("inline_text",),
            required_summary_terms=("cout estime", "mode recommande"),
            required_summary_any=("claude", "anthropic", "sonnet"),
            required_paths={"metadata.approval_metadata.approval_type": "reasoning_escalation"},
        )

        self.assertEqual(evaluate_turn_payload(payload, expectation), [])

    def test_scenario_catalog_contains_protected_cases(self):
        catalog = scenario_catalog()

        self.assertIn("natural_reply_hides_plumbing", catalog)
        self.assertIn("persona_identity_not_generic", catalog)
        self.assertIn("deep_research_mode_selection_preserved", catalog)
        self.assertIn("deep_research_explicit_mode_cost_gate", catalog)
        self.assertIn("reasoning_escalation_requires_confirmation", catalog)

    def test_scenario_ids_for_layers_split_smoke_persona_and_manual(self):
        smoke_ids = set(scenario_ids_for_layers(("smoke",)))
        persona_ids = set(scenario_ids_for_layers(("persona",)))
        all_ids = set(scenario_ids_for_layers(("all",)))
        manual_ids = set(scenario_ids_for_layers(("manual",)))

        self.assertIn("natural_reply_hides_plumbing", smoke_ids)
        self.assertNotIn("persona_identity_not_generic", smoke_ids)
        self.assertIn("persona_identity_not_generic", persona_ids)
        self.assertNotIn("ambiguous_followup_clarifies", persona_ids)
        self.assertIn("natural_reply_hides_plumbing", all_ids)
        self.assertIn("persona_identity_not_generic", all_ids)
        self.assertEqual(manual_ids, set())

    def test_build_isolated_storage_config_writes_valid_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = build_isolated_storage_config(Path(tmp))
            payload = json.loads(target.read_text(encoding="utf-8"))

            self.assertEqual(target.name, "storage_roots.smoke.json")
            self.assertIn("runtime_root", payload)
            self.assertTrue(str(payload["runtime_root"]).startswith(tmp))

    def test_parse_args_defaults_to_cheap_anthropic_model(self):
        args = parse_args([])

        self.assertEqual(args.anthropic_model, DEFAULT_SMOKE_ANTHROPIC_MODEL)

    def test_manual_acceptance_checks_are_exposed(self):
        checks = manual_acceptance_checks()

        self.assertGreaterEqual(len(checks), 4)
        self.assertIn("check_id", checks[0])
        self.assertIn("watch_for", checks[0])

    def test_main_with_manual_layer_prints_manual_checks(self):
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            code = smoke_main(["--layer", "manual"])

        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertIn("manual_presence_typing", rendered)
        self.assertIn("manual_thread_continuity_days", rendered)


if __name__ == "__main__":
    unittest.main()
