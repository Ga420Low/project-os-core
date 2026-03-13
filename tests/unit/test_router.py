from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.config import load_runtime_config
from project_os_core.database import CanonicalDatabase
from project_os_core.models import (
    ActionRiskClass,
    CostClass,
    MissionIntent,
    RuntimeState,
    RuntimeVerdict,
    new_id,
)
from project_os_core.paths import PathPolicy, build_project_paths, ensure_project_roots
from project_os_core.router.service import MissionRouter
from project_os_core.runtime.journal import LocalJournal
from project_os_core.runtime.store import RuntimeStore
from project_os_core.secrets import SecretResolver


class MissionRouterTests(unittest.TestCase):
    def _runtime_components(self, tmp_path: Path):
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
        config.secret_config.local_fallback_path = str(tmp_path / "secrets.json")
        paths = build_project_paths(config)
        ensure_project_roots(paths)
        database = CanonicalDatabase(paths.canonical_db_path)
        journal = LocalJournal(database, paths.journal_file_path)
        runtime = RuntimeStore(database, paths, PathPolicy(paths), journal)
        resolver = SecretResolver(config.secret_config, repo_root=config.repo_root)
        return config, paths, database, runtime, resolver

    def test_standard_route_uses_gpt54_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, paths, database, runtime, resolver = self._runtime_components(tmp_path)
            resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
            session = runtime.open_session(profile_name="browser", owner="founder")
            runtime.record_runtime_state(
                RuntimeState(
                    runtime_state_id=new_id("runtime_state"),
                    session_id=session.session_id,
                    verdict=RuntimeVerdict.READY,
                    active_profile="browser",
                )
            )
            router = MissionRouter(
                database=database,
                runtime=runtime,
                path_policy=PathPolicy(paths),
                secret_resolver=resolver,
                execution_policy=config.execution_policy,
            )
            intent = MissionIntent(
                intent_id=new_id("intent"),
                source="test",
                actor_id="founder",
                channel="cli",
                objective="Send a browser-based summary email",
                target_profile="browser",
                requested_worker="browser",
                requested_risk_class=ActionRiskClass.SAFE_WRITE,
            )

            decision, _, _ = router.route_intent(intent, persist=False)

            self.assertTrue(decision.allowed)
            self.assertEqual(decision.model_route.model, "gpt-5.4")
            self.assertEqual(decision.model_route.reasoning_effort, "high")
            self.assertEqual(decision.budget_state.mission_cost_class, CostClass.STANDARD)
            database.close()

    def test_exceptional_route_requires_founder_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, paths, database, runtime, resolver = self._runtime_components(tmp_path)
            resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
            session = runtime.open_session(profile_name="uefn", owner="founder")
            runtime.record_runtime_state(
                RuntimeState(
                    runtime_state_id=new_id("runtime_state"),
                    session_id=session.session_id,
                    verdict=RuntimeVerdict.READY,
                    active_profile="uefn",
                )
            )
            router = MissionRouter(
                database=database,
                runtime=runtime,
                path_policy=PathPolicy(paths),
                secret_resolver=resolver,
                execution_policy=config.execution_policy,
            )
            intent = MissionIntent(
                intent_id=new_id("intent"),
                source="test",
                actor_id="founder",
                channel="cli",
                objective="Delete old project outputs",
                target_profile="uefn",
                requested_worker="windows",
                requested_risk_class=ActionRiskClass.EXCEPTIONAL,
                metadata={"exceptional": True},
            )

            decision, _, _ = router.route_intent(intent, persist=False)
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.model_route.model, "gpt-5.4-pro")

            approved_intent = MissionIntent(
                intent_id=new_id("intent"),
                source="test",
                actor_id="founder",
                channel="cli",
                objective="Delete old project outputs",
                target_profile="uefn",
                requested_worker="windows",
                requested_risk_class=ActionRiskClass.EXCEPTIONAL,
                metadata={"exceptional": True, "founder_approved": True, "approval_id": "approval_1"},
            )
            approved_decision, _, _ = router.route_intent(approved_intent, persist=False)
            self.assertTrue(approved_decision.allowed)
            self.assertEqual(approved_decision.model_route.model, "gpt-5.4-pro")
            database.close()


if __name__ == "__main__":
    unittest.main()
