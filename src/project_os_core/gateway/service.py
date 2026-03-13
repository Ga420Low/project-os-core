from __future__ import annotations

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
        selective_sync: SelectiveSyncPromoter | None = None,
    ) -> None:
        self.database = database
        self.journal = journal
        self.router = router
        self.memory = memory
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
        intent = self.router.envelope_to_intent(envelope)
        decision, trace, mission_run = self.router.route_intent(intent, persist=True)
        promoted_memory_ids = self._apply_selective_sync(candidate, promotion)
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
        if message_kind in {None, }:
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
        self.database.execute(
            """
            INSERT OR REPLACE INTO channel_events(
                event_id, surface, event_type, actor_id, channel, message_kind,
                thread_ref_json, message_json, raw_payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.surface,
                event.event_type,
                event.message.actor_id,
                event.message.channel,
                candidate.classification.value,
                dump_json(to_jsonable(event.message.thread_ref)),
                dump_json(to_jsonable(event.message)),
                dump_json(event.raw_payload),
                event.created_at,
            ),
        )

        self.database.execute(
            """
            INSERT OR REPLACE INTO conversation_memory_candidates(
                candidate_id, source_event_id, actor_id, classification, thread_ref_json, summary,
                content, tags_json, tier, should_promote, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.source_event_id,
                candidate.actor_id,
                candidate.classification.value,
                dump_json(to_jsonable(candidate.thread_ref)),
                candidate.summary,
                candidate.content,
                dump_json(candidate.tags),
                candidate.tier.value,
                1 if candidate.should_promote else 0,
                dump_json(candidate.metadata),
                candidate.created_at,
            ),
        )

    def _persist_promotion(self, candidate, promotion) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO promotion_decisions(
                promotion_decision_id, candidate_id, action, reason, memory_type, tier,
                memory_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                promotion.promotion_decision_id,
                candidate.candidate_id,
                promotion.action.value,
                promotion.reason,
                promotion.memory_type.value if promotion.memory_type else None,
                promotion.tier.value if promotion.tier else None,
                promotion.memory_id,
                dump_json(promotion.metadata),
                promotion.created_at,
            ),
        )

    def _persist_dispatch(self, dispatch: GatewayDispatchResult) -> None:
        self.database.execute(
            """
            INSERT OR REPLACE INTO gateway_dispatch_results(
                dispatch_id, channel_event_id, envelope_id, intent_id, decision_id, mission_run_id,
                memory_candidate_id, promotion_decision_id, promoted_memory_ids_json, reply_json,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dispatch.dispatch_id,
                dispatch.channel_event_id,
                dispatch.envelope_id,
                dispatch.intent_id,
                dispatch.decision_id,
                dispatch.mission_run_id,
                dispatch.memory_candidate_id,
                dispatch.promotion_decision_id,
                dump_json(dispatch.promoted_memory_ids),
                dump_json(to_jsonable(dispatch.operator_reply)),
                dump_json(dispatch.metadata),
                dispatch.created_at,
            ),
        )
