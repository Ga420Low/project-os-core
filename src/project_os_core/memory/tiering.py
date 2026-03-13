from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import TierManagerConfig
from ..database import CanonicalDatabase
from ..models import MemoryTier, new_id
from ..paths import PathPolicy, ProjectPaths
from ..runtime.journal import LocalJournal
from .store import MemoryStore


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TierManagerService:
    """Manages warm-to-cold archival so E: becomes a real long-term store."""

    def __init__(
        self,
        *,
        config: TierManagerConfig,
        database: CanonicalDatabase,
        memory: MemoryStore,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        journal: LocalJournal,
    ) -> None:
        self.config = config
        self.database = database
        self.memory = memory
        self.paths = paths
        self.path_policy = path_policy
        self.journal = journal
        self._run_in_progress = False

    def report_path(self) -> Path:
        return self.paths.learning_root / "tier_manager" / "latest_report.json"

    def analyze(self, *, now: datetime | None = None, trigger: str = "analyze") -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        tier_counts = {
            str(row["tier"]): int(row["count"])
            for row in self.database.fetchall(
                "SELECT tier, COUNT(*) AS count FROM memory_records GROUP BY tier ORDER BY tier"
            )
        }
        warm_rows = self.database.fetchall(
            """
            SELECT memory_id, created_at, archived_artifact_path
            FROM memory_records
            WHERE tier = ?
            ORDER BY created_at DESC, memory_id DESC
            """,
            (MemoryTier.WARM.value,),
        )
        protected_count = max(0, int(self.config.keep_latest_warm_records))
        age_threshold = now - timedelta(hours=max(0, int(self.config.warm_min_age_hours)))
        candidates: list[dict[str, Any]] = []
        for index, row in enumerate(warm_rows):
            if index < protected_count:
                continue
            created_at = _parse_timestamp(str(row["created_at"]))
            if created_at > age_threshold:
                continue
            age_hours = round((now - created_at).total_seconds() / 3600, 2)
            candidates.append(
                {
                    "memory_id": str(row["memory_id"]),
                    "created_at": str(row["created_at"]),
                    "age_hours": age_hours,
                    "current_artifact_path": str(row["archived_artifact_path"] or ""),
                    "archive_target_root": str(self.paths.archive_episodes_root),
                }
            )

        artifact_counts = {
            str(row["storage_tier"]): int(row["count"])
            for row in self.database.fetchall(
                "SELECT storage_tier, COUNT(*) AS count FROM artifact_pointers GROUP BY storage_tier ORDER BY storage_tier"
            )
        }
        report = {
            "report_id": new_id("tier_report"),
            "created_at": now.isoformat(),
            "trigger": trigger,
            "config": {
                "enabled": self.config.enabled,
                "auto_archive_on_write": self.config.auto_archive_on_write,
                "warm_min_age_hours": self.config.warm_min_age_hours,
                "keep_latest_warm_records": self.config.keep_latest_warm_records,
                "max_archive_batch_size": self.config.max_archive_batch_size,
            },
            "counts": {
                "memory_by_tier": tier_counts,
                "artifact_by_tier": artifact_counts,
            },
            "warm_summary": {
                "warm_total": len(warm_rows),
                "protected_latest_count": protected_count,
                "candidate_count": len(candidates),
            },
            "candidates": candidates[: self.config.max_archive_batch_size],
            "report_path": str(self.report_path()),
        }
        self._write_report(report)
        return report

    def maybe_auto_archive(self, *, trigger: str) -> dict[str, Any]:
        if not self.config.enabled or not self.config.auto_archive_on_write:
            report = self.analyze(trigger=f"{trigger}:disabled")
            report["status"] = "disabled"
            self._write_report(report)
            return report
        return self.compact(trigger=trigger)

    def compact(
        self,
        *,
        dry_run: bool = False,
        trigger: str = "manual",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if self._run_in_progress:
            report = self.analyze(now=now, trigger=f"{trigger}:reentrant")
            report["status"] = "skipped"
            report["reason"] = "tier_manager_run_in_progress"
            self._write_report(report)
            return report

        self._run_in_progress = True
        try:
            report = self.analyze(now=now, trigger=trigger)
            report["status"] = "dry_run" if dry_run else "completed"
            report["dry_run"] = dry_run
            archived: list[dict[str, Any]] = []
            if not dry_run:
                for candidate in report["candidates"]:
                    record = self.memory.move_to_cold(str(candidate["memory_id"]))
                    archived.append(
                        {
                            "memory_id": record.memory_id,
                            "archived_artifact_path": record.archived_artifact_path,
                            "tier": record.tier.value,
                        }
                    )
                self.journal.append(
                    "tier_manager_compacted",
                    "memory",
                    {
                        "trigger": trigger,
                        "archived_count": len(archived),
                        "candidate_count": report["warm_summary"]["candidate_count"],
                    },
                )
            report["archived_count"] = len(archived)
            report["archived_records"] = archived
            self._write_report(report)
            return report
        finally:
            self._run_in_progress = False

    def _write_report(self, payload: dict[str, Any]) -> None:
        target = self.path_policy.ensure_allowed_write(self.report_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
