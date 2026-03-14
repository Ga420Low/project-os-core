from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from ..database import CanonicalDatabase, dump_json
from ..models import (
    ApiRunMode,
    ApiRunRequest,
    ApiRunStatus,
    CommunicationMode,
    new_id,
    to_jsonable,
    utc_now_iso,
)
from ..runtime.journal import LocalJournal

if TYPE_CHECKING:
    from ..api_runs.service import ApiRunService
    from ..models import MegaPromptTemplate, ApiRunRequest, ContextPack


@dataclass(slots=True)
class MissionStep:
    step_index: int
    mode: ApiRunMode
    objective: str
    depends_on_previous: bool = True
    skip_on_previous_failure: bool = False


@dataclass(slots=True)
class MissionChain:
    chain_id: str
    objective: str
    steps: list[MissionStep]
    current_step_index: int = 0
    status: str = "running"
    total_cost_eur: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


STANDARD_CHAINS: dict[str, list[MissionStep]] = {
    "full_refactor": [
        MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit complet du module cible"),
        MissionStep(step_index=1, mode=ApiRunMode.DESIGN, objective="Plan de refactoring base sur l'audit"),
        MissionStep(step_index=2, mode=ApiRunMode.PATCH_PLAN, objective="Patch plan detaille"),
        MissionStep(step_index=3, mode=ApiRunMode.GENERATE_PATCH, objective="Generation du patch"),
    ],
    "audit_then_patch": [
        MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit du code existant"),
        MissionStep(step_index=1, mode=ApiRunMode.GENERATE_PATCH, objective="Patch base sur l'audit"),
    ],
    "design_only": [
        MissionStep(step_index=0, mode=ApiRunMode.AUDIT, objective="Audit rapide"),
        MissionStep(step_index=1, mode=ApiRunMode.DESIGN, objective="Design complet"),
    ],
}


class MissionChainService:
    def __init__(self, *, database: CanonicalDatabase, api_runs: ApiRunService, journal: LocalJournal) -> None:
        self.database = database
        self.api_runs = api_runs
        self.journal = journal

    def create_chain(
        self,
        *,
        objective: str,
        branch_name: str,
        chain_template: str | None = None,
        steps: list[MissionStep] | None = None,
        target_profile: str | None = None,
        skill_tags: list[str] | None = None,
        source_paths: list[str] | None = None,
        constraints: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MissionChain:
        resolved_steps = self._resolve_steps(chain_template=chain_template, steps=steps)
        chain = MissionChain(
            chain_id=new_id("mission_chain"),
            objective=objective.strip(),
            steps=resolved_steps,
            metadata={
                "branch_name": branch_name,
                "target_profile": target_profile,
                "skill_tags": list(skill_tags or ["mission_chain"]),
                "source_paths": list(source_paths or []),
                "constraints": list(constraints or []),
                "acceptance_criteria": list(acceptance_criteria or []),
                "template": chain_template or "custom",
                **(metadata or {}),
            },
        )
        self._persist_chain(chain)
        self.journal.append(
            "mission_chain_created",
            "mission_chain",
            {
                "chain_id": chain.chain_id,
                "objective": chain.objective,
                "branch_name": branch_name,
                "step_count": len(chain.steps),
                "template": chain.metadata.get("template"),
            },
        )
        return chain

    def advance_chain(
        self,
        chain_id: str,
        *,
        response_runner: Callable[[ApiRunRequest, MegaPromptTemplate, ContextPack], Any] | None = None,
    ) -> dict[str, Any]:
        chain = self.chain_status(chain_id)
        if chain.status != "running":
            return {"status": chain.status, "action": "none", "chain_id": chain.chain_id}

        current_step = chain.steps[chain.current_step_index]
        step_runs = self._get_runs_for_step(chain.chain_id, chain.current_step_index)
        if not step_runs:
            launched = self._launch_step(chain=chain, step=current_step, previous_output=None, response_runner=response_runner)
            if launched.get("guardian_blocked"):
                return {
                    "status": "paused",
                    "action": "guardian_blocked",
                    "chain_id": chain.chain_id,
                    "step": to_jsonable(current_step),
                    "payload": launched,
                }
            return {
                "status": "running",
                "action": "launch_step",
                "chain_id": chain.chain_id,
                "step": to_jsonable(current_step),
                "payload": launched,
            }

        last_run = step_runs[-1]
        last_status = str(last_run["status"])
        if last_status in {ApiRunStatus.COMPLETED.value, ApiRunStatus.REVIEWED.value}:
            next_index = chain.current_step_index + 1
            if next_index >= len(chain.steps):
                completed = self._update_chain(
                    chain,
                    status="completed",
                    total_cost_eur=self._compute_total_cost_eur(chain.chain_id),
                )
                self.journal.append(
                    "mission_chain_completed",
                    "mission_chain",
                    {"chain_id": chain.chain_id, "total_cost_eur": completed.total_cost_eur},
                )
                return {
                    "status": "completed",
                    "action": "none",
                    "chain_id": chain.chain_id,
                    "total_cost_eur": completed.total_cost_eur,
                }
            next_step = chain.steps[next_index]
            advanced = self._update_chain(
                chain,
                current_step_index=next_index,
                total_cost_eur=self._compute_total_cost_eur(chain.chain_id),
            )
            launched = self._launch_step(
                chain=advanced,
                step=next_step,
                previous_output=last_run.get("structured_output"),
                response_runner=response_runner,
            )
            if launched.get("guardian_blocked"):
                return {
                    "status": "paused",
                    "action": "guardian_blocked",
                    "chain_id": chain.chain_id,
                    "step": to_jsonable(next_step),
                    "previous_output": last_run.get("structured_output"),
                    "payload": launched,
                }
            return {
                "status": "running",
                "action": "launch_step",
                "chain_id": chain.chain_id,
                "step": to_jsonable(next_step),
                "previous_output": last_run.get("structured_output"),
                "payload": launched,
            }

        if last_status == ApiRunStatus.FAILED.value:
            next_index = chain.current_step_index + 1
            if next_index < len(chain.steps) and chain.steps[next_index].skip_on_previous_failure:
                next_step = chain.steps[next_index]
                advanced = self._update_chain(
                    chain,
                    current_step_index=next_index,
                    total_cost_eur=self._compute_total_cost_eur(chain.chain_id),
                    metadata={
                        **chain.metadata,
                        "last_skipped_step_index": chain.current_step_index,
                        "skip_reason": "previous_step_failed",
                    },
                )
                launched = self._launch_step(
                    chain=advanced,
                    step=next_step,
                    previous_output=last_run.get("structured_output"),
                    response_runner=response_runner,
                )
                if launched.get("guardian_blocked"):
                    return {
                        "status": "paused",
                        "action": "guardian_blocked",
                        "chain_id": chain.chain_id,
                        "step": to_jsonable(next_step),
                        "skipped_failed_step_index": chain.current_step_index,
                        "payload": launched,
                    }
                return {
                    "status": "running",
                    "action": "launch_step",
                    "chain_id": chain.chain_id,
                    "step": to_jsonable(next_step),
                    "skipped_failed_step_index": chain.current_step_index,
                    "payload": launched,
                }
            failed = self.fail_chain(chain.chain_id, reason=f"step_{chain.current_step_index}_failed")
            return {"status": failed.status, "action": "none", "chain_id": chain.chain_id, "reason": "step_failed"}

        return {"status": "running", "action": "wait", "chain_id": chain.chain_id}

    def chain_status(self, chain_id: str) -> MissionChain:
        row = self.database.fetchone("SELECT * FROM mission_chains WHERE chain_id = ?", (chain_id,))
        if row is None:
            raise KeyError(f"Unknown mission chain: {chain_id}")
        return MissionChain(
            chain_id=str(row["chain_id"]),
            objective=str(row["objective"]),
            steps=self._deserialize_steps(str(row["steps_json"])),
            current_step_index=int(row["current_step_index"]),
            status=str(row["status"]),
            total_cost_eur=float(row["total_cost_eur"]),
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_chains(self, *, status: str | None = None) -> list[MissionChain]:
        if status:
            rows = self.database.fetchall(
                "SELECT * FROM mission_chains WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            )
        else:
            rows = self.database.fetchall("SELECT * FROM mission_chains ORDER BY updated_at DESC")
        return [
            MissionChain(
                chain_id=str(row["chain_id"]),
                objective=str(row["objective"]),
                steps=self._deserialize_steps(str(row["steps_json"])),
                current_step_index=int(row["current_step_index"]),
                status=str(row["status"]),
                total_cost_eur=float(row["total_cost_eur"]),
                metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def fail_chain(self, chain_id: str, *, reason: str) -> MissionChain:
        chain = self.chain_status(chain_id)
        failed = self._update_chain(
            chain,
            status="failed",
            total_cost_eur=self._compute_total_cost_eur(chain_id),
            metadata={**chain.metadata, "failure_reason": reason},
        )
        self.journal.append(
            "mission_chain_failed",
            "mission_chain",
            {"chain_id": chain_id, "reason": reason},
        )
        return failed

    def pause_chain(self, chain_id: str) -> MissionChain:
        chain = self.chain_status(chain_id)
        paused = self._update_chain(chain, status="paused", total_cost_eur=self._compute_total_cost_eur(chain_id))
        self.journal.append(
            "mission_chain_paused",
            "mission_chain",
            {"chain_id": chain_id, "current_step_index": paused.current_step_index},
        )
        return paused

    def _launch_step(
        self,
        *,
        chain: MissionChain,
        step: MissionStep,
        previous_output: dict[str, Any] | None,
        response_runner: Callable[[ApiRunRequest, MegaPromptTemplate, ContextPack], Any] | None,
    ) -> dict[str, Any]:
        branch_name = str(chain.metadata.get("branch_name") or "")
        if not branch_name:
            raise ValueError("mission chain requires branch_name metadata to launch a step")
        target_profile = str(chain.metadata.get("target_profile") or "") or None
        base_skill_tags = list(chain.metadata.get("skill_tags") or ["mission_chain"])
        if step.mode.value not in base_skill_tags:
            base_skill_tags.append(step.mode.value)
        step_metadata = {
            **chain.metadata,
            "mission_chain_id": chain.chain_id,
            "mission_chain_step": True,
            "mission_step_index": step.step_index,
            "mission_chain_objective": chain.objective,
            "mission_chain_step_objective": step.objective,
        }
        if previous_output is not None:
            step_metadata["mission_chain_previous_output"] = previous_output
        context_pack = self.api_runs.build_context_pack(
            mode=step.mode,
            objective=f"{step.objective}. Mission objective: {chain.objective}",
            branch_name=branch_name,
            skill_tags=base_skill_tags,
            target_profile=target_profile,
            source_paths=list(chain.metadata.get("source_paths") or []),
            constraints=list(chain.metadata.get("constraints") or []),
            acceptance_criteria=list(chain.metadata.get("acceptance_criteria") or []),
            metadata=step_metadata,
        )
        prompt_template = self.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
        contract = self.api_runs.create_run_contract(
            context_pack_id=context_pack.context_pack_id,
            prompt_template_id=prompt_template.prompt_template_id,
            target_profile=target_profile,
            metadata=step_metadata,
        )
        provisional_request = ApiRunRequest(
            run_request_id=new_id("run_request"),
            context_pack_id=context_pack.context_pack_id,
            prompt_template_id=prompt_template.prompt_template_id,
            mode=step.mode,
            objective=context_pack.objective,
            branch_name=context_pack.branch_name,
            target_profile=target_profile,
            mission_chain_id=chain.chain_id,
            mission_step_index=step.step_index,
            skill_tags=context_pack.skill_tags,
            expected_outputs=list(prompt_template.output_contract),
            communication_mode=CommunicationMode.BUILDER,
            speech_policy=self.api_runs.execution_policy.default_run_speech_policy,
            operator_language=self.api_runs.execution_policy.operator_language,
            audience=self.api_runs.execution_policy.operator_audience,
            run_contract_required=True,
            contract_id=contract.contract_id,
            metadata=dict(step_metadata),
        )
        can_proceed, blocking_reason = self.api_runs._guardian_pre_spend_check(
            request=provisional_request,
            prompt_template=prompt_template,
        )
        if not can_proceed:
            paused = self._update_chain(
                chain,
                status="paused",
                total_cost_eur=self._compute_total_cost_eur(chain.chain_id),
                metadata={
                    **chain.metadata,
                    "guardian_blocking_reason": blocking_reason,
                    "guardian_blocked_step_index": step.step_index,
                },
            )
            self.journal.append(
                "mission_chain_guardian_blocked",
                "mission_chain",
                {
                    "chain_id": chain.chain_id,
                    "step_index": step.step_index,
                    "blocking_reason": blocking_reason,
                    "status": paused.status,
                    "contract_id": contract.contract_id,
                },
            )
            return {
                "chain_id": chain.chain_id,
                "step_index": step.step_index,
                "mode": step.mode.value,
                "contract_id": contract.contract_id,
                "status": ApiRunStatus.CLARIFICATION_REQUIRED.value,
                "guardian_blocked": True,
                "blocking_reason": blocking_reason,
            }
        self.api_runs.approve_run_contract(
            contract_id=contract.contract_id,
            founder_decision="go",
            notes=f"Auto-approved from mission chain {chain.chain_id} step {step.step_index}.",
        )
        payload = self.api_runs.execute_run(
            contract_id=contract.contract_id,
            metadata=step_metadata,
            response_runner=response_runner,
            mission_chain_id=chain.chain_id,
            mission_step_index=step.step_index,
        )
        result = payload.get("result")
        if result is not None and getattr(result, "status", None) == ApiRunStatus.CLARIFICATION_REQUIRED:
            guardian_blocked = bool(getattr(result, "metadata", {}).get("guardian_blocked", False))
            if guardian_blocked:
                paused = self.pause_chain(chain.chain_id)
                self.journal.append(
                    "mission_chain_guardian_blocked",
                    "mission_chain",
                    {
                        "chain_id": chain.chain_id,
                        "step_index": step.step_index,
                        "blocking_reason": getattr(result, "metadata", {}).get("blocking_reason"),
                        "status": paused.status,
                    },
                )
        total_cost = self._compute_total_cost_eur(chain.chain_id)
        self._update_chain(self.chain_status(chain.chain_id), total_cost_eur=total_cost)
        self.journal.append(
            "mission_chain_step_launched",
            "mission_chain",
            {
                "chain_id": chain.chain_id,
                "step_index": step.step_index,
                "mode": step.mode.value,
                "run_id": payload["result"].run_id,
                "status": payload["result"].status.value,
            },
        )
        return {
            "chain_id": chain.chain_id,
            "step_index": step.step_index,
            "mode": step.mode.value,
            "contract_id": contract.contract_id,
            "run_id": payload["result"].run_id,
            "run_request_id": payload["request"].run_request_id,
            "status": payload["result"].status.value,
            "estimated_cost_eur": float(payload["result"].estimated_cost_eur),
        }

    def _get_runs_for_step(self, chain_id: str, step_index: int) -> list[dict[str, Any]]:
        rows = self.database.fetchall(
            """
            SELECT r.run_id, r.status, r.structured_output_json, r.estimated_cost_eur, r.created_at, r.updated_at
            FROM api_run_results r
            JOIN api_run_requests q ON q.run_request_id = r.run_request_id
            WHERE q.mission_chain_id = ? AND q.mission_step_index = ?
            ORDER BY r.created_at ASC
            """,
            (chain_id, step_index),
        )
        return [
            {
                "run_id": str(row["run_id"]),
                "status": str(row["status"]),
                "structured_output": json.loads(row["structured_output_json"]) if row["structured_output_json"] else {},
                "estimated_cost_eur": float(row["estimated_cost_eur"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def _compute_total_cost_eur(self, chain_id: str) -> float:
        row = self.database.fetchone(
            """
            SELECT COALESCE(SUM(r.estimated_cost_eur), 0.0) AS total_cost_eur
            FROM api_run_results r
            JOIN api_run_requests q ON q.run_request_id = r.run_request_id
            WHERE q.mission_chain_id = ?
            """,
            (chain_id,),
        )
        return round(float(row["total_cost_eur"]) if row else 0.0, 6)

    def _persist_chain(self, chain: MissionChain) -> None:
        self.database.upsert(
            "mission_chains",
            {
                "chain_id": chain.chain_id,
                "objective": chain.objective,
                "steps_json": dump_json([to_jsonable(step) for step in chain.steps]),
                "current_step_index": chain.current_step_index,
                "status": chain.status,
                "total_cost_eur": chain.total_cost_eur,
                "metadata_json": dump_json(chain.metadata),
                "created_at": chain.created_at,
                "updated_at": chain.updated_at,
            },
            conflict_columns="chain_id",
            immutable_columns=["created_at"],
        )

    def _update_chain(
        self,
        chain: MissionChain,
        *,
        current_step_index: int | None = None,
        status: str | None = None,
        total_cost_eur: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MissionChain:
        updated = MissionChain(
            chain_id=chain.chain_id,
            objective=chain.objective,
            steps=list(chain.steps),
            current_step_index=current_step_index if current_step_index is not None else chain.current_step_index,
            status=status or chain.status,
            total_cost_eur=total_cost_eur if total_cost_eur is not None else chain.total_cost_eur,
            metadata=metadata if metadata is not None else dict(chain.metadata),
            created_at=chain.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._persist_chain(updated)
        return updated

    @staticmethod
    def _resolve_steps(chain_template: str | None, steps: list[MissionStep] | None) -> list[MissionStep]:
        if steps:
            return [
                MissionStep(
                    step_index=index,
                    mode=step.mode,
                    objective=step.objective,
                    depends_on_previous=step.depends_on_previous,
                    skip_on_previous_failure=step.skip_on_previous_failure,
                )
                for index, step in enumerate(steps)
            ]
        if not chain_template:
            raise ValueError("chain_template or steps is required")
        template_steps = STANDARD_CHAINS.get(chain_template)
        if template_steps is None:
            raise KeyError(f"Unknown mission chain template: {chain_template}")
        return [
            MissionStep(
                step_index=index,
                mode=step.mode,
                objective=step.objective,
                depends_on_previous=step.depends_on_previous,
                skip_on_previous_failure=step.skip_on_previous_failure,
            )
            for index, step in enumerate(template_steps)
        ]

    @staticmethod
    def _deserialize_steps(raw_steps_json: str) -> list[MissionStep]:
        payload = json.loads(raw_steps_json)
        return [
            MissionStep(
                step_index=int(item["step_index"]),
                mode=ApiRunMode(str(item["mode"])),
                objective=str(item["objective"]),
                depends_on_previous=bool(item.get("depends_on_previous", True)),
                skip_on_previous_failure=bool(item.get("skip_on_previous_failure", False)),
            )
            for item in payload
        ]
