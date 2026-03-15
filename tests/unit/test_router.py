from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.config import load_runtime_config
from project_os_core.database import CanonicalDatabase
from project_os_core.models import (
    ActionRiskClass,
    CommunicationMode,
    CostClass,
    ModelRouteClass,
    MissionIntent,
    OperatorAudience,
    OperatorMessageKind,
    RunSpeechPolicy,
    RuntimeState,
    RuntimeVerdict,
    SensitivityClass,
    new_id,
)
from project_os_core.paths import PathPolicy, build_project_paths, ensure_project_roots
from project_os_core.router.service import MissionRouter
from project_os_core.runtime.journal import LocalJournal
from project_os_core.runtime.store import RuntimeStore
from project_os_core.secrets import SecretResolver


class StubLocalModelClient:
    def __init__(self, *, status: str = "ready", reason: str = "model_ready") -> None:
        self.status = status
        self.reason = reason

    def health(self, *, force: bool = False) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "provider": "ollama",
            "model": "qwen2.5:14b",
            "base_url": "http://127.0.0.1:11434",
            "latency_ms": 12,
        }

    def chat(self, *, message: str, system: str, model: str | None = None):
        return SimpleNamespace(content="OK_LOCAL")


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
        config.execution_policy.local_model_enabled = False
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
            self.assertEqual(decision.model_route.route_tier, ModelRouteClass.API)
            self.assertEqual(decision.budget_state.mission_cost_class, CostClass.STANDARD)
            database.close()

    def test_discord_simple_chat_uses_medium_and_discussion_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, paths, database, runtime, resolver = self._runtime_components(tmp_path)
            resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
            session = runtime.open_session(profile_name="core", owner="founder")
            runtime.record_runtime_state(
                RuntimeState(
                    runtime_state_id=new_id("runtime_state"),
                    session_id=session.session_id,
                    verdict=RuntimeVerdict.READY,
                    active_profile="core",
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
                channel="discord",
                objective="Salut, tu peux me dire ou en est le run ?",
                target_profile="core",
                metadata={"message_kind": OperatorMessageKind.CHAT.value},
            )

            decision, _, _ = router.route_intent(intent, persist=False)

            self.assertTrue(decision.allowed)
            self.assertEqual(decision.model_route.provider, "anthropic")
            self.assertEqual(decision.model_route.model, "claude-sonnet-4-20250514")
            self.assertEqual(decision.model_route.reasoning_effort, "medium")
            self.assertEqual(decision.model_route.route_tier, ModelRouteClass.FAST)
            self.assertEqual(decision.communication_mode, CommunicationMode.DISCUSSION)
            self.assertEqual(decision.speech_policy, RunSpeechPolicy.DIALOGUE_RICH)
            self.assertEqual(decision.audience, OperatorAudience.NON_DEVELOPER)
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

    def test_model_stack_health_snapshot_reports_fast_local_api_tiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, paths, database, runtime, resolver = self._runtime_components(tmp_path)
            resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
            resolver.write_local_fallback("ANTHROPIC_API_KEY", "anthropic-test-secret")
            router = MissionRouter(
                database=database,
                runtime=runtime,
                path_policy=PathPolicy(paths),
                secret_resolver=resolver,
                execution_policy=config.execution_policy,
            )

            snapshot = router.model_stack_health_snapshot()

            self.assertEqual(snapshot["tiers"]["fast"]["status"], "ready")
            self.assertEqual(snapshot["tiers"]["local"]["status"], "absent")
            self.assertEqual(snapshot["tiers"]["api"]["status"], "ready")
            self.assertEqual(snapshot["providers"]["openai"]["available"], True)
            self.assertEqual(snapshot["providers"]["anthropic"]["available"], True)
            database.close()

    def test_prefer_local_model_escalates_to_api_when_local_missing(self):
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
                objective="Prepare a patch plan with local preference.",
                target_profile="browser",
                requested_worker="browser",
                metadata={"prefer_local_model": True},
            )

            decision, _, _ = router.route_intent(intent, persist=False)

            self.assertTrue(decision.allowed)
            self.assertEqual(decision.model_route.route_tier, ModelRouteClass.API)
            self.assertEqual(decision.model_route.reason, "local_unavailable_escalated_to_api")
            self.assertEqual(decision.model_route.model, "gpt-5.4")
            database.close()

    def test_s3_sensitive_route_blocks_without_local_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, paths, database, runtime, resolver = self._runtime_components(tmp_path)
            resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
            session = runtime.open_session(profile_name="core", owner="founder")
            runtime.record_runtime_state(
                RuntimeState(
                    runtime_state_id=new_id("runtime_state"),
                    session_id=session.session_id,
                    verdict=RuntimeVerdict.READY,
                    active_profile="core",
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
                channel="discord",
                objective="Token Discord: sk-secret-value-123456789",
                target_profile="core",
                metadata={"sensitivity_class": SensitivityClass.S3.value, "message_kind": OperatorMessageKind.CHAT.value},
            )

            decision, _, _ = router.route_intent(intent, persist=False)

            self.assertFalse(decision.allowed)
            self.assertEqual(decision.model_route.route_tier, ModelRouteClass.LOCAL)
            self.assertEqual(decision.model_route.reason, "s3_requires_local_model")
            database.close()

    def test_prefer_local_model_uses_local_route_when_runtime_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config, paths, database, runtime, resolver = self._runtime_components(tmp_path)
            config.execution_policy.local_model_enabled = True
            config.execution_policy.local_model_name = "qwen2.5:14b"
            session = runtime.open_session(profile_name="core", owner="founder")
            runtime.record_runtime_state(
                RuntimeState(
                    runtime_state_id=new_id("runtime_state"),
                    session_id=session.session_id,
                    verdict=RuntimeVerdict.READY,
                    active_profile="core",
                )
            )
            router = MissionRouter(
                database=database,
                runtime=runtime,
                path_policy=PathPolicy(paths),
                secret_resolver=resolver,
                execution_policy=config.execution_policy,
                local_model_client=StubLocalModelClient(),
            )
            intent = MissionIntent(
                intent_id=new_id("intent"),
                source="test",
                actor_id="founder",
                channel="cli",
                objective="Analyse localement cette note sensible.",
                target_profile="core",
                metadata={"prefer_local_model": True},
            )

            decision, _, _ = router.route_intent(intent, persist=False)
            snapshot = router.model_stack_health_snapshot()

            self.assertTrue(decision.allowed)
            self.assertEqual(decision.model_route.route_tier, ModelRouteClass.LOCAL)
            self.assertEqual(decision.model_route.provider, "local")
            self.assertEqual(decision.model_route.reason, "local_route")
            self.assertEqual(snapshot["tiers"]["local"]["status"], "ready")
            database.close()


if __name__ == "__main__":
    unittest.main()
