from __future__ import annotations

from ..database import CanonicalDatabase, dump_json
from ..memory.store import MemoryStore
from ..models import (
    ChannelEvent,
    GatewayDispatchResult,
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
        envelope = OperatorEnvelope(
            envelope_id=new_id("envelope"),
            actor_id=event.message.actor_id,
            channel=event.message.channel,
            objective=event.message.text.strip() or candidate.summary,
            target_profile=target_profile,
            requested_worker=requested_worker,
            requested_risk_class=risk_class,
            metadata={
                "channel_event_id": event.event_id,
                "message_kind": candidate.classification.value,
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
            metadata={
                "routing_trace_id": trace.trace_id,
                "classification": candidate.classification.value,
                "reply_kind": reply.reply_kind,
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
            summary = (
                f"Mission queued on {decision.chosen_worker or 'unknown'} "
                f"with {decision.execution_class.value} route."
            )
            reply_kind = "ack"
        else:
            summary = f"Mission blocked: {', '.join(decision.blocked_reasons or [decision.route_reason])}"
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
            metadata={"surface": event.surface},
        )

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
