from __future__ import annotations

import asyncio
import importlib
import os
import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from ..embedding import EmbeddingStrategy
from ..models import MemoryRecord, RetrievalContext
from ..paths import ProjectPaths
from ..secrets import SecretResolver


def _run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@dataclass(slots=True)
class OpenMemoryAdapterStatus:
    available: bool
    reason: str | None = None


class OpenMemoryAdapter:
    def __init__(self, paths: ProjectPaths, strategy: EmbeddingStrategy, secret_resolver: SecretResolver):
        self.paths = paths
        self.strategy = strategy
        self.secret_resolver = secret_resolver
        self.db_url = f"sqlite:///{self.paths.openmemory_db_path.as_posix()}"
        self._memory_cls = None
        self._status = self._initialize()

    def _initialize(self) -> OpenMemoryAdapterStatus:
        try:
            os.environ["OM_DB_URL"] = self.db_url
            if self.strategy.provider == "openai":
                os.environ["OM_EMBED_KIND"] = "openai"
                os.environ["OM_OPENAI_MODEL"] = self.strategy.model
                os.environ["OPENAI_API_KEY"] = self.secret_resolver.get_required("OPENAI_API_KEY")
            else:
                os.environ["OM_EMBED_KIND"] = "synthetic"
            os.environ["OM_VEC_DIM"] = str(self.strategy.dimensions)
            client_mod = importlib.import_module("openmemory.client")
            config_mod = importlib.import_module("openmemory.core.config")
            config_mod.env.database_url = self.db_url
            config_mod.env.emb_kind = os.environ["OM_EMBED_KIND"]
            config_mod.env.vec_dim = int(os.environ["OM_VEC_DIM"])
            config_mod.env.openai_model = os.environ.get("OM_OPENAI_MODEL")
            self._memory_cls = client_mod.Memory
            return OpenMemoryAdapterStatus(available=True)
        except Exception as exc:
            return OpenMemoryAdapterStatus(available=False, reason=str(exc))

    @property
    def status(self) -> OpenMemoryAdapterStatus:
        return self._status

    def mark_unavailable(self, reason: str) -> None:
        self._memory_cls = None
        self._status = OpenMemoryAdapterStatus(available=False, reason=reason)

    def _client(self, user_id: str):
        if not self._memory_cls:
            raise RuntimeError(self._status.reason or "OpenMemory is unavailable")
        return self._memory_cls(user=user_id)

    def add_record(self, record: MemoryRecord) -> dict[str, Any]:
        client = self._client(record.user_id)
        return _run_sync(
            client.add(
                record.content,
                user_id=record.user_id,
                tags=record.tags,
                meta=record.metadata,
            )
        )

    def search(self, context: RetrievalContext) -> list[dict[str, Any]]:
        client = self._client(context.user_id)
        return _run_sync(
            client.search(
                context.query,
                user_id=context.user_id,
                limit=context.limit,
                tags=context.tags,
            )
        )

    def close(self) -> None:
        try:
            core_db = importlib.import_module("openmemory.core.db")
            if getattr(core_db.db, "conn", None) is not None:
                core_db.db.conn.close()
                core_db.db.conn = None
        except Exception:
            return

    def reset_storage(self) -> None:
        self.close()
        try:
            for suffix in ("", "-shm", "-wal"):
                candidate = Path(f"{self.paths.openmemory_db_path}{suffix}")
                if candidate.exists():
                    candidate.unlink()
            return
        except PermissionError:
            pass

        if not self.paths.openmemory_db_path.exists():
            return

        connection = sqlite3.connect(str(self.paths.openmemory_db_path))
        try:
            tables = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
            for (table_name,) in tables:
                connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            connection.commit()
            connection.execute("VACUUM")
        finally:
            connection.close()
