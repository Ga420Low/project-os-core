from __future__ import annotations

import json
import math
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import MemoryThoughtsConfig, MemorySupersessionConfig
from ..database import CanonicalDatabase, dump_json
from ..models import MemoryLayer, ThoughtMemory, ThoughtMemoryStatus, new_id, utc_now_iso
from .os_service import MemoryOSService


class ThoughtMemoryService:
    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        memory_os: MemoryOSService,
        thoughts_config: MemoryThoughtsConfig,
        supersession_config: MemorySupersessionConfig,
    ) -> None:
        self.database = database
        self.memory_os = memory_os
        self.thoughts_config = thoughts_config
        self.supersession_config = supersession_config

    def create_thought(
        self,
        *,
        kind: str,
        summary: str,
        content: str,
        source_ids: list[str] | None = None,
        confidence: float = 0.75,
        metadata: dict[str, Any] | None = None,
        supersedes: list[str] | None = None,
        status: ThoughtMemoryStatus = ThoughtMemoryStatus.ACTIVE,
    ) -> ThoughtMemory:
        normalized_summary = str(summary).strip()
        normalized_content = str(content).strip()
        if not normalized_summary:
            raise ValueError("summary must not be empty")
        if not normalized_content:
            raise ValueError("content must not be empty")
        payload_metadata = dict(metadata or {})
        payload_metadata["privacy_view"] = str(payload_metadata.get("privacy_view") or "clean").strip().lower()
        cube = self.memory_os.create_cube(
            payload={"summary": normalized_summary, "content": normalized_content, "kind": kind},
            layer=MemoryLayer.THOUGHT,
            kind=kind,
            confidence=confidence,
            supersedes=list(supersedes or []),
            sources=list(source_ids or []),
            access_scope=str(payload_metadata.get("privacy_view") or "clean"),
            metadata={"source": "thought_memory", **payload_metadata},
        )
        payload_metadata.setdefault("cube_id", cube.cube_id)
        thought = ThoughtMemory(
            thought_id=new_id("thought"),
            kind=kind,
            summary=normalized_summary,
            content=normalized_content,
            source_ids=list(source_ids or []),
            confidence=max(0.0, min(1.0, float(confidence))),
            status=status,
            supersedes=list(supersedes or []),
            metadata=payload_metadata,
        )
        self.database.upsert(
            "thought_memories",
            {
                "thought_id": thought.thought_id,
                "kind": thought.kind,
                "summary": thought.summary,
                "content": thought.content,
                "confidence": thought.confidence,
                "status": thought.status.value,
                "source_ids_json": dump_json(thought.source_ids),
                "supersedes_json": dump_json(thought.supersedes),
                "metadata_json": dump_json(thought.metadata),
                "created_at": thought.created_at,
                "updated_at": thought.updated_at,
            },
            conflict_columns="thought_id",
            immutable_columns=["created_at"],
        )
        self.memory_os.trace_operation(
            operation="thought_inserted",
            target_type="thought_memory",
            target_id=thought.thought_id,
            detail={"kind": kind, "source_ids": thought.source_ids, "cube_id": cube.cube_id},
        )
        return thought

    def list_thoughts(
        self,
        *,
        status: ThoughtMemoryStatus | None = ThoughtMemoryStatus.ACTIVE,
        limit: int = 20,
    ) -> list[ThoughtMemory]:
        sql = "SELECT * FROM thought_memories"
        params: list[Any] = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        rows = self.database.fetchall(sql, tuple(params))
        return [self._row_to_thought(row) for row in rows]

    def search(self, *, query: str, limit: int = 5, include_private_full: bool = False) -> list[ThoughtMemory]:
        candidates = self.list_thoughts(status=ThoughtMemoryStatus.ACTIVE, limit=max(10, limit * 4))
        scored: list[tuple[float, ThoughtMemory]] = []
        query_tokens = self._tokenize(query)
        for thought in candidates:
            if float(thought.confidence) < float(self.thoughts_config.min_confidence):
                continue
            privacy_view = str(thought.metadata.get("privacy_view") or "clean").strip().lower()
            if privacy_view == "full" and not include_private_full:
                continue
            base = self._token_overlap_score(query_tokens, self._tokenize(f"{thought.summary} {thought.content}"))
            if base <= 0.0:
                continue
            recency = self._recency_score(thought.updated_at)
            score = (thought.confidence * 0.55) + (base * 0.35) + (recency * 0.10)
            scored.append((score, thought))
        scored.sort(key=lambda item: (-item[0], item[1].updated_at, item[1].thought_id))
        return [item[1] for item in scored[: max(1, limit)]]

    def supersede_thought(
        self,
        *,
        old_thought_id: str,
        reason: str,
        replacement_kind: str,
        replacement_summary: str,
        replacement_content: str,
        source_ids: list[str] | None = None,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
    ) -> ThoughtMemory:
        current = self.get_thought(old_thought_id)
        replacement = self.create_thought(
            kind=replacement_kind,
            summary=replacement_summary,
            content=replacement_content,
            source_ids=list(source_ids or current.source_ids),
            confidence=confidence,
            metadata=metadata,
            supersedes=[old_thought_id, *current.supersedes],
        )
        now = utc_now_iso()
        self.database.execute(
            """
            UPDATE thought_memories
            SET status = ?, updated_at = ?
            WHERE thought_id = ?
            """,
            (ThoughtMemoryStatus.SUPERSEDED.value, now, old_thought_id),
        )
        self.memory_os.record_supersession(
            superseded_type="thought_memory",
            superseded_id=old_thought_id,
            superseding_type="thought_memory",
            superseding_id=replacement.thought_id,
            reason=reason,
            metadata={"replacement_kind": replacement.kind},
        )
        self.memory_os.trace_operation(
            operation="thought_merged",
            target_type="thought_memory",
            target_id=replacement.thought_id,
            detail={"supersedes": old_thought_id, "reason": reason},
        )
        return replacement

    def scan_for_supersession(self) -> dict[str, Any]:
        if not self.supersession_config.enabled:
            return {"superseded": [], "count": 0, "skipped": "disabled"}
        thoughts = self.list_thoughts(status=ThoughtMemoryStatus.ACTIVE, limit=100)
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(self.supersession_config.recent_window_hours)))
        replacements: list[dict[str, Any]] = []
        by_kind: dict[str, list[ThoughtMemory]] = {}
        for thought in thoughts:
            try:
                updated_at = datetime.fromisoformat(thought.updated_at)
            except ValueError:
                updated_at = None
            if updated_at is not None and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if updated_at is not None and updated_at < recent_cutoff:
                continue
            by_kind.setdefault(thought.kind, []).append(thought)
        threshold = float(self.supersession_config.similarity_threshold)
        for items in by_kind.values():
            ordered = sorted(items, key=lambda item: (item.updated_at, item.thought_id))[-max(2, int(self.thoughts_config.max_merge_candidates)) :]
            for older, newer in zip(ordered, ordered[1:]):
                similarity = self._text_similarity(
                    f"{older.summary}\n{older.content}",
                    f"{newer.summary}\n{newer.content}",
                )
                if similarity < threshold:
                    continue
                if older.thought_id in newer.supersedes:
                    continue
                self._mark_superseded_with_existing(
                    old_thought_id=older.thought_id,
                    replacement_id=newer.thought_id,
                    reason="automatic_supersession_scan",
                )
                replacements.append(
                    {
                        "superseded": older.thought_id,
                        "replacement": newer.thought_id,
                        "similarity": similarity,
                    }
                )
        return {"superseded": replacements, "count": len(replacements)}

    def get_thought(self, thought_id: str) -> ThoughtMemory:
        row = self.database.fetchone("SELECT * FROM thought_memories WHERE thought_id = ?", (thought_id,))
        if row is None:
            raise KeyError(f"Unknown thought memory: {thought_id}")
        return self._row_to_thought(row)

    def _mark_superseded_with_existing(self, *, old_thought_id: str, replacement_id: str, reason: str) -> None:
        now = utc_now_iso()
        self.database.execute(
            """
            UPDATE thought_memories
            SET status = ?, updated_at = ?
            WHERE thought_id = ?
            """,
            (ThoughtMemoryStatus.SUPERSEDED.value, now, old_thought_id),
        )
        self.memory_os.record_supersession(
            superseded_type="thought_memory",
            superseded_id=old_thought_id,
            superseding_type="thought_memory",
            superseding_id=replacement_id,
            reason=reason,
        )
        self.memory_os.trace_operation(
            operation="thought_merged",
            target_type="thought_memory",
            target_id=replacement_id,
            detail={"supersedes": old_thought_id, "reason": reason},
        )

    def _row_to_thought(self, row) -> ThoughtMemory:
        return ThoughtMemory(
            thought_id=str(row["thought_id"]),
            kind=str(row["kind"]),
            summary=str(row["summary"]),
            content=str(row["content"]),
            source_ids=json.loads(str(row["source_ids_json"])) if row["source_ids_json"] else [],
            confidence=float(row["confidence"]),
            status=ThoughtMemoryStatus(str(row["status"])),
            supersedes=json.loads(str(row["supersedes_json"])) if row["supersedes_json"] else [],
            metadata=json.loads(str(row["metadata_json"])) if row["metadata_json"] else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        return {token for token in re.findall(r"[a-zA-Z0-9_/-]{3,}", value.lower())}

    @classmethod
    def _token_overlap_score(cls, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        overlap = left & right
        if not overlap:
            return 0.0
        return len(overlap) / max(len(left), len(right))

    @staticmethod
    def _recency_score(updated_at: str) -> float:
        try:
            updated = datetime.fromisoformat(updated_at)
        except ValueError:
            return 0.0
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 3600.0)
        return max(0.0, min(1.0, math.exp(-age_hours / 168.0)))

    @classmethod
    def _text_similarity(cls, left: str, right: str) -> float:
        left_tokens = cls._tokenize(left)
        right_tokens = cls._tokenize(right)
        token_score = 0.0
        if left_tokens and right_tokens:
            token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        sequence_score = SequenceMatcher(None, left.lower(), right.lower()).ratio()
        return max(token_score, sequence_score)
