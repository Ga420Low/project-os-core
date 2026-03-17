from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.models import DecisionStatus, RetrievalContext, ThoughtMemoryStatus
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
        "memory": {
            "curator": {
                "llm_mode": "disabled",
                "async_enabled": True,
                "lookback_hours": 48,
            }
        },
        "api_dashboard_config": {
            "auto_start": False,
            "auto_open_browser": False,
        },
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
    return build_app_services(config_path=str(config_path), policy_path=str(policy_path))


class MemoryOSTests(unittest.TestCase):
    def test_shared_block_is_readable_across_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                block = services.memory_blocks.upsert_block(
                    block_name="runtime/discord_state.md",
                    content="# Discord State\n\n- shared state\n",
                    owner_role="operator_concierge",
                    updated_by_role="system",
                    reason="unit_test",
                    provenance=["test:shared_block"],
                    surface="scheduler",
                )

                discord_view = services.memory_blocks.read_block_content(
                    block.block_name,
                    reader_role="discord",
                    surface="discord",
                )
                guardian_view = services.memory_blocks.read_block_content(block.block_name, reader_role="guardian")

                self.assertIn("shared state", discord_view)
                self.assertEqual(discord_view, guardian_view)
            finally:
                services.close()

    def test_block_noop_update_does_not_bump_version_or_create_extra_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                first = services.memory_blocks.upsert_block(
                    block_name="runtime/mission_state.md",
                    content="# Mission State\n\n- unchanged\n",
                    owner_role="executor_coordinator",
                    updated_by_role="system",
                    reason="unit_test",
                    provenance=["test:noop"],
                    surface="scheduler",
                )
                revisions_before = services.database.fetchall(
                    "SELECT * FROM memory_block_revisions WHERE block_id = ? ORDER BY version ASC",
                    (first.block_id,),
                )
                second = services.memory_blocks.upsert_block(
                    block_name="runtime/mission_state.md",
                    content="# Mission State\n\n- unchanged\n",
                    owner_role="executor_coordinator",
                    updated_by_role="system",
                    reason="unit_test_repeat",
                    provenance=["test:noop"],
                    surface="scheduler",
                )

                revisions = services.database.fetchall(
                    "SELECT * FROM memory_block_revisions WHERE block_id = ? ORDER BY version ASC",
                    (first.block_id,),
                )

                self.assertEqual(first.version, second.version)
                self.assertEqual(len(revisions), len(revisions_before))
            finally:
                services.close()

    def test_block_surface_policy_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                with self.assertRaises(PermissionError):
                    services.memory_blocks.read_block_content(
                        "runtime/uefn_state.md",
                        reader_role="guardian",
                        surface="discord",
                    )
            finally:
                services.close()

    def test_block_size_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                oversize = "x" * (services.config.memory_config.blocks.max_block_bytes + 1)
                with self.assertRaises(ValueError):
                    services.memory_blocks.upsert_block(
                        block_name="runtime/discord_state.md",
                        content=oversize,
                        owner_role="operator_concierge",
                        updated_by_role="system",
                        reason="oversize",
                        surface="cli",
                    )
            finally:
                services.close()

    def test_curator_generates_thought_memory_from_recent_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope="memory_os:test",
                    summary="Keep Project OS as the canonical brain.",
                )

                payload = services.curator.run_sleeptime(trigger="unit_test", async_mode=False)
                thoughts = services.thoughts.list_thoughts(limit=10)

                self.assertEqual(payload["status"], "completed")
                self.assertGreaterEqual(len(thoughts), 1)
                self.assertIn("canonical brain", thoughts[0].summary.lower())
            finally:
                services.close()

    def test_curator_is_idempotent_for_same_window_and_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope="memory_os:idempotence",
                    summary="Do not duplicate the same thought twice.",
                )

                first = services.curator.run_sleeptime(trigger="unit_test", async_mode=False)
                second = services.curator.run_sleeptime(trigger="unit_test", async_mode=False)

                self.assertEqual(first["status"], "completed")
                self.assertEqual(second["status"], "skipped")
                self.assertEqual(second["reason"], "idempotent_window")
            finally:
                services.close()

    def test_supersession_keeps_history_and_marks_old_thought(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                older = services.thoughts.create_thought(
                    kind="fix",
                    summary="Restart the gateway after stale socket.",
                    content="Restart the gateway after stale socket.",
                    source_ids=["signal_1"],
                    confidence=0.7,
                )
                newer = services.thoughts.create_thought(
                    kind="fix",
                    summary="Restart gateway after stale socket disconnect.",
                    content="Restart gateway after stale socket disconnect.",
                    source_ids=["signal_2"],
                    confidence=0.9,
                )

                result = services.thoughts.scan_for_supersession()
                refreshed = services.thoughts.get_thought(older.thought_id)

                self.assertEqual(result["count"], 1)
                self.assertEqual(refreshed.status, ThoughtMemoryStatus.SUPERSEDED)
                supersession_rows = services.database.fetchall("SELECT * FROM supersession_records")
                self.assertEqual(len(supersession_rows), 1)
                self.assertEqual(str(supersession_rows[0]["superseding_id"]), newer.thought_id)
            finally:
                services.close()

    def test_dual_layer_profile_returns_stable_and_recent_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.memory_blocks.upsert_block(
                    block_name="profiles/founder_stable_profile.md",
                    content="# Founder Stable Profile\n\n- prefer concrete tradeoffs\n",
                    owner_role="guardian",
                    updated_by_role="system",
                    reason="unit_test",
                    provenance=["test:dual_layer"],
                )
                services.memory_blocks.upsert_block(
                    block_name="profiles/recent_operating_context.md",
                    content="# Recent Operating Context\n\n- testing discord memory flow\n",
                    owner_role="memory_curator",
                    updated_by_role="system",
                    reason="unit_test",
                    provenance=["test:dual_layer"],
                )

                profile = services.memory_os.dual_layer_profile()

                self.assertIn("prefer concrete tradeoffs", profile["stable"])
                self.assertIn("testing discord memory flow", profile["recent"])
            finally:
                services.close()

    def test_temporal_graph_answers_queries_at_specific_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.temporal_graph.upsert_fact(
                    entity="uefn_layout",
                    relation="mode",
                    value="fullscreen",
                    source_ref="decision_1",
                    valid_at="2026-03-10T10:00:00+00:00",
                    invalid_at="2026-03-12T10:00:00+00:00",
                )
                services.temporal_graph.upsert_fact(
                    entity="uefn_layout",
                    relation="mode",
                    value="split",
                    source_ref="decision_2",
                    valid_at="2026-03-12T10:00:00+00:00",
                )

                old_view = services.temporal_graph.facts_for(
                    entity="uefn_layout",
                    relation="mode",
                    at_time="2026-03-11T10:00:00+00:00",
                )
                new_view = services.temporal_graph.facts_for(
                    entity="uefn_layout",
                    relation="mode",
                    at_time="2026-03-13T10:00:00+00:00",
                )

                self.assertEqual(old_view[0]["value"], "fullscreen")
                self.assertEqual(new_view[0]["value"], "split")
            finally:
                services.close()

    def test_memory_search_prefers_thought_memory_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.memory.remember(
                    content="Gateway stale socket incident on Discord reconnect.",
                    user_id="project_os",
                    metadata={"privacy_view": "clean", "openmemory_enabled": False},
                )
                services.thoughts.create_thought(
                    kind="incident_fix",
                    summary="Gateway stale socket fix",
                    content="Restart the gateway when a stale socket disconnect is detected.",
                    source_ids=["signal_1"],
                    confidence=0.9,
                )

                hits = services.memory.search(
                    RetrievalContext(
                        query="gateway stale socket fix",
                        user_id="project_os",
                        channel="discord",
                        surface="discord",
                        limit=5,
                    )
                )

                self.assertGreaterEqual(len(hits), 2)
                self.assertEqual(hits[0]["source"], "thought_memory")
            finally:
                services.close()

    def test_memory_search_respects_limit_after_thought_enrichment(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                for index in range(4):
                    services.memory.remember(
                        content=f"Gateway issue #{index}",
                        user_id="project_os",
                        metadata={"privacy_view": "clean", "openmemory_enabled": False},
                    )
                services.thoughts.create_thought(
                    kind="incident_fix",
                    summary="Gateway fix",
                    content="Restart the gateway cleanly.",
                    source_ids=["signal_limit"],
                    confidence=0.92,
                )

                hits = services.memory.search(
                    RetrievalContext(
                        query="gateway fix",
                        user_id="project_os",
                        channel="discord",
                        surface="discord",
                        limit=3,
                    )
                )

                self.assertEqual(len(hits), 3)
                self.assertEqual(hits[0]["source"], "thought_memory")
            finally:
                services.close()

    def test_private_full_thoughts_are_hidden_from_default_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.thoughts.create_thought(
                    kind="secret",
                    summary="Sensitive private full thought",
                    content="OPENAI_API_KEY=hidden",
                    source_ids=["secret_signal"],
                    confidence=0.9,
                    metadata={"privacy_view": "full"},
                )

                hidden = services.thoughts.search(query="private full thought", include_private_full=False)
                visible = services.thoughts.search(query="private full thought", include_private_full=True)

                self.assertEqual(hidden, [])
                self.assertEqual(len(visible), 1)
            finally:
                services.close()

    def test_memory_traces_capture_block_write_and_recall_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                block = services.memory_blocks.upsert_block(
                    block_name="runtime/mission_state.md",
                    content="# Mission State\n\n- traced write\n",
                    owner_role="executor_coordinator",
                    updated_by_role="system",
                    reason="unit_test",
                    provenance=["test:trace"],
                    surface="scheduler",
                )
                plan = services.memory_os.build_recall_plan(
                    context=RetrievalContext(
                        query="mission state",
                        user_id="project_os",
                        project_id="proj_1",
                        branch_name="codex/project-os-test",
                        channel="discord",
                        surface="discord",
                    ),
                    reason="unit_test",
                )

                trace_rows = services.database.fetchall("SELECT * FROM memory_operation_traces ORDER BY created_at ASC")
                operations = [str(row["operation"]) for row in trace_rows]

                self.assertGreaterEqual(len(trace_rows), 2)
                self.assertIn("block_write", operations)
                self.assertEqual(str(trace_rows[-1]["operation"]), "recall_plan_built")
                self.assertEqual(plan.reason, "unit_test")
            finally:
                services.close()

    def test_project_continuity_brief_is_bounded_and_hides_private_thoughts(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.memory_blocks.upsert_block(
                    block_name="profiles/founder_stable_profile.md",
                    content="# Founder Stable Profile\n\n- garder une facade Discord naturelle\n",
                    owner_role="guardian",
                    updated_by_role="system",
                    reason="unit_test",
                    provenance=["test:project_continuity"],
                )
                services.memory_blocks.upsert_block(
                    block_name="profiles/recent_operating_context.md",
                    content="# Recent Operating Context\n\n- pack 4 ferme, pack 5 en cours\n",
                    owner_role="memory_curator",
                    updated_by_role="system",
                    reason="unit_test",
                    provenance=["test:project_continuity"],
                )
                current = services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope="gateway:discord_facade",
                    summary="Keep the Discord facade natural and readable.",
                    metadata={"branch_name": "codex/discord-facade"},
                )
                old = services.learning.record_decision(
                    status=DecisionStatus.CONFIRMED,
                    scope="gateway:legacy",
                    summary="Legacy noisy disclosure should stay visible everywhere.",
                )
                services.learning.record_deferred_decision(
                    scope="gateway:pack5",
                    summary="Brancher la suite d evals conversationnelles.",
                    next_trigger="quand le seam de continuite projet est stable",
                    metadata={"branch_name": "codex/discord-facade"},
                )
                services.thoughts.create_thought(
                    kind="continuity",
                    summary="Discord continuity stays anchored on recent decisions.",
                    content="Use bounded project continuity for Discord continuity and recent decisions.",
                    source_ids=[current.decision_record_id],
                    confidence=0.92,
                    metadata={"privacy_view": "clean"},
                )
                private_thought = services.thoughts.create_thought(
                    kind="continuity",
                    summary="Founder-only private continuity detail.",
                    content="This private continuity note must stay hidden by default.",
                    source_ids=["private_note"],
                    confidence=0.95,
                    metadata={"privacy_view": "full"},
                )

                old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
                services.database.execute(
                    "UPDATE decision_records SET created_at = ?, updated_at = ? WHERE decision_record_id = ?",
                    (old_ts, old_ts, old.decision_record_id),
                )
                services.database.execute(
                    "UPDATE thought_memories SET created_at = ?, updated_at = ? WHERE thought_id = ?",
                    (old_ts, old_ts, private_thought.thought_id),
                )

                brief = services.memory_os.build_project_continuity_brief(
                    context=RetrievalContext(
                        query="discord continuity recent decisions",
                        user_id="founder",
                        surface="discord",
                        channel="discord",
                        branch_name="codex/discord-facade",
                        target_profile="core",
                    )
                )

                self.assertIn("cap stable: garder une facade Discord naturelle", brief["summary"])
                self.assertIn("Keep the Discord facade natural and readable.", brief["summary"])
                self.assertIn("Brancher la suite d evals conversationnelles.", brief["summary"])
                self.assertIn("Discord continuity stays anchored on recent decisions.", brief["summary"])
                self.assertNotIn("Legacy noisy disclosure", brief["summary"])
                self.assertNotIn("Founder-only private continuity detail.", brief["summary"])
                self.assertEqual(brief["retention"]["lookback_days"], 5)
                self.assertEqual(brief["retention"]["privacy_view"], "clean_only")
                trace = services.database.fetchone(
                    "SELECT operation FROM memory_operation_traces WHERE operation = 'project_continuity_built' ORDER BY created_at DESC LIMIT 1"
                )
                self.assertIsNotNone(trace)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
