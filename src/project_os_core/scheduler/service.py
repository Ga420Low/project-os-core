from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..config import GitHubConfig, MemoryConfig
from ..database import CanonicalDatabase, dump_json
from ..models import new_id, utc_now_iso
from ..observability import StructuredLogger
from ..runtime.journal import LocalJournal


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


BASE_DEFAULT_TASKS: tuple[dict[str, Any], ...] = (
    {
        "name": "memory_compact",
        "schedule_kind": "interval",
        "interval_seconds": 3600 * 6,
        "command": "memory_compact",
        "command_args": {"trigger": "scheduled"},
    },
    {
        "name": "health_check",
        "schedule_kind": "interval",
        "interval_seconds": 3600,
        "command": "health_check",
        "command_args": {},
    },
    {
        "name": "daily_audit",
        "schedule_kind": "daily_at",
        "daily_at_hour": 6,
        "daily_at_minute": 0,
        "command": "daily_audit",
        "command_args": {"mode": "audit", "objective": "Audit quotidien automatique du repo"},
        "enabled": False,
    },
    {
        "name": "project_review_loop",
        "schedule_kind": "interval",
        "interval_seconds": 3600 * 12,
        "command": "project_review_loop",
        "command_args": {"limit": 12},
    },
    {
        "name": "cleanup_expired_deliveries",
        "schedule_kind": "interval",
        "interval_seconds": 3600 * 12,
        "command": "cleanup_deliveries",
        "command_args": {"max_age_hours": 48},
    },
)


@dataclass(slots=True)
class ScheduledTask:
    task_id: str
    name: str
    schedule_kind: str
    interval_seconds: int | None
    daily_at_hour: int | None
    daily_at_minute: int | None
    command: str
    command_args: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


class SchedulerService:
    """Manage system scheduled tasks without embedding execution logic."""

    def __init__(
        self,
        *,
        database: CanonicalDatabase,
        journal: LocalJournal,
        logger: StructuredLogger,
        github_config: GitHubConfig | None = None,
        memory_config: MemoryConfig | None = None,
    ) -> None:
        self.database = database
        self.journal = journal
        self.logger = logger
        self.github_config = github_config
        self.memory_config = memory_config
        self._ensure_default_tasks()

    def _ensure_default_tasks(self) -> None:
        for task_def in self._default_tasks():
            existing = self.database.fetchone(
                "SELECT task_id FROM scheduled_tasks WHERE name = ?",
                (str(task_def["name"]),),
            )
            if existing is not None:
                continue
            task = ScheduledTask(
                task_id=new_id("sched_task"),
                name=str(task_def["name"]),
                schedule_kind=str(task_def["schedule_kind"]),
                interval_seconds=(
                    int(task_def["interval_seconds"]) if task_def.get("interval_seconds") is not None else None
                ),
                daily_at_hour=int(task_def["daily_at_hour"]) if task_def.get("daily_at_hour") is not None else None,
                daily_at_minute=(
                    int(task_def["daily_at_minute"]) if task_def.get("daily_at_minute") is not None else None
                ),
                command=str(task_def["command"]),
                command_args=dict(task_def.get("command_args", {})),
                enabled=bool(task_def.get("enabled", True)),
            )
            task.next_run_at = self._compute_next_run(task)
            self._persist_task(task)
            self.logger.log("INFO", "scheduled_task_created", task_id=task.task_id, name=task.name)
            self.journal.append(
                "scheduled_task_created",
                "scheduler",
                {"task_id": task.task_id, "name": task.name, "next_run_at": task.next_run_at},
            )

    def _default_tasks(self) -> list[dict[str, Any]]:
        tasks = [dict(item) for item in BASE_DEFAULT_TASKS]
        if self.memory_config is not None:
            tasks.extend(
                [
                    {
                        "name": "memory_curator_sleeptime",
                        "schedule_kind": "interval",
                        "interval_seconds": max(300, int(self.memory_config.curator.interval_seconds)),
                        "command": "memory_curator_sleeptime",
                        "command_args": {"trigger": "scheduled"},
                        "enabled": bool(self.memory_config.curator.enabled),
                    },
                    {
                        "name": "memory_block_refresh",
                        "schedule_kind": "interval",
                        "interval_seconds": max(300, int(self.memory_config.blocks.refresh_interval_seconds)),
                        "command": "memory_block_refresh",
                        "command_args": {},
                        "enabled": bool(self.memory_config.blocks.enabled),
                    },
                    {
                        "name": "memory_supersession_scan",
                        "schedule_kind": "interval",
                        "interval_seconds": max(600, int(self.memory_config.supersession.interval_seconds)),
                        "command": "memory_supersession_scan",
                        "command_args": {},
                        "enabled": bool(self.memory_config.supersession.enabled),
                    },
                ]
            )
        if self.github_config is not None:
            tasks.append(
                {
                    "name": "github_issue_learning_sync",
                    "schedule_kind": "interval",
                    "interval_seconds": max(1, int(self.github_config.sync_interval_hours)) * 3600,
                    "command": "github_issue_learning_sync",
                    "command_args": {},
                    "enabled": bool(self.github_config.sync_enabled),
                }
            )
        return tasks

    def _persist_task(self, task: ScheduledTask) -> None:
        self.database.execute(
            """
            INSERT INTO scheduled_tasks(
                task_id, name, schedule_kind, interval_seconds, daily_at_hour, daily_at_minute,
                command, command_args_json, enabled, last_run_at, next_run_at, last_status,
                last_error, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.name,
                task.schedule_kind,
                task.interval_seconds,
                task.daily_at_hour,
                task.daily_at_minute,
                task.command,
                dump_json(task.command_args),
                1 if task.enabled else 0,
                task.last_run_at,
                task.next_run_at,
                task.last_status,
                task.last_error,
                dump_json(task.metadata),
                task.created_at,
                task.updated_at,
            ),
        )

    def _row_to_task(self, row) -> ScheduledTask:
        return ScheduledTask(
            task_id=str(row["task_id"]),
            name=str(row["name"]),
            schedule_kind=str(row["schedule_kind"]),
            interval_seconds=int(row["interval_seconds"]) if row["interval_seconds"] is not None else None,
            daily_at_hour=int(row["daily_at_hour"]) if row["daily_at_hour"] is not None else None,
            daily_at_minute=int(row["daily_at_minute"]) if row["daily_at_minute"] is not None else None,
            command=str(row["command"]),
            command_args=json.loads(row["command_args_json"]) if row["command_args_json"] else {},
            enabled=bool(row["enabled"]),
            last_run_at=str(row["last_run_at"]) if row["last_run_at"] else None,
            next_run_at=str(row["next_run_at"]) if row["next_run_at"] else None,
            last_status=str(row["last_status"]) if row["last_status"] else None,
            last_error=str(row["last_error"]) if row["last_error"] else None,
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get_task(self, task_id: str) -> ScheduledTask:
        row = self.database.fetchone("SELECT * FROM scheduled_tasks WHERE task_id = ?", (task_id,))
        if row is None:
            raise KeyError(f"Unknown scheduled task: {task_id}")
        return self._row_to_task(row)

    def get_due_tasks(self) -> list[ScheduledTask]:
        now = _utc_now().isoformat()
        rows = self.database.fetchall(
            """
            SELECT * FROM scheduled_tasks
            WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at ASC
            """,
            (now,),
        )
        return [self._row_to_task(row) for row in rows]

    def mark_task_executed(self, task_id: str, *, status: str, error: str | None = None) -> None:
        task = self.get_task(task_id)
        now = _utc_now().isoformat()
        next_run = self._compute_next_run(task)
        self.database.execute(
            """
            UPDATE scheduled_tasks
            SET last_run_at = ?, last_status = ?, last_error = ?, next_run_at = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (now, status, error, next_run, now, task_id),
        )
        self.logger.log(
            "INFO" if status == "success" else "WARNING",
            "scheduled_task_executed",
            task_id=task_id,
            name=task.name,
            status=status,
            next_run_at=next_run,
            error=error,
        )
        self.journal.append(
            "scheduled_task_executed",
            "scheduler",
            {"task_id": task_id, "name": task.name, "status": status, "next_run_at": next_run, "error": error or ""},
        )

    def enable_task(self, name: str) -> ScheduledTask:
        return self._set_task_enabled(name, enabled=True)

    def disable_task(self, name: str) -> ScheduledTask:
        return self._set_task_enabled(name, enabled=False)

    def list_tasks(self) -> list[ScheduledTask]:
        rows = self.database.fetchall("SELECT * FROM scheduled_tasks ORDER BY name ASC")
        return [self._row_to_task(row) for row in rows]

    def _set_task_enabled(self, name: str, *, enabled: bool) -> ScheduledTask:
        row = self.database.fetchone("SELECT * FROM scheduled_tasks WHERE name = ?", (name,))
        if row is None:
            raise KeyError(f"Unknown scheduled task: {name}")
        task = self._row_to_task(row)
        now = _utc_now().isoformat()
        next_run_at = self._compute_next_run(task) if enabled else task.next_run_at
        self.database.execute(
            """
            UPDATE scheduled_tasks
            SET enabled = ?, next_run_at = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (1 if enabled else 0, next_run_at, now, task.task_id),
        )
        updated = self.get_task(task.task_id)
        self.logger.log(
            "INFO",
            "scheduled_task_toggled",
            task_id=updated.task_id,
            name=updated.name,
            enabled=updated.enabled,
            next_run_at=updated.next_run_at,
        )
        self.journal.append(
            "scheduled_task_toggled",
            "scheduler",
            {"task_id": updated.task_id, "name": updated.name, "enabled": updated.enabled},
        )
        return updated

    def _compute_next_run(self, task: ScheduledTask) -> str:
        now = _utc_now()
        if task.schedule_kind == "interval" and task.interval_seconds:
            return (now + timedelta(seconds=task.interval_seconds)).isoformat()
        if task.schedule_kind == "daily_at" and task.daily_at_hour is not None:
            target = now.replace(
                hour=task.daily_at_hour,
                minute=task.daily_at_minute or 0,
                second=0,
                microsecond=0,
            )
            if target <= now:
                target += timedelta(days=1)
            return target.isoformat()
        return (now + timedelta(hours=1)).isoformat()

    def tick(self, *, executor: Callable[[str, dict[str, Any]], dict[str, Any]]) -> list[dict[str, Any]]:
        due_tasks = self.get_due_tasks()
        results: list[dict[str, Any]] = []
        for task in due_tasks:
            self.logger.log("INFO", "scheduled_task_starting", task_id=task.task_id, name=task.name, command=task.command)
            try:
                result = executor(task.command, dict(task.command_args))
                self.mark_task_executed(task.task_id, status="success")
                results.append({"task_id": task.task_id, "name": task.name, "status": "success", "result": result})
            except Exception as exc:
                self.mark_task_executed(task.task_id, status="failed", error=str(exc))
                self.logger.log(
                    "WARNING",
                    "scheduled_task_failed",
                    task_id=task.task_id,
                    name=task.name,
                    error=str(exc),
                )
                results.append({"task_id": task.task_id, "name": task.name, "status": "failed", "error": str(exc)})
        return results
