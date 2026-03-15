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
                artifact_path = services.paths.learning_decision_records_root / f"{record.decision_record_id}.json"
                self.assertTrue(artifact_path.exists())
            finally:
                services.close()

    def test_deferred_decision_writes_runtime_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                record = services.learning.record_deferred_decision(
                    scope="openclaw:pack2",
                    summary="Keep rich custom Discord business components out of scope until callbacks are unambiguous.",
                    next_trigger="when Discord component callbacks can carry a stable action id",
                    metadata={"pack": "pack_2"},
                )
                deferred_log = services.paths.learning_deferred_log_path
                self.assertTrue(deferred_log.exists())
                lines = deferred_log.read_text(encoding="utf-8").strip().splitlines()
                self.assertEqual(len(lines), 1)
                payload = json.loads(lines[0])
                self.assertEqual(payload["decision_record_id"], record.decision_record_id)
                self.assertEqual(payload["metadata"]["classification"], "deferred")
                self.assertIn("deferred_at", payload["metadata"])
                self.assertEqual(payload["metadata"]["next_trigger"], "when Discord component callbacks can carry a stable action id")
            finally:
                services.close()

    def test_list_deferred_decisions_filters_by_scope_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.learning.record_deferred_decision(
                    scope="openclaw:pack2:discord_operations_ux",
                    summary="Keep ambiguous business buttons out of scope.",
                    next_trigger="when callbacks carry a stable action id",
                )
                services.learning.record_deferred_decision(
                    scope="openclaw:pack4:privacy_guard",
                    summary="Keep S3 local-only routing for later.",
                    next_trigger="when the privacy guard contract is ready",
                )

                items = services.learning.list_deferred_decisions(scope_prefix="openclaw:pack2", limit=10)

                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["scope"], "openclaw:pack2:discord_operations_ux")
                self.assertEqual(items[0]["metadata"]["classification"], "deferred")
            finally:
                services.close()

    def test_sync_runbook_deferred_decisions_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                runbook_path = Path(tmp) / "OPENCLAW_DISCORD_OPERATIONS_UX.md"
                runbook_path.write_text(
                    "\n".join(
                        [
                            "# Pack 2",
                            "",
                            "```project-os-deferred",
                            "id: discord-business-components",
                            "scope: openclaw:pack2:discord_operations_ux",
                            "summary: Keep ambiguous Discord business buttons out of scope until callbacks are replay-safe.",
                            "next_trigger: when Discord callbacks carry a stable action id",
                            "```",
                        ]
                    ),
                    encoding="utf-8",
                )

                first_sync = services.learning.sync_runbook_deferred_decisions(glob_patterns=[str(runbook_path)])
                second_sync = services.learning.sync_runbook_deferred_decisions(glob_patterns=[str(runbook_path)])
                items = services.learning.list_deferred_decisions(scope_prefix="openclaw:pack2", limit=10)

                self.assertEqual(first_sync["created"], 1)
                self.assertEqual(second_sync["unchanged"], 1)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["metadata"]["source"], "runbook_sync")
                self.assertEqual(items[0]["metadata"]["runbook_item_id"], "discord-business-components")
            finally:
                services.close()

    def test_sync_runbook_deferred_absorbs_equivalent_manual_defer(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                manual_record = services.learning.record_deferred_decision(
                    scope="openclaw:pack2:discord_operations_ux",
                    summary="Keep ambiguous Discord business buttons out of scope until callbacks are replay-safe.",
                    next_trigger="when Discord callbacks carry a stable action id",
                )
                runbook_path = Path(tmp) / "OPENCLAW_DISCORD_OPERATIONS_UX.md"
                runbook_path.write_text(
                    "\n".join(
                        [
                            "# Pack 2",
                            "",
                            "```project-os-deferred",
                            "id: discord-business-components",
                            "scope: openclaw:pack2:discord_operations_ux",
                            "summary: Keep ambiguous Discord business buttons out of scope until callbacks are replay-safe.",
                            "next_trigger: when Discord callbacks carry a stable action id",
                            "```",
                        ]
                    ),
                    encoding="utf-8",
                )

                sync_payload = services.learning.sync_runbook_deferred_decisions(glob_patterns=[str(runbook_path)])
                items = services.learning.list_deferred_decisions(scope_prefix="openclaw:pack2", limit=10)

                self.assertEqual(sync_payload["updated"], 1)
                self.assertEqual(sync_payload["created"], 0)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0]["decision_record_id"], manual_record.decision_record_id)
                self.assertEqual(items[0]["metadata"]["source"], "runbook_sync")
            finally:
                services.close()

    def test_cleanup_duplicate_deferred_decisions_removes_non_canonical_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                manual_record = services.learning.record_deferred_decision(
                    scope="openclaw:pack2:discord_operations_ux",
                    summary="Keep ambiguous Discord business buttons out of scope until callbacks are replay-safe.",
                    next_trigger="when Discord callbacks carry a stable action id",
                )
                duplicate_record = services.learning.record_deferred_decision(
                    scope="openclaw:pack2:discord_operations_ux",
                    summary="Keep ambiguous Discord business buttons out of scope until callbacks are replay-safe.",
                    next_trigger="when Discord callbacks carry a stable action id",
                    metadata={"source": "runbook_sync"},
                )

                cleanup_payload = services.learning.cleanup_duplicate_deferred_decisions()
                items = services.learning.list_deferred_decisions(scope_prefix="openclaw:pack2", limit=10)

                self.assertEqual(cleanup_payload["duplicate_groups"], 1)
                self.assertEqual(cleanup_payload["removed_count"], 1)
                self.assertEqual(len(items), 1)
                self.assertNotEqual(items[0]["decision_record_id"], manual_record.decision_record_id)
                self.assertEqual(items[0]["decision_record_id"], duplicate_record.decision_record_id)
                manual_artifact = services.paths.learning_decision_records_root / f"{manual_record.decision_record_id}.json"
                self.assertFalse(manual_artifact.exists())
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
                branch_name = "project-os/learning-branch"
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
                services.learning.record_deferred_decision(
                    scope="openclaw:pack2:discord_operations_ux",
                    summary="Keep rich Discord business components out of scope until callbacks are replay-safe.",
                    next_trigger="when Discord callbacks carry a stable action id",
                    metadata={"pack": "pack_2"},
                )

                learning_context = services.learning.gather_learning_context(
                    mode="audit",
                    branch_name=branch_name,
                    objective="Audit the branch.",
                )

                self.assertEqual(len(learning_context["decisions"]), 1)
                self.assertEqual(len(learning_context["deferred_decisions"]), 1)
                self.assertEqual(len(learning_context["high_severity_signals"]), 1)
                self.assertEqual(len(learning_context["detected_loops"]), 1)
                self.assertEqual(len(learning_context["refresh_recommendations"]), 1)
                self.assertEqual(
                    learning_context["deferred_decisions"][0]["metadata"]["next_trigger"],
                    "when Discord callbacks carry a stable action id",
                )
                self.assertIn("1 decisions", learning_context["summary"])
                self.assertIn("1 deferred gaps", learning_context["summary"])
            finally:
                services.close()

    def test_gather_learning_context_auto_syncs_runbook_deferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                runbook_path = Path(tmp) / "OPENCLAW_DISCORD_OPERATIONS_UX.md"
                runbook_path.write_text(
                    "\n".join(
                        [
                            "# Pack 2",
                            "",
                            "```project-os-deferred",
                            "id: discord-business-components",
                            "scope: openclaw:pack2:discord_operations_ux",
                            "summary: Keep ambiguous Discord business buttons out of scope until callbacks are replay-safe.",
                            "next_trigger: when Discord callbacks carry a stable action id",
                            "```",
                        ]
                    ),
                    encoding="utf-8",
                )
                services.learning.auto_sync_runbook_deferred = True
                services.learning.runbook_deferred_globs = [str(runbook_path)]

                learning_context = services.learning.gather_learning_context(
                    mode="audit",
                    branch_name="project-os/no-learning",
                    objective="Audit what remains intentionally deferred.",
                )

                self.assertEqual(len(learning_context["deferred_decisions"]), 1)
                self.assertEqual(
                    learning_context["deferred_decisions"][0]["metadata"]["runbook_item_id"],
                    "discord-business-components",
                )
            finally:
                services.close()

    def test_gather_learning_context_returns_empty_dict_without_lessons(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                learning_context = services.learning.gather_learning_context(
                    mode="audit",
                    branch_name="project-os/no-learning",
                    objective="Audit the branch.",
                )
                self.assertEqual(learning_context, {})
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
