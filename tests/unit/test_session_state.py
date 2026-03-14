from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.database import dump_json
from project_os_core.models import (
    ApiRunMode,
    ApiRunRequest,
    ApiRunResult,
    ApiRunStatus,
    ChannelEvent,
    ClarificationReport,
    CommunicationMode,
    ConversationThreadRef,
    OperatorAudience,
    OperatorMessage,
    RunSpeechPolicy,
    new_id,
)
from project_os_core.services import build_app_services
from project_os_core.session.state import SessionSnapshot


class PersistentSessionStateTests(unittest.TestCase):
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
        return services

    def _build_context_and_prompt(self, services, *, mode: ApiRunMode, objective: str, branch_name: str):
        context = services.api_runs.build_context_pack(
            mode=mode,
            objective=objective,
            branch_name=branch_name,
            skill_tags=["python"],
            target_profile="browser",
            source_paths=[],
        )
        prompt = services.api_runs.render_prompt(context_pack_id=context.context_pack_id)
        return context, prompt

    def _persist_request_and_result(
        self,
        services,
        *,
        prompt,
        context,
        status: ApiRunStatus,
        branch_name: str,
        objective: str,
        contract_id: str | None = None,
        estimated_cost_eur: float = 0.0,
    ):
        request = ApiRunRequest(
            run_request_id=new_id("run_request"),
            context_pack_id=context.context_pack_id,
            prompt_template_id=prompt.prompt_template_id,
            mode=context.mode,
            objective=objective,
            branch_name=branch_name,
            target_profile="browser",
            skill_tags=["python"],
            expected_outputs=list(prompt.output_contract),
            communication_mode=CommunicationMode.BUILDER,
            speech_policy=RunSpeechPolicy.SILENT_UNTIL_TERMINAL_STATE,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            run_contract_required=bool(contract_id),
            contract_id=contract_id,
            status=status,
            metadata={},
        )
        result = ApiRunResult(
            run_id=new_id("api_run"),
            run_request_id=request.run_request_id,
            model=prompt.model,
            mode=context.mode,
            status=status,
            structured_output={},
            prompt_artifact_path=prompt.artifact_path,
            estimated_cost_eur=estimated_cost_eur,
            usage={},
            metadata={},
        )
        services.api_runs._persist_run_request(request)
        services.api_runs._persist_run_result(result)
        return request, result

    def test_load_returns_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                context_running, prompt_running = self._build_context_and_prompt(
                    services,
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Prepare patch plan",
                    branch_name="project-os/running-branch",
                )
                _, running_result = self._persist_request_and_result(
                    services,
                    prompt=prompt_running,
                    context=context_running,
                    status=ApiRunStatus.RUNNING,
                    branch_name="project-os/running-branch",
                    objective="Prepare patch plan",
                    estimated_cost_eur=0.17,
                )

                context_contract, prompt_contract = self._build_context_and_prompt(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Audit memory layer",
                    branch_name="project-os/pending-contract",
                )
                contract = services.api_runs.create_run_contract(
                    context_pack_id=context_contract.context_pack_id,
                    prompt_template_id=prompt_contract.prompt_template_id,
                    target_profile="browser",
                )

                context_clarification, prompt_clarification = self._build_context_and_prompt(
                    services,
                    mode=ApiRunMode.DESIGN,
                    objective="Design new flow",
                    branch_name="project-os/clarification-branch",
                )
                clarification_request, clarification_result = self._persist_request_and_result(
                    services,
                    prompt=prompt_clarification,
                    context=context_clarification,
                    status=ApiRunStatus.CLARIFICATION_REQUIRED,
                    branch_name="project-os/clarification-branch",
                    objective="Design new flow",
                    contract_id=contract.contract_id,
                    estimated_cost_eur=0.23,
                )
                clarification = ClarificationReport(
                    report_id=new_id("clarification_report"),
                    run_id=clarification_result.run_id,
                    cause="Need founder choice",
                    impact="Execution is blocked",
                    question_for_founder="Tu veux A ou B ?",
                    recommended_contract_change="Prendre l'option A",
                    metadata={},
                )
                services.api_runs._persist_clarification_report(clarification)

                context_completed, prompt_completed = self._build_context_and_prompt(
                    services,
                    mode=ApiRunMode.GENERATE_PATCH,
                    objective="Ship patch",
                    branch_name="project-os/completed-branch",
                )
                self._persist_request_and_result(
                    services,
                    prompt=prompt_completed,
                    context=context_completed,
                    status=ApiRunStatus.COMPLETED,
                    branch_name="project-os/completed-branch",
                    objective="Ship patch",
                    estimated_cost_eur=0.41,
                )

                services.runtime.create_approval(
                    requested_by="founder",
                    risk_tier="exceptional",
                    reason="Approve production write",
                    metadata={"action_name": "deploy_patch"},
                )

                services.database.execute(
                    """
                    INSERT INTO api_run_operator_deliveries(
                        delivery_id, lifecycle_event_id, adapter, surface, channel_hint, status,
                        attempts, payload_json, last_error, next_attempt_at, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("delivery"),
                        new_id("lifecycle_event"),
                        "openclaw",
                        "discord",
                        "approvals",
                        "pending",
                        0,
                        dump_json({"translated_message": "Question"}),
                        None,
                        None,
                        dump_json({}),
                        clarification.created_at,
                        clarification.created_at,
                    ),
                )

                services.database.execute(
                    """
                    INSERT INTO mission_runs(
                        mission_run_id, intent_id, objective, profile_name, status, execution_class,
                        routing_decision_id, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (
                        new_id("mission_run"),
                        new_id("intent"),
                        "Mission active",
                        "browser",
                        "running",
                        "assisted",
                        None,
                        dump_json({}),
                    ),
                )

                services.database.execute(
                    """
                    INSERT INTO channel_events(
                        event_id, surface, event_type, actor_id, channel, message_kind,
                        thread_ref_json, message_json, raw_payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        new_id("channel_event"),
                        "discord",
                        "message.created",
                        "founder",
                        "approvals",
                        "approval",
                        dump_json({"thread_id": "thread_1"}),
                        dump_json({"text": "go"}),
                        dump_json({}),
                    ),
                )

                snapshot = services.session_state.load()

                self.assertEqual(len(snapshot.active_runs), 1)
                self.assertEqual(snapshot.active_runs[0]["run_id"], running_result.run_id)
                self.assertEqual(len(snapshot.pending_clarifications), 1)
                self.assertEqual(snapshot.pending_clarifications[0]["report_id"], clarification.report_id)
                self.assertEqual(len(snapshot.pending_contracts), 1)
                self.assertEqual(snapshot.pending_contracts[0]["contract_id"], contract.contract_id)
                self.assertEqual(len(snapshot.pending_approvals), 1)
                self.assertEqual(snapshot.pending_approvals[0]["action_name"], "deploy_patch")
                self.assertEqual(snapshot.pending_deliveries, 1)
                self.assertEqual(len(snapshot.active_missions), 1)
                self.assertAlmostEqual(snapshot.daily_spend_eur, 0.81, places=2)
                self.assertAlmostEqual(snapshot.daily_budget_limit_eur, 5.0, places=2)
                self.assertIsNotNone(snapshot.last_run_completed_at)
                self.assertIsNotNone(snapshot.last_founder_message_at)
                self.assertEqual(clarification_request.contract_id, contract.contract_id)
            finally:
                services.close()

    def test_resolve_intent_approves_single_pending_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                snapshot = SessionSnapshot(pending_contracts=[{"contract_id": "contract_1"}])
                resolved = services.session_state.resolve_intent("go", snapshot=snapshot)
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved.action, "approve_contract")
                self.assertEqual(resolved.target_id, "contract_1")
                self.assertEqual(resolved.confidence, 0.95)
            finally:
                services.close()

    def test_resolve_intent_answers_single_clarification(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                snapshot = SessionSnapshot(
                    pending_clarifications=[{"report_id": "clarif_1", "metadata": {}}],
                )
                resolved = services.session_state.resolve_intent("ouais", snapshot=snapshot)
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved.action, "answer_clarification")
                self.assertEqual(resolved.target_id, "clarif_1")
                self.assertEqual(resolved.metadata["answer"], "approved")
            finally:
                services.close()

    def test_resolve_intent_status_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                resolved = services.session_state.resolve_intent("status", snapshot=SessionSnapshot())
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved.action, "status_request")
            finally:
                services.close()

    def test_resolve_intent_returns_none_when_contract_approval_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                snapshot = SessionSnapshot(
                    pending_contracts=[{"contract_id": "contract_1"}, {"contract_id": "contract_2"}],
                )
                resolved = services.session_state.resolve_intent("go", snapshot=snapshot)
                self.assertIsNone(resolved)
            finally:
                services.close()

    def test_resolve_intent_returns_none_when_go_targets_contract_and_clarification(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                snapshot = SessionSnapshot(
                    pending_contracts=[{"contract_id": "contract_1"}],
                    pending_clarifications=[{"report_id": "clarif_1", "metadata": {}}],
                )
                resolved = services.session_state.resolve_intent("go", snapshot=snapshot)
                self.assertIsNone(resolved)
            finally:
                services.close()

    def test_resolve_intent_returns_none_when_reject_targets_contract_and_clarification(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                snapshot = SessionSnapshot(
                    pending_contracts=[{"contract_id": "contract_1"}],
                    pending_clarifications=[{"report_id": "clarif_1", "metadata": {}}],
                )
                resolved = services.session_state.resolve_intent("non", snapshot=snapshot)
                self.assertIsNone(resolved)
            finally:
                services.close()

    def test_resolve_intent_returns_none_for_unknown_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                resolved = services.session_state.resolve_intent("je pensais a un autre truc", snapshot=SessionSnapshot())
                self.assertIsNone(resolved)
            finally:
                services.close()

    def test_resolve_intent_supports_guardian_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                snapshot = SessionSnapshot(
                    pending_clarifications=[
                        {
                            "report_id": "clarif_guardian",
                            "metadata": {"guardian_blocking_reason": "budget_exceeded"},
                        }
                    ]
                )
                resolved = services.session_state.resolve_intent("force quand meme", snapshot=snapshot)
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved.action, "guardian_override")
                self.assertEqual(resolved.target_id, "clarif_guardian")
            finally:
                services.close()

    def test_gateway_dispatch_approves_single_pending_contract_without_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                context, prompt = self._build_context_and_prompt(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Audit the module",
                    branch_name="project-os/session-contract",
                )
                contract = services.api_runs.create_run_contract(
                    context_pack_id=context.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                    target_profile="browser",
                )
                services.session_state.api_runs.execute_run = lambda contract_id: {  # type: ignore[method-assign]
                    "result": ApiRunResult(
                        run_id="api_run_launched",
                        run_request_id="run_request_launched",
                        model="gpt-5.4",
                        mode=ApiRunMode.AUDIT,
                        status=ApiRunStatus.RUNNING,
                        structured_output={},
                        estimated_cost_eur=0.21,
                        usage={},
                        metadata={},
                    )
                }
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="approvals",
                        text="go",
                        thread_ref=ConversationThreadRef(thread_id="thread_contract", channel="approvals"),
                    ),
                )

                dispatch = services.gateway.dispatch_event(event, target_profile="browser")
                approved = services.api_runs.get_run_contract(contract.contract_id)

                self.assertEqual(approved.status.value, "approved")
                self.assertEqual(dispatch.decision_id, None)
                self.assertEqual(dispatch.operator_reply.reply_kind, "ack")
                self.assertEqual(dispatch.metadata["resolved_action"], "approve_contract")
                self.assertEqual(dispatch.mission_run_id, "api_run_launched")
                self.assertIn("Run lance", dispatch.operator_reply.summary)
                routing_rows = services.database.fetchall("SELECT * FROM routing_decisions")
                self.assertEqual(routing_rows, [])
            finally:
                services.close()

    def test_gateway_persists_channel_event_before_session_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                context, prompt = self._build_context_and_prompt(
                    services,
                    mode=ApiRunMode.AUDIT,
                    objective="Audit the module",
                    branch_name="project-os/session-persist-order",
                )
                services.api_runs.create_run_contract(
                    context_pack_id=context.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                    target_profile="browser",
                )
                services.gateway._execute_resolved_intent = lambda resolved: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="approvals",
                        text="go",
                        thread_ref=ConversationThreadRef(thread_id="thread_contract", channel="approvals"),
                    ),
                )

                with self.assertRaises(RuntimeError):
                    services.gateway.dispatch_event(event, target_profile="browser")

                channel_event = services.database.fetchone("SELECT * FROM channel_events WHERE event_id = ?", (event.event_id,))
                promotion = services.database.fetchone("SELECT * FROM promotion_decisions")
                self.assertIsNotNone(channel_event)
                self.assertIsNotNone(promotion)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
