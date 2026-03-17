from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from ..artifacts import write_binary_artifact
from ..database import CanonicalDatabase, dump_json
from ..models import (
    AnalysisBundle,
    AnalysisObject,
    AnalysisObjectDigest,
    ArtifactLedgerEntry,
    ArtifactPointer,
    ChannelEvent,
    ConversationBrainBackend,
    ConversationBrainDecision,
    ConversationMemoryCandidate,
    ConversationResolution,
    ConversationThreadRef,
    InteractionState,
    IntentKind,
    MemoryTier,
    OperatorMessageKind,
    ReferenceResolution,
    ThreadLedgerSnapshot,
    WorkingSetPlan,
    new_id,
    to_jsonable,
    utc_now_iso,
)
from ..paths import PathPolicy, ProjectPaths


def _loads_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _loads_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _normalize_text(text: str) -> str:
    lowered = str(text or "").strip().lower().replace("'", " ").replace("â€™", " ")
    normalized = unicodedata.normalize("NFKD", lowered)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    cleaned = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _contains_hint(normalized: str, hints: Iterable[str]) -> bool:
    tokens = set(normalized.split())
    for hint in hints:
        value = str(hint or "").strip().lower()
        if not value:
            continue
        if " " in value:
            if value in normalized:
                return True
            continue
        if value in tokens:
            return True
    return False


class ThreadLedgerService:
    def __init__(self, *, database: CanonicalDatabase) -> None:
        self.database = database

    @staticmethod
    def conversation_key_for(thread_ref: ConversationThreadRef) -> str:
        return str(thread_ref.external_thread_id or thread_ref.thread_id or "").strip()

    def ensure_thread(
        self,
        *,
        surface: str,
        channel: str,
        thread_ref: ConversationThreadRef,
    ) -> ThreadLedgerSnapshot:
        conversation_key = self.conversation_key_for(thread_ref)
        row = self.database.fetchone(
            """
            SELECT *
            FROM thread_ledgers
            WHERE surface = ?
              AND channel = ?
              AND conversation_key = ?
            LIMIT 1
            """,
            (surface, channel, conversation_key),
        )
        if row is not None:
            return self._row_to_snapshot(row)
        snapshot = ThreadLedgerSnapshot(
            thread_ledger_id=new_id("thread_ledger"),
            surface=surface,
            channel=channel,
            thread_id=thread_ref.thread_id,
            external_thread_id=thread_ref.external_thread_id,
            conversation_key=conversation_key,
        )
        self.save_snapshot(snapshot)
        self.append_event(
            thread_ledger_id=snapshot.thread_ledger_id,
            event_kind="thread_initialized",
            payload={
                "surface": surface,
                "channel": channel,
                "thread_id": thread_ref.thread_id,
                "external_thread_id": thread_ref.external_thread_id,
                "conversation_key": conversation_key,
            },
        )
        return snapshot

    def load_thread(
        self,
        *,
        surface: str,
        channel: str,
        thread_ref: ConversationThreadRef,
    ) -> ThreadLedgerSnapshot | None:
        conversation_key = self.conversation_key_for(thread_ref)
        if not conversation_key:
            return None
        row = self.database.fetchone(
            """
            SELECT *
            FROM thread_ledgers
            WHERE surface = ?
              AND channel = ?
              AND conversation_key = ?
            LIMIT 1
            """,
            (surface, channel, conversation_key),
        )
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def save_snapshot(self, snapshot: ThreadLedgerSnapshot) -> None:
        self.database.upsert(
            "thread_ledgers",
            {
                "thread_ledger_id": snapshot.thread_ledger_id,
                "surface": snapshot.surface,
                "channel": snapshot.channel,
                "thread_id": snapshot.thread_id,
                "external_thread_id": snapshot.external_thread_id,
                "conversation_key": snapshot.conversation_key or snapshot.thread_id,
                "status": snapshot.status,
                "active_subject": snapshot.active_subject,
                "subtopics_json": dump_json(snapshot.subtopics),
                "last_operator_reply_id": snapshot.last_operator_reply_id,
                "last_authoritative_reply_summary": snapshot.last_authoritative_reply_summary,
                "last_artifact_id": snapshot.last_artifact_id,
                "last_pdf_artifact_id": snapshot.last_pdf_artifact_id,
                "last_bundle_id": snapshot.last_bundle_id,
                "active_bundle_ids_json": dump_json(snapshot.active_bundle_ids),
                "active_analysis_object_ids_json": dump_json(snapshot.active_analysis_object_ids),
                "referenced_object_ids_json": dump_json(snapshot.referenced_object_ids),
                "pending_approval_ids_json": dump_json(snapshot.pending_approval_ids),
                "mode": snapshot.mode,
                "claims_json": dump_json(snapshot.claims),
                "questions_json": dump_json(snapshot.questions),
                "decisions_json": dump_json(snapshot.decisions),
                "contradictions_json": dump_json(snapshot.contradictions),
                "metadata_json": dump_json(snapshot.metadata),
                "created_at": snapshot.created_at,
                "updated_at": snapshot.updated_at,
            },
            conflict_columns="thread_ledger_id",
            immutable_columns=["created_at"],
        )

    def record_inbound_message(
        self,
        *,
        event: ChannelEvent,
        candidate: ConversationMemoryCandidate,
        message_object_id: str | None = None,
    ) -> ThreadLedgerSnapshot:
        snapshot = self.ensure_thread(surface=event.surface, channel=event.message.channel, thread_ref=event.message.thread_ref)
        normalized = _normalize_text(event.message.text)
        if not snapshot.active_subject and candidate.summary:
            snapshot.active_subject = candidate.summary
        if len(normalized.split()) >= 4 and not self._looks_like_followup(normalized):
            snapshot.active_subject = candidate.summary or snapshot.active_subject
        if self._extract_questions(event.message.text):
            snapshot.questions = _dedupe([*self._extract_questions(event.message.text), *snapshot.questions])[:6]
        if message_object_id:
            snapshot.referenced_object_ids = _dedupe([message_object_id, *snapshot.referenced_object_ids])[:8]
            snapshot.active_analysis_object_ids = _dedupe([message_object_id, *snapshot.active_analysis_object_ids])[:8]
        snapshot.metadata = {
            **snapshot.metadata,
            "last_user_message_id": event.message.message_id,
            "last_user_text": event.message.text,
            "last_user_created_at": event.created_at,
            "last_candidate_id": candidate.candidate_id,
            "last_user_question": self._extract_questions(event.message.text)[0] if self._extract_questions(event.message.text) else None,
        }
        snapshot.updated_at = event.created_at
        self.save_snapshot(snapshot)
        self.append_event(
            thread_ledger_id=snapshot.thread_ledger_id,
            event_kind="inbound_message",
            related_id=event.event_id,
            payload={
                "message_id": event.message.message_id,
                "candidate_id": candidate.candidate_id,
                "classification": candidate.classification.value,
                "summary": candidate.summary,
                "message_object_id": message_object_id,
            },
        )
        return snapshot

    def record_reply(
        self,
        *,
        event: ChannelEvent,
        reply_id: str,
        summary: str,
        artifact_ids: list[str] | None = None,
        pdf_artifact_id: str | None = None,
        object_ids: list[str] | None = None,
        bundle_ids: list[str] | None = None,
        mode: str | None = None,
        created_at: str,
    ) -> ThreadLedgerSnapshot:
        snapshot = self.ensure_thread(surface=event.surface, channel=event.message.channel, thread_ref=event.message.thread_ref)
        snapshot.last_operator_reply_id = reply_id
        snapshot.last_authoritative_reply_summary = summary or snapshot.last_authoritative_reply_summary
        if artifact_ids:
            snapshot.last_artifact_id = artifact_ids[0]
        if pdf_artifact_id:
            snapshot.last_pdf_artifact_id = pdf_artifact_id
        if bundle_ids:
            snapshot.last_bundle_id = bundle_ids[0]
            snapshot.active_bundle_ids = _dedupe([*bundle_ids, *snapshot.active_bundle_ids])[:8]
        if object_ids:
            snapshot.active_analysis_object_ids = _dedupe([*object_ids, *snapshot.active_analysis_object_ids])[:12]
            snapshot.referenced_object_ids = _dedupe([*object_ids, *snapshot.referenced_object_ids])[:12]
        if mode:
            snapshot.mode = mode
        decision = self._extract_reply_decision(summary)
        if decision:
            snapshot.decisions = _dedupe([decision, *snapshot.decisions])[:6]
        reply_questions = self._extract_questions(summary)
        if reply_questions:
            snapshot.questions = _dedupe([*reply_questions, *snapshot.questions])[:6]
        next_step = self._extract_reply_next_step(summary)
        snapshot.metadata = {
            **snapshot.metadata,
            "last_reply_id": reply_id,
            "last_reply_created_at": created_at,
            "next_step": next_step or snapshot.metadata.get("next_step"),
        }
        snapshot.updated_at = created_at
        self.save_snapshot(snapshot)
        self.append_event(
            thread_ledger_id=snapshot.thread_ledger_id,
            event_kind="operator_reply",
            related_id=reply_id,
            payload={
                "summary": summary,
                "artifact_ids": artifact_ids or [],
                "pdf_artifact_id": pdf_artifact_id,
                "object_ids": object_ids or [],
                "bundle_ids": bundle_ids or [],
                "mode": mode,
            },
        )
        return snapshot

    def mark_artifact(
        self,
        *,
        event: ChannelEvent,
        artifact_id: str,
        object_id: str | None = None,
        bundle_id: str | None = None,
        is_pdf: bool = False,
        created_at: str | None = None,
    ) -> ThreadLedgerSnapshot:
        snapshot = self.ensure_thread(surface=event.surface, channel=event.message.channel, thread_ref=event.message.thread_ref)
        snapshot.last_artifact_id = artifact_id
        if is_pdf:
            snapshot.last_pdf_artifact_id = artifact_id
        if object_id:
            snapshot.active_analysis_object_ids = _dedupe([object_id, *snapshot.active_analysis_object_ids])[:12]
            snapshot.referenced_object_ids = _dedupe([object_id, *snapshot.referenced_object_ids])[:12]
        if bundle_id:
            snapshot.last_bundle_id = bundle_id
            snapshot.active_bundle_ids = _dedupe([bundle_id, *snapshot.active_bundle_ids])[:8]
        snapshot.updated_at = created_at or snapshot.updated_at
        self.save_snapshot(snapshot)
        self.append_event(
            thread_ledger_id=snapshot.thread_ledger_id,
            event_kind="artifact_registered",
            related_id=artifact_id,
            payload={"object_id": object_id, "bundle_id": bundle_id, "is_pdf": is_pdf},
        )
        return snapshot

    def sync_pending_approvals(
        self,
        *,
        surface: str,
        channel: str,
        thread_ref: ConversationThreadRef,
        approvals: list[dict[str, Any]],
        mode: str | None = None,
        approval_state: str | None = None,
        updated_at: str | None = None,
    ) -> ThreadLedgerSnapshot:
        snapshot = self.ensure_thread(surface=surface, channel=channel, thread_ref=thread_ref)
        matching_ids: list[str] = []
        for approval in approvals:
            if self._approval_matches_thread(approval, snapshot):
                approval_id = str(approval.get("approval_id") or "").strip()
                if approval_id:
                    matching_ids.append(approval_id)
        snapshot.pending_approval_ids = _dedupe(matching_ids)
        if mode:
            snapshot.mode = str(mode).strip() or snapshot.mode
        if approval_state:
            snapshot.metadata = {
                **snapshot.metadata,
                "approval_state": approval_state,
            }
        if updated_at:
            snapshot.updated_at = updated_at
        self.save_snapshot(snapshot)
        self.append_event(
            thread_ledger_id=snapshot.thread_ledger_id,
            event_kind="approval_sync",
            payload={
                "pending_approval_ids": snapshot.pending_approval_ids,
                "mode": snapshot.mode,
                "approval_state": approval_state,
            },
            created_at=updated_at,
        )
        return snapshot

    def append_event(
        self,
        *,
        thread_ledger_id: str,
        event_kind: str,
        payload: dict[str, Any],
        related_id: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self.database.upsert(
            "thread_ledger_events",
            {
                "thread_ledger_event_id": new_id("thread_ledger_event"),
                "thread_ledger_id": thread_ledger_id,
                "event_kind": event_kind,
                "related_id": related_id,
                "payload_json": dump_json(payload),
                "created_at": created_at or utc_now_iso(),
            },
            conflict_columns="thread_ledger_event_id",
        )

    @staticmethod
    def _looks_like_followup(normalized: str) -> bool:
        return _contains_hint(normalized, ("pdf", "document", "doc", "reponse", "lui", "ca", "sur le", "sur la", "et tu", "bah sur"))

    @staticmethod
    def _extract_questions(text: str) -> list[str]:
        return _dedupe(match.strip() for match in re.findall(r"[^.!?\n]*\?+", str(text or "")) if match.strip())[:4]

    @staticmethod
    def _extract_reply_next_step(text: str) -> str | None:
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip(" -\t")
            lowered = line.lower()
            if lowered.startswith("prochain pas:"):
                return line.split(":", 1)[1].strip() or None
            if lowered.startswith("action recommandee:"):
                return line.split(":", 1)[1].strip() or None
        return None

    @staticmethod
    def _extract_reply_decision(text: str) -> str | None:
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            lowered = line.lower()
            if not line:
                continue
            if lowered.startswith(("question:", "prochain pas:", "action recommandee:", "branche:")):
                continue
            return line[:180]
        compact = " ".join(str(text or "").split())
        return compact[:180] if compact else None

    @staticmethod
    def _approval_matches_thread(approval: dict[str, Any], snapshot: ThreadLedgerSnapshot) -> bool:
        metadata = approval.get("metadata") if isinstance(approval.get("metadata"), dict) else {}
        thread_payload = metadata.get("thread_ref") if isinstance(metadata.get("thread_ref"), dict) else {}
        approval_conversation_key = str(
            metadata.get("conversation_key")
            or thread_payload.get("external_thread_id")
            or thread_payload.get("thread_id")
            or ""
        ).strip()
        if approval_conversation_key and approval_conversation_key == str(snapshot.conversation_key or "").strip():
            return True
        approval_thread_id = str(thread_payload.get("thread_id") or "").strip()
        if approval_thread_id and approval_thread_id == str(snapshot.thread_id or "").strip():
            return True
        approval_external_thread_id = str(thread_payload.get("external_thread_id") or "").strip()
        if approval_external_thread_id and approval_external_thread_id == str(snapshot.external_thread_id or "").strip():
            return True
        return False

    @staticmethod
    def _row_to_snapshot(row: Any) -> ThreadLedgerSnapshot:
        return ThreadLedgerSnapshot(
            thread_ledger_id=str(row["thread_ledger_id"]),
            surface=str(row["surface"]),
            channel=str(row["channel"]),
            thread_id=str(row["thread_id"]),
            external_thread_id=str(row["external_thread_id"]) if row["external_thread_id"] else None,
            conversation_key=str(row["conversation_key"]) if row["conversation_key"] else None,
            status=str(row["status"]),
            active_subject=str(row["active_subject"]) if row["active_subject"] else None,
            subtopics=[str(item) for item in _loads_json_list(row["subtopics_json"])],
            last_operator_reply_id=str(row["last_operator_reply_id"]) if row["last_operator_reply_id"] else None,
            last_authoritative_reply_summary=str(row["last_authoritative_reply_summary"]) if row["last_authoritative_reply_summary"] else None,
            last_artifact_id=str(row["last_artifact_id"]) if row["last_artifact_id"] else None,
            last_pdf_artifact_id=str(row["last_pdf_artifact_id"]) if row["last_pdf_artifact_id"] else None,
            last_bundle_id=str(row["last_bundle_id"]) if row["last_bundle_id"] else None,
            active_bundle_ids=[str(item) for item in _loads_json_list(row["active_bundle_ids_json"])],
            active_analysis_object_ids=[str(item) for item in _loads_json_list(row["active_analysis_object_ids_json"])],
            referenced_object_ids=[str(item) for item in _loads_json_list(row["referenced_object_ids_json"])],
            pending_approval_ids=[str(item) for item in _loads_json_list(row["pending_approval_ids_json"])],
            mode=str(row["mode"]) if row["mode"] else None,
            claims=[str(item) for item in _loads_json_list(row["claims_json"])],
            questions=[str(item) for item in _loads_json_list(row["questions_json"])],
            decisions=[str(item) for item in _loads_json_list(row["decisions_json"])],
            contradictions=[str(item) for item in _loads_json_list(row["contradictions_json"])],
            metadata=_loads_json_dict(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


class ArtifactLedgerService:
    IMPORTANT_ARTIFACT_KINDS = frozenset(
        {
            "response_review_pdf",
            "response_review_markdown",
            "response_manifest",
            "ingress_input",
            "ingress_attachment_manifest",
            "long_context_workflow",
            "long_context_segments",
        }
    )

    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        paths: ProjectPaths | None = None,
        path_policy: PathPolicy | None = None,
    ) -> None:
        self.database = database
        self.paths = paths
        self.path_policy = path_policy

    def register_artifact(
        self,
        *,
        pointer: ArtifactPointer,
        owner_type: str,
        owner_id: str,
        event: ChannelEvent | None = None,
        reply_id: str | None = None,
        run_id: str | None = None,
        approval_id: str | None = None,
        bundle_id: str | None = None,
        source_object_id: str | None = None,
        source_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        cold_backup: bool | None = None,
        ingestion_status: str | None = None,
        source_locator: str | None = None,
    ) -> ArtifactLedgerEntry:
        existing = self.database.fetchone(
            "SELECT * FROM artifact_ledger_entries WHERE artifact_id = ?",
            (pointer.artifact_id,),
        )
        conversation_key = None
        thread_id = None
        external_thread_id = None
        surface = None
        channel = None
        if event is not None:
            conversation_key = ThreadLedgerService.conversation_key_for(event.message.thread_ref)
            thread_id = event.message.thread_ref.thread_id
            external_thread_id = event.message.thread_ref.external_thread_id
            surface = event.surface
            channel = event.message.channel
        existing_entry = self._row_to_entry(existing) if existing is not None else None
        cold_pointer = None
        if self._should_cold_backup(pointer, explicit=cold_backup) and not (existing_entry and existing_entry.cold_artifact_id):
            cold_pointer = self._write_cold_backup(pointer)
        entry = ArtifactLedgerEntry(
            artifact_ledger_entry_id=existing_entry.artifact_ledger_entry_id if existing_entry else new_id("artifact_ledger"),
            artifact_id=pointer.artifact_id,
            artifact_kind=pointer.artifact_kind,
            owner_type=owner_type or (existing_entry.owner_type if existing_entry else owner_type),
            owner_id=owner_id or (existing_entry.owner_id if existing_entry else owner_id),
            surface=surface or (existing_entry.surface if existing_entry else None),
            channel=channel or (existing_entry.channel if existing_entry else None),
            thread_id=thread_id or (existing_entry.thread_id if existing_entry else None),
            external_thread_id=external_thread_id or (existing_entry.external_thread_id if existing_entry else None),
            conversation_key=conversation_key or (existing_entry.conversation_key if existing_entry else None),
            reply_id=reply_id or (existing_entry.reply_id if existing_entry else None),
            run_id=run_id or (existing_entry.run_id if existing_entry else None),
            approval_id=approval_id or (existing_entry.approval_id if existing_entry else None),
            bundle_id=bundle_id or (existing_entry.bundle_id if existing_entry else None),
            source_object_id=source_object_id or (existing_entry.source_object_id if existing_entry else None),
            source_ids=_dedupe([*(existing_entry.source_ids if existing_entry else []), *(source_ids or [])]),
            cold_artifact_id=cold_pointer.artifact_id if cold_pointer else (existing_entry.cold_artifact_id if existing_entry else None),
            cold_path=cold_pointer.path if cold_pointer else (existing_entry.cold_path if existing_entry else None),
            ingestion_status=str(ingestion_status or (existing_entry.ingestion_status if existing_entry else "ready")),
            source_locator=source_locator or (existing_entry.source_locator if existing_entry else pointer.path),
            metadata={
                **(existing_entry.metadata if existing_entry else {}),
                **dict(metadata or {}),
            },
            created_at=existing_entry.created_at if existing_entry else utc_now_iso(),
        )
        self.database.upsert(
            "artifact_ledger_entries",
            {
                "artifact_ledger_entry_id": entry.artifact_ledger_entry_id,
                "artifact_id": entry.artifact_id,
                "artifact_kind": entry.artifact_kind,
                "owner_type": entry.owner_type,
                "owner_id": entry.owner_id,
                "surface": entry.surface,
                "channel": entry.channel,
                "thread_id": entry.thread_id,
                "external_thread_id": entry.external_thread_id,
                "conversation_key": entry.conversation_key,
                "reply_id": entry.reply_id,
                "run_id": entry.run_id,
                "approval_id": entry.approval_id,
                "bundle_id": entry.bundle_id,
                "source_object_id": entry.source_object_id,
                "source_ids_json": dump_json(entry.source_ids),
                "cold_artifact_id": entry.cold_artifact_id,
                "cold_path": entry.cold_path,
                "ingestion_status": entry.ingestion_status,
                "source_locator": entry.source_locator,
                "metadata_json": dump_json(entry.metadata),
                "created_at": entry.created_at,
            },
            conflict_columns="artifact_id",
            immutable_columns=["created_at"],
        )
        stored = self.database.fetchone(
            "SELECT * FROM artifact_ledger_entries WHERE artifact_id = ?",
            (pointer.artifact_id,),
        )
        return self._row_to_entry(stored) if stored is not None else entry

    def _should_cold_backup(self, pointer: ArtifactPointer, *, explicit: bool | None = None) -> bool:
        if explicit is not None:
            return explicit
        if pointer.storage_tier is MemoryTier.COLD:
            return False
        suffix = Path(pointer.path).suffix.lower()
        if suffix == ".pdf":
            return True
        return pointer.artifact_kind in self.IMPORTANT_ARTIFACT_KINDS

    def _write_cold_backup(self, pointer: ArtifactPointer) -> ArtifactPointer | None:
        if self.paths is None or self.path_policy is None:
            return None
        source_path = Path(pointer.path)
        if not source_path.exists():
            return None
        suffix = source_path.suffix or ".bin"
        payload = source_path.read_bytes()
        cold_kind = "report" if suffix.lower() == ".pdf" else "snapshot"
        cold_pointer = write_binary_artifact(
            paths=self.paths,
            path_policy=self.path_policy,
            owner_id=f"{pointer.artifact_id}_cold",
            artifact_kind=cold_kind,
            storage_tier=MemoryTier.COLD,
            payload=payload,
            suffix=suffix,
        )
        self.database.upsert(
            "artifact_pointers",
            {
                "artifact_id": cold_pointer.artifact_id,
                "owner_type": "artifact_cold_backup",
                "owner_id": pointer.artifact_id,
                "artifact_kind": cold_pointer.artifact_kind,
                "storage_tier": cold_pointer.storage_tier.value,
                "path": cold_pointer.path,
                "checksum_sha256": cold_pointer.checksum_sha256,
                "size_bytes": cold_pointer.size_bytes,
                "created_at": cold_pointer.created_at,
            },
            conflict_columns="artifact_id",
            immutable_columns=["created_at"],
        )
        return cold_pointer

    @staticmethod
    def _row_to_entry(row: Any) -> ArtifactLedgerEntry:
        return ArtifactLedgerEntry(
            artifact_ledger_entry_id=str(row["artifact_ledger_entry_id"]),
            artifact_id=str(row["artifact_id"]),
            artifact_kind=str(row["artifact_kind"]),
            owner_type=str(row["owner_type"]),
            owner_id=str(row["owner_id"]),
            surface=str(row["surface"]) if row["surface"] else None,
            channel=str(row["channel"]) if row["channel"] else None,
            thread_id=str(row["thread_id"]) if row["thread_id"] else None,
            external_thread_id=str(row["external_thread_id"]) if row["external_thread_id"] else None,
            conversation_key=str(row["conversation_key"]) if row["conversation_key"] else None,
            reply_id=str(row["reply_id"]) if row["reply_id"] else None,
            run_id=str(row["run_id"]) if row["run_id"] else None,
            approval_id=str(row["approval_id"]) if row["approval_id"] else None,
            bundle_id=str(row["bundle_id"]) if row["bundle_id"] else None,
            source_object_id=str(row["source_object_id"]) if row["source_object_id"] else None,
            source_ids=[str(item) for item in _loads_json_list(row["source_ids_json"])],
            cold_artifact_id=str(row["cold_artifact_id"]) if row["cold_artifact_id"] else None,
            cold_path=str(row["cold_path"]) if row["cold_path"] else None,
            ingestion_status=str(row["ingestion_status"] or "ready"),
            source_locator=str(row["source_locator"]) if row["source_locator"] else None,
            metadata=_loads_json_dict(row["metadata_json"]),
            created_at=str(row["created_at"]),
        )


class AnalysisObjectService:
    def __init__(self, *, database: CanonicalDatabase) -> None:
        self.database = database

    def register_message_object(self, *, event: ChannelEvent, candidate: ConversationMemoryCandidate) -> AnalysisObject:
        existing = self.find_existing_by_source_id(event.event_id)
        if existing is not None:
            return existing
        title = candidate.summary or self._title_for(event.message.text)
        return self.create_object(
            AnalysisObject(
                object_id=new_id("analysis"),
                object_type="source_message",
                surface=event.surface,
                channel=event.message.channel,
                thread_id=event.message.thread_ref.thread_id,
                conversation_key=ThreadLedgerService.conversation_key_for(event.message.thread_ref),
                title=title,
                summary_short=candidate.summary,
                summary_full=event.message.text.strip(),
                source_ids=[event.event_id],
                artifact_ids=[],
                claims=[],
                questions=self._extract_questions(event.message.text),
                decisions=[],
                confidence=float(candidate.metadata.get("intent_confidence") or 0.6),
                status="active",
                content_status="ready",
                source_mime_type=None,
                extracted_text_artifact_id=None,
                bundle_ids=[],
                tags=list(candidate.tags),
                metadata={
                    "message_id": event.message.message_id,
                    "classification": candidate.classification.value,
                    "input_profile": candidate.metadata.get("input_profile"),
                },
            )
        )

    def register_artifact_object(
        self,
        *,
        entry: ArtifactLedgerEntry,
        object_type: str,
        title: str | None,
        summary_short: str,
        summary_full: str,
        claims: list[str] | None = None,
        questions: list[str] | None = None,
        decisions: list[str] | None = None,
        confidence: float = 0.7,
        tags: list[str] | None = None,
        content_status: str = "ready",
        source_mime_type: str | None = None,
        extracted_text_artifact_id: str | None = None,
        bundle_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AnalysisObject:
        existing = self.find_existing_by_artifact_id(entry.artifact_id)
        if existing is not None:
            return existing
        return self.create_object(
            AnalysisObject(
                object_id=new_id("analysis"),
                object_type=object_type,
                surface=entry.surface,
                channel=entry.channel,
                thread_id=entry.thread_id,
                conversation_key=entry.conversation_key,
                title=title,
                summary_short=summary_short,
                summary_full=summary_full,
                source_ids=list(entry.source_ids),
                artifact_ids=[entry.artifact_id, *([entry.cold_artifact_id] if entry.cold_artifact_id else [])],
                claims=list(claims or []),
                questions=list(questions or []),
                decisions=list(decisions or []),
                confidence=confidence,
                status="active",
                content_status=content_status,
                source_mime_type=source_mime_type,
                extracted_text_artifact_id=extracted_text_artifact_id,
                bundle_ids=list(bundle_ids or ([] if not entry.bundle_id else [entry.bundle_id])),
                tags=list(tags or []),
                metadata={
                    "artifact_kind": entry.artifact_kind,
                    "owner_type": entry.owner_type,
                    "owner_id": entry.owner_id,
                    **(metadata or {}),
                },
            )
        )

    def create_object(self, obj: AnalysisObject) -> AnalysisObject:
        self.database.upsert(
            "analysis_objects",
            {
                "object_id": obj.object_id,
                "object_type": obj.object_type,
                "surface": obj.surface,
                "channel": obj.channel,
                "thread_id": obj.thread_id,
                "conversation_key": obj.conversation_key,
                "title": obj.title,
                "summary_short": obj.summary_short,
                "summary_full": obj.summary_full,
                "source_ids_json": dump_json(obj.source_ids),
                "artifact_ids_json": dump_json(obj.artifact_ids),
                "claims_json": dump_json(obj.claims),
                "questions_json": dump_json(obj.questions),
                "decisions_json": dump_json(obj.decisions),
                "confidence": obj.confidence,
                "status": obj.status,
                "content_status": obj.content_status,
                "source_mime_type": obj.source_mime_type,
                "extracted_text_artifact_id": obj.extracted_text_artifact_id,
                "bundle_ids_json": dump_json(obj.bundle_ids),
                "supersedes_json": dump_json(obj.supersedes),
                "tags_json": dump_json(obj.tags),
                "metadata_json": dump_json(obj.metadata),
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
            },
            conflict_columns="object_id",
            immutable_columns=["created_at"],
        )
        return obj

    def recent_objects(self, *, conversation_key: str, limit: int = 12) -> list[AnalysisObject]:
        rows = self.database.fetchall(
            """
            SELECT *
            FROM analysis_objects
            WHERE conversation_key = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (conversation_key, limit),
        )
        return [self._row_to_object(row) for row in rows]

    def find_existing_by_source_id(self, source_id: str) -> AnalysisObject | None:
        row = self.database.fetchone(
            """
            SELECT *
            FROM analysis_objects
            WHERE source_ids_json LIKE ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (f'%"{str(source_id)}"%',),
        )
        return self._row_to_object(row) if row is not None else None

    def find_existing_by_artifact_id(self, artifact_id: str) -> AnalysisObject | None:
        row = self.database.fetchone(
            """
            SELECT *
            FROM analysis_objects
            WHERE artifact_ids_json LIKE ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (f'%"{str(artifact_id)}"%',),
        )
        return self._row_to_object(row) if row is not None else None

    @staticmethod
    def build_digest(obj: AnalysisObject) -> AnalysisObjectDigest:
        return AnalysisObjectDigest(
            object_id=obj.object_id,
            object_type=obj.object_type,
            title=obj.title,
            summary_short=obj.summary_short,
            claims=list(obj.claims[:3]),
            questions=list(obj.questions[:3]),
            decisions=list(obj.decisions[:3]),
            artifact_ids=list(obj.artifact_ids[:4]),
            bundle_ids=list(obj.bundle_ids[:3]),
        )

    @staticmethod
    def _row_to_object(row: Any) -> AnalysisObject:
        return AnalysisObject(
            object_id=str(row["object_id"]),
            object_type=str(row["object_type"]),
            surface=str(row["surface"]) if row["surface"] else None,
            channel=str(row["channel"]) if row["channel"] else None,
            thread_id=str(row["thread_id"]) if row["thread_id"] else None,
            conversation_key=str(row["conversation_key"]) if row["conversation_key"] else None,
            title=str(row["title"]) if row["title"] else None,
            summary_short=str(row["summary_short"] or ""),
            summary_full=str(row["summary_full"] or ""),
            source_ids=[str(item) for item in _loads_json_list(row["source_ids_json"])],
            artifact_ids=[str(item) for item in _loads_json_list(row["artifact_ids_json"])],
            claims=[str(item) for item in _loads_json_list(row["claims_json"])],
            questions=[str(item) for item in _loads_json_list(row["questions_json"])],
            decisions=[str(item) for item in _loads_json_list(row["decisions_json"])],
            confidence=float(row["confidence"] or 0.0),
            status=str(row["status"] or "active"),
            content_status=str(row["content_status"] or "ready"),
            source_mime_type=str(row["source_mime_type"]) if row["source_mime_type"] else None,
            extracted_text_artifact_id=str(row["extracted_text_artifact_id"]) if row["extracted_text_artifact_id"] else None,
            bundle_ids=[str(item) for item in _loads_json_list(row["bundle_ids_json"])],
            supersedes=[str(item) for item in _loads_json_list(row["supersedes_json"])],
            tags=[str(item) for item in _loads_json_list(row["tags_json"])],
            metadata=_loads_json_dict(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _title_for(text: str) -> str:
        clean = " ".join(str(text or "").split())
        return clean[:80] if clean else "Conversation object"

    @staticmethod
    def _extract_questions(text: str) -> list[str]:
        return _dedupe(match.strip() for match in re.findall(r"[^.!?\n]*\?+", str(text or "")) if match.strip())[:4]


class BundleComposerService:
    def __init__(self, *, database: CanonicalDatabase) -> None:
        self.database = database

    def ensure_thread_bundle(
        self,
        *,
        surface: str,
        channel: str,
        thread_ref: ConversationThreadRef,
        title: str | None = None,
        bundle_kind: str = "thread_active",
    ) -> AnalysisBundle:
        conversation_key = ThreadLedgerService.conversation_key_for(thread_ref)
        row = self.database.fetchone(
            """
            SELECT *
            FROM analysis_bundles
            WHERE conversation_key = ?
              AND bundle_kind = ?
              AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (conversation_key, bundle_kind),
        )
        if row is not None:
            return self._row_to_bundle(row)
        bundle = AnalysisBundle(
            bundle_id=new_id("bundle"),
            bundle_kind=bundle_kind,
            title=title or f"Thread bundle {thread_ref.thread_id}",
            surface=surface,
            channel=channel,
            thread_id=thread_ref.thread_id,
            conversation_key=conversation_key,
        )
        self.save_bundle(bundle)
        return bundle

    def save_bundle(self, bundle: AnalysisBundle) -> AnalysisBundle:
        self.database.upsert(
            "analysis_bundles",
            {
                "bundle_id": bundle.bundle_id,
                "bundle_kind": bundle.bundle_kind,
                "title": bundle.title,
                "surface": bundle.surface,
                "channel": bundle.channel,
                "thread_id": bundle.thread_id,
                "conversation_key": bundle.conversation_key,
                "summary_short": bundle.summary_short,
                "summary_full": bundle.summary_full,
                "status": bundle.status,
                "metadata_json": dump_json(bundle.metadata),
                "created_at": bundle.created_at,
                "updated_at": bundle.updated_at,
            },
            conflict_columns="bundle_id",
            immutable_columns=["created_at"],
        )
        return bundle

    def add_member(
        self,
        *,
        bundle_id: str,
        object_id: str,
        member_role: str = "member",
        position: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.database.upsert(
            "bundle_members",
            {
                "bundle_id": bundle_id,
                "object_id": object_id,
                "member_role": member_role,
                "position": position,
                "metadata_json": dump_json(metadata or {}),
                "created_at": utc_now_iso(),
            },
            conflict_columns=["bundle_id", "object_id"],
            immutable_columns=["created_at"],
        )

    @staticmethod
    def _row_to_bundle(row: Any) -> AnalysisBundle:
        return AnalysisBundle(
            bundle_id=str(row["bundle_id"]),
            bundle_kind=str(row["bundle_kind"]),
            title=str(row["title"]),
            surface=str(row["surface"]) if row["surface"] else None,
            channel=str(row["channel"]) if row["channel"] else None,
            thread_id=str(row["thread_id"]) if row["thread_id"] else None,
            conversation_key=str(row["conversation_key"]) if row["conversation_key"] else None,
            summary_short=str(row["summary_short"] or ""),
            summary_full=str(row["summary_full"] or ""),
            status=str(row["status"] or "active"),
            metadata=_loads_json_dict(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


class WorkingSetPlannerService:
    _REFERENCE_HINTS = (
        "pdf",
        "doc",
        "document",
        "reponse",
        "note",
        "combien",
        "sur le",
        "sur la",
        "lui",
        "ca",
        "precedent",
    )
    _AMBIGUOUS_FOLLOWUP_HINTS = (
        "et du coup",
        "du coup",
        "et donc",
        "alors",
        "ca",
        "lui",
        "celle",
        "celui",
        "lequel",
        "laquelle",
        "combien",
        "note",
        "suite",
        "apres",
    )

    def __init__(self, *, database: CanonicalDatabase, analysis_objects: AnalysisObjectService) -> None:
        self.database = database
        self.analysis_objects = analysis_objects

    def plan(
        self,
        *,
        event: ChannelEvent,
        candidate: ConversationMemoryCandidate,
        thread_ledger: ThreadLedgerSnapshot | None,
        limit: int = 4,
    ) -> WorkingSetPlan:
        conversation_key = ThreadLedgerService.conversation_key_for(event.message.thread_ref)
        recent_objects = self.analysis_objects.recent_objects(conversation_key=conversation_key, limit=12)
        normalized = _normalize_text(event.message.text)
        short_followup = len(normalized.split()) <= 6
        ambiguous_short_followup = short_followup and self._looks_like_ambiguous_followup(normalized)
        comparative_request = _contains_hint(normalized, ("compare", "comparaison", "contradiction", "les docs", "les document"))
        if ambiguous_short_followup:
            limit = 1
        elif short_followup:
            limit = min(limit, 3)
        elif comparative_request:
            limit = max(limit, 6)
        selected: list[AnalysisObject] = []
        reasons: list[str] = []
        if thread_ledger is not None:
            if thread_ledger.last_pdf_artifact_id and _contains_hint(normalized, self._REFERENCE_HINTS):
                match = next((obj for obj in recent_objects if thread_ledger.last_pdf_artifact_id in obj.artifact_ids), None)
                if match is not None:
                    selected.append(match)
                    reasons.append("last_pdf_reference")
            if not selected and thread_ledger.referenced_object_ids:
                by_id = {obj.object_id: obj for obj in recent_objects}
                for object_id in thread_ledger.referenced_object_ids[:3]:
                    obj = by_id.get(object_id)
                    if obj is not None:
                        selected.append(obj)
                if selected:
                    reasons.append("recent_referenced_objects")
            if not selected and thread_ledger.active_bundle_ids and comparative_request:
                bundle_match = [obj for obj in recent_objects if any(bundle_id in obj.bundle_ids for bundle_id in thread_ledger.active_bundle_ids)]
                if bundle_match:
                    selected.extend(bundle_match[:limit])
                    reasons.append("active_bundle_context")
        if not selected:
            selected.extend(recent_objects[:limit])
            if selected:
                reasons.append("recent_thread_objects")
        selected = selected[:limit]
        digests = [self.analysis_objects.build_digest(obj) for obj in selected]
        summary_parts: list[str] = []
        if thread_ledger and thread_ledger.active_subject:
            summary_parts.append(f"Sujet actif: {thread_ledger.active_subject[:160]}")
        next_step = str((thread_ledger.metadata or {}).get("next_step") or "").strip() if thread_ledger else ""
        if next_step:
            summary_parts.append(f"Prochain pas proche: {next_step[:160]}")
        if thread_ledger and thread_ledger.decisions:
            summary_parts.append("Decisions recentes:\n- " + "\n- ".join(thread_ledger.decisions[:3]))
        if thread_ledger and thread_ledger.last_pdf_artifact_id:
            summary_parts.append("Dernier PDF envoye connu dans ce thread.")
        if thread_ledger and thread_ledger.pending_approval_ids:
            summary_parts.append(
                "Approvals en attente: " + ", ".join(thread_ledger.pending_approval_ids[:3])
            )
        if digests:
            digest_lines: list[str] = []
            for digest in digests[:limit]:
                headline = digest.title or digest.object_type
                summary = str(digest.summary_short or "").strip()
                detail_parts: list[str] = []
                if summary:
                    detail_parts.append(summary[:120])
                if digest.decisions:
                    detail_parts.append("decisions: " + "; ".join(digest.decisions[:2]))
                elif digest.questions:
                    detail_parts.append("questions: " + "; ".join(digest.questions[:2]))
                rendered = headline
                if detail_parts:
                    rendered = f"{rendered} - {' | '.join(detail_parts)}"
                digest_lines.append(rendered)
            summary_parts.append("Objets charges:\n- " + "\n- ".join(digest_lines))
        plan = WorkingSetPlan(
            working_set_id=new_id("working_set"),
            surface=event.surface,
            channel=event.message.channel,
            thread_id=event.message.thread_ref.thread_id,
            conversation_key=conversation_key,
            message_id=event.message.message_id,
            summary="\n".join(part for part in summary_parts if part).strip(),
            selected_object_ids=[obj.object_id for obj in selected],
            selected_object_digests=digests,
            selected_artifact_ids=_dedupe(artifact_id for obj in selected for artifact_id in obj.artifact_ids),
            selected_bundle_ids=list(thread_ledger.active_bundle_ids[:2]) if thread_ledger else [],
            reasons=reasons or ["fallback_discussion"],
            metadata={
                "candidate_id": candidate.candidate_id,
                "message_summary": candidate.summary,
            },
        )
        self.database.upsert(
            "working_set_snapshots",
            {
                "working_set_id": plan.working_set_id,
                "surface": plan.surface,
                "channel": plan.channel,
                "thread_id": plan.thread_id,
                "conversation_key": plan.conversation_key,
                "message_id": plan.message_id,
                "summary": plan.summary,
                "selected_object_ids_json": dump_json(plan.selected_object_ids),
                "selected_object_digests_json": dump_json([to_jsonable(digest) for digest in plan.selected_object_digests]),
                "selected_artifact_ids_json": dump_json(plan.selected_artifact_ids),
                "selected_bundle_ids_json": dump_json(plan.selected_bundle_ids),
                "reasons_json": dump_json(plan.reasons),
                "metadata_json": dump_json(plan.metadata),
                "created_at": plan.created_at,
            },
            conflict_columns="working_set_id",
            immutable_columns=["created_at"],
        )
        return plan

    @classmethod
    def _looks_like_ambiguous_followup(cls, normalized: str) -> bool:
        return _contains_hint(normalized, cls._AMBIGUOUS_FOLLOWUP_HINTS)


class MemoryCoprocessorBridge:
    def resolve_reference(
        self,
        *,
        message_text: str,
        thread_ledger: ThreadLedgerSnapshot | None,
        working_set: WorkingSetPlan | None,
    ) -> ReferenceResolution | None:
        if thread_ledger is None:
            return None
        normalized = _normalize_text(message_text)
        if not normalized:
            return None
        if thread_ledger.last_pdf_artifact_id and _contains_hint(normalized, ("pdf", "doc", "document", "note", "combien", "sur le", "sur la")):
            return ReferenceResolution(
                resolution_id=new_id("reference"),
                resolution_kind="answer_about_last_pdf",
                confidence=0.92,
                conversation_key=thread_ledger.conversation_key,
                thread_id=thread_ledger.thread_id,
                target_type="artifact",
                target_id=thread_ledger.last_pdf_artifact_id,
                reason="last_pdf_reference",
                metadata={"working_set_id": working_set.working_set_id if working_set else None},
            )
        if thread_ledger.last_artifact_id and _contains_hint(normalized, ("artefact", "reponse", "ca", "lui", "precedent")):
            return ReferenceResolution(
                resolution_id=new_id("reference"),
                resolution_kind="answer_about_last_artifact",
                confidence=0.82,
                conversation_key=thread_ledger.conversation_key,
                thread_id=thread_ledger.thread_id,
                target_type="artifact",
                target_id=thread_ledger.last_artifact_id,
                reason="last_artifact_reference",
                metadata={"working_set_id": working_set.working_set_id if working_set else None},
            )
        if (
            working_set
            and len(normalized.split()) <= 6
            and working_set.selected_object_ids
            and thread_ledger.last_operator_reply_id
        ):
            return ReferenceResolution(
                resolution_id=new_id("reference"),
                resolution_kind="continue_previous_answer",
                confidence=0.72,
                conversation_key=thread_ledger.conversation_key,
                thread_id=thread_ledger.thread_id,
                target_type="analysis_object",
                target_id=working_set.selected_object_ids[0],
                reason="short_followup_with_working_set",
                metadata={"working_set_id": working_set.working_set_id},
            )
        return None


class ConversationReliabilityService:
    def inject_candidate_state(
        self,
        *,
        candidate: ConversationMemoryCandidate,
        thread_ledger: ThreadLedgerSnapshot | None,
        working_set: WorkingSetPlan | None,
        resolution: ConversationResolution,
    ) -> None:
        candidate.metadata["thread_ledger_id"] = thread_ledger.thread_ledger_id if thread_ledger else None
        candidate.metadata["thread_conversation_key"] = thread_ledger.conversation_key if thread_ledger else None
        candidate.metadata["thread_last_artifact_id"] = thread_ledger.last_artifact_id if thread_ledger else None
        candidate.metadata["thread_last_pdf_artifact_id"] = thread_ledger.last_pdf_artifact_id if thread_ledger else None
        candidate.metadata["thread_last_reply_summary"] = thread_ledger.last_authoritative_reply_summary if thread_ledger else None
        candidate.metadata["thread_active_subject"] = thread_ledger.active_subject if thread_ledger else None
        candidate.metadata["thread_recent_decisions"] = list(thread_ledger.decisions[:3]) if thread_ledger else []
        candidate.metadata["thread_recent_questions"] = list(thread_ledger.questions[:3]) if thread_ledger else []
        candidate.metadata["thread_next_step"] = str((thread_ledger.metadata or {}).get("next_step") or "").strip() if thread_ledger else ""
        candidate.metadata["thread_pending_approval_ids"] = thread_ledger.pending_approval_ids if thread_ledger else []
        candidate.metadata["thread_mode"] = thread_ledger.mode if thread_ledger else None
        candidate.metadata["working_set_id"] = working_set.working_set_id if working_set else None
        candidate.metadata["working_set_object_ids"] = working_set.selected_object_ids if working_set else []
        candidate.metadata["working_set_object_digests"] = [to_jsonable(item) for item in (working_set.selected_object_digests if working_set else [])]
        candidate.metadata["working_set_artifact_ids"] = working_set.selected_artifact_ids if working_set else []
        candidate.metadata["working_set_bundle_ids"] = working_set.selected_bundle_ids if working_set else []
        candidate.metadata["working_set_summary"] = working_set.summary if working_set else ""
        candidate.metadata["brain_resolution_kind"] = resolution.resolution_kind
        candidate.metadata["brain_resolution_confidence"] = resolution.confidence
        candidate.metadata["brain_reasons"] = list(resolution.reasons)
        candidate.metadata["brain_fallback_discussion"] = bool(resolution.fallback_discussion)
        candidate.metadata["brain_backend"] = (
            resolution.brain_decision.backend.value if resolution.brain_decision is not None else ConversationBrainBackend.FALLBACK.value
        )
        if resolution.reference_resolution is not None:
            candidate.metadata["reference_resolution"] = {
                "resolution_id": resolution.reference_resolution.resolution_id,
                "resolution_kind": resolution.reference_resolution.resolution_kind,
                "target_type": resolution.reference_resolution.target_type,
                "target_id": resolution.reference_resolution.target_id,
                "confidence": resolution.reference_resolution.confidence,
                "reason": resolution.reference_resolution.reason,
            }
        if resolution.brain_decision is not None:
            candidate.metadata["brain_decision"] = {
                "backend": resolution.brain_decision.backend.value,
                "target_type": resolution.brain_decision.target_type,
                "target_id": resolution.brain_decision.target_id,
                "reason": resolution.brain_decision.reason,
                "selected_object_ids": list(resolution.brain_decision.selected_object_ids),
                "selected_artifact_ids": list(resolution.brain_decision.selected_artifact_ids),
                "needs_provider_fallback": bool(resolution.brain_decision.needs_provider_fallback),
            }
            if resolution.brain_decision.metadata.get("clarification_question"):
                candidate.metadata["brain_clarification_question"] = str(
                    resolution.brain_decision.metadata.get("clarification_question") or ""
                ).strip()

    @staticmethod
    def should_force_discussion(resolution: ConversationResolution) -> bool:
        return resolution.fallback_discussion and resolution.confidence >= 0.72

    @staticmethod
    def should_suppress_reasoning_escalation(candidate: ConversationMemoryCandidate) -> bool:
        kind = str(candidate.metadata.get("brain_resolution_kind") or "").strip().lower()
        confidence = float(candidate.metadata.get("brain_resolution_confidence") or 0.0)
        if confidence < 0.72:
            return False
        return kind in {"answer_about_last_pdf", "answer_about_last_artifact", "continue_previous_answer", "answer_about_active_bundle"}


class ConversationBrainService:
    APPROVAL_RESPONSE_HINTS = ("go", "avance", "simple", "extreme", "opus", "sonnet")
    _AMBIGUOUS_FOLLOWUP_HINTS = (
        "et du coup",
        "du coup",
        "et donc",
        "alors",
        "ca",
        "lui",
        "celle",
        "celui",
        "lequel",
        "laquelle",
        "combien",
        "note",
        "suite",
        "apres",
    )

    def __init__(
        self,
        *,
        thread_ledgers: ThreadLedgerService,
        working_sets: WorkingSetPlannerService,
        coprocessor: MemoryCoprocessorBridge,
        reliability: ConversationReliabilityService,
        local_backend=None,
        provider_backend=None,
    ) -> None:
        self.thread_ledgers = thread_ledgers
        self.working_sets = working_sets
        self.coprocessor = coprocessor
        self.reliability = reliability
        self.local_backend = local_backend
        self.provider_backend = provider_backend

    def analyze(
        self,
        *,
        event: ChannelEvent,
        candidate: ConversationMemoryCandidate,
    ) -> tuple[ThreadLedgerSnapshot | None, ConversationResolution]:
        thread_ledger = self.thread_ledgers.load_thread(surface=event.surface, channel=event.message.channel, thread_ref=event.message.thread_ref)
        working_set = self.working_sets.plan(event=event, candidate=candidate, thread_ledger=thread_ledger)
        normalized = _normalize_text(event.message.text)
        if thread_ledger is not None and thread_ledger.pending_approval_ids and (
            normalized in self.APPROVAL_RESPONSE_HINTS or normalized.startswith("go ")
        ):
            brain_decision = ConversationBrainDecision(
                backend=ConversationBrainBackend.DETERMINISTIC,
                resolution_kind="approval_response",
                confidence=0.95,
                reason="approval_like_message_with_pending_approval",
                selected_object_ids=list(working_set.selected_object_ids),
                selected_artifact_ids=list(working_set.selected_artifact_ids),
            )
            resolution = ConversationResolution(
                resolution_kind="approval_response",
                confidence=0.95,
                fallback_discussion=False,
                reasons=["approval_like_message"],
                working_set=working_set,
                brain_decision=brain_decision,
            )
            self.reliability.inject_candidate_state(candidate=candidate, thread_ledger=thread_ledger, working_set=working_set, resolution=resolution)
            return thread_ledger, resolution
        brain_decision = self._run_local_backend(
            event=event,
            candidate=candidate,
            thread_ledger=thread_ledger,
            working_set=working_set,
        )
        if (
            brain_decision.needs_provider_fallback
            and self.provider_backend is not None
        ):
            provider_decision = self.provider_backend(
                event=event,
                candidate=candidate,
                thread_ledger=thread_ledger,
                working_set=working_set,
            )
            if isinstance(provider_decision, ConversationBrainDecision):
                brain_decision = provider_decision
        reference = None
        if brain_decision.target_type and brain_decision.target_id and brain_decision.resolution_kind != "approval_response":
            reference = ReferenceResolution(
                resolution_id=new_id("reference"),
                resolution_kind=brain_decision.resolution_kind,
                confidence=brain_decision.confidence,
                surface=event.surface,
                channel=event.message.channel,
                thread_id=event.message.thread_ref.thread_id,
                conversation_key=ThreadLedgerService.conversation_key_for(event.message.thread_ref),
                message_id=event.message.message_id,
                target_type=brain_decision.target_type,
                target_id=brain_decision.target_id,
                reason=brain_decision.reason,
                metadata={"backend": brain_decision.backend.value},
            )
        resolution = ConversationResolution(
            resolution_kind=brain_decision.resolution_kind,
            confidence=brain_decision.confidence,
            fallback_discussion=brain_decision.resolution_kind != "approval_response",
            reasons=[brain_decision.reason] if brain_decision.reason else ["default_discussion"],
            working_set=working_set,
            reference_resolution=reference,
            brain_decision=brain_decision,
            metadata={"backend": brain_decision.backend.value},
        )
        self.reliability.inject_candidate_state(candidate=candidate, thread_ledger=thread_ledger, working_set=working_set, resolution=resolution)
        return thread_ledger, resolution

    def _run_local_backend(
        self,
        *,
        event: ChannelEvent,
        candidate: ConversationMemoryCandidate,
        thread_ledger: ThreadLedgerSnapshot | None,
        working_set: WorkingSetPlan,
    ) -> ConversationBrainDecision:
        if self.local_backend is not None:
            external = self.local_backend(
                event=event,
                candidate=candidate,
                thread_ledger=thread_ledger,
                working_set=working_set,
            )
            if isinstance(external, ConversationBrainDecision):
                return external
        return self._fallback_local_decision(
            event=event,
            candidate=candidate,
            thread_ledger=thread_ledger,
            working_set=working_set,
        )

    def _fallback_local_decision(
        self,
        *,
        event: ChannelEvent,
        candidate: ConversationMemoryCandidate,
        thread_ledger: ThreadLedgerSnapshot | None,
        working_set: WorkingSetPlan,
    ) -> ConversationBrainDecision:
        normalized = _normalize_text(event.message.text)
        reference = self.coprocessor.resolve_reference(
            message_text=event.message.text,
            thread_ledger=thread_ledger,
            working_set=working_set,
        )
        if reference is not None:
            clarification_question = self._clarification_question_for_low_recall(
                normalized=normalized,
                thread_ledger=thread_ledger,
                reference_resolution=reference,
            )
            if clarification_question:
                return ConversationBrainDecision(
                    backend=ConversationBrainBackend.LOCAL,
                    resolution_kind="clarification_needed",
                    confidence=0.9,
                    reason="low_recall_confidence_requires_clarification",
                    selected_object_ids=list(working_set.selected_object_ids),
                    selected_artifact_ids=list(working_set.selected_artifact_ids),
                    metadata={"clarification_question": clarification_question},
                )
            return ConversationBrainDecision(
                backend=ConversationBrainBackend.LOCAL,
                resolution_kind=reference.resolution_kind,
                confidence=reference.confidence,
                target_type=reference.target_type,
                target_id=reference.target_id,
                reason=reference.reason,
                selected_object_ids=list(working_set.selected_object_ids),
                selected_artifact_ids=list(working_set.selected_artifact_ids),
            )
        if thread_ledger is not None:
            clarification_question = self._clarification_question_for_low_recall(
                normalized=normalized,
                thread_ledger=thread_ledger,
                reference_resolution=None,
            )
            if clarification_question:
                return ConversationBrainDecision(
                    backend=ConversationBrainBackend.LOCAL,
                    resolution_kind="clarification_needed",
                    confidence=0.88,
                    reason="ambiguous_followup_requires_clarification",
                    selected_object_ids=list(working_set.selected_object_ids),
                    selected_artifact_ids=list(working_set.selected_artifact_ids),
                    metadata={"clarification_question": clarification_question},
                )
        if thread_ledger is not None and thread_ledger.last_bundle_id and _contains_hint(
            normalized, ("compare", "comparaison", "contradiction", "les docs", "les document")
        ):
            return ConversationBrainDecision(
                backend=ConversationBrainBackend.LOCAL,
                resolution_kind="answer_about_active_bundle",
                confidence=0.78,
                target_type="bundle",
                target_id=thread_ledger.last_bundle_id,
                reason="active_bundle_reference",
                selected_object_ids=list(working_set.selected_object_ids),
                selected_artifact_ids=list(working_set.selected_artifact_ids),
            )
        if thread_ledger is not None and len(normalized.split()) <= 6 and thread_ledger.last_operator_reply_id:
            return ConversationBrainDecision(
                backend=ConversationBrainBackend.LOCAL,
                resolution_kind="continue_previous_answer",
                confidence=0.74,
                target_type="analysis_object" if working_set.selected_object_ids else None,
                target_id=working_set.selected_object_ids[0] if working_set.selected_object_ids else None,
                reason="short_followup_after_reply",
                selected_object_ids=list(working_set.selected_object_ids),
                selected_artifact_ids=list(working_set.selected_artifact_ids),
                needs_provider_fallback=True,
            )
        ambiguous_followup = (
            thread_ledger is not None
            and bool(thread_ledger.last_operator_reply_id or thread_ledger.last_artifact_id)
            and len(normalized.split()) <= 10
        )
        return ConversationBrainDecision(
            backend=ConversationBrainBackend.FALLBACK,
            resolution_kind="new_topic",
            confidence=0.35,
            reason="default_discussion",
            selected_object_ids=list(working_set.selected_object_ids),
            selected_artifact_ids=list(working_set.selected_artifact_ids),
            needs_provider_fallback=ambiguous_followup,
        )

    @classmethod
    def _clarification_question_for_low_recall(
        cls,
        *,
        normalized: str,
        thread_ledger: ThreadLedgerSnapshot | None,
        reference_resolution: ReferenceResolution | None,
    ) -> str | None:
        if thread_ledger is None:
            return None
        if not cls._looks_like_ambiguous_followup(normalized):
            return None
        has_recall_anchor = bool(
            thread_ledger.last_operator_reply_id
            or thread_ledger.last_authoritative_reply_summary
            or thread_ledger.last_pdf_artifact_id
            or thread_ledger.last_artifact_id
            or thread_ledger.last_bundle_id
        )
        if not has_recall_anchor:
            return None
        if reference_resolution is not None and reference_resolution.confidence >= 0.8:
            return None
        if len(normalized.split()) > 10:
            return None
        options: list[str] = []
        if thread_ledger.last_pdf_artifact_id:
            options.append("du dernier PDF")
        elif thread_ledger.last_authoritative_reply_summary:
            options.append("de ma derniere reponse")
        if thread_ledger.last_artifact_id and thread_ledger.last_artifact_id != thread_ledger.last_pdf_artifact_id:
            options.append("du dernier artefact")
        if not options:
            return "Tu parles de quel element exactement ?"
        if len(options) == 1:
            if options[0] == "de ma derniere reponse":
                return f"Tu parles {options[0]}, ou d'autre chose exactement ?"
            return None
        if len(options) == 2:
            return f"Tu parles {options[0]} ou {options[1]} exactement ?"
        return f"Tu parles {options[0]}, {options[1]}, ou d'autre chose exactement ?"

    @classmethod
    def _looks_like_ambiguous_followup(cls, normalized: str) -> bool:
        return _contains_hint(normalized, cls._AMBIGUOUS_FOLLOWUP_HINTS)

    def apply_to_candidate(self, *, candidate: ConversationMemoryCandidate, resolution: ConversationResolution) -> None:
        if not self.reliability.should_force_discussion(resolution):
            return
        candidate.classification = OperatorMessageKind.CHAT
        candidate.metadata["intent_kind"] = IntentKind.DISCUSSION.value
        candidate.metadata["delegation_level"] = "none"
        candidate.metadata["interaction_state"] = InteractionState.DISCUSSION.value
        candidate.metadata["suggested_next_state"] = InteractionState.DISCUSSION.value
        candidate.metadata["intent_confidence"] = max(float(candidate.metadata.get("intent_confidence") or 0.0), resolution.confidence)
        existing_signals = [str(item) for item in candidate.metadata.get("intent_signals") or [] if str(item) not in {"note_signal", "directive_implicit", "prepare_hint", "deliverable_hint"}]
        candidate.metadata["intent_signals"] = _dedupe([*existing_signals, "brain_followup"])
        directive_detection = dict(candidate.metadata.get("directive_detection") or {})
        directive_detection["likely_directive"] = False
        directive_detection["strength"] = "none"
        directive_detection["blocked_reason"] = "brain_followup_context"
        candidate.metadata["directive_detection"] = directive_detection


class ConversationReliabilityHarness:
    def __init__(self, *, database: CanonicalDatabase) -> None:
        self.database = database

    def record_reference_resolution(self, resolution: ReferenceResolution | None) -> None:
        if resolution is None:
            return
        self.database.upsert(
            "reference_resolutions",
            {
                "resolution_id": resolution.resolution_id,
                "resolution_kind": resolution.resolution_kind,
                "confidence": resolution.confidence,
                "surface": resolution.surface,
                "channel": resolution.channel,
                "thread_id": resolution.thread_id,
                "conversation_key": resolution.conversation_key,
                "message_id": resolution.message_id,
                "target_type": resolution.target_type,
                "target_id": resolution.target_id,
                "reason": resolution.reason,
                "metadata_json": dump_json(resolution.metadata),
                "created_at": resolution.created_at,
            },
            conflict_columns="resolution_id",
            immutable_columns=["created_at"],
        )
