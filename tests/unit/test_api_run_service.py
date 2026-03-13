from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.api_runs.dashboard import build_dashboard_payload, render_dashboard_html
from project_os_core.models import ApiRunMode, ApiRunReviewVerdict
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
    services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
    return services


def _prepare_approved_contract(services, *, mode: ApiRunMode, objective: str, branch_name: str, skill_tags: list[str]):
    context_pack = services.api_runs.build_context_pack(
        mode=mode,
        objective=objective,
        branch_name=branch_name,
        skill_tags=skill_tags,
    )
    prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
    contract = services.api_runs.create_run_contract(
        context_pack_id=context_pack.context_pack_id,
        prompt_template_id=prompt.prompt_template_id,
    )
    services.api_runs.approve_run_contract(contract_id=contract.contract_id, founder_decision="go")
    return contract


class ApiRunServiceTests(unittest.TestCase):
    def test_dashboard_html_emits_operator_beacon_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                payload = build_dashboard_payload(services, limit=4)
                html = render_dashboard_html(payload, refresh_seconds=4)
                self.assertIn("/api/operator-beacon", html)
                self.assertIn('params.get("focus")', html)
            finally:
                services.close()

    def test_execute_run_fails_closed_if_visible_ui_cannot_be_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.config.api_dashboard_config.auto_start = True
                services.config.api_dashboard_config.auto_open_browser = True
                services.config.api_dashboard_config.require_visible_ui = True
                services.api_runs.dashboard_config = services.config.api_dashboard_config
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier le garde-fou de visibility UI.",
                    branch_name="codex/test-ui-guard",
                    skill_tags=["audit", "dashboard"],
                )
                with patch(
                    "project_os_core.api_runs.dashboard.ensure_dashboard_running",
                    return_value={"ready": False, "ui_visible": False, "url": "http://127.0.0.1:8765/"},
                ):
                    with self.assertRaisesRegex(RuntimeError, "control room locale"):
                        services.api_runs.execute_run(contract_id=contract.contract_id)
            finally:
                services.close()

    def test_live_snapshot_updates_while_run_is_still_executing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier le live dashboard pendant un run API.",
                    branch_name="codex/test-live-snapshot",
                    skill_tags=["audit", "dashboard"],
                )
                observed_snapshot: dict[str, object] = {}

                def _runner(request, prompt, context):
                    snapshot_path = services.paths.api_runs_terminal_snapshot_path
                    observed_snapshot.update(json.loads(snapshot_path.read_text(encoding="utf-8")))
                    return {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Le dashboard live doit afficher generation pendant le run.",
                                "why": "La visibilite temps reel est obligatoire.",
                                "alternatives": ["N'afficher que le resultat final."],
                                "files_to_change": ["src/project_os_core/api_runs/service.py"],
                                "interfaces": ["ApiRunResult"],
                                "patch_outline": ["Creer un placeholder running.", "Rafraichir le snapshot a chaque phase."],
                                "tests": ["Verifier le snapshot pendant response_runner."],
                                "risks": ["Snapshot live absent ou stale."],
                                "acceptance_criteria": ["Le snapshot montre generation avant la fin du run."],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 600, "output_tokens": 250},
                    }

                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=_runner,
                )
                self.assertEqual(observed_snapshot["current_run"]["status"], "running")
                self.assertEqual(observed_snapshot["current_run"]["phase"], "generation")
                self.assertEqual(observed_snapshot["current_run"]["branch_name"], "codex/test-live-snapshot")
                self.assertEqual(observed_snapshot["current_run"]["run_id"], payload["result"].run_id)
            finally:
                services.close()

    def test_patch_plan_run_builds_context_and_persists_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Finish the OpenClaw live adapter plan.",
                    branch_name="codex/test-api-run",
                    skill_tags=["patch_plan", "openclaw"],
                )
                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Implement the OpenClaw live adapter in the next lot.",
                                "why": "The repo already has the internal gateway and needs the live bridge next.",
                                "alternatives": ["Delay OpenClaw live and do LangGraph first."],
                                "files_to_change": ["src/project_os_core/gateway/openclaw_adapter.py"],
                                "interfaces": ["ChannelEvent", "GatewayDispatchResult"],
                                "patch_outline": ["Wire the live adapter.", "Validate Discord event ingestion."],
                                "tests": ["Add live adapter ingestion test."],
                                "risks": ["OpenClaw runtime mismatch."],
                                "acceptance_criteria": ["Discord message reaches Mission Router through the adapter."],
                                "open_questions": ["Which OpenClaw runtime hook will be used on the machine?"],
                            }
                        ),
                        "usage": {"input_tokens": 1000, "output_tokens": 500},
                    },
                )
                result = payload["result"]
                self.assertEqual(result.status.value, "completed")
                self.assertEqual(payload["request"].branch_name, "codex/test-api-run")
                self.assertEqual(payload["context_pack"].skill_tags, ["PATCH_PLAN", "OPENCLAW"])
                self.assertTrue(Path(result.raw_output_path).exists())
                self.assertTrue(Path(result.result_artifact_path).exists())
                self.assertTrue(Path(payload["prompt_template"].artifact_path).exists())
                monitor = services.api_runs.monitor_snapshot()
                self.assertEqual(monitor["current_run"]["run_id"], result.run_id)
            finally:
                services.close()

    def test_review_acceptance_promotes_learning_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.DESIGN,
                    objective="Design the first LangGraph live bridge.",
                    branch_name="codex/test-review",
                    skill_tags=["design", "langgraph"],
                )
                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Keep a single canonical graph and add the live LangGraph adapter next.",
                                "why": "Multiple graphs now would create drift.",
                                "alternatives": ["Fork a second graph for UEFN now."],
                                "files_to_change": ["src/project_os_core/orchestration/graph.py"],
                                "interfaces": ["GraphState", "RoleHandoff"],
                                "patch_outline": ["Add LangGraph adapter shell."],
                                "tests": ["Adapter handoff test."],
                                "risks": ["Over-coupling LangGraph to runtime state."],
                                "acceptance_criteria": ["The live adapter consumes the canonical graph state."],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 800, "output_tokens": 400},
                    },
                )
                review = services.api_runs.review_result(
                    run_id=payload["result"].run_id,
                    verdict=ApiRunReviewVerdict.ACCEPTED,
                    reviewer="codex",
                    findings=["Design is coherent."],
                    accepted_changes=["Proceed with LangGraph live adapter shell."],
                )
                self.assertEqual(review.verdict.value, "accepted")
                decision_rows = services.database.fetchall("SELECT * FROM decision_records")
                dataset_rows = services.database.fetchall("SELECT * FROM dataset_candidates")
                self.assertEqual(len(decision_rows), 1)
                self.assertEqual(len(dataset_rows), 1)
            finally:
                services.close()

    def test_review_rejection_records_patch_rejected_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.GENERATE_PATCH,
                    objective="Generate a patch for a risky refactor.",
                    branch_name="codex/test-reject",
                    skill_tags=["generate_patch", "security"],
                )
                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Attempt the refactor in one sweep.",
                                "why": "Fastest route.",
                                "alternatives": ["Split the refactor."],
                                "files_to_change": ["src/project_os_core/cli.py"],
                                "interfaces": ["ApiRunRequest"],
                                "patch_outline": ["Rewrite the CLI parser."],
                                "tests": ["CLI smoke test."],
                                "risks": ["Parser breakage."],
                                "acceptance_criteria": ["CLI still routes all commands."],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 1200, "output_tokens": 600},
                    },
                )
                services.api_runs.review_result(
                    run_id=payload["result"].run_id,
                    verdict=ApiRunReviewVerdict.REJECTED,
                    reviewer="codex",
                    findings=["Too risky in one sweep."],
                )
                signal_rows = services.database.fetchall("SELECT * FROM learning_signals")
                self.assertTrue(any(str(row["kind"]) == "patch_rejected" for row in signal_rows))
            finally:
                services.close()

    def test_response_parser_accepts_extra_text_after_json_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                parsed, _, _ = services.api_runs._normalize_response_payload(
                    {
                        "model": "gpt-5.4",
                        "output_text": '{"decision":"OK","why":"Test"}\n{"ignored":"extra"}',
                        "usage": {"input_tokens": 10, "output_tokens": 5},
                    }
                )
                self.assertEqual(parsed["decision"], "OK")
                self.assertEqual(parsed["why"], "Test")
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
