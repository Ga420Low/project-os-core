from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.cli import main
from project_os_core.models import (
    ChannelEvent,
    ConversationThreadRef,
    IncidentSeverity,
    IncidentStatus,
    OperatorDeliveryStatus,
    OperatorMessage,
    RuntimeState,
    RuntimeVerdict,
    TraceEntityKind,
    TraceRelationKind,
    new_id,
)
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
    return services, config_path, policy_path


class Pack3IncidentsAndEvalsTests(unittest.TestCase):
    def test_incident_from_dead_letter_requires_proof_before_verified_and_lists_in_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, config_path, policy_path = _build_services(Path(tmp))
            try:
                published = services.api_runs.publish_operator_update(
                    title="Incident operateur",
                    summary="La livraison Discord est tombee.",
                    text="Livraison Discord en echec.",
                    target="channel:123",
                    reply_to="discord-message-123",
                )
                delivery_id = str(published["delivery_id"])
                services.api_runs.mark_operator_delivery(
                    delivery_id=delivery_id,
                    status=OperatorDeliveryStatus.FAILED,
                    error="discord_down",
                )
                dead_letter = services.database.fetchone(
                    """
                    SELECT dead_letter_id
                    FROM dead_letter_records
                    WHERE domain = 'operator_delivery'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                self.assertIsNotNone(dead_letter)
                incident = services.incidents.create_from_dead_letter(
                    dead_letter_id=str(dead_letter["dead_letter_id"]),
                    severity=IncidentSeverity.P1,
                    summary="Discord delivery incident",
                    symptom="Le canal Discord ne delivre plus les updates operateur.",
                )
                self.assertEqual(incident["status"], IncidentStatus.OPEN.value)
                services.incidents.update_incident_status(
                    incident_id=incident["incident_id"],
                    status=IncidentStatus.TRIAGED,
                )
                services.incidents.update_incident_status(
                    incident_id=incident["incident_id"],
                    status=IncidentStatus.REPRO_READY,
                )
                services.incidents.update_incident_status(
                    incident_id=incident["incident_id"],
                    status=IncidentStatus.FIX_IN_PROGRESS,
                )
                with self.assertRaisesRegex(ValueError, "verification_refs or latest_eval_run_id"):
                    services.incidents.update_incident_status(
                        incident_id=incident["incident_id"],
                        status=IncidentStatus.VERIFIED,
                    )
            finally:
                services.close()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--config-path",
                        str(config_path),
                        "--policy-path",
                        str(policy_path),
                        "debug",
                        "incidents",
                        "--limit",
                        "10",
                    ]
                )
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["items"][0]["summary"], "Discord delivery incident")

    def test_eval_seed_and_run_trace_suite_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, config_path, policy_path = _build_services(Path(tmp))
            try:
                session = services.runtime.open_session(profile_name="browser", owner="founder")
                services.runtime.record_runtime_state(
                    RuntimeState(
                        runtime_state_id=new_id("runtime_state"),
                        session_id=session.session_id,
                        verdict=RuntimeVerdict.READY,
                        active_profile="browser",
                    )
                )
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Je veux une reponse propre sur la facade Discord.",
                        thread_ref=ConversationThreadRef(thread_id="thread_pack3_trace", channel="discord"),
                    ),
                )
                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="browser",
                    requested_worker="browser",
                )
                services.learning.record_eval_candidate(
                    scenario="Trace spine core path stays visible",
                    target_system="debug_system",
                    expected_behavior="La trace locale doit exposer un dispatch et zero dead letter.",
                    source_ids=[dispatch.dispatch_id],
                    metadata={
                        "runner_kind": "trace_report",
                        "correlation_id": str(dispatch.correlation_id),
                        "expectations": {"min_gateway_dispatches": 1, "max_dead_letters": 0},
                    },
                )
            finally:
                services.close()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--config-path",
                        str(config_path),
                        "--policy-path",
                        str(policy_path),
                        "eval",
                        "seed-from-candidates",
                        "--suite-id",
                        "core-debug",
                        "--target-system",
                        "debug_system",
                    ]
                )
            self.assertEqual(exit_code, 0)
            seed_payload = json.loads(stdout.getvalue())
            self.assertEqual(seed_payload["count"], 1)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--config-path",
                        str(config_path),
                        "--policy-path",
                        str(policy_path),
                        "eval",
                        "run",
                        "--suite-id",
                        "core-debug",
                    ]
                )
            self.assertEqual(exit_code, 0)
            run_payload = json.loads(stdout.getvalue())
            self.assertEqual(run_payload["status"], "passed")
            self.assertEqual(run_payload["passed_count"], 1)
            self.assertIn("repo_branch", run_payload["provenance"])
            self.assertIn("last_commit", run_payload["provenance"])

    def test_incident_verified_links_eval_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, _ = _build_services(Path(tmp))
            try:
                session = services.runtime.open_session(profile_name="browser", owner="founder")
                services.runtime.record_runtime_state(
                    RuntimeState(
                        runtime_state_id=new_id("runtime_state"),
                        session_id=session.session_id,
                        verdict=RuntimeVerdict.READY,
                        active_profile="browser",
                    )
                )
                event = ChannelEvent(
                    event_id=new_id("channel_event"),
                    surface="discord",
                    event_type="message.created",
                    message=OperatorMessage(
                        message_id=new_id("message"),
                        actor_id="founder",
                        channel="discord",
                        text="Verifie la colonne vertebrale debug de ce thread.",
                        thread_ref=ConversationThreadRef(thread_id="thread_pack3_incident_eval", channel="discord"),
                    ),
                )
                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="browser",
                    requested_worker="browser",
                )
                incident = services.incidents.create_incident(
                    severity=IncidentSeverity.P2,
                    summary="Regression facade debug",
                    symptom="Une reponse replonge dans la tuyauterie.",
                    source_ids=["thread:debug"],
                    correlation_id=str(dispatch.correlation_id),
                )
                eval_case = services.evals.create_case(
                    suite_id="core-debug",
                    scenario="Trace proof stays green for incident verification",
                    target_system="debug_system",
                    expected_behavior="La trace associee a l incident doit rester saine.",
                    runner_kind="trace_report",
                    metadata={
                        "correlation_id": str(dispatch.correlation_id),
                        "expectations": {"min_gateway_dispatches": 1, "max_dead_letters": 0},
                    },
                )
                services.incidents.update_incident_status(
                    incident_id=incident["incident_id"],
                    status=IncidentStatus.TRIAGED,
                )
                services.incidents.update_incident_status(
                    incident_id=incident["incident_id"],
                    status=IncidentStatus.REPRO_READY,
                )
                services.incidents.update_incident_status(
                    incident_id=incident["incident_id"],
                    status=IncidentStatus.FIX_IN_PROGRESS,
                )
                passing_run = services.evals.run_suite(
                    suite_id="core-debug",
                    case_ids=[eval_case["eval_case_id"]],
                )
                self.assertEqual(passing_run["status"], "passed")
                updated = services.incidents.update_incident_status(
                    incident_id=incident["incident_id"],
                    status=IncidentStatus.VERIFIED,
                    verification_refs=["replay:debug_pack3"],
                    latest_eval_run_id=passing_run["eval_run_id"],
                )
                self.assertEqual(updated["status"], IncidentStatus.VERIFIED.value)
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
                        incident["incident_id"],
                        TraceEntityKind.INCIDENT.value,
                        passing_run["eval_run_id"],
                        TraceRelationKind.VERIFIED_BY.value,
                    ),
                )
                self.assertIsNotNone(edge)
            finally:
                services.close()

    def test_seed_from_candidates_is_idempotent_per_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, _ = _build_services(Path(tmp))
            try:
                services.learning.record_eval_candidate(
                    scenario="Dead letter remains requeueable",
                    target_system="debug_system",
                    expected_behavior="Le dead letter operateur doit rester rejouable.",
                    metadata={
                        "runner_kind": "dead_letter_status",
                        "source_entity_kind": "operator_delivery",
                        "source_entity_id": "delivery_x",
                        "expected_replayable": True,
                    },
                )
                first = services.evals.seed_cases_from_candidates(suite_id="core-debug", target_system="debug_system")
                second = services.evals.seed_cases_from_candidates(suite_id="core-debug", target_system="debug_system")
                self.assertEqual(first["count"], 1)
                self.assertEqual(second["count"], 1)
                rows = services.database.fetchall("SELECT * FROM eval_cases")
                self.assertEqual(len(rows), 1)
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
