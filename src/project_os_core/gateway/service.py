from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from ..artifacts import write_json_artifact, write_text_artifact
from ..database import CanonicalDatabase, dump_json
from ..deep_research import DeepResearchService
from ..local_model import LocalModelClient
from ..memory.store import MemoryStore
from ..models import (
    ActionContract,
    ActionRiskClass,
    ArtifactPointer,
    ChannelEvent,
    CommunicationMode,
    DelegationLevel,
    DiscordThreadBinding,
    DiscordChannelClass,
    DiscordRunCard,
    GatewayDispatchResult,
    InteractionState,
    IntentKind,
    MemoryTier,
    OperatorAudience,
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
from ..research_scaffold import ResearchScaffoldRequest, detect_deep_research_request, scaffold_research
from ..router.service import MissionRouter
from ..runtime.journal import LocalJournal
from ..session.state import PersistentSessionState, ResolvedIntent
from .context_builder import GatewayContextBuilder, GatewayContextBundle
from .persona import PersonaSpec, load_persona_spec
from .promotion import SelectiveSyncPromoter

_LONG_CONTEXT_SEGMENT_TARGET = 1200
_LONG_CONTEXT_SEGMENT_HARD_LIMIT = 1500
_LONG_CONTEXT_MAX_ITEMS = 6
_ARTIFACT_SUMMARY_RESPONSE_LENGTH = 1200
_ARTIFACT_SUMMARY_LINE_THRESHOLD = 10
_THREAD_CHUNK_RESPONSE_LENGTH = 700
_THREAD_CHUNK_LINE_THRESHOLD = 6
_DISCORD_ARTIFACT_SUMMARY_LIMIT = 900
_RESPONSE_REVIEW_OVERVIEW_LIMIT = 320
_RESPONSE_REVIEW_ITEM_LIMIT = 3


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
        deep_research_job = self._maybe_launch_deep_research_job(normalized_event, research_scaffold)
        if deep_research_job is not None:
            candidate.metadata["deep_research_job"] = deep_research_job
            candidate.metadata["deep_research_job_id"] = deep_research_job.get("job_id")
            candidate.metadata["deep_research_job_path"] = deep_research_job.get("job_path")
            candidate.metadata["deep_research_job_launched"] = deep_research_job.get("launched")
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
                "deep_research_job": candidate.metadata.get("deep_research_job"),
                "deep_research_job_id": candidate.metadata.get("deep_research_job_id"),
                "deep_research_job_path": candidate.metadata.get("deep_research_job_path"),
                "deep_research_job_launched": candidate.metadata.get("deep_research_job_launched"),
                **self._operator_override_metadata(normalized_event),
                **(metadata or {}),
            },
        )
        if deep_research_job is not None:
            self._persist_promotion(candidate, promotion)
            promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
            dispatch = self._build_deep_research_dispatch(
                event=normalized_event,
                envelope=envelope,
                promoted_memory_ids=promoted_memory_ids,
                candidate_id=candidate.candidate_id,
                promotion_decision_id=promotion.promotion_decision_id,
                channel_class=channel_class,
                job_payload=deep_research_job,
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
                "gateway_deep_research_dispatch_completed",
                "gateway",
                {
                    "dispatch_id": dispatch.dispatch_id,
                    "channel_event_id": normalized_event.event_id,
                    "deep_research_job_id": deep_research_job.get("job_id"),
                    "promoted_memory_count": len(promoted_memory_ids),
                },
            )
            return dispatch
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
        intent = self.router.envelope_to_intent(envelope)
        decision, trace, mission_run = self.router.route_intent(intent, persist=True)
        promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
        inline_context: GatewayContextBundle | None = None

        if decision.allowed and self._should_inline_chat(normalized_event, decision):
            message_for_model = self._message_for_route(candidate, decision)
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
                "action_result": to_jsonable(action_result),
            },
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
            response = client.messages.create(
                model=model,
                max_tokens=500,
                system=self._simple_chat_system_blocks(),
                messages=[
                    {
                        "role": "user",
                        "content": self._simple_chat_user_message(
                            message,
                            provider="anthropic",
                            model=model,
                            route_reason=route_reason,
                            context_bundle=context_bundle,
                        ),
                    },
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
    def _message_for_route(candidate, decision: RoutingDecision) -> str:
        compact_message = str(candidate.metadata.get("long_context_compact_message") or "").strip()
        if compact_message:
            return compact_message
        if decision.model_route.provider == "local":
            return candidate.content
        return GatewayService._message_for_cloud(candidate)

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
            summary = f"{summary} Le rapport final reviendra sur Discord avec le fichier Markdown."
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
        review_pointer = self._write_gateway_text_artifact(
            owner_type="gateway_reply",
            owner_id=reply.reply_id,
            artifact_kind="response_review_markdown",
            text=self._render_response_review_markdown(
                event=event,
                candidate=candidate,
                decision=decision,
                full_response=response_text,
                extracted=extracted,
                context_bundle=context_bundle,
            ),
            suffix=".md",
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
            candidate=candidate,
            full_response=response_text,
            extracted=extracted,
        )
        manifest.full_artifact_id = review_pointer.artifact_id
        manifest.review_artifact_id = review_pointer.artifact_id
        manifest.decision_extract_artifact_id = decision_pointer.artifact_id
        manifest.action_extract_artifact_id = action_pointer.artifact_id
        manifest.source_artifact_id = self._primary_source_artifact_id(candidate)
        long_context_map = candidate.metadata.get("long_context_artifact_map") or {}
        if isinstance(long_context_map, dict):
            segments_ref = long_context_map.get("long_context_segments") or {}
            manifest.segments_artifact_id = (
                str(segments_ref.get("artifact_id")).strip() if segments_ref.get("artifact_id") else None
            )
        manifest.attachments = [
            OperatorReplyArtifact(
                artifact_id=review_pointer.artifact_id,
                artifact_kind=review_pointer.artifact_kind,
                path=review_pointer.path,
                name=f"project-os-review-{reply.reply_id}.md",
                mime_type="text/markdown",
                label="Document complet",
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
                "review_artifact_id": review_pointer.artifact_id,
            },
        )
        return manifest

    def _response_delivery_mode(self, candidate, response_text: str) -> str:
        normalized = str(response_text or "").strip()
        line_count = len([line for line in normalized.splitlines() if line.strip()])
        input_profile = str(candidate.metadata.get("input_profile") or "").strip().lower()
        requires_long_context = bool(candidate.metadata.get("requires_long_context_pipeline"))
        if (
            requires_long_context
            or input_profile in {"document", "transcript", "attachment_heavy", "very_long_text"}
            or len(normalized) >= _ARTIFACT_SUMMARY_RESPONSE_LENGTH
            or line_count >= _ARTIFACT_SUMMARY_LINE_THRESHOLD
        ):
            return "artifact_summary"
        if len(normalized) >= _THREAD_CHUNK_RESPONSE_LENGTH or line_count >= _THREAD_CHUNK_LINE_THRESHOLD:
            return "thread_chunked_text"
        return "inline_text"

    def _build_artifact_summary_message(self, *, candidate, full_response: str, extracted: dict[str, list[str]]) -> str:
        input_profile = str(candidate.metadata.get("input_profile") or "").strip().lower()
        title = {
            "transcript": "Synthese complete prete.",
            "document": "Document de revue pret.",
            "attachment_heavy": "Livrable complet pret.",
        }.get(input_profile, "Reponse complete prete.")
        overview = self._trim_long_context_text(full_response, limit=_RESPONSE_REVIEW_OVERVIEW_LIMIT)
        priority_items = extracted["actions"] or extracted["decisions"] or extracted["questions"]
        lines = [
            title,
            f"Resume court: {overview}",
        ]
        if priority_items:
            lines.append("A verifier en priorite:")
            for item in priority_items[:_RESPONSE_REVIEW_ITEM_LIMIT]:
                lines.append(f"- {item}")
        lines.append("Document complet joint. Le contenu long reste stocke.")
        return "\n".join(lines)

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
