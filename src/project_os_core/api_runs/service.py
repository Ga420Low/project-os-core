from __future__ import annotations

import json
import re
import sqlite3
import shutil
import subprocess
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - dependency is declared in pyproject but may be absent in local dev until installed
    Anthropic = None
from openai import OpenAI

from ..costing import estimate_usage_cost_eur
from ..database import CanonicalDatabase, dump_json
from ..learning.service import LearningService
from ..models import (
    ApiRunArtifact,
    ApiRunMode,
    ApiRunRequest,
    ApiRunResult,
    ApiRunReview,
    ApiRunReviewVerdict,
    ApiRunStatus,
    BlockageReport,
    ClarificationReport,
    CommunicationMode,
    CompletionReport,
    ContextPack,
    ContextSource,
    DatasetCandidate,
    DecisionStatus,
    LearningSignalKind,
    MegaPromptTemplate,
    OperatorChannelHint,
    OperatorDelivery,
    OperatorDeliveryGuarantee,
    OperatorDeliveryStatus,
    OperatorAudience,
    OutputQuarantineReason,
    RunContract,
    RunContractStatus,
    RunLifecycleEvent,
    RunLifecycleEventKind,
    RunSpeechPolicy,
    TraceEntityKind,
    TraceRelationKind,
    new_id,
    to_jsonable,
)
from ..observability import StructuredLogger
from ..operator_visibility_policy import StandardReplyPolicy
from ..paths import PathPolicy, ProjectPaths
from ..runtime.journal import LocalJournal
from ..secrets import SecretResolver
from ..router.service import MissionRouter


DEFAULT_CONTEXT_SOURCE_LIMIT = 12_000
DEFAULT_CONTEXT_FILE_COUNT = 10
REVIEWER_MODEL = "claude-haiku-4-5-20251001"
TRANSLATOR_MODEL = "claude-haiku-4-5-20251001"

_DELIVERY_GUARANTEE_RANK: dict[OperatorDeliveryGuarantee, int] = {
    OperatorDeliveryGuarantee.BEST_EFFORT: 0,
    OperatorDeliveryGuarantee.IMPORTANT: 1,
    OperatorDeliveryGuarantee.MUST_NOTIFY: 2,
    OperatorDeliveryGuarantee.MUST_PERSIST: 3,
}


class ApiRunService:
    """Owns large-context audit, design, patch-plan, and patch-generation runs."""

    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        secret_resolver: SecretResolver,
        logger: StructuredLogger,
        router: MissionRouter,
        execution_policy,
        dashboard_config,
        learning: LearningService,
    ) -> None:
        self.database = database
        self.journal = journal
        self.paths = paths
        self.path_policy = path_policy
        self.secret_resolver = secret_resolver
        self.logger = logger
        self.router = router
        self.execution_policy = execution_policy
        self.dashboard_config = dashboard_config
        self.learning = learning
        self.repo_root = paths.repo_root
        self.templates_path = self.repo_root / "config" / "api_run_templates.json"
        self.templates = self._load_templates()

    def build_context_pack(
        self,
        *,
        mode: ApiRunMode,
        objective: str,
        branch_name: str | None,
        skill_tags: list[str],
        target_profile: str | None = None,
        source_paths: list[str] | None = None,
        constraints: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContextPack:
        resolved_branch = self._normalize_branch_name(branch_name)
        normalized_skills = self._normalize_skill_tags(skill_tags)
        selected_sources = self._resolve_context_source_paths(source_paths)
        context_pack = ContextPack(
            context_pack_id=new_id("context_pack"),
            mode=mode,
            objective=objective.strip(),
            branch_name=resolved_branch,
            target_profile=target_profile,
            source_refs=[self._read_context_source(path) for path in selected_sources],
            repo_state=self._repo_state(target_branch=resolved_branch),
            runtime_facts=self._runtime_facts(target_branch=resolved_branch, target_profile=target_profile),
            constraints=list(constraints or self._default_constraints()),
            acceptance_criteria=list(acceptance_criteria or self._default_acceptance_criteria(mode)),
            skill_tags=normalized_skills,
            metadata=dict(metadata or {}),
        )
        previous_chain_output = context_pack.metadata.get("mission_chain_previous_output")
        if previous_chain_output is not None:
            context_pack.runtime_facts["previous_chain_output"] = previous_chain_output
        try:
            learning_context = self.learning.gather_learning_context(
                mode=mode.value,
                branch_name=resolved_branch,
                objective=context_pack.objective,
            )
            context_pack.runtime_facts["learning_context"] = learning_context
            self.logger.log(
                "INFO",
                "learning_context_injected",
                context_pack_id=context_pack.context_pack_id,
                mode=mode.value,
                branch_name=resolved_branch,
                decisions=len(learning_context.get("decisions", [])),
                deferred_decisions=len(learning_context.get("deferred_decisions", [])),
                high_severity_signals=len(learning_context.get("high_severity_signals", [])),
                detected_loops=len(learning_context.get("detected_loops", [])),
                refresh_recommendations=len(learning_context.get("refresh_recommendations", [])),
            )
        except Exception as exc:
            self.logger.log(
                "WARNING",
                "learning_injection_failed",
                mode=mode.value,
                branch_name=resolved_branch,
                error=str(exc),
            )
            context_pack.runtime_facts["learning_context"] = {
                "error": str(exc),
                "decisions": [],
                "deferred_decisions": [],
                "high_severity_signals": [],
                "detected_loops": [],
                "refresh_recommendations": [],
                "summary": "Learning context unavailable for this run.",
            }
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "context_packs",
            context_pack.context_pack_id,
            to_jsonable(context_pack),
        )
        context_pack.artifact_path = str(artifact_path)
        self._persist_context_pack(context_pack)
        self.journal.append(
            "api_run_context_pack_created",
            "api_runs",
            {
                "context_pack_id": context_pack.context_pack_id,
                "mode": context_pack.mode.value,
                "branch_name": context_pack.branch_name,
                "source_count": len(context_pack.source_refs),
                "skill_tags": context_pack.skill_tags,
            },
        )
        return context_pack

    def render_prompt(self, *, context_pack_id: str) -> MegaPromptTemplate:
        context_pack = self.get_context_pack(context_pack_id)
        template_config = self._template_for_mode(context_pack.mode)
        rendered_prompt = self._render_prompt_text(context_pack, template_config)
        prompt_template = MegaPromptTemplate(
            prompt_template_id=new_id("mega_prompt"),
            context_pack_id=context_pack.context_pack_id,
            mode=context_pack.mode,
            agent_identity=str(template_config["agent_identity"]),
            skill_tags=context_pack.skill_tags,
            output_contract=list(template_config["output_contract"]),
            rendered_prompt=rendered_prompt,
            model=str(template_config["model"]),
            reasoning_effort=str(template_config["reasoning_effort"]),
            metadata={"template_version": template_config.get("version", "v1")},
        )
        artifact_path = self._write_runtime_text(
            self.paths.api_runs_root / "prompts",
            prompt_template.prompt_template_id,
            rendered_prompt,
            suffix=".md",
        )
        prompt_template.artifact_path = str(artifact_path)
        self._persist_prompt_template(prompt_template)
        self.journal.append(
            "api_run_prompt_rendered",
            "api_runs",
            {
                "prompt_template_id": prompt_template.prompt_template_id,
                "context_pack_id": context_pack.context_pack_id,
                "mode": prompt_template.mode.value,
                "model": prompt_template.model,
                "reasoning_effort": prompt_template.reasoning_effort,
            },
        )
        return prompt_template

    def create_run_contract(
        self,
        *,
        context_pack_id: str,
        prompt_template_id: str,
        target_profile: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunContract:
        context_pack = self.get_context_pack(context_pack_id)
        prompt_template = self.get_prompt_template(prompt_template_id)
        estimated_cost = self._estimate_cost_hint(prompt_template.model, prompt_template.reasoning_effort, context_pack.mode)
        contract = RunContract(
            contract_id=new_id("run_contract"),
            context_pack_id=context_pack.context_pack_id,
            prompt_template_id=prompt_template.prompt_template_id,
            mode=context_pack.mode,
            objective=context_pack.objective,
            branch_name=context_pack.branch_name,
            target_profile=target_profile or context_pack.target_profile,
            model=prompt_template.model,
            reasoning_effort=prompt_template.reasoning_effort,
            communication_mode=CommunicationMode.BUILDER,
            speech_policy=self.execution_policy.default_run_speech_policy,
            operator_language=self.execution_policy.operator_language,
            audience=self.execution_policy.operator_audience,
            expected_outputs=list(prompt_template.output_contract),
            summary=self._build_contract_summary(context_pack, prompt_template, estimated_cost),
            non_goals=self._contract_non_goals(),
            success_criteria=list(context_pack.acceptance_criteria),
            estimated_cost_eur=estimated_cost,
            founder_decision=None,
            founder_decision_at=None,
            status=RunContractStatus.PREPARED,
            metadata=dict(metadata or {}),
        )
        self._persist_run_contract(contract)
        self.journal.append(
            "api_run_contract_created",
            "api_runs",
            {
                "contract_id": contract.contract_id,
                "mode": contract.mode.value,
                "branch_name": contract.branch_name,
                "estimated_cost_eur": contract.estimated_cost_eur,
            },
        )
        return contract

    def approve_run_contract(
        self,
        *,
        contract_id: str,
        founder_decision: str,
        notes: str | None = None,
    ) -> RunContract:
        contract = self.get_run_contract(contract_id)
        normalized = founder_decision.strip().lower()
        if normalized not in {"go", "go_avec_correction", "stop"}:
            raise ValueError("founder_decision must be go, go_avec_correction, or stop")
        expected_updated_at = contract.updated_at
        decision_timestamp = datetime.now(timezone.utc).isoformat()
        contract.status = RunContractStatus.APPROVED if normalized != "stop" else RunContractStatus.REJECTED
        contract.founder_decision = normalized
        contract.founder_decision_at = decision_timestamp if normalized != "stop" else None
        contract.updated_at = decision_timestamp
        if contract.founder_decision_at:
            contract.metadata["founder_decision_at"] = contract.founder_decision_at
        else:
            contract.metadata.pop("founder_decision_at", None)
        contract.metadata["requires_reapproval"] = False
        contract.metadata["clarification_pending"] = False
        contract.metadata.pop("pending_clarification_report_id", None)
        contract.metadata["approval_round"] = int(contract.metadata.get("approval_round") or 0) + 1
        history = list(contract.metadata.get("approval_history") or [])
        history.append(
            {
                "decision": normalized,
                "notes": notes or "",
                "timestamp": decision_timestamp,
                "round": contract.metadata["approval_round"],
            }
        )
        contract.metadata["approval_history"] = history
        if notes:
            contract.metadata["founder_notes"] = notes
        self._persist_run_contract(contract, expected_updated_at=expected_updated_at)
        self.journal.append(
            "api_run_contract_updated",
            "api_runs",
            {
                "contract_id": contract.contract_id,
                "status": contract.status.value,
                "founder_decision": normalized,
            },
        )
        return contract

    def amend_run_contract(
        self,
        *,
        contract_id: str,
        objective: str | None = None,
        branch_name: str | None = None,
        target_profile: str | None = None,
        constraints: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunContract:
        contract = self.get_run_contract(contract_id)
        context_pack = self.get_context_pack(contract.context_pack_id)
        updated_objective = (objective or contract.objective).strip()
        updated_branch_name = self._normalize_branch_name(branch_name or contract.branch_name)
        updated_target_profile = target_profile if target_profile is not None else contract.target_profile
        updated_constraints = list(constraints) if constraints else list(context_pack.constraints)
        updated_acceptance = list(acceptance_criteria) if acceptance_criteria else list(context_pack.acceptance_criteria)
        updated_metadata = {**context_pack.metadata, **(metadata or {})}
        source_paths = [item.path for item in context_pack.source_refs]
        rebuilt_context = self.build_context_pack(
            mode=contract.mode,
            objective=updated_objective,
            branch_name=updated_branch_name,
            skill_tags=context_pack.skill_tags,
            target_profile=updated_target_profile,
            source_paths=source_paths,
            constraints=updated_constraints,
            acceptance_criteria=updated_acceptance,
            metadata=updated_metadata,
        )
        rebuilt_prompt = self.render_prompt(context_pack_id=rebuilt_context.context_pack_id)
        estimated_cost = self._estimate_cost_hint(rebuilt_prompt.model, rebuilt_prompt.reasoning_effort, contract.mode)
        expected_updated_at = contract.updated_at
        amendment_timestamp = datetime.now(timezone.utc).isoformat()
        contract.context_pack_id = rebuilt_context.context_pack_id
        contract.prompt_template_id = rebuilt_prompt.prompt_template_id
        contract.objective = rebuilt_context.objective
        contract.branch_name = rebuilt_context.branch_name
        contract.target_profile = rebuilt_context.target_profile
        contract.model = rebuilt_prompt.model
        contract.reasoning_effort = rebuilt_prompt.reasoning_effort
        contract.expected_outputs = list(rebuilt_prompt.output_contract)
        contract.estimated_cost_eur = estimated_cost
        contract.summary = self._build_contract_summary(rebuilt_context, rebuilt_prompt, estimated_cost)
        contract.success_criteria = list(rebuilt_context.acceptance_criteria)
        contract.status = RunContractStatus.PREPARED
        contract.founder_decision = None
        contract.founder_decision_at = None
        contract.updated_at = amendment_timestamp
        contract.metadata.update(metadata or {})
        contract.metadata["amendment_count"] = int(contract.metadata.get("amendment_count") or 0) + 1
        contract.metadata["amended_at"] = amendment_timestamp
        contract.metadata["requires_reapproval"] = True
        contract.metadata["clarification_pending"] = False
        contract.metadata.pop("pending_clarification_report_id", None)
        contract.metadata.pop("founder_decision_at", None)
        self._persist_run_contract(contract, expected_updated_at=expected_updated_at)
        self.journal.append(
            "api_run_contract_amended",
            "api_runs",
            {
                "contract_id": contract.contract_id,
                "mode": contract.mode.value,
                "branch_name": contract.branch_name,
                "amendment_count": contract.metadata["amendment_count"],
            },
        )
        return contract

    def execute_run(
        self,
        *,
        mode: ApiRunMode | None = None,
        objective: str | None = None,
        branch_name: str | None = None,
        skill_tags: list[str] | None = None,
        target_profile: str | None = None,
        source_paths: list[str] | None = None,
        constraints: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        expected_outputs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        response_runner: Callable[[ApiRunRequest, MegaPromptTemplate, ContextPack], Any] | None = None,
        contract_id: str | None = None,
        mission_chain_id: str | None = None,
        mission_step_index: int | None = None,
    ) -> dict[str, Any]:
        contract = self.get_run_contract(contract_id) if contract_id else None
        if contract is not None:
            if contract.status is not RunContractStatus.APPROVED:
                raise RuntimeError("Le contrat de run doit etre approuve avant l'execution.")
            context_pack = self.get_context_pack(contract.context_pack_id)
            prompt_template = self.get_prompt_template(contract.prompt_template_id)
            resolved_mode = contract.mode
            resolved_target_profile = contract.target_profile
            resolved_expected_outputs = list(expected_outputs or contract.expected_outputs)
            request_metadata = {**contract.metadata, **(metadata or {}), "founder_decision": contract.founder_decision}
        else:
            if self.execution_policy.run_contract_required:
                raise RuntimeError("Un contrat de run approuve est obligatoire avant l'execution.")
            if mode is None or objective is None or not skill_tags:
                raise ValueError("mode, objective, and skill_tags are required without contract_id")
            context_pack = self.build_context_pack(
                mode=mode,
                objective=objective,
                branch_name=branch_name,
                skill_tags=skill_tags,
                target_profile=target_profile,
                source_paths=source_paths,
                constraints=constraints,
                acceptance_criteria=acceptance_criteria,
                metadata=metadata,
            )
            prompt_template = self.render_prompt(context_pack_id=context_pack.context_pack_id)
            resolved_mode = mode
            resolved_target_profile = context_pack.target_profile
            resolved_expected_outputs = list(expected_outputs or prompt_template.output_contract)
            request_metadata = dict(metadata or {})
        repo_preflight = self._run_repo_preflight(target_branch=context_pack.branch_name, contract=contract)
        request_metadata["repo_preflight"] = repo_preflight
        if not repo_preflight["ok"]:
            return self._create_preflight_clarification_exit(
                contract=contract,
                context_pack=context_pack,
                prompt_template=prompt_template,
                resolved_mode=resolved_mode,
                resolved_target_profile=resolved_target_profile,
                resolved_expected_outputs=resolved_expected_outputs,
                request_metadata=request_metadata,
                preflight=repo_preflight,
            )
        dashboard_status = self._ensure_operator_dashboard(contract=contract)
        request_metadata["operator_dashboard_reason"] = str(dashboard_status.get("reason") or "unknown")
        request_metadata["operator_dashboard_ready"] = bool(dashboard_status.get("ready"))
        request = ApiRunRequest(
            run_request_id=new_id("run_request"),
            context_pack_id=context_pack.context_pack_id,
            prompt_template_id=prompt_template.prompt_template_id,
            mode=resolved_mode,
            objective=context_pack.objective,
            branch_name=context_pack.branch_name,
            target_profile=resolved_target_profile,
            mission_chain_id=mission_chain_id or str(request_metadata.get("mission_chain_id") or "") or None,
            mission_step_index=(
                mission_step_index
                if mission_step_index is not None
                else (
                    int(request_metadata["mission_step_index"])
                    if request_metadata.get("mission_step_index") is not None
                    else None
                )
            ),
            skill_tags=context_pack.skill_tags,
            expected_outputs=resolved_expected_outputs,
            communication_mode=CommunicationMode.BUILDER,
            speech_policy=self.execution_policy.default_run_speech_policy,
            operator_language=self.execution_policy.operator_language,
            audience=self.execution_policy.operator_audience,
            run_contract_required=bool(contract is not None or self.execution_policy.run_contract_required),
            contract_id=contract.contract_id if contract else None,
            metadata=request_metadata,
        )
        run_id = new_id("api_run")
        placeholder_result = ApiRunResult(
            run_id=run_id,
            run_request_id=request.run_request_id,
            model=prompt_template.model,
            mode=request.mode,
            status=ApiRunStatus.RUNNING,
            structured_output={},
            raw_output_path=None,
            prompt_artifact_path=prompt_template.artifact_path,
            result_artifact_path=None,
            estimated_cost_eur=0.0,
            usage={},
            metadata={"live_state": "running"},
        )
        contract_expected_updated_at = contract.updated_at if contract is not None else None
        run_started_at = datetime.now(timezone.utc).isoformat()
        request.status = ApiRunStatus.RUNNING
        request.updated_at = run_started_at
        placeholder_result.updated_at = run_started_at
        with self.database.transaction() as connection:
            self._persist_run_request(request, connection=connection)
            self._persist_run_result(placeholder_result, connection=connection)
            if contract is not None:
                contract.status = RunContractStatus.EXECUTED
                contract.updated_at = run_started_at
                contract.metadata["last_run_request_id"] = request.run_request_id
                self._persist_run_contract(
                    contract,
                    connection=connection,
                    expected_updated_at=contract_expected_updated_at,
                )
            self._emit_run_lifecycle_event(
                run_id=run_id,
                run_request_id=request.run_request_id,
                contract_id=request.contract_id,
                kind=RunLifecycleEventKind.RUN_STARTED,
                mode=request.mode,
                branch_name=request.branch_name,
                status=ApiRunStatus.RUNNING,
                phase="demarrage",
                title=f"Run {request.mode.value} demarre",
                summary=f"Le lot {request.mode.value} travaille maintenant sur {request.branch_name}.",
                metadata={
                    "objective": request.objective,
                    "operator_guard_reason": request.metadata.get("operator_dashboard_reason"),
                },
                connection=connection,
                refresh_snapshot=False,
            )
            self._record_run_event(
                run_id=run_id,
                phase="demarrage",
                severity="info",
                machine_summary="Le run de code a demarre en mode silencieux.",
                human_summary=None,
                payload={
                    "mode": resolved_mode.value,
                    "branch_name": request.branch_name,
                    "speech_policy": request.speech_policy.value,
                    "contract_id": request.contract_id,
                },
                connection=connection,
                refresh_snapshot=False,
            )
        self.logger.log(
            "INFO",
            "api_run_started",
            run_request_id=request.run_request_id,
            mode=resolved_mode.value,
            branch_name=request.branch_name,
        )
        self.journal.append(
            "api_run_started",
            "api_runs",
            {
                "run_id": run_id,
                "run_request_id": request.run_request_id,
                "context_pack_id": context_pack.context_pack_id,
                "prompt_template_id": prompt_template.prompt_template_id,
                "mode": resolved_mode.value,
                "branch_name": request.branch_name,
            },
        )
        self._refresh_live_snapshot()
        review: ApiRunReview | None = None
        completion_report: CompletionReport | None = None
        can_proceed, blocking_reason = self._guardian_pre_spend_check(
            request=request,
            prompt_template=prompt_template,
        )
        if not can_proceed and blocking_reason is not None:
            self.logger.log(
                "WARNING",
                "guardian_blocked_run",
                run_request_id=request.run_request_id,
                run_id=run_id,
                reason=blocking_reason,
            )
            self._record_run_event(
                run_id=run_id,
                phase="guardian_blocked",
                severity="warning",
                machine_summary=f"Guardian a bloque le run: {blocking_reason}",
                human_summary="Le systeme a detecte un probleme et demande confirmation.",
                payload={"blocking_reason": blocking_reason},
            )
            cause = "Budget journalier depasse" if "budget_exceeded" in blocking_reason else "Boucle detectee sur cette branche"
            question = (
                "Le budget du jour est presque atteint. Tu veux quand meme lancer ce run ?"
                if "budget_exceeded" in blocking_reason
                else "Ce meme type de run a deja tourne plusieurs fois sur cette branche. Tu veux forcer ?"
            )
            recommendation = (
                "Attendre demain ou augmenter la limite."
                if "budget_exceeded" in blocking_reason
                else "Verifier les runs precedents et changer de strategie si necessaire."
            )
            clarification = ClarificationReport(
                report_id=new_id("clarification_report"),
                run_id=run_id,
                cause=cause,
                impact="Le run ne peut pas demarrer sans confirmation.",
                question_for_founder=question,
                recommended_contract_change=recommendation,
                requires_reapproval=True,
                metadata={"guardian_blocking_reason": blocking_reason},
            )
            result = ApiRunResult(
                run_id=run_id,
                run_request_id=request.run_request_id,
                model=prompt_template.model,
                mode=request.mode,
                status=ApiRunStatus.CLARIFICATION_REQUIRED,
                structured_output={},
                raw_output_path=None,
                prompt_artifact_path=prompt_template.artifact_path,
                result_artifact_path=None,
                estimated_cost_eur=0.0,
                usage={},
                metadata={"guardian_blocked": True, "blocking_reason": blocking_reason},
            )
            request_blocked_at = datetime.now(timezone.utc).isoformat()
            request.status = ApiRunStatus.CLARIFICATION_REQUIRED
            request.updated_at = request_blocked_at
            result.updated_at = request_blocked_at
            with self.database.transaction() as connection:
                self._persist_clarification_report(clarification, connection=connection)
                result.metadata["clarification_report_path"] = str(clarification.metadata.get("artifact_path") or "")
                self._persist_run_result(result, connection=connection)
                self._update_request_status(
                    request.run_request_id,
                    ApiRunStatus.CLARIFICATION_REQUIRED,
                    updated_at=request_blocked_at,
                    connection=connection,
                )
                if contract is not None:
                    self._mark_contract_clarification_pending(
                        contract=contract,
                        clarification=clarification,
                        connection=connection,
                        expected_updated_at=contract.updated_at,
                    )
                self._emit_run_lifecycle_event(
                    run_id=run_id,
                    run_request_id=request.run_request_id,
                    contract_id=request.contract_id,
                    kind=RunLifecycleEventKind.CLARIFICATION_REQUIRED,
                    mode=request.mode,
                    branch_name=request.branch_name,
                    status=ApiRunStatus.CLARIFICATION_REQUIRED,
                    phase="guardian_blocked",
                    title="Guardian a bloque le run",
                    summary=cause,
                    blocking_question=question,
                    recommended_action=recommendation,
                    metadata={"guardian_blocking_reason": blocking_reason},
                    connection=connection,
                    refresh_snapshot=False,
                )
            self._refresh_live_snapshot()
            snapshot = self.monitor_snapshot()
            return {
                "contract": contract,
                "context_pack": context_pack,
                "prompt_template": prompt_template,
                "request": request,
                "result": result,
                "review": None,
                "completion_report": None,
                "monitor_snapshot": snapshot,
            }
        try:
            self._record_run_event(
                run_id=run_id,
                phase="generation",
                severity="info",
                machine_summary="Generation du resultat en cours via l'API grande fenetre.",
                human_summary=None,
                payload={"model": prompt_template.model, "reasoning_effort": prompt_template.reasoning_effort},
            )
            response_payload = response_runner(request, prompt_template, context_pack) if response_runner else self._call_openai(request, prompt_template)
            self._record_run_event(
                run_id=run_id,
                phase="analyse",
                severity="info",
                machine_summary="Le resultat brut a ete recu, normalisation et verification en cours.",
                human_summary=None,
                payload={"run_request_id": request.run_request_id},
            )
            structured_output, raw_payload, usage = self._normalize_response_payload(
                response_payload,
                run_id=run_id,
                run_request_id=request.run_request_id,
                model=prompt_template.model,
            )
            raw_output_path = self._write_runtime_json(self.paths.api_runs_root / "raw_results", run_id, raw_payload)
            structured_output_path = self._write_runtime_json(self.paths.api_runs_root / "structured_results", run_id, structured_output)
            estimated_cost = self._estimate_cost_eur(model=str(raw_payload.get("model") or prompt_template.model), usage=usage)
            if self._structured_output_requires_clarification(structured_output):
                clarification = self._build_clarification_report(
                    run_id=run_id,
                    request=request,
                    structured_output=structured_output,
                )
                result = ApiRunResult(
                    run_id=run_id,
                    run_request_id=request.run_request_id,
                    model=str(raw_payload.get("model") or prompt_template.model),
                    mode=request.mode,
                    status=ApiRunStatus.CLARIFICATION_REQUIRED,
                    structured_output=structured_output,
                    raw_output_path=str(raw_output_path),
                    prompt_artifact_path=prompt_template.artifact_path,
                    result_artifact_path=str(structured_output_path),
                    estimated_cost_eur=estimated_cost,
                    usage=usage,
                    metadata={},
                )
                request_finalized_at = datetime.now(timezone.utc).isoformat()
                contract_expected_updated_at = contract.updated_at if contract is not None else None
                with self.database.transaction() as connection:
                    self._persist_clarification_report(clarification, connection=connection)
                    result.metadata["clarification_report_path"] = str(clarification.metadata["artifact_path"])
                    result.updated_at = request_finalized_at
                    self._persist_run_result(result, connection=connection)
                    self._update_request_status(
                        request.run_request_id,
                        ApiRunStatus.CLARIFICATION_REQUIRED,
                        updated_at=request_finalized_at,
                        connection=connection,
                    )
                    if contract is not None:
                        self._mark_contract_clarification_pending(
                            contract=contract,
                            clarification=clarification,
                            connection=connection,
                            expected_updated_at=contract_expected_updated_at,
                        )
                    self._record_run_event(
                        run_id=run_id,
                        phase="clarification",
                        severity="warning",
                        machine_summary=f"Clarification requise: {clarification.cause}",
                        human_summary=f"Question fondatrice requise: {clarification.question_for_founder}",
                        payload={
                            "clarification_report_id": clarification.report_id,
                            "requires_reapproval": clarification.requires_reapproval,
                        },
                        connection=connection,
                        refresh_snapshot=False,
                    )
                    self._emit_run_lifecycle_event(
                        run_id=run_id,
                        run_request_id=request.run_request_id,
                        contract_id=request.contract_id,
                        kind=RunLifecycleEventKind.CLARIFICATION_REQUIRED,
                        mode=request.mode,
                        branch_name=request.branch_name,
                        status=ApiRunStatus.CLARIFICATION_REQUIRED,
                        phase="clarification",
                        title="Clarification requise",
                        summary=clarification.cause,
                        blocking_question=clarification.question_for_founder,
                        recommended_action=clarification.recommended_contract_change,
                        requires_reapproval=clarification.requires_reapproval,
                        metadata={
                            "objective": request.objective,
                            "clarification_report_id": clarification.report_id,
                        },
                        connection=connection,
                        refresh_snapshot=False,
                    )
                self.logger.log(
                    "WARNING",
                    "api_run_clarification_required",
                    run_id=result.run_id,
                    run_request_id=request.run_request_id,
                    mode=result.mode.value,
                    clarification_report_id=clarification.report_id,
                )
                self.journal.append(
                    "api_run_clarification_required",
                    "api_runs",
                    {
                        "run_id": result.run_id,
                        "run_request_id": request.run_request_id,
                        "mode": result.mode.value,
                        "branch_name": request.branch_name,
                        "clarification_report_id": clarification.report_id,
                    },
                )
                self._refresh_live_snapshot()
            else:
                review_package_path = self._write_runtime_json(
                    self.paths.api_runs_root / "review_packages",
                    run_id,
                    {
                        "run_id": run_id,
                        "objective": request.objective,
                        "mode": request.mode.value,
                        "branch_name": request.branch_name,
                        "structured_output": structured_output,
                        "expected_outputs": request.expected_outputs,
                    },
                )
                result = ApiRunResult(
                    run_id=run_id,
                    run_request_id=request.run_request_id,
                    model=str(raw_payload.get("model") or prompt_template.model),
                    mode=request.mode,
                    status=ApiRunStatus.COMPLETED,
                    structured_output=structured_output,
                    raw_output_path=str(raw_output_path),
                    prompt_artifact_path=prompt_template.artifact_path,
                    result_artifact_path=str(structured_output_path),
                    estimated_cost_eur=estimated_cost,
                    usage=usage,
                    metadata={"review_package_path": str(review_package_path)},
                )
                self._record_run_event(
                    run_id=run_id,
                    phase="review",
                    severity="info",
                    machine_summary="Cross-model review in progress via Claude API.",
                    human_summary=None,
                    payload={"reviewer_model": REVIEWER_MODEL},
                )
                review = self._call_reviewer(result=result, context_pack=context_pack)
                review_cost = float(review.metadata.get("estimated_cost_eur") or 0.0)
                review_usage = dict(review.metadata.get("usage") or {})
                generation_usage = dict(result.usage)
                result.estimated_cost_eur = round(result.estimated_cost_eur + review_cost, 6)
                result.usage = self._merge_usage(generation_usage, review_usage)
                result.metadata.update(
                    {
                        "review_id": review.review_id,
                        "review_artifact_path": review.metadata.get("artifact_path"),
                        "review_estimated_cost_eur": review_cost,
                        "generation_estimated_cost_eur": estimated_cost,
                    }
                )
                completion_report = self._build_completion_report(review=review, result=result, request=request)
                request_finalized_at = datetime.now(timezone.utc).isoformat()
                result.updated_at = request_finalized_at
                with self.database.transaction() as connection:
                    self._persist_completion_report(completion_report, connection=connection)
                    result.metadata["completion_report_id"] = completion_report.report_id
                    result.metadata["completion_report_path"] = str(completion_report.metadata.get("artifact_path") or "")
                    self._persist_run_result(result, connection=connection)
                    self._update_request_status(
                        request.run_request_id,
                        ApiRunStatus.COMPLETED,
                        updated_at=request_finalized_at,
                        connection=connection,
                    )
                    self._record_run_event(
                        run_id=run_id,
                        phase="termine",
                        severity="info",
                        machine_summary="Le run est termine et la review Claude est disponible.",
                        human_summary=completion_report.summary,
                        payload={
                            "estimated_cost_eur": result.estimated_cost_eur,
                            "result_artifact_path": result.result_artifact_path,
                            "review_package_path": str(review_package_path),
                            "review_id": review.review_id,
                            "review_verdict": review.verdict.value,
                            "completion_report_id": completion_report.report_id,
                        },
                        connection=connection,
                        refresh_snapshot=False,
                    )
                    self._emit_run_lifecycle_event(
                        run_id=run_id,
                        run_request_id=request.run_request_id,
                        contract_id=request.contract_id,
                        kind=RunLifecycleEventKind.RUN_COMPLETED,
                        mode=request.mode,
                        branch_name=request.branch_name,
                        status=ApiRunStatus.COMPLETED,
                        phase="termine",
                        title="Run termine",
                        summary="Le run est termine et la review Claude est disponible pour decision.",
                        recommended_action=completion_report.next_action,
                        result=result,
                        review=review,
                        metadata={
                            "objective": request.objective,
                            "review_package_path": str(review_package_path),
                            "estimated_cost_eur": result.estimated_cost_eur,
                            "review_id": review.review_id,
                            "review_verdict": review.verdict.value,
                            "completion_report_id": completion_report.report_id,
                        },
                        connection=connection,
                        refresh_snapshot=False,
                    )
                self._detect_noise_signal(run_id=result.run_id, structured_output=structured_output, request=request)
                self.logger.log(
                    "INFO",
                    "api_run_completed",
                    run_id=result.run_id,
                    mode=result.mode.value,
                    estimated_cost_eur=result.estimated_cost_eur,
                    review_verdict=review.verdict.value,
                    review_id=review.review_id,
                )
                self.journal.append(
                    "api_run_completed",
                    "api_runs",
                    {
                        "run_id": result.run_id,
                        "run_request_id": request.run_request_id,
                        "mode": result.mode.value,
                        "branch_name": request.branch_name,
                        "estimated_cost_eur": result.estimated_cost_eur,
                        "review_id": review.review_id,
                        "review_verdict": review.verdict.value,
                    },
                )
                self._refresh_live_snapshot()
        except Exception as exc:
            error_payload = {"error": str(exc), "mode": request.mode.value, "branch_name": request.branch_name}
            raw_output_path = self._write_runtime_json(self.paths.api_runs_root / "failed_results", run_id, error_payload)
            result = ApiRunResult(
                run_id=run_id,
                run_request_id=request.run_request_id,
                model=prompt_template.model,
                mode=request.mode,
                status=ApiRunStatus.FAILED,
                structured_output={},
                raw_output_path=str(raw_output_path),
                prompt_artifact_path=prompt_template.artifact_path,
                result_artifact_path=None,
                estimated_cost_eur=0.0,
                usage={},
                metadata={"error": str(exc)},
            )
            blockage = self._build_blockage_report(result=result, request=request, error=str(exc))
            request_failed_at = datetime.now(timezone.utc).isoformat()
            result.updated_at = request_failed_at
            with self.database.transaction() as connection:
                self._persist_run_result(result, connection=connection)
                self._update_request_status(
                    request.run_request_id,
                    ApiRunStatus.FAILED,
                    updated_at=request_failed_at,
                    connection=connection,
                )
                self._persist_blockage_report(blockage, connection=connection)
                self._record_run_event(
                    run_id=run_id,
                    phase="bloque",
                    severity="error",
                    machine_summary=f"Le run a echoue: {str(exc)}",
                    human_summary=f"Blocage reel detecte: {blockage.cause}",
                    payload={"blockage_report_id": blockage.report_id, "error": str(exc)},
                    connection=connection,
                    refresh_snapshot=False,
                )
                self._emit_run_lifecycle_event(
                    run_id=run_id,
                    run_request_id=request.run_request_id,
                    contract_id=request.contract_id,
                    kind=RunLifecycleEventKind.RUN_FAILED,
                    mode=request.mode,
                    branch_name=request.branch_name,
                    status=ApiRunStatus.FAILED,
                    phase="bloque",
                    title="Run bloque",
                    summary=blockage.cause,
                    recommended_action=blockage.recommendation,
                    metadata={
                        "objective": request.objective,
                        "blockage_report_id": blockage.report_id,
                        "error": str(exc),
                    },
                    connection=connection,
                    refresh_snapshot=False,
                )
            self._record_dead_letter(
                domain="api_run_failure",
                source_entity_kind=TraceEntityKind.API_RUN.value,
                source_entity_id=run_id,
                error_code="run_failed",
                error_message=str(exc),
                replayable=False,
                recovery_command=f"project-os api-runs show-artifacts --run-id {run_id}",
                artifact_path=str(blockage.metadata.get("artifact_path") or raw_output_path),
                run_id=run_id,
                metadata={
                    "run_request_id": request.run_request_id,
                    "mode": request.mode.value,
                    "branch_name": request.branch_name,
                    "blockage_report_id": blockage.report_id,
                },
            )
            self.logger.log(
                "ERROR",
                "api_run_failed",
                run_id=run_id,
                run_request_id=request.run_request_id,
                mode=request.mode.value,
                error=str(exc),
            )
            self.journal.append(
                "api_run_failed",
                "api_runs",
                {
                    "run_id": run_id,
                    "run_request_id": request.run_request_id,
                    "mode": request.mode.value,
                    "branch_name": request.branch_name,
                    "error": str(exc),
                },
            )
            self._refresh_live_snapshot()

        snapshot = self.monitor_snapshot()
        return {
            "contract": contract,
            "context_pack": context_pack,
            "prompt_template": prompt_template,
            "request": request,
            "result": result,
            "review": review,
            "completion_report": completion_report,
            "monitor_snapshot": snapshot,
        }

    def _ensure_operator_dashboard(self, *, contract: RunContract | None = None) -> dict[str, Any]:
        if not getattr(self.dashboard_config, "auto_start", False):
            return {"ready": True, "reason": "dashboard_disabled"}
        from .dashboard import ensure_dashboard_running

        status = ensure_dashboard_running(
            repo_root=self.repo_root,
            host=self.dashboard_config.host,
            port=self.dashboard_config.port,
            limit=self.dashboard_config.limit,
            refresh_seconds=self.dashboard_config.refresh_seconds,
            open_browser=self.dashboard_config.auto_open_browser,
            require_visible_ui=getattr(self.dashboard_config, "require_visible_ui", True),
            wait_seconds=float(getattr(self.dashboard_config, "beacon_wait_seconds", 12.0)),
            recent_beacon_grace_seconds=int(getattr(self.dashboard_config, "recent_beacon_grace_seconds", 1800)),
            visibility_state_path=self.paths.api_runs_root / "operator_visibility.json",
        )
        if status.get("ready"):
            return status
        if self._has_recent_founder_approval(contract):
            fallback_status = {
                **status,
                "ready": True,
                "reason": "founder_approval_fallback",
            }
            self.journal.append(
                "api_run_dashboard_fallback_used",
                "api_runs",
                {
                    "contract_id": contract.contract_id if contract else None,
                    "dashboard_reason": str(status.get("reason") or "control_room_unverified"),
                },
            )
            return fallback_status
        detail = str(status.get("reason") or "control_room_unverified")
        raise RuntimeError(f"La control room locale n'a pas pu etre ouverte et verifiee sur le PC. Cause: {detail}")

    def _has_recent_founder_approval(self, contract: RunContract | None) -> bool:
        if contract is None or contract.founder_decision not in {"go", "go_avec_correction"}:
            return False
        grace_seconds = int(getattr(self.dashboard_config, "founder_approval_grace_seconds", 1800))
        if grace_seconds <= 0:
            return False
        approved_at = str(contract.founder_decision_at or "")
        if not approved_at:
            return False
        try:
            approved_at_dt = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        age_seconds = (datetime.now(timezone.utc) - approved_at_dt).total_seconds()
        return 0 <= age_seconds <= grace_seconds

    def _run_repo_preflight(self, *, target_branch: str, contract: RunContract | None) -> dict[str, Any]:
        repo_state = self._repo_state(target_branch=target_branch)
        metadata = contract.metadata if contract is not None else {}
        current_branch = str(repo_state.get("current_branch") or "")
        dirty = bool(repo_state.get("dirty"))
        allow_branch_mismatch = bool(metadata.get("allow_branch_mismatch"))
        allow_dirty_worktree = bool(metadata.get("allow_dirty_worktree"))
        require_clean_worktree = bool(metadata.get("require_clean_worktree"))
        issues: list[str] = []
        if current_branch != target_branch and not allow_branch_mismatch:
            issues.append("branch_mismatch")
        if dirty and current_branch != target_branch and not allow_dirty_worktree:
            issues.append("dirty_worktree_on_mismatched_branch")
        elif dirty and require_clean_worktree and not allow_dirty_worktree:
            issues.append("dirty_worktree_requires_clean_checkout")
        return {
            **repo_state,
            "ok": not issues,
            "issues": issues,
            "allow_branch_mismatch": allow_branch_mismatch,
            "allow_dirty_worktree": allow_dirty_worktree,
            "require_clean_worktree": require_clean_worktree,
        }

    def _build_repo_preflight_clarification(
        self,
        *,
        run_id: str,
        request: ApiRunRequest,
        preflight: dict[str, Any],
    ) -> ClarificationReport:
        current_branch = str(preflight.get("current_branch") or "unknown")
        target_branch = str(preflight.get("target_branch") or request.branch_name)
        dirty = bool(preflight.get("dirty"))
        status_short = [str(item) for item in preflight.get("status_short") or []]
        if current_branch != target_branch and dirty:
            cause = (
                f"Conflit repo/runtime reel: le contrat vise `{target_branch}`, alors que le checkout local est "
                f"`{current_branch}` et que l'arbre Git est deja sale."
            )
        elif current_branch != target_branch:
            cause = (
                f"Conflit de branche: le contrat vise `{target_branch}`, mais le checkout local est `{current_branch}`."
            )
        else:
            cause = "Le contrat exige un checkout propre avant ecriture, mais l'arbre Git local est deja sale."
        if dirty:
            impact = (
                "Un patch ecrit maintenant risque de melanger ou d'ecraser des changements locaux non arbitres. "
                f"Etat Git courant: {' | '.join(status_short[:8]) or 'worktree sale'}."
            )
        else:
            impact = (
                "Un patch ecrit maintenant partirait sur une base repo differente de celle approuvee dans le contrat."
            )
        question = (
            f"Confirmez-vous que ce lot doit s'integrer sur `{current_branch}` tel quel, "
            f"ou faut-il d'abord realigner le checkout sur `{target_branch}` avant patch et tests ?"
        )
        recommended = (
            f"Ajouter une precondition repo explicite au contrat: checkout de `{target_branch}` avant generation de patch. "
            f"A defaut, noter noir sur blanc que l'integration sur `{current_branch}`"
            f"{' avec worktree sale' if dirty else ''} est acceptee puis redonner un go."
        )
        return ClarificationReport(
            report_id=new_id("clarification_report"),
            run_id=run_id,
            cause=cause,
            impact=impact,
            question_for_founder=question,
            recommended_contract_change=recommended,
            requires_reapproval=True,
            metadata={
                "mode": request.mode.value,
                "branch_name": request.branch_name,
                "preflight": preflight,
                "source": "repo_preflight",
            },
        )

    def _create_preflight_clarification_exit(
        self,
        *,
        contract: RunContract | None,
        context_pack: ContextPack,
        prompt_template: MegaPromptTemplate,
        resolved_mode: ApiRunMode,
        resolved_target_profile: str | None,
        resolved_expected_outputs: list[str],
        request_metadata: dict[str, Any],
        preflight: dict[str, Any],
    ) -> dict[str, Any]:
        contract_expected_updated_at = contract.updated_at if contract is not None else None
        request = ApiRunRequest(
            run_request_id=new_id("run_request"),
            context_pack_id=context_pack.context_pack_id,
            prompt_template_id=prompt_template.prompt_template_id,
            mode=resolved_mode,
            objective=context_pack.objective,
            branch_name=context_pack.branch_name,
            target_profile=resolved_target_profile,
            skill_tags=context_pack.skill_tags,
            expected_outputs=resolved_expected_outputs,
            communication_mode=CommunicationMode.BUILDER,
            speech_policy=self.execution_policy.default_run_speech_policy,
            operator_language=self.execution_policy.operator_language,
            audience=self.execution_policy.operator_audience,
            run_contract_required=bool(contract is not None or self.execution_policy.run_contract_required),
            contract_id=contract.contract_id if contract else None,
            status=ApiRunStatus.CLARIFICATION_REQUIRED,
            metadata={**request_metadata, "preflight_blocked": True},
        )
        run_id = new_id("api_run")
        clarification = self._build_repo_preflight_clarification(
            run_id=run_id,
            request=request,
            preflight=preflight,
        )
        structured_output = {
            "decision": "clarification_required",
            "why": clarification.impact,
            "alternatives": [
                f"Realigner le checkout sur `{request.branch_name}` puis relancer.",
                "Assumer explicitement l'integration sur l'arbre local actuel et redonner un go.",
            ],
            "files_to_change": [],
            "interfaces": ["repo_preflight", "run_contract"],
            "patch_outline": ["Aucun patch produit avant arbitrage repo."],
            "tests": ["Aucun test lance avant arbitrage repo."],
            "risks": [clarification.cause],
            "acceptance_criteria": ["Le patch ne doit partir que sur la base repo explicitement confirmee."],
            "open_questions": [clarification.question_for_founder],
            "clarification_needed": True,
            "blocking_reason": clarification.cause,
            "recommended_contract_change": clarification.recommended_contract_change,
            "question_for_founder": clarification.question_for_founder,
        }
        raw_output_path = self._write_runtime_json(
            self.paths.api_runs_root / "raw_results",
            run_id,
            {"source": "repo_preflight", "preflight": preflight, "clarification_report_id": clarification.report_id},
        )
        structured_output_path = self._write_runtime_json(
            self.paths.api_runs_root / "structured_results",
            run_id,
            structured_output,
        )
        result = ApiRunResult(
            run_id=run_id,
            run_request_id=request.run_request_id,
            model=prompt_template.model,
            mode=request.mode,
            status=ApiRunStatus.CLARIFICATION_REQUIRED,
            structured_output=structured_output,
            raw_output_path=str(raw_output_path),
            prompt_artifact_path=prompt_template.artifact_path,
            result_artifact_path=str(structured_output_path),
            estimated_cost_eur=0.0,
            usage={},
            metadata={"source": "repo_preflight"},
        )
        with self.database.transaction() as connection:
            self._persist_run_request(request, connection=connection)
            self._persist_clarification_report(clarification, connection=connection)
            result.metadata["clarification_report_path"] = str(clarification.metadata["artifact_path"])
            self._persist_run_result(result, connection=connection)
            if contract is not None:
                self._mark_contract_clarification_pending(
                    contract=contract,
                    clarification=clarification,
                    connection=connection,
                    expected_updated_at=contract_expected_updated_at,
                )
            self._record_run_event(
                run_id=run_id,
                phase="clarification",
                severity="warning",
                machine_summary=f"Clarification requise avant depense API: {clarification.cause}",
                human_summary=f"Question fondatrice requise: {clarification.question_for_founder}",
                payload={"clarification_report_id": clarification.report_id, "preflight": preflight},
                connection=connection,
                refresh_snapshot=False,
            )
            self._emit_run_lifecycle_event(
                run_id=run_id,
                run_request_id=request.run_request_id,
                contract_id=request.contract_id,
                kind=RunLifecycleEventKind.CLARIFICATION_REQUIRED,
                mode=request.mode,
                branch_name=request.branch_name,
                status=ApiRunStatus.CLARIFICATION_REQUIRED,
                phase="clarification",
                title="Clarification requise avant run",
                summary=clarification.cause,
                blocking_question=clarification.question_for_founder,
                recommended_action=clarification.recommended_contract_change,
                requires_reapproval=clarification.requires_reapproval,
                metadata={"objective": request.objective, "source": "repo_preflight"},
                connection=connection,
                refresh_snapshot=False,
            )
        self.journal.append(
            "api_run_preflight_blocked",
            "api_runs",
            {
                "run_id": run_id,
                "run_request_id": request.run_request_id,
                "contract_id": request.contract_id,
                "issues": preflight.get("issues", []),
                "target_branch": request.branch_name,
                "current_branch": preflight.get("current_branch"),
            },
        )
        self._refresh_live_snapshot()
        snapshot = self.monitor_snapshot()
        return {
            "contract": contract,
            "context_pack": context_pack,
            "prompt_template": prompt_template,
            "request": request,
            "result": result,
            "monitor_snapshot": snapshot,
        }

    def review_result(
        self,
        *,
        run_id: str,
        verdict: ApiRunReviewVerdict,
        reviewer: str,
        findings: list[str] | None = None,
        accepted_changes: list[str] | None = None,
        followup_actions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApiRunReview:
        run_result = self.get_run_result(run_id)
        if run_result.status is ApiRunStatus.CLARIFICATION_REQUIRED:
            raise RuntimeError("Les runs en clarification_required doivent etre amendes puis re-executes avant review.")
        request = self.get_run_request(run_result.run_request_id)
        review = ApiRunReview(
            review_id=new_id("run_review"),
            run_id=run_id,
            verdict=verdict,
            reviewer=reviewer,
            findings=list(findings or []),
            accepted_changes=list(accepted_changes or []),
            followup_actions=list(followup_actions or []),
            metadata=dict(metadata or {}),
        )
        self._store_run_review(review)
        self._update_result_status(run_id, ApiRunStatus.REVIEWED)
        self._update_request_status(request.run_request_id, ApiRunStatus.REVIEWED)
        self._apply_learning(review=review, result=run_result, request=request)
        completion_report = self._build_completion_report(review=review, result=run_result, request=request)
        self._persist_completion_report(completion_report)
        self._record_run_event(
            run_id=run_id,
            phase="revue_terminee",
            severity="info",
            machine_summary=f"Revue terminee avec verdict {review.verdict.value}.",
            human_summary=completion_report.summary,
            payload={"review_id": review.review_id, "completion_report_id": completion_report.report_id},
        )
        self._emit_run_lifecycle_event(
            run_id=run_id,
            run_request_id=request.run_request_id,
            contract_id=request.contract_id,
            kind=RunLifecycleEventKind.RUN_REVIEWED,
            mode=request.mode,
            branch_name=request.branch_name,
            status=ApiRunStatus.REVIEWED,
            phase="revue_terminee",
            title="Run relu",
            summary=f"Verdict local: {review.verdict.value}.",
            recommended_action=completion_report.next_action,
            result=run_result,
            review=review,
            metadata={
                "review_id": review.review_id,
                "review_verdict": review.verdict.value,
                "completion_report_id": completion_report.report_id,
            },
        )
        self.journal.append(
            "api_run_reviewed",
            "api_runs",
            {
                "run_id": run_id,
                "review_id": review.review_id,
                "verdict": review.verdict.value,
                "reviewer": reviewer,
            },
        )
        self.monitor_snapshot()
        return review

    def set_run_status(self, *, run_id: str, status: ApiRunStatus) -> dict[str, Any]:
        run_result = self.get_run_result(run_id)
        request = self.get_run_request(run_result.run_request_id)
        self._update_result_status(run_id, status)
        self._update_request_status(request.run_request_id, status)
        payload = {"run_id": run_id, "run_request_id": request.run_request_id, "status": status.value}
        self.journal.append("api_run_status_updated", "api_runs", payload)
        self.monitor_snapshot()
        return payload

    def show_artifacts(self, *, run_id: str) -> dict[str, Any]:
        run_result = self.get_run_result(run_id)
        request = self.get_run_request(run_result.run_request_id)
        context_pack = self.get_context_pack(request.context_pack_id)
        prompt_template = self.get_prompt_template(request.prompt_template_id)
        contract = self.get_run_contract(request.contract_id) if request.contract_id else None
        review_row = self.database.fetchone(
            "SELECT * FROM api_run_reviews WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        )
        review_payload = json.loads(review_row["metadata_json"]) if review_row else {}
        artifacts = [
            ApiRunArtifact(new_id("api_artifact"), run_id, "context_pack", context_pack.artifact_path or ""),
            ApiRunArtifact(new_id("api_artifact"), run_id, "prompt", prompt_template.artifact_path or ""),
            ApiRunArtifact(new_id("api_artifact"), run_id, "raw_output", run_result.raw_output_path or ""),
            ApiRunArtifact(new_id("api_artifact"), run_id, "structured_output", run_result.result_artifact_path or ""),
        ]
        if contract and contract.metadata.get("artifact_path"):
            artifacts.append(ApiRunArtifact(new_id("api_artifact"), run_id, "contrat", str(contract.metadata["artifact_path"])))
        if review_payload.get("artifact_path"):
            artifacts.append(ApiRunArtifact(new_id("api_artifact"), run_id, "review", str(review_payload["artifact_path"])))
        completion_row = self.database.fetchone(
            "SELECT * FROM completion_reports WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        )
        if completion_row:
            completion_payload = json.loads(completion_row["metadata_json"])
            if completion_payload.get("artifact_path"):
                artifacts.append(ApiRunArtifact(new_id("api_artifact"), run_id, "rapport_final", str(completion_payload["artifact_path"])))
        blockage_row = self.database.fetchone(
            "SELECT * FROM blockage_reports WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        )
        if blockage_row:
            blockage_payload = json.loads(blockage_row["metadata_json"])
            if blockage_payload.get("artifact_path"):
                artifacts.append(ApiRunArtifact(new_id("api_artifact"), run_id, "blocage", str(blockage_payload["artifact_path"])))
        clarification_row = self.database.fetchone(
            "SELECT * FROM clarification_reports WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        )
        if clarification_row:
            clarification_payload = json.loads(clarification_row["metadata_json"])
            if clarification_payload.get("artifact_path"):
                artifacts.append(
                    ApiRunArtifact(new_id("api_artifact"), run_id, "clarification", str(clarification_payload["artifact_path"]))
                )
        return {"run_id": run_id, "artifacts": [to_jsonable(item) for item in artifacts]}

    def publish_operator_update(
        self,
        *,
        title: str,
        summary: str,
        text: str | None = None,
        kind: RunLifecycleEventKind = RunLifecycleEventKind.RUN_COMPLETED,
        status: ApiRunStatus | None = None,
        channel_hint: OperatorChannelHint = OperatorChannelHint.RUNS_LIVE,
        mode: ApiRunMode | None = None,
        branch_name: str | None = None,
        target: str | None = None,
        reply_to: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = RunLifecycleEvent(
            lifecycle_event_id=new_id("lifecycle_event"),
            run_id=new_id("external_run"),
            run_request_id=new_id("external_request"),
            kind=kind,
            title=title.strip(),
            summary=summary.strip(),
            branch_name=branch_name,
            mode=mode,
            channel_hint=channel_hint,
            status=status,
            phase="external_update",
            metadata=dict(metadata or {}),
        )
        with self.database.transaction() as connection:
            self._persist_lifecycle_event(event, connection=connection)
            self._prune_pending_operator_deliveries(incoming_channel_hint=event.channel_hint, connection=connection)
            delivery_guarantee = self._delivery_guarantee_for_kind(kind, channel_hint=event.channel_hint)
            backlog_state = self._operator_delivery_backlog_state(connection=connection)
            payload = self._build_operator_delivery_payload(
                event,
                translated_message=(text or self._render_operator_delivery_text(event)),
                delivery_guarantee=delivery_guarantee,
                backlog_state=backlog_state,
            )
            if target:
                payload["target"] = target
            if reply_to:
                payload["reply_to"] = reply_to
            if attachments:
                payload["response_manifest"] = {
                    "delivery_mode": "direct_attachment",
                    "discord_summary": str(text or summary),
                    "attachments": attachments,
                    "metadata": {"source": "publish_operator_update"},
                }
            delivery = OperatorDelivery(
                delivery_id=new_id("operator_delivery"),
                lifecycle_event_id=event.lifecycle_event_id,
                adapter="openclaw",
                surface="discord",
                channel_hint=event.channel_hint,
                status=OperatorDeliveryStatus.PENDING,
                payload=payload,
                metadata={
                    "run_id": event.run_id,
                    "kind": kind.value,
                    "delivery_guarantee": delivery_guarantee.value,
                    "delivery_priority_rank": self._operator_delivery_guarantee_rank(delivery_guarantee),
                    "replayable": True,
                    "backlog_soft_limit_exceeded": backlog_state["soft_limit_exceeded"],
                    "pending_backlog_count": backlog_state["pending_count"],
                    "pending_backlog_limit": backlog_state["max_pending"],
                    "external_update": True,
                },
                next_attempt_at=event.created_at,
            )
            self._persist_operator_delivery(delivery, connection=connection)
        self.journal.append(
            "api_run_external_operator_update_published",
            "api_runs",
            {
                "lifecycle_event_id": event.lifecycle_event_id,
                "delivery_id": delivery.delivery_id,
                "kind": kind.value,
                "channel_hint": channel_hint.value,
            },
        )
        self._refresh_live_snapshot()
        return {
            "lifecycle_event_id": event.lifecycle_event_id,
            "delivery_id": delivery.delivery_id,
            "delivery_guarantee": delivery_guarantee.value,
            "target": target,
            "reply_to": reply_to,
        }

    def list_operator_deliveries(
        self,
        *,
        status: OperatorDeliveryStatus | None = OperatorDeliveryStatus.PENDING,
        limit: int = 20,
    ) -> dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = """
            SELECT
                d.*,
                e.run_id,
                e.run_request_id,
                e.contract_id,
                e.kind,
                e.title,
                e.summary,
                e.branch_name,
                e.mode,
                e.status AS run_status,
                e.phase,
                e.blocking_question,
                e.recommended_action,
                e.requires_reapproval,
                e.artifact_path
            FROM api_run_operator_deliveries d
            JOIN api_run_lifecycle_events e ON e.lifecycle_event_id = d.lifecycle_event_id
        """
        params: list[Any] = []
        if status is not None:
            sql += " WHERE d.status = ?"
            params.append(status.value)
            if status is OperatorDeliveryStatus.PENDING:
                sql += " AND COALESCE(d.next_attempt_at, d.updated_at, d.created_at) <= ?"
                params.append(now_iso)
        sql += " ORDER BY COALESCE(d.next_attempt_at, d.created_at) ASC, d.created_at ASC"
        rows = self.database.fetchall(sql, tuple(params))
        deliveries_with_sort_keys: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for row in rows:
            payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            guarantee = self._coerce_operator_delivery_guarantee(
                metadata.get("delivery_guarantee")
                or payload.get("delivery_guarantee")
                or self._delivery_guarantee_for_kind(
                    RunLifecycleEventKind(str(row["kind"])) if row["kind"] else None,
                    channel_hint=OperatorChannelHint(str(row["channel_hint"])),
                ).value
            )
            priority_rank = self._operator_delivery_guarantee_rank(guarantee)
            delivery = {
                "delivery_id": str(row["delivery_id"]),
                "lifecycle_event_id": str(row["lifecycle_event_id"]),
                "adapter": str(row["adapter"]),
                "surface": str(row["surface"]),
                "channel_hint": str(row["channel_hint"]),
                "status": str(row["status"]),
                "attempts": int(row["attempts"]),
                "last_error": str(row["last_error"]) if row["last_error"] else None,
                "next_attempt_at": str(row["next_attempt_at"]) if row["next_attempt_at"] else None,
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "delivery_guarantee": guarantee.value,
                "delivery_priority_rank": priority_rank,
                "payload": payload,
                "metadata": metadata,
                "event": {
                    "run_id": str(row["run_id"]),
                    "run_request_id": str(row["run_request_id"]),
                    "contract_id": str(row["contract_id"]) if row["contract_id"] else None,
                    "kind": str(row["kind"]),
                    "title": str(row["title"]),
                    "summary": str(row["summary"]),
                    "branch_name": str(row["branch_name"]) if row["branch_name"] else None,
                    "mode": str(row["mode"]) if row["mode"] else None,
                    "status": str(row["run_status"]) if row["run_status"] else None,
                    "phase": str(row["phase"]) if row["phase"] else None,
                    "blocking_question": str(row["blocking_question"]) if row["blocking_question"] else None,
                    "recommended_action": str(row["recommended_action"]) if row["recommended_action"] else None,
                    "requires_reapproval": bool(row["requires_reapproval"]),
                    "artifact_path": str(row["artifact_path"]) if row["artifact_path"] else None,
                },
            }
            deliveries_with_sort_keys.append(
                (
                    self._operator_delivery_sort_key(
                        status=str(row["status"]),
                        next_attempt_at=str(row["next_attempt_at"]) if row["next_attempt_at"] else None,
                        created_at=str(row["created_at"]),
                        guarantee=guarantee,
                    ),
                    delivery,
                )
            )
        deliveries = [item for _, item in sorted(deliveries_with_sort_keys, key=lambda entry: entry[0])[:limit]]
        return {"deliveries": deliveries}

    def _coerce_operator_delivery_guarantee(self, value: Any) -> OperatorDeliveryGuarantee:
        if isinstance(value, OperatorDeliveryGuarantee):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            for candidate in OperatorDeliveryGuarantee:
                if candidate.value == normalized:
                    return candidate
        return OperatorDeliveryGuarantee.IMPORTANT

    def _operator_delivery_guarantee_rank(self, guarantee: OperatorDeliveryGuarantee | str | None) -> int:
        resolved = self._coerce_operator_delivery_guarantee(guarantee)
        return _DELIVERY_GUARANTEE_RANK.get(resolved, _DELIVERY_GUARANTEE_RANK[OperatorDeliveryGuarantee.IMPORTANT])

    def _operator_delivery_sort_key(
        self,
        *,
        status: str,
        next_attempt_at: str | None,
        created_at: str,
        guarantee: OperatorDeliveryGuarantee | str | None,
    ) -> tuple[Any, ...]:
        priority_rank = self._operator_delivery_guarantee_rank(guarantee)
        due_marker = next_attempt_at or created_at
        status_marker = 0 if status == OperatorDeliveryStatus.PENDING.value else 1
        return (status_marker, -priority_rank, due_marker, created_at)

    def _delivery_guarantee_for_kind(
        self,
        kind: RunLifecycleEventKind | None,
        *,
        channel_hint: OperatorChannelHint,
    ) -> OperatorDeliveryGuarantee:
        if kind is RunLifecycleEventKind.RUN_COMPLETED:
            return OperatorDeliveryGuarantee.MUST_PERSIST
        if kind in {
            RunLifecycleEventKind.CLARIFICATION_REQUIRED,
            RunLifecycleEventKind.CONTRACT_PROPOSED,
            RunLifecycleEventKind.CONTRACT_APPROVED,
            RunLifecycleEventKind.CONTRACT_REJECTED,
            RunLifecycleEventKind.RUN_FAILED,
            RunLifecycleEventKind.BUDGET_ALERT,
        }:
            return OperatorDeliveryGuarantee.MUST_NOTIFY
        if channel_hint is OperatorChannelHint.RUNS_LIVE:
            return OperatorDeliveryGuarantee.IMPORTANT
        return OperatorDeliveryGuarantee.IMPORTANT

    def mark_operator_delivery(
        self,
        *,
        delivery_id: str,
        status: OperatorDeliveryStatus,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM api_run_operator_deliveries WHERE delivery_id = ?",
            (delivery_id,),
        )
        if row is None:
            raise KeyError(f"Unknown operator delivery: {delivery_id}")
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        delivery_metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        current_status = OperatorDeliveryStatus(str(row["status"]))
        if current_status is OperatorDeliveryStatus.DELIVERED and status is not OperatorDeliveryStatus.DELIVERED:
            self.journal.append(
                "api_run_operator_delivery_ack_ignored",
                "api_runs",
                {
                    "delivery_id": delivery_id,
                    "current_status": current_status.value,
                    "requested_status": status.value,
                },
            )
            return {
                "delivery_id": delivery_id,
                "status": current_status.value,
                "attempts": int(row["attempts"] or 0),
                "last_error": str(row["last_error"]) if row["last_error"] else None,
                "next_attempt_at": str(row["next_attempt_at"]) if row["next_attempt_at"] else None,
                "delivery_guarantee": str(
                    delivery_metadata.get("delivery_guarantee")
                    or payload.get("delivery_guarantee")
                    or OperatorDeliveryGuarantee.IMPORTANT.value
                ),
                "metadata": delivery_metadata,
            }
        if metadata:
            delivery_metadata.update(metadata)
        guarantee = self._coerce_operator_delivery_guarantee(
            delivery_metadata.get("delivery_guarantee") or payload.get("delivery_guarantee")
        )
        delivery_metadata["delivery_guarantee"] = guarantee.value
        delivery_metadata["delivery_priority_rank"] = self._operator_delivery_guarantee_rank(guarantee)
        delivery_metadata["replayable"] = True
        attempts = int(row["attempts"] or 0) + 1
        updated_at = datetime.now(timezone.utc).isoformat()
        final_status = status
        next_attempt_at: str | None = None
        if status is OperatorDeliveryStatus.PENDING:
            max_attempts = max(1, int(getattr(self.execution_policy, "operator_delivery_max_attempts", 4)))
            if attempts >= max_attempts:
                final_status = OperatorDeliveryStatus.FAILED
            else:
                base_seconds = max(1, int(getattr(self.execution_policy, "operator_delivery_retry_base_seconds", 30)))
                max_seconds = max(base_seconds, int(getattr(self.execution_policy, "operator_delivery_retry_max_seconds", 900)))
                delay_seconds = min(max_seconds, base_seconds * (2 ** max(0, attempts - 1)))
                jitter_seconds = min(15, abs(hash(delivery_id)) % 7)
                next_attempt_at = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds + jitter_seconds)).isoformat()
                delivery_metadata["retry_backoff_seconds"] = delay_seconds + jitter_seconds
        else:
            delivery_metadata.pop("retry_backoff_seconds", None)
        attempt_history = delivery_metadata.get("attempt_history")
        if not isinstance(attempt_history, list):
            attempt_history = []
        attempt_history.append(
            {
                "attempt": attempts,
                "requested_status": status.value,
                "applied_status": final_status.value,
                "error": error,
                "at": updated_at,
            }
        )
        delivery_metadata["attempt_history"] = attempt_history[-10:]
        delivery_metadata["last_transition_at"] = updated_at
        if final_status is OperatorDeliveryStatus.DELIVERED:
            delivery_metadata["delivered_at"] = updated_at
            delivery_metadata["replay_status"] = "delivered"
        elif final_status is OperatorDeliveryStatus.PENDING:
            delivery_metadata["replay_status"] = "queued"
        else:
            delivery_metadata["replay_status"] = "manual_requeue_available"
        dead_letter_artifact_path: str | None = None
        if final_status in {OperatorDeliveryStatus.FAILED, OperatorDeliveryStatus.SKIPPED, OperatorDeliveryStatus.EXPIRED}:
            delivery_metadata["delivery_terminal_reason"] = error or final_status.value
            dead_letter_artifact_path = self._persist_operator_delivery_dead_letter(
                delivery_id=delivery_id,
                row=row,
                payload=payload,
                metadata=delivery_metadata,
                final_status=final_status,
                error=error,
                attempts=attempts,
                updated_at=updated_at,
            )
            if dead_letter_artifact_path:
                delivery_metadata["dead_letter_artifact_path"] = dead_letter_artifact_path
                delivery_metadata["dead_letter_created_at"] = updated_at
        else:
            delivery_metadata.pop("delivery_terminal_reason", None)
        self.database.execute(
            """
            UPDATE api_run_operator_deliveries
            SET status = ?, attempts = ?, last_error = ?, next_attempt_at = ?, metadata_json = ?, updated_at = ?
            WHERE delivery_id = ?
            """,
            (
                final_status.value,
                attempts,
                error,
                next_attempt_at,
                dump_json(delivery_metadata),
                updated_at,
                delivery_id,
            ),
        )
        self.journal.append(
            "api_run_operator_delivery_updated",
            "api_runs",
            {
                "delivery_id": delivery_id,
                "status": final_status.value,
                "attempts": attempts,
                "last_error": error or "",
                "delivery_guarantee": guarantee.value,
                "dead_letter_artifact_path": dead_letter_artifact_path or "",
            },
        )
        self._refresh_live_snapshot()
        return {
            "delivery_id": delivery_id,
            "status": final_status.value,
            "attempts": attempts,
            "last_error": error,
            "next_attempt_at": next_attempt_at,
            "delivery_guarantee": guarantee.value,
            "metadata": delivery_metadata,
        }

    def _persist_operator_delivery_dead_letter(
        self,
        *,
        delivery_id: str,
        row: Any,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        final_status: OperatorDeliveryStatus,
        error: str | None,
        attempts: int,
        updated_at: str,
    ) -> str | None:
        try:
            event_row = self.database.fetchone(
                "SELECT * FROM api_run_lifecycle_events WHERE lifecycle_event_id = ?",
                (str(row["lifecycle_event_id"]),),
            )
            artifact_path = self._write_runtime_json(
                self.paths.api_runs_root / "operator_delivery_dead_letters",
                delivery_id,
                {
                    "delivery_id": delivery_id,
                    "lifecycle_event_id": str(row["lifecycle_event_id"]),
                    "adapter": str(row["adapter"]),
                    "surface": str(row["surface"]),
                    "channel_hint": str(row["channel_hint"]),
                    "status": final_status.value,
                    "attempts": attempts,
                    "last_error": error or (str(row["last_error"]) if row["last_error"] else None),
                    "payload": payload,
                    "metadata": metadata,
                    "updated_at": updated_at,
                    "event": {
                        "kind": str(event_row["kind"]) if event_row else None,
                        "title": str(event_row["title"]) if event_row else None,
                        "summary": str(event_row["summary"]) if event_row else None,
                        "run_id": str(event_row["run_id"]) if event_row and event_row["run_id"] else None,
                        "branch_name": str(event_row["branch_name"]) if event_row and event_row["branch_name"] else None,
                    },
                    "requeue_command": f"project-os api-runs requeue-operator-delivery --delivery-id {delivery_id}",
                },
            )
            self.journal.append(
                "api_run_operator_delivery_dead_lettered",
                "api_runs",
                {
                    "delivery_id": delivery_id,
                    "status": final_status.value,
                    "artifact_path": str(artifact_path),
                },
            )
            self._record_dead_letter(
                domain="operator_delivery",
                source_entity_kind="operator_delivery",
                source_entity_id=delivery_id,
                error_code=final_status.value,
                error_message=error or (str(row["last_error"]) if row["last_error"] else None),
                replayable=True,
                recovery_command=f"project-os api-runs requeue-operator-delivery --delivery-id {delivery_id}",
                artifact_path=str(artifact_path),
                run_id=str(event_row["run_id"]) if event_row and event_row["run_id"] else None,
                metadata={
                    "adapter": str(row["adapter"]),
                    "surface": str(row["surface"]),
                    "channel_hint": str(row["channel_hint"]),
                    "lifecycle_event_id": str(row["lifecycle_event_id"]),
                    "attempts": attempts,
                },
            )
            return str(artifact_path)
        except Exception as exc:
            self.logger.log(
                "WARNING",
                "api_run_operator_delivery_dead_letter_failed",
                delivery_id=delivery_id,
                error=str(exc),
            )
            return None

    def requeue_operator_delivery(self, *, delivery_id: str) -> dict[str, Any]:
        row = self.database.fetchone(
            "SELECT * FROM api_run_operator_deliveries WHERE delivery_id = ?",
            (delivery_id,),
        )
        if row is None:
            raise KeyError(f"Unknown operator delivery: {delivery_id}")
        current_status = OperatorDeliveryStatus(str(row["status"]))
        if current_status not in {
            OperatorDeliveryStatus.FAILED,
            OperatorDeliveryStatus.SKIPPED,
            OperatorDeliveryStatus.EXPIRED,
        }:
            raise ValueError(f"Operator delivery {delivery_id} is not replayable from status {current_status.value}")
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        updated_at = datetime.now(timezone.utc).isoformat()
        metadata["replayable"] = True
        metadata["requeue_count"] = int(metadata.get("requeue_count") or 0) + 1
        metadata["last_requeued_at"] = updated_at
        metadata["replay_status"] = "queued"
        metadata.pop("retry_backoff_seconds", None)
        self.database.update_dead_letter_status_for_source(
            source_entity_kind="operator_delivery",
            source_entity_id=delivery_id,
            status="requeued",
            metadata={
                "last_requeued_at": updated_at,
                "requeue_count": metadata["requeue_count"],
            },
        )
        self.database.execute(
            """
            UPDATE api_run_operator_deliveries
            SET status = ?, attempts = 0, last_error = NULL, next_attempt_at = ?, metadata_json = ?, updated_at = ?
            WHERE delivery_id = ?
            """,
            (
                OperatorDeliveryStatus.PENDING.value,
                updated_at,
                dump_json(metadata),
                updated_at,
                delivery_id,
            ),
        )
        self.journal.append(
            "api_run_operator_delivery_requeued",
            "api_runs",
            {
                "delivery_id": delivery_id,
                "previous_status": current_status.value,
                "requeue_count": metadata["requeue_count"],
            },
        )
        self._refresh_live_snapshot()
        return {
            "delivery_id": delivery_id,
            "status": OperatorDeliveryStatus.PENDING.value,
            "attempts": 0,
            "last_error": None,
            "next_attempt_at": updated_at,
            "delivery_guarantee": str(metadata.get("delivery_guarantee") or OperatorDeliveryGuarantee.IMPORTANT.value),
            "metadata": metadata,
        }

    def _record_dead_letter(
        self,
        *,
        domain: str,
        source_entity_kind: str,
        source_entity_id: str,
        error_code: str | None,
        error_message: str | None,
        replayable: bool,
        recovery_command: str | None,
        artifact_path: str | None,
        correlation_id: str | None = None,
        run_id: str | None = None,
        mission_run_id: str | None = None,
        dispatch_id: str | None = None,
        channel_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        try:
            dead_letter_id = self.database.record_dead_letter(
                domain=domain,
                source_entity_kind=source_entity_kind,
                source_entity_id=source_entity_id,
                status="active",
                error_code=error_code,
                error_message=error_message,
                replayable=replayable,
                recovery_command=recovery_command,
                artifact_path=artifact_path,
                correlation_id=correlation_id,
                run_id=run_id,
                mission_run_id=mission_run_id,
                dispatch_id=dispatch_id,
                channel_event_id=channel_event_id,
                metadata=metadata,
            )
            self.database.record_trace_edge(
                parent_id=source_entity_id,
                parent_kind=source_entity_kind,
                child_id=dead_letter_id,
                child_kind=TraceEntityKind.DEAD_LETTER.value,
                relation=TraceRelationKind.DEAD_LETTERED_AS.value,
                metadata={"domain": domain, "replayable": replayable},
            )
            return dead_letter_id
        except Exception as exc:
            self.logger.log(
                "WARNING",
                "api_run_dead_letter_record_failed",
                domain=domain,
                source_entity_kind=source_entity_kind,
                source_entity_id=source_entity_id,
                error=str(exc),
            )
            return None

    def monitor_snapshot(self, *, limit: int = 5) -> dict[str, Any]:
        snapshot = self._build_monitor_snapshot(limit=limit)
        snapshot_path = self.path_policy.ensure_allowed_write(self.paths.api_runs_terminal_snapshot_path)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        return snapshot

    def _build_monitor_snapshot(self, *, limit: int = 5) -> dict[str, Any]:
        rows = self.database.fetchall(
            """
            SELECT
                q.run_request_id,
                q.mode,
                q.objective,
                q.branch_name,
                q.status,
                q.metadata_json,
                q.communication_mode,
                q.speech_policy,
                q.operator_language,
                q.audience,
                q.contract_id,
                q.created_at,
                q.updated_at,
                r.run_id,
                r.model,
                r.raw_output_path,
                r.result_artifact_path,
                r.estimated_cost_eur,
                c.status AS contract_status,
                c.summary AS contract_summary,
                c.founder_decision,
                c.estimated_cost_eur AS contract_estimated_cost
            FROM api_run_requests q
            LEFT JOIN api_run_results r ON r.run_request_id = q.run_request_id
            LEFT JOIN api_run_contracts c ON c.contract_id = q.contract_id
            ORDER BY q.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        run_ids = [str(row["run_id"]) for row in rows if row["run_id"]]
        placeholders = ",".join("?" for _ in run_ids)
        review_rows: list[Any] = []
        event_rows: list[Any] = []
        clarification_rows: list[Any] = []
        lifecycle_rows: list[Any] = []
        delivery_rows: list[Any] = []
        if run_ids:
            review_rows = self.database.fetchall(
                f"SELECT * FROM api_run_reviews WHERE run_id IN ({placeholders}) ORDER BY created_at DESC",
                tuple(run_ids),
            )
            event_rows = self.database.fetchall(
                f"SELECT * FROM api_run_events WHERE run_id IN ({placeholders}) ORDER BY created_at DESC",
                tuple(run_ids),
            )
            clarification_rows = self.database.fetchall(
                f"SELECT * FROM clarification_reports WHERE run_id IN ({placeholders}) ORDER BY created_at DESC",
                tuple(run_ids),
            )
            lifecycle_rows = self.database.fetchall(
                f"SELECT * FROM api_run_lifecycle_events WHERE run_id IN ({placeholders}) ORDER BY created_at DESC",
                tuple(run_ids),
            )
            lifecycle_event_ids = [str(row["lifecycle_event_id"]) for row in lifecycle_rows]
            if lifecycle_event_ids:
                lifecycle_placeholders = ",".join("?" for _ in lifecycle_event_ids)
                delivery_rows = self.database.fetchall(
                    (
                        "SELECT * FROM api_run_operator_deliveries "
                        f"WHERE lifecycle_event_id IN ({lifecycle_placeholders}) ORDER BY created_at DESC"
                    ),
                    tuple(lifecycle_event_ids),
                )
        cost_rows = self.database.fetchall(
            "SELECT estimated_cost_eur, created_at FROM api_run_results ORDER BY created_at DESC",
        )
        reviews: dict[str, Any] = {}
        for row in review_rows:
            reviews.setdefault(str(row["run_id"]), row)
        events: dict[str, Any] = {}
        for row in event_rows:
            events.setdefault(str(row["run_id"]), row)
        clarifications: dict[str, Any] = {}
        for row in clarification_rows:
            clarifications.setdefault(str(row["run_id"]), row)
        lifecycle_events: dict[str, Any] = {}
        for row in lifecycle_rows:
            lifecycle_events.setdefault(str(row["run_id"]), row)
        deliveries: dict[str, Any] = {}
        for row in delivery_rows:
            deliveries.setdefault(str(row["lifecycle_event_id"]), row)
        now = datetime.now(timezone.utc)
        day_key = now.date().isoformat()
        month_key = now.strftime("%Y-%m")
        daily_cost = 0.0
        monthly_cost = 0.0
        for row in cost_rows:
            created_at = str(row["created_at"])
            estimated_cost = float(row["estimated_cost_eur"])
            if created_at.startswith(day_key):
                daily_cost += estimated_cost
            if created_at.startswith(month_key):
                monthly_cost += estimated_cost
        items: list[dict[str, Any]] = []
        for row in rows:
            created_at = str(row["created_at"])
            estimated_cost = float(row["estimated_cost_eur"] or row["contract_estimated_cost"] or 0.0)
            run_id = str(row["run_id"]) if row["run_id"] else None
            review_row = reviews.get(run_id) if run_id else None
            event_row = events.get(run_id) if run_id else None
            clarification_row = clarifications.get(run_id) if run_id else None
            lifecycle_row = lifecycle_events.get(run_id) if run_id else None
            delivery_row = deliveries.get(str(lifecycle_row["lifecycle_event_id"])) if lifecycle_row else None
            request_metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            guard_reason = self._normalize_operator_guard_reason(request_metadata.get("operator_dashboard_reason"))
            clarification_metadata = json.loads(clarification_row["metadata_json"]) if clarification_row else {}
            delivery_payload = json.loads(delivery_row["payload_json"]) if delivery_row and delivery_row["payload_json"] else {}
            delivery_metadata = json.loads(delivery_row["metadata_json"]) if delivery_row and delivery_row["metadata_json"] else {}
            delivery_manifest = (
                delivery_payload.get("response_manifest")
                if isinstance(delivery_payload.get("response_manifest"), dict)
                else {}
            )
            delivery_contract = (
                delivery_payload.get("delivery_contract")
                if isinstance(delivery_payload.get("delivery_contract"), dict)
                else {}
            )
            no_loss_state = self._operator_delivery_no_loss_state(
                status=str(delivery_row["status"]) if delivery_row else None,
                last_error=str(delivery_row["last_error"]) if delivery_row and delivery_row["last_error"] else None,
                delivery_guarantee=str(delivery_metadata.get("delivery_guarantee") or delivery_payload.get("delivery_guarantee") or ""),
                visible_failure_required=bool(delivery_contract.get("visible_failure_required")),
                failure_notice_sent=bool(delivery_metadata.get("failure_notice_sent")),
                dead_letter_artifact_path=str(delivery_metadata.get("dead_letter_artifact_path") or "").strip() or None,
            )
            items.append(
                {
                    "run_id": run_id,
                    "run_request_id": str(row["run_request_id"]),
                    "mode": str(row["mode"]),
                    "branch_name": str(row["branch_name"]),
                    "status": str(row["status"]),
                    "contract_id": str(row["contract_id"]) if row["contract_id"] else None,
                    "contract_status": str(row["contract_status"]) if row["contract_status"] else None,
                    "founder_decision": str(row["founder_decision"]) if row["founder_decision"] else None,
                    "objective": str(row["objective"]),
                    "estimated_cost_eur": estimated_cost,
                    "created_at": created_at,
                    "review_verdict": str(review_row["verdict"]) if review_row else None,
                    "raw_output_path": row["raw_output_path"],
                    "structured_output_path": row["result_artifact_path"],
                    "communication_mode": str(row["communication_mode"] or CommunicationMode.BUILDER.value),
                    "speech_policy": str(row["speech_policy"] or self.execution_policy.default_run_speech_policy.value),
                    "operator_language": str(row["operator_language"] or self.execution_policy.operator_language),
                    "audience": str(row["audience"] or self.execution_policy.operator_audience.value),
                    "operator_guard_reason": guard_reason,
                    "operator_guard_raw": str(request_metadata.get("operator_dashboard_reason") or "unknown"),
                    "phase": str(event_row["phase"]) if event_row else None,
                    "machine_summary": str(event_row["machine_summary"]) if event_row else None,
                    "human_summary": str(event_row["human_summary"]) if event_row and event_row["human_summary"] else None,
                    "lifecycle_event_id": str(lifecycle_row["lifecycle_event_id"]) if lifecycle_row else None,
                    "lifecycle_event_kind": str(lifecycle_row["kind"]) if lifecycle_row else None,
                    "lifecycle_event_title": str(lifecycle_row["title"]) if lifecycle_row else None,
                    "lifecycle_event_summary": str(lifecycle_row["summary"]) if lifecycle_row else None,
                    "operator_channel_hint": str(lifecycle_row["channel_hint"]) if lifecycle_row else None,
                    "operator_delivery_status": str(delivery_row["status"]) if delivery_row else None,
                    "operator_delivery_attempts": int(delivery_row["attempts"]) if delivery_row else 0,
                    "operator_delivery_error": str(delivery_row["last_error"]) if delivery_row and delivery_row["last_error"] else None,
                    "operator_delivery_next_attempt_at": (
                        str(delivery_row["next_attempt_at"]) if delivery_row and delivery_row["next_attempt_at"] else None
                    ),
                    "operator_delivery_guarantee": (
                        str(delivery_metadata.get("delivery_guarantee") or delivery_payload.get("delivery_guarantee") or "")
                        if delivery_row
                        else None
                    ),
                    "operator_delivery_replayable": bool(delivery_metadata.get("replayable")) if delivery_row else False,
                    "operator_delivery_failure_notice_sent": (
                        bool(delivery_metadata.get("failure_notice_sent")) if delivery_row else False
                    ),
                    "operator_delivery_dead_letter_artifact_path": (
                        str(delivery_metadata.get("dead_letter_artifact_path") or "").strip() or None
                        if delivery_row
                        else None
                    ),
                    "operator_delivery_visible_failure_required": (
                        bool(delivery_contract.get("visible_failure_required")) if delivery_row else False
                    ),
                    "operator_delivery_must_persist": bool(delivery_contract.get("must_persist")) if delivery_row else False,
                    "operator_delivery_no_loss_state": no_loss_state,
                    "operator_delivery_response_mode": (
                        str(delivery_manifest.get("delivery_mode") or "").strip() or None
                        if delivery_row
                        else None
                    ),
                    "operator_delivery_attachment_count": (
                        len(delivery_manifest.get("attachments") or [])
                        if isinstance(delivery_manifest.get("attachments"), list)
                        else 0
                    ),
                    "clarification_report_id": str(clarification_row["report_id"]) if clarification_row else None,
                    "clarification_reason": str(clarification_row["cause"]) if clarification_row else None,
                    "clarification_question": str(clarification_row["question_for_founder"]) if clarification_row else None,
                    "clarification_recommended_contract_change": (
                        str(clarification_row["recommended_contract_change"]) if clarification_row else None
                    ),
                    "clarification_requires_reapproval": bool(clarification_row["requires_reapproval"]) if clarification_row else False,
                    "clarification_artifact_path": str(clarification_metadata.get("artifact_path") or "") if clarification_row else None,
                }
            )

        current_contract_row = self.database.fetchone(
            "SELECT * FROM api_run_contracts ORDER BY created_at DESC LIMIT 1",
        )
        current_contract = None
        if current_contract_row is not None:
            current_contract_metadata = json.loads(current_contract_row["metadata_json"]) if current_contract_row["metadata_json"] else {}
            current_contract = {
                "contract_id": str(current_contract_row["contract_id"]),
                "mode": str(current_contract_row["mode"]),
                "branch_name": str(current_contract_row["branch_name"]),
                "status": str(current_contract_row["status"]),
                "summary": str(current_contract_row["summary"]),
                "estimated_cost_eur": float(current_contract_row["estimated_cost_eur"]),
                "founder_decision": str(current_contract_row["founder_decision"]) if current_contract_row["founder_decision"] else None,
                "created_at": str(current_contract_row["created_at"]),
                "clarification_pending": bool(current_contract_metadata.get("clarification_pending")),
                "requires_reapproval": bool(current_contract_metadata.get("requires_reapproval")),
                "pending_clarification_report_id": str(current_contract_metadata.get("pending_clarification_report_id") or ""),
            }

        status_counts: dict[str, int] = {}
        review_counts: dict[str, int] = {}
        operator_delivery_counts: dict[str, int] = {}
        operator_delivery_health_counts: dict[str, int] = {}
        dead_letter_count = 0
        replayable_count = 0
        visible_failure_gap_count = 0
        artifact_delivery_count = 0
        for item in items:
            status_key = str(item.get("status") or "unknown")
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            review_key = str(item.get("review_verdict") or "pending")
            review_counts[review_key] = review_counts.get(review_key, 0) + 1
            delivery_key = str(item.get("operator_delivery_status") or "none")
            operator_delivery_counts[delivery_key] = operator_delivery_counts.get(delivery_key, 0) + 1
            health_key = str(item.get("operator_delivery_no_loss_state") or "none")
            operator_delivery_health_counts[health_key] = operator_delivery_health_counts.get(health_key, 0) + 1
            if item.get("operator_delivery_dead_letter_artifact_path"):
                dead_letter_count += 1
            if item.get("operator_delivery_replayable"):
                replayable_count += 1
            if health_key == "breach":
                visible_failure_gap_count += 1
            if item.get("operator_delivery_response_mode") == "artifact_summary":
                artifact_delivery_count += 1

        snapshot = {
            "schema_version": "2",
            "generated_at": now.isoformat(),
            "current_run": items[0] if items else None,
            "current_contract": current_contract,
            "budget": {
                "daily_spend_estimate_eur": round(daily_cost, 6),
                "monthly_spend_estimate_eur": round(monthly_cost, 6),
                "daily_soft_limit_eur": self.execution_policy.daily_soft_limit_eur,
                "monthly_limit_eur": self.execution_policy.monthly_limit_eur,
            },
            "status_counts": status_counts,
            "review_counts": review_counts,
            "operator_delivery_counts": operator_delivery_counts,
            "operator_delivery_health": {
                "status": "breach"
                if visible_failure_gap_count > 0
                else ("attention" if operator_delivery_health_counts.get("attention", 0) > 0 else "ok"),
                "counts": operator_delivery_health_counts,
                "dead_letter_count": dead_letter_count,
                "replayable_count": replayable_count,
                "visible_failure_gap_count": visible_failure_gap_count,
                "artifact_delivery_count": artifact_delivery_count,
            },
            "no_loss_audit": {
                "status": "breach"
                if visible_failure_gap_count > 0
                else ("attention" if dead_letter_count > 0 else "ok"),
                "silent_loss_risk_count": visible_failure_gap_count,
                "dead_letter_count": dead_letter_count,
                "replayable_count": replayable_count,
                "artifact_delivery_count": artifact_delivery_count,
            },
            "latest_runs": items,
        }
        return self._sanitize_monitor_snapshot(snapshot)

    def render_terminal_dashboard(self, *, limit: int = 5) -> str:
        snapshot = self.monitor_snapshot(limit=limit)
        width = max(88, min(shutil.get_terminal_size(fallback=(120, 40)).columns, 140))
        return "\n".join(self._render_terminal_frame(snapshot, width=width))

    def _normalize_operator_guard_reason(self, reason: Any) -> str:
        normalized = str(reason or "unknown").strip().lower()
        mapping = {
            "beacon_verified": "beacon",
            "recent_operator_beacon": "recent_beacon",
            "founder_approval_fallback": "founder_fallback",
            "dashboard_reachable": "dashboard_only",
            "dashboard_disabled": "dashboard_disabled",
        }
        return mapping.get(normalized, normalized or "unknown")

    @staticmethod
    def _operator_delivery_no_loss_state(
        *,
        status: str | None,
        last_error: str | None,
        delivery_guarantee: str | None,
        visible_failure_required: bool,
        failure_notice_sent: bool,
        dead_letter_artifact_path: str | None,
    ) -> str:
        normalized_status = str(status or "none").strip().lower()
        normalized_guarantee = str(delivery_guarantee or "").strip().lower()
        if normalized_status in {"", "none"}:
            return "none"
        if normalized_status == OperatorDeliveryStatus.DELIVERED.value:
            return "ok"
        if normalized_status == OperatorDeliveryStatus.PENDING.value and not last_error:
            return "queued"
        if normalized_status in {
            OperatorDeliveryStatus.FAILED.value,
            OperatorDeliveryStatus.SKIPPED.value,
            OperatorDeliveryStatus.EXPIRED.value,
        }:
            if dead_letter_artifact_path:
                return "attention"
            return "breach" if normalized_guarantee in {"must_notify", "must_persist"} else "attention"
        if visible_failure_required and last_error and not failure_notice_sent:
            return "breach"
        if last_error:
            return "attention"
        return "ok"

    def _is_legacy_api_run_branch(self, branch_name: Any) -> bool:
        normalized = str(branch_name or "").strip()
        if not normalized:
            return False
        return not normalized.startswith("codex/project-os-")

    def _sanitize_monitor_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        latest_runs = snapshot.get("latest_runs") or []
        visible_runs: list[dict[str, Any]] = []
        hidden_run_count = 0
        for item in latest_runs:
            if not isinstance(item, dict):
                continue
            annotated = dict(item)
            if self._is_legacy_api_run_branch(annotated.get("branch_name")):
                hidden_run_count += 1
                continue
            annotated["legacy_runtime_artifact"] = False
            visible_runs.append(annotated)

        current_run = snapshot.get("current_run")
        if isinstance(current_run, dict):
            if self._is_legacy_api_run_branch(current_run.get("branch_name")):
                current_run = None
            elif visible_runs:
                current_run = visible_runs[0]
            else:
                current_run = dict(current_run)
                current_run["legacy_runtime_artifact"] = False
        elif visible_runs:
            current_run = visible_runs[0]

        current_contract = snapshot.get("current_contract")
        hidden_contract_count = 0
        if isinstance(current_contract, dict):
            if self._is_legacy_api_run_branch(current_contract.get("branch_name")):
                hidden_contract_count = 1
                current_contract = None
            else:
                current_contract = dict(current_contract)
                current_contract["legacy_runtime_artifact"] = False

        status_counts: dict[str, int] = {}
        review_counts: dict[str, int] = {}
        operator_delivery_counts: dict[str, int] = {}
        operator_delivery_health_counts: dict[str, int] = {}
        dead_letter_count = 0
        replayable_count = 0
        visible_failure_gap_count = 0
        artifact_delivery_count = 0
        for item in visible_runs:
            status_key = str(item.get("status") or "unknown")
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            review_key = str(item.get("review_verdict") or "pending")
            review_counts[review_key] = review_counts.get(review_key, 0) + 1
            delivery_key = str(item.get("operator_delivery_status") or "none")
            operator_delivery_counts[delivery_key] = operator_delivery_counts.get(delivery_key, 0) + 1
            health_key = str(item.get("operator_delivery_no_loss_state") or "none")
            operator_delivery_health_counts[health_key] = operator_delivery_health_counts.get(health_key, 0) + 1
            if item.get("operator_delivery_dead_letter_artifact_path"):
                dead_letter_count += 1
            if item.get("operator_delivery_replayable"):
                replayable_count += 1
            if health_key == "breach":
                visible_failure_gap_count += 1
            if item.get("operator_delivery_response_mode") == "artifact_summary":
                artifact_delivery_count += 1

        sanitized = dict(snapshot)
        sanitized["current_run"] = current_run
        sanitized["current_contract"] = current_contract
        sanitized["latest_runs"] = visible_runs
        sanitized["status_counts"] = status_counts
        sanitized["review_counts"] = review_counts
        sanitized["operator_delivery_counts"] = operator_delivery_counts
        sanitized["operator_delivery_health"] = {
            "status": "breach"
            if visible_failure_gap_count > 0
            else ("attention" if operator_delivery_health_counts.get("attention", 0) > 0 else "ok"),
            "counts": operator_delivery_health_counts,
            "dead_letter_count": dead_letter_count,
            "replayable_count": replayable_count,
            "visible_failure_gap_count": visible_failure_gap_count,
            "artifact_delivery_count": artifact_delivery_count,
        }
        sanitized["no_loss_audit"] = {
            "status": "breach"
            if visible_failure_gap_count > 0
            else ("attention" if dead_letter_count > 0 else "ok"),
            "silent_loss_risk_count": visible_failure_gap_count,
            "dead_letter_count": dead_letter_count,
            "replayable_count": replayable_count,
            "artifact_delivery_count": artifact_delivery_count,
        }
        sanitized["legacy_hidden"] = {
            "run_count": hidden_run_count,
            "contract_count": hidden_contract_count,
            "reason": "branch_not_project_os",
        }
        return sanitized

    def _render_terminal_frame(self, snapshot: dict[str, Any], *, width: int) -> list[str]:
        width = max(88, width)
        lines = [
            "+" + "-" * (width - 2) + "+",
            self._terminal_line(
                f" Project OS API Monitor | snapshot {snapshot.get('generated_at') or 'n/a'}",
                width=width,
            ),
            "+" + "-" * (width - 2) + "+",
        ]
        budget = snapshot["budget"]
        budget_line = (
            f"Jour {budget['daily_spend_estimate_eur']:.4f}/{budget['daily_soft_limit_eur']:.2f} EUR"
            f" | Mois {budget['monthly_spend_estimate_eur']:.4f}/{budget['monthly_limit_eur']:.2f} EUR"
        )
        delivery_counts = snapshot.get("operator_delivery_counts") or {}
        delivery_line = ", ".join(f"{key}={value}" for key, value in sorted(delivery_counts.items())) or "aucune livraison"
        budget_lines = [budget_line, f"Livraisons operateur: {delivery_line}"]
        legacy_hidden = snapshot.get("legacy_hidden") or {}
        hidden_runs = int(legacy_hidden.get("run_count") or 0)
        hidden_contracts = int(legacy_hidden.get("contract_count") or 0)
        if hidden_runs or hidden_contracts:
            budget_lines.append(
                f"Hygiene runtime: runs legacy masques={hidden_runs}, contrats legacy masques={hidden_contracts}"
            )
        lines.extend(self._terminal_section("Budget", budget_lines, width=width))

        current = snapshot.get("current_run")
        if current:
            current_lines = [
                (
                    f"Run {current['run_id'] or 'en_attente'}"
                    f" | mode={current['mode']}"
                    f" | statut={current['status']}"
                    f" | phase={current['phase'] or 'preparation'}"
                ),
                (
                    f"Garde operateur: {current.get('operator_guard_reason') or 'unknown'}"
                    f" | revue={current['review_verdict'] or 'pending'}"
                    f" | contrat={current['contract_status'] or 'sans_contrat'}"
                ),
                (
                    f"Signal humain: {current.get('lifecycle_event_kind') or 'n/a'}"
                    f" | canal={current.get('operator_channel_hint') or 'n/a'}"
                    f" | livraison={current.get('operator_delivery_status') or 'none'}"
                ),
                f"Branche: {current['branch_name']}",
                f"Objectif: {current['objective']}",
                f"Resume machine: {current['machine_summary'] or 'aucun evenement live'}",
                (
                    f"Artefacts: raw={current['raw_output_path'] or 'n/a'}"
                    f" | structured={current['structured_output_path'] or 'n/a'}"
                ),
            ]
            if current["status"] == ApiRunStatus.CLARIFICATION_REQUIRED.value:
                current_lines.extend(
                    [
                        f"Raison de clarification: {current.get('clarification_reason') or 'n/a'}",
                        f"Question bloquante: {current.get('clarification_question') or 'n/a'}",
                        (
                            f"Contrat a appliquer: {current.get('clarification_recommended_contract_change') or 'n/a'}"
                            f" | re-go requis={'oui' if current.get('clarification_requires_reapproval') else 'non'}"
                        ),
                    ]
                )
        else:
            current_lines = ["Aucun run API enregistre pour le moment."]
        lines.extend(self._terminal_section("Run courant", current_lines, width=width))

        current_contract = snapshot.get("current_contract")
        if current_contract:
            contract_lines = [
                (
                    f"Contrat {current_contract['contract_id']}"
                    f" | statut={current_contract['status']}"
                    f" | decision={current_contract['founder_decision'] or 'en_attente'}"
                ),
                f"Branche: {current_contract['branch_name']}",
                f"Objectif: {current_contract['summary']}",
            ]
            if current_contract.get("clarification_pending"):
                contract_lines.append("Clarification en attente: le contrat doit etre amende puis reapprouve.")
        else:
            contract_lines = ["Aucun contrat recent."]
        lines.extend(self._terminal_section("Contrat courant", contract_lines, width=width))

        recent_lines: list[str] = []
        for item in snapshot["latest_runs"]:
            recent_lines.append(
                self._fit_terminal_text(
                    (
                        f"{item['created_at']} | {item['status']} | {item['mode']} | "
                        f"guard={item.get('operator_guard_reason') or 'unknown'} | "
                        f"phase={item['phase'] or 'preparation'} | "
                        f"review={item['review_verdict'] or 'pending'} | "
                        f"{item['branch_name']}"
                    ),
                    width - 6,
                )
            )
        if not recent_lines:
            recent_lines.append("Aucun run API pour le moment.")
        lines.extend(self._terminal_section("Derniers runs", recent_lines, width=width))
        lines.append("+" + "-" * (width - 2) + "+")
        return lines

    def _terminal_section(self, title: str, body_lines: list[str], *, width: int) -> list[str]:
        lines = [self._terminal_line(f" [{title}] ", width=width)]
        for body in body_lines:
            wrapped = textwrap.wrap(
                str(body or ""),
                width=max(20, width - 6),
                break_long_words=False,
                break_on_hyphens=False,
            ) or [""]
            for item in wrapped:
                lines.append(self._terminal_line(f" {item}", width=width))
        lines.append("+" + "-" * (width - 2) + "+")
        return lines

    def _terminal_line(self, content: str, *, width: int) -> str:
        inner_width = max(10, width - 4)
        clipped = self._fit_terminal_text(content, inner_width)
        return f"| {clipped:<{inner_width}} |"

    def _fit_terminal_text(self, content: str, width: int) -> str:
        text = str(content or "")
        if len(text) <= width:
            return text
        if width <= 3:
            return text[:width]
        return text[: width - 3] + "..."

    def get_context_pack(self, context_pack_id: str) -> ContextPack:
        row = self.database.fetchone("SELECT * FROM context_packs WHERE context_pack_id = ?", (context_pack_id,))
        if row is None:
            raise KeyError(f"Unknown context_pack_id: {context_pack_id}")
        sources = [
            ContextSource(
                source_id=str(item["source_id"]),
                path=str(item["path"]),
                kind=str(item["kind"]),
                content=str(item["content"]),
                truncated=bool(item.get("truncated")),
                metadata=dict(item.get("metadata", {})),
            )
            for item in json.loads(row["source_refs_json"])
        ]
        return ContextPack(
            context_pack_id=str(row["context_pack_id"]),
            mode=ApiRunMode(str(row["mode"])),
            objective=str(row["objective"]),
            branch_name=str(row["branch_name"]),
            target_profile=row["target_profile"],
            source_refs=sources,
            repo_state=json.loads(row["repo_state_json"]),
            runtime_facts=json.loads(row["runtime_facts_json"]),
            constraints=json.loads(row["constraints_json"]),
            acceptance_criteria=json.loads(row["acceptance_criteria_json"]),
            skill_tags=json.loads(row["skill_tags_json"]),
            artifact_path=row["artifact_path"],
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
        )

    def get_prompt_template(self, prompt_template_id: str) -> MegaPromptTemplate:
        row = self.database.fetchone(
            "SELECT * FROM mega_prompt_templates WHERE prompt_template_id = ?",
            (prompt_template_id,),
        )
        if row is None:
            raise KeyError(f"Unknown prompt_template_id: {prompt_template_id}")
        return MegaPromptTemplate(
            prompt_template_id=str(row["prompt_template_id"]),
            context_pack_id=str(row["context_pack_id"]),
            mode=ApiRunMode(str(row["mode"])),
            agent_identity=str(row["agent_identity"]),
            skill_tags=json.loads(row["skill_tags_json"]),
            output_contract=json.loads(row["output_contract_json"]),
            rendered_prompt=str(row["rendered_prompt"]),
            model=str(row["model"]),
            reasoning_effort=str(row["reasoning_effort"]),
            artifact_path=row["artifact_path"],
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
        )

    def get_run_request(self, run_request_id: str) -> ApiRunRequest:
        row = self.database.fetchone("SELECT * FROM api_run_requests WHERE run_request_id = ?", (run_request_id,))
        if row is None:
            raise KeyError(f"Unknown run_request_id: {run_request_id}")
        return ApiRunRequest(
            run_request_id=str(row["run_request_id"]),
            context_pack_id=str(row["context_pack_id"]),
            prompt_template_id=str(row["prompt_template_id"]),
            mode=ApiRunMode(str(row["mode"])),
            objective=str(row["objective"]),
            branch_name=str(row["branch_name"]),
            target_profile=row["target_profile"],
            mission_chain_id=str(row["mission_chain_id"]) if row["mission_chain_id"] else None,
            mission_step_index=int(row["mission_step_index"]) if row["mission_step_index"] is not None else None,
            skill_tags=json.loads(row["skill_tags_json"]),
            expected_outputs=json.loads(row["expected_outputs_json"]),
            coding_lane=str(row["coding_lane"]),
            desktop_lane=str(row["desktop_lane"]),
            communication_mode=CommunicationMode(str(row["communication_mode"] or CommunicationMode.BUILDER.value)),
            speech_policy=RunSpeechPolicy(str(row["speech_policy"] or self.execution_policy.default_run_speech_policy.value)),
            operator_language=str(row["operator_language"] or self.execution_policy.operator_language),
            audience=OperatorAudience(str(row["audience"] or self.execution_policy.operator_audience.value)),
            run_contract_required=bool(row["run_contract_required"]) if row["run_contract_required"] is not None else self.execution_policy.run_contract_required,
            contract_id=str(row["contract_id"]) if row["contract_id"] else None,
            status=ApiRunStatus(str(row["status"])),
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get_run_contract(self, contract_id: str) -> RunContract:
        row = self.database.fetchone("SELECT * FROM api_run_contracts WHERE contract_id = ?", (contract_id,))
        if row is None:
            raise KeyError(f"Unknown contract_id: {contract_id}")
        return RunContract(
            contract_id=str(row["contract_id"]),
            context_pack_id=str(row["context_pack_id"]),
            prompt_template_id=str(row["prompt_template_id"]),
            mode=ApiRunMode(str(row["mode"])),
            objective=str(row["objective"]),
            branch_name=str(row["branch_name"]),
            target_profile=row["target_profile"],
            model=str(row["model"]),
            reasoning_effort=str(row["reasoning_effort"]),
            communication_mode=CommunicationMode(str(row["communication_mode"])),
            speech_policy=RunSpeechPolicy(str(row["speech_policy"])),
            operator_language=str(row["operator_language"]),
            audience=OperatorAudience(str(row["audience"])),
            expected_outputs=json.loads(row["expected_outputs_json"]),
            summary=str(row["summary"]),
            non_goals=json.loads(row["non_goals_json"]),
            success_criteria=json.loads(row["success_criteria_json"]),
            estimated_cost_eur=float(row["estimated_cost_eur"]),
            founder_decision=str(row["founder_decision"]) if row["founder_decision"] else None,
            founder_decision_at=str(row["founder_decision_at"]) if row["founder_decision_at"] else None,
            status=RunContractStatus(str(row["status"])),
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get_run_result(self, run_id: str) -> ApiRunResult:
        row = self.database.fetchone("SELECT * FROM api_run_results WHERE run_id = ?", (run_id,))
        if row is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        return ApiRunResult(
            run_id=str(row["run_id"]),
            run_request_id=str(row["run_request_id"]),
            model=str(row["model"]),
            mode=ApiRunMode(str(row["mode"])),
            status=ApiRunStatus(str(row["status"])),
            structured_output=json.loads(row["structured_output_json"]),
            raw_output_path=row["raw_output_path"],
            prompt_artifact_path=row["prompt_artifact_path"],
            result_artifact_path=row["result_artifact_path"],
            estimated_cost_eur=float(row["estimated_cost_eur"]),
            usage=json.loads(row["usage_json"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _call_openai(self, request: ApiRunRequest, prompt_template: MegaPromptTemplate) -> Any:
        api_key = self.secret_resolver.get_required("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        return client.responses.create(
            model=prompt_template.model,
            reasoning={"effort": prompt_template.reasoning_effort},
            input=prompt_template.rendered_prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "project_os_api_run_result",
                    "schema": self._output_schema(),
                    "strict": True,
                    "description": "Structured output for a Project OS mega run",
                },
                "verbosity": "high",
            },
            store=False,
            metadata={
                "run_request_id": request.run_request_id,
                "mode": request.mode.value,
                "branch_name": request.branch_name,
            },
        )

    def _call_reviewer(self, result: ApiRunResult, context_pack: ContextPack) -> ApiRunReview:
        if Anthropic is None:
            raise RuntimeError("anthropic package is not installed")
        self.logger.log(
            "INFO",
            "api_run_review_started",
            run_id=result.run_id,
            mode=result.mode.value,
            reviewer_model=REVIEWER_MODEL,
        )
        api_key = self.secret_resolver.get_required("ANTHROPIC_API_KEY")
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=REVIEWER_MODEL,
            max_tokens=700,
            temperature=0,
            system=self._reviewer_system_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": self._reviewer_user_prompt(result=result, context_pack=context_pack),
                }
            ],
        )
        raw_payload = response.model_dump() if hasattr(response, "model_dump") else {"repr": repr(response)}
        review_payload = self._parse_structured_output_text(self._extract_text_blocks(response))
        verdict = self._review_verdict(review_payload)
        usage = self._extract_anthropic_usage(response)
        summary = str(review_payload.get("summary") or "").strip()
        recommendation = str(review_payload.get("recommendation") or "").strip()
        issues_found = self._coerce_non_negative_int(review_payload.get("issues_found"), field_name="issues_found")
        critical = self._coerce_non_negative_int(review_payload.get("critical"), field_name="critical")
        high = self._coerce_non_negative_int(review_payload.get("high"), field_name="high")
        estimated_cost = self._estimate_cost_eur(
            model=str(raw_payload.get("model") or REVIEWER_MODEL),
            usage=usage,
        )
        review = ApiRunReview(
            review_id=new_id("run_review"),
            run_id=result.run_id,
            verdict=verdict,
            reviewer=str(raw_payload.get("model") or REVIEWER_MODEL),
            findings=self._review_findings(
                verdict=verdict,
                summary=summary,
                issues_found=issues_found,
                critical=critical,
                high=high,
            ),
            accepted_changes=[],
            followup_actions=[recommendation] if recommendation else [],
            metadata={
                "type": "review_result",
                "source": "claude_api",
                "context_pack_id": context_pack.context_pack_id,
                "mode": context_pack.mode.value,
                "branch_name": context_pack.branch_name,
                "objective": context_pack.objective,
                "files_included": [item.path for item in context_pack.source_refs],
                "acceptance_criteria": self._review_acceptance_criteria(context_pack),
                "issues_found": issues_found,
                "critical": critical,
                "high": high,
                "summary": summary,
                "recommendation": recommendation,
                "usage": usage,
                "estimated_cost_eur": estimated_cost,
            },
        )
        self._store_run_review(review)
        self.logger.log(
            "INFO",
            "api_run_review_completed",
            run_id=result.run_id,
            review_id=review.review_id,
            verdict=review.verdict.value,
            reviewer=review.reviewer,
            estimated_cost_eur=estimated_cost,
            issues_found=issues_found,
            critical=critical,
            high=high,
        )
        return review

    def _call_translator(
        self,
        *,
        event: RunLifecycleEvent,
        result: ApiRunResult | None = None,
        review: ApiRunReview | None = None,
    ) -> str | None:
        """Traduit un lifecycle event en message Discord francais simple.

        Retourne None si l'evenement doit etre filtre (bruit).
        Retourne le message traduit sinon (max 3 lignes, francais simple, pas de code).
        """
        filter_reason = self._translator_filter_reason(event)
        if filter_reason is not None:
            self.logger.log(
                "INFO",
                "translator_filtered",
                event_id=event.lifecycle_event_id,
                kind=event.kind.value,
                reason=filter_reason,
            )
            return None

        fallback_message = self._translator_fallback_message(event=event, review=review)
        try:
            if Anthropic is None:
                raise RuntimeError("anthropic package is not installed")
            api_key = self.secret_resolver.get_required("ANTHROPIC_API_KEY")
            client = Anthropic(api_key=api_key)
            message = client.messages.create(
                model=TRANSLATOR_MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": self._translator_prompt(event=event, result=result, review=review)}],
            )
            translated_text = self._extract_text_blocks(message)
            final_message = self._finalize_translated_message(translated_text, fallback_message=fallback_message)
            usage = self._extract_anthropic_usage(message)
            estimated_cost_eur = self._estimate_cost_eur(model=TRANSLATOR_MODEL, usage=usage)
            self.logger.log(
                "INFO",
                "translator_completed",
                event_id=event.lifecycle_event_id,
                kind=event.kind.value,
                model=TRANSLATOR_MODEL,
                estimated_cost_eur=estimated_cost_eur,
                line_count=len(final_message.splitlines()),
            )
            return final_message
        except Exception as exc:
            self.logger.log(
                "WARNING",
                "translator_fallback_used",
                event_id=event.lifecycle_event_id,
                kind=event.kind.value,
                error=str(exc),
            )
            return fallback_message

    def _guardian_pre_spend_check(
        self,
        *,
        request: ApiRunRequest,
        prompt_template: MegaPromptTemplate,
    ) -> tuple[bool, str | None]:
        """Verifie budget et boucles AVANT un appel API couteux.

        Returns:
            (True, None) si le run peut continuer.
            (False, reason) si le run doit etre bloque.
        """
        if request.metadata.get("guardian_override") is True:
            self.logger.log(
                "WARNING",
                "guardian_override_active",
                run_request_id=request.run_request_id,
                branch_name=request.branch_name,
                mode=request.mode.value,
            )
            return True, None

        estimated_cost = self._estimate_cost_hint(prompt_template.model, prompt_template.reasoning_effort, request.mode)
        self.logger.log(
            "INFO",
            "guardian_pre_spend_check_started",
            run_request_id=request.run_request_id,
            branch_name=request.branch_name,
            mode=request.mode.value,
            estimated_cost_eur=estimated_cost,
        )

        try:
            daily_limit = float(getattr(self.execution_policy, "daily_budget_limit_eur", 5.0))
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            budget_row = self.database.fetchone(
                (
                    "SELECT COALESCE(SUM(estimated_cost_eur), 0.0) as daily_spend "
                    "FROM api_run_results WHERE created_at >= ? AND status != 'failed'"
                ),
                (today_start,),
            )
            daily_spend = float(budget_row["daily_spend"]) if budget_row else 0.0
            self.logger.log(
                "INFO",
                "guardian_budget_checked",
                run_request_id=request.run_request_id,
                daily_spend_eur=daily_spend,
                estimated_cost_eur=estimated_cost,
                daily_limit_eur=daily_limit,
            )
            if daily_spend + estimated_cost > daily_limit:
                reason = (
                    f"budget_exceeded:daily_spend={daily_spend:.2f}"
                    f"+estimated={estimated_cost:.2f}>limit={daily_limit:.2f}"
                )
                self.logger.log(
                    "WARNING",
                    "guardian_blocked_budget",
                    run_request_id=request.run_request_id,
                    reason=reason,
                )
                return False, reason

            window_hours = int(getattr(self.execution_policy, "loop_detection_window_hours", 2))
            threshold = int(getattr(self.execution_policy, "loop_detection_threshold", 3))
            window_start = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
            loop_row = self.database.fetchone(
                "SELECT COUNT(*) as loop_count FROM api_run_requests WHERE branch_name = ? AND mode = ? AND created_at >= ?",
                (request.branch_name, request.mode.value, window_start),
            )
            loop_count = int(loop_row["loop_count"]) if loop_row else 0
            self.logger.log(
                "INFO",
                "guardian_loop_checked",
                run_request_id=request.run_request_id,
                branch_name=request.branch_name,
                mode=request.mode.value,
                loop_count=loop_count,
                window_hours=window_hours,
                threshold=threshold,
            )
            if loop_count >= threshold:
                reason = (
                    f"loop_detected:branch={request.branch_name},mode={request.mode.value},"
                    f"count={loop_count},window={window_hours}h"
                )
                self.logger.log(
                    "WARNING",
                    "guardian_blocked_loop",
                    run_request_id=request.run_request_id,
                    reason=reason,
                )
                return False, reason
        except Exception as exc:
            self.logger.log(
                "WARNING",
                "guardian_pre_spend_fail_open",
                run_request_id=request.run_request_id,
                error=str(exc),
            )
            return True, None

        self.logger.log(
            "INFO",
            "guardian_pre_spend_allowed",
            run_request_id=request.run_request_id,
            branch_name=request.branch_name,
            mode=request.mode.value,
            estimated_cost_eur=estimated_cost,
        )
        return True, None

    @staticmethod
    def _preview_text(value: Any, *, max_chars: int = 16_000) -> str | None:
        text = str(value or "")
        if not text:
            return None
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars].rstrip()}...[truncated]"

    @staticmethod
    def _infer_provider_from_model(model_name: str | None) -> str | None:
        candidate = str(model_name or "").strip().lower()
        if not candidate:
            return None
        if candidate.startswith("claude"):
            return "anthropic"
        if candidate.startswith(("gpt", "o1", "o3", "o4")):
            return "openai"
        return None

    def _quarantine_api_run_output(
        self,
        *,
        reason_code: str,
        run_id: str | None,
        run_request_id: str | None,
        model: str | None,
        raw_payload: dict[str, Any],
        output_text: str | None,
        error: str,
    ) -> str:
        provider = str(raw_payload.get("provider") or raw_payload.get("model_provider") or "").strip() or self._infer_provider_from_model(
            str(raw_payload.get("model") or model or "").strip() or None
        )
        source_entity_id = str(run_id or run_request_id or "unknown_api_run").strip()
        quarantine_id = self.database.record_output_quarantine(
            source_system="api_runs",
            source_entity_kind=TraceEntityKind.API_RUN.value,
            source_entity_id=source_entity_id,
            reason_code=reason_code,
            provider=provider,
            model=str(raw_payload.get("model") or model or "").strip() or None,
            run_id=str(run_id or "").strip() or None,
            record_locator=str(run_request_id or run_id or "").strip() or None,
            payload={
                "raw_payload": raw_payload,
                "output_text_preview": self._preview_text(output_text),
            },
            metadata={
                "error": error,
                "run_request_id": str(run_request_id or "").strip() or None,
            },
        )
        self.database.record_trace_edge(
            parent_id=source_entity_id,
            parent_kind=TraceEntityKind.API_RUN.value,
            child_id=quarantine_id,
            child_kind=TraceEntityKind.OUTPUT_QUARANTINE.value,
            relation=TraceRelationKind.QUARANTINED_AS.value,
            metadata={"reason_code": reason_code},
        )
        self.logger.log(
            "WARNING",
            "api_run_output_quarantined",
            quarantine_id=quarantine_id,
            reason_code=reason_code,
            run_id=run_id,
            run_request_id=run_request_id,
            provider=provider,
            model=str(raw_payload.get("model") or model or "").strip() or None,
        )
        return quarantine_id

    def _normalize_response_payload(
        self,
        response_payload: Any,
        *,
        run_id: str | None = None,
        run_request_id: str | None = None,
        model: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if isinstance(response_payload, dict):
            raw_payload = dict(response_payload)
            output_text = raw_payload.get("output_text")
        else:
            raw_payload = response_payload.model_dump() if hasattr(response_payload, "model_dump") else {"repr": repr(response_payload)}
            output_text = getattr(response_payload, "output_text", None)
        if not output_text:
            self._quarantine_api_run_output(
                reason_code=OutputQuarantineReason.MISSING_OUTPUT_TEXT.value,
                run_id=run_id,
                run_request_id=run_request_id,
                model=model,
                raw_payload=raw_payload,
                output_text=None,
                error="Responses API returned no output_text",
            )
            raise RuntimeError("Responses API returned no output_text")
        try:
            structured_output = self._parse_structured_output_text(str(output_text))
        except RuntimeError as exc:
            reason_code = OutputQuarantineReason.INVALID_STRUCTURED_PAYLOAD.value
            if "invalid JSON" in str(exc):
                reason_code = OutputQuarantineReason.INVALID_JSON.value
            elif "non-object" in str(exc):
                reason_code = OutputQuarantineReason.NON_OBJECT_PAYLOAD.value
            self._quarantine_api_run_output(
                reason_code=reason_code,
                run_id=run_id,
                run_request_id=run_request_id,
                model=model,
                raw_payload=raw_payload,
                output_text=str(output_text),
                error=str(exc),
            )
            raise
        usage = raw_payload.get("usage")
        if usage is None and hasattr(response_payload, "usage") and getattr(response_payload, "usage") is not None:
            usage_obj = getattr(response_payload, "usage")
            usage = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else dict(usage_obj)
        return structured_output, raw_payload, usage or {}

    def _parse_structured_output_text(self, output_text: str) -> dict[str, Any]:
        text = output_text.strip()
        decoder = json.JSONDecoder()
        try:
            parsed, _ = decoder.raw_decode(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        if "```json" in text:
            start = text.find("```json") + len("```json")
            end = text.find("```", start)
            if end > start:
                fenced = text[start:end].strip()
                try:
                    parsed, _ = decoder.raw_decode(fenced)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed

        for marker in ("{", "["):
            start = text.find(marker)
            if start >= 0:
                try:
                    parsed, _ = decoder.raw_decode(text[start:])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed

        if text.find("{") >= 0 or text.find("[") >= 0 or "```json" in text:
            raise RuntimeError("Responses API returned invalid JSON in structured output")
        raise RuntimeError("Responses API returned a non-object structured payload")

    def _reviewer_system_prompt(self) -> str:
        return textwrap.dedent(
            """
            You are the cross-model reviewer for Project OS.
            Audit a GPT-produced structured result against the current architecture, interfaces, risks, and acceptance criteria.
            Be strict, technical, and terse.
            Return exactly one JSON object and nothing else.
            Allowed verdicts: "accepted", "accepted_with_reserves", "needs_revision", "rejected", "needs_clarification".
            Use "critical" for P0 blockers and "high" for P1 blockers.
            Use "needs_revision" when the result is directionally correct but must be revised before integration.
            If the provided context is insufficient for a reliable verdict, use "needs_clarification".
            """
        ).strip()

    def _reviewer_user_prompt(self, *, result: ApiRunResult, context_pack: ContextPack) -> str:
        source_paths = [item.path for item in context_pack.source_refs]
        context_summary = {
            "run_id": result.run_id,
            "mode": context_pack.mode.value,
            "objective": context_pack.objective,
            "branch": context_pack.branch_name,
            "included_files_count": len(source_paths),
            "included_files": source_paths,
        }
        return textwrap.dedent(
            f"""
            Review the following Project OS run result.

            Quality gates:
            {self._render_list(self._review_quality_gates())}

            Mode-specific acceptance criteria:
            {self._render_list(self._review_acceptance_criteria(context_pack))}

            Context pack summary:
            {json.dumps(context_summary, ensure_ascii=True, indent=2, sort_keys=True)}

            Structured output under review:
            {json.dumps(result.structured_output, ensure_ascii=True, indent=2, sort_keys=True)}

            Return JSON with this exact schema:
            {{
              "verdict": "accepted" | "accepted_with_reserves" | "needs_revision" | "rejected" | "needs_clarification",
              "issues_found": <int>,
              "critical": <int>,
              "high": <int>,
              "summary": "<1-2 technical sentences>",
              "recommendation": "<next action>"
            }}
            """
        ).strip()

    def _review_quality_gates(self) -> list[str]:
        return [
            "Coherence: the result must fit the current architecture and repository conventions.",
            "Interfaces: declared inputs, outputs, and contracts must stay internally consistent.",
            "Risks: flag security, regression, data-loss, and state-corruption risks.",
            "Tests: expected tests must cover the primary behavior and failure paths.",
            "Loops: reject unbounded loops, recursion hazards, or retry storms.",
            "Degradation: reject outcomes that reduce quality versus the existing implementation.",
        ]

    def _review_acceptance_criteria(self, context_pack: ContextPack) -> list[str]:
        mode_specific: dict[ApiRunMode, list[str]] = {
            ApiRunMode.AUDIT: [
                "All identified zones are covered.",
                "Severity assignments remain coherent across P0, P1, and P2.",
                "Recommendations are actionable.",
            ],
            ApiRunMode.DESIGN: [
                "Interfaces define inputs, outputs, and error paths.",
                "Dependencies are explicit.",
                "Alternatives are documented.",
            ],
            ApiRunMode.PATCH_PLAN: [
                "Every target file is identified.",
                "The modification order is explicit.",
                "Regression risks are evaluated.",
            ],
            ApiRunMode.GENERATE_PATCH: [
                "The code should compile and tests should pass.",
                "Project conventions must be respected.",
                "No dead code or unresolved TODOs remain.",
            ],
        }
        combined = list(mode_specific.get(context_pack.mode, []))
        for item in context_pack.acceptance_criteria:
            candidate = str(item).strip()
            if candidate and candidate not in combined:
                combined.append(candidate)
        return combined

    def _render_list(self, items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- None"

    def _extract_text_blocks(self, response_payload: Any) -> str:
        content = getattr(response_payload, "content", None)
        if content is None and isinstance(response_payload, dict):
            content = response_payload.get("content")
        blocks: list[str] = []
        for item in content or []:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    blocks.append(str(item["text"]))
                continue
            if getattr(item, "type", None) == "text" and getattr(item, "text", None):
                blocks.append(str(item.text))
        if not blocks:
            raise RuntimeError("Anthropic Messages API returned no text content")
        return "\n".join(blocks).strip()

    def _extract_anthropic_usage(self, response_payload: Any) -> dict[str, Any]:
        usage_obj = getattr(response_payload, "usage", None)
        if usage_obj is None and isinstance(response_payload, dict):
            usage_obj = response_payload.get("usage")
        if usage_obj is None:
            return {}
        if hasattr(usage_obj, "model_dump"):
            dumped = usage_obj.model_dump()
            if isinstance(dumped, dict):
                return dumped
        if isinstance(usage_obj, dict):
            return dict(usage_obj)
        usage: dict[str, Any] = {}
        for field in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            value = getattr(usage_obj, field, None)
            if value is not None:
                usage[field] = value
        return usage

    def _review_verdict(self, review_payload: dict[str, Any]) -> ApiRunReviewVerdict:
        raw_verdict = str(review_payload.get("verdict") or "").strip().lower()
        mapping = {
            ApiRunReviewVerdict.ACCEPTED.value: ApiRunReviewVerdict.ACCEPTED,
            ApiRunReviewVerdict.ACCEPTED_WITH_RESERVES.value: ApiRunReviewVerdict.ACCEPTED_WITH_RESERVES,
            ApiRunReviewVerdict.NEEDS_REVISION.value: ApiRunReviewVerdict.NEEDS_REVISION,
            ApiRunReviewVerdict.REJECTED.value: ApiRunReviewVerdict.REJECTED,
            ApiRunReviewVerdict.NEEDS_CLARIFICATION.value: ApiRunReviewVerdict.NEEDS_CLARIFICATION,
        }
        verdict = mapping.get(raw_verdict)
        if verdict is None:
            raise RuntimeError(f"Anthropic review returned an unsupported verdict: {raw_verdict or 'missing'}")
        return verdict

    def _review_findings(
        self,
        *,
        verdict: ApiRunReviewVerdict,
        summary: str,
        issues_found: int,
        critical: int,
        high: int,
    ) -> list[str]:
        findings: list[str] = []
        if summary and (issues_found > 0 or verdict is not ApiRunReviewVerdict.ACCEPTED):
            findings.append(summary)
        if critical > 0:
            findings.append(f"Critical blockers reported: {critical}.")
        if high > 0:
            findings.append(f"High-severity blockers reported: {high}.")
        return findings

    def _coerce_non_negative_int(self, value: Any, *, field_name: str) -> int:
        try:
            coerced = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Anthropic review returned an invalid integer for {field_name}") from exc
        if coerced < 0:
            raise RuntimeError(f"Anthropic review returned a negative integer for {field_name}")
        return coerced

    def _merge_usage(self, generation_usage: dict[str, Any], review_usage: dict[str, Any]) -> dict[str, Any]:
        merged = {
            "input_tokens": int(generation_usage.get("input_tokens") or 0) + int(review_usage.get("input_tokens") or 0),
            "output_tokens": int(generation_usage.get("output_tokens") or 0) + int(review_usage.get("output_tokens") or 0),
            "generation": dict(generation_usage),
            "review": dict(review_usage),
        }
        for key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
            total = int(generation_usage.get(key) or 0) + int(review_usage.get(key) or 0)
            if total:
                merged[key] = total
        return merged

    def _translator_filter_reason(self, event: RunLifecycleEvent) -> str | None:
        if event.kind is RunLifecycleEventKind.RUN_STARTED:
            return "run_started_noise"
        if event.kind is RunLifecycleEventKind.CONTRACT_APPROVED:
            return "contract_approved_noise"
        if event.kind is RunLifecycleEventKind.CONTRACT_REJECTED:
            return "contract_rejected_already_handled"
        auto_retry_in_progress = str(event.metadata.get("auto_retry_in_progress") or "").strip().lower() in {"1", "true", "yes"}
        if event.kind is RunLifecycleEventKind.RUN_FAILED and auto_retry_in_progress:
            return "run_failed_retry_in_progress"
        if event.kind is RunLifecycleEventKind.BUDGET_ALERT:
            percent = float(event.metadata.get("budget_percent") or event.metadata.get("budget_usage_percent") or 0.0)
            if percent < 80.0:
                return "budget_below_notification_threshold"
        return None

    def _translator_prompt(
        self,
        *,
        event: RunLifecycleEvent,
        result: ApiRunResult | None = None,
        review: ApiRunReview | None = None,
    ) -> str:
        files_changed = 0
        if result is not None:
            files_changed = len(result.structured_output.get("files_to_change") or [])
        review_metadata = dict(review.metadata) if review is not None else {}
        prompt_payload = {
            "event_kind": event.kind.value,
            "title": event.title,
            "machine_summary": event.summary,
            "branch_name": event.branch_name,
            "mode": event.mode.value if event.mode else None,
            "estimated_cost_eur": result.estimated_cost_eur if result is not None else event.metadata.get("estimated_cost_eur"),
            "files_changed": files_changed or event.metadata.get("files_changed"),
            "blocking_question": event.blocking_question,
            "recommended_action": event.recommended_action,
            "review_verdict": review.verdict.value if review is not None else event.metadata.get("review_verdict"),
            "review_summary": review_metadata.get("summary") if review_metadata else None,
            "review_recommendation": review_metadata.get("recommendation") if review_metadata else None,
            "issues_found": review_metadata.get("issues_found") if review_metadata else None,
            "critical": review_metadata.get("critical") if review_metadata else None,
            "high": review_metadata.get("high") if review_metadata else None,
            "requires_reapproval": event.requires_reapproval,
        }
        return textwrap.dedent(
            f"""
            Traduis ce signal machine Project OS en message Discord pour le fondateur.

            Regles absolues:
            - Francais simple, max 3 lignes
            - Pas de code, pas de chemin de fichier, pas de JSON
            - Pas de jargon technique
            - Le fondateur ne code pas
            - Si une information manque, n'invente pas

            Signal:
            {json.dumps(prompt_payload, ensure_ascii=True, indent=2, sort_keys=True)}

            Templates Discord a imiter:
            1. Run complete
            [branche] termine — [decision en 1 phrase].
            [nb fichiers] fichiers, [cout]EUR. Review dispo au retour.

            2. Clarification requise
            Question sur [branche] —
            [question en francais simple].
            A) [option A] B) [option B]
            [urgence]. Si tu reponds pas je fais [fallback].

            3. Run echoue
            [branche] echoue — [raison simple].
            [action requise ou "Aucune action requise"].

            4. Contrat propose
            Nouveau lot propose — [objectif en 1 phrase].
            Cout estime: [montant]EUR. On lance ?

            5. Budget alert
            Budget jour a [pourcentage]% — [depense]EUR sur [limite]EUR.
            [consequence simple].

            6. Review terminee
            Review de [branche] — [verdict en 1 phrase].
            [detail principal si pertinent].
            [prochaine action].

            Traduis en francais simple, max 3 lignes, pas de code, pas de chemin de fichier, pas de JSON.
            """
        ).strip()

    def _finalize_translated_message(self, translated_text: str, *, fallback_message: str) -> str:
        cleaned = translated_text.replace("```", "").replace("`", "").strip()
        lines = [line.strip(" -") for line in cleaned.splitlines() if line.strip()]
        message = "\n".join(lines[:3]).strip()
        if not message:
            return fallback_message
        if self._translated_message_looks_unsafe(message):
            return fallback_message
        return message

    def _translated_message_looks_unsafe(self, message: str) -> bool:
        lowered = message.lower()
        if any(marker in lowered for marker in ("src/", "project_os_core", "```")):
            return True
        if "{" in message or "}" in message:
            return True
        if re.search(r"[a-zA-Z]:\\\\", message):
            return True
        if re.search(r"\b\S+\.(py|json|md|sql|js|ts|tsx)\b", lowered):
            return True
        return False

    def _translator_fallback_message(
        self,
        *,
        event: RunLifecycleEvent,
        review: ApiRunReview | None = None,
    ) -> str:
        branch = event.branch_name or "Le lot"
        if event.kind is RunLifecycleEventKind.RUN_COMPLETED:
            return f"{branch} termine."
        if event.kind is RunLifecycleEventKind.CLARIFICATION_REQUIRED:
            question = event.blocking_question or "J'ai besoin d'une decision avant de continuer."
            return f"Question sur {branch}.\n{question}"
        if event.kind is RunLifecycleEventKind.RUN_FAILED:
            action = event.recommended_action or "Aucune action requise."
            return f"{branch} echoue.\n{action}"
        if event.kind is RunLifecycleEventKind.RUN_REVIEWED:
            if review is not None and review.verdict is ApiRunReviewVerdict.REJECTED:
                return f"Review de {branch}.\nLe lot doit etre corrige avant integration."
            if review is not None and review.verdict is ApiRunReviewVerdict.NEEDS_REVISION:
                return f"Review de {branch}.\nLe lot demande une revision avant integration."
            if review is not None and review.verdict is ApiRunReviewVerdict.ACCEPTED_WITH_RESERVES:
                return f"Review de {branch}.\nLe lot est presque bon mais demande une correction."
            if review is not None and review.verdict is ApiRunReviewVerdict.NEEDS_CLARIFICATION:
                return f"Review de {branch}.\nJ'ai besoin d'une clarification avant la suite."
            return f"Review de {branch}."
        if event.kind is RunLifecycleEventKind.CONTRACT_PROPOSED:
            return "Nouveau lot propose."
        if event.kind is RunLifecycleEventKind.BUDGET_ALERT:
            return "Budget jour en alerte."
        if event.kind is RunLifecycleEventKind.RUN_RELAUNCHED:
            return f"{branch} relance."
        return event.title or branch

    def _apply_learning(self, *, review: ApiRunReview, result: ApiRunResult, request: ApiRunRequest) -> None:
        source_ids = [result.run_id, review.review_id]
        if review.verdict is ApiRunReviewVerdict.ACCEPTED:
            self.learning.record_signal(
                kind=LearningSignalKind.PATCH_ACCEPTED,
                severity="info",
                summary=f"Accepted {request.mode.value} run for {request.branch_name}.",
                source_ids=source_ids,
                metadata={"objective": request.objective},
            )
            self.learning.record_dataset_candidate(
                source_type="api_run_review",
                quality_score=1.0,
                export_ready=True,
                source_ids=source_ids,
                metadata={"mode": request.mode.value, "branch_name": request.branch_name},
            )
            decision = str(result.structured_output.get("decision") or "").strip()
            if decision:
                self.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope=f"api_run:{request.mode.value}",
                    summary=decision,
                    source_run_id=result.run_id,
                    metadata={"branch_name": request.branch_name},
                )
        elif review.verdict is ApiRunReviewVerdict.REJECTED:
            self.learning.record_signal(
                kind=LearningSignalKind.PATCH_REJECTED,
                severity="high",
                summary=f"Rejected {request.mode.value} run for {request.branch_name}.",
                source_ids=source_ids,
                metadata={"findings": review.findings, "objective": request.objective},
            )
            if self._recent_negative_reviews(mode=request.mode) >= 2:
                self.learning.record_loop_signal(
                    repeated_pattern=f"Repeated negative reviews for {request.mode.value}",
                    impacted_area=request.branch_name,
                    recommended_reset="Reload the architecture context pack and rerun in design or patch_plan mode before generating another patch.",
                    source_ids=source_ids,
                    metadata={"objective": request.objective},
                )
        elif review.verdict is ApiRunReviewVerdict.NEEDS_REVISION:
            context_pack = self.get_context_pack(request.context_pack_id)
            self.learning.record_signal(
                kind=LearningSignalKind.CAPABILITY_DRIFT,
                severity="high",
                summary=f"{request.mode.value} run needs revision before integration.",
                source_ids=source_ids,
                metadata={"findings": review.findings, "objective": request.objective},
            )
            self.learning.recommend_refresh(
                cause=f"{request.mode.value} run needs revision",
                context_to_reload=[item.path for item in context_pack.source_refs],
                next_step="Revise the lot against the review findings, rerun the narrow scope, and only integrate after a clean review.",
                source_ids=source_ids,
                metadata={"branch_name": request.branch_name},
            )
        elif review.verdict is ApiRunReviewVerdict.NEEDS_CLARIFICATION:
            context_pack = self.get_context_pack(request.context_pack_id)
            self.learning.record_signal(
                kind=LearningSignalKind.CAPABILITY_DRIFT,
                severity="medium",
                summary=f"{request.mode.value} run needs founder clarification.",
                source_ids=source_ids,
                metadata={"findings": review.findings, "objective": request.objective},
            )
            self.learning.recommend_refresh(
                cause=f"{request.mode.value} run needs clarification",
                context_to_reload=[item.path for item in context_pack.source_refs],
                next_step="Capture the missing founder decision, refresh the context pack, and rerun with the clarified contract.",
                source_ids=source_ids,
                metadata={"branch_name": request.branch_name},
            )
        else:
            context_pack = self.get_context_pack(request.context_pack_id)
            self.learning.record_signal(
                kind=LearningSignalKind.CAPABILITY_DRIFT,
                severity="medium",
                summary=f"{request.mode.value} run was accepted with reserves.",
                source_ids=source_ids,
                metadata={"findings": review.findings},
            )
            self.learning.recommend_refresh(
                cause=f"{request.mode.value} run was accepted with reserves",
                context_to_reload=[item.path for item in context_pack.source_refs],
                next_step="Apply the review recommendations, refresh the context pack if needed, and rerun the narrow follow-up lot.",
                source_ids=source_ids,
                metadata={"branch_name": request.branch_name},
            )

    def _build_completion_report(
        self,
        *,
        review: ApiRunReview,
        result: ApiRunResult,
        request: ApiRunRequest,
    ) -> CompletionReport:
        output = result.structured_output
        summary_map = {
            ApiRunReviewVerdict.ACCEPTED: "Le lot est valide apres revue et peut passer a l'integration locale.",
            ApiRunReviewVerdict.ACCEPTED_WITH_RESERVES: "Le lot est globalement valide mais comporte des reserves a corriger avant integration.",
            ApiRunReviewVerdict.NEEDS_REVISION: "Le lot doit etre revise avant toute integration locale.",
            ApiRunReviewVerdict.NEEDS_CLARIFICATION: "Le lot ne peut pas etre integre sans clarification supplementaire du fondateur.",
            ApiRunReviewVerdict.REJECTED: "Le lot est rejete apres revue et ne doit pas etre integre tel quel.",
        }
        next_action_map = {
            ApiRunReviewVerdict.ACCEPTED: "Integrer localement, retester, puis preparer le lot suivant.",
            ApiRunReviewVerdict.ACCEPTED_WITH_RESERVES: "Appliquer les corrections mineures demandees, retester, puis integrer.",
            ApiRunReviewVerdict.NEEDS_REVISION: "Reviser le lot sur le scope minimal, retester, puis relancer la revue avant integration.",
            ApiRunReviewVerdict.NEEDS_CLARIFICATION: "Formuler la question de clarification, attendre la decision fondatrice, puis relancer le lot cible.",
            ApiRunReviewVerdict.REJECTED: "Recharger le contexte, revisiter le plan, puis relancer un patch-plan propre.",
        }
        return CompletionReport(
            report_id=new_id("completion_report"),
            run_id=result.run_id,
            verdict=review.verdict.value,
            summary=summary_map[review.verdict],
            done_items=list(output.get("patch_outline") or output.get("files_to_change") or []),
            test_summary=list(output.get("tests") or []),
            risks=list(output.get("risks") or []) + list(review.findings or []),
            next_action=next_action_map[review.verdict],
            metadata={"review_id": review.review_id, "mode": request.mode.value, "branch_name": request.branch_name},
        )

    def _build_blockage_report(
        self,
        *,
        result: ApiRunResult,
        request: ApiRunRequest,
        error: str,
    ) -> BlockageReport:
        return BlockageReport(
            report_id=new_id("blockage_report"),
            run_id=result.run_id,
            cause=error,
            impact="Le run n'a pas produit de resultat exploitable et la branche ne doit pas etre consideree comme avancee.",
            choices=[
                "Corriger le blocage technique puis relancer le meme lot.",
                "Ajuster le contrat de run avant une nouvelle tentative.",
                "Stopper ce lot et ouvrir un audit cible si le blocage se repete.",
            ],
            recommendation="Verifier le contrat, le contexte, les secrets et la sortie brute avant toute relance.",
            metadata={"mode": request.mode.value, "branch_name": request.branch_name},
        )

    def _structured_output_requires_clarification(self, structured_output: dict[str, Any]) -> bool:
        if bool(structured_output.get("clarification_needed")):
            return True
        return bool(str(structured_output.get("blocking_reason") or "").strip()) and bool(
            str(structured_output.get("question_for_founder") or "").strip()
        )

    def _build_clarification_report(
        self,
        *,
        run_id: str,
        request: ApiRunRequest,
        structured_output: dict[str, Any],
    ) -> ClarificationReport:
        cause = str(structured_output.get("blocking_reason") or "Le brief doit etre clarifie avant de continuer.").strip()
        question = str(structured_output.get("question_for_founder") or "Quelle correction precise faut-il apporter au contrat ?").strip()
        recommended_change = str(
            structured_output.get("recommended_contract_change") or "Amender le contrat courant puis redonner un go explicite."
        ).strip()
        why = str(structured_output.get("why") or "").strip()
        return ClarificationReport(
            report_id=new_id("clarification_report"),
            run_id=run_id,
            cause=cause,
            impact=why or "Le run s'arrete proprement pour eviter une implementation erronee ou hors cadre.",
            question_for_founder=question,
            recommended_contract_change=recommended_change,
            requires_reapproval=True,
            metadata={"mode": request.mode.value, "branch_name": request.branch_name},
        )

    def _mark_contract_clarification_pending(
        self,
        *,
        contract: RunContract,
        clarification: ClarificationReport,
        connection: sqlite3.Connection | None = None,
        expected_updated_at: str | None = None,
    ) -> None:
        contract.status = RunContractStatus.PREPARED
        contract.founder_decision = None
        contract.founder_decision_at = None
        contract.updated_at = datetime.now(timezone.utc).isoformat()
        contract.metadata["clarification_pending"] = True
        contract.metadata["pending_clarification_report_id"] = clarification.report_id
        contract.metadata["requires_reapproval"] = clarification.requires_reapproval
        contract.metadata["last_clarification_report_id"] = clarification.report_id
        contract.metadata.pop("founder_decision_at", None)
        self._persist_run_contract(
            contract,
            connection=connection,
            expected_updated_at=expected_updated_at,
        )

    def _detect_noise_signal(self, *, run_id: str, structured_output: dict[str, Any], request: ApiRunRequest) -> None:
        text_parts: list[str] = []
        for key in ("decision", "why"):
            value = structured_output.get(key)
            if isinstance(value, str):
                text_parts.append(value)
        for key in ("alternatives", "files_to_change", "interfaces", "patch_outline", "tests", "risks", "acceptance_criteria", "open_questions"):
            values = structured_output.get(key) or []
            if isinstance(values, list):
                text_parts.extend(str(value) for value in values)
        combined = "\n".join(text_parts)
        if len(combined) < 9000 and sum(1 for line in text_parts if line.strip()) < 45:
            return
        self.learning.record_noise_signal(
            run_id=run_id,
            reason="La sortie du run est trop verbeuse par rapport au contrat attendu.",
            evidence={
                "mode": request.mode.value,
                "branch_name": request.branch_name,
                "char_count": len(combined),
                "item_count": sum(1 for line in text_parts if line.strip()),
            },
        )

    def _recent_negative_reviews(self, *, mode: ApiRunMode) -> int:
        rows = self.database.fetchall(
            """
            SELECT v.verdict
            FROM api_run_reviews v
            JOIN api_run_results r ON r.run_id = v.run_id
            WHERE r.mode = ? AND v.verdict IN (?, ?, ?, ?)
            ORDER BY v.created_at DESC
            LIMIT 3
            """,
            (
                mode.value,
                ApiRunReviewVerdict.REJECTED.value,
                ApiRunReviewVerdict.NEEDS_REVISION.value,
                ApiRunReviewVerdict.ACCEPTED_WITH_RESERVES.value,
                ApiRunReviewVerdict.NEEDS_CLARIFICATION.value,
            ),
        )
        return len(rows)

    def _persist_context_pack(self, context_pack: ContextPack) -> None:
        self.database.upsert(
            "context_packs",
            {
                "context_pack_id": context_pack.context_pack_id,
                "mode": context_pack.mode.value,
                "objective": context_pack.objective,
                "branch_name": context_pack.branch_name,
                "target_profile": context_pack.target_profile,
                "source_refs_json": dump_json([to_jsonable(item) for item in context_pack.source_refs]),
                "repo_state_json": dump_json(context_pack.repo_state),
                "runtime_facts_json": dump_json(context_pack.runtime_facts),
                "constraints_json": dump_json(context_pack.constraints),
                "acceptance_criteria_json": dump_json(context_pack.acceptance_criteria),
                "skill_tags_json": dump_json(context_pack.skill_tags),
                "artifact_path": context_pack.artifact_path,
                "metadata_json": dump_json(context_pack.metadata),
                "created_at": context_pack.created_at,
            },
            conflict_columns="context_pack_id",
            immutable_columns=["created_at"],
        )

    def _persist_prompt_template(self, prompt_template: MegaPromptTemplate) -> None:
        self.database.upsert(
            "mega_prompt_templates",
            {
                "prompt_template_id": prompt_template.prompt_template_id,
                "context_pack_id": prompt_template.context_pack_id,
                "mode": prompt_template.mode.value,
                "agent_identity": prompt_template.agent_identity,
                "skill_tags_json": dump_json(prompt_template.skill_tags),
                "output_contract_json": dump_json(prompt_template.output_contract),
                "rendered_prompt": prompt_template.rendered_prompt,
                "model": prompt_template.model,
                "reasoning_effort": prompt_template.reasoning_effort,
                "artifact_path": prompt_template.artifact_path,
                "metadata_json": dump_json(prompt_template.metadata),
                "created_at": prompt_template.created_at,
            },
            conflict_columns="prompt_template_id",
            immutable_columns=["created_at"],
        )

    def _persist_run_contract(
        self,
        contract: RunContract,
        *,
        connection: sqlite3.Connection | None = None,
        expected_updated_at: str | None = None,
    ) -> None:
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "contracts",
            contract.contract_id,
            to_jsonable(contract),
        )
        contract.metadata["artifact_path"] = str(artifact_path)
        params = (
            contract.context_pack_id,
            contract.prompt_template_id,
            contract.mode.value,
            contract.objective,
            contract.branch_name,
            contract.target_profile,
            contract.model,
            contract.reasoning_effort,
            contract.communication_mode.value,
            contract.speech_policy.value,
            contract.operator_language,
            contract.audience.value,
            dump_json(contract.expected_outputs),
            contract.summary,
            dump_json(contract.non_goals),
            dump_json(contract.success_criteria),
            contract.estimated_cost_eur,
            contract.founder_decision,
            contract.founder_decision_at,
            contract.status.value,
            dump_json(contract.metadata),
            contract.created_at,
            contract.updated_at,
            contract.contract_id,
        )
        if expected_updated_at is not None:
            cursor = self.database.execute(
                """
                UPDATE api_run_contracts
                SET context_pack_id = ?, prompt_template_id = ?, mode = ?, objective = ?, branch_name = ?,
                    target_profile = ?, model = ?, reasoning_effort = ?, communication_mode = ?, speech_policy = ?,
                    operator_language = ?, audience = ?, expected_outputs_json = ?, summary = ?, non_goals_json = ?,
                    success_criteria_json = ?, estimated_cost_eur = ?, founder_decision = ?, founder_decision_at = ?,
                    status = ?, metadata_json = ?, created_at = ?, updated_at = ?
                WHERE contract_id = ? AND updated_at = ?
                """,
                (*params, expected_updated_at),
                connection=connection,
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Run contract {contract.contract_id} was modified concurrently; reload before applying more changes."
                )
            return
        existing = self.database.fetchone(
            "SELECT contract_id FROM api_run_contracts WHERE contract_id = ?",
            (contract.contract_id,),
            connection=connection,
        )
        if existing is None:
            self.database.execute(
                """
                INSERT INTO api_run_contracts(
                    contract_id, context_pack_id, prompt_template_id, mode, objective, branch_name,
                    target_profile, model, reasoning_effort, communication_mode, speech_policy,
                    operator_language, audience, expected_outputs_json, summary, non_goals_json,
                    success_criteria_json, estimated_cost_eur, founder_decision, founder_decision_at, status,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract.contract_id,
                    *params[:-1],
                ),
                connection=connection,
            )
            return
        self.database.execute(
            """
            UPDATE api_run_contracts
            SET context_pack_id = ?, prompt_template_id = ?, mode = ?, objective = ?, branch_name = ?,
                target_profile = ?, model = ?, reasoning_effort = ?, communication_mode = ?, speech_policy = ?,
                operator_language = ?, audience = ?, expected_outputs_json = ?, summary = ?, non_goals_json = ?,
                success_criteria_json = ?, estimated_cost_eur = ?, founder_decision = ?, founder_decision_at = ?,
                status = ?, metadata_json = ?, created_at = ?, updated_at = ?
            WHERE contract_id = ?
            """,
            params,
            connection=connection,
        )

    def _persist_run_request(self, request: ApiRunRequest, *, connection: sqlite3.Connection | None = None) -> None:
        self.database.upsert(
            "api_run_requests",
            {
                "run_request_id": request.run_request_id,
                "context_pack_id": request.context_pack_id,
                "prompt_template_id": request.prompt_template_id,
                "mode": request.mode.value,
                "objective": request.objective,
                "branch_name": request.branch_name,
                "target_profile": request.target_profile,
                "mission_chain_id": request.mission_chain_id,
                "mission_step_index": request.mission_step_index,
                "skill_tags_json": dump_json(request.skill_tags),
                "expected_outputs_json": dump_json(request.expected_outputs),
                "coding_lane": request.coding_lane,
                "desktop_lane": request.desktop_lane,
                "communication_mode": request.communication_mode.value,
                "speech_policy": request.speech_policy.value,
                "operator_language": request.operator_language,
                "audience": request.audience.value,
                "run_contract_required": 1 if request.run_contract_required else 0,
                "contract_id": request.contract_id,
                "status": request.status.value,
                "metadata_json": dump_json(request.metadata),
                "created_at": request.created_at,
                "updated_at": request.updated_at,
            },
            conflict_columns="run_request_id",
            immutable_columns=["created_at"],
            connection=connection,
        )

    def _persist_run_result(self, result: ApiRunResult, *, connection: sqlite3.Connection | None = None) -> None:
        self.database.upsert(
            "api_run_results",
            {
                "run_id": result.run_id,
                "run_request_id": result.run_request_id,
                "model": result.model,
                "mode": result.mode.value,
                "status": result.status.value,
                "raw_output_path": result.raw_output_path,
                "prompt_artifact_path": result.prompt_artifact_path,
                "result_artifact_path": result.result_artifact_path,
                "structured_output_json": dump_json(result.structured_output),
                "estimated_cost_eur": result.estimated_cost_eur,
                "usage_json": dump_json(result.usage),
                "metadata_json": dump_json(result.metadata),
                "created_at": result.created_at,
                "updated_at": result.updated_at,
            },
            conflict_columns="run_id",
            immutable_columns=["created_at"],
            connection=connection,
        )

    def _store_run_review(self, review: ApiRunReview) -> Path:
        folder = self.paths.api_runs_root / "reviews"
        folder.mkdir(parents=True, exist_ok=True)
        artifact_path = self.path_policy.ensure_allowed_write(folder / f"{review.review_id}.json")
        review.metadata["artifact_path"] = str(artifact_path)
        artifact_path.write_text(json.dumps(to_jsonable(review), ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        self._persist_run_review(review)
        return artifact_path

    def _persist_run_review(self, review: ApiRunReview) -> None:
        self.database.upsert(
            "api_run_reviews",
            {
                "review_id": review.review_id,
                "run_id": review.run_id,
                "verdict": review.verdict.value,
                "reviewer": review.reviewer,
                "findings_json": dump_json(review.findings),
                "accepted_changes_json": dump_json(review.accepted_changes),
                "followup_actions_json": dump_json(review.followup_actions),
                "metadata_json": dump_json(review.metadata),
                "created_at": review.created_at,
            },
            conflict_columns="review_id",
            immutable_columns=["created_at"],
        )

    def _persist_run_event(
        self,
        *,
        event_id: str,
        run_id: str,
        phase: str,
        severity: str,
        machine_summary: str,
        human_summary: str | None,
        payload: dict[str, Any],
        created_at: str,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database.upsert(
            "api_run_events",
            {
                "event_id": event_id,
                "run_id": run_id,
                "phase": phase,
                "severity": severity,
                "machine_summary": machine_summary,
                "human_summary": human_summary,
                "payload_json": dump_json(payload),
                "created_at": created_at,
            },
            conflict_columns="event_id",
            immutable_columns=["created_at"],
            connection=connection,
        )

    def _record_run_event(
        self,
        *,
        run_id: str,
        phase: str,
        severity: str,
        machine_summary: str,
        human_summary: str | None,
        payload: dict[str, Any],
        connection: sqlite3.Connection | None = None,
        refresh_snapshot: bool = True,
    ) -> None:
        event_id = new_id("api_event")
        created_at = datetime.now(timezone.utc).isoformat()
        self._persist_run_event(
            event_id=event_id,
            run_id=run_id,
            phase=phase,
            severity=severity,
            machine_summary=machine_summary,
            human_summary=human_summary,
            payload=payload,
            created_at=created_at,
            connection=connection,
        )
        self.journal.append(
            "api_run_event",
            "api_runs",
            {
                "event_id": event_id,
                "run_id": run_id,
                "phase": phase,
                "severity": severity,
                "machine_summary": machine_summary,
            },
        )
        if refresh_snapshot:
            self._refresh_live_snapshot()

    def _emit_run_lifecycle_event(
        self,
        *,
        run_id: str,
        run_request_id: str,
        contract_id: str | None,
        kind: RunLifecycleEventKind,
        mode: ApiRunMode,
        branch_name: str,
        status: ApiRunStatus,
        phase: str,
        title: str,
        summary: str,
        blocking_question: str | None = None,
        recommended_action: str | None = None,
        requires_reapproval: bool = False,
        result: ApiRunResult | None = None,
        review: ApiRunReview | None = None,
        metadata: dict[str, Any] | None = None,
        connection: sqlite3.Connection | None = None,
        refresh_snapshot: bool = True,
    ) -> RunLifecycleEvent:
        event = RunLifecycleEvent(
            lifecycle_event_id=new_id("lifecycle_event"),
            run_id=run_id,
            run_request_id=run_request_id,
            contract_id=contract_id,
            kind=kind,
            title=title,
            summary=summary,
            branch_name=branch_name,
            mode=mode,
            channel_hint=self._channel_hint_for_lifecycle(kind),
            status=status,
            phase=phase,
            blocking_question=blocking_question,
            recommended_action=recommended_action,
            requires_reapproval=requires_reapproval,
            metadata=dict(metadata or {}),
        )
        self._persist_lifecycle_event(event, connection=connection)
        delivery: OperatorDelivery | None = None
        translated_message: str | None = None
        filter_reason = "noise_filtered"
        try:
            translated_message = self._call_translator(event=event, result=result, review=review)
        except Exception as translate_exc:
            filter_reason = "translator_failed"
            self.logger.log(
                "WARNING",
                "translator_failed",
                event_id=event.lifecycle_event_id,
                kind=kind.value,
                error=str(translate_exc),
            )
        if translated_message is None:
            self.journal.append(
                "api_run_operator_delivery_filtered",
                "api_runs",
                {
                    "lifecycle_event_id": event.lifecycle_event_id,
                    "run_id": run_id,
                    "kind": kind.value,
                    "reason": filter_reason,
                },
            )
        else:
            self._prune_pending_operator_deliveries(incoming_channel_hint=event.channel_hint, connection=connection)
        if translated_message is not None:
            delivery_guarantee = self._delivery_guarantee_for_kind(kind, channel_hint=event.channel_hint)
            backlog_state = self._operator_delivery_backlog_state(connection=connection)
            delivery_payload = self._build_operator_delivery_payload(
                event,
                translated_message=translated_message,
                delivery_guarantee=delivery_guarantee,
                backlog_state=backlog_state,
            )
            delivery = OperatorDelivery(
                delivery_id=new_id("operator_delivery"),
                lifecycle_event_id=event.lifecycle_event_id,
                adapter="openclaw",
                surface="discord",
                channel_hint=event.channel_hint,
                status=OperatorDeliveryStatus.PENDING,
                payload=delivery_payload,
                metadata={
                    "run_id": run_id,
                    "kind": kind.value,
                    "delivery_guarantee": delivery_guarantee.value,
                    "delivery_priority_rank": self._operator_delivery_guarantee_rank(delivery_guarantee),
                    "replayable": True,
                    "backlog_soft_limit_exceeded": backlog_state["soft_limit_exceeded"],
                    "pending_backlog_count": backlog_state["pending_count"],
                    "pending_backlog_limit": backlog_state["max_pending"],
                },
                next_attempt_at=event.created_at,
            )
            self._persist_operator_delivery(delivery, connection=connection)
        self.journal.append(
            "api_run_lifecycle_event_created",
            "api_runs",
            {
                "lifecycle_event_id": event.lifecycle_event_id,
                "run_id": run_id,
                "kind": kind.value,
                "delivery_id": delivery.delivery_id if delivery else None,
                "channel_hint": event.channel_hint.value,
            },
        )
        if refresh_snapshot:
            self._refresh_live_snapshot()
        return event

    def _channel_hint_for_lifecycle(self, kind: RunLifecycleEventKind) -> OperatorChannelHint:
        if kind is RunLifecycleEventKind.CLARIFICATION_REQUIRED:
            return OperatorChannelHint.APPROVALS
        if kind in {
            RunLifecycleEventKind.CONTRACT_PROPOSED,
            RunLifecycleEventKind.CONTRACT_APPROVED,
            RunLifecycleEventKind.CONTRACT_REJECTED,
        }:
            return OperatorChannelHint.APPROVALS
        if kind is RunLifecycleEventKind.BUDGET_ALERT:
            return OperatorChannelHint.INCIDENTS
        if kind is RunLifecycleEventKind.RUN_FAILED:
            return OperatorChannelHint.INCIDENTS
        return OperatorChannelHint.RUNS_LIVE

    def _build_operator_delivery_payload(
        self,
        event: RunLifecycleEvent,
        *,
        translated_message: str | None = None,
        delivery_guarantee: OperatorDeliveryGuarantee,
        backlog_state: dict[str, Any],
    ) -> dict[str, Any]:
        text = translated_message or self._render_operator_delivery_text(event)
        return {
            "version": "v2",
            "surface": "discord",
            "channel_hint": event.channel_hint.value,
            "text": text,
            "translated_message": text,
            "delivery_guarantee": delivery_guarantee.value,
            "delivery_priority_rank": self._operator_delivery_guarantee_rank(delivery_guarantee),
            "delivery_contract": {
                "replayable": True,
                "visible_failure_required": delivery_guarantee
                in {OperatorDeliveryGuarantee.MUST_NOTIFY, OperatorDeliveryGuarantee.MUST_PERSIST},
                "must_persist": delivery_guarantee is OperatorDeliveryGuarantee.MUST_PERSIST,
                "soft_backlog_limit_exceeded": bool(backlog_state.get("soft_limit_exceeded")),
            },
            "card": {
                "title": event.title,
                "summary": event.summary,
                "kind": event.kind.value,
                "status": event.status.value if event.status else None,
                "phase": event.phase,
                "branch_name": event.branch_name,
                "mode": event.mode.value if event.mode else None,
                "blocking_question": event.blocking_question,
                "recommended_action": event.recommended_action,
                "requires_reapproval": event.requires_reapproval,
            },
            "event": to_jsonable(event),
        }

    def _render_operator_delivery_text(self, event: RunLifecycleEvent) -> str:
        return StandardReplyPolicy.render_operator_delivery_text(event)

    def _pending_operator_delivery_count(self, *, connection: sqlite3.Connection | None = None) -> int:
        row = self.database.fetchone(
            "SELECT COUNT(*) AS count FROM api_run_operator_deliveries WHERE status = ?",
            (OperatorDeliveryStatus.PENDING.value,),
            connection=connection,
        )
        return int(row["count"] or 0) if row is not None else 0

    def _should_enqueue_operator_delivery(
        self,
        *,
        incoming_channel_hint: OperatorChannelHint,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        del incoming_channel_hint, connection
        return True

    def _operator_delivery_backlog_state(self, *, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        max_pending = max(1, int(getattr(self.execution_policy, "operator_delivery_max_pending", 64)))
        pending_count = self._pending_operator_delivery_count(connection=connection)
        return {
            "soft_limit_exceeded": pending_count >= max_pending,
            "pending_count": pending_count,
            "max_pending": max_pending,
        }

    def _prune_pending_operator_deliveries(
        self,
        *,
        incoming_channel_hint: OperatorChannelHint,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        backlog_state = self._operator_delivery_backlog_state(connection=connection)
        if not backlog_state["soft_limit_exceeded"]:
            return 0
        self.journal.append(
            "api_run_operator_delivery_backlog_soft_limit_exceeded",
            "api_runs",
            {
                "incoming_channel_hint": incoming_channel_hint.value,
                "pending_count": backlog_state["pending_count"],
                "pending_limit": backlog_state["max_pending"],
            },
        )
        return 0

    def _refresh_live_snapshot(self, *, limit: int = 8) -> None:
        try:
            snapshot = self._build_monitor_snapshot(limit=limit)
            snapshot_path = self.path_policy.ensure_allowed_write(self.paths.api_runs_terminal_snapshot_path)
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            self.logger.log("WARNING", "api_run_snapshot_refresh_failed", error=str(exc))

    def _persist_lifecycle_event(self, event: RunLifecycleEvent, *, connection: sqlite3.Connection | None = None) -> None:
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "lifecycle_events",
            event.lifecycle_event_id,
            to_jsonable(event),
        )
        event.artifact_path = str(artifact_path)
        self.database.execute(
            """
            INSERT INTO api_run_lifecycle_events(
                lifecycle_event_id, run_id, run_request_id, contract_id, kind, title, summary,
                branch_name, mode, channel_hint, status, phase, blocking_question,
                recommended_action, requires_reapproval, artifact_path, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.lifecycle_event_id,
                event.run_id,
                event.run_request_id,
                event.contract_id,
                event.kind.value,
                event.title,
                event.summary,
                event.branch_name,
                event.mode.value if event.mode else None,
                event.channel_hint.value,
                event.status.value if event.status else None,
                event.phase,
                event.blocking_question,
                event.recommended_action,
                1 if event.requires_reapproval else 0,
                event.artifact_path,
                dump_json(event.metadata),
                event.created_at,
            ),
            connection=connection,
        )

    def _persist_operator_delivery(self, delivery: OperatorDelivery, *, connection: sqlite3.Connection | None = None) -> None:
        next_attempt_at = delivery.next_attempt_at
        if delivery.status is OperatorDeliveryStatus.PENDING and not next_attempt_at:
            next_attempt_at = delivery.created_at
        self.database.execute(
            """
            INSERT INTO api_run_operator_deliveries(
                delivery_id, lifecycle_event_id, adapter, surface, channel_hint, status,
                attempts, payload_json, last_error, next_attempt_at, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delivery.delivery_id,
                delivery.lifecycle_event_id,
                delivery.adapter,
                delivery.surface,
                delivery.channel_hint.value,
                delivery.status.value,
                delivery.attempts,
                dump_json(delivery.payload),
                delivery.last_error,
                next_attempt_at,
                dump_json(delivery.metadata),
                delivery.created_at,
                delivery.updated_at,
            ),
            connection=connection,
        )

    def _persist_completion_report(self, report: CompletionReport, *, connection: sqlite3.Connection | None = None) -> None:
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "completion_reports",
            report.report_id,
            to_jsonable(report),
        )
        report.metadata["artifact_path"] = str(artifact_path)
        self.database.upsert(
            "completion_reports",
            {
                "report_id": report.report_id,
                "run_id": report.run_id,
                "verdict": report.verdict,
                "summary": report.summary,
                "done_items_json": dump_json(report.done_items),
                "test_summary_json": dump_json(report.test_summary),
                "risks_json": dump_json(report.risks),
                "next_action": report.next_action,
                "metadata_json": dump_json(report.metadata),
                "created_at": report.created_at,
            },
            conflict_columns="report_id",
            immutable_columns=["created_at"],
            connection=connection,
        )

    def _persist_blockage_report(self, report: BlockageReport, *, connection: sqlite3.Connection | None = None) -> None:
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "blockage_reports",
            report.report_id,
            to_jsonable(report),
        )
        report.metadata["artifact_path"] = str(artifact_path)
        self.database.upsert(
            "blockage_reports",
            {
                "report_id": report.report_id,
                "run_id": report.run_id,
                "cause": report.cause,
                "impact": report.impact,
                "choices_json": dump_json(report.choices),
                "recommendation": report.recommendation,
                "metadata_json": dump_json(report.metadata),
                "created_at": report.created_at,
            },
            conflict_columns="report_id",
            immutable_columns=["created_at"],
            connection=connection,
        )

    def _persist_clarification_report(self, report: ClarificationReport, *, connection: sqlite3.Connection | None = None) -> None:
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "clarification_reports",
            report.report_id,
            to_jsonable(report),
        )
        report.metadata["artifact_path"] = str(artifact_path)
        self.database.upsert(
            "clarification_reports",
            {
                "report_id": report.report_id,
                "run_id": report.run_id,
                "cause": report.cause,
                "impact": report.impact,
                "question_for_founder": report.question_for_founder,
                "recommended_contract_change": report.recommended_contract_change,
                "requires_reapproval": 1 if report.requires_reapproval else 0,
                "metadata_json": dump_json(report.metadata),
                "created_at": report.created_at,
            },
            conflict_columns="report_id",
            immutable_columns=["created_at"],
            connection=connection,
        )

    def _update_request_status(
        self,
        run_request_id: str,
        status: ApiRunStatus,
        *,
        updated_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database.execute(
            "UPDATE api_run_requests SET status = ?, updated_at = ? WHERE run_request_id = ?",
            (status.value, updated_at or datetime.now(timezone.utc).isoformat(), run_request_id),
            connection=connection,
        )

    def _update_result_status(
        self,
        run_id: str,
        status: ApiRunStatus,
        *,
        updated_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database.execute(
            "UPDATE api_run_results SET status = ?, updated_at = ? WHERE run_id = ?",
            (status.value, updated_at or datetime.now(timezone.utc).isoformat(), run_id),
            connection=connection,
        )

    def _normalize_branch_name(self, branch_name: str | None) -> str:
        candidate = branch_name or self._current_branch()
        if not candidate.startswith("codex/project-os-"):
            raise ValueError("API runs must target a codex/project-os-* branch")
        return candidate

    def _normalize_skill_tags(self, skill_tags: list[str]) -> list[str]:
        normalized = []
        for item in skill_tags:
            value = item.strip().upper().replace(" ", "_")
            if value and value not in normalized:
                normalized.append(value)
        if not normalized:
            raise ValueError("API runs require at least one skill tag")
        return normalized

    def _resolve_context_source_paths(self, source_paths: list[str] | None) -> list[Path]:
        if not source_paths:
            source_paths = [
                "PROJECT_OS_MASTER_MACHINE.md",
                "docs/roadmap/BUILD_STATUS_CHECKLIST.md",
                "docs/architecture/HYBRID_LARGE_CONTEXT_WORKFLOW.md",
            ]
        resolved: list[Path] = []
        for raw in source_paths[:DEFAULT_CONTEXT_FILE_COUNT]:
            candidate = Path(raw)
            path = candidate if candidate.is_absolute() else (self.repo_root / candidate)
            resolved.append(path.resolve(strict=False))
        return resolved

    def _read_context_source(self, path: Path) -> ContextSource:
        text = path.read_text(encoding="utf-8")
        truncated = len(text) > DEFAULT_CONTEXT_SOURCE_LIMIT
        content = text[:DEFAULT_CONTEXT_SOURCE_LIMIT] if truncated else text
        try:
            relative = str(path.relative_to(self.repo_root))
        except ValueError:
            relative = str(path)
        return ContextSource(
            source_id=new_id("source"),
            path=str(path),
            kind=path.suffix.lstrip(".") or "text",
            content=content,
            truncated=truncated,
            metadata={"relative_path": relative, "char_count": len(text)},
        )

    def _repo_state(self, *, target_branch: str) -> dict[str, Any]:
        return {
            "current_branch": self._current_branch(),
            "target_branch": target_branch,
            "dirty": bool(self._git_lines("status", "--short")),
            "status_short": self._git_lines("status", "--short"),
            "last_commit": self._git_output("log", "-1", "--pretty=format:%H%x09%s%x09%ad", "--date=iso-strict"),
        }

    def _runtime_facts(self, *, target_branch: str, target_profile: str | None) -> dict[str, Any]:
        facts: dict[str, Any] = {}
        if self.paths.bootstrap_state_path.exists():
            facts["bootstrap"] = json.loads(self.paths.bootstrap_state_path.read_text(encoding="utf-8"))
        if self.paths.health_snapshot_path.exists():
            facts["health"] = json.loads(self.paths.health_snapshot_path.read_text(encoding="utf-8"))
        if self.paths.api_runs_terminal_snapshot_path.exists():
            snapshot = json.loads(self.paths.api_runs_terminal_snapshot_path.read_text(encoding="utf-8"))
            if isinstance(snapshot, dict):
                facts["api_runs_monitor"] = self._sanitize_monitor_snapshot(snapshot)
            else:
                facts["api_runs_monitor"] = snapshot
        facts["model_stack_health"] = self.router.model_stack_health_snapshot()
        recent_session_briefing = self._recent_session_briefing(target_branch=target_branch, target_profile=target_profile)
        if recent_session_briefing:
            facts["recent_session_briefing"] = recent_session_briefing
        return facts

    def _recent_session_briefing(self, *, target_branch: str, target_profile: str | None) -> dict[str, Any] | None:
        limit = max(1, min(int(self.execution_policy.proactive_briefing_max_items), 5))
        params: list[Any] = [target_branch]
        where_clause = "req.branch_name = ?"
        if target_profile:
            where_clause = "(req.branch_name = ? OR req.target_profile = ?)"
            params.append(target_profile)
        params.append(limit)
        rows = self.database.fetchall(
            f"""
            SELECT req.branch_name, req.mode, req.objective, req.target_profile, req.status AS request_status,
                   req.updated_at AS request_updated_at,
                   res.run_id, res.model, res.status AS result_status, res.updated_at AS result_updated_at
            FROM api_run_requests req
            LEFT JOIN api_run_results res ON res.run_request_id = req.run_request_id
            WHERE {where_clause}
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
            return None
        return {
            "count": len(items),
            "items": items,
            "summary": f"{len(items)} recent session summaries retained for this branch/profile.",
        }

    def _render_prompt_text(self, context_pack: ContextPack, template_config: dict[str, Any]) -> str:
        sections = [
            f"# Identite Agent\n{template_config['agent_identity']}",
            f"# Mode de run\n{context_pack.mode.value}",
            f"# Skills du run\n{', '.join(context_pack.skill_tags)}",
            f"# Objectif\n{context_pack.objective}",
            "# Contraintes\n" + "\n".join(f"- {item}" for item in context_pack.constraints),
            "# Criteres de reussite\n" + "\n".join(f"- {item}" for item in context_pack.acceptance_criteria),
            "# Etat du repo\n" + json.dumps(context_pack.repo_state, ensure_ascii=True, indent=2, sort_keys=True),
            "# Faits runtime\n" + json.dumps(context_pack.runtime_facts, ensure_ascii=True, indent=2, sort_keys=True),
        ]
        learning_section = self._render_learning_context_section(
            context_pack.runtime_facts.get("learning_context", {})
        )
        if learning_section:
            sections.append(learning_section)
        sections.extend(
            [
                "# Contrat de sortie\n" + "\n".join(f"- {item}" for item in template_config["output_contract"]),
                "# Regles de mode\n" + "\n".join(f"- {item}" for item in template_config.get("instructions", [])),
                "# Sources de contexte",
            ]
        )
        for source in context_pack.source_refs:
            sections.append(
                "\n".join(
                    [
                        f"## {source.metadata.get('relative_path', source.path)}",
                        f"- kind: {source.kind}",
                        f"- truncated: {str(source.truncated).lower()}",
                        "",
                        source.content,
                    ]
                )
            )
        sections.append(
            "# Instructions de reponse\n"
            "Retourne uniquement du JSON structure conforme au schema. Ne bavarde pas pendant l'execution. "
            "Produis une sortie exploitable par un inspecteur humain, claire en francais pour les resumes destines a l'operateur, "
            "et garde une voie repo/CLI first. Si le brief est contradictoire, dangereux, sous-specifie, hors-scope ou en conflit "
            "avec la verite repo/runtime, active clarification_needed, explique le blocage, pose la question minimale bloquante "
            "et n'invente pas une implementation finale."
        )
        return "\n\n".join(sections)

    def _render_learning_context_section(self, learning_context: dict[str, Any]) -> str | None:
        if not any(
            learning_context.get(key)
            for key in ("decisions", "deferred_decisions", "high_severity_signals", "detected_loops", "refresh_recommendations")
        ):
            return None
        lines = ["## Learning Context (lessons from recent runs)"]
        if learning_context.get("summary"):
            lines.append(str(learning_context["summary"]))
        if learning_context.get("detected_loops"):
            lines.append("")
            lines.append("DETECTED LOOPS (do NOT repeat these patterns):")
            for loop in learning_context["detected_loops"]:
                lines.append(f"  - Pattern: {loop['pattern']}")
                lines.append(f"    Reset: {loop['recommended_reset']}")
        if learning_context.get("high_severity_signals"):
            lines.append("")
            lines.append("High-severity signals from recent runs:")
            for signal in learning_context["high_severity_signals"]:
                lines.append(f"  - [{signal['kind']}] {signal['summary']}")
        if learning_context.get("decisions"):
            lines.append("")
            lines.append("Recent confirmed decisions:")
            for decision in learning_context["decisions"]:
                lines.append(f"  - [{decision['status']}] {decision['scope']}: {decision['summary']}")
        if learning_context.get("deferred_decisions"):
            lines.append("")
            lines.append("Known intentional deferrals / accepted gaps:")
            for decision in learning_context["deferred_decisions"]:
                lines.append(f"  - [{decision['status']}] {decision['scope']}: {decision['summary']}")
                next_trigger = decision.get("metadata", {}).get("next_trigger")
                if next_trigger:
                    lines.append(f"    Revisit when: {next_trigger}")
        if learning_context.get("refresh_recommendations"):
            lines.append("")
            lines.append("Refresh recommendations:")
            for recommendation in learning_context["refresh_recommendations"]:
                lines.append(f"  - Cause: {recommendation['cause']}")
                lines.append(f"    Next step: {recommendation['next_step']}")
        return "\n".join(lines)

    def _output_schema(self) -> dict[str, Any]:
        array_of_strings = {"type": "array", "items": {"type": "string"}}
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {"type": "string"},
                "why": {"type": "string"},
                "alternatives": array_of_strings,
                "files_to_change": array_of_strings,
                "interfaces": array_of_strings,
                "patch_outline": array_of_strings,
                "tests": array_of_strings,
                "risks": array_of_strings,
                "acceptance_criteria": array_of_strings,
                "open_questions": array_of_strings,
                "clarification_needed": {"type": "boolean"},
                "blocking_reason": {"type": "string"},
                "recommended_contract_change": {"type": "string"},
                "question_for_founder": {"type": "string"},
            },
            "required": [
                "decision",
                "why",
                "alternatives",
                "files_to_change",
                "interfaces",
                "patch_outline",
                "tests",
                "risks",
                "acceptance_criteria",
                "open_questions",
                "clarification_needed",
                "blocking_reason",
                "recommended_contract_change",
                "question_for_founder",
            ],
        }

    def _estimate_cost_eur(self, *, model: str, usage: dict[str, Any]) -> float:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return estimate_usage_cost_eur(model=model or self.execution_policy.default_model, input_tokens=input_tokens, output_tokens=output_tokens)

    def _default_constraints(self) -> list[str]:
        return [
            "Travaille d'abord sur le repo et la CLI. Pas de computer use Windows pour la lane code v1.",
            "Ne modifie jamais main. Travaille sur une branche codex/project-os-*.",
            "Ne contourne jamais le Mission Router, la verite runtime, ni la policy d'approbation.",
            "Reste silencieux pendant le run. Les messages naturels n'arrivent qu'en cas de blocage reel ou en fin de run.",
            "Retourne du JSON structure uniquement et signale explicitement les faits manquants.",
            "Si une ambiguite majeure ou une contradiction rend le lot non fiable, demande une clarification au lieu de deviner.",
        ]

    def _default_acceptance_criteria(self, mode: ApiRunMode) -> list[str]:
        base = [
            "The result is implementable in the current repo without inventing a second architecture.",
            "The result preserves the OpenClaw facade vs Project OS truth boundary.",
            "The result keeps raw run artifacts in runtime storage and validated artifacts in the repo only.",
        ]
        if mode is ApiRunMode.GENERATE_PATCH:
            base.append("The patch outline is ready for Claude review and local test execution.")
        return base

    def _build_contract_summary(self, context_pack: ContextPack, prompt_template: MegaPromptTemplate, estimated_cost: float) -> str:
        return (
            f"Run {context_pack.mode.value} sur {context_pack.branch_name}. "
            f"L'API travaillera en silence sur {prompt_template.model} ({prompt_template.reasoning_effort}) "
            f"avec un cout estime de {estimated_cost:.4f} EUR."
        )

    def _contract_non_goals(self) -> list[str]:
        return [
            "Ne pas pousser sur main.",
            "Ne pas bavarder pendant le run de code.",
            "Ne pas contourner le Mission Router ou la politique budget/approvals.",
            "Ne pas creer une deuxieme verite en dehors du runtime et du repo.",
        ]

    def _estimate_cost_hint(self, model: str, reasoning_effort: str, mode: ApiRunMode) -> float:
        usage_hints = {
            ApiRunMode.AUDIT: {"input_tokens": 18_000, "output_tokens": 3_000},
            ApiRunMode.DESIGN: {"input_tokens": 24_000, "output_tokens": 4_000},
            ApiRunMode.PATCH_PLAN: {"input_tokens": 22_000, "output_tokens": 4_500},
            ApiRunMode.GENERATE_PATCH: {"input_tokens": 28_000, "output_tokens": 6_000},
        }
        usage = dict(usage_hints.get(mode, usage_hints[ApiRunMode.PATCH_PLAN]))
        if reasoning_effort == "xhigh":
            usage["output_tokens"] = int(usage["output_tokens"] * 1.15)
        return self._estimate_cost_eur(model=model, usage=usage)

    def _load_templates(self) -> dict[str, Any]:
        payload = json.loads(self.templates_path.read_text(encoding="utf-8"))
        if "modes" not in payload:
            raise RuntimeError("api_run_templates.json must define a modes object")
        return payload

    def _template_for_mode(self, mode: ApiRunMode) -> dict[str, Any]:
        shared = dict(self.templates.get("shared", {}))
        specific = dict(self.templates["modes"].get(mode.value, {}))
        output_contract = specific.get("output_contract") or shared.get("output_contract") or []
        if not output_contract:
            raise RuntimeError(f"Missing output_contract for api run mode {mode.value}")
        return {
            "version": self.templates.get("version", "v1"),
            "agent_identity": shared.get("agent_identity", "Project OS Lead Agent v1"),
            "output_contract": list(output_contract),
            "instructions": list(shared.get("instructions", [])) + list(specific.get("instructions", [])),
            "model": specific.get("model", self.execution_policy.default_model),
            "reasoning_effort": specific.get("reasoning_effort", self.execution_policy.default_reasoning_effort),
        }

    def _write_runtime_json(self, folder: Path, stem: str, payload: Any) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        destination = self.path_policy.ensure_allowed_write(folder / f"{stem}.json")
        destination.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        return destination

    def _write_runtime_text(self, folder: Path, stem: str, payload: str, *, suffix: str = ".txt") -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        destination = self.path_policy.ensure_allowed_write(folder / f"{stem}{suffix}")
        destination.write_text(payload, encoding="utf-8")
        return destination

    def _git_output(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return completed.stdout.strip()

    def _git_lines(self, *args: str) -> list[str]:
        output = self._git_output(*args)
        return [line for line in output.splitlines() if line.strip()]

    def _current_branch(self) -> str:
        return self._git_output("rev-parse", "--abbrev-ref", "HEAD")
