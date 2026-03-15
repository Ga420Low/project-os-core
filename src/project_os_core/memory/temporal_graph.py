from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from ..config import MemoryTemporalGraphConfig
from ..database import CanonicalDatabase, dump_json
from ..models import new_id, utc_now_iso
from ..paths import PathPolicy, ProjectPaths


class TemporalGraphService:
    def __init__(
        self,
        database: CanonicalDatabase,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        config: MemoryTemporalGraphConfig,
    ) -> None:
        self.database = database
        self.paths = paths
        self.path_policy = path_policy
        self.config = config
        self.backend = str(config.backend or "kuzu_embedded")
        self.backend_status = self._resolve_backend_status()
        if self.config.strict_backend and self.backend_status != "kuzu_library_available_shadow_mode":
            raise RuntimeError(
                "Temporal graph strict_backend requires Kuzu availability; only sqlite shadow mode is available."
            )
        self.graph_root = self.path_policy.ensure_allowed_write(paths.memory_graph_root)
        self.graph_root.mkdir(parents=True, exist_ok=True)
        self.graph_path = self.graph_root / "project_os_graph.kuzu"

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "backend": self.backend,
            "backend_status": self.backend_status,
            "graph_path": str(self.graph_path),
        }

    def upsert_fact(
        self,
        *,
        entity: str,
        relation: str,
        value: str,
        source_ref: str,
        valid_at: str | None = None,
        invalid_at: str | None = None,
        episode_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now_iso()
        fact_id = new_id("graph_fact")
        self.database.upsert(
            "temporal_graph_facts",
            {
                "fact_id": fact_id,
                "episode_id": episode_id,
                "entity": entity,
                "relation": relation,
                "value": value,
                "valid_at": valid_at or now,
                "invalid_at": invalid_at,
                "source_ref": source_ref,
                "metadata_json": dump_json(metadata or {}),
                "created_at": now,
                "updated_at": now,
            },
            conflict_columns="fact_id",
            immutable_columns=["created_at"],
        )
        return self.get_fact(fact_id)

    def get_fact(self, fact_id: str) -> dict[str, Any]:
        row = self.database.fetchone("SELECT * FROM temporal_graph_facts WHERE fact_id = ?", (fact_id,))
        if row is None:
            raise KeyError(f"Unknown graph fact: {fact_id}")
        return self._row_to_fact(row)

    def facts_for(
        self,
        *,
        entity: str,
        relation: str | None = None,
        at_time: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit or self.config.max_results or 10), 50))
        sql = """
            SELECT * FROM temporal_graph_facts
            WHERE entity = ?
        """
        params: list[Any] = [entity]
        if relation:
            sql += " AND relation = ?"
            params.append(relation)
        if at_time:
            sql += " AND valid_at <= ? AND (invalid_at IS NULL OR invalid_at > ?)"
            params.extend([at_time, at_time])
        sql += " ORDER BY valid_at DESC, created_at DESC LIMIT ?"
        params.append(bounded_limit)
        rows = self.database.fetchall(sql, tuple(params))
        return [self._row_to_fact(row) for row in rows]

    def close(self) -> None:
        return None

    def _resolve_backend_status(self) -> str:
        if not self.config.enabled:
            return "disabled"
        if self.backend != "kuzu_embedded":
            return "sqlite_shadow"
        if importlib.util.find_spec("kuzu") is None:
            return "sqlite_shadow"
        return "kuzu_library_available_shadow_mode"

    @staticmethod
    def _row_to_fact(row) -> dict[str, Any]:
        return {
            "fact_id": str(row["fact_id"]),
            "episode_id": str(row["episode_id"]) if row["episode_id"] else None,
            "entity": str(row["entity"]),
            "relation": str(row["relation"]),
            "value": str(row["value"]),
            "valid_at": str(row["valid_at"]),
            "invalid_at": str(row["invalid_at"]) if row["invalid_at"] else None,
            "source_ref": str(row["source_ref"]),
            "metadata": json.loads(str(row["metadata_json"])) if row["metadata_json"] else {},
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
