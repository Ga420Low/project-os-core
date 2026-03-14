from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ..database import CanonicalDatabase, dump_json
from ..memory.store import MemoryStore
from ..models import (
    ChannelEvent,
    CommunicationMode,
    DiscordChannelClass,
    DiscordRunCard,
    GatewayDispatchResult,
    OperatorAudience,
    OperatorEnvelope,
    OperatorReply,
    PromotionAction,
    RoutingDecision,
    RoutingDecisionTrace,
    new_id,
    to_jsonable,
)
from ..router.service import MissionRouter
from ..runtime.journal import LocalJournal
from ..session.state import PersistentSessionState, ResolvedIntent
from .promotion import SelectiveSyncPromoter


class GatewayService:
    """Operator-facing ingress that stays policy-safe and memory-aware."""

    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        router: MissionRouter,
        memory: MemoryStore,
        session_state: PersistentSessionState,
        secret_resolver=None,
        selective_sync: SelectiveSyncPromoter | None = None,
    ) -> None:
        self.database = database
        self.journal = journal
        self.router = router
        self.memory = memory
        self.session_state = session_state
        self.secret_resolver = secret_resolver
        self.selective_sync = selective_sync or SelectiveSyncPromoter()

    def dispatch_event(
        self,
        event: ChannelEvent,
        *,
        target_profile: str | None = None,
        requested_worker: str | None = None,
        risk_class=None,
        metadata: dict | None = None,
    ) -> GatewayDispatchResult:
        candidate = self.selective_sync.build_candidate(event)
        promotion = self.selective_sync.decide_promotion(candidate)
        human_artifacts = self.selective_sync.build_human_artifacts(event)
        candidate.metadata["human_artifacts"] = [to_jsonable(item) for item in human_artifacts]
        channel_class = self._channel_class_for(event.message.channel, event.message.thread_ref.parent_thread_id)
        communication_mode = self._communication_mode_for(candidate.classification, channel_class)
        envelope = OperatorEnvelope(
            envelope_id=new_id("envelope"),
            actor_id=event.message.actor_id,
            channel=event.message.channel,
            objective=event.message.text.strip() or candidate.summary,
            target_profile=target_profile,
            requested_worker=requested_worker,
            requested_risk_class=risk_class,
            communication_mode=communication_mode,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "channel_event_id": event.event_id,
                "message_kind": candidate.classification.value,
                "channel_class": channel_class.value,
                "thread_ref": to_jsonable(event.message.thread_ref),
                "attachments": [to_jsonable(item) for item in event.message.attachments],
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                **(metadata or {}),
            },
        )
        snapshot = self.session_state.load()
        resolved = self.session_state.resolve_intent(event.message.text, snapshot=snapshot)
        if resolved is not None:
            self._persist_channel_event(event, candidate)
            self._persist_promotion(candidate, promotion)
            action_result = self._execute_resolved_intent(resolved)
            promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
            reply = self._build_session_reply(event, envelope.envelope_id, resolved, action_result)
            dispatch = self._build_session_dispatch(
                event=event,
                envelope=envelope,
                resolved=resolved,
                action_result=action_result,
                promoted_memory_ids=promoted_memory_ids,
                candidate_id=candidate.candidate_id,
                promotion_decision_id=promotion.promotion_decision_id,
                reply=reply,
                channel_class=channel_class,
                human_artifacts=human_artifacts,
            )
            self._persist_dispatch(dispatch)
            self.journal.append(
                "gateway_session_dispatch_completed",
                "gateway",
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "channel_event_id": event.event_id,
                    "resolved_action": resolved.action,
                    "target_id": resolved.target_id,
                    "promoted_memory_count": len(promoted_memory_ids),
                },
            )
            return dispatch
        intent = self.router.envelope_to_intent(envelope)
        decision, trace, mission_run = self.router.route_intent(intent, persist=True)
        promoted_memory_ids = self._apply_selective_sync(candidate, promotion)

        # For simple Discord chat routes, call GPT directly for an intelligent response
        if decision.allowed and decision.route_reason == "discord_simple_route":
            gpt_response = self._call_simple_chat(
                message=event.message.text.strip(),
            )
            if gpt_response:
                reply = OperatorReply(
                    reply_id=new_id("reply"),
                    channel=event.message.channel,
                    envelope_id=envelope.envelope_id,
                    thread_ref=event.message.thread_ref,
                    summary=gpt_response,
                    mission_run_id=mission_run.mission_run_id if mission_run else None,
                    decision_id=decision.decision_id,
                    reply_kind="chat_response",
                    communication_mode=decision.communication_mode,
                    operator_language=decision.operator_language,
                    audience=decision.audience,
                    metadata={"surface": event.surface, "speech_policy": decision.speech_policy.value},
                )
            else:
                reply = self._build_reply(event, envelope.envelope_id, decision, mission_run.mission_run_id if mission_run else None)
        else:
            reply = self._build_reply(event, envelope.envelope_id, decision, mission_run.mission_run_id if mission_run else None)
        run_card = self._build_run_card(
            decision=decision,
            channel_class=channel_class,
            objective=envelope.objective,
            mission_run_id=mission_run.mission_run_id if mission_run else None,
        )

        self._persist_channel_event(event, candidate)
        self._persist_promotion(candidate, promotion)
        dispatch = GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=event.event_id,
            envelope_id=envelope.envelope_id,
            intent_id=intent.intent_id,
            decision_id=decision.decision_id,
            mission_run_id=mission_run.mission_run_id if mission_run else None,
            operator_reply=reply,
            promoted_memory_ids=promoted_memory_ids,
            memory_candidate_id=candidate.candidate_id,
            promotion_decision_id=promotion.promotion_decision_id,
            discord_run_card=to_jsonable(run_card),
            metadata={
                "routing_trace_id": trace.trace_id,
                "classification": candidate.classification.value,
                "reply_kind": reply.reply_kind,
                "channel_class": channel_class.value,
                "communication_mode": communication_mode.value,
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
            },
        )
        self._persist_dispatch(dispatch)
        self.journal.append(
            "gateway_dispatch_completed",
            "gateway",
            {
                "dispatch_id": dispatch.dispatch_id,
                "channel_event_id": event.event_id,
                "decision_id": decision.decision_id,
                "mission_run_id": dispatch.mission_run_id,
                "promoted_memory_count": len(promoted_memory_ids),
            },
        )
        return dispatch

    def _execute_resolved_intent(self, resolved: ResolvedIntent) -> dict:
        if resolved.action == "approve_contract":
            return self._approve_contract(resolved.target_id)
        if resolved.action == "reject_contract":
            return self._reject_contract(resolved.target_id)
        if resolved.action == "answer_clarification":
            return self._answer_clarification(resolved.target_id, resolved.metadata.get("answer"))
        if resolved.action == "reject_clarification":
            return self._reject_clarification(resolved.target_id)
        if resolved.action == "guardian_override":
            return self._guardian_override(resolved.target_id)
        if resolved.action == "status_request":
            snapshot = self.session_state.load()
            return {"action": "status_request", "status": "ok", "snapshot": to_jsonable(snapshot)}
        return {"action": resolved.action, "status": "unhandled"}

    def _approve_contract(self, contract_id: str | None) -> dict[str, object]:
        if not contract_id:
            return {"action": "approve_contract", "status": "missing_target"}
        contract = self.session_state.api_runs.approve_run_contract(
            contract_id=contract_id,
            founder_decision="go",
            notes="Approved from Discord persistent session state.",
        )
        self.journal.append(
            "session_contract_approved",
            "gateway",
            {"contract_id": contract.contract_id, "branch_name": contract.branch_name},
        )
        run_result: dict[str, object] = {}
        try:
            payload = self.session_state.api_runs.execute_run(contract_id=contract.contract_id)
            result = payload.get("result")
            run_result = {
                "run_launched": True,
                "run_id": getattr(result, "run_id", None),
                "run_status": getattr(result, "status", None),
                "estimated_cost_eur": getattr(result, "estimated_cost_eur", None),
            }
            self.journal.append(
                "session_contract_run_launched",
                "gateway",
                {
                    "contract_id": contract.contract_id,
                    "run_id": getattr(result, "run_id", None),
                },
            )
        except Exception as exc:
            run_result = {"run_launched": False, "run_error": str(exc)}
            self.journal.append(
                "session_contract_run_failed",
                "gateway",
                {"contract_id": contract.contract_id, "error": str(exc)},
            )
        return {
            "action": "approve_contract",
            "status": "approved_and_launched" if run_result.get("run_launched") else "approved",
            "contract_id": contract.contract_id,
            "branch_name": contract.branch_name,
            "estimated_cost_eur": contract.estimated_cost_eur,
            "run_id": run_result.get("run_id"),
            **run_result,
        }

    def _reject_contract(self, contract_id: str | None) -> dict[str, object]:
        if not contract_id:
            return {"action": "reject_contract", "status": "missing_target"}
        contract = self.session_state.api_runs.approve_run_contract(
            contract_id=contract_id,
            founder_decision="stop",
            notes="Rejected from Discord persistent session state.",
        )
        self.journal.append(
            "session_contract_rejected",
            "gateway",
            {"contract_id": contract.contract_id, "branch_name": contract.branch_name},
        )
        return {
            "action": "reject_contract",
            "status": "rejected",
            "contract_id": contract.contract_id,
            "branch_name": contract.branch_name,
        }

    def _answer_clarification(self, report_id: str | None, answer: str | None) -> dict[str, object]:
        context = self._load_clarification_context(report_id)
        resolution = answer or "approved"
        report_metadata = self._update_clarification_resolution(
            report_id=str(context["report_id"]),
            resolution="approved",
            extra_metadata={"answer": resolution, "resolution_source": "discord"},
        )
        contract_id = str(context["contract_id"]) if context["contract_id"] else None
        if contract_id:
            self.session_state.api_runs.approve_run_contract(
                contract_id=contract_id,
                founder_decision="go_avec_correction",
                notes=f"Clarification resolved from Discord: {resolution}",
            )
        self.journal.append(
            "session_clarification_answered",
            "gateway",
            {"report_id": context["report_id"], "run_id": context["run_id"], "answer": resolution},
        )
        return {
            "action": "answer_clarification",
            "status": "recorded",
            "report_id": str(context["report_id"]),
            "run_id": str(context["run_id"]),
            "branch_name": str(context["branch_name"]),
            "metadata": report_metadata,
        }

    def _reject_clarification(self, report_id: str | None) -> dict[str, object]:
        context = self._load_clarification_context(report_id)
        report_metadata = self._update_clarification_resolution(
            report_id=str(context["report_id"]),
            resolution="rejected",
            extra_metadata={"answer": "rejected", "resolution_source": "discord"},
        )
        contract_id = str(context["contract_id"]) if context["contract_id"] else None
        if contract_id:
            self.session_state.api_runs.approve_run_contract(
                contract_id=contract_id,
                founder_decision="stop",
                notes="Clarification rejected from Discord.",
            )
        self.journal.append(
            "session_clarification_rejected",
            "gateway",
            {"report_id": context["report_id"], "run_id": context["run_id"]},
        )
        return {
            "action": "reject_clarification",
            "status": "recorded",
            "report_id": str(context["report_id"]),
            "run_id": str(context["run_id"]),
            "branch_name": str(context["branch_name"]),
            "metadata": report_metadata,
        }

    def _guardian_override(self, report_id: str | None) -> dict[str, object]:
        context = self._load_clarification_context(report_id)
        existing_metadata = dict(context["metadata"])
        if not existing_metadata.get("guardian_blocking_reason"):
            return {
                "action": "guardian_override",
                "status": "not_guardian_clarification",
                "report_id": str(context["report_id"]),
            }
        report_metadata = self._update_clarification_resolution(
            report_id=str(context["report_id"]),
            resolution="guardian_override",
            extra_metadata={
                "answer": "override",
                "resolution_source": "discord",
                "guardian_override": True,
            },
        )
        request = self.session_state.api_runs.get_run_request(str(context["run_request_id"]))
        contract_id = str(context["contract_id"]) if context["contract_id"] else None
        relaunch_metadata = {
            **request.metadata,
            "guardian_override": True,
            "guardian_override_source_report_id": str(context["report_id"]),
            "guardian_blocking_reason": str(existing_metadata["guardian_blocking_reason"]),
            "relaunch_of_run_id": str(context["run_id"]),
        }
        if contract_id:
            self.session_state.api_runs.approve_run_contract(
                contract_id=contract_id,
                founder_decision="go_avec_correction",
                notes="Guardian override approved from Discord.",
            )
            payload = self.session_state.api_runs.execute_run(contract_id=contract_id, metadata=relaunch_metadata)
        else:
            payload = self.session_state.api_runs.execute_run(
                mode=request.mode,
                objective=request.objective,
                branch_name=request.branch_name,
                skill_tags=request.skill_tags,
                target_profile=request.target_profile,
                expected_outputs=request.expected_outputs,
                metadata=relaunch_metadata,
            )
        result = payload.get("result")
        self.journal.append(
            "session_guardian_override_applied",
            "gateway",
            {
                "report_id": context["report_id"],
                "run_id": context["run_id"],
                "relaunch_run_id": getattr(result, "run_id", None),
            },
        )
        return {
            "action": "guardian_override",
            "status": "relaunch_started",
            "report_id": str(context["report_id"]),
            "previous_run_id": str(context["run_id"]),
            "run_id": getattr(result, "run_id", None),
            "branch_name": str(context["branch_name"]),
            "metadata": report_metadata,
        }

    def _load_clarification_context(self, report_id: str | None) -> dict[str, object]:
        if not report_id:
            raise KeyError("clarification report id is required")
        row = self.database.fetchone(
            """
            SELECT
                c.report_id,
                c.run_id,
                c.requires_reapproval,
                c.metadata_json,
                r.run_request_id,
                q.contract_id,
                q.branch_name
            FROM clarification_reports c
            JOIN api_run_results r ON r.run_id = c.run_id
            JOIN api_run_requests q ON q.run_request_id = r.run_request_id
            WHERE c.report_id = ?
            """,
            (report_id,),
        )
        if row is None:
            raise KeyError(f"Unknown clarification report: {report_id}")
        return {
            "report_id": str(row["report_id"]),
            "run_id": str(row["run_id"]),
            "run_request_id": str(row["run_request_id"]),
            "contract_id": str(row["contract_id"]) if row["contract_id"] else None,
            "branch_name": str(row["branch_name"]),
            "requires_reapproval": bool(row["requires_reapproval"]),
            "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        }

    def _update_clarification_resolution(
        self,
        *,
        report_id: str,
        resolution: str,
        extra_metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        row = self.database.fetchone(
            "SELECT metadata_json FROM clarification_reports WHERE report_id = ?",
            (report_id,),
        )
        if row is None:
            raise KeyError(f"Unknown clarification report: {report_id}")
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        metadata["resolved_at"] = datetime.now(timezone.utc).isoformat()
        metadata["resolution"] = resolution
        metadata.update(extra_metadata or {})
        self.database.execute(
            "UPDATE clarification_reports SET metadata_json = ? WHERE report_id = ?",
            (dump_json(metadata), report_id),
        )
        return metadata

    def _build_session_reply(
        self,
        event: ChannelEvent,
        envelope_id: str,
        resolved: ResolvedIntent,
        action_result: dict,
    ) -> OperatorReply:
        reply_kind = "ack" if str(action_result.get("status")) not in {"missing_target", "unhandled"} else "blocked"
        communication_mode = (
            CommunicationMode.GUARDIAN
            if resolved.action in {
                "approve_contract",
                "reject_contract",
                "answer_clarification",
                "reject_clarification",
                "guardian_override",
            }
            else CommunicationMode.DISCUSSION
        )
        return OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=envelope_id,
            thread_ref=event.message.thread_ref,
            summary=self._session_reply_summary(resolved, action_result),
            mission_run_id=str(action_result.get("run_id") or "") or None,
            decision_id=None,
            reply_kind=reply_kind,
            communication_mode=communication_mode,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={"surface": event.surface, "resolved_action": resolved.action},
        )

    def _build_session_dispatch(
        self,
        *,
        event: ChannelEvent,
        envelope: OperatorEnvelope,
        resolved: ResolvedIntent,
        action_result: dict,
        promoted_memory_ids: list[str],
        candidate_id: str,
        promotion_decision_id: str,
        reply: OperatorReply,
        channel_class: DiscordChannelClass,
        human_artifacts: list,
    ) -> GatewayDispatchResult:
        return GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=event.event_id,
            envelope_id=envelope.envelope_id,
            intent_id=new_id("session_intent"),
            decision_id=None,
            mission_run_id=str(action_result.get("run_id") or "") or None,
            operator_reply=reply,
            promoted_memory_ids=promoted_memory_ids,
            memory_candidate_id=candidate_id,
            promotion_decision_id=promotion_decision_id,
            discord_run_card=None,
            metadata={
                "classification": "session_resolved",
                "reply_kind": reply.reply_kind,
                "channel_class": channel_class.value,
                "communication_mode": reply.communication_mode.value,
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                "resolved_action": resolved.action,
                "resolved_target_id": resolved.target_id,
                "resolved_confidence": resolved.confidence,
                "action_result": to_jsonable(action_result),
            },
        )

    @staticmethod
    def _session_reply_summary(resolved: ResolvedIntent, action_result: dict) -> str:
        if resolved.action == "approve_contract":
            branch = str(action_result.get("branch_name") or "ce lot")
            if action_result.get("run_launched"):
                return f"{branch}: contrat approuve. Run lance."
            return f"{branch}: contrat approuve. Lancement en attente."
        if resolved.action == "reject_contract":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: contrat refuse. Rien n'est lance."
        if resolved.action == "answer_clarification":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: clarification enregistree. J'applique la decision."
        if resolved.action == "reject_clarification":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: clarification refusee. Le lot reste stoppe."
        if resolved.action == "guardian_override":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: override guardian applique. Run relance."
        if resolved.action == "status_request":
            snapshot = action_result.get("snapshot") or {}
            active_runs = len(snapshot.get("active_runs") or [])
            pending_clarifications = len(snapshot.get("pending_clarifications") or [])
            pending_contracts = len(snapshot.get("pending_contracts") or [])
            daily_spend = float(snapshot.get("daily_spend_eur") or 0.0)
            daily_limit = float(snapshot.get("daily_budget_limit_eur") or 0.0)
            return (
                f"Status: {active_runs} run actif, {pending_clarifications} clarification, "
                f"{pending_contracts} contrat. Budget {daily_spend:.2f}/{daily_limit:.2f} EUR."
            )
        return f"Action {resolved.action}: {action_result.get('status', 'ok')}"

    def _apply_selective_sync(self, candidate, promotion) -> list[str]:
        if promotion.action is not PromotionAction.PROMOTE or promotion.memory_type is None or promotion.tier is None:
            return []
        promoted_candidate = self.selective_sync.promote_ready_candidate(candidate)
        record = self.memory.remember(
            content=promoted_candidate.content,
            user_id=promoted_candidate.actor_id,
            memory_type=promotion.memory_type,
            tier=promotion.tier,
            tags=promoted_candidate.tags,
            metadata={
                **promoted_candidate.metadata,
                "conversation_thread": to_jsonable(promoted_candidate.thread_ref),
                "source_event_id": promoted_candidate.source_event_id,
                "summary": promoted_candidate.summary,
            },
        )
        promotion.memory_id = record.memory_id
        return [record.memory_id]

    def _call_simple_chat(self, message: str, model: str = "claude-sonnet-4-20250514") -> str | None:
        """Call Claude API directly for simple Discord chat messages. Returns the response text or None on failure."""
        if not self.secret_resolver:
            return None
        try:
            import anthropic
            api_key = self.secret_resolver.get_required("ANTHROPIC_API_KEY")
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model,
                max_tokens=500,
                system=(
                    "Tu es Project OS, un agent autonome qui gère des projets de développement. "
                    "Tu réponds en français, de façon concise et directe. "
                    "Tu es connecté via Discord et tu assistes le fondateur du projet. "
                    "Sois utile, professionnel mais décontracté."
                ),
                messages=[
                    {"role": "user", "content": message},
                ],
            )
            return response.content[0].text
        except Exception as exc:
            logging.getLogger("project_os.gateway").warning("simple_chat Claude call failed: %s", exc)
            return None

    def _build_reply(
        self,
        event: ChannelEvent,
        envelope_id: str,
        decision: RoutingDecision,
        mission_run_id: str | None,
    ) -> OperatorReply:
        if decision.allowed:
            worker = self._worker_label(decision.chosen_worker)
            summary = f"Mission lancee sur {worker}. Mode: {decision.execution_class.value}."
            reply_kind = "ack"
        else:
            reason = self._translate_block_reason(decision.blocked_reasons or [decision.route_reason])
            summary = f"Mission bloquee: {reason}"
            reply_kind = "blocked"
        return OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=envelope_id,
            thread_ref=event.message.thread_ref,
            summary=summary,
            mission_run_id=mission_run_id,
            decision_id=decision.decision_id,
            reply_kind=reply_kind,
            communication_mode=decision.communication_mode,
            operator_language=decision.operator_language,
            audience=decision.audience,
            metadata={"surface": event.surface, "speech_policy": decision.speech_policy.value},
        )

    def _build_run_card(
        self,
        *,
        decision: RoutingDecision,
        channel_class: DiscordChannelClass,
        objective: str,
        mission_run_id: str | None,
    ) -> DiscordRunCard:
        status = "en_attente" if decision.allowed else "bloque"
        verdict = None if decision.allowed else "blocked"
        summary = objective[:140]
        return DiscordRunCard(
            card_id=new_id("discord_card"),
            run_id=mission_run_id,
            channel_class=channel_class,
            title="Run en cours" if decision.allowed else "Run bloque",
            status=status,
            summary=summary,
            branch_name=None,
            phase="route",
            estimated_cost_eur=decision.budget_state.mission_estimate_eur,
            verdict=verdict,
            metadata={
                "worker": decision.chosen_worker,
                "route_reason": decision.route_reason,
                "decision_id": decision.decision_id,
                "model": decision.model_route.model,
            },
        )

    def _channel_class_for(self, channel: str, parent_thread_id: str | None) -> DiscordChannelClass:
        lowered = (channel or "").strip().lower().lstrip("#")
        if parent_thread_id:
            return DiscordChannelClass.MISSION_THREAD
        if lowered == "pilotage":
            return DiscordChannelClass.PILOTAGE
        if lowered == "runs-live":
            return DiscordChannelClass.RUNS_LIVE
        if lowered == "approvals":
            return DiscordChannelClass.APPROVALS
        if lowered == "incidents":
            return DiscordChannelClass.INCIDENTS
        return DiscordChannelClass.UNKNOWN

    def _communication_mode_for(self, message_kind, channel_class: DiscordChannelClass) -> CommunicationMode:
        if channel_class is DiscordChannelClass.INCIDENTS:
            return CommunicationMode.INCIDENT
        if channel_class is DiscordChannelClass.APPROVALS:
            return CommunicationMode.GUARDIAN
        if message_kind is None:
            return CommunicationMode.DISCUSSION
        if str(message_kind.value) in {"decision", "note", "idea"}:
            return CommunicationMode.ARCHITECT
        if str(message_kind.value) == "approval":
            return CommunicationMode.GUARDIAN
        if str(message_kind.value) == "tasking":
            return CommunicationMode.BUILDER
        return CommunicationMode.DISCUSSION

    @staticmethod
    def _worker_label(worker: str | None) -> str:
        mapping = {
            "browser": "le worker navigateur",
            "windows": "le worker Windows",
            "deterministic": "la lane deterministe",
            None: "le worker cible",
        }
        return mapping.get(worker, worker or "le worker cible")

    @staticmethod
    def _translate_block_reason(reasons: list[str]) -> str:
        mapping = {
            "runtime_not_ready": "le runtime n'est pas pret",
            "profile_missing": "le profil cible est introuvable",
            "worker_unresolved": "aucun worker n'a ete resolu",
            "worker_not_allowed": "le worker demande n'est pas autorise",
            "forbidden_zone_target": "la cible touche une zone interdite",
            "path_outside_managed_roots": "la cible est hors des racines gerees",
            "required_secret_missing": "un secret requis manque",
            "monthly_budget_exceeded": "le budget mensuel est depasse",
            "exceptional_requires_founder_approval": "une validation fondateur est obligatoire",
            "daily_budget_soft_exceeded": "le budget journalier souple est depasse",
        }
        return ", ".join(mapping.get(item, item) for item in reasons)

    def _persist_channel_event(self, event: ChannelEvent, candidate) -> None:
        self.database.upsert(
            "channel_events",
            {
                "event_id": event.event_id,
                "surface": event.surface,
                "event_type": event.event_type,
                "actor_id": event.message.actor_id,
                "channel": event.message.channel,
                "message_kind": candidate.classification.value,
                "thread_ref_json": dump_json(to_jsonable(event.message.thread_ref)),
                "message_json": dump_json(to_jsonable(event.message)),
                "raw_payload_json": dump_json(event.raw_payload),
                "created_at": event.created_at,
            },
            conflict_columns="event_id",
            immutable_columns=["created_at"],
        )

        self.database.upsert(
            "conversation_memory_candidates",
            {
                "candidate_id": candidate.candidate_id,
                "source_event_id": candidate.source_event_id,
                "actor_id": candidate.actor_id,
                "classification": candidate.classification.value,
                "thread_ref_json": dump_json(to_jsonable(candidate.thread_ref)),
                "summary": candidate.summary,
                "content": candidate.content,
                "tags_json": dump_json(candidate.tags),
                "tier": candidate.tier.value,
                "should_promote": 1 if candidate.should_promote else 0,
                "payload_json": dump_json(candidate.metadata),
                "created_at": candidate.created_at,
            },
            conflict_columns="candidate_id",
            immutable_columns=["created_at"],
        )

    def _persist_promotion(self, candidate, promotion) -> None:
        self.database.upsert(
            "promotion_decisions",
            {
                "promotion_decision_id": promotion.promotion_decision_id,
                "candidate_id": candidate.candidate_id,
                "action": promotion.action.value,
                "reason": promotion.reason,
                "memory_type": promotion.memory_type.value if promotion.memory_type else None,
                "tier": promotion.tier.value if promotion.tier else None,
                "memory_id": promotion.memory_id,
                "payload_json": dump_json(promotion.metadata),
                "created_at": promotion.created_at,
            },
            conflict_columns="promotion_decision_id",
            immutable_columns=["created_at"],
        )

    def _persist_dispatch(self, dispatch: GatewayDispatchResult) -> None:
        self.database.upsert(
            "gateway_dispatch_results",
            {
                "dispatch_id": dispatch.dispatch_id,
                "channel_event_id": dispatch.channel_event_id,
                "envelope_id": dispatch.envelope_id,
                "intent_id": dispatch.intent_id,
                "decision_id": dispatch.decision_id,
                "mission_run_id": dispatch.mission_run_id,
                "memory_candidate_id": dispatch.memory_candidate_id,
                "promotion_decision_id": dispatch.promotion_decision_id,
                "promoted_memory_ids_json": dump_json(dispatch.promoted_memory_ids),
                "reply_json": dump_json(to_jsonable(dispatch.operator_reply)),
                "metadata_json": dump_json(dispatch.metadata),
                "created_at": dispatch.created_at,
            },
            conflict_columns="dispatch_id",
            immutable_columns=["created_at"],
        )
