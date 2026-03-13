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
from project_os_core.services import build_app_services


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

    def test_tier_manager_compacts_warm_records_to_cold_and_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            storage_payload = {
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
            config_path.write_text(json.dumps(storage_payload), encoding="utf-8")
            policy_payload = {
                "secret_config": {
                    "mode": "infisical_first",
                    "required_secret_names": ["OPENAI_API_KEY"],
                    "local_fallback_path": str(tmp_path / "secrets.json"),
                },
                "embedding_policy": {
                    "provider_mode": "local_hash",
                    "quality": "balanced",
                    "local_model": "local-hash-v1",
                    "local_dimensions": 64,
                },
                "tier_manager_config": {
                    "enabled": True,
                    "auto_archive_on_write": False,
                    "warm_min_age_hours": 6,
                    "keep_latest_warm_records": 1,
                    "max_archive_batch_size": 16,
                },
            }
            policy_path = tmp_path / "runtime_policy.json"
            policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

            services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
            try:
                services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
                first = services.memory.remember(
                    content="First durable lesson.",
                    user_id="founder",
                    tier=MemoryTier.WARM,
                )
                second = services.memory.remember(
                    content="Second durable lesson.",
                    user_id="founder",
                    tier=MemoryTier.WARM,
                )
                latest = services.memory.remember(
                    content="Latest working memory.",
                    user_id="founder",
                    tier=MemoryTier.WARM,
                )
                old_ts = "2026-03-01T00:00:00+00:00"
                services.database.execute(
                    """
                    UPDATE memory_records
                    SET created_at = ?, updated_at = ?
                    WHERE memory_id IN (?, ?)
                    """,
                    (old_ts, old_ts, first.memory_id, second.memory_id),
                )
                report = services.tier_manager.compact(trigger="test_manual_compact")
                rows = {
                    str(row["memory_id"]): dict(row)
                    for row in services.database.fetchall(
                        "SELECT memory_id, tier, archived_artifact_path FROM memory_records"
                    )
                }

                self.assertEqual(report["archived_count"], 2)
                self.assertEqual(rows[first.memory_id]["tier"], MemoryTier.COLD.value)
                self.assertEqual(rows[second.memory_id]["tier"], MemoryTier.COLD.value)
                self.assertEqual(rows[latest.memory_id]["tier"], MemoryTier.WARM.value)
                self.assertTrue(str(rows[first.memory_id]["archived_artifact_path"]).startswith(str(tmp_path / "archive")))
                self.assertTrue(services.tier_manager.report_path().exists())
            finally:
                services.close()

    def test_tier_manager_can_auto_archive_on_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            storage_payload = {
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
            config_path.write_text(json.dumps(storage_payload), encoding="utf-8")
            policy_payload = {
                "secret_config": {
                    "mode": "infisical_first",
                    "required_secret_names": ["OPENAI_API_KEY"],
                    "local_fallback_path": str(tmp_path / "secrets.json"),
                },
                "embedding_policy": {
                    "provider_mode": "local_hash",
                    "quality": "balanced",
                    "local_model": "local-hash-v1",
                    "local_dimensions": 64,
                },
                "tier_manager_config": {
                    "enabled": True,
                    "auto_archive_on_write": True,
                    "warm_min_age_hours": 0,
                    "keep_latest_warm_records": 1,
                    "max_archive_batch_size": 16,
                },
            }
            policy_path = tmp_path / "runtime_policy.json"
            policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

            services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
            try:
                services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
                first = services.memory.remember(
                    content="Old warm memory to archive automatically.",
                    user_id="founder",
                    tier=MemoryTier.WARM,
                )
                old_ts = "2026-03-01T00:00:00+00:00"
                services.database.execute(
                    "UPDATE memory_records SET created_at = ?, updated_at = ? WHERE memory_id = ?",
                    (old_ts, old_ts, first.memory_id),
                )
                latest = services.memory.remember(
                    content="Newest warm memory should stay on SSD.",
                    user_id="founder",
                    tier=MemoryTier.WARM,
                )
                rows = {
                    str(row["memory_id"]): dict(row)
                    for row in services.database.fetchall(
                        "SELECT memory_id, tier, archived_artifact_path FROM memory_records"
                    )
                }

                self.assertEqual(rows[first.memory_id]["tier"], MemoryTier.COLD.value)
                self.assertEqual(rows[latest.memory_id]["tier"], MemoryTier.WARM.value)
                self.assertTrue(Path(str(rows[first.memory_id]["archived_artifact_path"])).exists())
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
