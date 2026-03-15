from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

from ..database import CanonicalDatabase, dump_json
from ..local_model import LocalModelClient
from ..memory.store import MemoryStore
from ..models import (
    ChannelEvent,
    CommunicationMode,
    DiscordThreadBinding,
    DiscordChannelClass,
    DiscordRunCard,
    GatewayDispatchResult,
    OperatorAudience,
    OperatorEnvelope,
    OperatorReply,
    PromotionAction,
    RoutingDecision,
    RoutingDecisionTrace,
    SensitivityClass,
    new_id,
    to_jsonable,
)
from ..privacy_guard import sanitize_sensitive_text
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
        local_model_client: LocalModelClient | None = None,
        selective_sync: SelectiveSyncPromoter | None = None,
    ) -> None:
        self.database = database
        self.journal = journal
        self.router = router
        self.memory = memory
        self.session_state = session_state
        self.secret_resolver = secret_resolver
        self.local_model_client = local_model_client or getattr(router, "local_model_client", None)
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
        normalized_event = self._normalize_event_for_routing(event)
        candidate = self.selective_sync.build_candidate(normalized_event)
        candidate.metadata.update(self._operator_override_metadata(normalized_event))
        duplicate_event_id = self._duplicate_channel_event_id(normalized_event)
        if duplicate_event_id:
            self.journal.append(
                "gateway_duplicate_ingress_ignored",
                "gateway",
                {
                    "channel_event_id": normalized_event.event_id,
                    "duplicate_of_event_id": duplicate_event_id,
                    "message_id": normalized_event.message.message_id,
                    "surface": normalized_event.surface,
                },
            )
            return self._build_duplicate_dispatch(normalized_event, duplicate_event_id)
        promotion = self.selective_sync.decide_promotion(candidate)
        human_artifacts = self.selective_sync.build_human_artifacts(normalized_event)
        candidate.metadata["human_artifacts"] = [to_jsonable(item) for item in human_artifacts]
        duplicate_event_id = self._reserve_channel_event(normalized_event, candidate)
        if duplicate_event_id:
            self.journal.append(
                "gateway_duplicate_ingress_ignored",
                "gateway",
                {
                    "channel_event_id": normalized_event.event_id,
                    "duplicate_of_event_id": duplicate_event_id,
                    "message_id": normalized_event.message.message_id,
                    "surface": normalized_event.surface,
                    "mode": "race_safe_reservation",
                },
            )
            return self._build_duplicate_dispatch(normalized_event, duplicate_event_id)
        channel_class = self._channel_class_for(
            normalized_event.message.channel,
            normalized_event.message.thread_ref.parent_thread_id,
        )
        communication_mode = self._communication_mode_for(candidate.classification, channel_class)
        envelope = OperatorEnvelope(
            envelope_id=new_id("envelope"),
            actor_id=normalized_event.message.actor_id,
            channel=normalized_event.message.channel,
            objective=normalized_event.message.text.strip() or candidate.summary,
            target_profile=target_profile,
            requested_worker=requested_worker,
            requested_risk_class=risk_class,
            communication_mode=communication_mode,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "channel_event_id": normalized_event.event_id,
                "message_kind": candidate.classification.value,
                "channel_class": channel_class.value,
                "sensitivity_class": candidate.metadata.get("sensitivity_class", SensitivityClass.S1.value),
                "sensitivity_reason": candidate.metadata.get("sensitivity_reason"),
                "thread_ref": to_jsonable(normalized_event.message.thread_ref),
                "attachments": [to_jsonable(item) for item in normalized_event.message.attachments],
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                **self._operator_override_metadata(normalized_event),
                **(metadata or {}),
            },
        )
        snapshot = self.session_state.load()
        resolved = self.session_state.resolve_intent(normalized_event.message.text, snapshot=snapshot)
        if resolved is not None:
            self._persist_promotion(candidate, promotion)
            action_result = self._execute_resolved_intent(resolved)
            promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
            reply = self._build_session_reply(normalized_event, envelope.envelope_id, resolved, action_result)
            dispatch = self._build_session_dispatch(
                event=normalized_event,
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
            thread_binding = self._upsert_discord_thread_binding(
                event=normalized_event,
                dispatch=dispatch,
                channel_class=channel_class,
            )
            if thread_binding is not None:
                dispatch.metadata["thread_binding_id"] = thread_binding.binding_id
                dispatch.metadata["thread_binding_kind"] = thread_binding.binding_kind
            self._persist_dispatch(dispatch)
            self.journal.append(
                "gateway_session_dispatch_completed",
                "gateway",
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "channel_event_id": normalized_event.event_id,
                    "resolved_action": resolved.action,
                    "target_id": resolved.target_id,
                    "promoted_memory_count": len(promoted_memory_ids),
                },
            )
            return dispatch
        intent = self.router.envelope_to_intent(envelope)
        decision, trace, mission_run = self.router.route_intent(intent, persist=True)
        promoted_memory_ids = self._apply_selective_sync(candidate, promotion)

        if decision.allowed and self._should_inline_chat(normalized_event, decision):
            message_for_model = self._message_for_route(candidate, decision)
            inline_response = self._call_inline_chat(
                message=message_for_model,
                model=decision.model_route.model,
                provider=decision.model_route.provider,
                reasoning_effort=decision.model_route.reasoning_effort,
                sensitivity=self._candidate_sensitivity(candidate),
            )
            if inline_response:
                reply = OperatorReply(
                    reply_id=new_id("reply"),
                    channel=normalized_event.message.channel,
                    envelope_id=envelope.envelope_id,
                    thread_ref=normalized_event.message.thread_ref,
                    summary=self._decorate_inline_reply_summary(inline_response, decision),
                    mission_run_id=mission_run.mission_run_id if mission_run else None,
                    decision_id=decision.decision_id,
                    reply_kind="chat_response",
                    communication_mode=decision.communication_mode,
                    operator_language=decision.operator_language,
                    audience=decision.audience,
                    metadata={"surface": normalized_event.surface, "speech_policy": decision.speech_policy.value},
                )
            elif decision.model_route.provider == "local":
                reply = OperatorReply(
                    reply_id=new_id("reply"),
                    channel=normalized_event.message.channel,
                    envelope_id=envelope.envelope_id,
                    thread_ref=normalized_event.message.thread_ref,
                    summary="Message bloque: la voie locale sensible est indisponible. Rien n'a ete envoye au cloud.",
                    mission_run_id=mission_run.mission_run_id if mission_run else None,
                    decision_id=decision.decision_id,
                    reply_kind="blocked",
                    communication_mode=decision.communication_mode,
                    operator_language=decision.operator_language,
                    audience=decision.audience,
                    metadata={"surface": normalized_event.surface, "speech_policy": decision.speech_policy.value},
                )
            else:
                reply = self._build_reply(
                    normalized_event,
                    envelope.envelope_id,
                    decision,
                    mission_run.mission_run_id if mission_run else None,
                )
        else:
            reply = self._build_reply(
                normalized_event,
                envelope.envelope_id,
                decision,
                mission_run.mission_run_id if mission_run else None,
            )
        run_card = self._build_run_card(
            decision=decision,
            channel_class=channel_class,
            objective=envelope.objective,
            mission_run_id=mission_run.mission_run_id if mission_run else None,
        )

        self._persist_promotion(candidate, promotion)
        dispatch = GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=normalized_event.event_id,
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
                "sensitivity_class": candidate.metadata.get("sensitivity_class", SensitivityClass.S1.value),
                "reply_kind": reply.reply_kind,
                "channel_class": channel_class.value,
                "communication_mode": communication_mode.value,
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                "model_provider": decision.model_route.provider,
                "requested_provider": envelope.metadata.get("requested_provider"),
                "message_prefix_consumed": envelope.metadata.get("message_prefix_consumed"),
            },
        )
        thread_binding = self._upsert_discord_thread_binding(
            event=normalized_event,
            dispatch=dispatch,
            channel_class=channel_class,
        )
        if thread_binding is not None:
            dispatch.metadata["thread_binding_id"] = thread_binding.binding_id
            dispatch.metadata["thread_binding_kind"] = thread_binding.binding_kind
        self._persist_dispatch(dispatch)
        self.journal.append(
            "gateway_dispatch_completed",
            "gateway",
            {
                "dispatch_id": dispatch.dispatch_id,
                "channel_event_id": normalized_event.event_id,
                "decision_id": decision.decision_id,
                "mission_run_id": dispatch.mission_run_id,
                "promoted_memory_count": len(promoted_memory_ids),
            },
        )
        return dispatch

    @staticmethod
    def _parse_operator_provider_override(raw_text: str) -> tuple[str, dict[str, str]] | None:
        stripped = raw_text.lstrip()
        if not stripped:
            return None
        prefixes = {
            "CLAUDE": {"requested_provider": "anthropic", "requested_model_family": "claude"},
            "GPT": {"requested_provider": "openai", "requested_model_family": "gpt"},
            "LOCAL": {"requested_provider": "local", "requested_model_family": "local"},
            "OLLAMA": {"requested_provider": "local", "requested_model_family": "ollama"},
        }
        upper = stripped.upper()
        for token, metadata in prefixes.items():
            remainder: str | None = None
            if upper.startswith(f"{token}:"):
                remainder = stripped[len(token) + 1 :].strip()
            elif upper.startswith(f"{token} "):
                remainder = stripped[len(token) :].strip()
            if not remainder:
                continue
            return (
                remainder,
                {
                    **metadata,
                    "requested_route_mode": "forced_provider",
                    "message_prefix_consumed": token,
                },
            )
        return None

    def _normalize_event_for_routing(self, event: ChannelEvent) -> ChannelEvent:
        parsed = self._parse_operator_provider_override(event.message.text)
        if parsed is None:
            return event
        normalized_text, override_metadata = parsed
        message_metadata = {
            **event.message.metadata,
            **override_metadata,
            "raw_operator_text": event.message.text,
            "normalized_operator_text": normalized_text,
        }
        raw_payload = dict(event.raw_payload)
        operator_ingress = dict(raw_payload.get("operator_ingress") or {})
        operator_ingress.update(
            {
                **override_metadata,
                "raw_operator_text": event.message.text,
                "normalized_operator_text": normalized_text,
            }
        )
        raw_payload["operator_ingress"] = operator_ingress
        return replace(
            event,
            message=replace(event.message, text=normalized_text, metadata=message_metadata),
            raw_payload=raw_payload,
        )

    @staticmethod
    def _operator_override_metadata(event: ChannelEvent) -> dict[str, str]:
        message_metadata = event.message.metadata
        requested_provider = str(message_metadata.get("requested_provider") or "").strip()
        if not requested_provider:
            return {}
        fields = (
            "requested_provider",
            "requested_model_family",
            "requested_route_mode",
            "message_prefix_consumed",
            "raw_operator_text",
            "normalized_operator_text",
        )
        return {
            field: str(message_metadata[field])
            for field in fields
            if message_metadata.get(field) not in (None, "")
        }

    def _reserve_channel_event(self, event: ChannelEvent, candidate) -> str | None:
        try:
            self._persist_channel_event(event, candidate)
        except sqlite3.IntegrityError as exc:
            if "channel_events.ingress_dedup_key" not in str(exc):
                raise
            return self._duplicate_channel_event_id(event)
        return None

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
        sensitivity = self._candidate_sensitivity(promoted_candidate)
        base_metadata = {
            **promoted_candidate.metadata,
            "conversation_thread": to_jsonable(promoted_candidate.thread_ref),
            "source_event_id": promoted_candidate.source_event_id,
            "summary": promoted_candidate.summary,
        }
        if sensitivity is SensitivityClass.S2:
            full_record = self.memory.remember(
                content=promoted_candidate.content,
                user_id=promoted_candidate.actor_id,
                memory_type=promotion.memory_type,
                tier=promotion.tier,
                tags=[*promoted_candidate.tags, "privacy_full"],
                metadata={
                    **base_metadata,
                    "privacy_view": "full",
                    "openmemory_enabled": False,
                    "embedding_provider": "local_hash",
                },
            )
            clean_content = str(promoted_candidate.metadata.get("clean_content") or promoted_candidate.summary)
            clean_record = self.memory.remember(
                content=clean_content,
                user_id=promoted_candidate.actor_id,
                memory_type=promotion.memory_type,
                tier=promotion.tier,
                tags=[tag for tag in promoted_candidate.tags if tag != "privacy_guard"] + ["privacy_clean"],
                metadata={
                    **base_metadata,
                    "privacy_view": "clean",
                    "clean_source_memory_id": full_record.memory_id,
                    "full_content_redacted": True,
                },
            )
            promotion.memory_id = clean_record.memory_id
            return [full_record.memory_id, clean_record.memory_id]

        record_metadata = dict(base_metadata)
        record_tags = list(promoted_candidate.tags)
        if sensitivity is SensitivityClass.S3:
            record_metadata.update(
                {
                    "privacy_view": "full",
                    "openmemory_enabled": False,
                    "embedding_provider": "local_hash",
                    "cloud_route_blocked": True,
                }
            )
            record_tags.append("privacy_full")
        else:
            record_metadata.setdefault("privacy_view", "clean")
        record = self.memory.remember(
            content=promoted_candidate.content,
            user_id=promoted_candidate.actor_id,
            memory_type=promotion.memory_type,
            tier=promotion.tier,
            tags=record_tags,
            metadata=record_metadata,
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
                system=self._simple_chat_system_prompt(),
                messages=[
                    {"role": "user", "content": self._simple_chat_user_message(message)},
                ],
            )
            return response.content[0].text
        except Exception as exc:
            logging.getLogger("project_os.gateway").warning("simple_chat Claude call failed: %s", exc)
            return None

    def _call_openai_chat(
        self,
        message: str,
        *,
        model: str | None,
        reasoning_effort: str | None,
    ) -> str | None:
        if not self.secret_resolver:
            return None
        try:
            from openai import OpenAI

            api_key = self.secret_resolver.get_required("OPENAI_API_KEY")
            client = OpenAI(api_key=api_key)
            response = client.responses.create(
                model=model or "gpt-5.4",
                reasoning={"effort": reasoning_effort or "medium"},
                input=(
                    f"System:\n{self._simple_chat_system_prompt()}\n\n"
                    f"User:\n{self._simple_chat_user_message(message)}"
                ),
                store=False,
            )
            output_text = getattr(response, "output_text", None)
            if not output_text and hasattr(response, "model_dump"):
                output_text = response.model_dump().get("output_text")
            rendered = str(output_text or "").strip()
            return rendered or None
        except Exception as exc:
            logging.getLogger("project_os.gateway").warning("simple_chat OpenAI call failed: %s", exc)
            return None

    @staticmethod
    def _simple_chat_system_prompt() -> str:
        return (
            "Tu es la voix operateur de Project OS sur la machine Windows du fondateur. "
            "Tu reponds en francais, de facon concise, claire et concrete. "
            "Tu n'es pas un assistant web public ni une simple interface de chat. "
            "Tu peux orchestrer des actions sur le projet et sur les dossiers geres par Project OS quand une mission le demande. "
            "N'affirme jamais que tu n'as pas acces au projet, aux dossiers, au systeme de fichiers ou aux APIs locales de facon generale. "
            "Si tu n'as pas encore inspecte un fichier ou execute une action dans ce tour, dis simplement que tu ne l'as pas encore fait. "
            "Ne te presente pas comme Claude ou Anthropic. "
            "Ne promets jamais une action non executee."
        )

    @staticmethod
    def _simple_chat_user_message(message: str) -> str:
        return (
            "Contexte runtime:\n"
            "- surface: Discord\n"
            "- role: Project OS operator voice\n"
            "- host: Windows-first\n"
            "- managed_workspace: D:/ProjectOS/project-os-core\n"
            "- principle: do not invent completed file inspection or executed actions\n\n"
            f"Message fondateur:\n{message}"
        )

    def _call_local_chat(
        self,
        *,
        message: str,
        model: str | None,
        sensitivity: SensitivityClass,
    ) -> str | None:
        if self.local_model_client is None:
            return None
        try:
            response = self.local_model_client.chat(
                message=message,
                model=model,
                system=self._local_system_prompt(sensitivity),
            )
        except Exception as exc:
            logging.getLogger("project_os.gateway").warning("local_chat call failed: %s", exc)
            return None
        rendered = response.content.strip()
        if sensitivity is not SensitivityClass.S1:
            rendered = sanitize_sensitive_text(rendered)
        return rendered or None

    def _call_inline_chat(
        self,
        *,
        message: str,
        model: str | None,
        provider: str,
        reasoning_effort: str | None,
        sensitivity: SensitivityClass,
    ) -> str | None:
        if provider == "local":
            return self._call_local_chat(message=message, model=model, sensitivity=sensitivity)
        if provider == "openai":
            return self._call_openai_chat(
                message,
                model=model,
                reasoning_effort=reasoning_effort,
            )
        return self._call_simple_chat(message=message, model=model or "claude-sonnet-4-20250514")

    @staticmethod
    def _decorate_inline_reply_summary(summary: str, decision: RoutingDecision) -> str:
        rendered = summary.strip()
        if decision.model_route.provider == "local":
            label = "[Local S3 / Ollama]" if decision.route_reason == "s3_local_route" else "[Local / Ollama]"
            if rendered.lower().startswith(label.lower()):
                return rendered
            return f"{label} {rendered}"
        return rendered

    @staticmethod
    def _candidate_sensitivity(candidate) -> SensitivityClass:
        raw = str(candidate.metadata.get("sensitivity_class") or "").strip().lower()
        try:
            return SensitivityClass(raw)
        except Exception:
            return SensitivityClass.S1

    @staticmethod
    def _message_for_cloud(candidate) -> str:
        sensitivity = GatewayService._candidate_sensitivity(candidate)
        if sensitivity is SensitivityClass.S2:
            clean_content = str(candidate.metadata.get("clean_content") or "").strip()
            if clean_content:
                return clean_content
        return candidate.content

    @staticmethod
    def _should_inline_chat(event: ChannelEvent, decision: RoutingDecision) -> bool:
        if event.surface != "discord" or not decision.allowed:
            return False
        if decision.model_route.provider == "local":
            return decision.communication_mode in {CommunicationMode.DISCUSSION, CommunicationMode.ARCHITECT}
        if (
            decision.route_reason.startswith("operator_forced_")
            and decision.model_route.provider in {"anthropic", "openai"}
        ):
            return decision.communication_mode in {CommunicationMode.DISCUSSION, CommunicationMode.ARCHITECT}
        return decision.route_reason == "discord_simple_route"

    @staticmethod
    def _message_for_route(candidate, decision: RoutingDecision) -> str:
        if decision.model_route.provider == "local":
            return candidate.content
        return GatewayService._message_for_cloud(candidate)

    @staticmethod
    def _local_system_prompt(sensitivity: SensitivityClass) -> str:
        base = (
            "Tu es Project OS sur une voie locale Windows-first. "
            "Tu reponds en francais, de facon concise, utile et concrete. "
            "Ne fais pas de theatre, ne promets pas d'actions non executees."
        )
        if sensitivity is SensitivityClass.S3:
            return (
                base
                + " Le message contient des donnees tres sensibles et doit rester local. "
                + "N'affiche jamais de secret, token, cle, email ou valeur sensible verbatim dans ta reponse. "
                + "Explique seulement ce qu'il faut faire ou retenir, en version redactee."
            )
        if sensitivity is SensitivityClass.S2:
            return (
                base
                + " Le message peut contenir des donnees personnelles ou sensibles. "
                + "Ne repete pas les informations identifiantes verbatim."
            )
        return base

    def _duplicate_channel_event_id(self, event: ChannelEvent) -> str | None:
        dedup_key = self._ingress_dedup_key(event)
        if not dedup_key:
            return None
        row = self.database.fetchone(
            "SELECT event_id FROM channel_events WHERE ingress_dedup_key = ?",
            (dedup_key,),
        )
        if row is None:
            return None
        return str(row["event_id"])

    def _build_duplicate_dispatch(self, event: ChannelEvent, duplicate_event_id: str) -> GatewayDispatchResult:
        reply = OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=new_id("envelope"),
            thread_ref=event.message.thread_ref,
            summary="Doublon OpenClaw ignore. Rien n'est relance.",
            reply_kind="ack",
            communication_mode=CommunicationMode.DISCUSSION,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={"surface": event.surface, "duplicate_of_event_id": duplicate_event_id},
        )
        return GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=duplicate_event_id,
            envelope_id=reply.envelope_id,
            intent_id=new_id("intent"),
            decision_id=None,
            mission_run_id=None,
            operator_reply=reply,
            promoted_memory_ids=[],
            memory_candidate_id=None,
            promotion_decision_id=None,
            discord_run_card=None,
            metadata={"duplicate_ingress": True, "duplicate_of_event_id": duplicate_event_id},
        )

    @staticmethod
    def _ingress_dedup_key(event: ChannelEvent) -> str | None:
        source = str(event.raw_payload.get("source") or event.message.metadata.get("source") or "").strip().lower()
        if source != "openclaw":
            return None
        source_message_id = str(event.message.metadata.get("message_id") or event.message.message_id or "").strip()
        conversation_key = str(event.message.thread_ref.external_thread_id or event.message.thread_ref.thread_id or "").strip()
        if not source_message_id or not conversation_key:
            return None
        content_hash = hashlib.sha256(event.message.text.strip().encode("utf-8")).hexdigest()
        raw = f"{event.surface}|{event.message.channel}|{source_message_id}|{conversation_key}|{content_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

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
            "s3_requires_local_model": "le contenu est trop sensible pour le cloud et aucune voie locale sure n'est disponible",
            "operator_forced_anthropic_unavailable": "la voie Claude demandee n'est pas disponible sur cette machine",
            "operator_forced_openai_unavailable": "la voie GPT demandee n'est pas disponible sur cette machine",
            "operator_forced_local_unavailable": "la voie locale demandee n'est pas disponible sur cette machine",
        }
        return ", ".join(mapping.get(item, item) for item in reasons)

    def _persist_channel_event(self, event: ChannelEvent, candidate) -> None:
        ingress_dedup_key = self._ingress_dedup_key(event)
        self.database.upsert(
            "channel_events",
            {
                "event_id": event.event_id,
                "surface": event.surface,
                "event_type": event.event_type,
                "actor_id": event.message.actor_id,
                "channel": event.message.channel,
                "message_kind": candidate.classification.value,
                "source_message_id": event.message.metadata.get("message_id"),
                "conversation_key": event.message.thread_ref.external_thread_id or event.message.thread_ref.thread_id,
                "ingress_dedup_key": ingress_dedup_key,
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

    def _upsert_discord_thread_binding(
        self,
        *,
        event: ChannelEvent,
        dispatch: GatewayDispatchResult,
        channel_class: DiscordChannelClass,
    ) -> DiscordThreadBinding | None:
        if event.surface.strip().lower() != "discord":
            return None

        thread_ref = event.message.thread_ref
        thread_key_source = str(thread_ref.external_thread_id or thread_ref.thread_id or "").strip()
        if not thread_key_source:
            return None

        binding_key = hashlib.sha256(
            f"{event.surface.strip().lower()}|{event.message.channel}|{thread_key_source}".encode("utf-8")
        ).hexdigest()
        existing = self.database.fetchone(
            "SELECT binding_id, created_at FROM discord_thread_bindings WHERE binding_key = ?",
            (binding_key,),
        )
        binding = DiscordThreadBinding(
            binding_id=str(existing["binding_id"]) if existing else new_id("discord_binding"),
            binding_key=binding_key,
            surface=event.surface.strip().lower(),
            channel=event.message.channel,
            thread_id=thread_ref.thread_id,
            external_thread_id=thread_ref.external_thread_id,
            parent_thread_id=thread_ref.parent_thread_id,
            channel_event_id=event.event_id,
            dispatch_id=dispatch.dispatch_id,
            envelope_id=dispatch.envelope_id,
            decision_id=dispatch.decision_id,
            mission_run_id=dispatch.mission_run_id,
            binding_kind=self._discord_binding_kind_for(channel_class=channel_class, dispatch=dispatch),
            status="blocked" if dispatch.operator_reply.reply_kind == "blocked" else "active",
            metadata={
                "channel_class": channel_class.value,
                "reply_kind": dispatch.operator_reply.reply_kind,
                "source_message_id": event.message.metadata.get("message_id"),
                "conversation_key": thread_key_source,
            },
            created_at=str(existing["created_at"]) if existing else event.created_at,
            updated_at=event.created_at,
        )
        self.database.upsert(
            "discord_thread_bindings",
            {
                "binding_id": binding.binding_id,
                "binding_key": binding.binding_key,
                "surface": binding.surface,
                "channel": binding.channel,
                "thread_id": binding.thread_id,
                "external_thread_id": binding.external_thread_id,
                "parent_thread_id": binding.parent_thread_id,
                "channel_event_id": binding.channel_event_id,
                "dispatch_id": binding.dispatch_id,
                "envelope_id": binding.envelope_id,
                "decision_id": binding.decision_id,
                "mission_run_id": binding.mission_run_id,
                "binding_kind": binding.binding_kind,
                "status": binding.status,
                "metadata_json": dump_json(binding.metadata),
                "created_at": binding.created_at,
                "updated_at": binding.updated_at,
            },
            conflict_columns="binding_key",
            immutable_columns=["binding_id", "created_at"],
        )
        return binding

    @staticmethod
    def _discord_binding_kind_for(
        *,
        channel_class: DiscordChannelClass,
        dispatch: GatewayDispatchResult,
    ) -> str:
        if channel_class is DiscordChannelClass.INCIDENTS:
            return "incident"
        if channel_class is DiscordChannelClass.APPROVALS:
            return "approval"
        if dispatch.mission_run_id:
            return "run"
        return "discussion"
