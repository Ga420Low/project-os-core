from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.config import load_runtime_config
from project_os_core.database import CanonicalDatabase, dump_json
from project_os_core.embedding import choose_embedding_strategy
from project_os_core.memory.store import MemoryStore
from project_os_core.models import ApiRunStatus, MemoryTier, RetrievalContext, new_id
from project_os_core.paths import PathPolicy, build_project_paths, ensure_project_roots
from project_os_core.secrets import SecretResolver
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


def _build_services_with_policy(tmp_path: Path, policy_payload: dict[str, Any]):
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
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
    services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
    services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
    return services


def _set_record_timestamp(services, memory_id: str, *, created_at: str) -> None:
    services.database.execute(
        "UPDATE memory_records SET created_at = ?, updated_at = ? WHERE memory_id = ?",
        (created_at, created_at, memory_id),
    )


def _insert_thread_recall_fixture(
    services,
    *,
    channel: str,
    conversation_key: str,
    message_text: str,
    reply_summary: str,
    created_at: str,
    sensitivity_class: str = "s1_passthrough",
) -> None:
    event_id = new_id("channel_event")
    dispatch_id = new_id("dispatch")
    thread_ref = {
        "thread_id": conversation_key,
        "channel": channel,
        "external_thread_id": conversation_key,
        "metadata": {"surface": "discord"},
    }
    message = {
        "message_id": new_id("message"),
        "actor_id": "founder",
        "channel": channel,
        "text": message_text,
        "thread_ref": thread_ref,
        "metadata": {"source": "openclaw"},
        "created_at": created_at,
    }
    services.database.upsert(
        "channel_events",
        {
            "event_id": event_id,
            "surface": "discord",
            "event_type": "message.received",
            "actor_id": "founder",
            "channel": channel,
            "message_kind": "chat",
            "source_message_id": new_id("source_message"),
            "conversation_key": conversation_key,
            "ingress_dedup_key": new_id("dedup"),
            "thread_ref_json": dump_json(thread_ref),
            "message_json": dump_json(message),
            "raw_payload_json": dump_json({"source": "fixture"}),
            "created_at": created_at,
        },
        conflict_columns="event_id",
        immutable_columns=["created_at"],
    )
    services.database.upsert(
        "conversation_memory_candidates",
        {
            "candidate_id": new_id("candidate"),
            "source_event_id": event_id,
            "actor_id": "founder",
            "classification": "chat",
            "thread_ref_json": dump_json(thread_ref),
            "summary": message_text[:240],
            "content": message_text,
            "tags_json": dump_json(["discord", "session"]),
            "tier": "warm",
            "should_promote": 1,
            "payload_json": dump_json({"sensitivity_class": sensitivity_class}),
            "created_at": created_at,
        },
        conflict_columns="candidate_id",
        immutable_columns=["created_at"],
    )
    services.database.upsert(
        "gateway_dispatch_results",
        {
            "dispatch_id": dispatch_id,
            "channel_event_id": event_id,
            "envelope_id": new_id("envelope"),
            "intent_id": new_id("intent"),
            "decision_id": new_id("decision"),
            "mission_run_id": None,
            "memory_candidate_id": None,
            "promotion_decision_id": None,
            "promoted_memory_ids_json": dump_json([]),
            "reply_json": dump_json(
                {
                    "reply_id": new_id("reply"),
                    "channel": channel,
                    "envelope_id": new_id("envelope"),
                    "thread_ref": thread_ref,
                    "summary": reply_summary,
                    "reply_kind": "chat_response",
                    "created_at": created_at,
                }
            ),
            "metadata_json": dump_json({"sensitivity_class": sensitivity_class}),
            "created_at": created_at,
        },
        conflict_columns="dispatch_id",
        immutable_columns=["created_at"],
    )
    services.database.upsert(
        "discord_thread_bindings",
        {
            "binding_id": new_id("discord_binding"),
            "binding_key": f"discord|{channel}|{conversation_key}",
            "surface": "discord",
            "channel": channel,
            "thread_id": conversation_key,
            "external_thread_id": conversation_key,
            "parent_thread_id": None,
            "channel_event_id": event_id,
            "dispatch_id": dispatch_id,
            "envelope_id": None,
            "decision_id": None,
            "mission_run_id": None,
            "binding_kind": "run",
            "status": "active",
            "metadata_json": dump_json({"conversation_key": conversation_key}),
            "created_at": created_at,
            "updated_at": created_at,
        },
        conflict_columns="binding_id",
        immutable_columns=["created_at"],
    )


def _insert_recent_run_fixture(
    services,
    *,
    branch_name: str,
    target_profile: str,
    objective: str,
    updated_at: str,
) -> None:
    run_request_id = new_id("run_request")
    services.database.upsert(
        "api_run_requests",
        {
            "run_request_id": run_request_id,
            "context_pack_id": new_id("context_pack"),
            "prompt_template_id": new_id("prompt"),
            "mode": "audit",
            "objective": objective,
            "branch_name": branch_name,
            "target_profile": target_profile,
            "mission_chain_id": None,
            "mission_step_index": None,
            "skill_tags_json": dump_json(["history"]),
            "expected_outputs_json": dump_json([]),
            "coding_lane": "repo_cli",
            "desktop_lane": "future_computer_use",
            "communication_mode": "builder",
            "speech_policy": "silent_until_terminal_state",
            "operator_language": "fr",
            "audience": "non_developer",
            "run_contract_required": 1,
            "contract_id": None,
            "status": ApiRunStatus.COMPLETED.value,
            "metadata_json": dump_json({}),
            "created_at": updated_at,
            "updated_at": updated_at,
        },
        conflict_columns="run_request_id",
        immutable_columns=["created_at"],
    )
    services.database.upsert(
        "api_run_results",
        {
            "run_id": new_id("run"),
            "run_request_id": run_request_id,
            "model": "gpt-5.4",
            "mode": "audit",
            "status": ApiRunStatus.COMPLETED.value,
            "raw_output_path": None,
            "prompt_artifact_path": None,
            "result_artifact_path": None,
            "structured_output_json": dump_json({"decision": "done"}),
            "estimated_cost_eur": 0.0,
            "usage_json": dump_json({}),
            "metadata_json": dump_json({}),
            "created_at": updated_at,
            "updated_at": updated_at,
        },
        conflict_columns="run_id",
        immutable_columns=["created_at"],
    )


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

    def test_private_full_memory_is_hidden_from_default_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services(tmp_path)
            try:
                full_record = services.memory.remember(
                    content="Founder secret token stays local only.",
                    user_id="founder",
                    metadata={
                        "privacy_view": "full",
                        "openmemory_enabled": False,
                        "embedding_provider": "local_hash",
                    },
                )
                clean_record = services.memory.remember(
                    content="Founder sensitive reference stays local only.",
                    user_id="founder",
                    metadata={"privacy_view": "clean"},
                )

                default_hits = services.memory.search(RetrievalContext(query="local only", user_id="founder", limit=5))
                full_hits = services.memory.search(
                    RetrievalContext(query="local only", user_id="founder", limit=5, include_private_full=True)
                )

                self.assertNotIn(full_record.memory_id, [item["memory_id"] for item in default_hits])
                self.assertIn(clean_record.memory_id, [item["memory_id"] for item in default_hits])
                self.assertIn(full_record.memory_id, [item["memory_id"] for item in full_hits])
            finally:
                services.close()

    def test_retrieval_sidecar_prefers_recent_memory_when_scores_are_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services(tmp_path)
            try:
                old_record = services.memory.remember(
                    content="Gateway retrieval sidecar status remains healthy after the restart.",
                    user_id="founder",
                    tags=["gateway", "retrieval"],
                )
                new_record = services.memory.remember(
                    content="Gateway retrieval sidecar status remains healthy after the restart.",
                    user_id="founder",
                    tags=["gateway", "retrieval"],
                )
                old_ts = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
                fresh_ts = datetime.now(timezone.utc).isoformat()
                _set_record_timestamp(services, old_record.memory_id, created_at=old_ts)
                _set_record_timestamp(services, new_record.memory_id, created_at=fresh_ts)

                hits = services.memory.search(
                    RetrievalContext(
                        query="gateway retrieval status",
                        user_id="founder",
                        limit=2,
                    )
                )

                self.assertEqual(hits[0]["memory_id"], new_record.memory_id)
                self.assertGreater(
                    hits[0]["retrieval_trace"]["recency_boost"],
                    hits[1]["retrieval_trace"]["recency_boost"],
                )
            finally:
                services.close()

    def test_retrieval_sidecar_uses_mmr_to_diversify_near_duplicate_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services(tmp_path)
            try:
                first = services.memory.remember(
                    content="Gateway routing issue blocks the Discord reply path on restart.",
                    user_id="founder",
                    tags=["gateway", "routing", "discord"],
                )
                second = services.memory.remember(
                    content="Gateway routing issue blocks the Discord reply path on restart and duplicates the reply.",
                    user_id="founder",
                    tags=["gateway", "routing", "discord"],
                )
                diverse = services.memory.remember(
                    content="Gateway routing incident needs a watchdog restart plan and health validation.",
                    user_id="founder",
                    tags=["gateway", "health", "watchdog"],
                )

                hits = services.memory.search(
                    RetrievalContext(
                        query="gateway routing discord restart",
                        user_id="founder",
                        limit=3,
                    )
                )

                ordered_ids = [item["memory_id"] for item in hits]
                top_two = set(ordered_ids[:2])
                duplicate_ids = {first.memory_id, second.memory_id}
                self.assertIn(diverse.memory_id, top_two)
                self.assertLess(len(top_two & duplicate_ids), 2)
                self.assertGreater(
                    max(item["retrieval_trace"]["diversity_penalty"] for item in hits),
                    0.0,
                )
            finally:
                services.close()

    def test_retrieval_sidecar_query_expansion_uses_context_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services(tmp_path)
            try:
                record = services.memory.remember(
                    content="project os retrieval pack stays stable on the roadmap-freeze branch.",
                    user_id="founder",
                    project_id="project-os-core",
                    tags=["roadmap-freeze", "retrieval"],
                )

                hits = services.memory.search(
                    RetrievalContext(
                        query="stable retrieval pack",
                        user_id="founder",
                        branch_name="project-os/roadmap-freeze",
                        target_profile="core",
                        limit=3,
                    )
                )

                self.assertEqual(hits[0]["memory_id"], record.memory_id)
                self.assertIn("roadmap", hits[0]["retrieval_trace"]["expanded_query_terms"])
            finally:
                services.close()

    def test_retrieval_sidecar_recalls_recent_thread_and_branch_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services(tmp_path)
            try:
                now = datetime.now(timezone.utc).isoformat()
                _insert_thread_recall_fixture(
                    services,
                    channel="discord",
                    conversation_key="channel:discord-general",
                    message_text="Qui est tu ?",
                    reply_summary="Je suis la voix operateur de Project OS.",
                    created_at=now,
                )
                _insert_recent_run_fixture(
                    services,
                    branch_name="project-os/roadmap-freeze",
                    target_profile="core",
                    objective="Audit retrieval sidecar behavior.",
                    updated_at=now,
                )

                hits = services.memory.search(
                    RetrievalContext(
                        query="qui est tu",
                        user_id="founder",
                        channel="discord",
                        conversation_key="channel:discord-general",
                        external_thread_id="channel:discord-general",
                        branch_name="project-os/roadmap-freeze",
                        target_profile="core",
                        limit=4,
                    )
                )

                self.assertEqual(hits[0]["source"], "session_thread_recall")
                self.assertTrue(any(item["source"] == "recent_session_briefing" for item in hits))
                self.assertEqual(
                    hits[0]["retrieval_trace"]["candidate_source"],
                    "session_thread_recall",
                )
            finally:
                services.close()

    def test_retrieval_sidecar_keeps_s3_thread_recall_hidden_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services(tmp_path)
            try:
                now = datetime.now(timezone.utc).isoformat()
                _insert_thread_recall_fixture(
                    services,
                    channel="discord",
                    conversation_key="channel:discord-sensitive",
                    message_text="OPENCLAW_GATEWAY_TOKEN=fake-test-token",
                    reply_summary="[Local S3 / Ollama] Message sensible traite localement.",
                    created_at=now,
                    sensitivity_class="s3_local",
                )

                default_hits = services.memory.search(
                    RetrievalContext(
                        query="gateway token",
                        user_id="founder",
                        channel="discord",
                        conversation_key="channel:discord-sensitive",
                        limit=3,
                    )
                )
                full_hits = services.memory.search(
                    RetrievalContext(
                        query="gateway token",
                        user_id="founder",
                        channel="discord",
                        conversation_key="channel:discord-sensitive",
                        limit=3,
                        include_private_full=True,
                    )
                )

                self.assertEqual(default_hits, [])
                self.assertEqual(full_hits[0]["source"], "session_thread_recall")
            finally:
                services.close()

    def test_retrieval_sidecar_can_be_disabled_without_trace_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services_with_policy(
                tmp_path,
                {
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
                    "memory": {
                        "retrieval_sidecar": {
                            "enabled": False,
                        }
                    },
                },
            )
            try:
                record = services.memory.remember(
                    content="Legacy memory search stays simple when the sidecar is disabled.",
                    user_id="founder",
                )
                hits = services.memory.search(
                    RetrievalContext(
                        query="legacy memory search",
                        user_id="founder",
                        limit=3,
                    )
                )

                self.assertEqual(hits[0]["memory_id"], record.memory_id)
                self.assertNotIn("retrieval_trace", hits[0])
            finally:
                services.close()

    def test_local_only_memory_skips_openmemory_even_after_reindex(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services(tmp_path)
            try:
                def _forbidden_add(record):
                    raise AssertionError("openmemory add_record should not be called for local-only memory")

                services.memory.openmemory.add_record = _forbidden_add  # type: ignore[method-assign]
                record = services.memory.remember(
                    content="OPENCLAW_GATEWAY_TOKEN stays local.",
                    user_id="founder",
                    metadata={
                        "privacy_view": "full",
                        "openmemory_enabled": False,
                        "embedding_provider": "local_hash",
                    },
                )

                report = services.memory.reindex()
                refreshed = services.memory.get(record.memory_id)

                self.assertIn(report["status"], {"completed"})
                self.assertIsNone(refreshed.openmemory_id)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
