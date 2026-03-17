from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..database import CanonicalDatabase
from ..models import ChannelEvent, RetrievalContext, RoutingDecision, SensitivityClass
from ..memory.os_service import MemoryOSService
from ..session.state import PersistentSessionState, SessionSnapshot
from .handoff import HandoffContract


@dataclass(slots=True, frozen=True)
class MoodHint:
    mood: str
    guidance: str
    style_overrides: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ThreadTurn:
    role: str
    text: str
    created_at: str


@dataclass(slots=True, frozen=True)
class GatewayContextBundle:
    mood_hint: MoodHint
    session_brief: str
    handoff_contract: HandoffContract
    recent_thread_messages: tuple[ThreadTurn, ...] = ()
    recent_operator_replies: tuple[ThreadTurn, ...] = ()
    conversation_key: str | None = None
    thread_binding_id: str | None = None
    thread_binding_kind: str | None = None
    sensitivity: SensitivityClass = SensitivityClass.S1
    query_scope: str = "contextual"
    long_context_digest: dict[str, Any] | None = None
    long_context_brief: str = ""
    thread_ledger_summary: str = ""
    working_set_summary: str = ""
    pending_approvals_summary: str = ""
    project_continuity_summary: str = ""


class GatewayContextBuilder:
    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        session_state: PersistentSessionState,
        memory_os: MemoryOSService | None = None,
    ) -> None:
        self.database = database
        self.session_state = session_state
        self.memory_os = memory_os

    def build(
        self,
        *,
        event: ChannelEvent,
        envelope,
        candidate,
        decision: RoutingDecision,
        snapshot: SessionSnapshot,
        mission_run_id: str | None,
    ) -> GatewayContextBundle:
        raw_user_intent = str(envelope.metadata.get("raw_operator_text") or event.message.text).strip()
        conversation_key = str(event.message.thread_ref.external_thread_id or event.message.thread_ref.thread_id or "").strip() or None
        sensitivity = self._candidate_sensitivity(candidate)
        mood_hint = self._classify_mood(raw_user_intent)
        query_scope = self._classify_query_scope(raw_user_intent)
        include_deep_context = query_scope not in {"identity", "runtime_truth"}
        session_brief = self.session_state.build_context_brief(snapshot=snapshot) if include_deep_context else ""
        recent_thread_messages = (
            self._load_recent_thread_messages(
                surface=event.surface,
                channel=event.message.channel,
                conversation_key=conversation_key,
                exclude_event_id=event.event_id,
                limit=3,
            )
            if include_deep_context
            else ()
        )
        recent_operator_replies = (
            self._load_recent_operator_replies(
                surface=event.surface,
                channel=event.message.channel,
                conversation_key=conversation_key,
                exclude_event_id=event.event_id,
                limit=2,
            )
            if include_deep_context
            else ()
        )
        binding = self._load_thread_binding(
            surface=event.surface,
            channel=event.message.channel,
            conversation_key=conversation_key,
        )
        handoff_contract = HandoffContract(
            version="v1",
            task_id=mission_run_id or (binding or {}).get("mission_run_id") or decision.decision_id,
            source_model="project_os_gateway",
            target_model=decision.model_route.model or decision.model_route.provider,
            raw_user_intent=raw_user_intent,
            decisions_taken=self._decisions_taken(envelope=envelope, candidate=candidate, decision=decision, binding=binding),
            pending_questions=self._pending_questions(snapshot=snapshot, include_deep_context=include_deep_context),
            context_snapshot=self._context_snapshot(
                snapshot=snapshot,
                recent_thread_messages=recent_thread_messages,
                recent_operator_replies=recent_operator_replies,
                query_scope=query_scope,
                include_deep_context=include_deep_context,
            ),
            style_overrides=dict(mood_hint.style_overrides),
            reason=decision.route_reason,
        )
        long_context_digest = candidate.metadata.get("long_context_digest")
        if not isinstance(long_context_digest, dict):
            long_context_digest = None
        project_continuity_summary = (
            self._build_project_continuity_summary(
                event=event,
                envelope=envelope,
                candidate=candidate,
                decision=decision,
                snapshot=snapshot,
                conversation_key=conversation_key,
            )
            if include_deep_context
            else ""
        )
        return GatewayContextBundle(
            mood_hint=mood_hint,
            session_brief=session_brief,
            handoff_contract=handoff_contract,
            recent_thread_messages=recent_thread_messages,
            recent_operator_replies=recent_operator_replies,
            conversation_key=conversation_key,
            thread_binding_id=(binding or {}).get("binding_id"),
            thread_binding_kind=(binding or {}).get("binding_kind"),
            sensitivity=sensitivity,
            query_scope=query_scope,
            long_context_digest=long_context_digest,
            long_context_brief=self._render_long_context_brief(long_context_digest),
            thread_ledger_summary=self._render_thread_ledger_summary(candidate),
            working_set_summary=self._render_working_set_summary(candidate),
            pending_approvals_summary=self._render_pending_approvals_summary(candidate),
            project_continuity_summary=project_continuity_summary,
        )

    def _build_project_continuity_summary(
        self,
        *,
        event: ChannelEvent,
        envelope,
        candidate,
        decision: RoutingDecision,
        snapshot: SessionSnapshot,
        conversation_key: str | None,
    ) -> str:
        if self.memory_os is None:
            return ""
        retrieval_context = RetrievalContext(
            query=str(envelope.metadata.get("raw_operator_text") or event.message.text).strip(),
            user_id=str(event.message.actor_id or "founder"),
            branch_name=self._active_branch_name(snapshot),
            target_profile=str(envelope.target_profile or "").strip() or None,
            requested_worker=str(envelope.requested_worker or decision.chosen_worker or "").strip() or None,
            channel=event.message.channel,
            surface=event.surface,
            thread_id=event.message.thread_ref.thread_id,
            external_thread_id=event.message.thread_ref.external_thread_id,
            conversation_key=conversation_key,
            tags=[str(candidate.metadata.get("input_profile") or "").strip()],
            limit=5,
            include_private_full=False,
            metadata={"channel_event_id": event.event_id},
        )
        continuity = self.memory_os.build_project_continuity_brief(context=retrieval_context)
        return str(continuity.get("summary") or "").strip()

    @staticmethod
    def _render_thread_ledger_summary(candidate) -> str:
        lines: list[str] = []
        active_subject = str(candidate.metadata.get("thread_active_subject") or "").strip()
        last_reply = str(candidate.metadata.get("thread_last_reply_summary") or "").strip()
        last_pdf = str(candidate.metadata.get("thread_last_pdf_artifact_id") or "").strip()
        last_artifact = str(candidate.metadata.get("thread_last_artifact_id") or "").strip()
        next_step = str(candidate.metadata.get("thread_next_step") or "").strip()
        recent_decisions = candidate.metadata.get("thread_recent_decisions") or []
        mode = str(candidate.metadata.get("thread_mode") or "").strip()
        if active_subject:
            lines.append(f"- sujet actif: {GatewayContextBuilder._trim(active_subject, limit=180)}")
        if last_reply:
            lines.append(f"- derniere reponse autoritative: {GatewayContextBuilder._trim(last_reply, limit=180)}")
        if isinstance(recent_decisions, list):
            cleaned_decisions = [GatewayContextBuilder._trim(str(item).strip(), limit=160) for item in recent_decisions if str(item).strip()]
            for decision in cleaned_decisions[:3]:
                lines.append(f"- decision recente: {decision}")
        if next_step:
            lines.append(f"- prochain pas proche: {GatewayContextBuilder._trim(next_step, limit=160)}")
        if last_pdf:
            lines.append(f"- dernier pdf connu: {last_pdf}")
        if last_artifact and last_artifact != last_pdf:
            lines.append(f"- dernier artefact connu: {last_artifact}")
        if mode:
            lines.append(f"- mode courant: {mode}")
        return "\n".join(lines)

    @staticmethod
    def _render_pending_approvals_summary(candidate) -> str:
        approval_ids = candidate.metadata.get("thread_pending_approval_ids") or []
        if not isinstance(approval_ids, list) or not approval_ids:
            return ""
        cleaned = [str(item).strip() for item in approval_ids if str(item).strip()]
        if not cleaned:
            return ""
        return "\n".join(f"- {item}" for item in cleaned[:4])

    @staticmethod
    def _render_working_set_summary(candidate) -> str:
        summary = str(candidate.metadata.get("working_set_summary") or "").strip()
        raw_digests = candidate.metadata.get("working_set_object_digests")
        if not isinstance(raw_digests, list) or not raw_digests:
            return summary
        lines: list[str] = []
        if summary:
            lines.append(summary)
        lines.append("Digests:")
        for item in raw_digests[:6]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("object_type") or "objet").strip()
            summary_short = GatewayContextBuilder._trim(str(item.get("summary_short") or "").strip(), limit=120)
            digest_line = f"- {title}"
            if summary_short:
                digest_line = f"{digest_line}: {summary_short}"
            decisions = item.get("decisions") if isinstance(item.get("decisions"), list) else []
            questions = item.get("questions") if isinstance(item.get("questions"), list) else []
            if decisions:
                digest_line = f"{digest_line} | decisions: {'; '.join(str(part) for part in decisions[:2])}"
            elif questions:
                digest_line = f"{digest_line} | questions: {'; '.join(str(part) for part in questions[:2])}"
            lines.append(digest_line)
        return "\n".join(lines).strip()

    @staticmethod
    def _candidate_sensitivity(candidate) -> SensitivityClass:
        raw = str(candidate.metadata.get("sensitivity_class") or "").strip().lower()
        try:
            return SensitivityClass(raw)
        except Exception:
            return SensitivityClass.S1

    def _load_recent_thread_messages(
        self,
        *,
        surface: str,
        channel: str,
        conversation_key: str | None,
        exclude_event_id: str,
        limit: int,
    ) -> tuple[ThreadTurn, ...]:
        if not conversation_key:
            return ()
        rows = self.database.fetchall(
            """
            SELECT actor_id, message_json, created_at
            FROM channel_events
            WHERE surface = ?
              AND channel = ?
              AND conversation_key = ?
              AND event_id != ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (surface, channel, conversation_key, exclude_event_id, limit),
        )
        turns: list[ThreadTurn] = []
        for row in reversed(rows):
            try:
                message = json.loads(row["message_json"]) if row["message_json"] else {}
            except Exception:
                message = {}
            text = self._trim(str(message.get("text") or "").strip())
            if not text:
                continue
            role = "founder" if str(row["actor_id"]).strip().lower() == "founder" else "participant"
            turns.append(ThreadTurn(role=role, text=text, created_at=str(row["created_at"])))
        return tuple(turns)

    def _load_recent_operator_replies(
        self,
        *,
        surface: str,
        channel: str,
        conversation_key: str | None,
        exclude_event_id: str,
        limit: int,
    ) -> tuple[ThreadTurn, ...]:
        if not conversation_key:
            return ()
        rows = self.database.fetchall(
            """
            SELECT g.reply_json, g.created_at
            FROM gateway_dispatch_results AS g
            JOIN channel_events AS c ON c.event_id = g.channel_event_id
            WHERE c.surface = ?
              AND c.channel = ?
              AND c.conversation_key = ?
              AND c.event_id != ?
            ORDER BY g.created_at DESC
            LIMIT ?
            """,
            (surface, channel, conversation_key, exclude_event_id, limit),
        )
        turns: list[ThreadTurn] = []
        for row in reversed(rows):
            try:
                reply = json.loads(row["reply_json"]) if row["reply_json"] else {}
            except Exception:
                reply = {}
            text = self._render_recent_operator_reply_text(reply)
            if not text:
                continue
            turns.append(ThreadTurn(role="project_os", text=text, created_at=str(row["created_at"])))
        return tuple(turns)

    @staticmethod
    def _active_branch_name(snapshot: SessionSnapshot) -> str | None:
        for collection in (snapshot.pending_contracts, snapshot.active_runs, snapshot.active_missions):
            for item in collection:
                branch_name = str(item.get("branch_name") or "").strip()
                if branch_name:
                    return branch_name
        return None

    @classmethod
    def _render_recent_operator_reply_text(cls, reply: dict[str, Any]) -> str:
        summary = str(reply.get("summary") or "").strip()
        manifest = reply.get("response_manifest") if isinstance(reply.get("response_manifest"), dict) else {}
        delivery_mode = str(manifest.get("delivery_mode") or "").strip().lower() if isinstance(manifest, dict) else ""
        attachments_raw = manifest.get("attachments") if isinstance(manifest.get("attachments"), list) else []
        attachment_labels: list[str] = []
        for item in attachments_raw:
            if not isinstance(item, dict):
                continue
            mime_type = str(item.get("mime_type") or "").strip().lower()
            name = str(item.get("name") or "").strip()
            if mime_type == "application/pdf" or name.lower().endswith(".pdf"):
                attachment_labels.append(f"PDF joint ({name})" if name else "PDF joint")
                break
        if delivery_mode == "artifact_summary" and not attachment_labels:
            attachment_labels.append("artefact joint")
        if attachment_labels:
            suffix = "; ".join(attachment_labels[:2])
            if summary:
                return cls._trim(f"{summary} [{suffix}]")
            return cls._trim(suffix)
        return cls._trim(summary)

    def _load_thread_binding(self, *, surface: str, channel: str, conversation_key: str | None) -> dict[str, Any] | None:
        if not conversation_key:
            return None
        row = self.database.fetchone(
            """
            SELECT binding_id, binding_kind, mission_run_id
            FROM discord_thread_bindings
            WHERE surface = ?
              AND channel = ?
              AND (external_thread_id = ? OR thread_id = ?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (surface, channel, conversation_key, conversation_key),
        )
        if row is None:
            return None
        return {
            "binding_id": str(row["binding_id"]),
            "binding_kind": str(row["binding_kind"]),
            "mission_run_id": str(row["mission_run_id"]) if row["mission_run_id"] else None,
        }

    def _context_snapshot(
        self,
        *,
        snapshot: SessionSnapshot,
        recent_thread_messages: tuple[ThreadTurn, ...],
        recent_operator_replies: tuple[ThreadTurn, ...],
        query_scope: str,
        include_deep_context: bool,
    ) -> str:
        if not include_deep_context:
            return (
                f"scope={query_scope}; "
                f"last_founder_message_at={snapshot.last_founder_message_at or 'none'}"
            )
        founder_tail = recent_thread_messages[-1].text if recent_thread_messages else "none"
        operator_tail = recent_operator_replies[-1].text if recent_operator_replies else "none"
        return (
            f"active_runs={len(snapshot.active_runs)}; "
            f"pending_clarifications={len(snapshot.pending_clarifications)}; "
            f"pending_contracts={len(snapshot.pending_contracts)}; "
            f"pending_approvals={len(snapshot.pending_approvals)}; "
            f"active_missions={len(snapshot.active_missions)}; "
            f"last_founder_message_at={snapshot.last_founder_message_at or 'none'}; "
            f"thread_tail_founder={self._trim(founder_tail, limit=120)}; "
            f"thread_tail_operator={self._trim(operator_tail, limit=120)}"
        )

    def _decisions_taken(self, *, envelope, candidate, decision: RoutingDecision, binding: dict[str, Any] | None) -> list[str]:
        decisions = [
            f"route_reason={decision.route_reason}",
            f"communication_mode={decision.communication_mode.value}",
            f"sensitivity_class={candidate.metadata.get('sensitivity_class', SensitivityClass.S1.value)}",
        ]
        requested_model_mode = str(envelope.metadata.get("requested_model_mode") or "").strip()
        if requested_model_mode:
            decisions.append(f"requested_model_mode={requested_model_mode}")
        if binding and binding.get("binding_kind"):
            decisions.append(f"thread_binding_kind={binding['binding_kind']}")
        return decisions

    @staticmethod
    def _pending_questions(*, snapshot: SessionSnapshot, include_deep_context: bool) -> list[str]:
        if not include_deep_context:
            return []
        return [
            str(item.get("question") or "").strip()
            for item in snapshot.pending_clarifications[:2]
            if str(item.get("question") or "").strip()
        ]

    @staticmethod
    def _classify_query_scope(message: str) -> str:
        normalized = GatewayContextBuilder._normalize_scope_text(message)
        if normalized.startswith("test "):
            normalized = normalized[5:].strip()
        identity_patterns = {
            "qui est tu",
            "qui es tu",
            "tu es qui",
            "t es qui",
            "quel est ton role",
            "c est quoi ton role",
        }
        if normalized in identity_patterns:
            return "identity"
        runtime_truth_patterns = (
            "quelle api",
            "quel api",
            "quel modele",
            "quel model",
            "quel provider",
            "quelle provider",
            "sur quel modele",
            "sur quelle api",
            "tu utilises quel",
            "tu utilises quoi",
        )
        runtime_truth_blockers = (
            "bug",
            "beug",
            "probleme",
            "connexion",
            "connect",
            "inspect",
            "regarde",
            "analyse",
            "audit",
            "log",
            "config",
            "fichier",
            "etat",
            "pourquoi",
        )
        if any(pattern in normalized for pattern in runtime_truth_patterns) and not any(
            blocker in normalized for blocker in runtime_truth_blockers
        ):
            return "runtime_truth"
        return "contextual"

    @staticmethod
    def _normalize_scope_text(text: str) -> str:
        lowered = text.strip().lower().replace("'", " ").replace("’", " ")
        normalized = unicodedata.normalize("NFKD", lowered)
        ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
        cleaned = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _classify_mood(message: str) -> MoodHint:
        lowered = message.lower()
        if any(token in lowered for token in ("ca marche pas", "ça marche pas", "fais chier", "saoule", "ras le bol")):
            return MoodHint(
                mood="frustrated",
                guidance="Reste calme, plus chaleureux, coupe le bruit et propose un diagnostic net.",
                style_overrides={"warmth": 1, "directness": 1, "challenge_level": -1},
            )
        if any(token in lowered for token in ("urgent", "vite", "asap", "bloque", "bloqué", "critique", "immediat", "immédiat")):
            return MoodHint(
                mood="urgent",
                guidance="Va droit au but, priorise le risque et le prochain pas.",
                style_overrides={"directness": 1, "seriousness": 2, "operator_clarity": 1},
            )
        if any(token in lowered for token in ("idee", "idée", "brainstorm", "option", "architecture", "plan", "naming", "et si")):
            return MoodHint(
                mood="brainstorming",
                guidance="Ouvre un peu le champ mais garde un cadre net et des compromis explicites.",
                style_overrides={"challenge_level": 1, "warmth": 1, "humor_tolerance": 1},
            )
        if any(token in lowered for token in ("lol", "mdr", "haha", "blague", "😂")):
            return MoodHint(
                mood="casual",
                guidance="Tu peux relacher legerement sans quitter le cadre de travail.",
                style_overrides={"warmth": 1, "humor_tolerance": 2},
            )
        if any(token in lowered for token in ("serieux", "sérieux", "risque", "secret", "prod", "important", "audit")):
            return MoodHint(
                mood="serious",
                guidance="Reste tres net, factuel et sobre.",
                style_overrides={"seriousness": 2, "operator_clarity": 1, "humor_tolerance": -1},
            )
        return MoodHint(
            mood="focused",
            guidance="Reste direct, utile et propre.",
            style_overrides={},
        )

    @staticmethod
    def _trim(text: str, *, limit: int = 220) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    @classmethod
    def _render_long_context_brief(cls, digest: dict[str, Any] | None) -> str:
        if not digest:
            return ""
        lines: list[str] = []
        summary = str(digest.get("summary") or "").strip()
        if summary:
            lines.append(f"- summary: {cls._trim(summary, limit=280)}")
        input_profile = str(digest.get("input_profile") or "").strip()
        if input_profile:
            lines.append(f"- input_profile: {input_profile}")
        segment_count = digest.get("segment_count")
        if segment_count not in (None, ""):
            lines.append(f"- segment_count: {segment_count}")
        artifact_ids = digest.get("artifact_ids") or []
        if artifact_ids:
            lines.append(f"- artifact_ids: {', '.join(str(item) for item in artifact_ids[:4])}")
        for label, key in (("decisions", "decisions"), ("actions", "actions"), ("questions", "questions")):
            values = digest.get(key) or []
            if values:
                trimmed = [cls._trim(str(item), limit=160) for item in list(values)[:3]]
                lines.append(f"- {label}: {' | '.join(trimmed)}")
        segment_summaries = digest.get("hierarchical_summary") or []
        if segment_summaries:
            lines.append("- segment_summaries:")
            for item in list(segment_summaries)[:3]:
                lines.append(f"  - {cls._trim(str(item), limit=160)}")
        return "\n".join(lines)
