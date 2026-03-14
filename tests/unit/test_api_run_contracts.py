from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.models import ApiRunMode, ApiRunReview, ApiRunReviewVerdict, new_id
from project_os_core.secrets import SecretLookup
from project_os_core.services import build_app_services


def _install_stub_reviewer(services):
    def _stub(result, context_pack):
        review = ApiRunReview(
            review_id=new_id("run_review"),
            run_id=result.run_id,
            verdict=ApiRunReviewVerdict.ACCEPTED,
            reviewer="claude-sonnet-4-20250514",
            findings=[],
            followup_actions=["Proceed to founder decision."],
            metadata={
                "type": "review_result",
                "source": "test_stub",
                "summary": "Claude review accepted the run.",
                "recommendation": "Proceed to founder decision.",
                "issues_found": 0,
                "critical": 0,
                "high": 0,
                "usage": {"input_tokens": 120, "output_tokens": 40},
                "estimated_cost_eur": 0.0012,
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
            "require_visible_ui": False,
        },
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

    services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
    services.secret_resolver._from_infisical = lambda name: SecretLookup(
        value=None,
        source="test_infisical_disabled",
        available=False,
    )
    services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
    services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "anthropic-test-secret")
    _install_stub_reviewer(services)
    return services


class ApiRunContractTests(unittest.TestCase):
    def test_contract_flow_generates_completion_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Construire le prochain lot de code en silence.",
                    branch_name="codex/test-contract-flow",
                    skill_tags=["patch_plan", "code"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                contract = services.api_runs.create_run_contract(
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                )
                contract.metadata["allow_branch_mismatch"] = True
                contract.metadata["allow_dirty_worktree"] = True
                services.api_runs._persist_run_contract(contract)
                self.assertEqual(contract.status.value, "prepared")
                approved = services.api_runs.approve_run_contract(contract_id=contract.contract_id, founder_decision="go")
                self.assertEqual(approved.status.value, "approved")

                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt_template, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Le prochain lot doit finaliser l'adaptateur Discord.",
                                "why": "C'est le plus petit lot utile et stable.",
                                "alternatives": ["Commencer directement par LangGraph."],
                                "files_to_change": ["src/project_os_core/gateway/service.py"],
                                "interfaces": ["DiscordRunCard", "OperatorReply"],
                                "patch_outline": ["Ajouter les cartes de run.", "Ajouter le resume final."],
                                "tests": ["Verifier le dispatch Discord.", "Verifier la carte de run."],
                                "risks": ["Bruit UX si la carte est trop verbeuse."],
                                "acceptance_criteria": ["Le run reste silencieux jusqu'a la fin."],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 1400, "output_tokens": 700},
                    },
                )
                self.assertEqual(payload["review"].verdict.value, "accepted")
                self.assertIsNotNone(payload["completion_report"])
                completion_rows = services.database.fetchall("SELECT * FROM completion_reports")
                self.assertEqual(len(completion_rows), 1)
                event_rows = services.database.fetchall("SELECT * FROM api_run_events WHERE run_id = ?", (payload["result"].run_id,))
                self.assertGreaterEqual(len(event_rows), 3)
                artifacts = services.api_runs.show_artifacts(run_id=payload["result"].run_id)["artifacts"]
                artifact_kinds = {item["artifact_kind"] for item in artifacts}
                self.assertIn("contrat", artifact_kinds)
                self.assertIn("rapport_final", artifact_kinds)
            finally:
                services.close()

    def test_execute_without_contract_is_blocked_when_policy_requires_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                with self.assertRaises(RuntimeError):
                    services.api_runs.execute_run(
                        mode=ApiRunMode.AUDIT,
                        objective="Audit rapide",
                        branch_name="codex/test-contract-required",
                        skill_tags=["audit"],
                        response_runner=lambda *_args: {},
                    )
            finally:
                services.close()

    def test_contract_persist_detects_stale_concurrent_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier le guard de concurrence du contrat.",
                    branch_name="codex/test-contract-concurrency",
                    skill_tags=["audit"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                contract = services.api_runs.create_run_contract(
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                )
                stale_updated_at = contract.updated_at
                contract.summary = "Premier update"
                contract.updated_at = "2026-03-13T12:00:01+00:00"
                services.api_runs._persist_run_contract(contract, expected_updated_at=stale_updated_at)

                stale_copy = services.api_runs.get_run_contract(contract.contract_id)
                stale_copy.summary = "Update concurrent"
                stale_copy.updated_at = "2026-03-13T12:00:02+00:00"
                with self.assertRaisesRegex(RuntimeError, "modified concurrently"):
                    services.api_runs._persist_run_contract(stale_copy, expected_updated_at=stale_updated_at)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
