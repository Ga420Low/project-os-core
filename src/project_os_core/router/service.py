from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..costing import estimate_router_usage, estimate_usage_cost_eur
from ..database import CanonicalDatabase, dump_json
from ..local_model import LocalModelClient
from ..models import (
    ActionRiskClass,
    AdaptiveModelRoute,
    ApprovalGate,
    BudgetState,
    CommunicationMode,
    CostClass,
    DiscordChannelClass,
    ExecutionPolicy,
    MissionExecutionClass,
    MissionIntent,
    MissionRun,
    MissionStatus,
    ModelRouteClass,
    ModelRoute,
    OperatorAudience,
    OperatorEnvelope,
    OperatorMessageKind,
    ProfileCapability,
    RoutingDecision,
    RoutingDecisionTrace,
    RunSpeechPolicy,
    SensitivityClass,
    TraceEntityKind,
    TraceRelationKind,
    RuntimeState,
    RuntimeVerdict,
    new_id,
    to_jsonable,
)
from ..paths import PathPolicy
from ..runtime.store import RuntimeStore
from ..secrets import SecretResolver
from .policy import default_profile_capabilities


class MissionRouter:
    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        runtime: RuntimeStore,
        path_policy: PathPolicy,
        secret_resolver: SecretResolver,
        execution_policy: ExecutionPolicy,
        local_model_client: LocalModelClient | None = None,
        profile_capabilities: dict[str, ProfileCapability] | None = None,
    ):
        self.database = database
        self.runtime = runtime
        self.path_policy = path_policy
        self.secret_resolver = secret_resolver
        self.execution_policy = execution_policy
        self.local_model_client = local_model_client
        self.profile_capabilities = profile_capabilities or default_profile_capabilities()

    def model_stack_health_snapshot(self) -> dict[str, Any]:
        openai_available = bool(self.secret_resolver.get_optional("OPENAI_API_KEY"))
        anthropic_available = bool(self.secret_resolver.get_optional("ANTHROPIC_API_KEY"))
        local_health = self._local_model_health_snapshot()
        local_enabled = bool(self.execution_policy.local_model_enabled)
        api_ready_count = int(openai_available) + int(anthropic_available)
        if api_ready_count >= 2:
            api_status = "ready"
        elif api_ready_count == 1:
            api_status = "degraded"
        else:
            api_status = "blocked"
        return {
            "tiers": {
                ModelRouteClass.FAST.value: {
                    "status": "ready",
                    "reason": "deterministic_first_available",
                },
                ModelRouteClass.LOCAL.value: local_health,
                ModelRouteClass.API.value: {
                    "status": api_status,
                    "reason": "providers_available" if api_ready_count else "no_api_provider_available",
                    "preferred_provider": self._preferred_api_provider(openai_available, anthropic_available),
                },
            },
            "providers": {
                "openai": {
                    "available": openai_available,
                    "model": self.execution_policy.default_model,
                },
                "anthropic": {
                    "available": anthropic_available,
                    "model": self.execution_policy.discord_simple_model,
                },
                "local": {
                    "available": local_health["status"] == "ready",
                    "enabled": local_enabled,
                    "provider": local_health.get("provider"),
                    "model": local_health.get("model") if local_enabled else None,
                    "base_url": local_health.get("base_url") if local_enabled else None,
                    "latency_ms": local_health.get("latency_ms"),
                    "reason": local_health.get("reason"),
                },
            },
        }

    def _local_model_health_snapshot(self) -> dict[str, Any]:
        if not self.execution_policy.local_model_enabled:
            return {
                "status": "absent",
                "reason": "not_configured",
                "provider": None,
                "model": None,
                "base_url": None,
            }
        if self.local_model_client is None:
            return {
                "status": "blocked",
                "reason": "local_model_client_missing",
                "provider": self.execution_policy.local_model_provider,
                "model": self.execution_policy.local_model_name,
                "base_url": self.execution_policy.local_model_base_url,
            }
        health = dict(self.local_model_client.health())
        health.setdefault("provider", self.execution_policy.local_model_provider)
        health.setdefault("model", self.execution_policy.local_model_name)
        health.setdefault("base_url", self.execution_policy.local_model_base_url)
        return health

    def proactive_briefing(self, *, branch_name: str | None = None, limit: int | None = None) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit or self.execution_policy.proactive_briefing_max_items), 5))
        params: list[Any] = []
        where_clause = ""
        if branch_name:
            where_clause = "WHERE req.branch_name = ?"
            params.append(branch_name)
        params.append(bounded_limit)
        rows = self.database.fetchall(
            f"""
            SELECT req.branch_name, req.mode, req.objective, req.target_profile, req.status AS request_status,
                   req.updated_at AS request_updated_at,
                   res.run_id, res.model, res.status AS result_status, res.updated_at AS result_updated_at
            FROM api_run_requests req
            LEFT JOIN api_run_results res ON res.run_request_id = req.run_request_id
            {where_clause}
            ORDER BY COALESCE(res.updated_at, req.updated_at) DESC
            LIMIT ?
            """,
            tuple(params),
        )
        items = [
            {
                "branch_name": str(row["branch_name"]),
                "mode": str(row["mode"]),
                "objective": str(row["objective"]),
                "target_profile": str(row["target_profile"]) if row["target_profile"] else None,
                "request_status": str(row["request_status"]),
                "result_status": str(row["result_status"]) if row["result_status"] else None,
                "model": str(row["model"]) if row["model"] else None,
                "updated_at": str(row["result_updated_at"] or row["request_updated_at"]),
                "run_id": str(row["run_id"]) if row["run_id"] else None,
            }
            for row in rows
        ]
        if not items:
            return {}
        return {
            "count": len(items),
            "items": items,
            "summary": f"{len(items)} recent session summaries available.",
        }

    def envelope_to_intent(self, envelope: OperatorEnvelope) -> MissionIntent:
        return MissionIntent(
            intent_id=new_id("intent"),
            source="operator_envelope",
            actor_id=envelope.actor_id,
            channel=envelope.channel,
            objective=envelope.objective,
            target_profile=envelope.target_profile,
            requested_worker=envelope.requested_worker,
            requested_risk_class=envelope.requested_risk_class,
            communication_mode=envelope.communication_mode,
            operator_language=envelope.operator_language,
            audience=envelope.audience,
            metadata=dict(envelope.metadata),
        )

    def route_intent(
        self,
        intent: MissionIntent,
        *,
        persist: bool = True,
        runtime_override: RuntimeState | None = None,
    ) -> tuple[RoutingDecision, RoutingDecisionTrace, MissionRun | None]:
        runtime_state = runtime_override or self.runtime.latest_runtime_state()
        profile = self._profile_for(intent.target_profile)
        risk_class = intent.requested_risk_class or self._infer_risk_class(intent)
        mission_cost_class = self._classify_cost(intent, risk_class)
        budget_state = self._budget_state(intent, mission_cost_class)
        chosen_worker = self._choose_worker(intent, profile)

        blocked_reasons: list[str] = []
        if runtime_state is None or runtime_state.verdict is not RuntimeVerdict.READY:
            blocked_reasons.append("runtime_not_ready")
        if profile is None:
            blocked_reasons.append("profile_missing")
        if chosen_worker is None:
            blocked_reasons.append("worker_unresolved")
        elif profile and chosen_worker not in profile.allowed_workers:
            blocked_reasons.append("worker_not_allowed")

        for target in self._extract_paths(intent):
            if self.path_policy.is_forbidden(target):
                blocked_reasons.append("forbidden_zone_target")
            elif not self.path_policy.is_managed(target):
                blocked_reasons.append("path_outside_managed_roots")

        missing_secrets = []
        for secret_name in profile.required_secrets if profile else []:
            if not self.secret_resolver.get_optional(secret_name):
                missing_secrets.append(secret_name)
        if missing_secrets:
            blocked_reasons.append("required_secret_missing")

        approval_gate = self._approval_gate(intent, risk_class, budget_state, chosen_worker)
        model_route = self._model_route(intent, mission_cost_class, budget_state, approval_gate)
        communication_mode = self._communication_mode(intent, chosen_worker)
        speech_policy = self._speech_policy(communication_mode)
        adaptive_model_route = self._adaptive_model_route(intent, communication_mode, model_route)

        if not budget_state.within_monthly_limit:
            blocked_reasons.append("monthly_budget_exceeded")
        if model_route.allowed is False and model_route.reason not in blocked_reasons:
            blocked_reasons.append(model_route.reason)

        allowed = not blocked_reasons and (not approval_gate.required or approval_gate.approved)
        execution_class = self._execution_class(risk_class, model_route, approval_gate, allowed)
        mission_run = None
        if persist:
            self._persist_intent(intent)
            mission_run = MissionRun(
                mission_run_id=new_id("mission"),
                intent_id=intent.intent_id,
                objective=intent.objective,
                profile_name=profile.profile_name if profile else None,
                parent_mission_id=None,
                step_index=0,
                total_steps=1,
                status=MissionStatus.QUEUED if allowed else MissionStatus.FAILED,
                execution_class=execution_class,
            )

        decision = RoutingDecision(
            decision_id=new_id("route"),
            intent_id=intent.intent_id,
            mission_run_id=mission_run.mission_run_id if mission_run else None,
            execution_class=execution_class,
            risk_class=risk_class,
            allowed=allowed,
            chosen_worker=chosen_worker,
            model_route=model_route,
            approval_gate=approval_gate,
            budget_state=budget_state,
            communication_mode=communication_mode,
            speech_policy=speech_policy,
            operator_language=intent.operator_language or self.execution_policy.operator_language,
            audience=intent.audience or self.execution_policy.operator_audience,
            adaptive_model_route=adaptive_model_route,
            route_reason=model_route.reason if allowed else ";".join(blocked_reasons or [approval_gate.reason or "blocked"]),
            blocked_reasons=blocked_reasons,
        )
        trace = RoutingDecisionTrace(
            trace_id=new_id("trace"),
            decision_id=decision.decision_id,
            runtime_state_id=runtime_state.runtime_state_id if runtime_state else None,
            inputs={
                "intent": to_jsonable(intent),
                "runtime_state": to_jsonable(runtime_state) if runtime_state else None,
                "profile": to_jsonable(profile) if profile else None,
            },
            outputs={
                "decision": to_jsonable(decision),
            },
        )

        if persist:
            mission_run = MissionRun(
                mission_run_id=mission_run.mission_run_id,
                intent_id=mission_run.intent_id,
                objective=mission_run.objective,
                profile_name=mission_run.profile_name,
                parent_mission_id=mission_run.parent_mission_id,
                step_index=mission_run.step_index,
                total_steps=mission_run.total_steps,
                status=MissionStatus.QUEUED if allowed else MissionStatus.FAILED,
                execution_class=execution_class,
                routing_decision_id=decision.decision_id,
                metadata={"route_reason": decision.route_reason},
                created_at=mission_run.created_at,
                updated_at=mission_run.updated_at,
            )
            self._persist_mission_run(mission_run)
            self._persist_decision(decision)
            self._persist_trace(trace)
            self.database.record_trace_edge(
                parent_id=intent.intent_id,
                parent_kind=TraceEntityKind.MISSION_INTENT.value,
                child_id=decision.decision_id,
                child_kind=TraceEntityKind.ROUTING_DECISION.value,
                relation=TraceRelationKind.ROUTED_TO.value,
                metadata={"route_reason": decision.route_reason},
            )
            self.database.record_trace_edge(
                parent_id=decision.decision_id,
                parent_kind=TraceEntityKind.ROUTING_DECISION.value,
                child_id=trace.trace_id,
                child_kind=TraceEntityKind.ROUTING_TRACE.value,
                relation=TraceRelationKind.PRODUCED.value,
            )
            if mission_run is not None:
                self.database.record_trace_edge(
                    parent_id=decision.decision_id,
                    parent_kind=TraceEntityKind.ROUTING_DECISION.value,
                    child_id=mission_run.mission_run_id,
                    child_kind=TraceEntityKind.MISSION_RUN.value,
                    relation=TraceRelationKind.PRODUCED.value,
                )

        return decision, trace, mission_run

    def _profile_for(self, target_profile: str | None) -> ProfileCapability | None:
        profile_name = (target_profile or "core").strip().lower()
        return self.profile_capabilities.get(profile_name)

    def _infer_risk_class(self, intent: MissionIntent) -> ActionRiskClass:
        objective = intent.objective.lower()
        if any(keyword in objective for keyword in ("delete", "destroy", "remove", "format")):
            return ActionRiskClass.DESTRUCTIVE
        if any(keyword in objective for keyword in ("publish", "ship", "apply", "write", "edit")):
            return ActionRiskClass.SAFE_WRITE
        return ActionRiskClass.READ_ONLY

    def _classify_cost(self, intent: MissionIntent, risk_class: ActionRiskClass) -> CostClass:
        metadata = intent.metadata
        if metadata.get("exceptional"):
            return CostClass.EXCEPTIONAL
        if metadata.get("multi_worker") or metadata.get("ambiguous_recovery") or metadata.get("error_cost") == "high":
            return CostClass.HARD
        if risk_class is ActionRiskClass.READ_ONLY and not intent.requested_worker:
            return CostClass.CHEAP
        return CostClass.STANDARD

    def _budget_state(self, intent: MissionIntent, mission_cost_class: CostClass) -> BudgetState:
        daily_spend = float(intent.metadata.get("daily_spend_estimate_eur", 0.0))
        monthly_spend = float(intent.metadata.get("monthly_spend_estimate_eur", 0.0))
        if intent.metadata.get("mission_estimate_eur") is not None:
            mission_estimate = float(intent.metadata.get("mission_estimate_eur") or 0.0)
        else:
            usage = estimate_router_usage(
                objective=intent.objective,
                mission_cost_class=mission_cost_class.value,
                channel=intent.channel,
            )
            if mission_cost_class is CostClass.EXCEPTIONAL:
                model = self.execution_policy.exceptional_model
            elif mission_cost_class is CostClass.CHEAP and intent.channel == "discord":
                model = self.execution_policy.discord_simple_model
            elif mission_cost_class is CostClass.CHEAP:
                model = None
            else:
                model = self.execution_policy.default_model
            mission_estimate = estimate_usage_cost_eur(
                model=model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        within_daily = daily_spend + mission_estimate <= self.execution_policy.daily_soft_limit_eur
        within_monthly = monthly_spend + mission_estimate <= self.execution_policy.monthly_limit_eur
        return BudgetState(
            daily_soft_limit_eur=self.execution_policy.daily_soft_limit_eur,
            monthly_limit_eur=self.execution_policy.monthly_limit_eur,
            daily_spend_estimate_eur=daily_spend,
            monthly_spend_estimate_eur=monthly_spend,
            mission_estimate_eur=mission_estimate,
            mission_cost_class=mission_cost_class,
            within_daily_soft=within_daily,
            within_monthly_limit=within_monthly,
            route_reason="within_budget" if within_daily and within_monthly else "budget_guardrail_triggered",
        )

    def _choose_worker(self, intent: MissionIntent, profile: ProfileCapability | None) -> str | None:
        if intent.requested_worker:
            return intent.requested_worker
        if profile is None:
            return None
        objective = intent.objective.lower()
        if any(keyword in objective for keyword in ("browser", "web", "mail", "site", "form")) and "browser" in profile.allowed_workers:
            return "browser"
        if "windows" in profile.allowed_workers:
            return "windows"
        if "browser" in profile.allowed_workers:
            return "browser"
        if "deterministic" in profile.allowed_workers:
            return "deterministic"
        return None

    def _approval_gate(
        self,
        intent: MissionIntent,
        risk_class: ActionRiskClass,
        budget_state: BudgetState,
        chosen_worker: str | None,
    ) -> ApprovalGate:
        needs_approval = False
        reasons: list[str] = []
        founder_approved = bool(intent.metadata.get("founder_approved"))
        approval_id = intent.metadata.get("approval_id")

        if risk_class in {ActionRiskClass.DESTRUCTIVE, ActionRiskClass.EXCEPTIONAL}:
            needs_approval = True
            reasons.append("risk_requires_approval")
        if budget_state.within_daily_soft is False:
            needs_approval = True
            reasons.append("daily_budget_soft_exceeded")
        if chosen_worker and chosen_worker not in {"deterministic", "windows", "browser"}:
            needs_approval = True
            reasons.append("worker_outside_allowlist")
        if intent.metadata.get("exceptional"):
            needs_approval = True
            reasons.append("exceptional_route_requested")

        return ApprovalGate(
            required=needs_approval,
            approved=founder_approved if needs_approval else True,
            approval_id=str(approval_id) if approval_id else None,
            reason=";".join(reasons) if reasons else None,
        )

    def _model_route(
        self,
        intent: MissionIntent,
        mission_cost_class: CostClass,
        budget_state: BudgetState,
        approval_gate: ApprovalGate,
    ) -> ModelRoute:
        model_health = self.model_stack_health_snapshot()
        message_kind = str(intent.metadata.get("message_kind") or "")
        sensitivity = self._sensitivity_class(intent)
        if self.execution_policy.privacy_guard_enabled and sensitivity is SensitivityClass.S3:
            if model_health["tiers"][ModelRouteClass.LOCAL.value]["status"] == "ready":
                return ModelRoute(
                    provider="local",
                    model=self.execution_policy.local_model_name,
                    reasoning_effort=self.execution_policy.local_model_reasoning_effort,
                    route_class=mission_cost_class,
                    route_tier=ModelRouteClass.LOCAL,
                    allowed=True,
                    reason="s3_local_route",
                )
            if self.execution_policy.s3_requires_local_model:
                return ModelRoute(
                    provider="local",
                    model=self.execution_policy.local_model_name if self.execution_policy.local_model_enabled else None,
                    reasoning_effort=self.execution_policy.local_model_reasoning_effort
                    if self.execution_policy.local_model_enabled
                    else None,
                    route_class=mission_cost_class,
                    route_tier=ModelRouteClass.LOCAL,
                    allowed=False,
                    reason="s3_requires_local_model",
                )
            return self._api_model_route(
                mission_cost_class=mission_cost_class,
                budget_state=budget_state,
                approval_gate=approval_gate,
                reason_override="s3_policy_override_api",
            )

        forced_provider = str(intent.metadata.get("requested_provider") or "").strip().lower()
        if forced_provider:
            return self._forced_provider_route(
                intent=intent,
                requested_provider=forced_provider,
                mission_cost_class=mission_cost_class,
                budget_state=budget_state,
                approval_gate=approval_gate,
                model_health=model_health,
            )

        if (
            intent.channel == "discord"
            and mission_cost_class is CostClass.CHEAP
            and message_kind in {OperatorMessageKind.CHAT.value, OperatorMessageKind.STATUS_REQUEST.value}
        ):
            return ModelRoute(
                provider="anthropic",
                model=self.execution_policy.discord_simple_model,
                reasoning_effort=self.execution_policy.discord_simple_reasoning_effort,
                route_class=mission_cost_class,
                route_tier=ModelRouteClass.FAST,
                allowed=True,
                reason="discord_simple_route",
            )

        if bool(intent.metadata.get("prefer_local_model")):
            if model_health["tiers"][ModelRouteClass.LOCAL.value]["status"] == "ready":
                return ModelRoute(
                    provider="local",
                    model=self.execution_policy.local_model_name,
                    reasoning_effort=self.execution_policy.local_model_reasoning_effort,
                    route_class=mission_cost_class,
                    route_tier=ModelRouteClass.LOCAL,
                    allowed=True,
                    reason="local_route",
                )
            return self._api_model_route(
                mission_cost_class=mission_cost_class,
                budget_state=budget_state,
                approval_gate=approval_gate,
                reason_override="local_unavailable_escalated_to_api",
            )

        if mission_cost_class is CostClass.CHEAP:
            return ModelRoute(
                provider="project_os",
                model="deterministic-fastpath",
                reasoning_effort="none",
                route_class=mission_cost_class,
                route_tier=ModelRouteClass.FAST,
                allowed=True,
                reason="deterministic_fast_route",
            )

        if mission_cost_class is CostClass.EXCEPTIONAL:
            if not approval_gate.approved or not approval_gate.required:
                return ModelRoute(
                    provider="openai",
                    model=self.execution_policy.exceptional_model,
                    reasoning_effort="xhigh",
                    route_class=mission_cost_class,
                    route_tier=ModelRouteClass.API,
                    allowed=False,
                    reason="exceptional_requires_founder_approval",
                )
            return ModelRoute(
                provider="openai",
                model=self.execution_policy.exceptional_model,
                reasoning_effort="xhigh",
                route_class=mission_cost_class,
                route_tier=ModelRouteClass.API,
                allowed=True,
                reason="exceptional_approved",
            )

        if mission_cost_class is CostClass.HARD:
            if not budget_state.within_daily_soft and not intent.metadata.get("budget_justified"):
                return ModelRoute(
                    provider="openai",
                    model=self.execution_policy.default_model,
                    reasoning_effort=self.execution_policy.default_reasoning_effort,
                    route_class=CostClass.STANDARD,
                    route_tier=ModelRouteClass.API,
                    allowed=True,
                    reason="downgraded_due_to_daily_budget",
                )
            return ModelRoute(
                provider="openai",
                model=self.execution_policy.default_model,
                reasoning_effort=self.execution_policy.escalation_reasoning_effort,
                route_class=mission_cost_class,
                route_tier=ModelRouteClass.API,
                allowed=True,
                reason="hard_route",
            )

        return ModelRoute(
            provider="openai",
            model=self.execution_policy.default_model,
            reasoning_effort=self.execution_policy.default_reasoning_effort,
            route_class=mission_cost_class,
            route_tier=ModelRouteClass.API,
            allowed=True,
            reason="standard_route",
        )

    def _forced_provider_route(
        self,
        *,
        intent: MissionIntent,
        requested_provider: str,
        mission_cost_class: CostClass,
        budget_state: BudgetState,
        approval_gate: ApprovalGate,
        model_health: dict[str, Any],
    ) -> ModelRoute:
        requested_model = str(intent.metadata.get("requested_model") or "").strip() or None
        requested_model_mode = str(intent.metadata.get("requested_model_mode") or "").strip().lower()
        if requested_provider == "anthropic":
            model_name = requested_model or self.execution_policy.discord_simple_model
            route_reason = {
                "opus": "operator_forced_opus_route",
                "sonnet": "operator_forced_sonnet_route",
            }.get(requested_model_mode, "operator_forced_anthropic_route")
            if not self.secret_resolver.get_optional("ANTHROPIC_API_KEY"):
                return ModelRoute(
                    provider="anthropic",
                    model=model_name,
                    reasoning_effort=self.execution_policy.discord_simple_reasoning_effort,
                    route_class=mission_cost_class,
                    route_tier=ModelRouteClass.API,
                    allowed=False,
                    reason="operator_forced_anthropic_unavailable",
                )
            return ModelRoute(
                provider="anthropic",
                model=model_name,
                reasoning_effort=self.execution_policy.discord_simple_reasoning_effort,
                route_class=mission_cost_class,
                route_tier=ModelRouteClass.API,
                allowed=True,
                reason=route_reason,
            )
        if requested_provider == "openai":
            if not self.secret_resolver.get_optional("OPENAI_API_KEY"):
                return ModelRoute(
                    provider="openai",
                    model=self.execution_policy.default_model,
                    reasoning_effort=self.execution_policy.default_reasoning_effort,
                    route_class=mission_cost_class,
                    route_tier=ModelRouteClass.API,
                    allowed=False,
                    reason="operator_forced_openai_unavailable",
                )
            return self._api_model_route(
                mission_cost_class=mission_cost_class,
                budget_state=budget_state,
                approval_gate=approval_gate,
                reason_override="operator_forced_openai_route",
            )
        if requested_provider == "local":
            if model_health["tiers"][ModelRouteClass.LOCAL.value]["status"] == "ready":
                return ModelRoute(
                    provider="local",
                    model=self.execution_policy.local_model_name,
                    reasoning_effort=self.execution_policy.local_model_reasoning_effort,
                    route_class=mission_cost_class,
                    route_tier=ModelRouteClass.LOCAL,
                    allowed=True,
                    reason="operator_forced_local_route",
                )
            return ModelRoute(
                provider="local",
                model=self.execution_policy.local_model_name if self.execution_policy.local_model_enabled else None,
                reasoning_effort=self.execution_policy.local_model_reasoning_effort
                if self.execution_policy.local_model_enabled
                else None,
                route_class=mission_cost_class,
                route_tier=ModelRouteClass.LOCAL,
                allowed=False,
                reason="operator_forced_local_unavailable",
            )
        return self._api_model_route(
            mission_cost_class=mission_cost_class,
            budget_state=budget_state,
            approval_gate=approval_gate,
        )

    @staticmethod
    def _sensitivity_class(intent: MissionIntent) -> SensitivityClass:
        raw = str(intent.metadata.get("sensitivity_class") or "").strip().lower()
        try:
            return SensitivityClass(raw)
        except Exception:
            return SensitivityClass.S1

    def _communication_mode(self, intent: MissionIntent, chosen_worker: str | None) -> CommunicationMode:
        if intent.metadata.get("channel_class") == "incidents":
            return CommunicationMode.INCIDENT
        if intent.metadata.get("message_kind") == OperatorMessageKind.APPROVAL.value:
            return CommunicationMode.GUARDIAN
        if intent.metadata.get("message_kind") in {OperatorMessageKind.CHAT.value, OperatorMessageKind.STATUS_REQUEST.value}:
            return CommunicationMode.DISCUSSION
        if intent.metadata.get("message_kind") in {OperatorMessageKind.IDEA.value, OperatorMessageKind.DECISION.value, OperatorMessageKind.NOTE.value}:
            return CommunicationMode.ARCHITECT
        if chosen_worker or intent.metadata.get("message_kind") == OperatorMessageKind.TASKING.value:
            return CommunicationMode.BUILDER
        return intent.communication_mode or CommunicationMode.DISCUSSION

    def _speech_policy(self, communication_mode: CommunicationMode) -> RunSpeechPolicy:
        if communication_mode in {CommunicationMode.BUILDER, CommunicationMode.REVIEWER}:
            return self.execution_policy.default_run_speech_policy
        if communication_mode is CommunicationMode.INCIDENT:
            return RunSpeechPolicy.PHASE_MARKERS_ONLY
        return RunSpeechPolicy.DIALOGUE_RICH

    def _adaptive_model_route(
        self,
        intent: MissionIntent,
        communication_mode: CommunicationMode,
        model_route: ModelRoute,
    ) -> AdaptiveModelRoute:
        channel_class_raw = str(intent.metadata.get("channel_class") or "unknown")
        try:
            channel_class = DiscordChannelClass(channel_class_raw)
        except Exception:
            channel_class = DiscordChannelClass.UNKNOWN
        message_kind_raw = intent.metadata.get("message_kind")
        try:
            message_kind = OperatorMessageKind(str(message_kind_raw)) if message_kind_raw else None
        except Exception:
            message_kind = None
        return AdaptiveModelRoute(
            route_id=new_id("adaptive_route"),
            channel_class=channel_class,
            communication_mode=communication_mode,
            message_kind=message_kind,
            provider=model_route.provider,
            model=model_route.model,
            reasoning_effort=model_route.reasoning_effort,
            deterministic_first=self.execution_policy.deterministic_first,
            reason=model_route.reason,
        )

    def _api_model_route(
        self,
        *,
        mission_cost_class: CostClass,
        budget_state: BudgetState,
        approval_gate: ApprovalGate,
        reason_override: str | None = None,
    ) -> ModelRoute:
        if mission_cost_class is CostClass.EXCEPTIONAL:
            if not approval_gate.approved or not approval_gate.required:
                return ModelRoute(
                    provider="openai",
                    model=self.execution_policy.exceptional_model,
                    reasoning_effort="xhigh",
                    route_class=mission_cost_class,
                    route_tier=ModelRouteClass.API,
                    allowed=False,
                    reason="exceptional_requires_founder_approval",
                )
            return ModelRoute(
                provider="openai",
                model=self.execution_policy.exceptional_model,
                reasoning_effort="xhigh",
                route_class=mission_cost_class,
                route_tier=ModelRouteClass.API,
                allowed=True,
                reason=reason_override or "exceptional_approved",
            )
        if mission_cost_class is CostClass.HARD:
            if not budget_state.within_daily_soft:
                return ModelRoute(
                    provider="openai",
                    model=self.execution_policy.default_model,
                    reasoning_effort=self.execution_policy.default_reasoning_effort,
                    route_class=CostClass.STANDARD,
                    route_tier=ModelRouteClass.API,
                    allowed=True,
                    reason=reason_override or "downgraded_due_to_daily_budget",
                )
            return ModelRoute(
                provider="openai",
                model=self.execution_policy.default_model,
                reasoning_effort=self.execution_policy.escalation_reasoning_effort,
                route_class=mission_cost_class,
                route_tier=ModelRouteClass.API,
                allowed=True,
                reason=reason_override or "hard_route",
            )
        return ModelRoute(
            provider="openai",
            model=self.execution_policy.default_model,
            reasoning_effort=self.execution_policy.default_reasoning_effort,
            route_class=mission_cost_class,
            route_tier=ModelRouteClass.API,
            allowed=True,
            reason=reason_override or "standard_route",
        )

    def _preferred_api_provider(self, openai_available: bool, anthropic_available: bool) -> str | None:
        if openai_available:
            return "openai"
        if anthropic_available:
            return "anthropic"
        return None

    def _execution_class(
        self,
        risk_class: ActionRiskClass,
        model_route: ModelRoute,
        approval_gate: ApprovalGate,
        allowed: bool,
    ) -> MissionExecutionClass:
        if not allowed:
            return MissionExecutionClass.BLOCKED
        if approval_gate.required:
            return MissionExecutionClass.SUPERVISED
        if model_route.route_class is CostClass.CHEAP:
            return MissionExecutionClass.DETERMINISTIC
        if risk_class is ActionRiskClass.READ_ONLY:
            return MissionExecutionClass.ASSISTED
        return MissionExecutionClass.SUPERVISED

    def _extract_paths(self, intent: MissionIntent) -> list[str]:
        paths = intent.metadata.get("paths")
        if isinstance(paths, list):
            return [str(item) for item in paths]
        return []

    def _persist_intent(self, intent: MissionIntent) -> None:
        self.database.upsert(
            "mission_intents",
            {
                "intent_id": intent.intent_id,
                "source": intent.source,
                "actor_id": intent.actor_id,
                "channel": intent.channel,
                "objective": intent.objective,
                "target_profile": intent.target_profile,
                "requested_worker": intent.requested_worker,
                "requested_risk_class": intent.requested_risk_class.value if intent.requested_risk_class else None,
                "metadata_json": dump_json(intent.metadata),
                "created_at": intent.created_at,
            },
            conflict_columns="intent_id",
            immutable_columns=["created_at"],
        )

    def _persist_mission_run(self, mission_run: MissionRun) -> None:
        self.database.upsert(
            "mission_runs",
            {
                "mission_run_id": mission_run.mission_run_id,
                "intent_id": mission_run.intent_id,
                "objective": mission_run.objective,
                "profile_name": mission_run.profile_name,
                "parent_mission_id": mission_run.parent_mission_id,
                "step_index": mission_run.step_index,
                "total_steps": mission_run.total_steps,
                "status": mission_run.status.value,
                "execution_class": mission_run.execution_class.value if mission_run.execution_class else None,
                "routing_decision_id": mission_run.routing_decision_id,
                "metadata_json": dump_json(mission_run.metadata),
                "created_at": mission_run.created_at,
                "updated_at": mission_run.updated_at,
            },
            conflict_columns="mission_run_id",
            immutable_columns=["created_at"],
        )

    def _persist_decision(self, decision: RoutingDecision) -> None:
        self.database.upsert(
            "routing_decisions",
            {
                "decision_id": decision.decision_id,
                "intent_id": decision.intent_id,
                "mission_run_id": decision.mission_run_id,
                "execution_class": decision.execution_class.value,
                "risk_class": decision.risk_class.value,
                "allowed": 1 if decision.allowed else 0,
                "chosen_worker": decision.chosen_worker,
                "model_route_json": dump_json(to_jsonable(decision.model_route)),
                "approval_gate_json": dump_json(to_jsonable(decision.approval_gate)),
                "budget_state_json": dump_json(to_jsonable(decision.budget_state)),
                "route_reason": decision.route_reason,
                "blocked_reasons_json": dump_json(decision.blocked_reasons),
                "created_at": decision.created_at,
            },
            conflict_columns="decision_id",
            immutable_columns=["created_at"],
        )

    def _persist_trace(self, trace: RoutingDecisionTrace) -> None:
        self.database.upsert(
            "routing_decision_traces",
            {
                "trace_id": trace.trace_id,
                "decision_id": trace.decision_id,
                "runtime_state_id": trace.runtime_state_id,
                "inputs_json": dump_json(trace.inputs),
                "outputs_json": dump_json(trace.outputs),
                "created_at": trace.created_at,
            },
            conflict_columns="trace_id",
            immutable_columns=["created_at"],
        )
