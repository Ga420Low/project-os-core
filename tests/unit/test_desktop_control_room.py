from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.desktop.control_room import DesktopControlRoomService
from project_os_core.services import build_app_services


class DesktopControlRoomServiceTests(unittest.TestCase):
    def _build_services(self, tmp_path: Path):
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
            "openclaw_config": {
                "enabled_channels": ["discord"]
            }
        }
        policy_path = tmp_path / "runtime_policy.json"
        policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

        services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
        services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
        return services

    def _seed_founder_context(self, services) -> None:
        now = datetime.now(timezone.utc)
        recent_created = now.isoformat()
        archive_created = (now - timedelta(days=10)).isoformat()
        services.database.upsert(
            "channel_events",
            {
                "event_id": "event_recent",
                "surface": "discord",
                "event_type": "message.created",
                "actor_id": "founder",
                "channel": "founder-room",
                "message_kind": "text",
                "source_message_id": "msg_recent",
                "conversation_key": "thread_recent",
                "ingress_dedup_key": "dedup_recent",
                "correlation_id": "corr_recent",
                "thread_ref_json": json.dumps({"thread_id": "thread_recent", "external_thread_id": "thread_recent"}),
                "message_json": json.dumps({"text": "Go Pack 7 et rends le terminal plus grand avec une sidebar utile."}),
                "raw_payload_json": json.dumps({}),
                "created_at": recent_created,
            },
            conflict_columns="event_id",
        )
        services.database.upsert(
            "gateway_dispatch_results",
            {
                "dispatch_id": "dispatch_recent",
                "channel_event_id": "event_recent",
                "envelope_id": "env_recent",
                "intent_id": "intent_recent",
                "decision_id": "decision_recent",
                "mission_run_id": "mission_recent",
                "correlation_id": "corr_recent",
                "memory_candidate_id": None,
                "promotion_decision_id": None,
                "promoted_memory_ids_json": json.dumps([]),
                "reply_json": json.dumps({"summary": "Pack 7 en cours: couts, contexte, conversations et sidebar."}),
                "metadata_json": json.dumps({}),
                "created_at": recent_created,
            },
            conflict_columns="dispatch_id",
        )
        services.database.upsert(
            "thread_ledgers",
            {
                "thread_ledger_id": "ledger_recent",
                "surface": "discord",
                "channel": "founder-room",
                "thread_id": "thread_recent",
                "external_thread_id": "thread_recent",
                "conversation_key": "thread_recent",
                "status": "active",
                "active_subject": "Pack 7 desktop control room",
                "subtopics_json": json.dumps([]),
                "last_operator_reply_id": "reply_recent",
                "last_authoritative_reply_summary": "Faire une grande zone terminal et une colonne de contexte fondateur.",
                "last_artifact_id": "artifact_pdf_recent",
                "last_pdf_artifact_id": "artifact_pdf_recent",
                "last_bundle_id": None,
                "active_bundle_ids_json": json.dumps([]),
                "active_analysis_object_ids_json": json.dumps([]),
                "referenced_object_ids_json": json.dumps([]),
                "pending_approval_ids_json": json.dumps([]),
                "mode": "implementation",
                "claims_json": json.dumps([]),
                "questions_json": json.dumps([]),
                "decisions_json": json.dumps(["Go Pack 7"]),
                "contradictions_json": json.dumps([]),
                "metadata_json": json.dumps({}),
                "created_at": recent_created,
                "updated_at": recent_created,
            },
            conflict_columns="thread_ledger_id",
        )
        services.database.upsert(
            "artifact_ledger_entries",
            {
                "artifact_ledger_entry_id": "artifact_entry_recent",
                "artifact_id": "artifact_pdf_recent",
                "artifact_kind": "report",
                "owner_type": "thread",
                "owner_id": "thread_recent",
                "surface": "discord",
                "channel": "founder-room",
                "thread_id": "thread_recent",
                "external_thread_id": "thread_recent",
                "conversation_key": "thread_recent",
                "reply_id": "reply_recent",
                "run_id": None,
                "approval_id": None,
                "bundle_id": None,
                "source_object_id": None,
                "source_ids_json": json.dumps([]),
                "cold_artifact_id": None,
                "cold_path": None,
                "ingestion_status": "ready",
                "source_locator": "D:/ProjectOS/runtime/reports/project_pack7_notes.pdf",
                "metadata_json": json.dumps({}),
                "created_at": recent_created,
            },
            conflict_columns="artifact_id",
        )
        services.database.upsert(
            "channel_events",
            {
                "event_id": "event_archive",
                "surface": "discord",
                "event_type": "message.created",
                "actor_id": "founder",
                "channel": "founder-room",
                "message_kind": "text",
                "source_message_id": "msg_archive",
                "conversation_key": "thread_archive",
                "ingress_dedup_key": "dedup_archive",
                "correlation_id": "corr_archive",
                "thread_ref_json": json.dumps({"thread_id": "thread_archive", "external_thread_id": "thread_archive"}),
                "message_json": json.dumps({"text": "On garde la roadmap desktop comme sujet principal sur plusieurs packs."}),
                "raw_payload_json": json.dumps({}),
                "created_at": archive_created,
            },
            conflict_columns="event_id",
        )
        services.database.upsert(
            "gateway_dispatch_results",
            {
                "dispatch_id": "dispatch_archive",
                "channel_event_id": "event_archive",
                "envelope_id": "env_archive",
                "intent_id": "intent_archive",
                "decision_id": "decision_archive",
                "mission_run_id": "mission_archive",
                "correlation_id": "corr_archive",
                "memory_candidate_id": None,
                "promotion_decision_id": None,
                "promoted_memory_ids_json": json.dumps([]),
                "reply_json": json.dumps({"summary": "La roadmap desktop reste epinglee comme sujet de reference."}),
                "metadata_json": json.dumps({}),
                "created_at": archive_created,
            },
            conflict_columns="dispatch_id",
        )
        services.database.upsert(
            "thread_ledgers",
            {
                "thread_ledger_id": "ledger_archive",
                "surface": "discord",
                "channel": "founder-room",
                "thread_id": "thread_archive",
                "external_thread_id": "thread_archive",
                "conversation_key": "thread_archive",
                "status": "active",
                "active_subject": "Roadmap desktop v1",
                "subtopics_json": json.dumps([]),
                "last_operator_reply_id": "reply_archive",
                "last_authoritative_reply_summary": "La roadmap desktop reste la colonne vertebrale du chantier.",
                "last_artifact_id": None,
                "last_pdf_artifact_id": None,
                "last_bundle_id": None,
                "active_bundle_ids_json": json.dumps([]),
                "active_analysis_object_ids_json": json.dumps([]),
                "referenced_object_ids_json": json.dumps([]),
                "pending_approval_ids_json": json.dumps([]),
                "mode": "roadmap",
                "claims_json": json.dumps([]),
                "questions_json": json.dumps([]),
                "decisions_json": json.dumps(["Continuer les packs desktop"]),
                "contradictions_json": json.dumps([]),
                "metadata_json": json.dumps({}),
                "created_at": archive_created,
                "updated_at": archive_created,
            },
            conflict_columns="thread_ledger_id",
        )

    def test_workspace_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                desktop = DesktopControlRoomService(services)
                saved = desktop.save_workspace_state(
                    {
                        "last_active_tab": "Runs",
                        "selected_run_id": "run_demo",
                        "persistent_panels": [
                            {
                                "role_id": "master_codex",
                                "kind": "master_codex",
                                "title": "Codex",
                                "command": "codex",
                                "persistent": True,
                            }
                        ],
                    }
                )
                self.assertEqual(saved["last_active_tab"], "Runs")
                loaded = desktop.load_workspace_state()
                self.assertEqual(loaded["last_active_tab"], "Runs")
                self.assertEqual(loaded["selected_run_id"], "run_demo")
                self.assertEqual(loaded["restore_status"], "restored")
                self.assertEqual(loaded["theme_variant"], "hybrid_luxe")
                self.assertEqual(loaded["motion_mode"], "full")
                self.assertEqual(loaded["terminal_dock_preset"], "focus")
            finally:
                services.close()

    def test_corrupt_workspace_falls_back_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                desktop = DesktopControlRoomService(services)
                desktop.state_root.mkdir(parents=True, exist_ok=True)
                desktop.workspace_state_path.write_text("{not json", encoding="utf-8")
                payload = desktop.load_workspace_state()
                self.assertEqual(payload["restore_status"], "corrupt_fallback")
                self.assertEqual(payload["last_active_tab"], "Home")
                self.assertEqual(payload["theme_variant"], "hybrid_luxe")
                self.assertEqual(payload["terminal_dock_preset"], "focus")
            finally:
                services.close()

    def test_startup_payload_contains_foundation_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                desktop = DesktopControlRoomService(services)
                with mock.patch.object(DesktopControlRoomService, "_run_gateway_operator", return_value={"ok": True, "payload": {"service": {"loaded": True, "runtime": {"status": "running"}}, "port": {"status": "busy"}, "rpc": {"ok": True}, "gateway": {"probeUrl": "ws://127.0.0.1:18789"}}, "stdout": "", "stderr": ""}), \
                    mock.patch.object(services.openclaw, "truth_health", return_value=SimpleNamespace(verdict="OK", summary="truth ok", evidence_refs=[], actionable_fixes=[])), \
                    mock.patch.object(services.openclaw, "discord_calibration_snapshot", return_value={"recent_events": [], "recent_deliveries": [], "gateway_status": {}, "live_proof": {}}):
                    payload = desktop.build_startup_payload(limit=4)
                self.assertIn("workspace_state", payload)
                self.assertIn("startup_health", payload)
                self.assertIn("home_summary", payload)
                self.assertIn("session_summary", payload)
                self.assertIn("cost_summary", payload)
                self.assertIn("codex_usage_status", payload)
                self.assertIn("views", payload)
                self.assertIn("home", payload["views"])
                self.assertIn("runtime_adapter_status", payload)
                self.assertIn("cards", payload["startup_health"])
                self.assertTrue(any(card["id"] == "gateway_runtime" for card in payload["startup_health"]["cards"]))
                self.assertTrue(any(card["id"] == "master_terminal" for card in payload["startup_health"]["cards"]))
                self.assertIn("health_cards", payload["views"]["home"])
            finally:
                services.close()

    def test_screen_payload_is_normalized_and_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                desktop = DesktopControlRoomService(services)
                with mock.patch.object(DesktopControlRoomService, "_run_gateway_operator", return_value={"ok": True, "payload": {"service": {"loaded": True, "runtime": {"status": "running"}}, "port": {"status": "busy"}, "rpc": {"ok": True}, "gateway": {"probeUrl": "ws://127.0.0.1:18789"}}, "stdout": "", "stderr": ""}), \
                    mock.patch.object(services.openclaw, "truth_health", return_value=SimpleNamespace(verdict="OK", summary="truth ok", evidence_refs=[], actionable_fixes=[])), \
                    mock.patch.object(services.openclaw, "discord_calibration_snapshot", return_value={"recent_events": [], "recent_deliveries": [], "gateway_status": {}, "live_proof": {}}):
                    payload = desktop.build_screen_payload("home", limit=4)
                self.assertEqual(payload["screen"], "home")
                self.assertIn("payload", payload)
                self.assertIn("metrics", payload["payload"])
                self.assertIn("startup_checks", payload["payload"])
                self.assertIn("current_session_items", payload["payload"])
            finally:
                services.close()

    def test_runtime_payload_stays_readable_when_monitor_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                desktop = DesktopControlRoomService(services)
                with mock.patch.object(DesktopControlRoomService, "_run_gateway_operator", return_value={"ok": True, "payload": {"service": {"loaded": True, "runtime": {"status": "running"}}, "port": {"status": "busy"}, "rpc": {"ok": True}, "gateway": {"probeUrl": "ws://127.0.0.1:18789"}}, "stdout": "", "stderr": ""}), \
                    mock.patch.object(services.openclaw, "truth_health", return_value=SimpleNamespace(verdict="OK", summary="truth ok", evidence_refs=[], actionable_fixes=[])), \
                    mock.patch.object(services.openclaw, "discord_calibration_snapshot", return_value={"recent_events": [], "recent_deliveries": [], "gateway_status": {}, "live_proof": {}}), \
                    mock.patch.object(services.api_runs, "monitor_snapshot", side_effect=RuntimeError("monitor down")):
                    payload = desktop.build_runtime_payload(limit=4)
                self.assertIn(payload["startup_health"]["overall_status"], {"warning", "error"})
                dashboard_card = next(card for card in payload["startup_health"]["cards"] if card["id"] == "dashboard_source")
                self.assertIn(dashboard_card["status"], {"warning", "error"})
                self.assertIn("degrade", payload["views"]["home"]["headline"].lower())
            finally:
                services.close()

    def test_pack7_payload_exposes_cost_lanes_sidebar_and_conversation_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                self._seed_founder_context(services)
                desktop = DesktopControlRoomService(services)
                with mock.patch.object(DesktopControlRoomService, "_run_gateway_operator", return_value={"ok": True, "payload": {"service": {"loaded": True, "runtime": {"status": "running"}}, "port": {"status": "busy"}, "rpc": {"ok": True}, "gateway": {"probeUrl": "ws://127.0.0.1:18789"}}, "stdout": "", "stderr": ""}), \
                    mock.patch.object(services.openclaw, "truth_health", return_value=SimpleNamespace(verdict="OK", summary="truth ok", evidence_refs=[], actionable_fixes=[])), \
                    mock.patch.object(services.openclaw, "discord_calibration_snapshot", return_value={"recent_events": [], "recent_deliveries": [], "gateway_status": {}, "live_proof": {}}):
                    payload = desktop.build_runtime_payload(limit=6)
                self.assertIn("cost_lanes", payload)
                self.assertIn("founder_sidebar", payload)
                self.assertIn("conversation_summary", payload)
                self.assertIn("conversations", payload["views"])
                self.assertEqual(len(payload["views"]["home"]["cost_strip"]), 4)
                self.assertGreaterEqual(len(payload["views"]["home"]["conversation_items"]), 1)
                self.assertGreaterEqual(len(payload["views"]["conversations"]["archive_exchanges"]), 1)
                latest_pdf = next(
                    item for item in payload["views"]["home"]["sidebar"]["highlights"] if item["label"] == "Latest PDF"
                )
                self.assertIn("project_pack7_notes.pdf", latest_pdf["value"])
                self.assertTrue(
                    any(
                        "Pack 7" in item["title"] or "Roadmap" in item["title"]
                        for item in payload["views"]["home"]["sidebar"]["pinned_topics"]
                    )
                )
            finally:
                services.close()

    def test_reset_panel_layout_restores_master_codex_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = self._build_services(Path(tmp))
            try:
                desktop = DesktopControlRoomService(services)
                desktop.save_workspace_state(
                    {
                        "last_selected_workspace_root": "D:/ProjectOS/project-os-core",
                        "persistent_panels": [
                            {
                                "role_id": "logs_live",
                                "kind": "logs_live",
                                "title": "Logs",
                                "command": "echo logs",
                                "persistent": True,
                            }
                        ],
                    }
                )
                result = desktop.perform_action("reset_panel_layout")
                reloaded = desktop.load_workspace_state()
                self.assertTrue(result["ok"])
                self.assertEqual(reloaded["last_selected_workspace_root"], "D:/ProjectOS/project-os-core")
                self.assertEqual(reloaded["persistent_panels"][0]["role_id"], "master_codex")
            finally:
                services.close()
