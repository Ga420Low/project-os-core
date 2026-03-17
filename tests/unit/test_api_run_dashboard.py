from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.api_runs.dashboard import (
    _make_handler,
    _recent_operator_visibility,
    _wait_for_operator_beacon,
    _write_visibility_state,
    build_dashboard_payload,
    ensure_dashboard_running,
    render_dashboard_html,
)
from project_os_core.models import (
    ApiRunMode,
    ApiRunReview,
    ApiRunReviewVerdict,
    ChannelEvent,
    ConversationThreadRef,
    OperatorMessage,
    RuntimeState,
    RuntimeVerdict,
    new_id,
)
from project_os_core.secrets import SecretLookup
from project_os_core.services import build_app_services


def _install_stub_reviewer(services):
    def _stub(result, context_pack):
        review = ApiRunReview(
            review_id=new_id("run_review"),
            run_id=result.run_id,
            verdict=ApiRunReviewVerdict.ACCEPTED_WITH_RESERVES,
            reviewer="claude-sonnet-4-20250514",
            findings=["Claude review found one minor reserve."],
            followup_actions=["Apply the minor correction before integration."],
            metadata={
                "type": "review_result",
                "source": "test_stub",
                "summary": "Claude review found one minor reserve.",
                "recommendation": "Apply the minor correction before integration.",
                "issues_found": 1,
                "critical": 0,
                "high": 1,
                "usage": {"input_tokens": 120, "output_tokens": 40},
                "estimated_cost_eur": 0.0012,
                "context_pack_id": context_pack.context_pack_id,
            },
        )
        services.api_runs._store_run_review(review)
        return review

    services.api_runs._call_reviewer = _stub


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
            "require_visible_ui": False,
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
    _install_stub_reviewer(services)
    return services


def _mark_runtime_ready(services, profile_name: str = "core") -> None:
    session = services.runtime.open_session(profile_name=profile_name, owner="founder")
    services.runtime.record_runtime_state(
        RuntimeState(
            runtime_state_id=new_id("runtime_state"),
            session_id=session.session_id,
            verdict=RuntimeVerdict.READY,
            active_profile=profile_name,
        )
    )


class ApiRunDashboardTests(unittest.TestCase):
    def test_dashboard_renders_needs_revision_badge(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                payload = build_dashboard_payload(services, limit=2)
                payload["snapshot"]["current_run"] = {
                    "run_id": "api_run_test",
                    "review_verdict": "needs_revision",
                    "status": "reviewed",
                    "mode": "patch_plan",
                    "branch_name": "codex/project-os-test-needs-revision",
                    "objective": "Revise the lot before integration.",
                }
                payload["snapshot"]["latest_runs"] = [dict(payload["snapshot"]["current_run"])]
                html = render_dashboard_html(payload, refresh_seconds=4)

                self.assertIn("review-needs_revision", html)
                self.assertIn("needs_revision", html)
            finally:
                services.close()

    def test_recent_operator_visibility_allows_reuse_without_new_browser_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "operator_visibility.json"
            _write_visibility_state(state_path, "focus_test")
            with patch("project_os_core.api_runs.dashboard._dashboard_reachable", return_value=True):
                with patch("project_os_core.api_runs.dashboard._launch_operator_dashboard") as launch:
                    status = ensure_dashboard_running(
                        repo_root=Path(tmp),
                        require_visible_ui=True,
                        open_browser=True,
                        visibility_state_path=state_path,
                        recent_beacon_grace_seconds=1800,
                    )
            self.assertTrue(status["ready"])
            self.assertEqual(status["reason"], "recent_operator_beacon")
            launch.assert_not_called()

    def test_recent_operator_visibility_expires_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "operator_visibility.json"
            state_path.write_text(
                json.dumps({"last_seen_at": "2020-01-01T00:00:00+00:00", "token": "focus_old"}, ensure_ascii=True),
                encoding="utf-8",
            )
            status = _recent_operator_visibility(state_path, max_age_seconds=60)
            self.assertFalse(status["fresh"])
            self.assertEqual(status["token"], "focus_old")

    def test_wait_for_operator_beacon_accepts_persisted_cross_process_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "operator_visibility.json"
            token = "focus_cross_process"

            def _writer():
                time.sleep(0.15)
                _write_visibility_state(state_path, token)

            writer = threading.Thread(target=_writer)
            writer.start()
            try:
                self.assertTrue(
                    _wait_for_operator_beacon(
                        token,
                        timeout_seconds=1.0,
                        state_path=state_path,
                    )
                )
            finally:
                writer.join()

    def test_dashboard_visibility_retries_browser_open_once_before_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "operator_visibility.json"
            wait_calls: list[str] = []

            def _fake_wait(token: str, *, timeout_seconds: float, state_path: Path | None = None) -> bool:
                wait_calls.append(token)
                if len(wait_calls) == 2:
                    _write_visibility_state(state_path, token)
                    return True
                return False

            with patch("project_os_core.api_runs.dashboard._dashboard_reachable", return_value=True):
                with patch("project_os_core.api_runs.dashboard._launch_operator_dashboard") as launch:
                    with patch("project_os_core.api_runs.dashboard._wait_for_operator_beacon", side_effect=_fake_wait):
                        status = ensure_dashboard_running(
                            repo_root=Path(tmp),
                            require_visible_ui=True,
                            open_browser=True,
                            visibility_state_path=state_path,
                            wait_seconds=1.0,
                        )
            self.assertTrue(status["ready"])
            self.assertEqual(status["reason"], "beacon_verified")
            self.assertEqual(launch.call_count, 2)
            self.assertEqual(len(wait_calls), 2)

    def test_dashboard_payload_contains_preview_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                context_pack = services.api_runs.build_context_pack(
                    mode=ApiRunMode.PATCH_PLAN,
                    objective="Build the local dashboard for API runs.",
                    branch_name="codex/project-os-test-dashboard",
                    skill_tags=["patch_plan", "dashboard"],
                )
                prompt = services.api_runs.render_prompt(context_pack_id=context_pack.context_pack_id)
                contract = services.api_runs.create_run_contract(
                    context_pack_id=context_pack.context_pack_id,
                    prompt_template_id=prompt.prompt_template_id,
                )
                contract.metadata["allow_branch_mismatch"] = True
                contract.metadata["allow_dirty_worktree"] = True
                services.api_runs._persist_run_contract(contract)
                services.api_runs.approve_run_contract(contract_id=contract.contract_id, founder_decision="go")
                payload = services.api_runs.execute_run(
                    contract_id=contract.contract_id,
                    response_runner=lambda request, prompt, context: {
                        "model": "gpt-5.4",
                        "output_text": json.dumps(
                            {
                                "decision": "Build the local dashboard in a single lot.",
                                "why": "A visible interface improves supervision.",
                                "alternatives": ["Stay terminal-only."],
                                "files_to_change": ["src/project_os_core/api_runs/dashboard.py"],
                                "interfaces": ["ApiRunResult"],
                                "patch_outline": ["Add a local web server.", "Render current run and artifacts."],
                                "tests": ["Dashboard payload test."],
                                "risks": ["UI drift from runtime state."],
                                "acceptance_criteria": ["Current run is visible in a browser."],
                                "open_questions": [],
                            }
                        ),
                        "usage": {"input_tokens": 1000, "output_tokens": 500},
                    },
                )
                snapshot = build_dashboard_payload(services, limit=5)
                self.assertEqual(snapshot["snapshot"]["current_run"]["run_id"], payload["result"].run_id)
                self.assertEqual(snapshot["current_preview"]["decision"], "Build the local dashboard in a single lot.")
                self.assertGreaterEqual(len(snapshot["current_artifacts"]), 4)
                self.assertIn("no_loss_audit", snapshot)
                self.assertIn("operator_delivery_health", snapshot)
            finally:
                services.close()

    def test_dashboard_payload_exposes_gateway_reply_audit_for_artifact_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                _mark_runtime_ready(services)

                def _stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    del message, model, route_reason, context_bundle
                    return (
                        "Decision: basculer en artifact-first.\n"
                        "Action: livrer un resume Discord.\n"
                        "Action: joindre le document complet.\n\n"
                        + ("Plan detaille a relire " * 260)
                    )

                services.gateway._call_simple_chat = _stub_simple_chat  # type: ignore[method-assign]
                services.gateway._should_inline_chat = lambda event, decision: True  # type: ignore[method-assign]
                services.gateway._maybe_create_reasoning_escalation_approval = lambda *args, **kwargs: None  # type: ignore[method-assign]

                services.gateway.dispatch_event(
                    ChannelEvent(
                        event_id=new_id("channel_event"),
                        surface="discord",
                        event_type="message.created",
                        message=OperatorMessage(
                            message_id=new_id("message"),
                            actor_id="founder",
                            channel="discord",
                            text=("j'ai besoin d'une reponse complete a verifier " * 80),
                            thread_ref=ConversationThreadRef(
                                thread_id="thread_dashboard_gateway_audit",
                                channel="discord",
                                external_thread_id="channel:thread_dashboard_gateway_audit",
                            ),
                        ),
                    ),
                    target_profile="core",
                )

                payload = build_dashboard_payload(services, limit=5)
                self.assertEqual(payload["gateway_reply_audit"]["artifact_summary_count"], 1)
                self.assertEqual(payload["gateway_reply_audit"]["manifest_gap_count"], 0)
                self.assertEqual(payload["gateway_reply_audit"]["status"], "attention")
                self.assertEqual(payload["gateway_reply_audit"]["recent_replies"][0]["delivery_mode"], "artifact_summary")
            finally:
                services.close()

    def test_dashboard_html_contains_live_panels(self):
        html = render_dashboard_html(
            {
                "generated_at": "2026-03-13T12:00:00+00:00",
                "snapshot": {
                    "budget": {
                        "daily_spend_estimate_eur": 0.1,
                        "monthly_spend_estimate_eur": 0.4,
                        "daily_soft_limit_eur": 1.5,
                        "monthly_limit_eur": 50.0,
                    },
                    "current_run": {
                        "run_id": "api_run_test",
                        "mode": "audit",
                        "branch_name": "codex/project-os-test-dashboard-html",
                        "status": "running",
                        "contract_status": "approved",
                        "phase": "generation",
                        "review_verdict": "pending",
                        "objective": "Verifier l'affichage de garde.",
                        "created_at": "2026-03-13T12:00:00+00:00",
                        "estimated_cost_eur": 0.2,
                        "machine_summary": "Generation en cours.",
                        "operator_guard_reason": "recent_beacon",
                        "lifecycle_event_kind": "run_started",
                        "operator_delivery_status": "pending",
                        "operator_channel_hint": "runs_live",
                    },
                    "latest_runs": [
                        {
                            "mode": "audit",
                            "branch_name": "codex/project-os-test-dashboard-html",
                            "status": "running",
                            "review_verdict": "pending",
                            "created_at": "2026-03-13T12:00:00+00:00",
                            "estimated_cost_eur": 0.2,
                            "objective": "Verifier l'affichage de garde.",
                            "operator_guard_reason": "recent_beacon",
                            "lifecycle_event_kind": "run_started",
                            "operator_delivery_status": "pending",
                        }
                    ],
                    "operator_delivery_counts": {"pending": 1},
                    "operator_delivery_health": {"counts": {"queued": 1}, "status": "ok"},
                    "no_loss_audit": {"status": "ok", "silent_loss_risk_count": 0, "dead_letter_count": 0, "replayable_count": 1},
                },
                "current_artifacts": [],
                "current_preview": None,
                "current_clarification": {
                    "cause": "Le lot doit etre clarifie.",
                    "impact": "Le run s'arrete proprement.",
                    "question_for_founder": "Confirme le perimetre du lot.",
                    "recommended_contract_change": "Amender l'objectif.",
                    "requires_reapproval": True,
                },
                "operator_delivery_health": {"counts": {"queued": 1}, "status": "ok"},
                "no_loss_audit": {"status": "ok", "silent_loss_risk_count": 0, "dead_letter_count": 0, "replayable_count": 1},
                "gateway_reply_audit": {
                    "status": "ok",
                    "delivery_mode_counts": {"artifact_summary": 1},
                    "artifact_summary_count": 1,
                    "manifest_gap_count": 0,
                    "recent_replies": [
                        {
                            "reply_kind": "chat_response",
                            "delivery_mode": "artifact_summary",
                            "attachment_count": 1,
                            "summary": "Plan complet pret.",
                            "created_at": "2026-03-13T12:00:00+00:00",
                            "channel": "discord",
                        }
                    ],
                },
                "status_counts": {},
                "review_counts": {},
                "lane_policy": {
                    "coding_lane": "repo_cli",
                    "desktop_lane": "future_computer_use",
                    "discord_surface": "mandatory",
                    "voice_mode": "future_ready",
                    "memory_sync": "selective_sync",
                },
            },
            refresh_seconds=5,
        )
        self.assertIn("Project OS Agent API", html)
        self.assertIn("Execution en cours", html)
        self.assertIn("Runs recents", html)
        self.assertIn("Apercu structure", html)
        self.assertIn("garde recent_beacon", html)
        self.assertIn("Clarification", html)
        self.assertIn("signal run_started", html)
        self.assertIn("livraison pending", html)
        self.assertIn("No-loss et UX Discord", html)
        self.assertIn("silent risks 0", html)
        self.assertIn("mode artifact_summary", html)

    def test_dashboard_http_500_hides_internal_exception_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                handler = _make_handler(services=services, limit=4, refresh_seconds=4, visibility_state_path=None)
                server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    port = server.server_address[1]
                    with patch("project_os_core.api_runs.dashboard.build_dashboard_payload", side_effect=RuntimeError("sqlite path leaked")):
                        with self.assertRaises(HTTPError) as ctx:
                            urlopen(f"http://127.0.0.1:{port}/api/snapshot")
                    error_response = ctx.exception
                    self.assertEqual(error_response.code, 500)
                    payload = json.loads(error_response.read().decode("utf-8"))
                    error_response.close()
                    self.assertEqual(payload["error"], "dashboard_error")
                    self.assertEqual(payload["message"], "internal server error")
                    self.assertNotIn("detail", payload)
                    self.assertNotIn("sqlite path leaked", json.dumps(payload))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
            finally:
                services.close()
