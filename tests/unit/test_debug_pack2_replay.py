from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.cli import main
from project_os_core.models import (
    ChannelEvent,
    ConversationThreadRef,
    OperatorDeliveryStatus,
    OperatorMessage,
    RuntimeState,
    RuntimeVerdict,
    TraceEntityKind,
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


class Pack2ReplayTests(unittest.TestCase):
    def test_debug_replay_cli_is_canonical_and_idempotent(self):
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
                        text="Resume-moi les decisions Discord en cours sans exposer la tuyauterie.",
                        thread_ref=ConversationThreadRef(
                            thread_id="thread_pack2_replay",
                            channel="discord",
                            external_thread_id="discord-thread-pack2-replay",
                        ),
                    ),
                )
                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="browser",
                    requested_worker="browser",
                )
                correlation_id = str(dispatch.correlation_id)
            finally:
                services.close()

            stdout_first = io.StringIO()
            with redirect_stdout(stdout_first):
                exit_code = main(
                    [
                        "--config-path",
                        str(config_path),
                        "--policy-path",
                        str(policy_path),
                        "debug",
                        "replay",
                        correlation_id,
                    ]
                )
            self.assertEqual(exit_code, 0)
            first_payload = json.loads(stdout_first.getvalue())
            self.assertEqual(first_payload["status"], "completed")
            self.assertFalse(first_payload["reused_existing"])
            replay_id = first_payload["replay_id"]

            stdout_second = io.StringIO()
            with redirect_stdout(stdout_second):
                exit_code = main(
                    [
                        "--config-path",
                        str(config_path),
                        "--policy-path",
                        str(policy_path),
                        "debug",
                        "replay",
                        correlation_id,
                    ]
                )
            self.assertEqual(exit_code, 0)
            second_payload = json.loads(stdout_second.getvalue())
            self.assertTrue(second_payload["reused_existing"])
            self.assertEqual(second_payload["replay_id"], replay_id)

            services, _, _ = _build_services(Path(tmp))
            try:
                row = services.database.fetchone(
                    "SELECT COUNT(*) AS count FROM debug_replay_runs",
                )
                self.assertEqual(int(row["count"]), 1)
                dead_letter_row = services.database.fetchone(
                    "SELECT COUNT(*) AS count FROM dead_letter_records WHERE domain = 'debug_replay'",
                )
                self.assertEqual(int(dead_letter_row["count"]), 0)
                trace = services.database.fetch_trace_report(first_payload["correlation_id"])
                self.assertTrue(trace["found"])
                self.assertEqual(trace["summary"]["counts"]["debug_replays"], 1)
            finally:
                services.close()

    def test_debug_replay_failure_creates_dead_letter(self):
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
                        text="On rejoue ce thread pour verifier le debug.",
                        thread_ref=ConversationThreadRef(thread_id="thread_pack2_failure", channel="discord"),
                    ),
                )
                dispatch = services.gateway.dispatch_event(
                    event,
                    target_profile="browser",
                    requested_worker="browser",
                )
                with patch.object(services.gateway, "dispatch_event", side_effect=RuntimeError("replay boom")):
                    payload = services.gateway.replay_identifier(str(dispatch.correlation_id), force=True)
                self.assertEqual(payload["status"], "failed")
                row = services.database.fetchone(
                    """
                    SELECT *
                    FROM dead_letter_records
                    WHERE domain = 'debug_replay'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                self.assertIsNotNone(row)
                self.assertEqual(str(row["source_entity_kind"]), TraceEntityKind.DEBUG_REPLAY.value)
                self.assertEqual(int(row["replayable"]), 1)
            finally:
                services.close()

    def test_operator_delivery_dead_letter_is_canonical_and_requeue_updates_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, _ = _build_services(Path(tmp))
            try:
                published = services.api_runs.publish_operator_update(
                    title="Incident Discord",
                    summary="Le bot doit publier une alerte operateur.",
                    text="Alerte de test pour dead letter operateur.",
                    target="channel:123",
                    reply_to="discord-message-123",
                )
                delivery_id = str(published["delivery_id"])
                failed = services.api_runs.mark_operator_delivery(
                    delivery_id=delivery_id,
                    status=OperatorDeliveryStatus.FAILED,
                    error="discord_down",
                )
                self.assertEqual(failed["status"], "failed")
                row = services.database.fetchone(
                    """
                    SELECT *
                    FROM dead_letter_records
                    WHERE domain = 'operator_delivery'
                      AND source_entity_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (delivery_id,),
                )
                self.assertIsNotNone(row)
                self.assertEqual(str(row["status"]), "active")
                replayed = services.api_runs.requeue_operator_delivery(delivery_id=delivery_id)
                self.assertEqual(replayed["status"], "pending")
                row = services.database.fetchone(
                    """
                    SELECT *
                    FROM dead_letter_records
                    WHERE domain = 'operator_delivery'
                      AND source_entity_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (delivery_id,),
                )
                self.assertEqual(str(row["status"]), "requeued")
            finally:
                services.close()

    def test_deep_research_resume_job_is_idempotent_and_resolves_dead_letter(self):
        with tempfile.TemporaryDirectory() as tmp:
            services, _, _ = _build_services(Path(tmp))
            try:
                completed_job_id = "deep_research_job_completed_pack2"
                completed_root = services.path_policy.ensure_allowed_write(
                    services.paths.runtime_root / "deep_research" / completed_job_id
                )
                completed_root.mkdir(parents=True, exist_ok=True)
                (completed_root / "request.json").write_text(
                    json.dumps({"job_id": completed_job_id, "title": "Completed job"}, ensure_ascii=True, indent=2),
                    encoding="utf-8",
                )
                (completed_root / "status.json").write_text(
                    json.dumps({"job_id": completed_job_id, "status": "completed"}, ensure_ascii=True, indent=2),
                    encoding="utf-8",
                )
                (completed_root / "result.json").write_text(
                    json.dumps({"status": "completed"}, ensure_ascii=True, indent=2),
                    encoding="utf-8",
                )
                skipped = services.deep_research.resume_job(job_id=completed_job_id)
                self.assertEqual(skipped["status"], "skipped_completed")

                failed_job_id = "deep_research_job_failed_pack2"
                failed_root = services.path_policy.ensure_allowed_write(
                    services.paths.runtime_root / "deep_research" / failed_job_id
                )
                failed_root.mkdir(parents=True, exist_ok=True)
                (failed_root / "request.json").write_text(
                    json.dumps(
                        {
                            "job_id": failed_job_id,
                            "title": "Failed job",
                            "correlation_id": "correlation_pack2_resume",
                        },
                        ensure_ascii=True,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                (failed_root / "status.json").write_text(
                    json.dumps(
                        {
                            "job_id": failed_job_id,
                            "status": "failed",
                            "failed_at": "2026-03-17T00:00:00+00:00",
                        },
                        ensure_ascii=True,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                services.database.record_dead_letter(
                    domain="deep_research_job",
                    source_entity_kind=TraceEntityKind.DEEP_RESEARCH_JOB.value,
                    source_entity_id=failed_job_id,
                    status="active",
                    replayable=True,
                )
                with patch.object(
                    services.deep_research,
                    "run_job_request",
                    return_value={
                        "job_id": failed_job_id,
                        "status": "completed",
                        "completed_at": "2026-03-17T01:00:00+00:00",
                    },
                ) as mocked_run:
                    resumed = services.deep_research.resume_job(job_id=failed_job_id, stale_after_minutes=1)
                self.assertTrue(resumed["resumed"])
                mocked_run.assert_called_once()
                row = services.database.fetchone(
                    """
                    SELECT *
                    FROM dead_letter_records
                    WHERE domain = 'deep_research_job'
                      AND source_entity_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (failed_job_id,),
                )
                self.assertEqual(str(row["status"]), "resolved")
            finally:
                services.close()


if __name__ == "__main__":
    unittest.main()
