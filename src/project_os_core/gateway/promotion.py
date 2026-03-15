from __future__ import annotations

from dataclasses import replace
from typing import Sequence

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
    SensitivityClass,
    new_id,
)
from ..privacy_guard import assess_sensitivity, attachment_safe_summary


class SelectiveSyncPromoter:
    """Classify channel events and decide whether they enter durable memory."""

    _DECISION_HINTS = ("decision", "decide", "on valide", "go ", "go:", "we keep", "keep ")
    _IDEA_HINTS = ("idea", "on pourrait", "maybe", "perhaps", "on devrait", "we could")
    _NOTE_HINTS = ("note", "remember", "rappel", "memo", "preference", "prefer", "always", "never", "by default")
    _TASK_HINTS = ("please", "fais", "implement", "build", "create", "write", "route", "run", "launch", "ouvre")
    _STATUS_HINTS = ("status", "statut", "ou en est", "où en est", "progress", "ca en est ou", "ça en est où")
    _APPROVAL_HINTS = ("approve", "approval", "validation", "valide", "approuve", "autorise")
    _NOISE_HINTS = ("salut", "hello", "hi", "yo", "ça va", "ca va", "merci", "thanks")

    def classify_message(self, event: ChannelEvent) -> OperatorMessageKind:
        text = event.message.text.strip().lower()
        if event.message.attachments and not text:
            return OperatorMessageKind.ARTIFACT_REF
        if any(token in text for token in self._STATUS_HINTS):
            return OperatorMessageKind.STATUS_REQUEST
        if any(token in text for token in self._APPROVAL_HINTS):
            return OperatorMessageKind.APPROVAL
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
        raw_text = event.message.text.strip()
        attachment_names = [attachment.name for attachment in event.message.attachments]
        sensitivity = assess_sensitivity(raw_text, attachment_names=attachment_names)
        summary = self._summarize(raw_text, classification, event.message.attachments)
        should_promote = self._should_promote(classification, event.message.text) or sensitivity.classification is not SensitivityClass.S1
        tags = self._tags_for(classification, event.message.attachments, sensitivity.classification)
        tier = MemoryTier.WARM if should_promote else MemoryTier.HOT
        clean_content = self._clean_content_for(
            raw_text=raw_text,
            attachment_names=attachment_names,
            sensitivity=sensitivity.classification,
            fallback=sensitivity.clean_text,
        )
        metadata = {
            "channel": event.message.channel,
            "surface": event.surface,
            "attachments": attachment_names,
            "thread_ref": event.message.thread_ref.external_thread_id or event.message.thread_ref.thread_id,
            "sensitivity_class": sensitivity.classification.value,
            "sensitivity_reason": sensitivity.reason,
            "clean_content": clean_content,
            "sensitive_attachments": list(sensitivity.sensitive_attachments),
        }
        return ConversationMemoryCandidate(
            candidate_id=new_id("candidate"),
            source_event_id=event.event_id,
            thread_ref=event.message.thread_ref,
            actor_id=event.message.actor_id,
            classification=classification,
            summary=summary,
            content=raw_text or self._attachments_summary(event.message.attachments),
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
            metadata={
                "classification": candidate.classification.value,
                "tags": list(candidate.tags),
                "sensitivity_class": candidate.metadata.get("sensitivity_class"),
                "sensitivity_reason": candidate.metadata.get("sensitivity_reason"),
            },
        )

    def promote_ready_candidate(self, candidate: ConversationMemoryCandidate) -> ConversationMemoryCandidate:
        return replace(
            candidate,
            metadata={
                **candidate.metadata,
                "promotion_policy": "selective_sync",
                "classification": candidate.classification.value,
                "sensitivity_class": candidate.metadata.get("sensitivity_class", SensitivityClass.S1.value),
            },
        )

    def _should_promote(self, classification: OperatorMessageKind, text: str) -> bool:
        lowered = text.strip().lower()
        if classification in {
            OperatorMessageKind.DECISION,
            OperatorMessageKind.TASKING,
            OperatorMessageKind.ARTIFACT_REF,
            OperatorMessageKind.APPROVAL,
        }:
            return True
        if classification is OperatorMessageKind.NOTE:
            return True
        if classification is OperatorMessageKind.IDEA:
            return "validated" in lowered or "go" in lowered or "keep" in lowered
        if classification is OperatorMessageKind.CHAT and any(token in lowered for token in self._NOISE_HINTS):
            return False
        return False

    def _memory_type_for(self, classification: OperatorMessageKind) -> MemoryType:
        if classification in {OperatorMessageKind.DECISION, OperatorMessageKind.APPROVAL}:
            return MemoryType.PROCEDURAL
        if classification is OperatorMessageKind.NOTE:
            return MemoryType.SEMANTIC
        if classification in {OperatorMessageKind.ARTIFACT_REF, OperatorMessageKind.TASKING}:
            return MemoryType.EPISODIC
        return MemoryType.SEMANTIC

    def _tags_for(
        self,
        classification: OperatorMessageKind,
        attachments: list[OperatorAttachment],
        sensitivity: SensitivityClass,
    ) -> list[str]:
        tags = [classification.value, "discord_selective_sync", sensitivity.value]
        if attachments:
            tags.append("has_attachment")
        if sensitivity is not SensitivityClass.S1:
            tags.append("privacy_guard")
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
        return f"Pieces jointes referencees: {names}" if names else "Reference de piece jointe"

    @staticmethod
    def _clean_content_for(
        *,
        raw_text: str,
        attachment_names: Sequence[str],
        sensitivity: SensitivityClass,
        fallback: str | None,
    ) -> str | None:
        if raw_text:
            return fallback or raw_text
        return attachment_safe_summary(attachment_names, sensitivity=sensitivity)
