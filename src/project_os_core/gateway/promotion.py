from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from typing import Sequence

from ..models import (
    ChannelEvent,
    ConversationMemoryCandidate,
    DelegationLevel,
    HumanArtifact,
    InteractionState,
    IntentKind,
    IntentTaxonomyResult,
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

    _LONG_TEXT_THRESHOLD = 1200
    _VERY_LONG_TEXT_THRESHOLD = 4000
    _ATTACHMENT_HEAVY_THRESHOLD = 2
    _DECISION_HINTS = ("decision", "decide", "on valide", "go ", "go:", "we keep", "keep ")
    _IDEA_HINTS = ("idea", "on pourrait", "maybe", "perhaps", "on devrait", "we could")
    _NOTE_HINTS = ("note", "remember", "memo", "preference", "prefer", "always", "never", "by default")
    _TASK_PREFIX_HINTS = (
        "please ",
        "fais ",
        "implement ",
        "build ",
        "create ",
        "write ",
        "route ",
        "run ",
        "launch ",
        "ouvre ",
        "supprime ",
        "delete ",
        "remove ",
        "efface ",
    )
    _DIRECTIVE_DELEGATION_HINTS = (
        "tu peux me ",
        "tu peux nous ",
        "tu peux ",
        "j aimerais qu on ",
        "j aimerais que tu ",
        "j aimerais ",
        "garde une trace",
        "garde ca",
        "mets moi ",
        "mets nous ",
        "mets ca propre",
        "prepare moi",
        "prepare nous",
        "prepare un",
        "prepare une",
        "pose un fichier",
        "pose moi",
        "on part la dessus",
        "on part la dessus",
        "lance proprement",
    )
    _DIRECTIVE_OUTPUT_HINTS = (
        "fichier",
        "file",
        "md",
        "markdown",
        "doc",
        "document",
        "note",
        "trace",
        "plan",
        "roadmap",
        "spec",
        "brief",
        "liste",
        "tableau",
        "rapport",
        "resume",
        "synthese",
    )
    _DIRECTIVE_TARGET_HINTS = (
        "repo",
        "branche",
        "docs",
        "readme",
        "worker",
        "windows",
        "browser",
        "uefn",
        "discord",
        "runtime",
        "projet",
        "thread",
    )
    _DIRECTIVE_DISCUSSION_HINTS = (
        "rappelle",
        "explique",
        "dis moi",
        "pourquoi",
        "comment",
        "blague",
        "qui est tu",
        "qui es tu",
        "quelle api",
        "quel modele",
    )
    _PREPARE_HINTS = (
        "plan",
        "roadmap",
        "spec",
        "markdown",
        " md ",
        "doc",
        "document",
        "trace",
        "resume",
        "audit",
        "brief",
    )
    _EXECUTE_HINTS = (
        "cree ",
        "creer ",
        "create ",
        "ecris ",
        "write ",
        "build ",
        "implement ",
        "ajoute ",
        "fais ",
        "fichier ",
        "file ",
        "pose ",
        "poser ",
        "mets ",
        "lance ",
        "route ",
        "run ",
        "supprime ",
        "delete ",
        "remove ",
        "efface ",
    )
    _STATUS_HINTS = ("status", "statut", "ou en est", "progress", "ca en est ou")
    _APPROVAL_HINTS = ("approve", "approval", "validation", "valide", "approuve", "autorise")
    _REPORT_FOLLOWUP_HINTS = (
        "c est fait",
        "ca a donne quoi",
        "qu est ce qui a ete fait",
        "qu as tu fait",
        "tu as fait quoi",
        "resultat",
        "livrable",
    )
    _NOISE_HINTS = ("salut", "hello", "hi", "yo", "ca va", "merci", "thanks")
    _CONVERSATIONAL_QUESTION_HINTS = (
        "qui est tu",
        "qui es tu",
        "quelle api",
        "quel api",
        "quel modele",
        "quel model",
        "rappelle moi",
        "petite blague",
        "si je dis",
        "tu fais quoi",
        "est ce que tu peux",
        "peux tu",
    )

    def classify_message(self, event: ChannelEvent) -> OperatorMessageKind:
        taxonomy = self.analyze_intent(event)
        text = event.message.text.strip()
        normalized = self._normalize_text(text)
        if event.message.attachments and not normalized:
            return OperatorMessageKind.ARTIFACT_REF
        if taxonomy.intent_kind is IntentKind.STATUS_REQUEST:
            return OperatorMessageKind.STATUS_REQUEST
        if taxonomy.intent_kind is IntentKind.EXECUTION_REPORT_FOLLOWUP:
            return OperatorMessageKind.STATUS_REQUEST
        if taxonomy.intent_kind is IntentKind.APPROVAL_RESPONSE:
            return OperatorMessageKind.APPROVAL
        if taxonomy.intent_kind is IntentKind.DECISION_SIGNAL:
            return OperatorMessageKind.DECISION
        if taxonomy.intent_kind in {IntentKind.DIRECTIVE_IMPLICIT, IntentKind.DIRECTIVE_EXPLICIT}:
            return OperatorMessageKind.TASKING
        if self._contains_any(normalized, self._IDEA_HINTS):
            return OperatorMessageKind.IDEA
        if self._contains_any(normalized, self._NOTE_HINTS):
            return OperatorMessageKind.NOTE
        if event.message.attachments:
            return OperatorMessageKind.ARTIFACT_REF
        return OperatorMessageKind.CHAT

    def analyze_intent(self, event: ChannelEvent) -> IntentTaxonomyResult:
        text = event.message.text.strip()
        normalized = self._normalize_text(text)
        directive_detection = self._directive_detection(normalized)
        signals: list[str] = []

        if event.message.attachments and not normalized:
            return IntentTaxonomyResult(
                intent_kind=IntentKind.DISCUSSION,
                delegation_level=DelegationLevel.NONE,
                interaction_state=InteractionState.REPORTING,
                suggested_next_state=InteractionState.REPORTING,
                confidence=0.55,
                signals=["attachment_only"],
            )
        if self._contains_any(normalized, self._STATUS_HINTS):
            return IntentTaxonomyResult(
                intent_kind=IntentKind.STATUS_REQUEST,
                delegation_level=DelegationLevel.NONE,
                interaction_state=InteractionState.REPORTING,
                suggested_next_state=InteractionState.REPORTING,
                confidence=0.98,
                signals=["status_request"],
            )
        if self._contains_any(normalized, self._REPORT_FOLLOWUP_HINTS):
            return IntentTaxonomyResult(
                intent_kind=IntentKind.EXECUTION_REPORT_FOLLOWUP,
                delegation_level=DelegationLevel.NONE,
                interaction_state=InteractionState.REPORTING,
                suggested_next_state=InteractionState.REPORTING,
                confidence=0.8,
                signals=["report_followup"],
            )
        if self._contains_any(normalized, self._APPROVAL_HINTS):
            return IntentTaxonomyResult(
                intent_kind=IntentKind.APPROVAL_RESPONSE,
                delegation_level=DelegationLevel.APPROVE,
                interaction_state=InteractionState.APPROVAL,
                suggested_next_state=InteractionState.EXECUTION,
                confidence=0.92,
                signals=["approval_response"],
            )
        if directive_detection["directive_form"] == "explicit":
            signals.extend(str(item) for item in directive_detection["signals"])
            delegation_level = self._delegation_level_for(normalized, intent_kind=IntentKind.DIRECTIVE_EXPLICIT)
            return IntentTaxonomyResult(
                intent_kind=IntentKind.DIRECTIVE_EXPLICIT,
                delegation_level=delegation_level,
                interaction_state=InteractionState.DIRECTIVE,
                suggested_next_state=InteractionState.EXECUTION,
                confidence=float(directive_detection["confidence"]),
                signals=signals,
            )
        if directive_detection["directive_form"] == "implicit":
            signals.extend(str(item) for item in directive_detection["signals"])
            delegation_level = self._delegation_level_for(normalized, intent_kind=IntentKind.DIRECTIVE_IMPLICIT)
            return IntentTaxonomyResult(
                intent_kind=IntentKind.DIRECTIVE_IMPLICIT,
                delegation_level=delegation_level,
                interaction_state=InteractionState.DIRECTIVE,
                suggested_next_state=InteractionState.EXECUTION,
                confidence=float(directive_detection["confidence"]),
                signals=signals,
            )
        if self._contains_any(normalized, self._DECISION_HINTS):
            return IntentTaxonomyResult(
                intent_kind=IntentKind.DECISION_SIGNAL,
                delegation_level=DelegationLevel.NONE,
                interaction_state=InteractionState.DISCUSSION,
                suggested_next_state=InteractionState.DISCUSSION,
                confidence=0.84,
                signals=["decision_signal"],
            )
        if self._contains_any(normalized, self._IDEA_HINTS):
            return IntentTaxonomyResult(
                intent_kind=IntentKind.DISCUSSION,
                delegation_level=DelegationLevel.EXPLORE,
                interaction_state=InteractionState.DISCUSSION,
                suggested_next_state=InteractionState.DISCUSSION,
                confidence=0.72,
                signals=["idea_signal"],
            )
        if self._contains_any(normalized, self._NOTE_HINTS):
            return IntentTaxonomyResult(
                intent_kind=IntentKind.DISCUSSION,
                delegation_level=DelegationLevel.NONE,
                interaction_state=InteractionState.DISCUSSION,
                suggested_next_state=InteractionState.DISCUSSION,
                confidence=0.7,
                signals=["note_signal"],
            )
        if self._is_conversational_question(normalized):
            return IntentTaxonomyResult(
                intent_kind=IntentKind.DISCUSSION,
                delegation_level=DelegationLevel.NONE,
                interaction_state=InteractionState.DISCUSSION,
                suggested_next_state=InteractionState.DISCUSSION,
                confidence=0.95,
                signals=["conversational_question"],
            )
        return IntentTaxonomyResult(
            intent_kind=IntentKind.DISCUSSION,
            delegation_level=DelegationLevel.NONE,
            interaction_state=InteractionState.DISCUSSION,
            suggested_next_state=InteractionState.DISCUSSION,
            confidence=0.6,
            signals=["default_discussion"],
        )

    @classmethod
    def _is_conversational_question(cls, text: str) -> bool:
        if not text:
            return False
        if any(text.startswith(prefix) for prefix in cls._CONVERSATIONAL_QUESTION_HINTS):
            return True
        return text.startswith(("qui ", "quelle ", "quel ", "pourquoi ", "comment ", "si "))

    @classmethod
    def _is_tasking(cls, text: str) -> bool:
        if not text:
            return False
        return any(text.startswith(prefix) for prefix in cls._TASK_PREFIX_HINTS)

    @staticmethod
    def _contains_any(text: str, patterns: Sequence[str]) -> bool:
        return any(pattern in text for pattern in patterns)

    @staticmethod
    def _matched_patterns(text: str, patterns: Sequence[str], *, startswith_only: bool = False) -> list[str]:
        if startswith_only:
            return [pattern.strip() for pattern in patterns if text.startswith(pattern)]
        return [pattern.strip() for pattern in patterns if pattern in text]

    def _directive_detection(self, text: str) -> dict[str, object]:
        if not text:
            return {
                "likely_directive": False,
                "directive_form": "none",
                "confidence": 0.0,
                "score": 0,
                "strength": "none",
                "signals": [],
                "question_form": False,
                "capability_query": False,
                "blocked_reason": "empty_text",
                "explicit_prefix_hits": [],
                "delegation_hits": [],
                "prepare_hits": [],
                "execute_hits": [],
                "output_hits": [],
                "target_hits": [],
                "discussion_hits": [],
            }

        explicit_prefix_hits = self._matched_patterns(text, self._TASK_PREFIX_HINTS, startswith_only=True)
        delegation_hits = self._matched_patterns(text, self._DIRECTIVE_DELEGATION_HINTS)
        prepare_hits = self._matched_patterns(text, self._PREPARE_HINTS)
        execute_hits = self._matched_patterns(text, self._EXECUTE_HINTS)
        output_hits = self._matched_patterns(text, self._DIRECTIVE_OUTPUT_HINTS)
        target_hits = self._matched_patterns(text, self._DIRECTIVE_TARGET_HINTS)
        discussion_hits = self._matched_patterns(text, self._DIRECTIVE_DISCUSSION_HINTS)
        question_form = text.endswith("?") or text.startswith(("est ce ", "peux tu ", "tu peux "))
        capability_query = bool(question_form and not output_hits and not explicit_prefix_hits and text.startswith(("est ce ", "peux tu ", "tu peux ")))

        score = 0
        score += len(explicit_prefix_hits) * 5
        score += len(delegation_hits) * 2
        score += len(prepare_hits) * 2
        score += len(execute_hits) * 3
        score += len(output_hits) * 2
        score += len(target_hits)
        if discussion_hits and not output_hits and not target_hits:
            score -= 3
        if capability_query and not output_hits:
            score -= 4

        likely_directive = False
        directive_form = "none"
        blocked_reason: str | None = None
        signals: list[str] = []

        if explicit_prefix_hits:
            likely_directive = True
            directive_form = "explicit"
            signals.append("directive_explicit")
        elif score >= 5 and (delegation_hits or output_hits or target_hits or execute_hits or prepare_hits):
            if capability_query and not output_hits:
                blocked_reason = "capability_query_without_deliverable"
            else:
                likely_directive = True
                directive_form = "implicit"
                signals.append("directive_implicit")
        elif capability_query:
            blocked_reason = "capability_query_without_deliverable"
        elif discussion_hits and not output_hits and not target_hits:
            blocked_reason = "discussion_request_without_deliverable"

        if explicit_prefix_hits:
            strength = "strong"
        elif score >= 8:
            strength = "strong"
        elif score >= 5:
            strength = "medium"
        elif score >= 2:
            strength = "weak"
        else:
            strength = "none"

        if delegation_hits:
            signals.append("delegation_phrase")
        if output_hits:
            signals.append("deliverable_hint")
        if target_hits:
            signals.append("target_hint")
        if execute_hits:
            signals.append("execute_hint")
        if prepare_hits and not execute_hits:
            signals.append("prepare_hint")

        confidence = 0.98 if directive_form == "explicit" else 0.82 if directive_form == "implicit" and strength == "strong" else 0.74 if directive_form == "implicit" else 0.22

        return {
            "likely_directive": likely_directive,
            "directive_form": directive_form,
            "confidence": confidence,
            "score": score,
            "strength": strength,
            "signals": signals,
            "question_form": question_form,
            "capability_query": capability_query,
            "blocked_reason": blocked_reason,
            "explicit_prefix_hits": explicit_prefix_hits,
            "delegation_hits": delegation_hits,
            "prepare_hits": prepare_hits,
            "execute_hits": execute_hits,
            "output_hits": output_hits,
            "target_hits": target_hits,
            "discussion_hits": discussion_hits,
        }

    @staticmethod
    def _normalize_text(text: str) -> str:
        lowered = text.strip().lower().replace("'", " ").replace("’", " ")
        normalized = unicodedata.normalize("NFKD", lowered)
        ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
        cleaned = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
        return re.sub(r"\s+", " ", cleaned).strip()

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
        taxonomy = self.analyze_intent(event)
        classification = self.classify_message(event)
        raw_text = event.message.text.strip()
        normalized_text = self._normalize_text(raw_text)
        directive_detection = self._directive_detection(normalized_text)
        input_profile = self._input_profile_for(raw_text, event.message.attachments)
        attachment_names = [attachment.name for attachment in event.message.attachments]
        sensitivity = assess_sensitivity(raw_text, attachment_names=attachment_names)
        summary = self._summarize(raw_text, classification, event.message.attachments)
        should_promote = self._should_promote(classification, event.message.text) or sensitivity.classification is not SensitivityClass.S1
        tags = self._tags_for(classification, event.message.attachments, sensitivity.classification, input_profile)
        tags.extend(
            [
                f"intent:{taxonomy.intent_kind.value}",
                f"delegation:{taxonomy.delegation_level.value}",
                f"state:{taxonomy.interaction_state.value}",
                f"next:{taxonomy.suggested_next_state.value}",
            ]
        )
        tier = MemoryTier.WARM if should_promote else MemoryTier.HOT
        clean_content = self._clean_content_for(
            raw_text=raw_text,
            attachment_names=attachment_names,
            sensitivity=sensitivity.classification,
            fallback=sensitivity.clean_text,
        )
        requires_ingress_artifact = input_profile != "short_text" or bool(event.message.attachments)
        requires_long_context_pipeline = input_profile in {"long_text", "very_long_text", "transcript", "document", "attachment_heavy"}
        metadata = {
            "channel": event.message.channel,
            "surface": event.surface,
            "attachments": attachment_names,
            "thread_ref": event.message.thread_ref.external_thread_id or event.message.thread_ref.thread_id,
            "input_profile": input_profile,
            "input_char_count": len(raw_text),
            "attachment_count": len(event.message.attachments),
            "intent_kind": taxonomy.intent_kind.value,
            "delegation_level": taxonomy.delegation_level.value,
            "interaction_state": taxonomy.interaction_state.value,
            "suggested_next_state": taxonomy.suggested_next_state.value,
            "intent_confidence": taxonomy.confidence,
            "intent_signals": list(taxonomy.signals),
            "state_transition": f"{taxonomy.interaction_state.value}->{taxonomy.suggested_next_state.value}",
            "directive_detection": directive_detection,
            "requires_ingress_artifact": requires_ingress_artifact,
            "requires_long_context_pipeline": requires_long_context_pipeline,
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
        input_profile: str,
    ) -> list[str]:
        tags = [classification.value, "discord_selective_sync", sensitivity.value, f"input:{input_profile}"]
        if attachments:
            tags.append("has_attachment")
        if sensitivity is not SensitivityClass.S1:
            tags.append("privacy_guard")
        return tags

    @classmethod
    def _delegation_level_for(cls, text: str, *, intent_kind: IntentKind) -> DelegationLevel:
        if intent_kind is IntentKind.APPROVAL_RESPONSE:
            return DelegationLevel.APPROVE
        if intent_kind is IntentKind.DISCUSSION:
            if cls._contains_any(text, cls._IDEA_HINTS):
                return DelegationLevel.EXPLORE
            return DelegationLevel.NONE
        if intent_kind in {IntentKind.DIRECTIVE_IMPLICIT, IntentKind.DIRECTIVE_EXPLICIT}:
            if cls._contains_any(text, cls._EXECUTE_HINTS):
                return DelegationLevel.EXECUTE
            if cls._contains_any(text, cls._PREPARE_HINTS):
                return DelegationLevel.PREPARE
            return DelegationLevel.PREPARE
        return DelegationLevel.NONE

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

    @classmethod
    def _input_profile_for(cls, text: str, attachments: list[OperatorAttachment]) -> str:
        char_count = len(text)
        if any(cls._is_transcript_attachment(item) for item in attachments):
            return "transcript"
        if any(cls._is_document_attachment(item) for item in attachments):
            return "document"
        if len(attachments) >= cls._ATTACHMENT_HEAVY_THRESHOLD:
            return "attachment_heavy"
        if char_count >= cls._VERY_LONG_TEXT_THRESHOLD:
            return "very_long_text"
        if char_count >= cls._LONG_TEXT_THRESHOLD:
            return "long_text"
        if attachments:
            return "attachment_ref"
        return "short_text"

    @staticmethod
    def _is_transcript_attachment(attachment: OperatorAttachment) -> bool:
        name = attachment.name.lower()
        mime = (attachment.mime_type or "").lower()
        metadata = attachment.metadata or {}
        if bool(metadata.get("is_transcript")) or bool(metadata.get("has_transcript")):
            return True
        if mime.startswith("audio/"):
            return True
        return any(token in name for token in ("transcript", "meeting-notes", "voice-note", "voice_note", "audio-note"))

    @staticmethod
    def _is_document_attachment(attachment: OperatorAttachment) -> bool:
        name = attachment.name.lower()
        mime = (attachment.mime_type or "").lower()
        if mime in {
            "application/pdf",
            "text/markdown",
            "text/plain",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }:
            return True
        return name.endswith((".pdf", ".md", ".txt", ".doc", ".docx"))
