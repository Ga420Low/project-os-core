from __future__ import annotations

import json
import sqlite3
import shutil
import subprocess
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

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
    OperatorDeliveryStatus,
    OperatorAudience,
    RunContract,
    RunContractStatus,
    RunLifecycleEvent,
    RunLifecycleEventKind,
    RunSpeechPolicy,
    new_id,
    to_jsonable,
)
from ..observability import StructuredLogger
from ..paths import PathPolicy, ProjectPaths
from ..runtime.journal import LocalJournal
from ..secrets import SecretResolver


PRICING_PER_MILLION_USD: dict[str, dict[str, float]] = {
    "gpt-5.4": {"input": 2.5, "output": 15.0},
    "gpt-5.4-pro": {"input": 30.0, "output": 180.0},
}
USD_TO_EUR = 0.92
DEFAULT_CONTEXT_SOURCE_LIMIT = 12_000
DEFAULT_CONTEXT_FILE_COUNT = 10


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
            runtime_facts=self._runtime_facts(),
            constraints=list(constraints or self._default_constraints()),
            acceptance_criteria=list(acceptance_criteria or self._default_acceptance_criteria(mode)),
            skill_tags=normalized_skills,
            metadata=dict(metadata or {}),
        )
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
            structured_output, raw_payload, usage = self._normalize_response_payload(response_payload)
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
                request_finalized_at = datetime.now(timezone.utc).isoformat()
                result.updated_at = request_finalized_at
                with self.database.transaction() as connection:
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
                        machine_summary="Le run est termine et pret pour revue.",
                        human_summary=None,
                        payload={
                            "estimated_cost_eur": result.estimated_cost_eur,
                            "result_artifact_path": result.result_artifact_path,
                            "review_package_path": str(review_package_path),
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
                        summary="Le run est termine et attend maintenant la revue locale.",
                        metadata={
                            "objective": request.objective,
                            "review_package_path": str(review_package_path),
                            "estimated_cost_eur": result.estimated_cost_eur,
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
        review_artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "reviews",
            review.review_id,
            to_jsonable(review),
        )
        review.metadata["artifact_path"] = str(review_artifact_path)
        self._persist_run_review(review)
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
        sql += " ORDER BY COALESCE(d.next_attempt_at, d.created_at) ASC, d.created_at ASC LIMIT ?"
        params.append(limit)
        rows = self.database.fetchall(sql, tuple(params))
        deliveries: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            deliveries.append(
                {
                    "delivery_id": str(row["delivery_id"]),
                    "lifecycle_event_id": str(row["lifecycle_event_id"]),
                    "adapter": str(row["adapter"]),
                    "surface": str(row["surface"]),
                    "channel_hint": str(row["channel_hint"]),
                    "status": str(row["status"]),
                    "attempts": int(row["attempts"]),
                    "last_error": str(row["last_error"]) if row["last_error"] else None,
                    "next_attempt_at": str(row["next_attempt_at"]) if row["next_attempt_at"] else None,
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
            )
        return {"deliveries": deliveries}

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
        delivery_metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        if metadata:
            delivery_metadata.update(metadata)
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
            },
        )
        self._refresh_live_snapshot()
        return {
            "delivery_id": delivery_id,
            "status": final_status.value,
            "attempts": attempts,
            "last_error": error,
            "next_attempt_at": next_attempt_at,
            "metadata": delivery_metadata,
        }

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
        review_rows = self.database.fetchall(
            "SELECT * FROM api_run_reviews ORDER BY created_at DESC",
        )
        event_rows = self.database.fetchall(
            "SELECT * FROM api_run_events ORDER BY created_at DESC",
        )
        clarification_rows = self.database.fetchall(
            "SELECT * FROM clarification_reports ORDER BY created_at DESC",
        )
        lifecycle_rows = self.database.fetchall(
            "SELECT * FROM api_run_lifecycle_events ORDER BY created_at DESC",
        )
        delivery_rows = self.database.fetchall(
            "SELECT * FROM api_run_operator_deliveries ORDER BY created_at DESC",
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
        for item in items:
            status_key = str(item.get("status") or "unknown")
            status_counts[status_key] = status_counts.get(status_key, 0) + 1
            review_key = str(item.get("review_verdict") or "pending")
            review_counts[review_key] = review_counts.get(review_key, 0) + 1
            delivery_key = str(item.get("operator_delivery_status") or "none")
            operator_delivery_counts[delivery_key] = operator_delivery_counts.get(delivery_key, 0) + 1

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
            "latest_runs": items,
        }
        return snapshot

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
        lines.extend(self._terminal_section("Budget", [budget_line, f"Livraisons operateur: {delivery_line}"], width=width))

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

    def _normalize_response_payload(self, response_payload: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if isinstance(response_payload, dict):
            raw_payload = dict(response_payload)
            output_text = raw_payload.get("output_text")
        else:
            raw_payload = response_payload.model_dump() if hasattr(response_payload, "model_dump") else {"repr": repr(response_payload)}
            output_text = getattr(response_payload, "output_text", None)
        if not output_text:
            raise RuntimeError("Responses API returned no output_text")
        structured_output = self._parse_structured_output_text(str(output_text))
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
                parsed, _ = decoder.raw_decode(fenced)
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

        raise RuntimeError("Responses API returned an invalid structured payload")

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
        else:
            context_pack = self.get_context_pack(request.context_pack_id)
            self.learning.record_signal(
                kind=LearningSignalKind.CAPABILITY_DRIFT,
                severity="medium",
                summary=f"{request.mode.value} run needs revision.",
                source_ids=source_ids,
                metadata={"findings": review.findings},
            )
            self.learning.recommend_refresh(
                cause=f"{request.mode.value} run required revision",
                context_to_reload=[item.path for item in context_pack.source_refs],
                next_step="Refresh the context pack, inspect the rejected findings, and rerun with clarified acceptance criteria.",
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
            ApiRunReviewVerdict.NEEDS_REVISION: "Le lot a une bonne base mais doit etre corrige avant integration.",
            ApiRunReviewVerdict.REJECTED: "Le lot est rejete apres revue et ne doit pas etre integre tel quel.",
        }
        next_action_map = {
            ApiRunReviewVerdict.ACCEPTED: "Integrer localement, retester, puis preparer le lot suivant.",
            ApiRunReviewVerdict.NEEDS_REVISION: "Corriger les points remontes, puis relancer un run ou un patch local cible.",
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
            WHERE r.mode = ? AND v.verdict IN (?, ?)
            ORDER BY v.created_at DESC
            LIMIT 3
            """,
            (
                mode.value,
                ApiRunReviewVerdict.REJECTED.value,
                ApiRunReviewVerdict.NEEDS_REVISION.value,
            ),
        )
        return len(rows)

    def _persist_context_pack(self, context_pack: ContextPack) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO context_packs(
                context_pack_id, mode, objective, branch_name, target_profile, source_refs_json,
                repo_state_json, runtime_facts_json, constraints_json, acceptance_criteria_json,
                skill_tags_json, artifact_path, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                context_pack.context_pack_id,
                context_pack.mode.value,
                context_pack.objective,
                context_pack.branch_name,
                context_pack.target_profile,
                dump_json([to_jsonable(item) for item in context_pack.source_refs]),
                dump_json(context_pack.repo_state),
                dump_json(context_pack.runtime_facts),
                dump_json(context_pack.constraints),
                dump_json(context_pack.acceptance_criteria),
                dump_json(context_pack.skill_tags),
                context_pack.artifact_path,
                dump_json(context_pack.metadata),
                context_pack.created_at,
            ),
        )

    def _persist_prompt_template(self, prompt_template: MegaPromptTemplate) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO mega_prompt_templates(
                prompt_template_id, context_pack_id, mode, agent_identity, skill_tags_json,
                output_contract_json, rendered_prompt, model, reasoning_effort, artifact_path,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prompt_template.prompt_template_id,
                prompt_template.context_pack_id,
                prompt_template.mode.value,
                prompt_template.agent_identity,
                dump_json(prompt_template.skill_tags),
                dump_json(prompt_template.output_contract),
                prompt_template.rendered_prompt,
                prompt_template.model,
                prompt_template.reasoning_effort,
                prompt_template.artifact_path,
                dump_json(prompt_template.metadata),
                prompt_template.created_at,
            ),
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO api_run_requests(
                run_request_id, context_pack_id, prompt_template_id, mode, objective, branch_name,
                target_profile, skill_tags_json, expected_outputs_json, coding_lane, desktop_lane,
                communication_mode, speech_policy, operator_language, audience, run_contract_required,
                contract_id, status, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.run_request_id,
                request.context_pack_id,
                request.prompt_template_id,
                request.mode.value,
                request.objective,
                request.branch_name,
                request.target_profile,
                dump_json(request.skill_tags),
                dump_json(request.expected_outputs),
                request.coding_lane,
                request.desktop_lane,
                request.communication_mode.value,
                request.speech_policy.value,
                request.operator_language,
                request.audience.value,
                1 if request.run_contract_required else 0,
                request.contract_id,
                request.status.value,
                dump_json(request.metadata),
                request.created_at,
                request.updated_at,
            ),
            connection=connection,
        )

    def _persist_run_result(self, result: ApiRunResult, *, connection: sqlite3.Connection | None = None) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO api_run_results(
                run_id, run_request_id, model, mode, status, raw_output_path, prompt_artifact_path,
                result_artifact_path, structured_output_json, estimated_cost_eur, usage_json,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.run_id,
                result.run_request_id,
                result.model,
                result.mode.value,
                result.status.value,
                result.raw_output_path,
                result.prompt_artifact_path,
                result.result_artifact_path,
                dump_json(result.structured_output),
                result.estimated_cost_eur,
                dump_json(result.usage),
                dump_json(result.metadata),
                result.created_at,
                result.updated_at,
            ),
            connection=connection,
        )

    def _persist_run_review(self, review: ApiRunReview) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO api_run_reviews(
                review_id, run_id, verdict, reviewer, findings_json, accepted_changes_json,
                followup_actions_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review.review_id,
                review.run_id,
                review.verdict.value,
                review.reviewer,
                dump_json(review.findings),
                dump_json(review.accepted_changes),
                dump_json(review.followup_actions),
                dump_json(review.metadata),
                review.created_at,
            ),
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO api_run_events(
                event_id, run_id, phase, severity, machine_summary, human_summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                run_id,
                phase,
                severity,
                machine_summary,
                human_summary,
                dump_json(payload),
                created_at,
            ),
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
        self._prune_pending_operator_deliveries(incoming_channel_hint=event.channel_hint, connection=connection)
        delivery: OperatorDelivery | None = None
        if self._should_enqueue_operator_delivery(incoming_channel_hint=event.channel_hint, connection=connection):
            delivery = OperatorDelivery(
                delivery_id=new_id("operator_delivery"),
                lifecycle_event_id=event.lifecycle_event_id,
                adapter="openclaw",
                surface="discord",
                channel_hint=event.channel_hint,
                status=OperatorDeliveryStatus.PENDING,
                payload=self._build_operator_delivery_payload(event),
                metadata={"run_id": run_id, "kind": kind.value},
                next_attempt_at=event.created_at,
            )
            self._persist_operator_delivery(delivery, connection=connection)
        else:
            self.journal.append(
                "api_run_operator_delivery_skipped",
                "api_runs",
                {
                    "lifecycle_event_id": event.lifecycle_event_id,
                    "run_id": run_id,
                    "kind": kind.value,
                    "channel_hint": event.channel_hint.value,
                    "reason": "pending_backlog_limit",
                },
            )
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
        if kind is RunLifecycleEventKind.RUN_FAILED:
            return OperatorChannelHint.INCIDENTS
        return OperatorChannelHint.RUNS_LIVE

    def _build_operator_delivery_payload(self, event: RunLifecycleEvent) -> dict[str, Any]:
        return {
            "version": "v1",
            "surface": "discord",
            "channel_hint": event.channel_hint.value,
            "text": self._render_operator_delivery_text(event),
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
        lines = [
            f"[Project OS] {event.title}",
            f"Mode: {event.mode.value if event.mode else 'n/a'} | Branche: {event.branch_name or 'n/a'}",
            f"Statut: {event.status.value if event.status else 'n/a'} | Phase: {event.phase or 'n/a'}",
            f"Resume: {event.summary}",
        ]
        if event.blocking_question:
            lines.append(f"Question: {event.blocking_question}")
        if event.recommended_action:
            lines.append(f"Action recommandee: {event.recommended_action}")
        if event.requires_reapproval:
            lines.append("Re-go requis: oui")
        return "\n".join(lines)

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
        max_pending = max(1, int(getattr(self.execution_policy, "operator_delivery_max_pending", 64)))
        pending_count = self._pending_operator_delivery_count(connection=connection)
        if pending_count < max_pending:
            return True
        return incoming_channel_hint is not OperatorChannelHint.RUNS_LIVE

    def _prune_pending_operator_deliveries(
        self,
        *,
        incoming_channel_hint: OperatorChannelHint,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        max_pending = max(1, int(getattr(self.execution_policy, "operator_delivery_max_pending", 64)))
        pending_count = self._pending_operator_delivery_count(connection=connection)
        if pending_count < max_pending:
            return 0
        overflow = pending_count - max_pending + 1
        prune_rows = self.database.fetchall(
            """
            SELECT delivery_id
            FROM api_run_operator_deliveries
            WHERE status = ? AND channel_hint = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (
                OperatorDeliveryStatus.PENDING.value,
                OperatorChannelHint.RUNS_LIVE.value,
                overflow,
            ),
            connection=connection,
        )
        if not prune_rows:
            return 0
        pruned_at = datetime.now(timezone.utc).isoformat()
        for row in prune_rows:
            self.database.execute(
                """
                UPDATE api_run_operator_deliveries
                SET status = ?, last_error = ?, next_attempt_at = NULL, updated_at = ?
                WHERE delivery_id = ?
                """,
                (
                    OperatorDeliveryStatus.SKIPPED.value,
                    f"pending_backlog_limit:{incoming_channel_hint.value}",
                    pruned_at,
                    str(row["delivery_id"]),
                ),
                connection=connection,
            )
        return len(prune_rows)

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
        self.database.execute(
            """
            INSERT OR REPLACE INTO completion_reports(
                report_id, run_id, verdict, summary, done_items_json, test_summary_json,
                risks_json, next_action, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.report_id,
                report.run_id,
                report.verdict,
                report.summary,
                dump_json(report.done_items),
                dump_json(report.test_summary),
                dump_json(report.risks),
                report.next_action,
                dump_json(report.metadata),
                report.created_at,
            ),
            connection=connection,
        )

    def _persist_blockage_report(self, report: BlockageReport, *, connection: sqlite3.Connection | None = None) -> None:
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "blockage_reports",
            report.report_id,
            to_jsonable(report),
        )
        report.metadata["artifact_path"] = str(artifact_path)
        self.database.execute(
            """
            INSERT OR REPLACE INTO blockage_reports(
                report_id, run_id, cause, impact, choices_json, recommendation, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.report_id,
                report.run_id,
                report.cause,
                report.impact,
                dump_json(report.choices),
                report.recommendation,
                dump_json(report.metadata),
                report.created_at,
            ),
            connection=connection,
        )

    def _persist_clarification_report(self, report: ClarificationReport, *, connection: sqlite3.Connection | None = None) -> None:
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "clarification_reports",
            report.report_id,
            to_jsonable(report),
        )
        report.metadata["artifact_path"] = str(artifact_path)
        self.database.execute(
            """
            INSERT OR REPLACE INTO clarification_reports(
                report_id, run_id, cause, impact, question_for_founder, recommended_contract_change,
                requires_reapproval, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.report_id,
                report.run_id,
                report.cause,
                report.impact,
                report.question_for_founder,
                report.recommended_contract_change,
                1 if report.requires_reapproval else 0,
                dump_json(report.metadata),
                report.created_at,
            ),
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
        if not candidate.startswith("codex/"):
            raise ValueError("API runs must target a codex/* branch")
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

    def _runtime_facts(self) -> dict[str, Any]:
        facts: dict[str, Any] = {}
        if self.paths.bootstrap_state_path.exists():
            facts["bootstrap"] = json.loads(self.paths.bootstrap_state_path.read_text(encoding="utf-8"))
        if self.paths.health_snapshot_path.exists():
            facts["health"] = json.loads(self.paths.health_snapshot_path.read_text(encoding="utf-8"))
        if self.paths.api_runs_terminal_snapshot_path.exists():
            facts["api_runs_monitor"] = json.loads(self.paths.api_runs_terminal_snapshot_path.read_text(encoding="utf-8"))
        return facts

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
            "# Contrat de sortie\n" + "\n".join(f"- {item}" for item in template_config["output_contract"]),
            "# Regles de mode\n" + "\n".join(f"- {item}" for item in template_config.get("instructions", [])),
            "# Sources de contexte",
        ]
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
        pricing = PRICING_PER_MILLION_USD.get(model, PRICING_PER_MILLION_USD.get(self.execution_policy.default_model))
        if not pricing:
            return 0.0
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        usd = ((input_tokens / 1_000_000) * pricing["input"]) + ((output_tokens / 1_000_000) * pricing["output"])
        return round(usd * USD_TO_EUR, 6)

    def _default_constraints(self) -> list[str]:
        return [
            "Travaille d'abord sur le repo et la CLI. Pas de computer use Windows pour la lane code v1.",
            "Ne modifie jamais main. Travaille sur une branche codex/*.",
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
            base.append("The patch outline is ready for Codex review and local test execution.")
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
