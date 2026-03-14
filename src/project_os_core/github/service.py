from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import GitHubConfig
from ..database import CanonicalDatabase, dump_json
from ..learning.service import LearningService
from ..models import DecisionStatus, LearningSignalKind
from ..observability import StructuredLogger
from ..runtime.journal import LocalJournal
from .parsing import (
    ParsedGitHubIssue,
    issue_matches_learning_labels,
    labels_to_modules,
    labels_to_severity,
    parse_issue_payload,
    section_has_signal,
)
from .validation import validate_issue_resolution_body


class GitHubLearningService:
    def __init__(
        self,
        *,
        config: GitHubConfig,
        database: CanonicalDatabase,
        learning: LearningService,
        journal: LocalJournal,
        logger: StructuredLogger,
        repo_root: Path,
    ) -> None:
        self.config = config
        self.database = database
        self.learning = learning
        self.journal = journal
        self.logger = logger
        self.repo_root = repo_root

    def sync_learning(self, *, limit: int = 100) -> dict[str, Any]:
        if not self.config.sync_enabled:
            return self._skip_sync("github_sync_disabled")
        if shutil.which(self.config.cli_command) is None:
            return self._skip_sync("gh_missing")
        if not self._gh_authenticated():
            return self._skip_sync("gh_unauthenticated")

        issues = self._fetch_closed_issues(limit=limit)
        ingested = 0
        skipped = 0
        processed: list[dict[str, Any]] = []
        for payload in issues:
            if payload.get("pull_request"):
                skipped += 1
                continue
            issue = parse_issue_payload(payload, repo=self.config.repo)
            if not issue_matches_learning_labels(issue.labels, self.config.learning_label_filter):
                skipped += 1
                continue
            validation = validate_issue_resolution_body(issue.body)
            if not validation["valid"]:
                skipped += 1
                processed.append(
                    {
                        "issue_number": issue.issue_number,
                        "title": issue.title,
                        "status": "skipped",
                        "reason": "missing_resolution_sections",
                        "missing_sections": list(validation["missing_sections"]),
                    }
                )
                continue
            existing = self.database.fetchone(
                "SELECT payload_sha256 FROM github_issue_ingestions WHERE repo = ? AND issue_number = ?",
                (self.config.repo, issue.issue_number),
            )
            if existing is not None and str(existing["payload_sha256"]) == issue.content_sha256:
                skipped += 1
                processed.append(
                    {
                        "issue_number": issue.issue_number,
                        "title": issue.title,
                        "status": "skipped",
                        "reason": "already_ingested",
                    }
                )
                continue
            learning_refs = self._ingest_issue(issue)
            ingested += 1
            processed.append(
                {
                    "issue_number": issue.issue_number,
                    "title": issue.title,
                    "status": "ingested",
                    "learning_refs": learning_refs,
                }
            )
            self.database.upsert(
                "github_issue_ingestions",
                {
                    "repo": self.config.repo,
                    "issue_number": issue.issue_number,
                    "issue_id": issue.issue_id,
                    "title": issue.title,
                    "state": issue.state,
                    "labels_json": dump_json(issue.labels),
                    "payload_sha256": issue.content_sha256,
                    "updated_at": issue.updated_at or datetime.now(timezone.utc).isoformat(),
                    "closed_at": issue.closed_at,
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                    "learning_refs_json": dump_json(learning_refs),
                    "metadata_json": dump_json(
                        {
                            "url": issue.url,
                            "scope_label": issue.scope_label,
                            "sections": issue.sections,
                        }
                    ),
                },
                conflict_columns=["repo", "issue_number"],
            )

        result = {
            "status": "success",
            "repo": self.config.repo,
            "fetched": len(issues),
            "ingested": ingested,
            "skipped": skipped,
            "processed": processed,
        }
        self.logger.log(
            "INFO",
            "github_issue_learning_sync_completed",
            repo=self.config.repo,
            fetched=len(issues),
            ingested=ingested,
            skipped=skipped,
        )
        self.journal.append("github_issue_learning_sync_completed", "github", result)
        return result

    def _skip_sync(self, reason: str) -> dict[str, Any]:
        payload = {"status": "skipped", "repo": self.config.repo, "reason": reason}
        self.logger.log("INFO", "github_issue_learning_sync_skipped", repo=self.config.repo, reason=reason)
        self.journal.append("github_issue_learning_sync_skipped", "github", payload)
        return payload

    def _gh_authenticated(self) -> bool:
        completed = subprocess.run(
            [self.config.cli_command, "auth", "status"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode == 0

    def _fetch_closed_issues(self, *, limit: int) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        completed = subprocess.run(
            [
                self.config.cli_command,
                "api",
                f"repos/{self.config.repo}/issues?state=closed&per_page={bounded_limit}",
            ],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(completed.stdout or "[]")
        if not isinstance(payload, list):
            raise RuntimeError("gh api did not return an issue list")
        return [item for item in payload if isinstance(item, dict)]

    def _ingest_issue(self, issue: ParsedGitHubIssue) -> list[dict[str, str]]:
        learning_refs: list[dict[str, str]] = []
        severity = labels_to_severity(issue.labels)
        modules = labels_to_modules(issue.labels)
        signal = self.learning.record_signal(
            kind=LearningSignalKind.ISSUE_RESOLVED,
            severity=severity,
            summary=f"Resolved issue #{issue.issue_number}: {issue.title}",
            source_ids=[issue.issue_ref],
            metadata={
                "repo": issue.repo,
                "issue_number": issue.issue_number,
                "labels": issue.labels,
                "modules": modules,
                "url": issue.url,
            },
        )
        learning_refs.append({"type": "signal", "id": signal.signal_id})

        resolution = issue.sections.get("Resolution", "")
        if section_has_signal(resolution):
            record = self.learning.record_decision(
                status=DecisionStatus.CONFIRMED,
                scope=f"github_issue:{issue.repo}:{issue.scope_label}",
                summary=resolution,
                metadata={"issue_number": issue.issue_number, "title": issue.title, "kind": "resolution"},
            )
            learning_refs.append({"type": "decision", "id": record.decision_record_id})

        durable_lesson = issue.sections.get("Durable Lesson", "")
        if section_has_signal(durable_lesson):
            record = self.learning.record_decision(
                status=DecisionStatus.CONFIRMED,
                scope=f"github_lesson:{issue.repo}:{issue.scope_label}",
                summary=durable_lesson,
                metadata={"issue_number": issue.issue_number, "title": issue.title, "kind": "durable_lesson"},
            )
            learning_refs.append({"type": "decision", "id": record.decision_record_id})

        repeated_pattern = issue.sections.get("Repeated Pattern", "")
        if section_has_signal(repeated_pattern):
            loop_signal = self.learning.record_loop_signal(
                repeated_pattern=repeated_pattern,
                impacted_area=issue.scope_label,
                recommended_reset=resolution or durable_lesson or "Review the issue history and change the execution sequence.",
                source_ids=[issue.issue_ref],
                metadata={"issue_number": issue.issue_number, "title": issue.title},
            )
            learning_refs.append({"type": "loop_signal", "id": loop_signal.loop_signal_id})

        eval_scenario = issue.sections.get("Eval Scenario", "")
        if section_has_signal(eval_scenario):
            eval_candidate = self.learning.record_eval_candidate(
                scenario=eval_scenario,
                target_system=f"{issue.repo}:{issue.scope_label}",
                expected_behavior=resolution or durable_lesson or issue.title,
                source_ids=[issue.issue_ref],
                metadata={"issue_number": issue.issue_number, "title": issue.title},
            )
            learning_refs.append({"type": "eval_candidate", "id": eval_candidate.eval_candidate_id})

        regression_coverage = issue.sections.get("Regression Coverage", "")
        reusable_pattern = issue.sections.get("Reusable Pattern", "")
        if section_has_signal(regression_coverage) or section_has_signal(reusable_pattern):
            quality_score = 0.6
            if section_has_signal(regression_coverage):
                quality_score += 0.2
            if section_has_signal(reusable_pattern):
                quality_score += 0.15
            if section_has_signal(durable_lesson):
                quality_score += 0.05
            dataset_candidate = self.learning.record_dataset_candidate(
                source_type="github_issue_resolution",
                quality_score=min(1.0, quality_score),
                export_ready=section_has_signal(regression_coverage),
                source_ids=[issue.issue_ref],
                metadata={
                    "issue_number": issue.issue_number,
                    "title": issue.title,
                    "regression_coverage": regression_coverage,
                    "reusable_pattern": reusable_pattern,
                },
            )
            learning_refs.append({"type": "dataset_candidate", "id": dataset_candidate.dataset_candidate_id})

        return learning_refs
