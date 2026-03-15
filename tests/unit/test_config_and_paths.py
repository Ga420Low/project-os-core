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
from project_os_core.embedding import choose_embedding_strategy
from project_os_core.paths import PathPolicy, build_project_paths, ensure_project_roots
from project_os_core.secrets import SecretResolver


class ConfigAndPathsTests(unittest.TestCase):
    def test_load_runtime_config_from_explicit_file(self):
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
            policy = PathPolicy(paths)

            self.assertTrue(paths.runtime_root.exists())
            self.assertTrue(paths.memory_blocks_root.exists())
            self.assertTrue(paths.memory_graph_root.exists())
            self.assertTrue(policy.is_forbidden(paths.archive_do_not_touch_root))
            self.assertTrue(policy.is_managed(paths.runtime_root))
            self.assertTrue(config.memory_config.retrieval_sidecar.enabled)
            self.assertTrue(config.memory_config.blocks.enabled)
            self.assertTrue(config.memory_config.curator.enabled)
            self.assertEqual(config.memory_config.temporal_graph.backend, "kuzu_embedded")
            with self.assertRaises(PermissionError):
                policy.ensure_allowed_write(paths.archive_do_not_touch_root / "blocked.json")

    def test_embedding_strategy_defaults_to_local_hash_without_key(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "",
                "PROJECT_OS_EMBED_PROVIDER": "local_hash",
                "PROJECT_OS_EMBED_MODEL": "",
                "PROJECT_OS_EMBED_DIMENSIONS": "",
            },
            clear=False,
        ):
            config = load_runtime_config()
            strategy = choose_embedding_strategy(config, SecretResolver(config.secret_config, repo_root=config.repo_root))
        self.assertEqual(strategy.provider, "local_hash")
        self.assertEqual(strategy.model, "local-hash-v1")


if __name__ == "__main__":
    unittest.main()
