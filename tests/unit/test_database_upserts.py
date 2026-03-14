from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.services import build_app_services


def _build_services(tmp_path: Path):
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
            "required_secret_names": [],
            "local_fallback_path": str(tmp_path / "secrets.json"),
        },
        "embedding_policy": {
            "provider_mode": "local_hash",
            "quality": "balanced",
            "local_model": "local-hash-v1",
            "local_dimensions": 64,
        },
        "api_dashboard_config": {
            "auto_start": False,
            "auto_open_browser": False,
        },
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
    return build_app_services(config_path=str(config_path), policy_path=str(policy_path))


class DatabaseUpsertTests(unittest.TestCase):
    def test_session_state_upsert_preserves_created_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                first = services.runtime.open_session(
                    session_id="session_fixed",
                    profile_name="core",
                    owner="founder",
                    status="ready",
                    metadata={"round": 1},
                )
                second = services.runtime.open_session(
                    session_id="session_fixed",
                    profile_name="core",
                    owner="founder",
                    status="busy",
                    metadata={"round": 2},
                )
                stored = services.runtime.get_session("session_fixed")

                self.assertEqual(stored.created_at, first.created_at)
                self.assertEqual(stored.updated_at, second.updated_at)
                self.assertEqual(stored.status, "busy")
                self.assertEqual(stored.metadata["round"], 2)
            finally:
                services.close()

    def test_composite_upsert_for_github_ingestion_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.database.upsert(
                    "github_issue_ingestions",
                    {
                        "repo": "Ga420Low/project-os-core",
                        "issue_number": 42,
                        "issue_id": "ISSUE_42",
                        "title": "Original title",
                        "state": "closed",
                        "labels_json": "[]",
                        "payload_sha256": "hash_a",
                        "updated_at": "2026-03-14T10:00:00+00:00",
                        "closed_at": "2026-03-14T09:00:00+00:00",
                        "ingested_at": "2026-03-14T10:05:00+00:00",
                        "learning_refs_json": "[]",
                        "metadata_json": "{}",
                    },
                    conflict_columns=["repo", "issue_number"],
                )
                services.database.upsert(
                    "github_issue_ingestions",
                    {
                        "repo": "Ga420Low/project-os-core",
                        "issue_number": 42,
                        "issue_id": "ISSUE_42",
                        "title": "Updated title",
                        "state": "closed",
                        "labels_json": "[\"task\"]",
                        "payload_sha256": "hash_b",
                        "updated_at": "2026-03-14T10:30:00+00:00",
                        "closed_at": "2026-03-14T09:00:00+00:00",
                        "ingested_at": "2026-03-14T10:35:00+00:00",
                        "learning_refs_json": "[{\"type\":\"signal\",\"id\":\"sig_1\"}]",
                        "metadata_json": "{\"url\":\"https://example.test/42\"}",
                    },
                    conflict_columns=["repo", "issue_number"],
                )

                rows = services.database.fetchall("SELECT * FROM github_issue_ingestions WHERE repo = ? AND issue_number = ?", ("Ga420Low/project-os-core", 42))

                self.assertEqual(len(rows), 1)
                self.assertEqual(str(rows[0]["title"]), "Updated title")
                self.assertEqual(str(rows[0]["payload_sha256"]), "hash_b")
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
