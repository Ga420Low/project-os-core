from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.config import load_runtime_config
from project_os_core.database import CanonicalDatabase
from project_os_core.embedding import choose_embedding_strategy
from project_os_core.memory.store import MemoryStore
from project_os_core.models import MemoryTier, RetrievalContext
from project_os_core.paths import PathPolicy, build_project_paths, ensure_project_roots
from project_os_core.secrets import SecretResolver


class MemoryStoreTests(unittest.TestCase):
    def test_memory_round_trip_and_cold_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = {
                "runtime_root": str(tmp_path / "runtime"),
                "memory_hot_root": str(tmp_path / "memory_hot"),
                "memory_warm_root": str(tmp_path / "memory_warm"),
                "index_root": str(tmp_path / "indexes"),
                "session_root": str(tmp_path / "sessions"),
                "cache_root": str(tmp_path / "cache"),
                "archive_drive": "Z:",
                "archive_do_not_touch_root": str(tmp_path / "archive" / "DO_NOT_TOUCH"),
                "archive_root": str(tmp_path / "archive"),
                "archive_episodes_root": str(tmp_path / "archive" / "episodes"),
                "archive_evidence_root": str(tmp_path / "archive" / "evidence"),
                "archive_screens_root": str(tmp_path / "archive" / "screens"),
                "archive_reports_root": str(tmp_path / "archive" / "reports"),
                "archive_logs_root": str(tmp_path / "archive" / "logs"),
                "archive_snapshots_root": str(tmp_path / "archive" / "snapshots"),
            }
            config_path = tmp_path / "storage_roots.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_runtime_config(config_path)
            paths = build_project_paths(config)
            ensure_project_roots(paths)
            with patch.dict(os.environ, {"PROJECT_OS_EMBED_PROVIDER": "local_hash", "OPENAI_API_KEY": ""}, clear=False):
                resolver = SecretResolver(config.secret_config, repo_root=config.repo_root)
                strategy = choose_embedding_strategy(config, resolver)
            database = CanonicalDatabase(paths.canonical_db_path, vector_dimensions=strategy.dimensions)
            store = MemoryStore(database, paths, PathPolicy(paths), strategy, resolver)

            remembered = store.remember(
                content="The founder prefers Discord for remote supervision.",
                user_id="founder",
            )
            hits = store.search(RetrievalContext(query="remote supervision", user_id="founder", limit=3))
            cold = store.move_to_cold(remembered.memory_id)

            self.assertEqual(remembered.user_id, "founder")
            self.assertGreaterEqual(len(hits), 1)
            self.assertEqual(cold.tier, MemoryTier.COLD)
            self.assertTrue(Path(cold.archived_artifact_path).exists())
            store.close()
            database.close()


if __name__ == "__main__":
    unittest.main()
