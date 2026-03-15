from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from ..artifacts import write_json_artifact
from ..config import RetrievalSidecarConfig
from ..database import CanonicalDatabase, dump_json
from ..embedding import EmbeddingService, EmbeddingStrategy
from ..models import MemoryRecord, MemoryTier, RetrievalContext, MemoryType, new_id, to_jsonable
from ..paths import PathPolicy, ProjectPaths
from ..secrets import SecretResolver
from .adapter import OpenMemoryAdapter
from .retrieval_sidecar import RetrievalSidecar


class MemoryStore:
    def __init__(
        self,
        database: CanonicalDatabase,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        embedding_strategy: EmbeddingStrategy,
        secret_resolver: SecretResolver,
        retrieval_sidecar_config: RetrievalSidecarConfig | None = None,
    ):
        self.database = database
        self.paths = paths
        self.path_policy = path_policy
        self.embedding_strategy = embedding_strategy
        self.secret_resolver = secret_resolver
        self.embedding_service = EmbeddingService(embedding_strategy, secret_resolver)
        self.openmemory = OpenMemoryAdapter(paths, embedding_strategy, secret_resolver)
        self.retrieval_sidecar_config = retrieval_sidecar_config or RetrievalSidecarConfig()
        self.retrieval_sidecar = RetrievalSidecar(self.database, self.retrieval_sidecar_config)
        self._tier_manager: Any | None = None
        self._memory_os: Any | None = None
        self._ensure_embedding_index_current()

    def attach_tier_manager(self, tier_manager: Any) -> None:
        self._tier_manager = tier_manager

    def attach_memory_os(self, memory_os: Any) -> None:
        self._memory_os = memory_os

    def remember(
        self,
        *,
        content: str,
        user_id: str,
        project_id: str | None = None,
        mission_id: str | None = None,
        memory_type: MemoryType = MemoryType.EPISODIC,
        tier: MemoryTier = MemoryTier.HOT,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord:
        metadata = dict(metadata or {})
        openmemory_enabled = self._openmemory_enabled(metadata)
        record = MemoryRecord(
            memory_id=new_id("memory"),
            user_id=user_id,
            project_id=project_id,
            mission_id=mission_id,
            content=content,
            memory_type=memory_type,
            tier=tier,
            tags=tags or [],
            metadata=metadata,
        )

        if openmemory_enabled and self.openmemory.status.available:
            try:
                added = self.openmemory.add_record(record)
                record.openmemory_id = added.get("id") or added.get("root_memory_id")
            except Exception as exc:
                self.openmemory.mark_unavailable(str(exc))
                record.metadata["openmemory_warning"] = str(exc)

        self.database.upsert(
            "memory_records",
            {
                "memory_id": record.memory_id,
                "openmemory_id": record.openmemory_id,
                "user_id": record.user_id,
                "project_id": record.project_id,
                "mission_id": record.mission_id,
                "content": record.content,
                "memory_type": record.memory_type.value,
                "tier": record.tier.value,
                "tags_json": dump_json(record.tags),
                "metadata_json": dump_json(record.metadata),
                "archived_artifact_path": record.archived_artifact_path,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            },
            conflict_columns="memory_id",
            immutable_columns=["created_at"],
        )
        try:
            vector = self._embed_for_record(content, record.metadata)
        except Exception as exc:
            vector = self.embedding_service._local_hash_embedding(content, self.database.vector_dimensions)
            if self._embedding_provider(record.metadata) != "local_hash":
                record.metadata["embedding_fallback"] = {
                    "provider": "local_hash",
                    "reason": str(exc),
                }
                self.database.execute(
                    """
                    UPDATE memory_records
                    SET metadata_json = ?, updated_at = ?
                    WHERE memory_id = ?
                    """,
                    (
                        dump_json(record.metadata),
                        record.updated_at,
                        record.memory_id,
                    ),
                )
        self.database.upsert_vector(
            record.memory_id,
            self.embedding_service.vector_literal(vector),
        )

        if tier is MemoryTier.WARM:
            artifact_path = self._persist_artifact(record, MemoryTier.WARM)
            record.archived_artifact_path = artifact_path
            self._update_archive_path(record)
        if tier is MemoryTier.COLD:
            record = self.move_to_cold(record.memory_id)
        elif self._tier_manager is not None:
            self._tier_manager.maybe_auto_archive(trigger=f"memory_remember:{tier.value}")

        return record

    def _update_archive_path(self, record: MemoryRecord) -> None:
        self.database.execute(
            """
            UPDATE memory_records
            SET archived_artifact_path = ?, updated_at = ?
            WHERE memory_id = ?
            """,
            (
                record.archived_artifact_path,
                record.updated_at,
                record.memory_id,
            ),
        )

    def _persist_artifact(self, record: MemoryRecord, target_tier: MemoryTier) -> str:
        artifact = write_json_artifact(
            paths=self.paths,
            path_policy=self.path_policy,
            owner_id=record.memory_id,
            artifact_kind="episode",
            storage_tier=target_tier,
            payload=to_jsonable(record),
        )
        self.database.upsert(
            "artifact_pointers",
            {
                "artifact_id": artifact.artifact_id,
                "owner_type": "memory_record",
                "owner_id": record.memory_id,
                "artifact_kind": artifact.artifact_kind,
                "storage_tier": artifact.storage_tier.value,
                "path": artifact.path,
                "checksum_sha256": artifact.checksum_sha256,
                "size_bytes": artifact.size_bytes,
                "created_at": artifact.created_at,
            },
            conflict_columns="artifact_id",
            immutable_columns=["created_at"],
        )
        return artifact.path

    def move_to_cold(self, memory_id: str) -> MemoryRecord:
        record = self.get(memory_id)
        archive_path = self._persist_artifact(record, MemoryTier.COLD)
        updated = replace(
            record,
            tier=MemoryTier.COLD,
            archived_artifact_path=archive_path,
        )
        self.database.execute(
            """
            UPDATE memory_records
            SET tier = ?, archived_artifact_path = ?, updated_at = ?
            WHERE memory_id = ?
            """,
            (
                updated.tier.value,
                updated.archived_artifact_path,
                updated.updated_at,
                updated.memory_id,
            ),
        )
        return updated

    def get(self, memory_id: str) -> MemoryRecord:
        row = self.database.fetchone("SELECT * FROM memory_records WHERE memory_id = ?", (memory_id,))
        if row is None:
            raise KeyError(f"Unknown memory_id: {memory_id}")
        return self._row_to_memory_record(row)

    def search(self, context: RetrievalContext) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]]
        if self.retrieval_sidecar_config.enabled:
            hits = self.retrieval_sidecar.apply(
                context=context,
                collect_base_hits=lambda query, limit: self._collect_base_hits(query, limit, context),
            )
        else:
            hits = self._collect_base_hits(context.query, context.limit, context)
        if self._memory_os is not None:
            return self._memory_os.enrich_search_results(context=context, hits=hits)
        return hits

    def _collect_base_hits(
        self,
        query: str,
        limit: int,
        context: RetrievalContext,
    ) -> list[dict[str, Any]]:
        hits: dict[str, dict[str, Any]] = {}
        try:
            query_vector = self.embedding_service.vector_literal(self.embedding_service.embed_text(query))
        except Exception:
            fallback = self.embedding_service._local_hash_embedding(query, self.database.vector_dimensions)
            query_vector = self.embedding_service.vector_literal(fallback)
        for row in self.database.search_vectors(query_vector, limit):
            record = self.get(str(row["memory_id"]))
            if not self._is_search_visible(record, context):
                continue
            hits[record.memory_id] = {
                "memory_id": record.memory_id,
                "_candidate_key": record.memory_id,
                "source": "sqlite_vec",
                "distance": float(row["distance"]),
                "record": to_jsonable(record),
            }

        if self.openmemory.status.available:
            try:
                query_context = replace(context, query=query, limit=limit)
                for result in self.openmemory.search(query_context):
                    result_id = result.get("id") or result.get("root_memory_id")
                    canonical = None
                    if result_id:
                        row = self.database.fetchone(
                            "SELECT memory_id FROM memory_records WHERE openmemory_id = ?",
                            (result_id,),
                        )
                        canonical = str(row["memory_id"]) if row else None
                    if canonical and canonical in hits:
                        hits[canonical]["source"] = "hybrid"
                        hits[canonical]["openmemory"] = result
                        continue
                    if canonical:
                        record = self.get(canonical)
                        if not self._is_search_visible(record, context):
                            continue
                        hits[canonical] = {
                            "memory_id": canonical,
                            "_candidate_key": canonical,
                            "source": "openmemory",
                            "record": to_jsonable(record),
                            "openmemory": result,
                        }
                        continue
                    orphan_id = new_id("memory_orphan")
                    hits[orphan_id] = {
                        "memory_id": orphan_id,
                        "_candidate_key": orphan_id,
                        "source": "openmemory_only",
                        "record": {
                            "content": result.get("content") or result.get("text"),
                            "user_id": context.user_id,
                            "metadata": {
                                "privacy_view": "clean",
                                "openmemory_only": True,
                            },
                        },
                        "openmemory": result,
                    }
            except Exception as exc:
                self.openmemory.mark_unavailable(str(exc))

        ordered = list(hits.values())
        ordered.sort(key=lambda item: item.get("distance", 0.0))
        return ordered[: limit]

    def reindex(self) -> dict[str, Any]:
        return self._ensure_embedding_index_current(force=True)

    def close(self) -> None:
        self.openmemory.close()

    def _ensure_embedding_index_current(self, force: bool = False) -> dict[str, Any]:
        signature = self.embedding_strategy.signature
        existing_signature = self.database.get_meta("embedding_strategy_signature")
        openmemory_signature = self.database.get_meta("openmemory_strategy_signature")
        reindex_state = self.database.get_meta("embedding_reindex_state")
        if reindex_state == "running":
            raise RuntimeError("Embedding reindex already running")
        rows = self.database.fetchall(
            """
            SELECT memory_id, openmemory_id, user_id, project_id, mission_id, content, memory_type, tier,
                   tags_json, metadata_json, archived_artifact_path, created_at, updated_at
            FROM memory_records
            ORDER BY created_at ASC
            """
        )
        rebuilt_canonical = False
        rebuilt_openmemory = False
        if not force and existing_signature == signature and openmemory_signature == signature:
            return {
                "status": "completed",
                "signature": signature,
                "canonical_rebuilt": False,
                "openmemory_rebuilt": False,
                "row_count": len(rows),
            }

        self.database.set_meta("embedding_reindex_state", "running")
        self.database.set_meta("embedding_reindex_failure_reason", "")
        try:
            if force or existing_signature != signature:
                with self.database.transaction() as connection:
                    if self.database.vector_enabled:
                        connection.execute("DELETE FROM memory_embeddings")
                        connection.execute("DELETE FROM memory_embedding_map")
                    for row in rows:
                        metadata = json.loads(str(row["metadata_json"]))
                        vector = self._embed_for_record(str(row["content"]), metadata)
                        self.database.upsert_vector(
                            str(row["memory_id"]),
                            self.embedding_service.vector_literal(vector),
                            connection=connection,
                        )
                    self.database.set_meta("embedding_strategy_signature", signature, connection=connection)
                rebuilt_canonical = True

            if self.openmemory.status.available and (force or openmemory_signature != signature):
                self.openmemory.reset_storage()
                self.openmemory = OpenMemoryAdapter(self.paths, self.embedding_strategy, self.secret_resolver)
                for row in rows:
                    record = self._row_to_memory_record(row)
                    if not self._openmemory_enabled(record.metadata):
                        self.database.execute(
                            "UPDATE memory_records SET openmemory_id = ?, updated_at = ? WHERE memory_id = ?",
                            (None, record.updated_at, record.memory_id),
                        )
                        continue
                    added = self.openmemory.add_record(record)
                    record.openmemory_id = added.get("id") or added.get("root_memory_id")
                    self.database.execute(
                        "UPDATE memory_records SET openmemory_id = ?, updated_at = ? WHERE memory_id = ?",
                        (record.openmemory_id, record.updated_at, record.memory_id),
                    )
                self.database.set_meta("openmemory_strategy_signature", signature)
                rebuilt_openmemory = True

            self.database.set_meta("embedding_reindex_state", "completed")
            self.database.set_meta("embedding_reindex_failure_reason", "")
            return {
                "status": "completed",
                "signature": signature,
                "canonical_rebuilt": rebuilt_canonical,
                "openmemory_rebuilt": rebuilt_openmemory,
                "row_count": len(rows),
            }
        except Exception as exc:
            self.database.set_meta("embedding_reindex_state", "failed")
            self.database.set_meta("embedding_reindex_failure_reason", str(exc))
            raise

    @staticmethod
    def _row_to_memory_record(row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=str(row["memory_id"]),
            openmemory_id=row["openmemory_id"],
            user_id=str(row["user_id"]),
            project_id=row["project_id"],
            mission_id=row["mission_id"],
            content=str(row["content"]),
            memory_type=MemoryType(str(row["memory_type"])),
            tier=MemoryTier(str(row["tier"])),
            tags=json.loads(row["tags_json"]),
            metadata=json.loads(row["metadata_json"]),
            archived_artifact_path=row["archived_artifact_path"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _embed_for_record(self, content: str, metadata: dict[str, Any]) -> list[float]:
        if self._embedding_provider(metadata) == "local_hash":
            return self.embedding_service._local_hash_embedding(content, self.database.vector_dimensions)
        return self.embedding_service.embed_text(content)

    @staticmethod
    def _embedding_provider(metadata: dict[str, Any]) -> str:
        provider = str(metadata.get("embedding_provider") or "").strip().lower()
        return provider or "default"

    @staticmethod
    def _openmemory_enabled(metadata: dict[str, Any]) -> bool:
        value = metadata.get("openmemory_enabled")
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _is_search_visible(record: MemoryRecord, context: RetrievalContext) -> bool:
        if context.include_private_full:
            return True
        return str(record.metadata.get("privacy_view") or "").strip().lower() != "full"
