from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.mission.chain import MissionStep
from project_os_core.models import (
    ApiRunMode,
    ApiRunRequest,
    ApiRunResult,
    ApiRunReview,
    ApiRunReviewVerdict,
    ApiRunStatus,
    CommunicationMode,
    OperatorAudience,
    RunSpeechPolicy,
    new_id,
)
from project_os_core.services import build_app_services

TEST_BRANCH = "project-os/test-mission-chain"


def _install_stub_reviewer(services) -> None:
    def _stub(result, context_pack):
        review = ApiRunReview(
            review_id=new_id("run_review"),
            run_id=result.run_id,
            verdict=ApiRunReviewVerdict.ACCEPTED,
            reviewer="claude-sonnet-4-20250514",
            findings=[],
            followup_actions=["Proceed."],
            metadata={
                "type": "review_result",
                "source": "test_stub",
                "summary": "Accepted.",
                "recommendation": "Proceed.",
                "issues_found": 0,
                "critical": 0,
                "high": 0,
                "usage": {"input_tokens": 100, "output_tokens": 30},
                "estimated_cost_eur": 0.0011,
                "context_pack_id": context_pack.context_pack_id,
            },
        )
        services.api_runs._store_run_review(review)
        return review

    services.api_runs._call_reviewer = _stub


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
    services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "anthropic-test-secret")
    _install_stub_reviewer(services)
    services.api_runs._run_repo_preflight = lambda **_kwargs: {  # type: ignore[method-assign]
        "ok": True,
        "issues": [],
        "current_branch": TEST_BRANCH,
        "target_branch": TEST_BRANCH,
        "dirty": False,
    }
    services.api_runs._ensure_operator_dashboard = lambda contract=None: {"ready": True, "reason": "test"}  # type: ignore[method-assign]
    return services


def _response_runner(request, prompt, context):
    del request, prompt, context
    return {
        "model": "gpt-5.4",
        "output_text": json.dumps(
            {
                "decision": "Proceed with the planned step.",
                "why": "The mission chain requested this step.",
                "alternatives": [],
                "files_to_change": ["src/project_os_core/api_runs/service.py"],
                "interfaces": [],
                "patch_outline": ["Implement the requested step."],
                "tests": ["Run unit tests."],
                "risks": [],
                "acceptance_criteria": ["The step completes successfully."],
                "open_questions": [],
                "clarification_needed": False,
                "blocking_reason": "",
                "recommended_contract_change": "",
                "question_for_founder": "",
            }
        ),
        "usage": {"input_tokens": 1000, "output_tokens": 250},
    }


class MissionChainTests(unittest.TestCase):
    def _persist_chain_run_for_step(
        self,
        services,
        *,
        chain,
        step_index: int,
        status: ApiRunStatus,
        structured_output: dict | None = None,
        estimated_cost_eur: float = 0.12,
    ):
        step = chain.steps[step_index]
        request = ApiRunRequest(
            run_request_id=new_id("run_request"),
            context_pack_id=new_id("context_pack"),
            prompt_template_id=new_id("mega_prompt"),
            mode=step.mode,
            objective=step.objective,
            branch_name=str(chain.metadata["branch_name"]),
            target_profile=str(chain.metadata.get("target_profile") or "") or None,
            mission_chain_id=chain.chain_id,
            mission_step_index=step_index,
            skill_tags=["mission_chain", step.mode.value],
            expected_outputs=[],
            communication_mode=CommunicationMode.BUILDER,
            speech_policy=RunSpeechPolicy.SILENT_UNTIL_TERMINAL_STATE,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            run_contract_required=False,
            status=status,
            metadata={"mission_chain_id": chain.chain_id, "mission_step_index": step_index},
        )
        result = ApiRunResult(
            run_id=new_id("api_run"),
            run_request_id=request.run_request_id,
            model="gpt-5.4",
            mode=step.mode,
            status=status,
            structured_output=structured_output or {"decision": f"step_{step_index}"},
            estimated_cost_eur=estimated_cost_eur,
            usage={},
            metadata={},
        )
        services.api_runs._persist_run_request(request)
        services.api_runs._persist_run_result(result)
        return request, result

    def test_create_chain_from_full_refactor_template_creates_four_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                chain = services.chain.create_chain(
                    objective="Refactor the gateway stack.",
                    branch_name=TEST_BRANCH,
                    chain_template="full_refactor",
                )
                self.assertEqual(len(chain.steps), 4)
                self.assertEqual(chain.steps[0].mode, ApiRunMode.AUDIT)
                self.assertEqual(chain.steps[3].mode, ApiRunMode.GENERATE_PATCH)
            finally:
                services.close()

    def test_advance_chain_moves_to_step_one_when_step_zero_is_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                chain = services.chain.create_chain(
                    objective="Refactor the router.",
                    branch_name=TEST_BRANCH,
                    chain_template="full_refactor",
                )
                self._persist_chain_run_for_step(services, chain=chain, step_index=0, status=ApiRunStatus.COMPLETED)

                payload = services.chain.advance_chain(chain.chain_id, response_runner=_response_runner)
                updated = services.chain.chain_status(chain.chain_id)

                self.assertEqual(payload["action"], "launch_step")
                self.assertEqual(payload["step"]["step_index"], 1)
                self.assertEqual(payload["step"]["mode"], ApiRunMode.DESIGN.value)
                self.assertEqual(updated.current_step_index, 1)
            finally:
                services.close()

    def test_advance_chain_marks_last_completed_step_as_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                chain = services.chain.create_chain(
                    objective="Single-step audit mission.",
                    branch_name=TEST_BRANCH,
                    steps=[MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit only")],
                )
                chain = services.chain._update_chain(chain, current_step_index=0)  # type: ignore[attr-defined]
                self._persist_chain_run_for_step(services, chain=chain, step_index=0, status=ApiRunStatus.COMPLETED)

                payload = services.chain.advance_chain(chain.chain_id)
                updated = services.chain.chain_status(chain.chain_id)

                self.assertEqual(payload["status"], "completed")
                self.assertEqual(updated.status, "completed")
            finally:
                services.close()

    def test_failed_step_stops_chain_when_skip_flag_is_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                chain = services.chain.create_chain(
                    objective="Chain that should fail.",
                    branch_name=TEST_BRANCH,
                    steps=[
                        MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit"),
                        MissionStep(step_index=1, mode=ApiRunMode.DESIGN, objective="Design"),
                    ],
                )
                self._persist_chain_run_for_step(services, chain=chain, step_index=0, status=ApiRunStatus.FAILED)

                payload = services.chain.advance_chain(chain.chain_id)
                updated = services.chain.chain_status(chain.chain_id)

                self.assertEqual(payload["status"], "failed")
                self.assertEqual(updated.status, "failed")
            finally:
                services.close()

    def test_failed_step_is_skipped_when_next_step_allows_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                chain = services.chain.create_chain(
                    objective="Chain with skip-on-failure.",
                    branch_name=TEST_BRANCH,
                    steps=[
                        MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit"),
                        MissionStep(
                            step_index=1,
                            mode=ApiRunMode.GENERATE_PATCH,
                            objective="Patch anyway",
                            skip_on_previous_failure=True,
                        ),
                    ],
                )
                self._persist_chain_run_for_step(services, chain=chain, step_index=0, status=ApiRunStatus.FAILED)

                payload = services.chain.advance_chain(chain.chain_id, response_runner=_response_runner)
                updated = services.chain.chain_status(chain.chain_id)

                self.assertEqual(payload["action"], "launch_step")
                self.assertEqual(payload["step"]["step_index"], 1)
                self.assertEqual(payload["skipped_failed_step_index"], 0)
                self.assertEqual(updated.current_step_index, 1)
            finally:
                services.close()

    def test_chain_status_returns_complete_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                chain = services.chain.create_chain(
                    objective="Inspect the chain state.",
                    branch_name=TEST_BRANCH,
                    chain_template="design_only",
                    metadata={"owner": "founder"},
                )
                loaded = services.chain.chain_status(chain.chain_id)

                self.assertEqual(loaded.chain_id, chain.chain_id)
                self.assertEqual(loaded.objective, "Inspect the chain state.")
                self.assertEqual(loaded.current_step_index, 0)
                self.assertEqual(loaded.metadata["owner"], "founder")
            finally:
                services.close()

    def test_runs_created_by_chain_have_chain_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                chain = services.chain.create_chain(
                    objective="Launch the first chain step.",
                    branch_name=TEST_BRANCH,
                    steps=[MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit first")],
                )

                payload = services.chain.advance_chain(chain.chain_id, response_runner=_response_runner)
                request = services.api_runs.get_run_request(payload["payload"]["run_request_id"])

                self.assertEqual(request.mission_chain_id, chain.chain_id)
                self.assertEqual(request.mission_step_index, 0)
            finally:
                services.close()

    def test_guardian_blocked_step_pauses_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.api_runs.execution_policy.daily_budget_limit_eur = 0.01
                chain = services.chain.create_chain(
                    objective="Pause chain when guardian blocks a step.",
                    branch_name=TEST_BRANCH,
                    steps=[MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit first")],
                )

                def _runner(*_args, **_kwargs):
                    raise AssertionError("response_runner should not be called when guardian blocks before approval")

                payload = services.chain.advance_chain(chain.chain_id, response_runner=_runner)
                updated = services.chain.chain_status(chain.chain_id)
                contract = services.api_runs.get_run_contract(payload["payload"]["contract_id"])

                self.assertEqual(payload["action"], "guardian_blocked")
                self.assertEqual(payload["payload"]["status"], ApiRunStatus.CLARIFICATION_REQUIRED.value)
                self.assertTrue(payload["payload"]["guardian_blocked"])
                self.assertEqual(updated.status, "paused")
                self.assertEqual(contract.status.value, "prepared")
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
