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
from project_os_core.models import ApprovalStatus, RuntimeState, RuntimeVerdict, new_id
from project_os_core.paths import PathPolicy, build_project_paths, ensure_project_roots
from project_os_core.runtime.journal import LocalJournal
from project_os_core.runtime.store import RuntimeStore
from project_os_core.secrets import SecretResolver


class RuntimeStoreTests(unittest.TestCase):
    def test_session_state_approval_and_evidence(self):
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
            journal = LocalJournal(database, paths.journal_file_path)
            runtime = RuntimeStore(database, paths, PathPolicy(paths), journal)

            session = runtime.open_session(profile_name="uefn", owner="founder")
            state = runtime.record_runtime_state(
                RuntimeState(
                    runtime_state_id=new_id("runtime_state"),
                    session_id=session.session_id,
                    verdict=RuntimeVerdict.READY,
                    active_profile="uefn",
                    status_summary="Session initialized.",
                )
            )
            approval = runtime.create_approval(
                requested_by="founder",
                risk_tier="destructive",
                reason="Need confirmation for a risky action.",
            )
            runtime.resolve_approval(approval.approval_id, ApprovalStatus.APPROVED)
            evidence = runtime.record_action_evidence(
                session_id=session.session_id,
                action_name="focus_window",
                success=True,
                summary="Focused the target window.",
                pre_state={"verdict": "ready"},
                post_state={"verdict": "ready"},
            )

            self.assertEqual(state.verdict, RuntimeVerdict.READY)
            self.assertEqual(approval.status, ApprovalStatus.PENDING)
            self.assertTrue(Path(evidence.artifacts[0].path).exists())
            self.assertTrue(paths.journal_file_path.exists())
            database.close()


if __name__ == "__main__":
    unittest.main()
