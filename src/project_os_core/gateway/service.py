from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace
import unicodedata
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from ..artifacts import write_binary_artifact, write_json_artifact, write_text_artifact
from ..costing import estimate_discussion_usage, estimate_text_tokens, estimate_usage_cost_eur
from ..database import CanonicalDatabase, dump_json
from ..deep_research import DeepResearchService
from .reply_pdf import render_operator_reply_pdf
from ..local_model import LocalModelClient
from ..memory.store import MemoryStore
from ..models import (
    ActionContract,
    ActionRiskClass,
    ApprovalStatus,
    ArtifactPointer,
    ChannelEvent,
    CommunicationMode,
    ConversationThreadRef,
    CostClass,
    MissionIntent,
    DelegationLevel,
    DiscordThreadBinding,
    DiscordChannelClass,
    DiscordRunCard,
    GatewayDispatchResult,
    InteractionState,
    IntentKind,
    MemoryTier,
    OperatorAttachment,
    OperatorAudience,
    OperatorMessage,
    OperatorEnvelope,
    OperatorReply,
    OperatorReplyArtifact,
    OperatorResponseManifest,
    PromotionAction,
    RoutingDecision,
    RoutingDecisionTrace,
    SensitivityClass,
    new_id,
    to_jsonable,
)
from ..paths import PathPolicy, ProjectPaths
from ..privacy_guard import sanitize_sensitive_text
from ..research_scaffold import (
    ResearchScaffoldRequest,
    detect_deep_research_request,
    parse_research_mode_selection,
    scaffold_research,
)
from ..router.service import MissionRouter
from ..runtime.journal import LocalJournal
from ..session.state import PersistentSessionState, ResolvedIntent
from .context_builder import GatewayContextBuilder, GatewayContextBundle
from .persona import PersonaSpec, load_persona_spec
from .promotion import SelectiveSyncPromoter

_LONG_CONTEXT_SEGMENT_TARGET = 1200
_LONG_CONTEXT_SEGMENT_HARD_LIMIT = 1500
_LONG_CONTEXT_MAX_ITEMS = 6
_ARTIFACT_SUMMARY_RESPONSE_LENGTH = 1800
_ARTIFACT_SUMMARY_LINE_THRESHOLD = 20
_THREAD_CHUNK_RESPONSE_LENGTH = 1800
_THREAD_CHUNK_LINE_THRESHOLD = 20
_DISCORD_ARTIFACT_SUMMARY_LIMIT = 900
_RESPONSE_REVIEW_OVERVIEW_LIMIT = 320
_RESPONSE_REVIEW_ITEM_LIMIT = 3
_REASONING_ESCALATION_LENGTH_THRESHOLD = 140
_REASONING_ESCALATION_WORD_THRESHOLD = 20
_REASONING_ESCALATION_KEYWORDS = (
    "architecture",
    "roadmap",
    "priorite",
    "compromis",
    "challenge",
    "strategie",
    "analyse",
    "audit",
    "compare",
    "comparaison",
    "tradeoff",
    "persona",
    "naming",
    "modele",
    "model",
    "prompt",
    "coherence",
    "synthese",
    "systeme",
    "memoire",
    "memory",
    "inspiration",
    "inspire",
    "pattern",
    "patterns",
    "documentation",
    "design",
    "repo",
)
_REASONING_ESCALATION_LONGFORM_HINTS = (
    "reponse longue",
    "2000 caractere",
    "2000 caracteres",
    "3000 caractere",
    "3000 caracteres",
    "detaillee",
    "detaille",
    "approfondie",
    "approfondi",
    "complet",
    "complete",
    "fais un pdf",
    "genere un pdf",
    "genere la en pdf",
    "mets le en pdf",
    "mets la en pdf",
    "en pdf",
)
_DISCUSSION_MODE_ALIASES = {
    "simple": "simple",
    "rapide": "simple",
    "speed": "simple",
    "avance": "avance",
    "avancee": "avance",
    "advanced": "avance",
    "sonnet": "avance",
    "extreme": "extreme",
    "extremee": "extreme",
    "opus": "extreme",
}


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
        paths: ProjectPaths | None = None,
        path_policy: PathPolicy | None = None,
        secret_resolver=None,
        local_model_client: LocalModelClient | None = None,
        selective_sync: SelectiveSyncPromoter | None = None,
        deep_research: DeepResearchService | None = None,
    ) -> None:
        self.database = database
        self.journal = journal
        self.router = router
        self.memory = memory
        self.session_state = session_state
        self.paths = paths
        self.path_policy = path_policy
        self.secret_resolver = secret_resolver
        self.local_model_client = local_model_client or getattr(router, "local_model_client", None)
        self.selective_sync = selective_sync or SelectiveSyncPromoter()
        self.deep_research = deep_research
        self.persona: PersonaSpec = load_persona_spec()
        self.context_builder = GatewayContextBuilder(database=database, session_state=session_state)

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
        ingress_artifacts = self._persist_ingress_artifacts(normalized_event, candidate)
        candidate.metadata["source_artifact_ids"] = [item.artifact_id for item in ingress_artifacts]
        candidate.metadata["source_artifact_count"] = len(ingress_artifacts)
        candidate.metadata["source_artifact_paths"] = [item.path for item in ingress_artifacts]
        long_context_artifacts = self._persist_long_context_workflow(normalized_event, candidate, ingress_artifacts)
        if long_context_artifacts:
            candidate.metadata["long_context_artifact_ids"] = [item.artifact_id for item in long_context_artifacts]
            candidate.metadata["long_context_artifact_paths"] = [item.path for item in long_context_artifacts]
        research_scaffold = self._maybe_prepare_deep_research_scaffold(normalized_event)
        if research_scaffold is not None:
            candidate.metadata["research_scaffold"] = research_scaffold
            candidate.metadata["research_scaffold_path"] = research_scaffold.get("path")
            candidate.metadata["research_scaffold_kind"] = research_scaffold.get("kind")
            candidate.metadata["research_scaffold_title"] = research_scaffold.get("title")
            candidate.metadata["research_scaffold_created"] = research_scaffold.get("created")
        action_contract = self._build_action_contract(
            event=normalized_event,
            candidate=candidate,
            requested_risk_class=risk_class,
        )
        candidate.metadata["action_contract"] = to_jsonable(action_contract)
        self._persist_candidate_metadata(candidate)
        channel_class = self._channel_class_for(
            normalized_event.message.channel,
            normalized_event.message.thread_ref.parent_thread_id,
        )
        communication_mode = self._communication_mode_for(
            candidate.classification,
            channel_class,
            intent_kind=str(candidate.metadata.get("intent_kind") or ""),
            delegation_level=str(candidate.metadata.get("delegation_level") or ""),
        )
        envelope = OperatorEnvelope(
            envelope_id=new_id("envelope"),
            actor_id=normalized_event.message.actor_id,
            channel=normalized_event.message.channel,
            objective=normalized_event.message.text.strip() or candidate.summary,
            target_profile=target_profile,
            requested_worker=requested_worker,
            requested_risk_class=risk_class or action_contract.risk_class,
            communication_mode=communication_mode,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "channel_event_id": normalized_event.event_id,
                "message_kind": candidate.classification.value,
                "intent_kind": candidate.metadata.get("intent_kind"),
                "delegation_level": candidate.metadata.get("delegation_level"),
                "interaction_state": candidate.metadata.get("interaction_state"),
                "suggested_next_state": candidate.metadata.get("suggested_next_state"),
                "intent_confidence": candidate.metadata.get("intent_confidence"),
                "intent_signals": candidate.metadata.get("intent_signals", []),
                "state_transition": candidate.metadata.get("state_transition"),
                "directive_detection": candidate.metadata.get("directive_detection"),
                "action_contract": candidate.metadata.get("action_contract"),
                "channel_class": channel_class.value,
                "sensitivity_class": candidate.metadata.get("sensitivity_class", SensitivityClass.S1.value),
                "sensitivity_reason": candidate.metadata.get("sensitivity_reason"),
                "input_profile": candidate.metadata.get("input_profile"),
                "input_char_count": candidate.metadata.get("input_char_count"),
                "attachment_count": candidate.metadata.get("attachment_count"),
                "requires_ingress_artifact": candidate.metadata.get("requires_ingress_artifact"),
                "requires_long_context_pipeline": candidate.metadata.get("requires_long_context_pipeline"),
                "thread_ref": to_jsonable(normalized_event.message.thread_ref),
                "attachments": [to_jsonable(item) for item in normalized_event.message.attachments],
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                "source_artifact_ids": candidate.metadata.get("source_artifact_ids", []),
                "long_context_digest": candidate.metadata.get("long_context_digest"),
                "long_context_workflow_id": candidate.metadata.get("long_context_workflow_id"),
                "long_context_summary": candidate.metadata.get("long_context_summary"),
                "long_context_artifact_ids": candidate.metadata.get("long_context_artifact_ids", []),
                "research_scaffold": candidate.metadata.get("research_scaffold"),
                "research_scaffold_path": candidate.metadata.get("research_scaffold_path"),
                "research_scaffold_kind": candidate.metadata.get("research_scaffold_kind"),
                "research_scaffold_title": candidate.metadata.get("research_scaffold_title"),
                "research_scaffold_created": candidate.metadata.get("research_scaffold_created"),
                "research_scaffold_relative_path": candidate.metadata.get("research_scaffold", {}).get("relative_path")
                if isinstance(candidate.metadata.get("research_scaffold"), dict)
                else None,
                "research_scaffold_doc_name": candidate.metadata.get("research_scaffold", {}).get("doc_name")
                if isinstance(candidate.metadata.get("research_scaffold"), dict)
                else None,
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
            self._finalize_session_resolved_reply_output(
                event=normalized_event,
                resolved=resolved,
                action_result=action_result,
                reply=reply,
            )
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
        if action_contract.needs_clarification:
            self._persist_promotion(candidate, promotion)
            promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
            reply = self._build_action_contract_clarification_reply(
                event=normalized_event,
                envelope_id=envelope.envelope_id,
                contract=action_contract,
            )
            dispatch = self._build_action_contract_dispatch(
                event=normalized_event,
                envelope=envelope,
                reply=reply,
                channel_class=channel_class,
                candidate_id=candidate.candidate_id,
                promotion_decision_id=promotion.promotion_decision_id,
                promoted_memory_ids=promoted_memory_ids,
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
                "gateway_action_contract_clarification_required",
                "gateway",
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "channel_event_id": normalized_event.event_id,
                    "candidate_id": candidate.candidate_id,
                    "contract_id": action_contract.contract_id,
                },
            )
            return dispatch
        if research_scaffold is not None and self.deep_research is not None:
            if str(research_scaffold.get("error") or "").strip():
                self._persist_promotion(candidate, promotion)
                promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
                dispatch = self._build_deep_research_dispatch(
                    event=normalized_event,
                    envelope=envelope,
                    promoted_memory_ids=promoted_memory_ids,
                    candidate_id=candidate.candidate_id,
                    promotion_decision_id=promotion.promotion_decision_id,
                    channel_class=channel_class,
                    job_payload={
                        "launched": False,
                        "error": str(research_scaffold.get("error") or "Preparation du dossier impossible."),
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
                    "gateway_deep_research_scaffold_blocked",
                    "gateway",
                    {
                        "dispatch_id": dispatch.dispatch_id,
                        "channel_event_id": normalized_event.event_id,
                        "error": research_scaffold.get("error"),
                    },
                )
                return dispatch
            if not self._deep_research_mode_ready(research_scaffold):
                self._persist_promotion(candidate, promotion)
                promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
                dispatch = self._build_deep_research_mode_selection_dispatch(
                    event=normalized_event,
                    envelope=envelope,
                    scaffold=research_scaffold,
                    channel_class=channel_class,
                    candidate_id=candidate.candidate_id,
                    promotion_decision_id=promotion.promotion_decision_id,
                    promoted_memory_ids=promoted_memory_ids,
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
                    "gateway_deep_research_mode_selection_required",
                    "gateway",
                    {
                        "dispatch_id": dispatch.dispatch_id,
                        "channel_event_id": normalized_event.event_id,
                        "approval_id": dispatch.metadata.get("approval_id"),
                    },
                )
                return dispatch
            self._persist_promotion(candidate, promotion)
            promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
            dispatch = self._build_deep_research_approval_dispatch(
                event=normalized_event,
                envelope=envelope,
                scaffold=research_scaffold,
                channel_class=channel_class,
                candidate_id=candidate.candidate_id,
                promotion_decision_id=promotion.promotion_decision_id,
                promoted_memory_ids=promoted_memory_ids,
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
                "gateway_deep_research_approval_required",
                "gateway",
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "channel_event_id": normalized_event.event_id,
                    "approval_id": dispatch.metadata.get("approval_id"),
                    "promoted_memory_count": len(promoted_memory_ids),
                },
            )
            return dispatch
        intent = self.router.envelope_to_intent(envelope)
        preview_decision, _, _ = self.router.route_intent(intent, persist=False)
        gateway_approval = self._maybe_create_gateway_route_approval(
            event=normalized_event,
            envelope=envelope,
            candidate=candidate,
            intent=intent,
            action_contract=action_contract,
            decision=preview_decision,
        )
        if gateway_approval is not None:
            self._persist_promotion(candidate, promotion)
            promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
            dispatch = self._build_gateway_approval_dispatch(
                event=normalized_event,
                envelope=envelope,
                approval=gateway_approval["approval"],
                reply=gateway_approval["reply"],
                channel_class=channel_class,
                candidate_id=candidate.candidate_id,
                promotion_decision_id=promotion.promotion_decision_id,
                promoted_memory_ids=promoted_memory_ids,
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
                "gateway_route_approval_required",
                "gateway",
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "channel_event_id": normalized_event.event_id,
                    "candidate_id": candidate.candidate_id,
                    "approval_id": gateway_approval["approval"].approval_id,
                    "proposal_kind": gateway_approval["metadata"]["proposal_kind"],
                },
            )
            return dispatch
        preview_inline_context: GatewayContextBundle | None = None
        reasoning_escalation = None
        if preview_decision.allowed and (
            self._should_inline_chat(normalized_event, preview_decision)
            or preview_decision.route_reason == "deterministic_fast_route"
        ):
            preview_inline_context = self.context_builder.build(
                event=normalized_event,
                envelope=envelope,
                candidate=candidate,
                decision=preview_decision,
                snapshot=snapshot,
                mission_run_id=None,
            )
            reasoning_escalation = self._maybe_create_reasoning_escalation_approval(
                event=normalized_event,
                envelope=envelope,
                candidate=candidate,
                intent=intent,
                decision=preview_decision,
                context_bundle=preview_inline_context,
            )
        if reasoning_escalation is not None:
            self._persist_promotion(candidate, promotion)
            promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
            dispatch = self._build_gateway_approval_dispatch(
                event=normalized_event,
                envelope=envelope,
                approval=reasoning_escalation["approval"],
                reply=reasoning_escalation["reply"],
                channel_class=channel_class,
                candidate_id=candidate.candidate_id,
                promotion_decision_id=promotion.promotion_decision_id,
                promoted_memory_ids=promoted_memory_ids,
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
                "gateway_reasoning_escalation_required",
                "gateway",
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "channel_event_id": normalized_event.event_id,
                    "approval_id": reasoning_escalation["approval"].approval_id,
                    "estimated_cost_eur": reasoning_escalation["metadata"]["estimated_cost_eur"],
                },
            )
            return dispatch

        decision, trace, mission_run = self.router.route_intent(intent, persist=True)
        promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
        inline_context: GatewayContextBundle | None = None

        if decision.allowed and self._should_inline_chat(normalized_event, decision):
            message_for_model = self._message_for_route(
                candidate,
                decision,
                discussion_mode=str(envelope.metadata.get("discussion_mode") or ""),
            )
            inline_context = self.context_builder.build(
                event=normalized_event,
                envelope=envelope,
                candidate=candidate,
                decision=decision,
                snapshot=snapshot,
                mission_run_id=mission_run.mission_run_id if mission_run else None,
            )
            inline_response = self._call_inline_chat(
                message=message_for_model,
                model=decision.model_route.model,
                provider=decision.model_route.provider,
                reasoning_effort=decision.model_route.reasoning_effort,
                sensitivity=self._candidate_sensitivity(candidate),
                route_reason=decision.route_reason,
                context_bundle=inline_context,
            )
            if inline_response:
                rendered_response = self._decorate_inline_reply_summary(inline_response, decision)
                reply = OperatorReply(
                    reply_id=new_id("reply"),
                    channel=normalized_event.message.channel,
                    envelope_id=envelope.envelope_id,
                    thread_ref=normalized_event.message.thread_ref,
                    summary=rendered_response,
                    mission_run_id=mission_run.mission_run_id if mission_run else None,
                    decision_id=decision.decision_id,
                    reply_kind="chat_response",
                    communication_mode=decision.communication_mode,
                    operator_language=decision.operator_language,
                    audience=decision.audience,
                    metadata={
                        "surface": normalized_event.surface,
                        "speech_policy": decision.speech_policy.value,
                        "research_scaffold_path": envelope.metadata.get("research_scaffold_path"),
                        "research_scaffold_kind": envelope.metadata.get("research_scaffold_kind"),
                        "research_scaffold_title": envelope.metadata.get("research_scaffold_title"),
                        "research_scaffold_relative_path": envelope.metadata.get("research_scaffold_relative_path"),
                        "research_scaffold_doc_name": envelope.metadata.get("research_scaffold_doc_name"),
                    },
                )
                if inline_context is not None:
                    reply.metadata["mood_hint"] = inline_context.mood_hint.mood
                    reply.metadata["handoff_task_id"] = inline_context.handoff_contract.task_id
                    reply.metadata["query_scope"] = inline_context.query_scope
                self._finalize_reply_artifact_output(
                    event=normalized_event,
                    candidate=candidate,
                    decision=decision,
                    reply=reply,
                    full_response=rendered_response,
                    context_bundle=inline_context,
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
                    metadata={
                        "surface": normalized_event.surface,
                        "speech_policy": decision.speech_policy.value,
                        "research_scaffold_path": envelope.metadata.get("research_scaffold_path"),
                        "research_scaffold_kind": envelope.metadata.get("research_scaffold_kind"),
                        "research_scaffold_title": envelope.metadata.get("research_scaffold_title"),
                        "research_scaffold_relative_path": envelope.metadata.get("research_scaffold_relative_path"),
                        "research_scaffold_doc_name": envelope.metadata.get("research_scaffold_doc_name"),
                    },
                )
            else:
                reply = self._build_reply(
                    normalized_event,
                    envelope.envelope_id,
                    decision,
                    mission_run.mission_run_id if mission_run else None,
                    envelope=envelope,
                )
        else:
            reply = self._build_reply(
                normalized_event,
                envelope.envelope_id,
                decision,
                mission_run.mission_run_id if mission_run else None,
                envelope=envelope,
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
                "intent_kind": candidate.metadata.get("intent_kind"),
                "delegation_level": candidate.metadata.get("delegation_level"),
                "interaction_state": candidate.metadata.get("interaction_state"),
                "suggested_next_state": candidate.metadata.get("suggested_next_state"),
                "intent_confidence": candidate.metadata.get("intent_confidence"),
                "intent_signals": candidate.metadata.get("intent_signals", []),
                "state_transition": candidate.metadata.get("state_transition"),
                "directive_detection": candidate.metadata.get("directive_detection"),
                "action_contract": candidate.metadata.get("action_contract"),
                "sensitivity_class": candidate.metadata.get("sensitivity_class", SensitivityClass.S1.value),
                "reply_kind": reply.reply_kind,
                "channel_class": channel_class.value,
                "communication_mode": communication_mode.value,
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                "source_artifact_ids": candidate.metadata.get("source_artifact_ids", []),
                "input_profile": candidate.metadata.get("input_profile"),
                "long_context_workflow_id": candidate.metadata.get("long_context_workflow_id"),
                "long_context_summary": candidate.metadata.get("long_context_summary"),
                "long_context_artifact_ids": candidate.metadata.get("long_context_artifact_ids", []),
                "response_delivery_mode": reply.response_manifest.delivery_mode if reply.response_manifest else None,
                "response_manifest_id": reply.response_manifest.metadata.get("manifest_artifact_id")
                if reply.response_manifest
                else None,
                "response_review_artifact_id": reply.response_manifest.review_artifact_id if reply.response_manifest else None,
                "model_provider": decision.model_route.provider,
                "requested_provider": envelope.metadata.get("requested_provider"),
                "requested_model": envelope.metadata.get("requested_model"),
                "requested_model_mode": envelope.metadata.get("requested_model_mode"),
                "message_prefix_consumed": envelope.metadata.get("message_prefix_consumed"),
                "mood_hint": inline_context.mood_hint.mood if inline_context else None,
                "query_scope": inline_context.query_scope if inline_context else None,
                "handoff_contract": to_jsonable(inline_context.handoff_contract) if inline_context else None,
                "thread_binding_projection_id": inline_context.thread_binding_id if inline_context else None,
                "thread_binding_projection_kind": inline_context.thread_binding_kind if inline_context else None,
                "research_scaffold_path": envelope.metadata.get("research_scaffold_path"),
                "research_scaffold_kind": envelope.metadata.get("research_scaffold_kind"),
                "research_scaffold_title": envelope.metadata.get("research_scaffold_title"),
                "research_scaffold_created": envelope.metadata.get("research_scaffold_created"),
                "research_scaffold_relative_path": envelope.metadata.get("research_scaffold_relative_path"),
                "research_scaffold_doc_name": envelope.metadata.get("research_scaffold_doc_name"),
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

    def _parse_operator_provider_override(self, raw_text: str) -> tuple[str, dict[str, str]] | None:
        stripped = raw_text.lstrip()
        if not stripped:
            return None
        prefixes = {
            "CLAUDE": {
                "requested_provider": "anthropic",
                "requested_model_family": "claude",
                "requested_model": self.router.execution_policy.discord_simple_model,
                "requested_model_mode": "claude",
            },
            "SONNET": {
                "requested_provider": "anthropic",
                "requested_model_family": "claude",
                "requested_model": self.router.execution_policy.discord_simple_model,
                "requested_model_mode": "sonnet",
            },
            "OPUS": {
                "requested_provider": "anthropic",
                "requested_model_family": "claude",
                "requested_model": self.router.execution_policy.discord_opus_model,
                "requested_model_mode": "opus",
            },
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
            "requested_model",
            "requested_model_mode",
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
        if resolved.action == "approve_runtime_approval":
            return self._approve_runtime_approval(resolved.target_id, resolved.metadata)
        if resolved.action == "reject_runtime_approval":
            return self._reject_runtime_approval(resolved.target_id)
        if resolved.action == "update_runtime_approval_selection":
            return self._update_runtime_approval_selection(resolved.target_id, resolved.metadata)
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

    def _approve_runtime_approval(self, approval_id: str | None, selection: dict[str, Any] | None = None) -> dict[str, object]:
        context = self._load_runtime_approval_context(approval_id)
        context_metadata = dict(context["metadata"])
        selection = dict(selection or {})
        if context_metadata.get("approval_type") == "reasoning_escalation" and selection.get("selected_mode"):
            score = int(context_metadata.get("assessment_score") or 3)
            objective = str(context_metadata.get("objective") or "").strip()
            explicit_longform = bool(context_metadata.get("explicit_longform"))
            recent_turn_count = int(context_metadata.get("recent_turn_count") or 0)
            input_tokens_override = int(context_metadata.get("estimated_input_tokens") or 0)
            selected_mode = self._resolve_discussion_mode(
                str(selection.get("selected_mode") or context_metadata.get("selected_mode") or context_metadata.get("recommended_mode") or "extreme"),
                fallback="extreme",
            )
            selected_spec = self._discussion_mode_spec(
                selected_mode,
                score=score,
                message=objective,
                explicit_longform=explicit_longform,
                recent_turn_count=recent_turn_count,
                input_tokens_override=input_tokens_override,
            )
            context_metadata = {
                **context_metadata,
                "selected_mode": selected_spec["mode"],
                "requested_provider": selected_spec["requested_provider"],
                "requested_model_family": selected_spec["requested_model_family"],
                "requested_model": selected_spec["requested_model"],
                "requested_model_mode": selected_spec["requested_model_mode"],
                "estimated_cost_eur": selected_spec["estimated_cost_eur"],
                "estimated_time_band": selected_spec["estimated_time_band"],
                "estimated_api_provider": selected_spec["requested_provider"],
                "estimated_api_model": selected_spec["requested_model"],
                "estimated_input_tokens": int(selected_spec.get("estimated_input_tokens") or input_tokens_override),
            }
            self._update_runtime_approval_metadata(str(context["approval_id"]), context_metadata)
            context = {**context, "metadata": context_metadata}
        resolution_metadata = {
            **context_metadata,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolution": "approved",
            "resolution_source": "discord",
        }
        self.router.runtime.resolve_approval(context["approval_id"], ApprovalStatus.APPROVED, metadata=resolution_metadata)
        if context["metadata"].get("approval_type") == "gateway_route_proposal":
            intent = self._rebuild_mission_intent(context["metadata"].get("intent_payload"))
            intent.metadata["founder_approved"] = True
            intent.metadata["approval_id"] = context["approval_id"]
            intent.metadata["approval_resolution_source"] = "discord"
            decision, trace, mission_run = self.router.route_intent(intent, persist=True)
            self.journal.append(
                "gateway_runtime_approval_applied",
                "gateway",
                {
                    "approval_id": context["approval_id"],
                    "decision_id": decision.decision_id,
                    "mission_run_id": mission_run.mission_run_id if mission_run else None,
                    "allowed": decision.allowed,
                },
            )
            return {
                "action": "approve_runtime_approval",
                "status": "approved_and_launched" if decision.allowed else "approved_but_blocked",
                "approval_id": context["approval_id"],
                "objective": intent.objective,
                "estimated_cost_eur": decision.budget_state.mission_estimate_eur,
                "api_label": self._describe_runtime_api(
                    provider=decision.model_route.provider,
                    model=decision.model_route.model,
                ),
                "api_provider": decision.model_route.provider,
                "api_model": decision.model_route.model,
                "decision_id": decision.decision_id,
                "run_id": mission_run.mission_run_id if mission_run else None,
                "run_launched": decision.allowed,
                "route_reason": decision.route_reason,
                "blocked_reasons": list(decision.blocked_reasons or []),
            }
        if context["metadata"].get("approval_type") == "deep_research_launch":
            scaffold = context["metadata"].get("research_scaffold")
            event_payload = context["metadata"].get("event_payload")
            event = self._rebuild_deep_research_event(event_payload)
            try:
                job_payload = self._maybe_launch_deep_research_job(event, scaffold if isinstance(scaffold, dict) else None) or {}
            except Exception as exc:
                job_payload = {"launched": False, "error": str(exc), "job_id": None, "job_path": None}
            launched = bool(job_payload.get("launched"))
            title = str(
                context["metadata"].get("research_scaffold_title")
                or (scaffold.get("title") if isinstance(scaffold, dict) else "")
                or "Deep Research"
            ).strip()
            objective = f"Recherche approfondie: {title}"
            self.journal.append(
                "gateway_runtime_approval_applied",
                "gateway",
                {
                    "approval_id": context["approval_id"],
                    "approval_type": "deep_research_launch",
                    "deep_research_job_id": job_payload.get("job_id"),
                    "deep_research_job_path": job_payload.get("job_path"),
                    "launched": launched,
                    "error": job_payload.get("error"),
                },
            )
            return {
                "action": "approve_runtime_approval",
                "status": "approved_and_launched" if launched else "approved_but_blocked",
                "approval_id": context["approval_id"],
                "approval_type": "deep_research_launch",
                "objective": objective,
                "estimated_cost_eur": float(context["metadata"].get("estimated_cost_eur") or 0.0),
                "estimated_time_band": context["metadata"].get("estimated_time_band"),
                "api_label": self._describe_runtime_api(
                    provider=str(context["metadata"].get("estimated_api_provider") or "openai"),
                    model=str(context["metadata"].get("estimated_api_model") or "") or None,
                ),
                "api_provider": str(context["metadata"].get("estimated_api_provider") or "openai"),
                "api_model": str(context["metadata"].get("estimated_api_model") or "") or None,
                "research_profile": context["metadata"].get("research_profile"),
                "research_intensity": context["metadata"].get("research_intensity"),
                "run_launched": launched,
                "deep_research_job_id": job_payload.get("job_id"),
                "deep_research_job_path": job_payload.get("job_path"),
                "deep_research_job_launched": launched,
                "dossier_relative_path": context["metadata"].get("research_scaffold_relative_path"),
                "doc_name": context["metadata"].get("research_scaffold_doc_name"),
                "error": job_payload.get("error"),
            }
        if context["metadata"].get("approval_type") == "reasoning_escalation":
            payload = self._execute_reasoning_escalation(context["metadata"], approval_id=context["approval_id"])
            self.journal.append(
                "gateway_runtime_approval_applied",
                "gateway",
                {
                    "approval_id": context["approval_id"],
                    "approval_type": "reasoning_escalation",
                    "decision_id": payload.get("decision_id"),
                    "mission_run_id": payload.get("run_id"),
                    "reply_kind": payload.get("reply_kind"),
                },
            )
            return payload
        return {
            "action": "approve_runtime_approval",
            "status": "approved",
            "approval_id": context["approval_id"],
        }

    def _reject_runtime_approval(self, approval_id: str | None) -> dict[str, object]:
        context = self._load_runtime_approval_context(approval_id)
        resolution_metadata = {
            **context["metadata"],
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolution": "rejected",
            "resolution_source": "discord",
        }
        self.router.runtime.resolve_approval(context["approval_id"], ApprovalStatus.REJECTED, metadata=resolution_metadata)
        self.journal.append(
            "gateway_runtime_approval_rejected",
            "gateway",
            {"approval_id": context["approval_id"]},
        )
        return {
            "action": "reject_runtime_approval",
            "status": "rejected",
            "approval_id": context["approval_id"],
            "approval_type": context["metadata"].get("approval_type"),
            "objective": (
                context["metadata"].get("intent_payload", {}).get("objective")
                or (
                    f"Recherche approfondie: {context['metadata'].get('research_scaffold_title')}"
                    if context["metadata"].get("approval_type") == "deep_research_launch"
                    and context["metadata"].get("research_scaffold_title")
                    else None
                )
            ),
            "summary": (
                (
                    f"Ok, je ne lance pas le {self._discussion_mode_spec(str(context['metadata'].get('selected_mode') or context['metadata'].get('recommended_mode') or 'avance'), score=int(context['metadata'].get('assessment_score') or 3), message=str(context['metadata'].get('objective') or ''), explicit_longform=bool(context['metadata'].get('explicit_longform')), recent_turn_count=int(context['metadata'].get('recent_turn_count') or 0), input_tokens_override=int(context['metadata'].get('estimated_input_tokens') or 0))['label'].lower()}. On reste sur le fil normal."
                )
                if context["metadata"].get("approval_type") == "reasoning_escalation"
                else "Choix du mode deep research annule. Rien n'est lance."
                if context["metadata"].get("approval_type") == "deep_research_mode_selection"
                else None
            ),
        }

    def _update_runtime_approval_selection(self, approval_id: str | None, selection: dict[str, Any] | None) -> dict[str, object]:
        context = self._load_runtime_approval_context(approval_id)
        metadata = dict(context["metadata"])
        approval_type = str(metadata.get("approval_type") or "").strip().lower()
        if approval_type == "reasoning_escalation":
            selection = dict(selection or {})
            score = int(metadata.get("assessment_score") or 3)
            recommended_mode = self._resolve_discussion_mode(
                str(metadata.get("recommended_mode") or metadata.get("selected_mode") or "extreme"),
                fallback="extreme",
            )
            selected_mode = self._resolve_discussion_mode(
                str(selection.get("selected_mode") or metadata.get("selected_mode") or recommended_mode),
                fallback=recommended_mode,
            )
            selected_spec = self._discussion_mode_spec(
                selected_mode,
                score=score,
                message=str(metadata.get("objective") or ""),
                explicit_longform=bool(metadata.get("explicit_longform")),
                recent_turn_count=int(metadata.get("recent_turn_count") or 0),
                input_tokens_override=int(metadata.get("estimated_input_tokens") or 0),
            )
            updated_metadata = {
                **metadata,
                "selected_mode": selected_spec["mode"],
                "requested_provider": selected_spec["requested_provider"],
                "requested_model_family": selected_spec["requested_model_family"],
                "requested_model": selected_spec["requested_model"],
                "requested_model_mode": selected_spec["requested_model_mode"],
                "estimated_cost_eur": selected_spec["estimated_cost_eur"],
                "estimated_time_band": selected_spec["estimated_time_band"],
                "estimated_api_provider": selected_spec["requested_provider"],
                "estimated_api_model": selected_spec["requested_model"],
                "estimated_input_tokens": int(selected_spec.get("estimated_input_tokens") or metadata.get("estimated_input_tokens") or 0),
            }
            self._update_runtime_approval_metadata(str(context["approval_id"]), updated_metadata)
            event = self._rebuild_deep_research_event(metadata.get("event_payload"))
            reply = self._build_reasoning_escalation_reply(
                event=event,
                envelope_id=str(context["approval_id"]),
                approval_id=str(context["approval_id"]),
                estimated_cost_eur=float(selected_spec["estimated_cost_eur"]),
                estimated_time_band=str(selected_spec["estimated_time_band"]),
                target_provider=str(selected_spec["requested_provider"]),
                target_model=str(selected_spec["requested_model"]),
                reasons=[str(item) for item in metadata.get("rationale") or []],
                selected_mode=selected_spec["mode"],
                recommended_mode=recommended_mode,
                score=score,
                objective=str(metadata.get("objective") or ""),
                explicit_longform=bool(metadata.get("explicit_longform")),
                recent_turn_count=int(metadata.get("recent_turn_count") or 0),
                input_tokens_override=int(selected_spec.get("estimated_input_tokens") or metadata.get("estimated_input_tokens") or 0),
            )
            self.journal.append(
                "gateway_runtime_approval_selection_updated",
                "gateway",
                {
                    "approval_id": context["approval_id"],
                    "status": "awaiting_go",
                    "discussion_mode": selected_spec["mode"],
                    "requested_model": selected_spec["requested_model"],
                },
            )
            return {
                "action": "update_runtime_approval_selection",
                "status": "awaiting_go",
                "approval_id": context["approval_id"],
                "approval_type": "reasoning_escalation",
                "selected_mode": selected_spec["mode"],
                "estimated_cost_eur": float(selected_spec["estimated_cost_eur"]),
                "estimated_time_band": str(selected_spec["estimated_time_band"]),
                "summary": reply.summary,
                "reply_kind": "approval_required",
                "communication_mode": CommunicationMode.GUARDIAN.value,
                "reply_metadata": reply.metadata,
            }
        if approval_type not in {"deep_research_mode_selection", "deep_research_launch"}:
            return {
                "action": "update_runtime_approval_selection",
                "status": "unsupported",
                "approval_id": context["approval_id"],
            }
        scaffold = dict(metadata.get("research_scaffold") or {})
        selection = dict(selection or {})
        selected_profile = str(
            selection.get("selected_profile")
            or metadata.get("selected_profile")
            or metadata.get("research_profile")
            or scaffold.get("explicit_profile")
            or ""
        ).strip().lower()
        selected_intensity = str(
            selection.get("selected_intensity")
            or metadata.get("selected_intensity")
            or metadata.get("research_intensity")
            or scaffold.get("explicit_intensity")
            or ""
        ).strip().lower()
        recommended_profile = str(
            metadata.get("recommended_profile")
            or scaffold.get("recommended_profile")
            or scaffold.get("research_profile")
            or "domain_audit"
        ).strip().lower()
        recommended_intensity = str(
            metadata.get("recommended_intensity")
            or scaffold.get("recommended_intensity")
            or scaffold.get("research_intensity")
            or "simple"
        ).strip().lower()
        updated_scaffold = {
            **scaffold,
            "research_profile": selected_profile or recommended_profile,
            "research_intensity": selected_intensity or recommended_intensity,
            "recommended_profile": recommended_profile,
            "recommended_intensity": recommended_intensity,
            "explicit_profile": selected_profile or None,
            "explicit_intensity": selected_intensity or None,
        }
        event = self._rebuild_deep_research_event(metadata.get("event_payload"))
        if selected_profile and selected_intensity:
            budget = self._estimated_deep_research_budget(updated_scaffold)
            updated_metadata = {
                **metadata,
                "approval_type": "deep_research_launch",
                "action_name": "deep_research_launch",
                "research_scaffold": to_jsonable(updated_scaffold),
                "research_scaffold_path": updated_scaffold.get("path"),
                "research_scaffold_kind": updated_scaffold.get("kind"),
                "research_scaffold_title": updated_scaffold.get("title"),
                "research_scaffold_relative_path": updated_scaffold.get("relative_path"),
                "research_scaffold_doc_name": updated_scaffold.get("doc_name"),
                "research_profile": selected_profile,
                "research_intensity": selected_intensity,
                "recommended_profile": recommended_profile,
                "recommended_intensity": recommended_intensity,
                "selected_profile": selected_profile,
                "selected_intensity": selected_intensity,
                "estimated_cost_eur": float(budget.get("estimated_cost_eur") or 0.0),
                "estimated_time_band": str(budget.get("estimated_time_band") or "moyen"),
                "estimated_api_provider": str(budget.get("estimated_api_provider") or "openai"),
                "estimated_api_model": str(budget.get("estimated_api_model") or "") or None,
            }
            self._update_runtime_approval_metadata(str(context["approval_id"]), updated_metadata)
            reply = self._build_deep_research_approval_reply(
                event=event,
                envelope_id=str(context["approval_id"]),
                approval_id=str(context["approval_id"]),
                scaffold=updated_scaffold,
                estimated_cost_eur=float(updated_metadata["estimated_cost_eur"]),
                estimated_time_band=str(updated_metadata["estimated_time_band"]),
                target_provider=str(updated_metadata["estimated_api_provider"] or "openai"),
                target_model=str(updated_metadata["estimated_api_model"] or "") or None,
            )
            status = "awaiting_go"
            reply_kind = "approval_required"
        else:
            updated_metadata = {
                **metadata,
                "approval_type": "deep_research_mode_selection",
                "action_name": "deep_research_mode_selection",
                "research_scaffold": to_jsonable(updated_scaffold),
                "selected_profile": selected_profile or None,
                "selected_intensity": selected_intensity or None,
                "recommended_profile": recommended_profile,
                "recommended_intensity": recommended_intensity,
            }
            self._update_runtime_approval_metadata(str(context["approval_id"]), updated_metadata)
            reply = self._build_deep_research_mode_selection_reply(
                event=event,
                envelope_id=str(context["approval_id"]),
                approval_id=str(context["approval_id"]),
                scaffold=updated_scaffold,
            )
            status = "awaiting_mode"
            reply_kind = "clarification_required"
        self.journal.append(
            "gateway_runtime_approval_selection_updated",
            "gateway",
            {
                "approval_id": context["approval_id"],
                "status": status,
                "research_profile": updated_scaffold.get("research_profile"),
                "research_intensity": updated_scaffold.get("research_intensity"),
            },
        )
        return {
            "action": "update_runtime_approval_selection",
            "status": status,
            "approval_id": context["approval_id"],
            "approval_type": updated_metadata.get("approval_type"),
            "research_profile": updated_scaffold.get("research_profile"),
            "research_intensity": updated_scaffold.get("research_intensity"),
            "summary": reply.summary,
            "reply_kind": reply_kind,
            "communication_mode": CommunicationMode.GUARDIAN.value,
            "reply_metadata": reply.metadata,
        }

    def _update_runtime_approval_metadata(self, approval_id: str, metadata: dict[str, Any]) -> None:
        self.database.execute(
            """
            UPDATE approval_records
            SET payload_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE approval_id = ?
            """,
            (dump_json(metadata), approval_id),
        )

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

    def _load_runtime_approval_context(self, approval_id: str | None) -> dict[str, object]:
        if not approval_id:
            raise KeyError("approval id is required")
        row = self.database.fetchone(
            """
            SELECT approval_id, mission_run_id, requested_by, risk_tier, reason, status, payload_json, created_at, updated_at
            FROM approval_records
            WHERE approval_id = ?
            """,
            (approval_id,),
        )
        if row is None:
            raise KeyError(f"Unknown approval: {approval_id}")
        return {
            "approval_id": str(row["approval_id"]),
            "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
            "requested_by": str(row["requested_by"]),
            "risk_tier": str(row["risk_tier"]),
            "reason": str(row["reason"]),
            "status": str(row["status"]),
            "metadata": json.loads(row["payload_json"]) if row["payload_json"] else {},
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _rebuild_mission_intent(self, payload: object) -> MissionIntent:
        raw = payload if isinstance(payload, dict) else {}
        requested_risk_raw = str(raw.get("requested_risk_class") or "").strip().lower()
        try:
            requested_risk = ActionRiskClass(requested_risk_raw) if requested_risk_raw else None
        except Exception:
            requested_risk = None
        communication_mode_raw = str(raw.get("communication_mode") or "").strip().lower()
        try:
            communication_mode = CommunicationMode(communication_mode_raw) if communication_mode_raw else CommunicationMode.DISCUSSION
        except Exception:
            communication_mode = CommunicationMode.DISCUSSION
        audience_raw = str(raw.get("audience") or "").strip().lower()
        try:
            audience = OperatorAudience(audience_raw) if audience_raw else OperatorAudience.NON_DEVELOPER
        except Exception:
            audience = OperatorAudience.NON_DEVELOPER
        metadata = raw.get("metadata")
        return MissionIntent(
            intent_id=new_id("intent"),
            source="gateway_runtime_approval",
            actor_id=str(raw.get("actor_id") or "founder"),
            channel=str(raw.get("channel") or "discord"),
            objective=str(raw.get("objective") or ""),
            target_profile=str(raw.get("target_profile")) if raw.get("target_profile") else None,
            requested_worker=str(raw.get("requested_worker")) if raw.get("requested_worker") else None,
            requested_risk_class=requested_risk,
            communication_mode=communication_mode,
            operator_language=str(raw.get("operator_language") or "fr"),
            audience=audience,
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )

    def _execute_reasoning_escalation(self, metadata: dict[str, Any], *, approval_id: str) -> dict[str, object]:
        event = self._rebuild_deep_research_event(metadata.get("event_payload"))
        selected_mode = self._resolve_discussion_mode(
            str(metadata.get("selected_mode") or metadata.get("recommended_mode") or "extreme"),
            fallback="extreme",
        )
        message_metadata = {
            **event.message.metadata,
            "requested_provider": str(metadata.get("requested_provider") or "anthropic"),
            "requested_model_family": str(metadata.get("requested_model_family") or "claude"),
            "requested_model": str(metadata.get("requested_model") or self.router.execution_policy.discord_opus_model),
            "requested_model_mode": str(metadata.get("requested_model_mode") or "opus"),
            "requested_route_mode": "approval_escalation",
            "approval_id": approval_id,
            "approval_resolution_source": "discord",
            "founder_approved": True,
            "discussion_mode": selected_mode,
        }
        escalated_event = replace(event, message=replace(event.message, metadata=message_metadata))
        candidate = self.selective_sync.build_candidate(escalated_event)
        channel_class = self._channel_class_for(
            escalated_event.message.channel,
            escalated_event.message.thread_ref.parent_thread_id,
        )
        communication_mode = self._communication_mode_for(
            candidate.classification,
            channel_class,
            intent_kind=str(candidate.metadata.get("intent_kind") or ""),
            delegation_level=str(candidate.metadata.get("delegation_level") or ""),
        )
        envelope = OperatorEnvelope(
            envelope_id=new_id("envelope"),
            actor_id=escalated_event.message.actor_id,
            channel=escalated_event.message.channel,
            objective=escalated_event.message.text.strip() or candidate.summary,
            target_profile=str(metadata.get("target_profile") or "core"),
            communication_mode=communication_mode,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "channel_event_id": escalated_event.event_id,
                "message_kind": candidate.classification.value,
                "intent_kind": candidate.metadata.get("intent_kind"),
                "delegation_level": candidate.metadata.get("delegation_level"),
                "interaction_state": candidate.metadata.get("interaction_state"),
                "suggested_next_state": candidate.metadata.get("suggested_next_state"),
                "intent_confidence": candidate.metadata.get("intent_confidence"),
                "intent_signals": candidate.metadata.get("intent_signals", []),
                "state_transition": candidate.metadata.get("state_transition"),
                "directive_detection": candidate.metadata.get("directive_detection"),
                "channel_class": channel_class.value,
                "sensitivity_class": candidate.metadata.get("sensitivity_class", SensitivityClass.S1.value),
                "input_profile": candidate.metadata.get("input_profile"),
                "requested_provider": message_metadata.get("requested_provider"),
                "requested_model_family": message_metadata.get("requested_model_family"),
                "requested_model": message_metadata.get("requested_model"),
                "requested_model_mode": message_metadata.get("requested_model_mode"),
                "requested_route_mode": message_metadata.get("requested_route_mode"),
                "discussion_mode": selected_mode,
                "approval_id": approval_id,
            },
        )
        intent = self.router.envelope_to_intent(envelope)
        decision, _, mission_run = self.router.route_intent(intent, persist=True)
        snapshot = self.session_state.load()
        if decision.allowed and self._should_inline_chat(escalated_event, decision):
            context_bundle = self.context_builder.build(
                event=escalated_event,
                envelope=envelope,
                candidate=candidate,
                decision=decision,
                snapshot=snapshot,
                mission_run_id=mission_run.mission_run_id if mission_run else None,
            )
            inline_response = self._call_inline_chat(
                message=self._message_for_route(candidate, decision, discussion_mode=selected_mode),
                model=decision.model_route.model,
                provider=decision.model_route.provider,
                reasoning_effort=decision.model_route.reasoning_effort,
                sensitivity=self._candidate_sensitivity(candidate),
                route_reason=decision.route_reason,
                context_bundle=context_bundle,
            )
            if inline_response:
                return {
                    "action": "approve_runtime_approval",
                    "status": "approved_and_answered",
                    "approval_id": approval_id,
                    "approval_type": "reasoning_escalation",
                    "objective": escalated_event.message.text,
                    "estimated_cost_eur": float(metadata.get("estimated_cost_eur") or 0.0),
                    "decision_id": decision.decision_id,
                    "run_id": mission_run.mission_run_id if mission_run else None,
                    "run_launched": False,
                    "reply_kind": "chat_response",
                    "communication_mode": decision.communication_mode.value,
                    "summary": self._decorate_inline_reply_summary(inline_response, decision),
                    "route_reason": decision.route_reason,
                    "api_label": self._describe_runtime_api(
                        provider=decision.model_route.provider,
                        model=decision.model_route.model,
                    ),
                    "api_provider": decision.model_route.provider,
                    "api_model": decision.model_route.model,
                    "selected_mode": selected_mode,
                    "input_profile": candidate.metadata.get("input_profile"),
                    "force_artifact_summary": bool(metadata.get("explicit_longform")),
                }
            return {
                "action": "approve_runtime_approval",
                "status": "approved_but_blocked",
                "approval_id": approval_id,
                "approval_type": "reasoning_escalation",
                "objective": escalated_event.message.text,
                "estimated_cost_eur": float(metadata.get("estimated_cost_eur") or 0.0),
                "decision_id": decision.decision_id,
                "run_id": mission_run.mission_run_id if mission_run else None,
                "run_launched": False,
                "reply_kind": "blocked",
                "communication_mode": CommunicationMode.GUARDIAN.value,
                "summary": "Bascule Opus approuvee, mais la reponse n'a pas pu etre calculee.",
                "route_reason": decision.route_reason,
            }
        reason = self._translate_block_reason(decision.blocked_reasons or [decision.route_reason])
        return {
            "action": "approve_runtime_approval",
            "status": "approved_but_blocked",
            "approval_id": approval_id,
            "approval_type": "reasoning_escalation",
            "objective": escalated_event.message.text,
            "estimated_cost_eur": float(metadata.get("estimated_cost_eur") or 0.0),
            "decision_id": decision.decision_id,
            "run_id": mission_run.mission_run_id if mission_run else None,
            "run_launched": False,
            "reply_kind": "blocked",
            "communication_mode": CommunicationMode.GUARDIAN.value,
            "summary": f"Bascule Opus approuvee, mais la route reste bloquee: {reason}",
            "route_reason": decision.route_reason,
            "blocked_reasons": list(decision.blocked_reasons or []),
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
        reply_kind = str(
            action_result.get("reply_kind")
            or ("ack" if str(action_result.get("status")) not in {"missing_target", "unhandled"} else "blocked")
        )
        communication_mode_raw = str(action_result.get("communication_mode") or "").strip().lower()
        try:
            communication_mode = CommunicationMode(communication_mode_raw) if communication_mode_raw else None
        except Exception:
            communication_mode = None
        if communication_mode is None:
            communication_mode = (
                CommunicationMode.GUARDIAN
                if resolved.action in {
                    "approve_contract",
                    "reject_contract",
                    "approve_runtime_approval",
                    "reject_runtime_approval",
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
            metadata={
                "surface": event.surface,
                "resolved_action": resolved.action,
                **(
                    dict(action_result.get("reply_metadata"))
                    if isinstance(action_result.get("reply_metadata"), dict)
                    else {}
                ),
            },
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
                "source_artifact_ids": list(envelope.metadata.get("source_artifact_ids") or []),
                "input_profile": envelope.metadata.get("input_profile"),
                "intent_kind": envelope.metadata.get("intent_kind"),
                "delegation_level": envelope.metadata.get("delegation_level"),
                "interaction_state": envelope.metadata.get("interaction_state"),
                "suggested_next_state": envelope.metadata.get("suggested_next_state"),
                "intent_confidence": envelope.metadata.get("intent_confidence"),
                "intent_signals": list(envelope.metadata.get("intent_signals") or []),
                "state_transition": envelope.metadata.get("state_transition"),
                "directive_detection": envelope.metadata.get("directive_detection"),
                "action_contract": envelope.metadata.get("action_contract"),
                "resolved_action": resolved.action,
                "resolved_target_id": resolved.target_id,
                "resolved_confidence": resolved.confidence,
                "response_delivery_mode": reply.response_manifest.delivery_mode if reply.response_manifest else None,
                "response_manifest_id": reply.response_manifest.metadata.get("manifest_artifact_id")
                if reply.response_manifest
                else None,
                "response_review_artifact_id": reply.response_manifest.review_artifact_id if reply.response_manifest else None,
                "action_result": to_jsonable(action_result),
            },
        )

    def _finalize_session_resolved_reply_output(
        self,
        *,
        event: ChannelEvent,
        resolved: ResolvedIntent,
        action_result: dict[str, Any],
        reply: OperatorReply,
    ) -> None:
        if resolved.action != "approve_runtime_approval":
            return
        if str(action_result.get("approval_type") or "").strip().lower() != "reasoning_escalation":
            return
        full_response = str(action_result.get("summary") or "").strip()
        if not full_response:
            return
        candidate = self.selective_sync.build_candidate(event)
        input_profile = str(action_result.get("input_profile") or "").strip().lower()
        if input_profile:
            candidate.metadata["input_profile"] = input_profile
        if bool(action_result.get("force_artifact_summary")):
            candidate.metadata["force_artifact_summary"] = True
        decision_like = SimpleNamespace(
            model_route=SimpleNamespace(
                provider=str(action_result.get("api_provider") or "unknown").strip() or "unknown",
                model=str(action_result.get("api_model") or "").strip() or None,
            )
        )
        self._finalize_reply_artifact_output(
            event=event,
            candidate=candidate,
            decision=decision_like,
            reply=reply,
            full_response=full_response,
            context_bundle=None,
        )

    def _build_action_contract_clarification_reply(
        self,
        *,
        event: ChannelEvent,
        envelope_id: str,
        contract: ActionContract,
    ) -> OperatorReply:
        return OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=envelope_id,
            thread_ref=event.message.thread_ref,
            summary=contract.clarification_question or "Tu veux quel livrable concret exactement ?",
            mission_run_id=None,
            decision_id=None,
            reply_kind="clarification_required",
            communication_mode=CommunicationMode.BUILDER,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "surface": event.surface,
                "clarification_gate": True,
                "action_contract": to_jsonable(contract),
            },
        )

    def _build_action_contract_dispatch(
        self,
        *,
        event: ChannelEvent,
        envelope: OperatorEnvelope,
        reply: OperatorReply,
        channel_class: DiscordChannelClass,
        candidate_id: str,
        promotion_decision_id: str,
        promoted_memory_ids: list[str],
        human_artifacts: list,
    ) -> GatewayDispatchResult:
        return GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=event.event_id,
            envelope_id=envelope.envelope_id,
            intent_id=new_id("action_contract_intent"),
            decision_id=None,
            mission_run_id=None,
            operator_reply=reply,
            promoted_memory_ids=promoted_memory_ids,
            memory_candidate_id=candidate_id,
            promotion_decision_id=promotion_decision_id,
            discord_run_card=None,
            metadata={
                "classification": envelope.metadata.get("message_kind"),
                "reply_kind": reply.reply_kind,
                "channel_class": channel_class.value,
                "communication_mode": reply.communication_mode.value,
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                "source_artifact_ids": list(envelope.metadata.get("source_artifact_ids") or []),
                "input_profile": envelope.metadata.get("input_profile"),
                "intent_kind": envelope.metadata.get("intent_kind"),
                "delegation_level": envelope.metadata.get("delegation_level"),
                "interaction_state": envelope.metadata.get("interaction_state"),
                "suggested_next_state": InteractionState.DIRECTIVE.value,
                "intent_confidence": envelope.metadata.get("intent_confidence"),
                "intent_signals": list(envelope.metadata.get("intent_signals") or []),
                "state_transition": "directive->directive",
                "directive_detection": envelope.metadata.get("directive_detection"),
                "action_contract": envelope.metadata.get("action_contract"),
                "clarification_gate": True,
            },
        )

    def _maybe_create_gateway_route_approval(
        self,
        *,
        event: ChannelEvent,
        envelope: OperatorEnvelope,
        candidate,
        intent: MissionIntent,
        action_contract: ActionContract,
        decision: RoutingDecision,
    ) -> dict[str, Any] | None:
        proposal_kind = self._gateway_route_approval_kind(
            event=event,
            action_contract=action_contract,
            decision=decision,
        )
        if proposal_kind is None:
            return None
        approval_reason = self._gateway_route_approval_reason(
            action_contract=action_contract,
            decision=decision,
            proposal_kind=proposal_kind,
        )
        time_band = self._estimated_time_band(decision.budget_state.mission_cost_class)
        approval_metadata = {
            "approval_type": "gateway_route_proposal",
            "proposal_kind": proposal_kind,
            "estimated_cost_eur": decision.budget_state.mission_estimate_eur,
            "estimated_time_band": time_band,
            "routing_preview": to_jsonable(decision),
            "action_contract": to_jsonable(action_contract),
            "intent_payload": to_jsonable(intent),
            "channel_event_id": event.event_id,
            "thread_ref": to_jsonable(event.message.thread_ref),
            "message_text": event.message.text,
            "input_profile": candidate.metadata.get("input_profile"),
        }
        approval = self.router.runtime.create_approval(
            requested_by="gateway_discord",
            risk_tier=decision.risk_class.value,
            reason=approval_reason,
            metadata=approval_metadata,
        )
        reply = self._build_gateway_approval_reply(
            event=event,
            envelope_id=envelope.envelope_id,
            approval_id=approval.approval_id,
            action_contract=action_contract,
            decision=decision,
            proposal_kind=proposal_kind,
            time_band=time_band,
        )
        return {"approval": approval, "reply": reply, "metadata": approval_metadata}

    @staticmethod
    def _gateway_route_approval_kind(
        *,
        event: ChannelEvent,
        action_contract: ActionContract,
        decision: RoutingDecision,
    ) -> str | None:
        if event.surface != "discord":
            return None
        if action_contract.intent_kind not in {IntentKind.DIRECTIVE_IMPLICIT, IntentKind.DIRECTIVE_EXPLICIT}:
            return None
        if decision.approval_gate.required and not decision.approval_gate.approved:
            return "approval_gate"
        if (
            decision.allowed
            and action_contract.execution_ready
            and decision.communication_mode is CommunicationMode.BUILDER
            and decision.model_route.route_class in {CostClass.HARD, CostClass.EXCEPTIONAL}
        ):
            return "cost_confirmation"
        return None

    @staticmethod
    def _gateway_route_approval_reason(
        *,
        action_contract: ActionContract,
        decision: RoutingDecision,
        proposal_kind: str,
    ) -> str:
        if proposal_kind == "cost_confirmation":
            return "confirmation_cout_operation"
        if action_contract.needs_approval:
            return action_contract.approval_reason or "validation_fondateur_requise"
        if decision.approval_gate.reason:
            return decision.approval_gate.reason
        return "validation_fondateur_requise"

    def _build_gateway_approval_reply(
        self,
        *,
        event: ChannelEvent,
        envelope_id: str,
        approval_id: str,
        action_contract: ActionContract,
        decision: RoutingDecision,
        proposal_kind: str,
        time_band: str,
    ) -> OperatorReply:
        objective = action_contract.objective.strip() or "cette operation"
        expected_output = action_contract.expected_output or "livrable"
        estimated_cost = float(decision.budget_state.mission_estimate_eur or 0.0)
        api_label = self._describe_runtime_api(provider=decision.model_route.provider, model=decision.model_route.model)
        if proposal_kind == "cost_confirmation":
            intro = "Je pense que lancer cette operation maintenant est le bon move."
        elif action_contract.needs_approval:
            intro = "Cette action demande une validation fondateur avant execution."
        else:
            intro = "Cette operation a besoin d'une validation explicite avant lancement."
        lines = [
            intro,
            f"Objectif: {objective}",
            f"Livrable attendu: {expected_output}",
            f"Cout estime: ~{estimated_cost:.2f} EUR.",
            f"Temps estime: {time_band}.",
            f"API utilisee: {api_label}.",
            "Reponds go pour lancer ou stop pour annuler.",
        ]
        return OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=envelope_id,
            thread_ref=event.message.thread_ref,
            summary="\n".join(lines),
            mission_run_id=None,
            decision_id=None,
            reply_kind="approval_required",
            communication_mode=CommunicationMode.GUARDIAN,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "surface": event.surface,
                "approval_id": approval_id,
                "proposal_kind": proposal_kind,
                "estimated_cost_eur": estimated_cost,
                "estimated_time_band": time_band,
                "estimated_api_label": api_label,
                "estimated_api_provider": decision.model_route.provider,
                "estimated_api_model": decision.model_route.model,
                "action_contract": to_jsonable(action_contract),
                "routing_preview": to_jsonable(decision),
            },
        )

    def _build_gateway_approval_dispatch(
        self,
        *,
        event: ChannelEvent,
        envelope: OperatorEnvelope,
        approval,
        reply: OperatorReply,
        channel_class: DiscordChannelClass,
        candidate_id: str,
        promotion_decision_id: str,
        promoted_memory_ids: list[str],
        human_artifacts: list,
    ) -> GatewayDispatchResult:
        return GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=event.event_id,
            envelope_id=envelope.envelope_id,
            intent_id=new_id("approval_intent"),
            decision_id=None,
            mission_run_id=None,
            operator_reply=reply,
            promoted_memory_ids=promoted_memory_ids,
            memory_candidate_id=candidate_id,
            promotion_decision_id=promotion_decision_id,
            discord_run_card=None,
            metadata={
                "classification": envelope.metadata.get("message_kind"),
                "reply_kind": reply.reply_kind,
                "channel_class": channel_class.value,
                "communication_mode": reply.communication_mode.value,
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                "source_artifact_ids": list(envelope.metadata.get("source_artifact_ids") or []),
                "input_profile": envelope.metadata.get("input_profile"),
                "intent_kind": envelope.metadata.get("intent_kind"),
                "delegation_level": envelope.metadata.get("delegation_level"),
                "interaction_state": envelope.metadata.get("interaction_state"),
                "suggested_next_state": InteractionState.APPROVAL.value,
                "intent_confidence": envelope.metadata.get("intent_confidence"),
                "intent_signals": list(envelope.metadata.get("intent_signals") or []),
                "state_transition": "directive->approval",
                "directive_detection": envelope.metadata.get("directive_detection"),
                "action_contract": envelope.metadata.get("action_contract"),
                "approval_id": approval.approval_id,
                "approval_reason": approval.reason,
                "approval_metadata": to_jsonable(approval.metadata),
            },
        )

    @staticmethod
    def _normalize_keyword_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        return normalized.encode("ascii", "ignore").decode("ascii").lower()

    @staticmethod
    def _resolve_discussion_mode(raw_value: str | None, *, fallback: str = "avance") -> str:
        normalized = GatewayService._normalize_keyword_text(str(raw_value or "")).strip()
        return _DISCUSSION_MODE_ALIASES.get(normalized, fallback)

    def _estimate_discussion_input_tokens(
        self,
        *,
        message: str,
        model: str,
        route_reason: str,
    ) -> int | None:
        api_key = self.secret_resolver.get_optional("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        normalized_key = str(api_key).strip().lower()
        if normalized_key.startswith("sk-ant-test") or "test-secret" in normalized_key or normalized_key.endswith("-test"):
            return None
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.count_tokens(
                model=model,
                system=self._simple_chat_system_blocks(),
                messages=[
                    {
                        "role": "user",
                        "content": self._simple_chat_user_message(
                            message,
                            provider="anthropic",
                            model=model,
                            route_reason=route_reason,
                        ),
                    }
                ],
            )
            counted = int(getattr(response, "input_tokens", 0) or 0)
            return counted if counted > 0 else None
        except Exception as exc:
            logging.getLogger("project_os.gateway").debug("anthropic count_tokens estimate unavailable: %s", exc)
            return None

    def _discussion_mode_spec(
        self,
        mode: str,
        *,
        score: int,
        message: str | None = None,
        explicit_longform: bool = False,
        recent_turn_count: int = 0,
        input_tokens_override: int | None = None,
    ) -> dict[str, Any]:
        normalized_mode = self._resolve_discussion_mode(mode)
        if normalized_mode == "simple":
            spec = {
                "mode": "simple",
                "label": "Mode simple",
                "description": "rapide, direct, peu verbeux",
                "requested_provider": "anthropic",
                "requested_model_family": "claude",
                "requested_model": self.router.execution_policy.discord_simple_model,
                "requested_model_mode": "sonnet",
                "estimated_time_band": "rapide",
            }
        elif normalized_mode == "extreme":
            spec = {
                "mode": "extreme",
                "label": "Mode extreme",
                "description": "le plus detaille, pense pour du long",
                "requested_provider": "anthropic",
                "requested_model_family": "claude",
                "requested_model": self.router.execution_policy.discord_opus_model,
                "requested_model_mode": "opus",
                "estimated_time_band": "long",
            }
        else:
            spec = {
                "mode": "avance",
                "label": "Mode avance",
                "description": "detaille, structure, toujours fluide sur Discord",
                "requested_provider": "anthropic",
                "requested_model_family": "claude",
                "requested_model": self.router.execution_policy.discord_simple_model,
                "requested_model_mode": "sonnet",
                "estimated_time_band": "court",
            }

        message_text = str(message or "").strip()
        base_input_tokens = int(input_tokens_override or 0)
        if base_input_tokens <= 0 and message_text:
            base_input_tokens = self._estimate_discussion_input_tokens(
                message=message_text,
                model=str(spec["requested_model"]),
                route_reason=(
                    "operator_forced_opus_route"
                    if normalized_mode == "extreme"
                    else "operator_forced_sonnet_route"
                ),
            ) or 0
        if base_input_tokens <= 0 and message_text:
            base_input_tokens = estimate_text_tokens(message_text) + 260

        usage = estimate_discussion_usage(
            message=message_text,
            mode=normalized_mode,
            score=score,
            explicit_longform=explicit_longform,
            recent_turn_count=recent_turn_count,
            base_input_tokens=base_input_tokens if base_input_tokens > 0 else None,
        )
        spec["estimated_input_tokens"] = usage.input_tokens
        spec["estimated_output_tokens"] = usage.output_tokens
        spec["estimated_cost_eur"] = estimate_usage_cost_eur(
            model=str(spec["requested_model"]),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        return spec

    @staticmethod
    def _recommended_discussion_mode(assessment: dict[str, Any]) -> str:
        if assessment.get("explicit_longform"):
            return "extreme"
        if int(assessment.get("score") or 0) >= 4:
            return "extreme"
        return "avance"

    def _maybe_create_reasoning_escalation_approval(
        self,
        *,
        event: ChannelEvent,
        envelope: OperatorEnvelope,
        candidate,
        intent: MissionIntent,
        decision: RoutingDecision,
        context_bundle: GatewayContextBundle,
    ) -> dict[str, Any] | None:
        if event.surface != "discord":
            return None
        if str(envelope.metadata.get("requested_provider") or "").strip():
            return None
        if decision.route_reason not in {"discord_simple_route", "deterministic_fast_route"}:
            return None
        if decision.communication_mode not in {CommunicationMode.DISCUSSION, CommunicationMode.ARCHITECT}:
            return None
        if str(candidate.classification.value) not in {"chat", "decision", "idea", "note"}:
            return None
        if str(candidate.metadata.get("intent_kind") or "") not in {
            IntentKind.DISCUSSION.value,
            IntentKind.DECISION_SIGNAL.value,
        }:
            return None
        if context_bundle.query_scope != "contextual":
            return None
        assessment = self._assess_reasoning_escalation_need(message=event.message.text, context_bundle=context_bundle)
        if int(assessment["score"]) < 3:
            return None
        recommended_mode = self._recommended_discussion_mode(assessment)
        recent_turn_count = len(context_bundle.recent_thread_messages) + len(context_bundle.recent_operator_replies)
        selected_spec = self._discussion_mode_spec(
            recommended_mode,
            score=int(assessment["score"]),
            message=event.message.text,
            explicit_longform=bool(assessment.get("explicit_longform")),
            recent_turn_count=recent_turn_count,
        )
        escalation_metadata = {
            **intent.metadata,
            "requested_provider": selected_spec["requested_provider"],
            "requested_model_family": selected_spec["requested_model_family"],
            "requested_model": selected_spec["requested_model"],
            "requested_model_mode": selected_spec["requested_model_mode"],
            "approval_resolution_source": "discord",
        }
        escalation_intent = replace(intent, metadata=escalation_metadata)
        escalation_decision, _, _ = self.router.route_intent(escalation_intent, persist=False)
        if not escalation_decision.allowed:
            return None
        approval_metadata = {
            "approval_type": "reasoning_escalation",
            "action_name": "reasoning_escalation_mode",
            "proposal_kind": "discussion_mode_selection",
            "selected_mode": selected_spec["mode"],
            "recommended_mode": recommended_mode,
            "estimated_cost_eur": selected_spec["estimated_cost_eur"],
            "estimated_time_band": selected_spec["estimated_time_band"],
            "estimated_api_provider": escalation_decision.model_route.provider,
            "estimated_api_model": escalation_decision.model_route.model,
            "objective": event.message.text,
            "rationale": [str(item) for item in assessment["reasons"]],
            "assessment_score": int(assessment["score"]),
            "explicit_longform": bool(assessment.get("explicit_longform")),
            "recent_turn_count": recent_turn_count,
            "estimated_input_tokens": int(selected_spec.get("estimated_input_tokens") or 0),
            "event_payload": self._serialize_deep_research_event(event),
            "target_profile": envelope.target_profile,
            "requested_provider": escalation_metadata["requested_provider"],
            "requested_model_family": escalation_metadata["requested_model_family"],
            "requested_model": escalation_metadata["requested_model"],
            "requested_model_mode": escalation_metadata["requested_model_mode"],
            "channel_event_id": event.event_id,
            "thread_ref": to_jsonable(event.message.thread_ref),
            "input_profile": envelope.metadata.get("input_profile"),
        }
        approval = self.router.runtime.create_approval(
            requested_by="gateway_discord",
            risk_tier="medium",
            reason="reasoning_escalation_recommended",
            metadata=approval_metadata,
        )
        reply = self._build_reasoning_escalation_reply(
            event=event,
            envelope_id=envelope.envelope_id,
            approval_id=approval.approval_id,
            estimated_cost_eur=float(selected_spec["estimated_cost_eur"]),
            estimated_time_band=str(selected_spec["estimated_time_band"]),
            target_provider=escalation_decision.model_route.provider,
            target_model=escalation_decision.model_route.model,
            reasons=[str(item) for item in assessment["reasons"]],
            selected_mode=str(selected_spec["mode"]),
            recommended_mode=recommended_mode,
            score=int(assessment["score"]),
            objective=event.message.text,
            explicit_longform=bool(assessment.get("explicit_longform")),
            recent_turn_count=recent_turn_count,
            input_tokens_override=int(selected_spec.get("estimated_input_tokens") or 0),
        )
        return {"approval": approval, "reply": reply, "metadata": approval_metadata}

    def _build_reasoning_escalation_reply(
        self,
        *,
        event: ChannelEvent,
        envelope_id: str,
        approval_id: str,
        estimated_cost_eur: float,
        estimated_time_band: str,
        target_provider: str,
        target_model: str | None,
        reasons: list[str],
        selected_mode: str,
        recommended_mode: str,
        score: int,
        objective: str,
        explicit_longform: bool,
        recent_turn_count: int,
        input_tokens_override: int,
    ) -> OperatorReply:
        api_label = self._describe_runtime_api(provider=target_provider, model=target_model)
        selected_spec = self._discussion_mode_spec(
            selected_mode,
            score=score,
            message=objective,
            explicit_longform=explicit_longform,
            recent_turn_count=recent_turn_count,
            input_tokens_override=input_tokens_override,
        )
        recommended_spec = self._discussion_mode_spec(
            recommended_mode,
            score=score,
            message=objective,
            explicit_longform=explicit_longform,
            recent_turn_count=recent_turn_count,
            input_tokens_override=input_tokens_override,
        )
        lines = [f"Je te recommande le {recommended_spec['label'].lower()} pour cette discussion."]
        if reasons:
            lines.append(f"Pourquoi: {'; '.join(reasons[:3])}.")
        lines.extend(
            [
                "",
                "Modes disponibles:",
            ]
        )
        for mode_name in ("simple", "avance", "extreme"):
            mode_spec = self._discussion_mode_spec(
                mode_name,
                score=score,
                message=objective,
                explicit_longform=explicit_longform,
                recent_turn_count=recent_turn_count,
                input_tokens_override=input_tokens_override,
            )
            mode_api = self._describe_runtime_api(
                provider=str(mode_spec["requested_provider"]),
                model=str(mode_spec["requested_model"]),
            )
            suffix = " (recommande)" if mode_name == recommended_spec["mode"] else ""
            lines.append(
                f"- {mode_spec['label']}{suffix}: {mode_spec['description']}, {mode_api}, ~{float(mode_spec['estimated_cost_eur']):.2f} EUR"
            )
        lines.extend(
            [
                "",
                f"Mode selectionne: {selected_spec['label']}.",
                f"Cout estime: ~{estimated_cost_eur:.2f} EUR.",
                f"Temps estime: {estimated_time_band}.",
                f"API utilisee: {api_label}.",
                (
                    "Reponds go pour lancer le mode recommande, ou simple/avance/extreme pour changer, puis go."
                    if selected_spec["mode"] == recommended_spec["mode"]
                    else "Reponds go pour lancer ce mode, ou simple/avance/extreme pour changer encore."
                ),
            ]
        )
        return OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=envelope_id,
            thread_ref=event.message.thread_ref,
            summary="\n".join(lines),
            mission_run_id=None,
            decision_id=None,
            reply_kind="approval_required",
            communication_mode=CommunicationMode.GUARDIAN,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "surface": event.surface,
                "approval_id": approval_id,
                "proposal_kind": "discussion_mode_selection",
                "selected_mode": selected_spec["mode"],
                "recommended_mode": recommended_spec["mode"],
                "estimated_cost_eur": estimated_cost_eur,
                "estimated_time_band": estimated_time_band,
                "estimated_api_label": api_label,
                "escalation_target_model": target_model,
                "escalation_target_provider": target_provider,
                "reasoning_rationale": list(reasons),
            },
        )

    @staticmethod
    def _assess_reasoning_escalation_need(*, message: str, context_bundle: GatewayContextBundle) -> dict[str, Any]:
        lowered = GatewayService._normalize_keyword_text(message)
        reasons: list[str] = []
        score = 0
        explicit_longform = False
        if len(message) >= _REASONING_ESCALATION_LENGTH_THRESHOLD or len(message.split()) >= _REASONING_ESCALATION_WORD_THRESHOLD:
            score += 1
            reasons.append("discussion plus dense que la moyenne")
        keyword_hits = [token for token in _REASONING_ESCALATION_KEYWORDS if token in lowered]
        if keyword_hits:
            score += 2
            reasons.append(f"sujet strategique ou de conception ({', '.join(keyword_hits[:3])})")
        longform_hits = [token for token in _REASONING_ESCALATION_LONGFORM_HINTS if token in lowered]
        if longform_hits:
            score += 2
            explicit_longform = True
            reasons.append("tu demandes explicitement une reponse longue ou approfondie")
        if context_bundle.mood_hint.mood in {"serious", "brainstorming"}:
            score += 1
            reasons.append(f"ton detecte: {context_bundle.mood_hint.mood}")
        thread_turns = len(context_bundle.recent_thread_messages) + len(context_bundle.recent_operator_replies)
        if thread_turns >= 3:
            score += 1
            reasons.append("discussion deja bien engagee dans le thread")
        if context_bundle.long_context_digest:
            score += 1
            reasons.append("contexte long deja compacte")
        return {"score": score, "reasons": reasons, "explicit_longform": explicit_longform}

    def _build_deep_research_approval_reply(
        self,
        *,
        event: ChannelEvent,
        envelope_id: str,
        approval_id: str,
        scaffold: dict[str, Any],
        estimated_cost_eur: float,
        estimated_time_band: str,
        target_provider: str,
        target_model: str | None,
    ) -> OperatorReply:
        title = str(scaffold.get("title") or "Deep Research").strip()
        doc_name = str(scaffold.get("doc_name") or "").strip()
        relative_path = str(scaffold.get("relative_path") or "").strip()
        profile = str(scaffold.get("research_profile") or scaffold.get("recommended_profile") or "domain_audit").strip()
        intensity = str(scaffold.get("research_intensity") or scaffold.get("recommended_intensity") or "simple").strip()
        api_label = self._describe_runtime_api(provider=target_provider, model=target_model)
        lines = [
            "Je pense que lancer cette recherche approfondie est le bon move.",
            f"Sujet: {title}",
        ]
        if doc_name or relative_path:
            lines.append(f"Dossier prepare: {doc_name or relative_path}")
        lines.append(f"Profil confirme: {self._display_research_profile(profile)}")
        lines.append(f"Intensite confirmee: {self._display_research_intensity(intensity)}")
        lines.extend(
            [
                f"Cout estime: ~{estimated_cost_eur:.2f} EUR.",
                f"Temps estime: {estimated_time_band}.",
                f"API utilisee: {api_label}.",
                (
                    "Mode debug temporaire: Sonnet pilote les passes de recherche extreme, et OpenAI garde seulement la traduction PDF FR."
                    if intensity == "extreme" and str(target_provider).strip().lower() == "anthropic"
                    else ""
                ),
                "Reponds go pour lancer ou stop pour annuler.",
            ]
        )
        lines = [line for line in lines if line]
        return OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=envelope_id,
            thread_ref=event.message.thread_ref,
            summary="\n".join(lines),
            mission_run_id=None,
            decision_id=None,
            reply_kind="approval_required",
            communication_mode=CommunicationMode.GUARDIAN,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "surface": event.surface,
                "approval_id": approval_id,
                "estimated_cost_eur": estimated_cost_eur,
                "estimated_time_band": estimated_time_band,
                "estimated_api_label": api_label,
                "estimated_api_provider": target_provider,
                "estimated_api_model": target_model,
                "research_scaffold_path": scaffold.get("path"),
                "research_scaffold_kind": scaffold.get("kind"),
                "research_scaffold_title": title,
                "research_scaffold_relative_path": relative_path,
                "research_scaffold_doc_name": doc_name,
                "research_profile": profile,
                "research_intensity": intensity,
            },
        )

    @staticmethod
    def _display_research_profile(profile: str) -> str:
        mapping = {
            "project_audit": "Project Audit",
            "component_discovery": "Component Discovery",
            "domain_audit": "Domain Audit",
        }
        return mapping.get(str(profile or "").strip().lower(), str(profile or "Domain Audit").strip() or "Domain Audit")

    @staticmethod
    def _display_research_intensity(intensity: str) -> str:
        mapping = {"simple": "Simple", "complex": "Complexe", "extreme": "Extreme"}
        return mapping.get(str(intensity or "").strip().lower(), str(intensity or "Simple").strip() or "Simple")

    @staticmethod
    def _deep_research_mode_ready(scaffold: dict[str, Any]) -> bool:
        profile = str(scaffold.get("explicit_profile") or "").strip().lower()
        intensity = str(scaffold.get("explicit_intensity") or "").strip().lower()
        return bool(profile and intensity and profile in {"project_audit", "component_discovery", "domain_audit"} and intensity in {"simple", "complex", "extreme"})

    def _build_deep_research_mode_selection_reply(
        self,
        *,
        event: ChannelEvent,
        envelope_id: str,
        approval_id: str,
        scaffold: dict[str, Any],
    ) -> OperatorReply:
        title = str(scaffold.get("title") or "Deep Research").strip()
        doc_name = str(scaffold.get("doc_name") or "").strip()
        relative_path = str(scaffold.get("relative_path") or "").strip()
        selected_profile = str(scaffold.get("explicit_profile") or "").strip().lower()
        selected_intensity = str(scaffold.get("explicit_intensity") or "").strip().lower()
        recommended_profile = str(scaffold.get("recommended_profile") or scaffold.get("research_profile") or "domain_audit").strip()
        recommended_intensity = str(scaffold.get("recommended_intensity") or scaffold.get("research_intensity") or "simple").strip()
        lines = [
            "Deep research detectee. Avant le calcul final du cout, je verrouille le mode.",
            f"Sujet: {title}",
        ]
        if doc_name or relative_path:
            lines.append(f"Dossier prepare: {doc_name or relative_path}")
        lines.append(f"Profil recommande: {self._display_research_profile(recommended_profile)}")
        lines.append(f"Intensite recommandee: {self._display_research_intensity(recommended_intensity)}")
        if selected_profile:
            lines.append(f"Profil deja detecte: {self._display_research_profile(selected_profile)}")
        if selected_intensity:
            lines.append(f"Intensite deja detectee: {self._display_research_intensity(selected_intensity)}")
        missing: list[str] = []
        if not selected_profile:
            missing.append("profil (`project audit`, `component discovery`, `domain audit`)")
        if not selected_intensity:
            missing.append("intensite (`Simple`, `Complexe`, `Extreme`)")
        if missing:
            lines.append(f"Il me manque: {', '.join(missing)}.")
        lines.append("Reponds avec le mode voulu. Exemple: `component discovery + complexe`.")
        lines.append("Une fois profil et intensite confirmes, je t'affiche cout, temps, API et j'attends `go`.")
        return OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=envelope_id,
            thread_ref=event.message.thread_ref,
            summary="\n".join(lines),
            mission_run_id=None,
            decision_id=None,
            reply_kind="clarification_required",
            communication_mode=CommunicationMode.GUARDIAN,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "surface": event.surface,
                "approval_id": approval_id,
                "clarification_gate": True,
                "deep_research_mode_selection": True,
                "research_scaffold_path": scaffold.get("path"),
                "research_scaffold_kind": scaffold.get("kind"),
                "research_scaffold_title": title,
                "research_scaffold_relative_path": relative_path,
                "research_scaffold_doc_name": doc_name,
                "recommended_profile": recommended_profile,
                "recommended_intensity": recommended_intensity,
                "selected_profile": selected_profile or None,
                "selected_intensity": selected_intensity or None,
            },
        )

    def _build_deep_research_mode_selection_dispatch(
        self,
        *,
        event: ChannelEvent,
        envelope: OperatorEnvelope,
        scaffold: dict[str, Any],
        channel_class: DiscordChannelClass,
        candidate_id: str,
        promotion_decision_id: str,
        promoted_memory_ids: list[str],
        human_artifacts: list,
    ) -> GatewayDispatchResult:
        approval_metadata = {
            "approval_type": "deep_research_mode_selection",
            "action_name": "deep_research_mode_selection",
            "research_scaffold": to_jsonable(scaffold),
            "research_scaffold_path": scaffold.get("path"),
            "research_scaffold_kind": scaffold.get("kind"),
            "research_scaffold_title": scaffold.get("title"),
            "research_scaffold_relative_path": scaffold.get("relative_path"),
            "research_scaffold_doc_name": scaffold.get("doc_name"),
            "recommended_profile": scaffold.get("recommended_profile"),
            "recommended_intensity": scaffold.get("recommended_intensity"),
            "selected_profile": scaffold.get("explicit_profile"),
            "selected_intensity": scaffold.get("explicit_intensity"),
            "event_payload": self._serialize_deep_research_event(event),
            "channel_event_id": event.event_id,
            "thread_ref": to_jsonable(event.message.thread_ref),
            "message_text": event.message.text,
            "input_profile": envelope.metadata.get("input_profile"),
        }
        approval = self.router.runtime.create_approval(
            requested_by="gateway_discord",
            risk_tier="high",
            reason="confirmation_deep_research_mode",
            metadata=approval_metadata,
        )
        reply = self._build_deep_research_mode_selection_reply(
            event=event,
            envelope_id=envelope.envelope_id,
            approval_id=approval.approval_id,
            scaffold=scaffold,
        )
        return GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=event.event_id,
            envelope_id=envelope.envelope_id,
            intent_id=new_id("deep_research_mode_intent"),
            decision_id=None,
            mission_run_id=None,
            operator_reply=reply,
            promoted_memory_ids=promoted_memory_ids,
            memory_candidate_id=candidate_id,
            promotion_decision_id=promotion_decision_id,
            discord_run_card=None,
            metadata={
                "classification": envelope.metadata.get("message_kind"),
                "reply_kind": reply.reply_kind,
                "channel_class": channel_class.value,
                "communication_mode": reply.communication_mode.value,
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                "source_artifact_ids": list(envelope.metadata.get("source_artifact_ids") or []),
                "input_profile": envelope.metadata.get("input_profile"),
                "intent_kind": envelope.metadata.get("intent_kind"),
                "delegation_level": envelope.metadata.get("delegation_level"),
                "interaction_state": envelope.metadata.get("interaction_state"),
                "suggested_next_state": InteractionState.APPROVAL.value,
                "intent_confidence": envelope.metadata.get("intent_confidence"),
                "intent_signals": list(envelope.metadata.get("intent_signals") or []),
                "state_transition": "directive->approval",
                "directive_detection": envelope.metadata.get("directive_detection"),
                "action_contract": envelope.metadata.get("action_contract"),
                "approval_id": approval.approval_id,
                "approval_reason": approval.reason,
                "approval_metadata": to_jsonable(approval.metadata),
                "research_scaffold_path": scaffold.get("path"),
                "research_scaffold_kind": scaffold.get("kind"),
                "research_scaffold_title": scaffold.get("title"),
                "research_scaffold_relative_path": scaffold.get("relative_path"),
                "research_scaffold_doc_name": scaffold.get("doc_name"),
                "research_profile": scaffold.get("explicit_profile") or scaffold.get("recommended_profile"),
                "research_intensity": scaffold.get("explicit_intensity") or scaffold.get("recommended_intensity"),
            },
        )

    def _build_deep_research_approval_dispatch(
        self,
        *,
        event: ChannelEvent,
        envelope: OperatorEnvelope,
        scaffold: dict[str, Any],
        channel_class: DiscordChannelClass,
        candidate_id: str,
        promotion_decision_id: str,
        promoted_memory_ids: list[str],
        human_artifacts: list,
    ) -> GatewayDispatchResult:
        budget = self._estimated_deep_research_budget(scaffold)
        estimated_cost = float(budget.get("estimated_cost_eur") or 0.0)
        estimated_time_band = str(budget.get("estimated_time_band") or "moyen")
        estimated_api_provider = str(budget.get("estimated_api_provider") or "openai")
        estimated_api_model = str(budget.get("estimated_api_model") or "") or None
        approval_metadata = {
            "approval_type": "deep_research_launch",
            "action_name": "deep_research_launch",
            "estimated_cost_eur": estimated_cost,
            "estimated_time_band": estimated_time_band,
            "estimated_api_provider": estimated_api_provider,
            "estimated_api_model": estimated_api_model,
            "research_scaffold": to_jsonable(scaffold),
            "research_scaffold_path": scaffold.get("path"),
            "research_scaffold_kind": scaffold.get("kind"),
            "research_scaffold_title": scaffold.get("title"),
            "research_scaffold_relative_path": scaffold.get("relative_path"),
            "research_scaffold_doc_name": scaffold.get("doc_name"),
            "research_profile": scaffold.get("research_profile"),
            "research_intensity": scaffold.get("research_intensity"),
            "recommended_profile": scaffold.get("recommended_profile"),
            "recommended_intensity": scaffold.get("recommended_intensity"),
            "event_payload": self._serialize_deep_research_event(event),
            "channel_event_id": event.event_id,
            "thread_ref": to_jsonable(event.message.thread_ref),
            "message_text": event.message.text,
            "input_profile": envelope.metadata.get("input_profile"),
        }
        approval = self.router.runtime.create_approval(
            requested_by="gateway_discord",
            risk_tier="high",
            reason="confirmation_deep_research",
            metadata=approval_metadata,
        )
        reply = self._build_deep_research_approval_reply(
            event=event,
            envelope_id=envelope.envelope_id,
            approval_id=approval.approval_id,
            scaffold=scaffold,
            estimated_cost_eur=estimated_cost,
            estimated_time_band=estimated_time_band,
            target_provider=estimated_api_provider,
            target_model=estimated_api_model,
        )
        return GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=event.event_id,
            envelope_id=envelope.envelope_id,
            intent_id=new_id("deep_research_approval_intent"),
            decision_id=None,
            mission_run_id=None,
            operator_reply=reply,
            promoted_memory_ids=promoted_memory_ids,
            memory_candidate_id=candidate_id,
            promotion_decision_id=promotion_decision_id,
            discord_run_card=None,
            metadata={
                "classification": envelope.metadata.get("message_kind"),
                "reply_kind": reply.reply_kind,
                "channel_class": channel_class.value,
                "communication_mode": reply.communication_mode.value,
                "human_artifact_ids": [item.artifact_id for item in human_artifacts],
                "source_artifact_ids": list(envelope.metadata.get("source_artifact_ids") or []),
                "input_profile": envelope.metadata.get("input_profile"),
                "intent_kind": envelope.metadata.get("intent_kind"),
                "delegation_level": envelope.metadata.get("delegation_level"),
                "interaction_state": envelope.metadata.get("interaction_state"),
                "suggested_next_state": InteractionState.APPROVAL.value,
                "intent_confidence": envelope.metadata.get("intent_confidence"),
                "intent_signals": list(envelope.metadata.get("intent_signals") or []),
                "state_transition": "directive->approval",
                "directive_detection": envelope.metadata.get("directive_detection"),
                "action_contract": envelope.metadata.get("action_contract"),
                "approval_id": approval.approval_id,
                "approval_reason": approval.reason,
                "approval_metadata": to_jsonable(approval.metadata),
                "research_scaffold_path": scaffold.get("path"),
                "research_scaffold_kind": scaffold.get("kind"),
                "research_scaffold_title": scaffold.get("title"),
                "research_scaffold_relative_path": scaffold.get("relative_path"),
                "research_scaffold_doc_name": scaffold.get("doc_name"),
                "research_profile": scaffold.get("research_profile"),
                "research_intensity": scaffold.get("research_intensity"),
            },
        )

    @staticmethod
    def _estimated_time_band(cost_class: CostClass) -> str:
        if cost_class is CostClass.EXCEPTIONAL:
            return "long"
        if cost_class is CostClass.HARD:
            return "moyen"
        return "court"

    @staticmethod
    def _describe_runtime_api(*, provider: str | None, model: str | None) -> str:
        normalized_provider = str(provider or "").strip().lower()
        provider_label = {
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "local": "Local",
            "project_os": "Project OS",
        }.get(normalized_provider, str(provider or "inconnue").strip() or "inconnue")
        model_label = str(model or "").strip()
        if model_label:
            return f"{provider_label} / {model_label}"
        return provider_label

    @staticmethod
    def _session_reply_summary(resolved: ResolvedIntent, action_result: dict) -> str:
        custom_summary = str(action_result.get("summary") or "").strip()
        if resolved.action == "approve_contract":
            branch = str(action_result.get("branch_name") or "ce lot")
            if action_result.get("run_launched"):
                return f"{branch}: contrat approuve. Run lance."
            return f"{branch}: contrat approuve. Lancement en attente."
        if resolved.action == "reject_contract":
            branch = str(action_result.get("branch_name") or "ce lot")
            return f"{branch}: contrat refuse. Rien n'est lance."
        if resolved.action == "approve_runtime_approval":
            if action_result.get("approval_type") == "reasoning_escalation" and custom_summary:
                return custom_summary
            if action_result.get("approval_type") == "deep_research_launch":
                estimated_cost = float(action_result.get("estimated_cost_eur") or 0.0)
                doc_name = str(action_result.get("doc_name") or action_result.get("dossier_relative_path") or "").strip()
                api_label = str(action_result.get("api_label") or "").strip()
                if action_result.get("run_launched"):
                    summary = f"Recherche approfondie lancee (~{estimated_cost:.2f} EUR)."
                    if api_label:
                        summary = f"{summary} API: {api_label}."
                    if doc_name:
                        summary = f"{summary} Dossier: {doc_name}."
                    return f"{summary} Le rapport final reviendra sur Discord avec le PDF et le fichier Markdown."
                error = str(action_result.get("error") or "lancement reste bloque").strip()
                return f"Recherche approfondie approuvee, mais le lancement reste bloque: {error}"
            objective = str(action_result.get("objective") or "cette operation")
            estimated_cost = float(action_result.get("estimated_cost_eur") or 0.0)
            api_label = str(action_result.get("api_label") or "").strip()
            if action_result.get("run_launched"):
                summary = f"{objective}: validation enregistree. Operation lancee (~{estimated_cost:.2f} EUR)."
                if api_label:
                    summary = f"{summary} API: {api_label}."
                return summary
            error = str(action_result.get("error") or "").strip()
            if error:
                return f"{objective}: validation enregistree, mais le lancement reste bloque: {error}"
            return f"{objective}: validation enregistree, mais le lancement reste bloque."
        if resolved.action == "reject_runtime_approval":
            if action_result.get("approval_type") == "reasoning_escalation" and custom_summary:
                return custom_summary
            if action_result.get("approval_type") == "deep_research_mode_selection":
                return "Choix du mode deep research annule. Rien n'est lance."
            if action_result.get("approval_type") == "deep_research_launch":
                return "Recherche approfondie annulee. Rien n'est lance."
            objective = str(action_result.get("objective") or "cette operation")
            return f"{objective}: validation refusee. Rien n'est lance."
        if resolved.action == "update_runtime_approval_selection" and custom_summary:
            return custom_summary
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

    def _build_action_contract(
        self,
        *,
        event: ChannelEvent,
        candidate,
        requested_risk_class: ActionRiskClass | None,
    ) -> ActionContract:
        intent_kind = self._parse_intent_kind(candidate.metadata.get("intent_kind"))
        delegation_level = self._parse_delegation_level(candidate.metadata.get("delegation_level"))
        confidence = float(candidate.metadata.get("intent_confidence") or 0.0)
        directive_detection = dict(candidate.metadata.get("directive_detection") or {})
        output_hits = [str(item) for item in directive_detection.get("output_hits") or []]
        target_hits = [str(item) for item in directive_detection.get("target_hits") or []]
        execute_hits = [str(item) for item in directive_detection.get("execute_hits") or []]
        prepare_hits = [str(item) for item in directive_detection.get("prepare_hits") or []]
        signals = [str(item) for item in candidate.metadata.get("intent_signals") or []]

        objective = str(candidate.summary or candidate.content or event.message.text).strip()
        scope = self._infer_action_scope(target_hits, event=event)
        expected_output = self._infer_expected_output(
            output_hits,
            delegation_level=delegation_level,
            execute_hits=execute_hits,
        )
        risk_class = requested_risk_class or self._infer_action_contract_risk(candidate.content)
        if (
            risk_class is ActionRiskClass.READ_ONLY
            and intent_kind in {IntentKind.DIRECTIVE_IMPLICIT, IntentKind.DIRECTIVE_EXPLICIT}
            and expected_output is not None
        ):
            risk_class = ActionRiskClass.SAFE_WRITE
        needs_approval = risk_class in {ActionRiskClass.DESTRUCTIVE, ActionRiskClass.EXCEPTIONAL}
        approval_reason = "destructive_change_requires_founder_approval" if risk_class is ActionRiskClass.DESTRUCTIVE else (
            "exceptional_change_requires_founder_approval" if risk_class is ActionRiskClass.EXCEPTIONAL else None
        )

        needs_clarification = False
        clarification_question: str | None = None
        if intent_kind in {IntentKind.DIRECTIVE_IMPLICIT, IntentKind.DIRECTIVE_EXPLICIT} and not needs_approval:
            if not output_hits and not target_hits:
                needs_clarification = True
                clarification_question = "Tu veux quoi comme livrable concret: fichier, note, plan ou patch ?"
            elif expected_output is None:
                needs_clarification = True
                clarification_question = "Tu veux quoi comme livrable concret: fichier, note, plan ou patch ?"
            elif delegation_level is DelegationLevel.EXECUTE and scope is None:
                needs_clarification = True
                clarification_question = "Tu veux que je le fasse ou exactement: repo, docs ou runtime ?"
            elif confidence < 0.72 and not execute_hits and not prepare_hits:
                needs_clarification = True
                clarification_question = "Tu veux que je prepare quelque chose ou que j execute directement ?"

        execution_ready = (
            intent_kind in {IntentKind.DIRECTIVE_IMPLICIT, IntentKind.DIRECTIVE_EXPLICIT}
            and not needs_clarification
            and not needs_approval
        )

        return ActionContract(
            contract_id=new_id("action_contract"),
            intent_kind=intent_kind,
            delegation_level=delegation_level,
            objective=objective,
            scope=scope,
            expected_output=expected_output,
            confidence=confidence,
            risk_class=risk_class,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            needs_approval=needs_approval,
            approval_reason=approval_reason,
            execution_ready=execution_ready,
            signals=signals,
            metadata={
                "directive_detection": directive_detection,
                "input_profile": candidate.metadata.get("input_profile"),
                "target_hits": target_hits,
                "output_hits": output_hits,
                "execute_hits": execute_hits,
                "prepare_hits": prepare_hits,
            },
        )

    @staticmethod
    def _infer_action_scope(target_hits: list[str], *, event: ChannelEvent) -> str | None:
        normalized_targets = {item.strip().lower() for item in target_hits if item}
        if normalized_targets & {"repo", "branche", "docs", "readme"}:
            return "repo"
        if normalized_targets & {"worker", "windows", "browser", "uefn"}:
            return "worker"
        if "runtime" in normalized_targets:
            return "runtime"
        if normalized_targets & {"thread", "canal", "channel", "run"}:
            return "discord" if event.message.channel == "discord" else "runtime"
        if "discord" in normalized_targets:
            return "discord"
        return None

    @staticmethod
    def _infer_expected_output(
        output_hits: list[str],
        *,
        delegation_level: DelegationLevel,
        execute_hits: list[str],
    ) -> str | None:
        normalized_hits = {item.strip().lower() for item in output_hits if item}
        if normalized_hits & {"md", "markdown", "doc", "document", "note", "trace"}:
            return "markdown_document"
        if normalized_hits & {"plan", "roadmap", "spec", "brief", "rapport", "resume", "synthese", "tableau", "liste"}:
            return "structured_document"
        if normalized_hits & {"fichier", "file"}:
            return "repo_file"
        if execute_hits and delegation_level is DelegationLevel.EXECUTE:
            return "repo_change"
        if delegation_level is DelegationLevel.PREPARE:
            return "prepared_output"
        return None

    @staticmethod
    def _infer_action_contract_risk(objective: str) -> ActionRiskClass:
        lowered = objective.lower()
        if any(keyword in lowered for keyword in ("delete", "destroy", "remove", "format", "supprime", "efface")):
            return ActionRiskClass.DESTRUCTIVE
        if any(
            keyword in lowered
            for keyword in ("publish", "ship", "apply", "write", "edit", "ecris", "cree", "create", "ajoute", "mets", "pose")
        ):
            return ActionRiskClass.SAFE_WRITE
        return ActionRiskClass.READ_ONLY

    @staticmethod
    def _parse_intent_kind(raw: object) -> IntentKind:
        try:
            return IntentKind(str(raw or "").strip().lower())
        except Exception:
            return IntentKind.DISCUSSION

    @staticmethod
    def _parse_delegation_level(raw: object) -> DelegationLevel:
        try:
            return DelegationLevel(str(raw or "").strip().lower())
        except Exception:
            return DelegationLevel.NONE

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

    def _call_simple_chat(
        self,
        message: str,
        model: str = "claude-sonnet-4-20250514",
        *,
        route_reason: str | None = None,
        context_bundle: GatewayContextBundle | None = None,
    ) -> str | None:
        """Call Claude API directly for simple Discord chat messages. Returns the response text or None on failure."""
        if not self.secret_resolver:
            return None
        try:
            import anthropic
            api_key = self.secret_resolver.get_required("ANTHROPIC_API_KEY")
            client = anthropic.Anthropic(api_key=api_key)
            system_blocks = self._simple_chat_system_blocks()
            user_message = self._simple_chat_user_message(
                message,
                provider="anthropic",
                model=model,
                route_reason=route_reason,
                context_bundle=context_bundle,
            )
            response = client.messages.create(
                model=model,
                max_tokens=1200,
                system=system_blocks,
                messages=[
                    {
                        "role": "user",
                        "content": user_message,
                    },
                ],
            )
            rendered = self._anthropic_text_blocks(response)
            if getattr(response, "stop_reason", None) == "max_tokens" and rendered:
                continuation = client.messages.create(
                    model=model,
                    max_tokens=600,
                    system=system_blocks,
                    messages=[
                        {"role": "user", "content": user_message},
                        {"role": "assistant", "content": rendered},
                        {
                            "role": "user",
                            "content": "Continue exactement la meme reponse sans repetition. Reprends a partir du dernier mot et termine proprement.",
                        },
                    ],
                )
                continuation_text = self._anthropic_text_blocks(continuation)
                if continuation_text:
                    rendered = f"{rendered.rstrip()}\n{continuation_text.lstrip()}"
            return rendered or None
        except Exception as exc:
            logging.getLogger("project_os.gateway").warning("simple_chat Claude call failed: %s", exc)
            return None

    @staticmethod
    def _anthropic_text_blocks(response: Any) -> str:
        parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text)
        return "".join(parts).strip()

    def _call_openai_chat(
        self,
        message: str,
        *,
        model: str | None,
        reasoning_effort: str | None,
        route_reason: str | None = None,
        context_bundle: GatewayContextBundle | None = None,
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
                input=[
                    {"role": "developer", "content": self._simple_chat_system_prompt()},
                    {
                        "role": "user",
                        "content": self._simple_chat_user_message(
                            message,
                            provider="openai",
                            model=model or "gpt-5.4",
                            route_reason=route_reason,
                            context_bundle=context_bundle,
                        ),
                    },
                ],
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

    def _simple_chat_system_blocks(self) -> list[dict[str, object]]:
        return self.persona.render_anthropic_system()

    def _simple_chat_system_prompt(self) -> str:
        return self.persona.render_openai_developer()

    def _simple_chat_user_message(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        route_reason: str | None = None,
        context_bundle: GatewayContextBundle | None = None,
    ) -> str:
        lines = [
            "Contexte runtime:",
            "- surface: Discord",
            "- role: Project OS operator voice",
            "- function: human translator between founder intent and Project OS",
            "- host: Windows-first",
            "- managed_workspace: D:/ProjectOS/project-os-core",
            f"- current_provider: {provider or 'unknown'}",
            f"- current_model: {model or 'unknown'}",
            f"- current_route_reason: {route_reason or 'unknown'}",
            "- principle: do not invent completed file inspection or executed actions",
            "- truth_contract: when suggesting next steps, phrase them as proposals or requests; never imply that an inspection, write, send, or background action is already happening unless it already happened in this turn",
            "- artifact_truth_contract: if recent thread history shows that Project OS already sent a PDF or another artifact in this thread, treat that artifact as real and already delivered; do not deny it",
        ]
        if context_bundle is not None:
            lines.extend(
                [
                    f"- detected_mood: {context_bundle.mood_hint.mood}",
                    f"- mood_guidance: {context_bundle.mood_hint.guidance}",
                    f"- sensitivity_class: {context_bundle.sensitivity.value}",
                    f"- query_scope: {context_bundle.query_scope}",
                ]
            )
            if context_bundle.thread_binding_id:
                lines.append(f"- thread_binding_id: {context_bundle.thread_binding_id}")
            if context_bundle.thread_binding_kind:
                lines.append(f"- thread_binding_kind: {context_bundle.thread_binding_kind}")
            if context_bundle.query_scope in {"identity", "runtime_truth"}:
                lines.append(
                    "- context_rule: answer the current identity/runtime question only; do not surface backlog, pending clarifications, or other missions unless the founder asks for them explicitly"
                )

        sections = ["\n".join(lines)]
        if context_bundle is not None:
            if context_bundle.session_brief.strip():
                sections.append(f"Contexte session recent:\n{context_bundle.session_brief}")
            thread_history = self._render_recent_thread_history(context_bundle)
            if thread_history:
                sections.append(f"Historique recent du thread:\n{thread_history}")
            if context_bundle.long_context_brief.strip():
                sections.append(f"Workflow long-context:\n{context_bundle.long_context_brief}")
            prompt_handoff = replace(context_bundle.handoff_contract, raw_user_intent=message)
            sections.append(
                "Handoff contract:\n"
                + json.dumps(to_jsonable(prompt_handoff), ensure_ascii=True, sort_keys=True, indent=2)
            )
        sections.append(f"Message fondateur pour ce tour:\n{message}")
        return "\n\n".join(sections)

    def _call_local_chat(
        self,
        *,
        message: str,
        model: str | None,
        sensitivity: SensitivityClass,
        context_bundle: GatewayContextBundle | None = None,
    ) -> str | None:
        if self.local_model_client is None:
            return None
        try:
            response = self.local_model_client.chat(
                message=self._simple_chat_user_message(
                    message,
                    provider="local",
                    model=model,
                    route_reason="s3_local_route" if sensitivity is SensitivityClass.S3 else "local_inline_route",
                    context_bundle=context_bundle,
                ),
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
        route_reason: str | None = None,
        context_bundle: GatewayContextBundle | None = None,
    ) -> str | None:
        if provider == "local":
            return self._call_local_chat(
                message=message,
                model=model,
                sensitivity=sensitivity,
                context_bundle=context_bundle,
            )
        if provider == "openai":
            return self._call_openai_chat(
                message,
                model=model,
                reasoning_effort=reasoning_effort,
                route_reason=route_reason,
                context_bundle=context_bundle,
            )
        return self._call_simple_chat(
            message=message,
            model=model or "claude-sonnet-4-20250514",
            route_reason=route_reason,
            context_bundle=context_bundle,
        )

    @staticmethod
    def _render_recent_thread_history(context_bundle: GatewayContextBundle) -> str:
        lines: list[str] = []
        for turn in context_bundle.recent_thread_messages:
            lines.append(f"- {turn.role}: {turn.text}")
        for turn in context_bundle.recent_operator_replies:
            lines.append(f"- {turn.role}: {turn.text}")
        return "\n".join(lines)

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
    def _apply_discussion_mode_instruction(message: str, discussion_mode: str | None) -> str:
        normalized_mode = GatewayService._resolve_discussion_mode(discussion_mode, fallback="")
        if normalized_mode == "simple":
            prefix = (
                "Mode simple Discord: reponds vite, net, humain, et reste bref. "
                "Vise une reponse compacte, sans livrable joint sauf si c'est indispensable.\n\n"
            )
            return f"{prefix}{message}".strip()
        if normalized_mode == "avance":
            prefix = (
                "Mode avance Discord: reponds de facon detaillee, structuree et naturelle. "
                "Tu peux prendre de la place si cela aide vraiment la decision.\n\n"
            )
            return f"{prefix}{message}".strip()
        if normalized_mode == "extreme":
            prefix = (
                "Mode extreme Discord: reponds de facon approfondie, structuree et exploitable. "
                "Si la reponse devient trop longue pour le chat, la plateforme la basculera vers un PDF.\n\n"
            )
            return f"{prefix}{message}".strip()
        return message

    @staticmethod
    def _message_for_route(candidate, decision: RoutingDecision, discussion_mode: str | None = None) -> str:
        compact_message = str(candidate.metadata.get("long_context_compact_message") or "").strip()
        if compact_message:
            return GatewayService._apply_discussion_mode_instruction(compact_message, discussion_mode)
        if decision.model_route.provider == "local":
            return GatewayService._apply_discussion_mode_instruction(candidate.content, discussion_mode)
        return GatewayService._apply_discussion_mode_instruction(
            GatewayService._message_for_cloud(candidate),
            discussion_mode,
        )

    def _local_system_prompt(self, sensitivity: SensitivityClass) -> str:
        return self.persona.render_local_system(sensitivity)

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
        *,
        envelope: OperatorEnvelope | None = None,
    ) -> OperatorReply:
        research_note = self._research_reply_suffix(envelope)
        if decision.allowed:
            worker = self._worker_label(decision.chosen_worker)
            summary = f"Mission lancee sur {worker}. Mode: {decision.execution_class.value}."
            if research_note:
                summary = f"{summary} {research_note}"
            reply_kind = "ack"
        else:
            reason = self._translate_block_reason(decision.blocked_reasons or [decision.route_reason])
            summary = f"Mission bloquee: {reason}"
            if research_note:
                summary = f"{summary} {research_note}"
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
            metadata={
                "surface": event.surface,
                "speech_policy": decision.speech_policy.value,
                "research_scaffold_path": envelope.metadata.get("research_scaffold_path") if envelope else None,
                "research_scaffold_kind": envelope.metadata.get("research_scaffold_kind") if envelope else None,
                "research_scaffold_title": envelope.metadata.get("research_scaffold_title") if envelope else None,
                "research_scaffold_relative_path": envelope.metadata.get("research_scaffold_relative_path") if envelope else None,
                "research_scaffold_doc_name": envelope.metadata.get("research_scaffold_doc_name") if envelope else None,
            },
        )

    def _maybe_prepare_deep_research_scaffold(self, event: ChannelEvent) -> dict[str, Any] | None:
        if self.paths is None:
            return None
        detected = detect_deep_research_request(event.message.text)
        if detected is None:
            return None
        try:
            payload = scaffold_research(
                self.paths.repo_root,
                ResearchScaffoldRequest(
                    title=detected.title,
                    kind=detected.kind,
                    research_profile=detected.research_profile,
                    research_intensity=detected.research_intensity,
                    question=detected.question,
                    keywords=detected.keywords,
                ),
            )
        except Exception as exc:
            self.journal.append(
                "gateway_research_scaffold_failed",
                "gateway",
                {
                    "channel_event_id": event.event_id,
                    "message_id": event.message.message_id,
                    "error": str(exc),
                },
            )
            return {
                "error": str(exc),
                "kind": detected.kind,
                "title": detected.title,
                "keywords": detected.keywords,
            }
        relative_path = Path(payload["path"]).resolve(strict=False).relative_to(self.paths.repo_root).as_posix()
        result = {
            **payload,
            "relative_path": relative_path,
            "doc_name": Path(payload["path"]).name,
            "recommended_profile": detected.recommended_profile,
            "recommended_intensity": detected.recommended_intensity,
            "explicit_profile": detected.explicit_profile,
            "explicit_intensity": detected.explicit_intensity,
        }
        self.journal.append(
            "gateway_research_scaffold_prepared",
            "gateway",
            {
                "channel_event_id": event.event_id,
                "message_id": event.message.message_id,
                "path": payload["path"],
                "kind": payload["kind"],
                "title": payload["title"],
                "created": bool(payload.get("created")),
            },
        )
        return result

    def _maybe_launch_deep_research_job(
        self,
        event: ChannelEvent,
        scaffold: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if scaffold is None or self.deep_research is None:
            return None
        try:
            return self.deep_research.launch_job_from_gateway(event=event, scaffold=scaffold)
        except Exception as exc:
            self.journal.append(
                "gateway_deep_research_launch_failed",
                "gateway",
                {
                    "channel_event_id": event.event_id,
                    "message_id": event.message.message_id,
                    "error": str(exc),
                },
            )
            return {
                "error": str(exc),
                "launched": False,
                "job_id": None,
            }

    def _build_deep_research_dispatch(
        self,
        *,
        event: ChannelEvent,
        envelope: OperatorEnvelope,
        promoted_memory_ids: list[str],
        candidate_id: str,
        promotion_decision_id: str,
        channel_class: DiscordChannelClass,
        job_payload: dict[str, Any],
    ) -> GatewayDispatchResult:
        launched = bool(job_payload.get("launched"))
        relative_path = str(envelope.metadata.get("research_scaffold_relative_path") or "").strip()
        doc_name = str(envelope.metadata.get("research_scaffold_doc_name") or "").strip()
        if launched:
            summary = "Recherche approfondie lancee."
            if doc_name or relative_path:
                summary = f"{summary} Dossier: {doc_name or relative_path}."
            summary = f"{summary} Le rapport final reviendra sur Discord avec le PDF et le fichier Markdown."
            reply_kind = "ack"
        else:
            error = str(job_payload.get("error") or "Lancement automatique impossible.").strip()
            summary = f"Recherche approfondie bloquee: {error}"
            reply_kind = "blocked"
        reply = OperatorReply(
            reply_id=new_id("reply"),
            channel=event.message.channel,
            envelope_id=envelope.envelope_id,
            thread_ref=event.message.thread_ref,
            summary=summary,
            mission_run_id=None,
            decision_id=None,
            reply_kind=reply_kind,
            communication_mode=CommunicationMode.DISCUSSION,
            operator_language="fr",
            audience=OperatorAudience.NON_DEVELOPER,
            metadata={
                "surface": event.surface,
                "channel_class": channel_class.value,
                "research_scaffold_path": envelope.metadata.get("research_scaffold_path"),
                "research_scaffold_kind": envelope.metadata.get("research_scaffold_kind"),
                "research_scaffold_title": envelope.metadata.get("research_scaffold_title"),
                "research_scaffold_relative_path": relative_path,
                "research_scaffold_doc_name": doc_name,
                "deep_research_job_id": job_payload.get("job_id"),
                "deep_research_job_path": job_payload.get("job_path"),
                "deep_research_job_launched": launched,
            },
        )
        return GatewayDispatchResult(
            dispatch_id=new_id("dispatch"),
            channel_event_id=event.event_id,
            envelope_id=envelope.envelope_id,
            intent_id=new_id("intent"),
            decision_id=None,
            mission_run_id=None,
            operator_reply=reply,
            promoted_memory_ids=promoted_memory_ids,
            memory_candidate_id=candidate_id,
            promotion_decision_id=promotion_decision_id,
            discord_run_card=None,
            metadata={
                "channel_class": channel_class.value,
                "reply_kind": reply.reply_kind,
                "research_scaffold_path": envelope.metadata.get("research_scaffold_path"),
                "research_scaffold_kind": envelope.metadata.get("research_scaffold_kind"),
                "research_scaffold_title": envelope.metadata.get("research_scaffold_title"),
                "research_scaffold_relative_path": relative_path,
                "research_scaffold_doc_name": doc_name,
                "deep_research_job_id": job_payload.get("job_id"),
                "deep_research_job_path": job_payload.get("job_path"),
                "deep_research_job_launched": launched,
            },
        )

    def _estimated_deep_research_budget(self, scaffold: dict[str, Any]) -> dict[str, Any]:
        if self.deep_research is not None:
            return self.deep_research.estimate_run(request=scaffold)
        kind = str(scaffold.get("kind") or "audit").strip().lower()
        intensity = str(scaffold.get("research_intensity") or scaffold.get("recommended_intensity") or "simple").strip().lower()
        keyword_count = len([item for item in scaffold.get("keywords", []) if str(item).strip()])
        recent_days = int(scaffold.get("recent_days") or 30)
        base = 1.10 if kind == "system" else 0.85
        base += min(keyword_count, 6) * 0.03
        if recent_days > 45:
            base += 0.10
        intensity_multiplier = {"simple": 1.0, "complex": 1.65, "extreme": 2.45}.get(intensity, 1.0)
        return {
            "estimated_cost_eur": round(base * intensity_multiplier, 2),
            "estimated_time_band": "long" if intensity == "extreme" else "moyen",
        }

    def _estimated_deep_research_cost_eur(self, scaffold: dict[str, Any]) -> float:
        return float(self._estimated_deep_research_budget(scaffold).get("estimated_cost_eur") or 0.0)

    def _estimated_deep_research_time_band(self, scaffold: dict[str, Any]) -> str:
        return str(self._estimated_deep_research_budget(scaffold).get("estimated_time_band") or "moyen")

    @staticmethod
    def _serialize_deep_research_event(event: ChannelEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "surface": event.surface,
            "event_type": event.event_type,
            "created_at": event.created_at,
            "message": {
                "message_id": event.message.message_id,
                "actor_id": event.message.actor_id,
                "channel": event.message.channel,
                "text": event.message.text,
                "thread_ref": to_jsonable(event.message.thread_ref),
                "attachments": [to_jsonable(item) for item in event.message.attachments],
                "metadata": dict(event.message.metadata),
                "created_at": event.message.created_at,
            },
        }

    @staticmethod
    def _rebuild_deep_research_event(payload: object) -> ChannelEvent:
        raw = payload if isinstance(payload, dict) else {}
        message_raw = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        thread_raw = message_raw.get("thread_ref") if isinstance(message_raw.get("thread_ref"), dict) else {}
        attachments_raw = message_raw.get("attachments") if isinstance(message_raw.get("attachments"), list) else []
        thread_ref = ConversationThreadRef(
            thread_id=str(thread_raw.get("thread_id") or "discord"),
            channel=str(thread_raw.get("channel") or message_raw.get("channel") or raw.get("surface") or "discord"),
            external_thread_id=str(thread_raw.get("external_thread_id")) if thread_raw.get("external_thread_id") else None,
            parent_thread_id=str(thread_raw.get("parent_thread_id")) if thread_raw.get("parent_thread_id") else None,
            title=str(thread_raw.get("title")) if thread_raw.get("title") else None,
            metadata=dict(thread_raw.get("metadata")) if isinstance(thread_raw.get("metadata"), dict) else {},
        )
        attachments = [
            OperatorAttachment(
                attachment_id=str(item.get("attachment_id") or new_id("attachment")),
                name=str(item.get("name") or "attachment"),
                kind=str(item.get("kind") or "file"),
                mime_type=str(item.get("mime_type")) if item.get("mime_type") else None,
                path=str(item.get("path")) if item.get("path") else None,
                url=str(item.get("url")) if item.get("url") else None,
                size_bytes=int(item["size_bytes"]) if item.get("size_bytes") is not None else None,
                metadata=dict(item.get("metadata")) if isinstance(item.get("metadata"), dict) else {},
            )
            for item in attachments_raw
            if isinstance(item, dict)
        ]
        message = OperatorMessage(
            message_id=str(message_raw.get("message_id") or new_id("message")),
            actor_id=str(message_raw.get("actor_id") or "founder"),
            channel=str(message_raw.get("channel") or raw.get("surface") or "discord"),
            text=str(message_raw.get("text") or ""),
            thread_ref=thread_ref,
            attachments=attachments,
            metadata=dict(message_raw.get("metadata")) if isinstance(message_raw.get("metadata"), dict) else {},
            created_at=str(message_raw.get("created_at") or datetime.now(timezone.utc).isoformat()),
        )
        return ChannelEvent(
            event_id=str(raw.get("event_id") or new_id("channel_event")),
            surface=str(raw.get("surface") or "discord"),
            event_type=str(raw.get("event_type") or "message.created"),
            message=message,
            created_at=str(raw.get("created_at") or datetime.now(timezone.utc).isoformat()),
        )

    @staticmethod
    def _research_reply_suffix(envelope: OperatorEnvelope | None) -> str | None:
        if envelope is None:
            return None
        relative_path = str(envelope.metadata.get("research_scaffold_relative_path") or "").strip()
        doc_name = str(envelope.metadata.get("research_scaffold_doc_name") or "").strip()
        kind = str(envelope.metadata.get("research_scaffold_kind") or "").strip()
        if not relative_path and not doc_name:
            return None
        label = "Dossier systeme prepare" if kind == "system" else "Audit prepare"
        detail = doc_name or relative_path
        if relative_path and doc_name and relative_path != doc_name:
            detail = f"{doc_name} ({relative_path})"
        return f"{label}: {detail}."

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

    def _communication_mode_for(
        self,
        message_kind,
        channel_class: DiscordChannelClass,
        *,
        intent_kind: str = "",
        delegation_level: str = "",
    ) -> CommunicationMode:
        if channel_class is DiscordChannelClass.INCIDENTS:
            return CommunicationMode.INCIDENT
        if channel_class is DiscordChannelClass.APPROVALS:
            return CommunicationMode.GUARDIAN
        if delegation_level in {DelegationLevel.PREPARE.value, DelegationLevel.EXECUTE.value}:
            return CommunicationMode.BUILDER
        if intent_kind in {"directive_implicit", "directive_explicit"}:
            return CommunicationMode.BUILDER
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
            "risk_requires_approval": "une validation fondateur est obligatoire",
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

    def _persist_candidate_metadata(self, candidate) -> None:
        self.database.execute(
            """
            UPDATE conversation_memory_candidates
            SET payload_json = ?
            WHERE candidate_id = ?
            """,
            (
                dump_json(candidate.metadata),
                candidate.candidate_id,
            ),
        )

    def _persist_ingress_artifacts(self, event: ChannelEvent, candidate) -> list[ArtifactPointer]:
        if not self.paths or not self.path_policy:
            return []
        if not candidate.metadata.get("requires_ingress_artifact"):
            return []
        artifacts: list[ArtifactPointer] = []
        artifacts.append(
            self._write_gateway_artifact(
                owner_type="channel_event",
                owner_id=event.event_id,
                artifact_kind="ingress_input",
                payload={
                    "version": "v1",
                    "channel_event_id": event.event_id,
                    "message_id": event.message.message_id,
                    "surface": event.surface,
                    "event_type": event.event_type,
                    "actor_id": event.message.actor_id,
                    "channel": event.message.channel,
                    "thread_ref": to_jsonable(event.message.thread_ref),
                    "input_profile": candidate.metadata.get("input_profile"),
                    "text": event.message.text,
                    "text_char_count": candidate.metadata.get("input_char_count"),
                    "attachments": [to_jsonable(item) for item in event.message.attachments],
                    "raw_payload": event.raw_payload,
                    "captured_at": event.created_at,
                },
            )
        )
        if event.message.attachments:
            artifacts.append(
                self._write_gateway_artifact(
                    owner_type="channel_event",
                    owner_id=event.event_id,
                    artifact_kind="ingress_attachment_manifest",
                    payload={
                        "version": "v1",
                        "channel_event_id": event.event_id,
                        "input_profile": candidate.metadata.get("input_profile"),
                        "attachment_count": len(event.message.attachments),
                        "attachments": [to_jsonable(item) for item in event.message.attachments],
                        "captured_at": event.created_at,
                    },
                )
            )
        self.journal.append(
            "gateway_ingress_artifacts_persisted",
            "gateway",
            {
                "channel_event_id": event.event_id,
                "artifact_ids": [item.artifact_id for item in artifacts],
                "input_profile": candidate.metadata.get("input_profile"),
            },
        )
        return artifacts

    def _persist_long_context_workflow(
        self,
        event: ChannelEvent,
        candidate,
        ingress_artifacts: list[ArtifactPointer],
    ) -> list[ArtifactPointer]:
        if not self.paths or not self.path_policy:
            return []
        if not candidate.metadata.get("requires_long_context_pipeline"):
            return []
        workflow, segments_payload = self._build_long_context_workflow(event, candidate, ingress_artifacts)
        workflow_pointer = self._write_gateway_artifact(
            owner_type="channel_event",
            owner_id=event.event_id,
            artifact_kind="long_context_workflow",
            payload=workflow,
        )
        segments_pointer = self._write_gateway_artifact(
            owner_type="channel_event",
            owner_id=event.event_id,
            artifact_kind="long_context_segments",
            payload=segments_payload,
        )
        digest = dict(workflow["digest"])
        digest["artifact_ids"] = [workflow_pointer.artifact_id, segments_pointer.artifact_id]
        digest["artifact_paths"] = [workflow_pointer.path, segments_pointer.path]
        candidate.metadata["long_context_workflow_id"] = workflow["workflow_id"]
        candidate.metadata["long_context_summary"] = workflow["summary"]
        candidate.metadata["long_context_phase_status"] = workflow["status"]
        candidate.metadata["long_context_artifact_map"] = {
            workflow_pointer.artifact_kind: {
                "artifact_id": workflow_pointer.artifact_id,
                "path": workflow_pointer.path,
            },
            segments_pointer.artifact_kind: {
                "artifact_id": segments_pointer.artifact_id,
                "path": segments_pointer.path,
            },
        }
        candidate.metadata["long_context_digest"] = digest
        candidate.metadata["long_context_compact_message"] = self._long_context_compact_message(event, workflow)
        self.journal.append(
            "gateway_long_context_workflow_ready",
            "gateway",
            {
                "channel_event_id": event.event_id,
                "workflow_id": workflow["workflow_id"],
                "segment_count": workflow["segment_count"],
                "input_profile": candidate.metadata.get("input_profile"),
            },
        )
        return [workflow_pointer, segments_pointer]

    def _build_long_context_workflow(
        self,
        event: ChannelEvent,
        candidate,
        ingress_artifacts: list[ArtifactPointer],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        source_text = self._long_context_source_text(event)
        normalized_text = self._normalize_long_context_text(source_text)
        segments = self._segment_long_context_text(normalized_text)
        segment_rows: list[dict[str, Any]] = []
        hierarchical_summary: list[str] = []
        decisions: list[str] = []
        actions: list[str] = []
        questions: list[str] = []
        for index, segment_text in enumerate(segments, start=1):
            extracted = self._extract_long_context_items(segment_text)
            segment_summary = self._summarize_long_context_segment(segment_text)
            hierarchical_summary.append(segment_summary)
            decisions = self._merge_long_context_items(decisions, extracted["decisions"])
            actions = self._merge_long_context_items(actions, extracted["actions"])
            questions = self._merge_long_context_items(questions, extracted["questions"])
            segment_rows.append(
                {
                    "segment_index": index,
                    "char_count": len(segment_text),
                    "summary": segment_summary,
                    "text_excerpt": self._trim_long_context_text(segment_text, limit=420),
                    "decisions": extracted["decisions"],
                    "actions": extracted["actions"],
                    "questions": extracted["questions"],
                }
            )
        workflow_id = new_id("long_context")
        overall_summary = self._long_context_overall_summary(
            input_profile=str(candidate.metadata.get("input_profile") or "long_text"),
            segment_count=len(segment_rows),
            hierarchical_summary=hierarchical_summary,
            decisions=decisions,
            actions=actions,
            questions=questions,
        )
        digest = {
            "workflow_id": workflow_id,
            "input_profile": str(candidate.metadata.get("input_profile") or "long_text"),
            "summary": overall_summary,
            "segment_count": len(segment_rows),
            "hierarchical_summary": hierarchical_summary[:3],
            "decisions": decisions[:_LONG_CONTEXT_MAX_ITEMS],
            "actions": actions[:_LONG_CONTEXT_MAX_ITEMS],
            "questions": questions[:_LONG_CONTEXT_MAX_ITEMS],
        }
        workflow = {
            "version": "v1",
            "workflow_id": workflow_id,
            "status": "ready",
            "channel_event_id": event.event_id,
            "message_id": event.message.message_id,
            "input_profile": str(candidate.metadata.get("input_profile") or "long_text"),
            "source_artifact_ids": [item.artifact_id for item in ingress_artifacts],
            "source_artifact_paths": [item.path for item in ingress_artifacts],
            "input_char_count": len(normalized_text),
            "segment_count": len(segment_rows),
            "summary": overall_summary,
            "digest": digest,
            "phases": [
                {"phase": "receive", "status": "completed", "summary": "Ingress brut deja persiste."},
                {"phase": "normalize", "status": "completed", "summary": "Texte compact et normalise."},
                {"phase": "segment", "status": "completed", "summary": f"{len(segment_rows)} segments prepares."},
                {"phase": "summarize", "status": "completed", "summary": "Resume hierarchique calcule."},
                {
                    "phase": "extract",
                    "status": "completed",
                    "summary": (
                        f"{len(decisions)} decisions, {len(actions)} actions, {len(questions)} questions extraites."
                    ),
                },
                {"phase": "ready", "status": "completed", "summary": "Digest pret pour routage et relecture."},
            ],
            "created_at": event.created_at,
        }
        segments_payload = {
            "version": "v1",
            "workflow_id": workflow_id,
            "channel_event_id": event.event_id,
            "segments": segment_rows,
            "created_at": event.created_at,
        }
        return workflow, segments_payload

    @staticmethod
    def _long_context_source_text(event: ChannelEvent) -> str:
        parts: list[str] = []
        raw_text = event.message.text.strip()
        if raw_text:
            parts.append(raw_text)
        if event.message.attachments:
            attachment_lines = []
            for attachment in event.message.attachments:
                descriptor = attachment.name
                if attachment.kind:
                    descriptor = f"{attachment.kind}: {descriptor}"
                if attachment.mime_type:
                    descriptor = f"{descriptor} ({attachment.mime_type})"
                attachment_lines.append(f"- {descriptor}")
            parts.append("Pieces jointes:\n" + "\n".join(attachment_lines))
        return "\n\n".join(part for part in parts if part.strip()).strip()

    @staticmethod
    def _normalize_long_context_text(text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _segment_long_context_text(self, text: str) -> list[str]:
        if not text:
            return [""]
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if not paragraphs:
            paragraphs = [text.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= _LONG_CONTEXT_SEGMENT_TARGET:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(paragraph) <= _LONG_CONTEXT_SEGMENT_HARD_LIMIT:
                current = paragraph
                continue
            current = ""
            chunks.extend(self._split_long_context_paragraph(paragraph))
        if current:
            chunks.append(current)
        return chunks or [text.strip()]

    @staticmethod
    def _split_long_context_paragraph(paragraph: str) -> list[str]:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
        if not sentences:
            sentences = [paragraph]
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= _LONG_CONTEXT_SEGMENT_HARD_LIMIT:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(sentence) <= _LONG_CONTEXT_SEGMENT_HARD_LIMIT:
                current = sentence
                continue
            words = sentence.split()
            word_chunk = ""
            for word in words:
                word_candidate = f"{word_chunk} {word}".strip() if word_chunk else word
                if len(word_candidate) <= _LONG_CONTEXT_SEGMENT_HARD_LIMIT:
                    word_chunk = word_candidate
                    continue
                if word_chunk:
                    chunks.append(word_chunk)
                word_chunk = word
            current = word_chunk
        if current:
            chunks.append(current)
        return chunks

    def _summarize_long_context_segment(self, text: str) -> str:
        cleaned = " ".join(text.split())
        if not cleaned:
            return ""
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
        if sentences:
            return self._trim_long_context_text(" ".join(sentences[:2]), limit=220)
        return self._trim_long_context_text(cleaned, limit=220)

    def _extract_long_context_items(self, text: str) -> dict[str, list[str]]:
        decisions: list[str] = []
        actions: list[str] = []
        questions: list[str] = []
        lines = [line.strip(" -*\t") for line in text.splitlines() if line.strip()]
        for question in re.findall(r"[^.!?\n]*\?+", text):
            cleaned = self._trim_long_context_text(question.strip(), limit=180)
            if cleaned:
                questions = self._merge_long_context_items(questions, [cleaned])
        for line in lines:
            lowered = line.lower()
            cleaned = self._trim_long_context_text(line.strip(), limit=180)
            if not cleaned:
                continue
            if "?" in line or any(token in lowered for token in ("est-ce", "faut-il", "dois-je", "confirme", "quel ", "quelle ", "quand ", "comment ")):
                questions = self._merge_long_context_items(questions, [cleaned])
                continue
            if any(token in lowered for token in ("decision", "verdict", "on garde", "on va", "contraint", "choix", "retenir", "keep ")):
                decisions = self._merge_long_context_items(decisions, [cleaned])
            if any(
                token in lowered
                for token in ("action", "test", "lancer", "corriger", "patch", "prochain pas", "todo", "doit", "faut ", "envoyer", "verifier")
            ):
                actions = self._merge_long_context_items(actions, [cleaned])
        return {
            "decisions": decisions[:_LONG_CONTEXT_MAX_ITEMS],
            "actions": actions[:_LONG_CONTEXT_MAX_ITEMS],
            "questions": questions[:_LONG_CONTEXT_MAX_ITEMS],
        }

    @staticmethod
    def _merge_long_context_items(existing: list[str], new_items: list[str]) -> list[str]:
        merged = list(existing)
        seen = {item.strip().lower() for item in existing}
        for item in new_items:
            normalized = item.strip().lower()
            if not normalized or normalized in seen:
                continue
            merged.append(item.strip())
            seen.add(normalized)
        return merged

    def _long_context_overall_summary(
        self,
        *,
        input_profile: str,
        segment_count: int,
        hierarchical_summary: list[str],
        decisions: list[str],
        actions: list[str],
        questions: list[str],
    ) -> str:
        headline = hierarchical_summary[0] if hierarchical_summary else "Digest long-context pret."
        return (
            f"Input {input_profile} traite en {segment_count} segments; "
            f"{len(decisions)} decisions, {len(actions)} actions, {len(questions)} questions. "
            f"Point principal: {self._trim_long_context_text(headline, limit=180)}"
        )

    def _long_context_compact_message(self, event: ChannelEvent, workflow: dict[str, Any]) -> str:
        digest = workflow.get("digest") or {}
        requested_focus = self._trim_long_context_text(event.message.text.strip(), limit=220)
        summary = self._trim_long_context_text(str(digest.get("summary") or workflow.get("summary") or ""), limit=260)
        if requested_focus and requested_focus != summary:
            return (
                "Input long detecte. Utilise le digest long-context et les artefacts associes comme source principale. "
                f"Focus fondateur: {requested_focus}\nDigest: {summary}"
            )
        return (
            "Input long detecte. Utilise le digest long-context et les artefacts associes comme source principale. "
            f"Digest: {summary}"
        )

    @staticmethod
    def _trim_long_context_text(text: str, *, limit: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    def _finalize_reply_artifact_output(
        self,
        *,
        event: ChannelEvent,
        candidate,
        decision: RoutingDecision,
        reply: OperatorReply,
        full_response: str,
        context_bundle: GatewayContextBundle | None,
    ) -> None:
        try:
            manifest = self._build_response_manifest(
                event=event,
                candidate=candidate,
                decision=decision,
                reply=reply,
                full_response=full_response,
                context_bundle=context_bundle,
            )
        except Exception as exc:
            logging.getLogger("project_os.gateway").warning("response manifest build failed: %s", exc)
            reply.metadata["response_manifest_error"] = str(exc)
            return
        if manifest is None:
            return
        reply.response_manifest = manifest
        reply.metadata["response_delivery_mode"] = manifest.delivery_mode
        if manifest.metadata.get("manifest_artifact_id"):
            reply.metadata["response_manifest_id"] = manifest.metadata["manifest_artifact_id"]
        if manifest.review_artifact_id:
            reply.metadata["response_review_artifact_id"] = manifest.review_artifact_id
        if manifest.delivery_mode == "artifact_summary":
            reply.summary = manifest.discord_summary

    def _build_response_manifest(
        self,
        *,
        event: ChannelEvent,
        candidate,
        decision: RoutingDecision,
        reply: OperatorReply,
        full_response: str,
        context_bundle: GatewayContextBundle | None,
    ) -> OperatorResponseManifest | None:
        response_text = str(full_response or "").strip()
        if not response_text:
            return None
        delivery_mode = self._response_delivery_mode(candidate, response_text)
        manifest = OperatorResponseManifest(
            delivery_mode=delivery_mode,
            discord_summary=reply.summary,
            metadata={
                "input_profile": candidate.metadata.get("input_profile"),
                "model_provider": decision.model_route.provider,
                "model": decision.model_route.model,
                "message_char_count": len(response_text),
                "source_artifact_ids": list(candidate.metadata.get("source_artifact_ids", [])),
                "long_context_artifact_ids": list(candidate.metadata.get("long_context_artifact_ids", [])),
            },
        )
        if delivery_mode != "artifact_summary" or not self.paths or not self.path_policy:
            return manifest

        extracted = self._extract_response_review_items(response_text)
        overview = self._response_review_overview(response_text)
        highlights = self._response_review_highlights(response_text, extracted)
        review_markdown = self._render_response_review_markdown(
            event=event,
            candidate=candidate,
            decision=decision,
            full_response=response_text,
            extracted=extracted,
            context_bundle=context_bundle,
        )
        review_pointer = self._write_gateway_text_artifact(
            owner_type="gateway_reply",
            owner_id=reply.reply_id,
            artifact_kind="response_review_markdown",
            text=review_markdown,
            suffix=".md",
        )
        review_pdf_pointer = self._write_gateway_response_pdf_artifact(
            owner_id=reply.reply_id,
            event=event,
            candidate=candidate,
            decision=decision,
            full_response=response_text,
            overview=overview,
            highlights=highlights,
            extracted=extracted,
        )
        decision_pointer = self._write_gateway_artifact(
            owner_type="gateway_reply",
            owner_id=f"{reply.reply_id}_decisions",
            artifact_kind="response_decision_extract",
            payload={
                "version": "v1",
                "reply_id": reply.reply_id,
                "items": extracted["decisions"],
                "created_at": reply.created_at,
            },
        )
        action_pointer = self._write_gateway_artifact(
            owner_type="gateway_reply",
            owner_id=f"{reply.reply_id}_actions",
            artifact_kind="response_action_extract",
            payload={
                "version": "v1",
                "reply_id": reply.reply_id,
                "items": extracted["actions"],
                "created_at": reply.created_at,
            },
        )
        manifest.discord_summary = self._build_artifact_summary_message(
            full_response=response_text,
            overview=overview,
            highlights=highlights,
        )
        manifest.full_artifact_id = review_pdf_pointer.artifact_id
        manifest.review_artifact_id = review_pdf_pointer.artifact_id
        manifest.decision_extract_artifact_id = decision_pointer.artifact_id
        manifest.action_extract_artifact_id = action_pointer.artifact_id
        manifest.source_artifact_id = self._primary_source_artifact_id(candidate)
        manifest.metadata["review_markdown_artifact_id"] = review_pointer.artifact_id
        manifest.metadata["review_markdown_artifact_path"] = review_pointer.path
        long_context_map = candidate.metadata.get("long_context_artifact_map") or {}
        if isinstance(long_context_map, dict):
            segments_ref = long_context_map.get("long_context_segments") or {}
            manifest.segments_artifact_id = (
                str(segments_ref.get("artifact_id")).strip() if segments_ref.get("artifact_id") else None
            )
        manifest.attachments = [
            OperatorReplyArtifact(
                artifact_id=review_pdf_pointer.artifact_id,
                artifact_kind=review_pdf_pointer.artifact_kind,
                path=review_pdf_pointer.path,
                name=f"project-os-review-{reply.reply_id}.pdf",
                mime_type="application/pdf",
                label="Reponse complete (PDF)",
                metadata={"owner_type": "gateway_reply", "owner_id": reply.reply_id},
            )
        ]
        manifest_pointer = self._write_gateway_artifact(
            owner_type="gateway_reply",
            owner_id=reply.reply_id,
            artifact_kind="response_manifest",
            payload={
                "version": "v1",
                "reply_id": reply.reply_id,
                "response_manifest": to_jsonable(manifest),
                "questions": extracted["questions"],
                "generated_at": reply.created_at,
            },
        )
        manifest.metadata["manifest_artifact_id"] = manifest_pointer.artifact_id
        manifest.metadata["manifest_artifact_path"] = manifest_pointer.path
        self.journal.append(
            "gateway_response_manifest_ready",
            "gateway",
            {
                "channel_event_id": event.event_id,
                "reply_id": reply.reply_id,
                "delivery_mode": delivery_mode,
                "manifest_artifact_id": manifest_pointer.artifact_id,
                "review_artifact_id": review_pdf_pointer.artifact_id,
            },
        )
        return manifest

    def _response_delivery_mode(self, candidate, response_text: str) -> str:
        normalized = str(response_text or "").strip()
        line_count = len([line for line in normalized.splitlines() if line.strip()])
        input_profile = str(candidate.metadata.get("input_profile") or "").strip().lower()
        requires_long_context = bool(candidate.metadata.get("requires_long_context_pipeline"))
        if bool(candidate.metadata.get("force_artifact_summary")):
            return "artifact_summary"
        if (
            requires_long_context
            or input_profile in {"document", "transcript", "attachment_heavy", "very_long_text"}
            or len(normalized) >= _ARTIFACT_SUMMARY_RESPONSE_LENGTH
            or line_count >= _ARTIFACT_SUMMARY_LINE_THRESHOLD
        ):
            return "artifact_summary"
        return "inline_text"

    def _build_artifact_summary_message(self, *, full_response: str, overview: str, highlights: list[str]) -> str:
        summary = overview.strip() or self._response_review_overview(full_response)
        lines: list[str] = []
        if summary:
            lines.append(summary)
        if highlights:
            if lines:
                lines.append("")
            lines.append("Dans le PDF :")
            for item in highlights[:_RESPONSE_REVIEW_ITEM_LIMIT]:
                lines.append(f"- {item}")
        if lines:
            lines.append("")
        lines.append("PDF joint.")
        return "\n".join(lines)

    def _response_review_overview(self, text: str) -> str:
        cleaned = re.sub(r"[*_`#>-]+", " ", str(text or ""))
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        source = paragraphs[0] if paragraphs else cleaned.strip()
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", source) if part.strip()]
        if sentences:
            return self._trim_long_context_text(" ".join(sentences[:2]), limit=220)
        return self._trim_long_context_text(source, limit=220)

    def _response_review_highlights(self, text: str, extracted: dict[str, list[str]]) -> list[str]:
        lowered = " ".join(str(text or "").lower().split())
        items: list[str] = []
        duration_match = re.search(r"\b(\d+\s*(?:-|a|à)\s*\d+\s*minutes?|\d+\s*minutes?)\b", lowered)
        if any(token in lowered for token in ("inspect", "inspection", "workspace", "repo", "code", "doc", "documentation")):
            items.append("la methode d'inspection du repo et de la doc")
        if duration_match is not None:
            items.append(f"le delai estime: {duration_match.group(1)}")
        if any(token in lowered for token in ("inspiration", "pattern", "reference", "architecture", "memoire", "gestion memoire")):
            items.append("les inspirations probables et les patterns a verifier")
        if any(token in lowered for token in ("je ne ferais pas", "je n'inventerais pas", "si on n'a pas", "pas documente", "pas formalise")):
            items.append("les limites actuelles et ce qui reste a confirmer")
        if extracted.get("questions"):
            items.append("la question ouverte a trancher")
        if not items:
            items.append("la version longue de la reponse")
        return self._merge_long_context_items([], items)[:_RESPONSE_REVIEW_ITEM_LIMIT]

    def _render_response_review_markdown(
        self,
        *,
        event: ChannelEvent,
        candidate,
        decision: RoutingDecision,
        full_response: str,
        extracted: dict[str, list[str]],
        context_bundle: GatewayContextBundle | None,
    ) -> str:
        sections = [
            "# Project OS Review Artifact",
            "",
            "## Metadata",
            f"- Channel event: `{event.event_id}`",
            f"- Message id: `{event.message.message_id}`",
            f"- Input profile: `{candidate.metadata.get('input_profile') or 'unknown'}`",
            f"- Provider: `{decision.model_route.provider}`",
            f"- Model: `{decision.model_route.model or 'unknown'}`",
            f"- Delivery mode: `artifact_summary`",
        ]
        if context_bundle is not None:
            sections.append(f"- Mood hint: `{context_bundle.mood_hint.mood}`")
            sections.append(f"- Query scope: `{context_bundle.query_scope}`")
        if extracted["decisions"]:
            sections.extend(["", "## Decisions"])
            sections.extend(f"- {item}" for item in extracted["decisions"])
        if extracted["actions"]:
            sections.extend(["", "## Actions"])
            sections.extend(f"- {item}" for item in extracted["actions"])
        if extracted["questions"]:
            sections.extend(["", "## Questions"])
            sections.extend(f"- {item}" for item in extracted["questions"])
        sections.extend(["", "## Full Response", "", full_response.strip()])
        long_context_summary = str(candidate.metadata.get("long_context_summary") or "").strip()
        if long_context_summary:
            sections.extend(["", "## Long Context Summary", "", long_context_summary])
        source_ids = list(candidate.metadata.get("source_artifact_ids", []))
        if source_ids:
            sections.extend(["", "## Source Artifacts"])
            sections.extend(f"- `{artifact_id}`" for artifact_id in source_ids)
        return "\n".join(sections).strip() + "\n"

    def _extract_response_review_items(self, text: str) -> dict[str, list[str]]:
        decisions: list[str] = []
        actions: list[str] = []
        questions: list[str] = []
        fallback_items: list[str] = []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("```"):
                continue
            normalized = stripped.lstrip("-*0123456789. )\t").strip()
            lowered = normalized.lower()
            if lowered.startswith(("decision:", "decisions:", "choix:", "verdict:")):
                decisions = self._merge_long_context_items(decisions, [normalized.split(":", 1)[-1].strip() or normalized])
                continue
            if lowered.startswith(("action:", "actions:", "prochain pas", "todo:", "a faire:")):
                actions = self._merge_long_context_items(actions, [normalized.split(":", 1)[-1].strip() or normalized])
                continue
            if lowered.startswith(("question:", "questions:", "a verifier:", "point a verifier:")):
                questions = self._merge_long_context_items(questions, [normalized.split(":", 1)[-1].strip() or normalized])
                continue
            if len(fallback_items) < _RESPONSE_REVIEW_ITEM_LIMIT:
                fallback_items.append(self._trim_long_context_text(normalized, limit=140))
        if not decisions:
            decisions = fallback_items[:1]
        if not actions:
            actions = fallback_items[:_RESPONSE_REVIEW_ITEM_LIMIT]
        return {
            "decisions": decisions[:_LONG_CONTEXT_MAX_ITEMS],
            "actions": actions[:_LONG_CONTEXT_MAX_ITEMS],
            "questions": questions[:_LONG_CONTEXT_MAX_ITEMS],
        }

    @staticmethod
    def _primary_source_artifact_id(candidate) -> str | None:
        source_artifact_ids = candidate.metadata.get("source_artifact_ids")
        if not isinstance(source_artifact_ids, list):
            return None
        for artifact_id in source_artifact_ids:
            value = str(artifact_id or "").strip()
            if value:
                return value
        return None

    def _write_gateway_text_artifact(
        self,
        *,
        owner_type: str,
        owner_id: str,
        artifact_kind: str,
        text: str,
        suffix: str = ".md",
    ) -> ArtifactPointer:
        assert self.paths is not None
        assert self.path_policy is not None
        pointer = write_text_artifact(
            paths=self.paths,
            path_policy=self.path_policy,
            owner_id=owner_id,
            artifact_kind=artifact_kind,
            storage_tier=MemoryTier.HOT,
            text=text,
            suffix=suffix,
        )
        self.database.upsert(
            "artifact_pointers",
            {
                "artifact_id": pointer.artifact_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "artifact_kind": pointer.artifact_kind,
                "storage_tier": pointer.storage_tier.value,
                "path": pointer.path,
                "checksum_sha256": pointer.checksum_sha256,
                "size_bytes": pointer.size_bytes,
                "created_at": pointer.created_at,
            },
            conflict_columns="artifact_id",
            immutable_columns=["created_at"],
        )
        return pointer

    def _write_gateway_binary_artifact(
        self,
        *,
        owner_type: str,
        owner_id: str,
        artifact_kind: str,
        payload: bytes,
        suffix: str,
    ) -> ArtifactPointer:
        assert self.paths is not None
        assert self.path_policy is not None
        pointer = write_binary_artifact(
            paths=self.paths,
            path_policy=self.path_policy,
            owner_id=owner_id,
            artifact_kind=artifact_kind,
            storage_tier=MemoryTier.HOT,
            payload=payload,
            suffix=suffix,
        )
        self.database.upsert(
            "artifact_pointers",
            {
                "artifact_id": pointer.artifact_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "artifact_kind": pointer.artifact_kind,
                "storage_tier": pointer.storage_tier.value,
                "path": pointer.path,
                "checksum_sha256": pointer.checksum_sha256,
                "size_bytes": pointer.size_bytes,
                "created_at": pointer.created_at,
            },
            conflict_columns="artifact_id",
            immutable_columns=["created_at"],
        )
        return pointer

    def _write_gateway_response_pdf_artifact(
        self,
        *,
        owner_id: str,
        event: ChannelEvent,
        candidate,
        decision: RoutingDecision,
        full_response: str,
        overview: str,
        highlights: list[str],
        extracted: dict[str, list[str]],
    ) -> ArtifactPointer:
        assert self.paths is not None
        assert self.path_policy is not None
        pdf_folder = self.paths.runtime_artifact_root / "response_review_pdf"
        pdf_folder.mkdir(parents=True, exist_ok=True)
        destination = self.path_policy.ensure_allowed_write(pdf_folder / f"{owner_id}.pdf")
        render_operator_reply_pdf(
            destination,
            display_title="Reponse detaillee Project OS",
            metadata={
                "channel": event.message.channel,
                "input_profile": candidate.metadata.get("input_profile") or "unknown",
                "provider": decision.model_route.provider,
                "model": decision.model_route.model or "unknown",
                "delivery_mode": "artifact_summary",
                "message_id": event.message.message_id,
            },
            overview=overview,
            highlights=highlights,
            questions=extracted["questions"],
            full_response=full_response,
        )
        return self._write_gateway_binary_artifact(
            owner_type="gateway_reply",
            owner_id=owner_id,
            artifact_kind="response_review_pdf",
            payload=destination.read_bytes(),
            suffix=".pdf",
        )

    def _write_gateway_artifact(
        self,
        *,
        owner_type: str,
        owner_id: str,
        artifact_kind: str,
        payload: dict,
    ) -> ArtifactPointer:
        assert self.paths is not None
        assert self.path_policy is not None
        pointer = write_json_artifact(
            paths=self.paths,
            path_policy=self.path_policy,
            owner_id=owner_id,
            artifact_kind=artifact_kind,
            storage_tier=MemoryTier.HOT,
            payload=payload,
        )
        self.database.upsert(
            "artifact_pointers",
            {
                "artifact_id": pointer.artifact_id,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "artifact_kind": pointer.artifact_kind,
                "storage_tier": pointer.storage_tier.value,
                "path": pointer.path,
                "checksum_sha256": pointer.checksum_sha256,
                "size_bytes": pointer.size_bytes,
                "created_at": pointer.created_at,
            },
            conflict_columns="artifact_id",
            immutable_columns=["created_at"],
        )
        return pointer

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
