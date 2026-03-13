from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
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
    CommunicationMode,
    CompletionReport,
    ContextPack,
    ContextSource,
    DatasetCandidate,
    DecisionStatus,
    LearningSignalKind,
    MegaPromptTemplate,
    OperatorAudience,
    RunContract,
    RunContractStatus,
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
        learning: LearningService,
    ) -> None:
        self.database = database
        self.journal = journal
        self.paths = paths
        self.path_policy = path_policy
        self.secret_resolver = secret_resolver
        self.logger = logger
        self.execution_policy = execution_policy
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
        contract.status = RunContractStatus.APPROVED if normalized != "stop" else RunContractStatus.REJECTED
        contract.founder_decision = normalized
        contract.updated_at = datetime.now(timezone.utc).isoformat()
        if notes:
            contract.metadata["founder_notes"] = notes
        self._persist_run_contract(contract)
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
        self._persist_run_request(request)
        self._update_request_status(request.run_request_id, ApiRunStatus.RUNNING)
        if contract is not None:
            contract.status = RunContractStatus.EXECUTED
            contract.updated_at = datetime.now(timezone.utc).isoformat()
            contract.metadata["last_run_request_id"] = request.run_request_id
            self._persist_run_contract(contract)
        self.logger.log(
            "INFO",
            "api_run_started",
            run_request_id=request.run_request_id,
            mode=resolved_mode.value,
            branch_name=request.branch_name,
        )
        self._record_run_event(
            run_id=request.run_request_id,
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
        )
        self.journal.append(
            "api_run_started",
            "api_runs",
            {
                "run_request_id": request.run_request_id,
                "context_pack_id": context_pack.context_pack_id,
                "prompt_template_id": prompt_template.prompt_template_id,
                "mode": resolved_mode.value,
                "branch_name": request.branch_name,
            },
        )

        run_id = new_id("api_run")
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
                estimated_cost_eur=self._estimate_cost_eur(model=str(raw_payload.get("model") or prompt_template.model), usage=usage),
                usage=usage,
                metadata={"review_package_path": str(review_package_path)},
            )
            self._persist_run_result(result)
            self._detect_noise_signal(run_id=result.run_id, structured_output=structured_output, request=request)
            self._update_request_status(request.run_request_id, ApiRunStatus.COMPLETED)
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
            )
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
            self._persist_run_result(result)
            self._update_request_status(request.run_request_id, ApiRunStatus.FAILED)
            blockage = self._build_blockage_report(result=result, request=request, error=str(exc))
            self._persist_blockage_report(blockage)
            self._record_run_event(
                run_id=run_id,
                phase="bloque",
                severity="error",
                machine_summary=f"Le run a echoue: {str(exc)}",
                human_summary=f"Blocage reel detecte: {blockage.cause}",
                payload={"blockage_report_id": blockage.report_id, "error": str(exc)},
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
        return {"run_id": run_id, "artifacts": [to_jsonable(item) for item in artifacts]}

    def monitor_snapshot(self, *, limit: int = 5) -> dict[str, Any]:
        rows = self.database.fetchall(
            """
            SELECT
                q.run_request_id,
                q.mode,
                q.objective,
                q.branch_name,
                q.status,
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
        cost_rows = self.database.fetchall(
            "SELECT estimated_cost_eur, created_at FROM api_run_results ORDER BY created_at DESC",
        )
        reviews: dict[str, Any] = {}
        for row in review_rows:
            reviews.setdefault(str(row["run_id"]), row)
        events: dict[str, Any] = {}
        for row in event_rows:
            events.setdefault(str(row["run_id"]), row)
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
                    "phase": str(event_row["phase"]) if event_row else None,
                    "machine_summary": str(event_row["machine_summary"]) if event_row else None,
                    "human_summary": str(event_row["human_summary"]) if event_row and event_row["human_summary"] else None,
                }
            )

        current_contract_row = self.database.fetchone(
            "SELECT * FROM api_run_contracts ORDER BY created_at DESC LIMIT 1",
        )
        current_contract = None
        if current_contract_row is not None:
            current_contract = {
                "contract_id": str(current_contract_row["contract_id"]),
                "mode": str(current_contract_row["mode"]),
                "branch_name": str(current_contract_row["branch_name"]),
                "status": str(current_contract_row["status"]),
                "summary": str(current_contract_row["summary"]),
                "estimated_cost_eur": float(current_contract_row["estimated_cost_eur"]),
                "founder_decision": str(current_contract_row["founder_decision"]) if current_contract_row["founder_decision"] else None,
                "created_at": str(current_contract_row["created_at"]),
            }

        snapshot = {
            "current_run": items[0] if items else None,
            "current_contract": current_contract,
            "budget": {
                "daily_spend_estimate_eur": round(daily_cost, 6),
                "monthly_spend_estimate_eur": round(monthly_cost, 6),
                "daily_soft_limit_eur": self.execution_policy.daily_soft_limit_eur,
                "monthly_limit_eur": self.execution_policy.monthly_limit_eur,
            },
            "latest_runs": items,
        }
        snapshot_path = self.path_policy.ensure_allowed_write(self.paths.api_runs_terminal_snapshot_path)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        return snapshot

    def render_terminal_dashboard(self, *, limit: int = 5) -> str:
        snapshot = self.monitor_snapshot(limit=limit)
        lines = [
            "Project OS Runs API",
            "====================",
            f"Depense du jour: {snapshot['budget']['daily_spend_estimate_eur']:.4f} EUR / {snapshot['budget']['daily_soft_limit_eur']:.2f} EUR",
            f"Depense du mois: {snapshot['budget']['monthly_spend_estimate_eur']:.4f} EUR / {snapshot['budget']['monthly_limit_eur']:.2f} EUR",
            "",
        ]
        current = snapshot.get("current_run")
        if current:
            lines.extend(
                [
                    f"Run courant: {current['run_id'] or 'en_attente_de_resultat'}",
                    f"Mode: {current['mode']}",
                    f"Branche: {current['branch_name']}",
                    f"Statut: {current['status']}",
                    f"Contrat: {current['contract_status'] or 'sans_contrat'}",
                    f"Phase: {current['phase'] or 'preparation'}",
                    f"Derniere revue: {current['review_verdict'] or 'pending'}",
                    f"Resume machine: {current['machine_summary'] or 'aucun evenement live'}",
                    f"Artefacts: {current['raw_output_path'] or 'n/a'} | {current['structured_output_path'] or 'n/a'}",
                    "",
                ]
            )
        current_contract = snapshot.get("current_contract")
        if current_contract:
            lines.extend(
                [
                    "Contrat courant",
                    "---------------",
                    f"Contrat: {current_contract['contract_id']}",
                    f"Statut: {current_contract['status']}",
                    f"Decision fondateur: {current_contract['founder_decision'] or 'en_attente'}",
                    f"Objectif: {current_contract['summary']}",
                    "",
                ]
            )
        lines.append("Derniers runs")
        lines.append("-------------")
        for item in snapshot["latest_runs"]:
            lines.append(
                f"- {item['created_at']} | {item['mode']} | {item['branch_name']} | {item['status']} | "
                f"{item['estimated_cost_eur']:.4f} EUR | phase={item['phase'] or 'preparation'} | review={item['review_verdict'] or 'pending'}"
            )
        if not snapshot["latest_runs"]:
            lines.append("- aucun run api pour le moment")
        return "\n".join(lines)

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
        structured_output = json.loads(output_text)
        usage = raw_payload.get("usage")
        if usage is None and hasattr(response_payload, "usage") and getattr(response_payload, "usage") is not None:
            usage_obj = getattr(response_payload, "usage")
            usage = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else dict(usage_obj)
        return structured_output, raw_payload, usage or {}

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

    def _persist_run_contract(self, contract: RunContract) -> None:
        artifact_path = self._write_runtime_json(
            self.paths.api_runs_root / "contracts",
            contract.contract_id,
            to_jsonable(contract),
        )
        contract.metadata["artifact_path"] = str(artifact_path)
        self.database.execute(
            """
            INSERT OR REPLACE INTO api_run_contracts(
                contract_id, context_pack_id, prompt_template_id, mode, objective, branch_name,
                target_profile, model, reasoning_effort, communication_mode, speech_policy,
                operator_language, audience, expected_outputs_json, summary, non_goals_json,
                success_criteria_json, estimated_cost_eur, founder_decision, status, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contract.contract_id,
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
                contract.status.value,
                dump_json(contract.metadata),
                contract.created_at,
                contract.updated_at,
            ),
        )

    def _persist_run_request(self, request: ApiRunRequest) -> None:
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
        )

    def _persist_run_result(self, result: ApiRunResult) -> None:
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

    def _persist_completion_report(self, report: CompletionReport) -> None:
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
        )

    def _persist_blockage_report(self, report: BlockageReport) -> None:
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
        )

    def _update_request_status(self, run_request_id: str, status: ApiRunStatus) -> None:
        self.database.execute(
            "UPDATE api_run_requests SET status = ?, updated_at = ? WHERE run_request_id = ?",
            (status.value, datetime.now(timezone.utc).isoformat(), run_request_id),
        )

    def _update_result_status(self, run_id: str, status: ApiRunStatus) -> None:
        self.database.execute(
            "UPDATE api_run_results SET status = ?, updated_at = ? WHERE run_id = ?",
            (status.value, datetime.now(timezone.utc).isoformat(), run_id),
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
            "Retourne uniquement du JSON structure conforme au schema. Ne bavarde pas pendant l'execution. Produis une sortie exploitable par un inspecteur humain, claire en francais pour les resumes destines a l'operateur, et garde une voie repo/CLI first."
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
