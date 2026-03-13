from __future__ import annotations

from dataclasses import replace

from ..models import (
    ChannelEvent,
    ConversationMemoryCandidate,
    HumanArtifact,
    MemoryTier,
    MemoryType,
    OperatorAttachment,
    OperatorMessageKind,
    PromotionAction,
    PromotionDecision,
    new_id,
)


class SelectiveSyncPromoter:
    """Classify channel events and decide whether they enter durable memory."""

    _DECISION_HINTS = ("decision", "decide", "on valide", "go ", "go:", "we keep", "keep ")
    _IDEA_HINTS = ("idea", "on pourrait", "maybe", "perhaps", "on devrait", "we could")
    _NOTE_HINTS = ("note", "remember", "rappel", "memo", "preference", "prefer", "always", "never", "by default")
    _TASK_HINTS = ("please", "fais", "implement", "build", "create", "write", "route", "run", "launch", "ouvre")
    _NOISE_HINTS = ("salut", "hello", "hi", "yo", "ça va", "ca va", "merci", "thanks")

    def classify_message(self, event: ChannelEvent) -> OperatorMessageKind:
        text = event.message.text.strip().lower()
        if event.message.attachments and not text:
            return OperatorMessageKind.ARTIFACT_REF
        if any(token in text for token in self._DECISION_HINTS):
            return OperatorMessageKind.DECISION
        if any(token in text for token in self._IDEA_HINTS):
            return OperatorMessageKind.IDEA
        if any(token in text for token in self._NOTE_HINTS):
            return OperatorMessageKind.NOTE
        if any(token in text for token in self._TASK_HINTS):
            return OperatorMessageKind.TASKING
        if event.message.attachments:
            return OperatorMessageKind.ARTIFACT_REF
        return OperatorMessageKind.CHAT

    def build_human_artifacts(self, event: ChannelEvent) -> list[HumanArtifact]:
        artifacts: list[HumanArtifact] = []
        excerpt = event.message.text.strip()[:240] or None
        for attachment in event.message.attachments:
            artifacts.append(
                HumanArtifact(
                    artifact_id=new_id("human_artifact"),
                    source_event_id=event.event_id,
                    thread_ref=event.message.thread_ref,
                    actor_id=event.message.actor_id,
                    kind=attachment.kind,
                    text_excerpt=excerpt,
                    attachment=attachment,
                    metadata={"name": attachment.name},
                )
            )
        return artifacts

    def build_candidate(self, event: ChannelEvent) -> ConversationMemoryCandidate:
        classification = self.classify_message(event)
        summary = self._summarize(event.message.text, classification, event.message.attachments)
        should_promote = self._should_promote(classification, event.message.text)
        tags = self._tags_for(classification, event.message.attachments)
        tier = MemoryTier.WARM if should_promote else MemoryTier.HOT
        metadata = {
            "channel": event.message.channel,
            "surface": event.surface,
            "attachments": [attachment.name for attachment in event.message.attachments],
            "thread_ref": event.message.thread_ref.external_thread_id or event.message.thread_ref.thread_id,
        }
        return ConversationMemoryCandidate(
            candidate_id=new_id("candidate"),
            source_event_id=event.event_id,
            thread_ref=event.message.thread_ref,
            actor_id=event.message.actor_id,
            classification=classification,
            summary=summary,
            content=event.message.text.strip() or self._attachments_summary(event.message.attachments),
            tags=tags,
            tier=tier,
            should_promote=should_promote,
            metadata=metadata,
        )

    def decide_promotion(self, candidate: ConversationMemoryCandidate) -> PromotionDecision:
        if not candidate.should_promote:
            return PromotionDecision(
                promotion_decision_id=new_id("promotion"),
                candidate_id=candidate.candidate_id,
                action=PromotionAction.SKIP,
                reason="selective_sync_filtered_noise",
                metadata={"classification": candidate.classification.value},
            )

        memory_type = self._memory_type_for(candidate.classification)
        return PromotionDecision(
            promotion_decision_id=new_id("promotion"),
            candidate_id=candidate.candidate_id,
            action=PromotionAction.PROMOTE,
            reason="selective_sync_promoted",
            memory_type=memory_type,
            tier=candidate.tier,
            metadata={"classification": candidate.classification.value, "tags": list(candidate.tags)},
        )

    def promote_ready_candidate(self, candidate: ConversationMemoryCandidate) -> ConversationMemoryCandidate:
        return replace(
            candidate,
            metadata={
                **candidate.metadata,
                "promotion_policy": "selective_sync",
                "classification": candidate.classification.value,
            },
        )

    def _should_promote(self, classification: OperatorMessageKind, text: str) -> bool:
        lowered = text.strip().lower()
        if classification in {OperatorMessageKind.DECISION, OperatorMessageKind.TASKING, OperatorMessageKind.ARTIFACT_REF}:
            return True
        if classification is OperatorMessageKind.NOTE:
            return True
        if classification is OperatorMessageKind.IDEA:
            return "validated" in lowered or "go" in lowered or "keep" in lowered
        if classification is OperatorMessageKind.CHAT and any(token in lowered for token in self._NOISE_HINTS):
            return False
        return False

    def _memory_type_for(self, classification: OperatorMessageKind) -> MemoryType:
        if classification is OperatorMessageKind.DECISION:
            return MemoryType.PROCEDURAL
        if classification is OperatorMessageKind.NOTE:
            return MemoryType.SEMANTIC
        if classification is OperatorMessageKind.ARTIFACT_REF:
            return MemoryType.EPISODIC
        if classification is OperatorMessageKind.TASKING:
            return MemoryType.EPISODIC
        return MemoryType.SEMANTIC

    def _tags_for(self, classification: OperatorMessageKind, attachments: list[OperatorAttachment]) -> list[str]:
        tags = [classification.value, "discord_selective_sync"]
        if attachments:
            tags.append("has_attachment")
        return tags

    def _summarize(self, text: str, classification: OperatorMessageKind, attachments: list[OperatorAttachment]) -> str:
        cleaned = " ".join(text.strip().split())
        if cleaned:
            return cleaned[:240]
        if attachments:
            return self._attachments_summary(attachments)
        return classification.value

    @staticmethod
    def _attachments_summary(attachments: list[OperatorAttachment]) -> str:
        names = ", ".join(attachment.name for attachment in attachments[:3])
        return f"Attachments referenced: {names}" if names else "Attachment reference"
