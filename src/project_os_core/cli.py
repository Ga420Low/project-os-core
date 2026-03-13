from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from .api_runs.dashboard import serve_dashboard
from .bootstrap import bootstrap_environment, doctor_report, health_snapshot
from .gateway.openclaw_adapter import build_dispatch_from_openclaw_payload
from .models import (
    ActionRiskClass,
    ApiRunMode,
    ApiRunReviewVerdict,
    ApiRunStatus,
    ApprovalStatus,
    ChannelEvent,
    ConversationThreadRef,
    DecisionStatus,
    MemoryTier,
    MemoryType,
    MissionIntent,
    OperatorAttachment,
    OperatorEnvelope,
    OperatorMessage,
    RetrievalContext,
    RuntimeState,
    RuntimeVerdict,
    new_id,
    to_jsonable,
)
from .services import build_app_services


def _json_arg(value: str | None) -> dict[str, Any]:
    return json.loads(value) if value else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="project-os")
    parser.add_argument("--config-path", help=argparse.SUPPRESS)
    parser.add_argument("--policy-path", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--strict", action="store_true")

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--strict", action="store_true")

    health_parser = subparsers.add_parser("health")
    health_sub = health_parser.add_subparsers(dest="health_command", required=True)
    health_sub.add_parser("snapshot")

    secrets_parser = subparsers.add_parser("secrets")
    secrets_sub = secrets_parser.add_subparsers(dest="secrets_command", required=True)
    secrets_sub.add_parser("doctor")
    secrets_push = secrets_sub.add_parser("push-openai-to-infisical")
    secrets_push.add_argument("--mark-infisical-required", action="store_true")

    memory_parser = subparsers.add_parser("memory")
    memory_sub = memory_parser.add_subparsers(dest="memory_command", required=True)

    memory_add = memory_sub.add_parser("add")
    memory_add.add_argument("--user-id", required=True)
    memory_add.add_argument("--content", required=True)
    memory_add.add_argument("--project-id")
    memory_add.add_argument("--mission-id")
    memory_add.add_argument("--memory-type", default=MemoryType.EPISODIC.value)
    memory_add.add_argument("--tier", default=MemoryTier.HOT.value)
    memory_add.add_argument("--tag", action="append", default=[])
    memory_add.add_argument("--metadata")

    memory_search = memory_sub.add_parser("search")
    memory_search.add_argument("--user-id", required=True)
    memory_search.add_argument("--query", required=True)
    memory_search.add_argument("--project-id")
    memory_search.add_argument("--mission-id")
    memory_search.add_argument("--tag", action="append", default=[])
    memory_search.add_argument("--limit", type=int, default=5)

    memory_sub.add_parser("reindex")

    runtime_parser = subparsers.add_parser("runtime")
    runtime_sub = runtime_parser.add_subparsers(dest="runtime_command", required=True)

    session_open = runtime_sub.add_parser("open-session")
    session_open.add_argument("--profile-name", required=True)
    session_open.add_argument("--owner", required=True)
    session_open.add_argument("--status", default="ready")
    session_open.add_argument("--metadata")

    record_state = runtime_sub.add_parser("record-state")
    record_state.add_argument("--session-id", required=True)
    record_state.add_argument("--verdict", default=RuntimeVerdict.READY.value)
    record_state.add_argument("--active-profile")
    record_state.add_argument("--mission-run-id")
    record_state.add_argument("--status-summary")
    record_state.add_argument("--blocker", action="append", default=[])
    record_state.add_argument("--metadata")

    create_approval = runtime_sub.add_parser("create-approval")
    create_approval.add_argument("--requested-by", required=True)
    create_approval.add_argument("--risk-tier", required=True)
    create_approval.add_argument("--reason", required=True)
    create_approval.add_argument("--mission-run-id")
    create_approval.add_argument("--expires-at")
    create_approval.add_argument("--metadata")

    resolve_approval = runtime_sub.add_parser("resolve-approval")
    resolve_approval.add_argument("--approval-id", required=True)
    resolve_approval.add_argument("--status", choices=[item.value for item in ApprovalStatus], required=True)
    resolve_approval.add_argument("--metadata")

    record_evidence = runtime_sub.add_parser("record-evidence")
    record_evidence.add_argument("--session-id", required=True)
    record_evidence.add_argument("--action-name", required=True)
    record_evidence.add_argument("--success", action="store_true")
    record_evidence.add_argument("--summary")
    record_evidence.add_argument("--result-code")
    record_evidence.add_argument("--failure-reason")
    record_evidence.add_argument("--policy-verdict")
    record_evidence.add_argument("--pre-state")
    record_evidence.add_argument("--post-state")
    record_evidence.add_argument("--metadata")

    router_parser = subparsers.add_parser("router")
    router_sub = router_parser.add_subparsers(dest="router_command", required=True)

    router_simulate = router_sub.add_parser("simulate")
    _add_router_args(router_simulate)

    router_route = router_sub.add_parser("route-intent")
    _add_router_args(router_route)

    gateway_parser = subparsers.add_parser("gateway")
    gateway_sub = gateway_parser.add_subparsers(dest="gateway_command", required=True)
    gateway_discord = gateway_sub.add_parser("ingest-discord")
    _add_gateway_args(gateway_discord)
    gateway_openclaw = gateway_sub.add_parser("ingest-openclaw-event")
    gateway_openclaw.add_argument("--stdin", action="store_true")
    gateway_openclaw.add_argument("--file")
    gateway_openclaw.add_argument("--target-profile")
    gateway_openclaw.add_argument("--requested-worker")
    gateway_openclaw.add_argument("--risk-class", choices=[item.value for item in ActionRiskClass])
    gateway_openclaw.add_argument("--metadata")

    openclaw_parser = subparsers.add_parser("openclaw")
    openclaw_sub = openclaw_parser.add_subparsers(dest="openclaw_command", required=True)
    openclaw_bootstrap = openclaw_sub.add_parser("bootstrap")
    openclaw_bootstrap.add_argument("--install-if-missing", action="store_true")
    openclaw_doctor = openclaw_sub.add_parser("doctor")
    openclaw_doctor.add_argument("--with-system-doctor", action="store_true")
    openclaw_replay = openclaw_sub.add_parser("replay")
    openclaw_replay.add_argument("--fixture")
    openclaw_replay.add_argument("--all", action="store_true")
    openclaw_live = openclaw_sub.add_parser("validate-live")
    openclaw_live.add_argument("--channel", required=True)
    openclaw_live.add_argument("--payload-file", required=True)

    orchestration_parser = subparsers.add_parser("orchestration")
    orchestration_sub = orchestration_parser.add_subparsers(dest="orchestration_command", required=True)
    orchestration_sim = orchestration_sub.add_parser("simulate")
    _add_router_args(orchestration_sim)

    api_runs_parser = subparsers.add_parser("api-runs")
    api_runs_sub = api_runs_parser.add_subparsers(dest="api_runs_command", required=True)

    api_build = api_runs_sub.add_parser("build-context")
    _add_api_run_request_args(api_build)

    api_prompt = api_runs_sub.add_parser("render-prompt")
    api_prompt.add_argument("--context-pack-id", required=True)

    api_contract = api_runs_sub.add_parser("prepare-contract")
    api_contract.add_argument("--context-pack-id", required=True)
    api_contract.add_argument("--prompt-template-id", required=True)
    api_contract.add_argument("--target-profile")
    api_contract.add_argument("--metadata")

    api_contract_approve = api_runs_sub.add_parser("approve-contract")
    api_contract_approve.add_argument("--contract-id", required=True)
    api_contract_approve.add_argument("--decision", choices=["go", "go_avec_correction", "stop"], required=True)
    api_contract_approve.add_argument("--notes")

    api_contract_show = api_runs_sub.add_parser("show-contract")
    api_contract_show.add_argument("--contract-id", required=True)

    api_execute = api_runs_sub.add_parser("execute")
    _add_api_run_request_args(api_execute, require_core=False)
    api_execute.add_argument("--expected-output", action="append", default=[])
    api_execute.add_argument("--contract-id")

    api_review = api_runs_sub.add_parser("review-result")
    api_review.add_argument("--run-id", required=True)
    api_review.add_argument("--verdict", choices=[item.value for item in ApiRunReviewVerdict], required=True)
    api_review.add_argument("--reviewer", required=True)
    api_review.add_argument("--finding", action="append", default=[])
    api_review.add_argument("--accepted-change", action="append", default=[])
    api_review.add_argument("--followup-action", action="append", default=[])
    api_review.add_argument("--metadata")

    api_set = api_runs_sub.add_parser("set-status")
    api_set.add_argument("--run-id", required=True)
    api_set.add_argument("--status", choices=[item.value for item in ApiRunStatus], required=True)

    api_show = api_runs_sub.add_parser("show-artifacts")
    api_show.add_argument("--run-id", required=True)

    api_monitor = api_runs_sub.add_parser("monitor")
    api_monitor.add_argument("--limit", type=int, default=5)
    api_monitor.add_argument("--watch", action="store_true")
    api_monitor.add_argument("--interval", type=float, default=3.0)
    api_monitor.add_argument("--iterations", type=int, default=0)

    api_dashboard = api_runs_sub.add_parser("dashboard")
    api_dashboard.add_argument("--host", default="127.0.0.1")
    api_dashboard.add_argument("--port", type=int, default=8765)
    api_dashboard.add_argument("--limit", type=int, default=8)
    api_dashboard.add_argument("--refresh-seconds", type=int, default=4)
    api_dashboard.add_argument("--open-browser", action="store_true")

    learning_parser = subparsers.add_parser("learning")
    learning_sub = learning_parser.add_subparsers(dest="learning_command", required=True)

    learning_confirm = learning_sub.add_parser("confirm-decision")
    _add_learning_decision_args(learning_confirm)

    learning_change = learning_sub.add_parser("change-decision")
    _add_learning_decision_args(learning_change)

    learning_loop = learning_sub.add_parser("record-loop")
    learning_loop.add_argument("--pattern", required=True)
    learning_loop.add_argument("--impacted-area", required=True)
    learning_loop.add_argument("--recommended-reset", required=True)
    learning_loop.add_argument("--source-id", action="append", default=[])
    learning_loop.add_argument("--metadata")

    learning_refresh = learning_sub.add_parser("recommend-refresh")
    learning_refresh.add_argument("--cause", required=True)
    learning_refresh.add_argument("--context", action="append", default=[])
    learning_refresh.add_argument("--next-step", required=True)
    learning_refresh.add_argument("--source-id", action="append", default=[])
    learning_refresh.add_argument("--metadata")

    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        print(json.dumps(bootstrap_environment(strict=bool(args.strict)), indent=2, ensure_ascii=True, sort_keys=True))
        return 0
    if args.command == "doctor":
        try:
            report = doctor_report(strict=bool(args.strict))
        except RuntimeError:
            report = doctor_report(strict=False)
            print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
            return 1
        print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
        return 0
    if args.command == "health" and args.health_command == "snapshot":
        print(json.dumps(health_snapshot(), indent=2, ensure_ascii=True, sort_keys=True))
        return 0

    services = build_app_services(config_path=args.config_path, policy_path=args.policy_path)
    try:
        if args.command == "secrets" and args.secrets_command == "doctor":
            print(json.dumps(services.secret_resolver.source_report(), indent=2, ensure_ascii=True, sort_keys=True))
            return 0
        if args.command == "secrets" and args.secrets_command == "push-openai-to-infisical":
            payload = services.secret_resolver.push_to_infisical("OPENAI_API_KEY")
            if args.mark_infisical_required:
                _mark_infisical_required(services.config.repo_root)
                payload["runtime_policy_local_updated"] = True
            print(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True))
            return 0

        if args.command == "memory":
            if args.memory_command == "add":
                record = services.memory.remember(
                    content=args.content,
                    user_id=args.user_id,
                    project_id=args.project_id,
                    mission_id=args.mission_id,
                    memory_type=MemoryType(args.memory_type),
                    tier=MemoryTier(args.tier),
                    tags=args.tag,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(record), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.memory_command == "search":
                context = RetrievalContext(
                    query=args.query,
                    user_id=args.user_id,
                    project_id=args.project_id,
                    mission_id=args.mission_id,
                    tags=args.tag,
                    limit=args.limit,
                )
                print(json.dumps(services.memory.search(context), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.memory_command == "reindex":
                print(json.dumps(services.memory.reindex(), indent=2, ensure_ascii=True, sort_keys=True))
                return 0

        if args.command == "runtime":
            if args.runtime_command == "open-session":
                session = services.runtime.open_session(
                    profile_name=args.profile_name,
                    owner=args.owner,
                    status=args.status,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(session), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.runtime_command == "record-state":
                state = RuntimeState(
                    runtime_state_id=new_id("runtime_state"),
                    session_id=args.session_id,
                    verdict=RuntimeVerdict(args.verdict),
                    active_profile=args.active_profile,
                    mission_run_id=args.mission_run_id,
                    status_summary=args.status_summary,
                    blockers=args.blocker,
                    metadata=_json_arg(args.metadata),
                )
                stored = services.runtime.record_runtime_state(state)
                print(json.dumps(to_jsonable(stored), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.runtime_command == "create-approval":
                approval = services.runtime.create_approval(
                    requested_by=args.requested_by,
                    risk_tier=args.risk_tier,
                    reason=args.reason,
                    mission_run_id=args.mission_run_id,
                    expires_at=args.expires_at,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(approval), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.runtime_command == "resolve-approval":
                services.runtime.resolve_approval(
                    approval_id=args.approval_id,
                    status=ApprovalStatus(args.status),
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps({"approval_id": args.approval_id, "status": args.status}, indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.runtime_command == "record-evidence":
                evidence = services.runtime.record_action_evidence(
                    session_id=args.session_id,
                    action_name=args.action_name,
                    success=bool(args.success),
                    summary=args.summary,
                    result_code=args.result_code,
                    failure_reason=args.failure_reason,
                    policy_verdict=args.policy_verdict,
                    pre_state=_json_arg(args.pre_state),
                    post_state=_json_arg(args.post_state),
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(evidence), indent=2, ensure_ascii=True, sort_keys=True))
                return 0

        if args.command == "router":
            intent = _router_intent_from_args(args)
            decision, trace, mission_run = services.router.route_intent(
                intent,
                persist=args.router_command == "route-intent",
            )
            payload = {
                "intent": to_jsonable(intent),
                "decision": to_jsonable(decision),
                "trace": to_jsonable(trace),
                "mission_run": to_jsonable(mission_run) if mission_run else None,
            }
            exit_code = 0 if decision.allowed else 1
            print(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True))
            return exit_code

        if args.command == "gateway" and args.gateway_command == "ingest-discord":
            event = _gateway_event_from_args(args)
            dispatch = services.gateway.dispatch_event(
                event,
                target_profile=args.target_profile,
                requested_worker=args.requested_worker,
                risk_class=ActionRiskClass(args.risk_class) if args.risk_class else None,
                metadata=_json_arg(args.metadata),
            )
            print(json.dumps(to_jsonable(dispatch), indent=2, ensure_ascii=True, sort_keys=True))
            return 0 if dispatch.operator_reply.reply_kind != "blocked" else 1
        if args.command == "gateway" and args.gateway_command == "ingest-openclaw-event":
            payload = _read_json_payload(args)
            adapted = build_dispatch_from_openclaw_payload(payload)
            dispatch = services.gateway.dispatch_event(
                adapted.event,
                target_profile=args.target_profile or adapted.target_profile,
                requested_worker=args.requested_worker or adapted.requested_worker,
                risk_class=ActionRiskClass(args.risk_class) if args.risk_class else adapted.risk_class,
                metadata={**(adapted.metadata or {}), **_json_arg(args.metadata)},
            )
            print(json.dumps(to_jsonable(dispatch), indent=2, ensure_ascii=True, sort_keys=True))
            return 0 if dispatch.operator_reply.reply_kind != "blocked" else 1

        if args.command == "openclaw":
            if args.openclaw_command == "bootstrap":
                report = services.openclaw.bootstrap(install_if_missing=bool(args.install_if_missing))
                print(json.dumps(to_jsonable(report), indent=2, ensure_ascii=True, sort_keys=True))
                return 0 if report.readiness == "ok" else 1
            if args.openclaw_command == "doctor":
                report = services.openclaw.doctor(with_system_doctor=bool(args.with_system_doctor))
                print(json.dumps(to_jsonable(report), indent=2, ensure_ascii=True, sort_keys=True))
                return 0 if report.verdict == "OK" else 1
            if args.openclaw_command == "replay":
                report = services.openclaw.replay(fixture_id=args.fixture, run_all=bool(args.all))
                print(json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True))
                return 0 if report["verdict"] == "OK" else 1
            if args.openclaw_command == "validate-live":
                report = services.openclaw.validate_live(channel=args.channel, payload_file=args.payload_file)
                print(json.dumps(to_jsonable(report), indent=2, ensure_ascii=True, sort_keys=True))
                return 0 if report.success else 1

        if args.command == "orchestration" and args.orchestration_command == "simulate":
            intent = _router_intent_from_args(args)
            decision, _, mission_run = services.router.route_intent(intent, persist=True)
            if mission_run is None or not decision.allowed:
                payload = {
                    "intent": to_jsonable(intent),
                    "decision": to_jsonable(decision),
                    "mission_run": to_jsonable(mission_run) if mission_run else None,
                }
                print(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True))
                return 1
            prepared = services.orchestration.prepare_execution(mission_run=mission_run, decision=decision)
            print(json.dumps(to_jsonable(prepared), indent=2, ensure_ascii=True, sort_keys=True))
            return 0

        if args.command == "api-runs":
            if args.api_runs_command == "build-context":
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode(args.mode),
                    objective=args.objective,
                    branch_name=args.branch_name,
                    skill_tags=args.skill_tag,
                    target_profile=args.target_profile,
                    source_paths=args.source_ref,
                    constraints=args.constraint,
                    acceptance_criteria=args.acceptance,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(context_pack), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.api_runs_command == "render-prompt":
                prompt = services.api_runs.render_prompt(context_pack_id=args.context_pack_id)
                print(json.dumps(to_jsonable(prompt), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.api_runs_command == "prepare-contract":
                contract = services.api_runs.create_run_contract(
                    context_pack_id=args.context_pack_id,
                    prompt_template_id=args.prompt_template_id,
                    target_profile=args.target_profile,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(contract), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.api_runs_command == "approve-contract":
                contract = services.api_runs.approve_run_contract(
                    contract_id=args.contract_id,
                    founder_decision=args.decision,
                    notes=args.notes,
                )
                print(json.dumps(to_jsonable(contract), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.api_runs_command == "show-contract":
                contract = services.api_runs.get_run_contract(args.contract_id)
                print(json.dumps(to_jsonable(contract), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.api_runs_command == "execute":
                payload = services.api_runs.execute_run(
                    mode=ApiRunMode(args.mode) if args.mode else None,
                    objective=args.objective,
                    branch_name=args.branch_name,
                    skill_tags=args.skill_tag,
                    target_profile=args.target_profile,
                    source_paths=args.source_ref,
                    constraints=args.constraint,
                    acceptance_criteria=args.acceptance,
                    expected_outputs=args.expected_output,
                    metadata=_json_arg(args.metadata),
                    contract_id=args.contract_id,
                )
                print(json.dumps(to_jsonable(payload), indent=2, ensure_ascii=True, sort_keys=True))
                return 0 if payload["result"].status is not ApiRunStatus.FAILED else 1
            if args.api_runs_command == "review-result":
                review = services.api_runs.review_result(
                    run_id=args.run_id,
                    verdict=ApiRunReviewVerdict(args.verdict),
                    reviewer=args.reviewer,
                    findings=args.finding,
                    accepted_changes=args.accepted_change,
                    followup_actions=args.followup_action,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(review), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.api_runs_command == "set-status":
                payload = services.api_runs.set_run_status(run_id=args.run_id, status=ApiRunStatus(args.status))
                print(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.api_runs_command == "show-artifacts":
                payload = services.api_runs.show_artifacts(run_id=args.run_id)
                print(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.api_runs_command == "monitor":
                if args.watch:
                    return _watch_api_runs_monitor(services, interval=args.interval, iterations=args.iterations, limit=args.limit)
                print(services.api_runs.render_terminal_dashboard(limit=args.limit))
                return 0
            if args.api_runs_command == "dashboard":
                return serve_dashboard(
                    services,
                    host=args.host,
                    port=args.port,
                    limit=args.limit,
                    refresh_seconds=args.refresh_seconds,
                    open_browser=bool(args.open_browser),
                )

        if args.command == "learning":
            if args.learning_command == "confirm-decision":
                record = services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope=args.scope,
                    summary=args.summary,
                    source_run_id=args.source_run_id,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(record), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.learning_command == "change-decision":
                record = services.learning.record_decision(
                    status=DecisionStatus.CHANGED,
                    scope=args.scope,
                    summary=args.summary,
                    source_run_id=args.source_run_id,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(record), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.learning_command == "record-loop":
                loop_signal = services.learning.record_loop_signal(
                    repeated_pattern=args.pattern,
                    impacted_area=args.impacted_area,
                    recommended_reset=args.recommended_reset,
                    source_ids=args.source_id,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(loop_signal), indent=2, ensure_ascii=True, sort_keys=True))
                return 0
            if args.learning_command == "recommend-refresh":
                recommendation = services.learning.recommend_refresh(
                    cause=args.cause,
                    context_to_reload=args.context,
                    next_step=args.next_step,
                    source_ids=args.source_id,
                    metadata=_json_arg(args.metadata),
                )
                print(json.dumps(to_jsonable(recommendation), indent=2, ensure_ascii=True, sort_keys=True))
                return 0

        return 1
    finally:
        services.close()


def _add_router_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--channel", default="cli")
    parser.add_argument("--objective", required=True)
    parser.add_argument("--target-profile", default="core")
    parser.add_argument("--requested-worker")
    parser.add_argument("--risk-class", choices=[item.value for item in ActionRiskClass])
    parser.add_argument("--daily-spend-estimate-eur", type=float, default=0.0)
    parser.add_argument("--monthly-spend-estimate-eur", type=float, default=0.0)
    parser.add_argument("--mission-estimate-eur", type=float)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--metadata")
    parser.add_argument("--founder-approved", action="store_true")
    parser.add_argument("--approval-id")
    parser.add_argument("--exceptional", action="store_true")
    parser.add_argument("--multi-worker", action="store_true")
    parser.add_argument("--ambiguous-recovery", action="store_true")
    parser.add_argument("--budget-justified", action="store_true")
    parser.add_argument("--error-cost", choices=["low", "high"], default="low")


def _add_gateway_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--channel", default="discord")
    parser.add_argument("--surface", default="discord")
    parser.add_argument("--event-type", default="message.created")
    parser.add_argument("--text", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--external-thread-id")
    parser.add_argument("--target-profile", default="core")
    parser.add_argument("--requested-worker")
    parser.add_argument("--risk-class", choices=[item.value for item in ActionRiskClass])
    parser.add_argument("--attachment", action="append", default=[])
    parser.add_argument("--metadata")


def _add_api_run_request_args(parser: argparse.ArgumentParser, *, require_core: bool = True) -> None:
    parser.add_argument("--mode", choices=[item.value for item in ApiRunMode], required=require_core)
    parser.add_argument("--objective", required=require_core)
    parser.add_argument("--branch-name")
    parser.add_argument("--skill-tag", action="append", default=[])
    parser.add_argument("--target-profile")
    parser.add_argument("--source-ref", action="append", default=[])
    parser.add_argument("--constraint", action="append", default=[])
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--metadata")


def _add_learning_decision_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scope", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--source-run-id")
    parser.add_argument("--metadata")


def _router_intent_from_args(args) -> MissionIntent:
    metadata = _json_arg(args.metadata)
    metadata.update(
        {
            "daily_spend_estimate_eur": args.daily_spend_estimate_eur,
            "monthly_spend_estimate_eur": args.monthly_spend_estimate_eur,
            "paths": args.path,
            "founder_approved": bool(args.founder_approved),
            "approval_id": args.approval_id,
            "exceptional": bool(args.exceptional),
            "multi_worker": bool(args.multi_worker),
            "ambiguous_recovery": bool(args.ambiguous_recovery),
            "budget_justified": bool(args.budget_justified),
            "error_cost": args.error_cost,
        }
    )
    if args.mission_estimate_eur is not None:
        metadata["mission_estimate_eur"] = args.mission_estimate_eur
    envelope = OperatorEnvelope(
        envelope_id=new_id("envelope"),
        actor_id=args.actor_id,
        channel=args.channel,
        objective=args.objective,
        target_profile=args.target_profile,
        requested_worker=args.requested_worker,
        requested_risk_class=ActionRiskClass(args.risk_class) if args.risk_class else None,
        metadata=metadata,
    )
    return MissionIntent(
        intent_id=new_id("intent"),
        source="cli",
        actor_id=envelope.actor_id,
        channel=envelope.channel,
        objective=envelope.objective,
        target_profile=envelope.target_profile,
        requested_worker=envelope.requested_worker,
        requested_risk_class=envelope.requested_risk_class,
        metadata=envelope.metadata,
    )


def _gateway_event_from_args(args) -> ChannelEvent:
    thread_ref = ConversationThreadRef(
        thread_id=args.thread_id,
        channel=args.channel,
        external_thread_id=args.external_thread_id,
        metadata={"surface": args.surface},
    )
    attachments = [
        OperatorAttachment(
            attachment_id=new_id("attachment"),
            name=value,
            kind="file",
            metadata={"source": "cli"},
        )
        for value in args.attachment
    ]
    return ChannelEvent(
        event_id=new_id("channel_event"),
        surface=args.surface,
        event_type=args.event_type,
        message=OperatorMessage(
            message_id=new_id("message"),
            actor_id=args.actor_id,
            channel=args.channel,
            text=args.text,
            thread_ref=thread_ref,
            attachments=attachments,
            metadata=_json_arg(args.metadata),
        ),
        raw_payload={"source": "cli"},
    )


def _read_json_payload(args) -> dict[str, Any]:
    if args.stdin:
        raw = sys.stdin.read()
    elif args.file:
        raw = open(args.file, "r", encoding="utf-8").read()
    else:
        raise RuntimeError("gateway ingest-openclaw-event requires --stdin or --file")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("openclaw payload must be a JSON object")
    return payload


def _mark_infisical_required(repo_root) -> None:
    config_dir = repo_root / "config"
    target = config_dir / "runtime_policy.local.json"
    payload = {"secret_config": {"mode": "infisical_required"}}
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
    else:
        existing = {}
    secret_config = dict(existing.get("secret_config", {}))
    secret_config.update(payload["secret_config"])
    existing["secret_config"] = secret_config
    target.write_text(json.dumps(existing, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def _watch_api_runs_monitor(services, *, interval: float, iterations: int, limit: int) -> int:
    count = 0
    try:
        while True:
            os.system("cls")
            print(services.api_runs.render_terminal_dashboard(limit=limit))
            count += 1
            if iterations and count >= iterations:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
