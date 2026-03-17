from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.cli import main
from project_os_core.scheduler.service import ScheduledTask
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


class SchedulerServiceTests(unittest.TestCase):
    def test_default_tasks_are_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                tasks = services.scheduler.list_tasks()
                self.assertEqual(len(tasks), 9)
                self.assertEqual(
                    [task.name for task in tasks],
                    [
                        "cleanup_expired_deliveries",
                        "daily_audit",
                        "github_issue_learning_sync",
                        "health_check",
                        "memory_block_refresh",
                        "memory_compact",
                        "memory_curator_sleeptime",
                        "memory_supersession_scan",
                        "project_review_loop",
                    ],
                )
                daily_audit = next(task for task in tasks if task.name == "daily_audit")
                self.assertFalse(daily_audit.enabled)
            finally:
                services.close()

    def test_get_due_tasks_returns_only_past_enabled_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                now = datetime.now(timezone.utc)
                services.database.execute(
                    "UPDATE scheduled_tasks SET next_run_at = ?, enabled = 1 WHERE name = ?",
                    ((now - timedelta(minutes=5)).isoformat(), "memory_compact"),
                )
                services.database.execute(
                    "UPDATE scheduled_tasks SET next_run_at = ?, enabled = 1 WHERE name = ?",
                    ((now + timedelta(minutes=5)).isoformat(), "health_check"),
                )
                services.database.execute(
                    "UPDATE scheduled_tasks SET next_run_at = ?, enabled = 0 WHERE name = ?",
                    ((now - timedelta(minutes=5)).isoformat(), "daily_audit"),
                )

                due_tasks = services.scheduler.get_due_tasks()

                self.assertEqual([task.name for task in due_tasks], ["memory_compact"])
            finally:
                services.close()

    def test_mark_task_executed_updates_last_run_and_next_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                task = next(item for item in services.scheduler.list_tasks() if item.name == "health_check")
                fixed_now = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
                with patch("project_os_core.scheduler.service._utc_now", return_value=fixed_now):
                    services.scheduler.mark_task_executed(task.task_id, status="success")
                updated = services.scheduler.get_task(task.task_id)

                self.assertEqual(updated.last_status, "success")
                self.assertEqual(updated.last_run_at, fixed_now.isoformat())
                self.assertEqual(updated.next_run_at, (fixed_now + timedelta(seconds=3600)).isoformat())
            finally:
                services.close()

    def test_tick_executes_due_task_and_marks_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.database.execute(
                    "UPDATE scheduled_tasks SET next_run_at = ?, enabled = 1 WHERE name = ?",
                    ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "memory_compact"),
                )
                calls: list[tuple[str, dict]] = []

                def executor(command, args_dict):
                    calls.append((command, args_dict))
                    return {"ok": True}

                results = services.scheduler.tick(executor=executor)
                task = next(item for item in services.scheduler.list_tasks() if item.name == "memory_compact")

                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], "memory_compact")
                self.assertEqual(results[0]["status"], "success")
                self.assertEqual(task.last_status, "success")
            finally:
                services.close()

    def test_tick_marks_failed_when_executor_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                services.database.execute(
                    "UPDATE scheduled_tasks SET next_run_at = ?, enabled = 1 WHERE name = ?",
                    ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "health_check"),
                )

                def executor(command, args_dict):
                    del command, args_dict
                    raise RuntimeError("health_down")

                results = services.scheduler.tick(executor=executor)
                task = next(item for item in services.scheduler.list_tasks() if item.name == "health_check")

                self.assertEqual(results[0]["status"], "failed")
                self.assertEqual(results[0]["error"], "health_down")
                self.assertEqual(task.last_status, "failed")
                self.assertEqual(task.last_error, "health_down")
            finally:
                services.close()

    def test_tick_without_due_tasks_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                calls: list[tuple[str, dict]] = []

                def executor(command, args_dict):
                    calls.append((command, args_dict))
                    return {"ok": True}

                results = services.scheduler.tick(executor=executor)

                self.assertEqual(results, [])
                self.assertEqual(calls, [])
            finally:
                services.close()

    def test_scheduler_tick_cli_serializes_curator_run_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            services = _build_services(tmp_path)
            try:
                services.database.execute(
                    "UPDATE scheduled_tasks SET next_run_at = ?, enabled = 1 WHERE name = ?",
                    ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "memory_curator_sleeptime"),
                )
            finally:
                services.close()

            config_path = tmp_path / "storage_roots.json"
            policy_path = tmp_path / "runtime_policy.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--config-path",
                        str(config_path),
                        "--policy-path",
                        str(policy_path),
                        "scheduler",
                        "tick",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload[0]["name"], "memory_curator_sleeptime")
            self.assertEqual(payload[0]["status"], "success")
            self.assertIn("run", payload[0]["result"])
            self.assertIn("curator_run_id", payload[0]["result"]["run"])

    def test_enable_and_disable_task_toggle_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                disabled = services.scheduler.disable_task("health_check")
                enabled = services.scheduler.enable_task("health_check")

                self.assertFalse(disabled.enabled)
                self.assertTrue(enabled.enabled)
                self.assertIsNotNone(enabled.next_run_at)
            finally:
                services.close()

    def test_compute_next_run_for_interval_uses_interval_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                task = ScheduledTask(
                    task_id="sched_task_test",
                    name="interval_test",
                    schedule_kind="interval",
                    interval_seconds=900,
                    daily_at_hour=None,
                    daily_at_minute=None,
                    command="noop",
                )
                fixed_now = datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc)
                with patch("project_os_core.scheduler.service._utc_now", return_value=fixed_now):
                    next_run = services.scheduler._compute_next_run(task)

                self.assertEqual(next_run, (fixed_now + timedelta(seconds=900)).isoformat())
            finally:
                services.close()

    def test_compute_next_run_for_daily_task_rolls_to_next_day_when_time_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                task = ScheduledTask(
                    task_id="sched_task_test",
                    name="daily_test",
                    schedule_kind="daily_at",
                    interval_seconds=None,
                    daily_at_hour=6,
                    daily_at_minute=0,
                    command="noop",
                )
                fixed_now = datetime(2026, 3, 14, 8, 15, tzinfo=timezone.utc)
                with patch("project_os_core.scheduler.service._utc_now", return_value=fixed_now):
                    next_run = services.scheduler._compute_next_run(task)

                self.assertEqual(next_run, datetime(2026, 3, 15, 6, 0, tzinfo=timezone.utc).isoformat())
            finally:
                services.close()
