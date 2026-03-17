from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.database import CanonicalDatabase
from project_os_core.models import OutputQuarantineReason, TraceEntityKind, TraceRelationKind
from project_os_core.secrets import SecretLookup
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
        "api_dashboard_config": {
            "auto_start": False,
            "auto_open_browser": False,
        },
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")

    services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
    services.secret_resolver._from_infisical = lambda name: SecretLookup(
        value=None,
        source="test_infisical_disabled",
        available=False,
    )
    services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
    services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "anthropic-test-secret")
    return services


class Pack0ContractTests(unittest.TestCase):
    def test_database_records_trace_edge_once_and_updates_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = CanonicalDatabase(Path(tmp) / "canonical.db")
            try:
                edge_id = database.record_trace_edge(
                    parent_id="intent_1",
                    parent_kind=TraceEntityKind.MISSION_INTENT.value,
                    child_id="decision_1",
                    child_kind=TraceEntityKind.ROUTING_DECISION.value,
                    relation=TraceRelationKind.ROUTED_TO.value,
                    metadata={"route_reason": "discord_simple_route"},
                )
                edge_id_again = database.record_trace_edge(
                    parent_id="intent_1",
                    parent_kind=TraceEntityKind.MISSION_INTENT.value,
                    child_id="decision_1",
                    child_kind=TraceEntityKind.ROUTING_DECISION.value,
                    relation=TraceRelationKind.ROUTED_TO.value,
                    metadata={"route_reason": "discord_simple_route", "updated": True},
                )

                self.assertEqual(edge_id, edge_id_again)
                row = database.fetchone("SELECT * FROM trace_edges WHERE trace_edge_id = ?", (edge_id,))
                self.assertIsNotNone(row)
                self.assertEqual(row["relation"], TraceRelationKind.ROUTED_TO.value)
                self.assertTrue(json.loads(row["metadata_json"])["updated"])
            finally:
                database.close()

    def test_api_run_invalid_structured_output_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                    services.api_runs._normalize_response_payload(
                        {
                            "model": "gpt-5.4",
                            "output_text": "```json\n{\"decision\":\n```",
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                        run_id="run_test_pack0",
                        run_request_id="request_test_pack0",
                        model="gpt-5.4",
                    )

                row = services.database.fetchone(
                    """
                    SELECT *
                    FROM output_quarantine_records
                    WHERE source_system = 'api_runs'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                self.assertIsNotNone(row)
                self.assertEqual(row["reason_code"], OutputQuarantineReason.INVALID_JSON.value)
                self.assertEqual(row["source_entity_id"], "run_test_pack0")
                payload = json.loads(row["payload_json"])
                self.assertIn("output_text_preview", payload)
                edge = services.database.fetchone(
                    """
                    SELECT *
                    FROM trace_edges
                    WHERE parent_id = ?
                      AND parent_kind = ?
                      AND child_id = ?
                      AND relation = ?
                    """,
                    (
                        "run_test_pack0",
                        TraceEntityKind.API_RUN.value,
                        row["quarantine_id"],
                        TraceRelationKind.QUARANTINED_AS.value,
                    ),
                )
                self.assertIsNotNone(edge)
            finally:
                services.close()

    def test_deep_research_invalid_json_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                request = {"job_id": "deep_research_job_pack0", "title": "Debug pack 0"}
                with self.assertRaisesRegex(RuntimeError, "not valid JSON"):
                    services.deep_research._parse_json_object(
                        "not-json-at-all",
                        quarantine_context={
                            "request": request,
                            "source_system": "deep_research",
                            "source_entity_kind": TraceEntityKind.DEEP_RESEARCH_JOB.value,
                            "source_entity_id": "deep_research_job_pack0",
                            "provider": "openai",
                            "model": "gpt-5",
                            "phase": "final_synthesis",
                            "schema_name": "project_os_deep_research_result",
                            "raw_payload": {"output_text": "not-json-at-all"},
                        },
                    )

                row = services.database.fetchone(
                    """
                    SELECT *
                    FROM output_quarantine_records
                    WHERE source_system = 'deep_research'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                self.assertIsNotNone(row)
                self.assertEqual(row["reason_code"], OutputQuarantineReason.INVALID_JSON.value)
                self.assertEqual(row["source_entity_id"], "deep_research_job_pack0")
                edge = services.database.fetchone(
                    """
                    SELECT *
                    FROM trace_edges
                    WHERE parent_id = ?
                      AND parent_kind = ?
                      AND child_id = ?
                      AND relation = ?
                    """,
                    (
                        "deep_research_job_pack0",
                        TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        row["quarantine_id"],
                        TraceRelationKind.QUARANTINED_AS.value,
                    ),
                )
                self.assertIsNotNone(edge)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
