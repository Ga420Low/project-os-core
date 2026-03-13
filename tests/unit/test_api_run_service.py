from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

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


if __name__ == "__main__":
    unittest.main()
