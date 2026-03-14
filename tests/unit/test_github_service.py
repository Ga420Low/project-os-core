from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.cli import _execute_scheduler_task
from project_os_core.github.parsing import (
    labels_to_modules,
    labels_to_severity,
    parse_issue_sections,
)
from project_os_core.github.validation import validate_issue_resolution_body
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
        "api_dashboard_config": {
            "auto_start": False,
            "auto_open_browser": False,
        },
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
    return build_app_services(config_path=str(config_path), policy_path=str(policy_path))


def _structured_issue_body() -> str:
    return """## Description
The issue was found during a structured audit.

## Impact
The workflow loses a distinct state and risks incorrect operator decisions.

## Root Cause
The runtime was missing a dedicated branch for the issue path.

## Resolution
Add the missing dedicated branch and persist the distinct state.

## Regression Coverage
Add unit tests and a scheduler smoke path.

## Durable Lesson
Workflow states need explicit serialization and explicit downstream handling.

## Reusable Pattern
When adding a new state, update prompts, parsers, dashboards, and tests in the same lot.

## Repeated Pattern
Status additions keep failing when only one layer is updated.

## Eval Scenario
Close a learning-ready issue, sync it locally, and confirm a single canonical ingestion.
"""


def _issue_payload() -> dict[str, object]:
    return {
        "number": 101,
        "node_id": "ISSUE_NODE_101",
        "title": "Fix distinct needs_revision handling",
        "state": "closed",
        "body": _structured_issue_body(),
        "html_url": "https://github.com/Ga420Low/project-os-core/issues/101",
        "closed_at": "2026-03-14T09:00:00+00:00",
        "updated_at": "2026-03-14T10:00:00+00:00",
        "labels": [
            {"name": "bug"},
            {"name": "P1-critical"},
            {"name": "module:models"},
            {"name": "audit-finding"},
        ],
    }


class GitHubServiceTests(unittest.TestCase):
    def test_parse_issue_sections_and_label_mapping(self):
        sections = parse_issue_sections(_structured_issue_body())
        self.assertEqual(sections["Resolution"], "Add the missing dedicated branch and persist the distinct state.")
        self.assertEqual(labels_to_severity(["bug", "P2-important"]), "high")
        self.assertEqual(labels_to_modules(["module:gateway", "module:learning", "bug"]), ["gateway", "learning"])

    def test_sync_learning_ingests_issue_and_dedupes_second_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                issue_json = json.dumps([_issue_payload()])

                def _fake_run(command, **kwargs):
                    if command[1:3] == ["auth", "status"]:
                        return subprocess.CompletedProcess(command, 0, stdout="logged in", stderr="")
                    if len(command) >= 2 and command[1] == "api":
                        return subprocess.CompletedProcess(command, 0, stdout=issue_json, stderr="")
                    raise AssertionError(f"Unexpected subprocess call: {command}")

                with patch("project_os_core.github.service.shutil.which", return_value="C:/Tools/gh.exe"):
                    with patch("project_os_core.github.service.subprocess.run", side_effect=_fake_run):
                        first = services.github.sync_learning(limit=10)
                        second = services.github.sync_learning(limit=10)

                self.assertEqual(first["ingested"], 1)
                self.assertEqual(second["ingested"], 0)
                self.assertTrue(any(item["reason"] == "already_ingested" for item in second["processed"]))
                signal_rows = services.database.fetchall(
                    "SELECT * FROM learning_signals WHERE kind = ?",
                    ("issue_resolved",),
                )
                decision_rows = services.database.fetchall("SELECT * FROM decision_records")
                loop_rows = services.database.fetchall("SELECT * FROM loop_signals")
                eval_rows = services.database.fetchall("SELECT * FROM eval_candidates")
                dataset_rows = services.database.fetchall("SELECT * FROM dataset_candidates")
                ingestion_rows = services.database.fetchall("SELECT * FROM github_issue_ingestions")

                self.assertEqual(len(signal_rows), 1)
                self.assertGreaterEqual(len(decision_rows), 2)
                self.assertEqual(len(loop_rows), 1)
                self.assertEqual(len(eval_rows), 1)
                self.assertEqual(len(dataset_rows), 1)
                self.assertEqual(len(ingestion_rows), 1)
            finally:
                services.close()

    def test_scheduler_github_sync_noops_cleanly_when_gh_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            services = _build_services(Path(tmp))
            try:
                with patch("project_os_core.github.service.shutil.which", return_value=None):
                    payload = _execute_scheduler_task(services, "github_issue_learning_sync", {"limit": 25})

                self.assertEqual(payload["status"], "skipped")
                self.assertEqual(payload["reason"], "gh_missing")
            finally:
                services.close()

    def test_resolution_validation_script_fails_when_sections_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            body_path = Path(tmp) / "issue.md"
            body_path.write_text("## Description\nFilled.\n\n## Impact\nFilled.\n", encoding="utf-8")
            script_path = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "validate_issue_resolution.py"

            completed = subprocess.run(
                [sys.executable, str(script_path), "--body-file", str(body_path)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("missing required resolution sections", completed.stdout)

    def test_validation_module_accepts_complete_issue_body(self):
        validation = validate_issue_resolution_body(_structured_issue_body())
        self.assertTrue(validation["valid"])


if __name__ == "__main__":
    unittest.main()
