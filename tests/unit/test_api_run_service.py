from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.api_runs.dashboard import build_dashboard_payload, render_dashboard_html
from project_os_core.models import (
    ApiRunMode,
    ApiRunRequest,
    ApiRunResult,
    ApiRunReview,
    ApiRunReviewVerdict,
    ApiRunStatus,
    DecisionStatus,
    LearningSignalKind,
    OperatorChannelHint,
    OperatorDeliveryStatus,
    RunLifecycleEvent,
    RunLifecycleEventKind,
    RunContractStatus,
    new_id,
)
from project_os_core.secrets import SecretLookup
from project_os_core.services import build_app_services


def _install_stub_reviewer(
    services,
    *,
    verdict: ApiRunReviewVerdict = ApiRunReviewVerdict.ACCEPTED,
    summary: str = "Claude review accepted the run.",
    recommendation: str = "Proceed to the next step.",
    issues_found: int = 0,
    critical: int = 0,
    high: int = 0,
):
    def _stub(result, context_pack):
        review = ApiRunReview(
            review_id=new_id("run_review"),
            run_id=result.run_id,
            verdict=verdict,
            reviewer="claude-sonnet-4-20250514",
            findings=[summary] if issues_found or verdict is not ApiRunReviewVerdict.ACCEPTED else [],
            followup_actions=[recommendation] if recommendation else [],
            metadata={
                "type": "review_result",
                "source": "test_stub",
                "summary": summary,
                "recommendation": recommendation,
                "issues_found": issues_found,
                "critical": critical,
                "high": high,
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
    contract.metadata["allow_branch_mismatch"] = True
    contract.metadata["allow_dirty_worktree"] = True
    services.api_runs._persist_run_contract(contract)
    services.api_runs.approve_run_contract(contract_id=contract.contract_id, founder_decision="go")
    return services.api_runs.get_run_contract(contract.contract_id)


class ApiRunServiceTests(unittest.TestCase):
    def test_review_verdict_values_are_unique_and_include_needs_revision(self):
        values = [item.value for item in ApiRunReviewVerdict]
        self.assertEqual(len(values), len(set(values)))
        self.assertIn("needs_revision", values)

    def test_templates_require_contradiction_guard_for_all_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                for mode in ApiRunMode:
                    template = services.api_runs._template_for_mode(mode)
                    self.assertIn("clarification_needed", template["output_contract"])
                    self.assertTrue(any("Challenge the brief if needed" in item for item in template["instructions"]))
            finally:
                services.close()

    def test_build_context_pack_injects_learning_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                branch_name = "codex/learning-injection"
                services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope=f"api_run:audit:{branch_name}",
                    summary="Prefer narrower diffs on this branch.",
                    metadata={"branch_name": branch_name},
                )

                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.AUDIT,
                    objective="Inject learning context into the run.",
                    branch_name=branch_name,
                    skill_tags=["audit", "learning"],
                )

                learning_context = context_pack.runtime_facts["learning_context"]
                self.assertEqual(len(learning_context["decisions"]), 1)
                self.assertEqual(learning_context["decisions"][0]["scope"], f"api_run:audit:{branch_name}")
            finally:
                services.close()

    def test_render_prompt_contains_learning_context_section_when_lessons_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                branch_name = "codex/learning-prompt"
                services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope=f"api_run:patch_plan:{branch_name}",
                    summary="Keep the architecture boundary stable.",
                    metadata={"branch_name": branch_name},
                )
                services.learning.record_signal(
                    kind=LearningSignalKind.PATCH_REJECTED,
                    severity="high",
                    summary=f"Rejected patch_plan run for {branch_name}.",
                    source_ids=["run_1"],
                    metadata={"branch_name": branch_name},
                )

                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Render prompt with learning context.",
                    branch_name=branch_name,
                    skill_tags=["patch_plan", "learning"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)

                self.assertIn("## Learning Context (lessons from recent runs)", prompt.rendered_prompt)
                self.assertIn("High-severity signals from recent runs:", prompt.rendered_prompt)
                self.assertIn("Recent confirmed decisions:", prompt.rendered_prompt)
            finally:
                services.close()

    def test_render_prompt_omits_learning_context_section_when_no_lessons_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.DESIGN,
                    objective="Render prompt without prior lessons.",
                    branch_name="codex/no-learning-prompt",
                    skill_tags=["design"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)

                self.assertNotIn("## Learning Context (lessons from recent runs)", prompt.rendered_prompt)
            finally:
                services.close()

    def test_build_context_pack_survives_learning_injection_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                def _raise_learning(**_kwargs):
                    raise RuntimeError("learning_db_down")

                services.learning.gather_learning_context = _raise_learning  # type: ignore[method-assign]

                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.GENERATE_PATCH,
                    objective="Continue even if learning injection fails.",
                    branch_name="codex/learning-failure",
                    skill_tags=["generate_patch"],
                )

                self.assertEqual(context_pack.runtime_facts["learning_context"]["error"], "learning_db_down")
                self.assertEqual(context_pack.runtime_facts["learning_context"]["decisions"], [])
            finally:
                services.close()

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
                services.config.api_dashboard_config.founder_approval_grace_seconds = 0
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

    def test_execute_run_uses_recent_founder_approval_fallback_when_browser_beacon_missing(self):
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
                    objective="Verifier le fallback d'approbation fondateur.",
                    branch_name="codex/test-founder-fallback",
                    skill_tags=["audit", "dashboard"],
                )
                with patch(
                    "project_os_core.api_runs.dashboard.ensure_dashboard_running",
                    return_value={"ready": False, "ui_visible": False, "reason": "browser_beacon_missing", "url": "http://127.0.0.1:8765/"},
                ):
                    payload = services.api_runs.execute_run(
                        contract_id=contract.contract_id,
                        response_runner=lambda request, prompt, context: {
                            "model": "gpt-5.4",
                            "output_text": json.dumps(
                                {
                                    "decision": "Fallback approuve.",
                                    "why": "Le go fondateur frais reste une preuve locale plus robuste qu'un simple launch navigateur.",
                                    "alternatives": ["Refuser tout run sans beacon navigateur."],
                                    "files_to_change": ["src/project_os_core/api_runs/service.py"],
                                    "interfaces": ["RunContract"],
                                    "patch_outline": ["Relier le contrat au guard."],
                                    "tests": ["Fallback d'approbation fraiche."],
                                    "risks": ["Fallback trop large si non borne dans le temps."],
                                    "acceptance_criteria": ["Le run approuve localement continue meme si le navigateur ne repond pas."],
                                    "open_questions": [],
                                }
                            ),
                            "usage": {"input_tokens": 10, "output_tokens": 10},
                        },
                )
                self.assertEqual(payload["result"].status.value, "completed")
                self.assertEqual(payload["request"].metadata["operator_dashboard_reason"], "founder_approval_fallback")
                self.assertTrue(payload["request"].metadata["operator_dashboard_ready"])
                snapshot = services.api_runs.monitor_snapshot(limit=1)
                self.assertEqual(snapshot["current_run"]["operator_guard_reason"], "founder_fallback")
                terminal = services.api_runs.render_terminal_dashboard(limit=1)
                self.assertIn("Garde operateur: founder_fallback", terminal)
            finally:
                services.close()

    def test_execute_run_keeps_fail_closed_when_founder_approval_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.config.api_dashboard_config.auto_start = True
                services.config.api_dashboard_config.auto_open_browser = True
                services.config.api_dashboard_config.require_visible_ui = True
                services.config.api_dashboard_config.founder_approval_grace_seconds = 60
                services.api_runs.dashboard_config = services.config.api_dashboard_config
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier que le fallback ne dure pas trop longtemps.",
                    branch_name="codex/test-stale-founder-fallback",
                    skill_tags=["audit", "dashboard"],
                )
                stale_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
                contract.founder_decision_at = stale_timestamp
                contract.metadata["founder_decision_at"] = datetime.now(timezone.utc).isoformat()
                contract.updated_at = stale_timestamp
                contract.status = RunContractStatus.APPROVED
                services.api_runs._persist_run_contract(contract)
                with patch(
                    "project_os_core.api_runs.dashboard.ensure_dashboard_running",
                    return_value={"ready": False, "ui_visible": False, "reason": "browser_beacon_missing", "url": "http://127.0.0.1:8765/"},
                ):
                    with self.assertRaisesRegex(RuntimeError, "browser_beacon_missing"):
                        services.api_runs.execute_run(contract_id=contract.contract_id)
            finally:
                services.close()

    def test_execute_run_ignores_fresh_metadata_timestamp_when_founder_approval_column_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.config.api_dashboard_config.auto_start = True
                services.config.api_dashboard_config.auto_open_browser = True
                services.config.api_dashboard_config.require_visible_ui = True
                services.config.api_dashboard_config.founder_approval_grace_seconds = 60
                services.api_runs.dashboard_config = services.config.api_dashboard_config
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier que le fallback lit la colonne canonique.",
                    branch_name="codex/test-founder-approval-column",
                    skill_tags=["audit", "dashboard"],
                )
                stale_timestamp = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
                contract.status = RunContractStatus.APPROVED
                contract.founder_decision = "go"
                contract.founder_decision_at = stale_timestamp
                contract.metadata["founder_decision_at"] = datetime.now(timezone.utc).isoformat()
                contract.updated_at = stale_timestamp
                services.api_runs._persist_run_contract(contract)
                with patch(
                    "project_os_core.api_runs.dashboard.ensure_dashboard_running",
                    return_value={"ready": False, "ui_visible": False, "reason": "browser_beacon_missing", "url": "http://127.0.0.1:8765/"},
                ):
                    with self.assertRaisesRegex(RuntimeError, "browser_beacon_missing"):
                        services.api_runs.execute_run(contract_id=contract.contract_id)
            finally:
                services.close()

    def test_execute_run_moves_to_clarification_required_and_persists_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.GENERATE_PATCH,
                    objective="Generer un patch sur un brief contradictoire.",
                    branch_name="codex/test-clarification-required",
                    skill_tags=["generate_patch", "guard"],
                )
                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Je m'arrete avant de proposer un patch final.",
                                "why": "Le brief demande une implementation incompatible avec le repo actuel.",
                                "alternatives": ["Clarifier le lot exact avant de produire le patch."],
                                "files_to_change": [],
                                "interfaces": [],
                                "patch_outline": [],
                                "tests": [],
                                "risks": ["Continuer maintenant ferait produire un patch hors cadre."],
                                "acceptance_criteria": ["Le contrat doit etre amende avant toute reprise."],
                                "open_questions": [],
                                "clarification_needed": True,
                                "blocking_reason": "Le lot vise contredit la verite repo/runtime.",
                                "recommended_contract_change": "Amender l'objectif pour cibler seulement la TUI live sans toucher au moteur d'execution.",
                                "question_for_founder": "Veux-tu limiter ce lot a la supervision terminal/web sans modifier la logique d'execution ?",
                            }
                        ),
                        "usage": {"input_tokens": 900, "output_tokens": 300},
                    },
                )
                self.assertEqual(payload["result"].status, ApiRunStatus.CLARIFICATION_REQUIRED)
                request = services.api_runs.get_run_request(payload["request"].run_request_id)
                self.assertEqual(request.status, ApiRunStatus.CLARIFICATION_REQUIRED)
                current_contract = services.api_runs.get_run_contract(contract.contract_id)
                self.assertEqual(current_contract.status, RunContractStatus.PREPARED)
                self.assertIsNone(current_contract.founder_decision)
                self.assertTrue(current_contract.metadata["clarification_pending"])
                snapshot = services.api_runs.monitor_snapshot(limit=1)
                self.assertEqual(snapshot["current_run"]["status"], "clarification_required")
                self.assertEqual(snapshot["current_run"]["clarification_reason"], "Le lot vise contredit la verite repo/runtime.")
                self.assertTrue(snapshot["current_run"]["clarification_requires_reapproval"])
                artifacts = services.api_runs.show_artifacts(run_id=payload["result"].run_id)
                artifact_kinds = {item["artifact_kind"] for item in artifacts["artifacts"]}
                self.assertIn("clarification", artifact_kinds)
                self.assertNotIn("rapport_final", artifact_kinds)
            finally:
                services.close()

    def test_repo_preflight_blocks_before_model_call_and_creates_operator_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.GENERATE_PATCH,
                    objective="Verifier le preflight dur avant depense API.",
                    branch_name="codex/preflight-mismatch",
                    skill_tags=["generate_patch", "guard"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                contract = services.api_runs.create_run_contract(
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                )
                services.api_runs.approve_run_contract(contract_id=contract.contract_id, founder_decision="go")

                def _runner(*_args, **_kwargs):
                    raise AssertionError("response_runner should not be called when repo preflight blocks the run")

                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=_runner,
                )

                self.assertEqual(payload["result"].status, ApiRunStatus.CLARIFICATION_REQUIRED)
                deliveries = services.api_runs.list_operator_deliveries(limit=10)["deliveries"]
                self.assertEqual(len(deliveries), 1)
                self.assertEqual(deliveries[0]["event"]["kind"], "clarification_required")
                self.assertEqual(deliveries[0]["channel_hint"], "approvals")
                self.assertEqual(deliveries[0]["status"], "pending")
            finally:
                services.close()

    def test_completed_run_enqueues_operator_deliveries_and_ack_updates_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier l'outbox operateur.",
                    branch_name="codex/test-operator-outbox",
                    skill_tags=["audit", "observability"],
                )
                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Le run est pret pour revue.",
                                "why": "Le lot a produit un resultat exploitable.",
                                "alternatives": ["Retarder la publication operateur."],
                                "files_to_change": ["src/project_os_core/api_runs/service.py"],
                                "interfaces": ["RunLifecycleEvent"],
                                "patch_outline": ["Persister l'event.", "Publier ensuite via OpenClaw."],
                                "tests": ["Outbox operateur."],
                                "risks": ["Livraison canal en erreur."],
                                "acceptance_criteria": ["Le run genere un event started puis completed."],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 50, "output_tokens": 40},
                    },
                )
                deliveries = services.api_runs.list_operator_deliveries(limit=10)["deliveries"]
                self.assertEqual(len(deliveries), 1)
                latest = deliveries[0]
                self.assertEqual(latest["event"]["run_id"], payload["result"].run_id)
                self.assertEqual(latest["status"], "pending")
                ack = services.api_runs.mark_operator_delivery(
                    delivery_id=latest["delivery_id"],
                    status=OperatorDeliveryStatus.DELIVERED,
                    metadata={"target": "channel:test"},
                )
                self.assertEqual(ack["status"], "delivered")
                snapshot = services.api_runs.monitor_snapshot(limit=3)
                self.assertIn("delivered", snapshot["operator_delivery_counts"])
            finally:
                services.close()

    def test_operator_delivery_pending_ack_uses_exponential_backoff_and_due_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.config.execution_policy.operator_delivery_retry_base_seconds = 1
                services.config.execution_policy.operator_delivery_retry_max_seconds = 8
                services.config.execution_policy.operator_delivery_max_attempts = 3
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier le retry backoff operateur.",
                    branch_name="codex/test-operator-backoff",
                    skill_tags=["audit", "observability"],
                )
                services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Le run est pret pour revue.",
                                "why": "Le lot a produit un resultat exploitable.",
                                "alternatives": [],
                                "files_to_change": [],
                                "interfaces": [],
                                "patch_outline": [],
                                "tests": [],
                                "risks": [],
                                "acceptance_criteria": [],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 30, "output_tokens": 20},
                    },
                )
                deliveries = services.api_runs.list_operator_deliveries(limit=10)["deliveries"]
                delivery = next(item for item in deliveries if item["event"]["kind"] == "run_completed")
                ack = services.api_runs.mark_operator_delivery(
                    delivery_id=delivery["delivery_id"],
                    status=OperatorDeliveryStatus.PENDING,
                    error="discord_down",
                )
                self.assertEqual(ack["status"], "pending")
                self.assertIsNotNone(ack["next_attempt_at"])
                due_ids = {
                    item["delivery_id"] for item in services.api_runs.list_operator_deliveries(limit=10)["deliveries"]
                }
                self.assertNotIn(delivery["delivery_id"], due_ids)
                for _ in range(2):
                    services.database.execute(
                        "UPDATE api_run_operator_deliveries SET next_attempt_at = ? WHERE delivery_id = ?",
                        ("2000-01-01T00:00:00+00:00", delivery["delivery_id"]),
                    )
                    ack = services.api_runs.mark_operator_delivery(
                        delivery_id=delivery["delivery_id"],
                        status=OperatorDeliveryStatus.PENDING,
                        error="discord_still_down",
                    )
                self.assertEqual(ack["status"], "failed")
            finally:
                services.close()

    def test_operator_delivery_backlog_prunes_oldest_runs_live_when_limit_is_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.config.execution_policy.operator_delivery_max_pending = 1
                for index in range(2):
                    contract = _prepare_approved_contract(
                        services,
                        mode=ApiRunMode.AUDIT,
                        objective=f"Verifier backlog operateur {index}.",
                        branch_name=f"codex/test-operator-backlog-{index}",
                        skill_tags=["audit", "observability"],
                    )
                    services.api_runs.execute_run(
                        contract_id=contract.contract_id,
                        response_runner=lambda request, prompt, context, i=index: {
                            "model": "gpt-5.4",
                            "output_text": json.dumps(
                                {
                                    "decision": f"Run {i} termine.",
                                    "why": "Le lot termine normalement.",
                                    "alternatives": [],
                                    "files_to_change": [],
                                    "interfaces": [],
                                    "patch_outline": [],
                                    "tests": [],
                                    "risks": [],
                                    "acceptance_criteria": [],
                                    "open_questions": [],
                                }
                            ),
                            "usage": {"input_tokens": 20, "output_tokens": 20},
                        },
                    )
                snapshot = services.api_runs.monitor_snapshot(limit=5)
                self.assertLessEqual(snapshot["operator_delivery_counts"].get("pending", 0), 1)
                self.assertGreaterEqual(snapshot["operator_delivery_counts"].get("skipped", 0), 1)
            finally:
                services.close()

    def test_amended_contract_requires_new_go_before_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.DESIGN,
                    objective="Design un lot ambigu.",
                    branch_name="codex/test-clarification-resume",
                    skill_tags=["design", "guard"],
                )
                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Clarification requise.",
                                "why": "Le lot melange design systeme et patch final.",
                                "alternatives": ["Se limiter au design."],
                                "files_to_change": [],
                                "interfaces": [],
                                "patch_outline": [],
                                "tests": [],
                                "risks": ["Continuer sans clarifier melangerait deux lots."],
                                "acceptance_criteria": ["Un seul lot doit etre vise."],
                                "open_questions": [],
                                "clarification_needed": True,
                                "blocking_reason": "Le brief combine deux intentions incompatibles.",
                                "recommended_contract_change": "Amender l'objectif pour ne garder que le design du lot.",
                                "question_for_founder": "Confirme que tu veux seulement un design et pas un patch dans ce run.",
                            }
                        ),
                        "usage": {"input_tokens": 700, "output_tokens": 200},
                    },
                )
                amended = services.api_runs.amend_run_contract(
                    contract_id=contract.contract_id,
                    objective="Design seulement le lot de contradiction guard.",
                    acceptance_criteria=["Le run produit uniquement un design implementable."],
                    metadata={"clarification_answer": "Design seulement."},
                )
                self.assertEqual(amended.status, RunContractStatus.PREPARED)
                with self.assertRaisesRegex(RuntimeError, "doit etre approuve"):
                    services.api_runs.execute_run(contract_id=contract.contract_id)
                services.api_runs.approve_run_contract(contract_id=contract.contract_id, founder_decision="go")
                resumed = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Le lot reste limite au design.",
                                "why": "Le contrat amende retire le patch final et cible seulement le design.",
                                "alternatives": ["Ajouter un patch dans un second run."],
                                "files_to_change": ["docs/integrations/API_RUN_CONTRACT.md"],
                                "interfaces": ["ClarificationReport"],
                                "patch_outline": ["Documenter la regle.", "Implementer ensuite."],
                                "tests": ["Verifier le workflow de clarification."],
                                "risks": ["Le lot suivant devra encore implementer le patch."],
                                "acceptance_criteria": ["Le run reste borne au design du guard."],
                                "open_questions": [],
                                "clarification_needed": False,
                                "blocking_reason": "",
                                "recommended_contract_change": "",
                                "question_for_founder": "",
                            }
                        ),
                        "usage": {"input_tokens": 500, "output_tokens": 180},
                    },
                )
                self.assertEqual(resumed["result"].status, ApiRunStatus.COMPLETED)
                final_contract = services.api_runs.get_run_contract(contract.contract_id)
                self.assertEqual(final_contract.metadata["approval_round"], 2)
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

    def test_guardian_pre_spend_check_allows_run_when_budget_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.api_runs.execution_policy.daily_budget_limit_eur = 1.0
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier le guardian budget ok.",
                    branch_name="codex/test-guardian-budget-ok",
                    skill_tags=["audit"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                request = ApiRunRequest(
                    run_request_id=new_id("run_request"),
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                    mode=ApiRunMode.AUDIT,
                    objective=context_pack.objective,
                    branch_name=context_pack.branch_name,
                )

                allowed, reason = services.api_runs._guardian_pre_spend_check(
                    request=request,
                    prompt_template=prompt,
                )

                self.assertTrue(allowed)
                self.assertIsNone(reason)
            finally:
                services.close()

    def test_guardian_pre_spend_check_blocks_when_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.api_runs.execution_policy.daily_budget_limit_eur = 0.20
                now_iso = datetime.now(timezone.utc).isoformat()
                services.api_runs._persist_run_result(
                    ApiRunResult(
                        run_id=new_id("api_run"),
                        run_request_id=new_id("run_request"),
                        model="gpt-5.4",
                        mode=ApiRunMode.AUDIT,
                        status=ApiRunStatus.COMPLETED,
                        estimated_cost_eur=0.15,
                        created_at=now_iso,
                        updated_at=now_iso,
                    )
                )
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier le guardian budget bloque.",
                    branch_name="codex/test-guardian-budget-blocked",
                    skill_tags=["audit"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                request = ApiRunRequest(
                    run_request_id=new_id("run_request"),
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                    mode=ApiRunMode.AUDIT,
                    objective=context_pack.objective,
                    branch_name=context_pack.branch_name,
                )

                allowed, reason = services.api_runs._guardian_pre_spend_check(
                    request=request,
                    prompt_template=prompt,
                )

                self.assertFalse(allowed)
                self.assertIsNotNone(reason)
                self.assertIn("budget_exceeded:", str(reason))
            finally:
                services.close()

    def test_guardian_pre_spend_check_blocks_when_loop_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.api_runs.execution_policy.daily_budget_limit_eur = 10.0
                services.api_runs.execution_policy.loop_detection_window_hours = 2
                services.api_runs.execution_policy.loop_detection_threshold = 3
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.DESIGN,
                    objective="Verifier le guardian boucle.",
                    branch_name="codex/test-guardian-loop",
                    skill_tags=["design"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                now_iso = datetime.now(timezone.utc).isoformat()
                for _ in range(3):
                    services.api_runs._persist_run_request(
                        ApiRunRequest(
                            run_request_id=new_id("run_request"),
                            context_pack_id=context_pack.context_pack_id,
                            prompt_template_id=prompt.prompt_template_id,
                            mode=ApiRunMode.DESIGN,
                            objective=context_pack.objective,
                            branch_name=context_pack.branch_name,
                            created_at=now_iso,
                            updated_at=now_iso,
                        )
                    )
                request = ApiRunRequest(
                    run_request_id=new_id("run_request"),
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                    mode=ApiRunMode.DESIGN,
                    objective=context_pack.objective,
                    branch_name=context_pack.branch_name,
                )

                allowed, reason = services.api_runs._guardian_pre_spend_check(
                    request=request,
                    prompt_template=prompt,
                )

                self.assertFalse(allowed)
                self.assertIsNotNone(reason)
                self.assertIn("loop_detected:", str(reason))
            finally:
                services.close()

    def test_guardian_pre_spend_check_allows_override_even_if_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.api_runs.execution_policy.daily_budget_limit_eur = 0.01
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.GENERATE_PATCH,
                    objective="Verifier le guardian override.",
                    branch_name="codex/test-guardian-override",
                    skill_tags=["generate_patch"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                request = ApiRunRequest(
                    run_request_id=new_id("run_request"),
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                    mode=ApiRunMode.GENERATE_PATCH,
                    objective=context_pack.objective,
                    branch_name=context_pack.branch_name,
                    metadata={"guardian_override": True},
                )

                allowed, reason = services.api_runs._guardian_pre_spend_check(
                    request=request,
                    prompt_template=prompt,
                )

                self.assertTrue(allowed)
                self.assertIsNone(reason)
            finally:
                services.close()

    def test_execute_run_returns_clarification_required_when_guardian_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.api_runs.execution_policy.daily_budget_limit_eur = 0.01
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Verifier le guardian bloque avant l'appel API.",
                    branch_name="codex/test-guardian-blocked",
                    skill_tags=["audit", "guardian"],
                )

                def _runner(*_args, **_kwargs):
                    raise AssertionError("response_runner should not be called when guardian blocks the run")

                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=_runner,
                )

                self.assertEqual(payload["result"].status, ApiRunStatus.CLARIFICATION_REQUIRED)
                self.assertTrue(payload["result"].metadata["guardian_blocked"])
                self.assertIn("clarification_report_path", payload["result"].metadata)
                current_contract = services.api_runs.get_run_contract(contract.contract_id)
                self.assertEqual(current_contract.status, RunContractStatus.PREPARED)
                deliveries = services.api_runs.list_operator_deliveries(limit=10)["deliveries"]
                self.assertEqual(len(deliveries), 1)
                self.assertEqual(deliveries[0]["event"]["kind"], "clarification_required")
            finally:
                services.close()

    def test_execute_run_continues_normally_when_guardian_allows(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.api_runs.execution_policy.daily_budget_limit_eur = 5.0
                contract = _prepare_approved_contract(
                    services,
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Verifier le guardian laisse passer.",
                    branch_name="codex/test-guardian-allowed",
                    skill_tags=["patch_plan", "guardian"],
                )
                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Le guardian a laisse passer le lot.",
                                "why": "Le budget et la boucle sont dans les limites.",
                                "alternatives": [],
                                "files_to_change": ["src/project_os_core/api_runs/service.py"],
                                "interfaces": ["ApiRunRequest"],
                                "patch_outline": ["Passer le guard.", "Produire le plan."],
                                "tests": ["Verifier la garde avant appel API."],
                                "risks": ["Aucun risque supplementaire."],
                                "acceptance_criteria": ["Le run passe le guardian puis produit son resultat."],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 40, "output_tokens": 20},
                    },
                )

                self.assertEqual(payload["result"].status, ApiRunStatus.COMPLETED)
                self.assertNotIn("guardian_blocked", payload["result"].metadata)
            finally:
                services.close()

    def test_call_reviewer_parses_claude_json_and_persists_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                class _FakeUsage:
                    input_tokens = 240
                    output_tokens = 60

                    def model_dump(self):
                        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

                class _FakeBlock:
                    type = "text"
                    text = json.dumps(
                        {
                            "verdict": "accepted_with_reserves",
                            "issues_found": 2,
                            "critical": 0,
                            "high": 1,
                            "summary": "One interface mismatch remains in the generated plan.",
                            "recommendation": "Tighten the interface contract before integration.",
                        }
                    )

                class _FakeResponse:
                    model = "claude-sonnet-4-20250514"
                    content = [_FakeBlock()]
                    usage = _FakeUsage()

                    def model_dump(self):
                        return {
                            "model": self.model,
                            "content": [{"type": "text", "text": self.content[0].text}],
                            "usage": self.usage.model_dump(),
                        }

                captured: dict[str, object] = {}

                class _FakeMessages:
                    def create(self, **kwargs):
                        captured.update(kwargs)
                        return _FakeResponse()

                class _FakeAnthropic:
                    def __init__(self, *, api_key):
                        captured["api_key"] = api_key
                        self.messages = _FakeMessages()

                services.api_runs._call_reviewer = services.api_runs.__class__._call_reviewer.__get__(
                    services.api_runs,
                    services.api_runs.__class__,
                )
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Audit the generated patch plan.",
                    branch_name="codex/test-claude-review",
                    skill_tags=["patch_plan", "review"],
                    source_paths=["src/project_os_core/api_runs/service.py"],
                )
                result = ApiRunResult(
                    run_id=new_id("api_run"),
                    run_request_id=new_id("run_request"),
                    model="gpt-5.4",
                    mode=ApiRunMode.PATCH_PLAN,
                    status=ApiRunStatus.COMPLETED,
                    structured_output={
                        "decision": "Add the reviewer bridge.",
                        "why": "Cross-model review is now mandatory.",
                        "files_to_change": ["src/project_os_core/api_runs/service.py"],
                        "patch_outline": ["Add Claude call.", "Persist review artifacts."],
                        "tests": ["Unit-test reviewer parsing."],
                        "risks": ["Prompt drift."],
                    },
                    usage={"input_tokens": 100, "output_tokens": 50},
                )
                with patch("project_os_core.api_runs.service.Anthropic", _FakeAnthropic):
                    review = services.api_runs._call_reviewer(result=result, context_pack=context_pack)

                self.assertEqual(review.verdict.value, "accepted_with_reserves")
                self.assertEqual(review.metadata["issues_found"], 2)
                self.assertEqual(review.metadata["high"], 1)
                self.assertTrue(Path(str(review.metadata["artifact_path"])).exists())
                review_rows = services.database.fetchall("SELECT * FROM api_run_reviews WHERE run_id = ?", (result.run_id,))
                self.assertEqual(len(review_rows), 1)
                self.assertEqual(captured["api_key"], "anthropic-test-secret")
                self.assertEqual(captured["model"], "claude-sonnet-4-20250514")
                self.assertIn("Quality gates:", str(captured["messages"][0]["content"]))
                self.assertIn("Return exactly one JSON object", str(captured["system"]))
            finally:
                services.close()

    def test_review_verdict_parser_accepts_needs_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                verdict = services.api_runs._review_verdict({"verdict": "needs_revision"})
                self.assertEqual(verdict, ApiRunReviewVerdict.NEEDS_REVISION)
            finally:
                services.close()

    def test_completion_report_handles_needs_revision_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                request = ApiRunRequest(
                    run_request_id=new_id("run_request"),
                    context_pack_id=new_id("context_pack"),
                    prompt_template_id=new_id("mega_prompt"),
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Revise the patch plan.",
                    branch_name="codex/test-needs-revision",
                )
                result = ApiRunResult(
                    run_id=new_id("api_run"),
                    run_request_id=request.run_request_id,
                    model="gpt-5.4",
                    mode=request.mode,
                    status=ApiRunStatus.COMPLETED,
                    structured_output={"patch_outline": ["Revise the interface contract."]},
                )
                review = ApiRunReview(
                    review_id=new_id("run_review"),
                    run_id=result.run_id,
                    verdict=ApiRunReviewVerdict.NEEDS_REVISION,
                    reviewer="claude-sonnet-4-20250514",
                    findings=["The contract still needs revision."],
                )

                report = services.api_runs._build_completion_report(review=review, result=result, request=request)

                self.assertEqual(report.verdict, "needs_revision")
                self.assertIn("revise", report.summary.lower())
                self.assertIn("relancer la revue", str(report.next_action).lower())
            finally:
                services.close()

    def test_call_translator_filters_run_started_without_api_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                event = RunLifecycleEvent(
                    lifecycle_event_id=new_id("lifecycle_event"),
                    run_id=new_id("api_run"),
                    run_request_id=new_id("run_request"),
                    kind=RunLifecycleEventKind.RUN_STARTED,
                    title="Run demarre",
                    summary="Le lot a commence.",
                    branch_name="codex/test-translator-filter",
                    mode=ApiRunMode.AUDIT,
                    channel_hint=OperatorChannelHint.RUNS_LIVE,
                    status=ApiRunStatus.RUNNING,
                    phase="demarrage",
                )

                class _ShouldNotBeCalled:
                    def __init__(self, *args, **kwargs):
                        raise AssertionError("Anthropic should not be instantiated for filtered events")

                services.api_runs._call_translator = services.api_runs.__class__._call_translator.__get__(
                    services.api_runs,
                    services.api_runs.__class__,
                )
                with patch("project_os_core.api_runs.service.Anthropic", _ShouldNotBeCalled):
                    translated = services.api_runs._call_translator(event=event)

                self.assertIsNone(translated)
            finally:
                services.close()

    def test_call_translator_returns_french_message_trimmed_to_three_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                class _FakeUsage:
                    input_tokens = 220
                    output_tokens = 50

                    def model_dump(self):
                        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

                class _FakeBlock:
                    type = "text"
                    text = "codex/test-translate termine — Le lot est pret.\n3 fichiers, 0.12EUR. Review dispo au retour.\nAucune action requise.\nLigne de trop."

                class _FakeResponse:
                    content = [_FakeBlock()]
                    usage = _FakeUsage()

                captured: dict[str, object] = {}

                class _FakeMessages:
                    def create(self, **kwargs):
                        captured.update(kwargs)
                        return _FakeResponse()

                class _FakeAnthropic:
                    def __init__(self, *, api_key):
                        captured["api_key"] = api_key
                        self.messages = _FakeMessages()

                services.api_runs._call_translator = services.api_runs.__class__._call_translator.__get__(
                    services.api_runs,
                    services.api_runs.__class__,
                )
                event = RunLifecycleEvent(
                    lifecycle_event_id=new_id("lifecycle_event"),
                    run_id=new_id("api_run"),
                    run_request_id=new_id("run_request"),
                    kind=RunLifecycleEventKind.RUN_COMPLETED,
                    title="Run termine",
                    summary="Le run est termine et la review Claude est disponible pour decision.",
                    branch_name="codex/test-translate",
                    mode=ApiRunMode.PATCH_PLAN,
                    channel_hint=OperatorChannelHint.RUNS_LIVE,
                    status=ApiRunStatus.COMPLETED,
                    phase="termine",
                )
                result = ApiRunResult(
                    run_id=event.run_id,
                    run_request_id=event.run_request_id,
                    model="gpt-5.4",
                    mode=ApiRunMode.PATCH_PLAN,
                    status=ApiRunStatus.COMPLETED,
                    structured_output={"files_to_change": ["a.py", "b.py", "c.py"]},
                    estimated_cost_eur=0.12,
                    usage={"input_tokens": 100, "output_tokens": 60},
                )
                with patch("project_os_core.api_runs.service.Anthropic", _FakeAnthropic):
                    translated = services.api_runs._call_translator(event=event, result=result)

                self.assertIsNotNone(translated)
                self.assertLessEqual(len(str(translated).splitlines()), 3)
                self.assertIn("termine", str(translated))
                self.assertEqual(captured["api_key"], "anthropic-test-secret")
                self.assertEqual(captured["model"], "claude-haiku-4-5-20251001")
                self.assertEqual(captured["max_tokens"], 256)
            finally:
                services.close()

    def test_call_translator_falls_back_when_claude_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                class _RaisingMessages:
                    def create(self, **kwargs):
                        raise RuntimeError("haiku_down")

                class _RaisingAnthropic:
                    def __init__(self, *, api_key):
                        self.messages = _RaisingMessages()

                services.api_runs._call_translator = services.api_runs.__class__._call_translator.__get__(
                    services.api_runs,
                    services.api_runs.__class__,
                )
                event = RunLifecycleEvent(
                    lifecycle_event_id=new_id("lifecycle_event"),
                    run_id=new_id("api_run"),
                    run_request_id=new_id("run_request"),
                    kind=RunLifecycleEventKind.RUN_FAILED,
                    title="Run bloque",
                    summary="Le run a echoue.",
                    branch_name="codex/test-translate-fallback",
                    mode=ApiRunMode.GENERATE_PATCH,
                    channel_hint=OperatorChannelHint.INCIDENTS,
                    status=ApiRunStatus.FAILED,
                    phase="bloque",
                    recommended_action="Aucune action requise.",
                )
                with patch("project_os_core.api_runs.service.Anthropic", _RaisingAnthropic):
                    translated = services.api_runs._call_translator(event=event)

                self.assertEqual(translated, "codex/test-translate-fallback echoue.\nAucune action requise.")
            finally:
                services.close()

    def test_translator_cost_estimate_stays_below_two_milli_eur(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                estimated = services.api_runs._estimate_cost_eur(
                    model="claude-haiku-4-5-20251001",
                    usage={"input_tokens": 220, "output_tokens": 50},
                )
                self.assertLess(estimated, 0.002)
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
