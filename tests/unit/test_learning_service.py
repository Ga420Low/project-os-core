from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.models import DecisionStatus, LearningSignalKind
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
            "required_secret_names": ["OPENAI_API_KEY"],
            "local_fallback_path": str(tmp_path / "secrets.json"),
        },
        "embedding_policy": {
            "provider_mode": "local_hash",
            "quality": "balanced",
            "local_model": "local-hash-v1",
            "local_dimensions": 64,
        },
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

    services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
    services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
    return services


class LearningServiceTests(unittest.TestCase):
    def test_decision_promotion_creates_memory_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                record = services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope="architecture",
                    summary="Keep OpenMemory as the primary memory engine.",
                    metadata={"source": "unit_test"},
                )
                self.assertEqual(record.status.value, "confirmed")
                memory_rows = services.database.fetchall("SELECT * FROM memory_records")
                self.assertEqual(len(memory_rows), 1)
            finally:
                services.close()

    def test_loop_and_refresh_signals_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                loop_signal = services.learning.record_loop_signal(
                    repeated_pattern="Repeated gateway redesign loop",
                    impacted_area="gateway",
                    recommended_reset="Reload the gateway docs and freeze the boundary again.",
                    source_ids=["run_1", "run_2"],
                )
                refresh = services.learning.recommend_refresh(
                    cause="Capability drift detected",
                    context_to_reload=["PROJECT_OS_MASTER_MACHINE.md"],
                    next_step="Pause and rebuild the context pack before coding more.",
                    source_ids=[loop_signal.loop_signal_id],
                )
                loop_rows = services.database.fetchall("SELECT * FROM loop_signals")
                refresh_rows = services.database.fetchall("SELECT * FROM refresh_recommendations")
                self.assertEqual(len(loop_rows), 1)
                self.assertEqual(len(refresh_rows), 1)
                self.assertEqual(refresh.cause, "Capability drift detected")
            finally:
                services.close()

    def test_gather_learning_context_returns_recent_lessons(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                branch_name = "codex/learning-branch"
                services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope=f"api_run:audit:{branch_name}",
                    summary="Keep the gateway boundary narrow.",
                    metadata={"branch_name": branch_name},
                )
                services.learning.record_signal(
                    kind=LearningSignalKind.PATCH_REJECTED,
                    severity="high",
                    summary=f"Rejected audit run for {branch_name}.",
                    metadata={"branch_name": branch_name},
                )
                services.learning.record_loop_signal(
                    repeated_pattern="Repeated review rejection",
                    impacted_area=branch_name,
                    recommended_reset="Reload docs before another patch.",
                )
                services.learning.recommend_refresh(
                    cause="Context is stale",
                    context_to_reload=["docs/architecture/QUALITY_STANDARDS.md"],
                    next_step="Refresh the context pack before rerunning.",
                )

                learning_context = services.learning.gather_learning_context(
                    mode="audit",
                    branch_name=branch_name,
                    objective="Audit the branch.",
                )

                self.assertEqual(len(learning_context["decisions"]), 1)
                self.assertEqual(len(learning_context["high_severity_signals"]), 1)
                self.assertEqual(len(learning_context["detected_loops"]), 1)
                self.assertEqual(len(learning_context["refresh_recommendations"]), 1)
                self.assertIn("1 decisions", learning_context["summary"])
            finally:
                services.close()

    def test_gather_learning_context_returns_empty_dict_without_lessons(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                learning_context = services.learning.gather_learning_context(
                    mode="audit",
                    branch_name="codex/no-learning",
                    objective="Audit the branch.",
                )
                self.assertEqual(learning_context, {})
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
