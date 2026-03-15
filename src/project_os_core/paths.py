from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import RuntimeConfig


@dataclass(slots=True)
class ProjectPaths:
    repo_root: Path
    runtime_root: Path
    openclaw_runtime_root: Path
    openclaw_state_root: Path
    memory_hot_root: Path
    memory_warm_root: Path
    index_root: Path
    session_root: Path
    cache_root: Path
    archive_do_not_touch_root: Path
    archive_root: Path
    archive_episodes_root: Path
    archive_evidence_root: Path
    archive_screens_root: Path
    archive_reports_root: Path
    archive_logs_root: Path
    archive_snapshots_root: Path
    canonical_db_path: Path
    journal_file_path: Path
    openmemory_db_path: Path
    runtime_artifact_root: Path
    memory_artifact_root: Path
    bootstrap_state_path: Path
    health_snapshot_path: Path
    structured_log_path: Path
    api_runs_root: Path
    learning_root: Path
    learning_decision_records_root: Path
    learning_deferred_log_path: Path
    memory_os_root: Path
    memory_blocks_root: Path
    memory_graph_root: Path
    api_runs_terminal_snapshot_path: Path
    openclaw_reports_root: Path
    openclaw_replay_root: Path
    openclaw_live_root: Path
    openclaw_bootstrap_report_path: Path
    openclaw_doctor_report_path: Path
    openclaw_replay_report_path: Path
    openclaw_live_validation_report_path: Path
    openclaw_truth_health_report_path: Path
    openclaw_trust_audit_report_path: Path
    openclaw_self_heal_report_path: Path


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def build_project_paths(config: RuntimeConfig) -> ProjectPaths:
    roots = config.storage_roots
    runtime_root = _path(roots.runtime_root)
    memory_hot_root = _path(roots.memory_hot_root)
    memory_warm_root = _path(roots.memory_warm_root)
    openclaw_runtime_root = _path(config.openclaw_config.runtime_root)
    openclaw_state_root = _path(config.openclaw_config.state_root)
    return ProjectPaths(
        repo_root=config.repo_root,
        runtime_root=runtime_root,
        openclaw_runtime_root=openclaw_runtime_root,
        openclaw_state_root=openclaw_state_root,
        memory_hot_root=memory_hot_root,
        memory_warm_root=memory_warm_root,
        index_root=_path(roots.index_root),
        session_root=_path(roots.session_root),
        cache_root=_path(roots.cache_root),
        archive_do_not_touch_root=_path(roots.archive_do_not_touch_root),
        archive_root=_path(roots.archive_root),
        archive_episodes_root=_path(roots.archive_episodes_root),
        archive_evidence_root=_path(roots.archive_evidence_root),
        archive_screens_root=_path(roots.archive_screens_root),
        archive_reports_root=_path(roots.archive_reports_root),
        archive_logs_root=_path(roots.archive_logs_root),
        archive_snapshots_root=_path(roots.archive_snapshots_root),
        canonical_db_path=runtime_root / "project_os_core.db",
        journal_file_path=runtime_root / "journal" / "events.jsonl",
        openmemory_db_path=memory_hot_root / "openmemory" / "openmemory.db",
        runtime_artifact_root=runtime_root / "artifacts",
        memory_artifact_root=memory_warm_root / "artifacts",
        bootstrap_state_path=runtime_root / "bootstrap" / "latest_bootstrap_state.json",
        health_snapshot_path=runtime_root / "health" / "latest_health.json",
        structured_log_path=runtime_root / "logs" / "structured.jsonl",
        api_runs_root=runtime_root / "api_runs",
        learning_root=runtime_root / "learning",
        learning_decision_records_root=runtime_root / "learning" / "decision_records",
        learning_deferred_log_path=runtime_root / "learning" / "deferred_decisions.jsonl",
        memory_os_root=runtime_root / "memory_os",
        memory_blocks_root=runtime_root / "memory_os" / "blocks",
        memory_graph_root=runtime_root / "memory_os" / "graph",
        api_runs_terminal_snapshot_path=runtime_root / "api_runs" / "latest_terminal_snapshot.json",
        openclaw_reports_root=runtime_root / "openclaw" / "reports",
        openclaw_replay_root=runtime_root / "openclaw" / "replay",
        openclaw_live_root=runtime_root / "openclaw" / "live",
        openclaw_bootstrap_report_path=runtime_root / "openclaw" / "reports" / "latest_bootstrap.json",
        openclaw_doctor_report_path=runtime_root / "openclaw" / "reports" / "latest_doctor.json",
        openclaw_replay_report_path=runtime_root / "openclaw" / "replay" / "latest_replay.json",
        openclaw_live_validation_report_path=runtime_root / "openclaw" / "live" / "latest_live_validation.json",
        openclaw_truth_health_report_path=runtime_root / "openclaw" / "live" / "latest_truth_health.json",
        openclaw_trust_audit_report_path=runtime_root / "openclaw" / "live" / "latest_trust_audit.json",
        openclaw_self_heal_report_path=runtime_root / "openclaw" / "live" / "latest_self_heal.json",
    )


class PathPolicy:
    def __init__(self, paths: ProjectPaths):
        self.paths = paths
        self._forbidden_roots = [paths.archive_do_not_touch_root]
        self._managed_roots = [
            paths.runtime_root,
            paths.openclaw_runtime_root,
            paths.memory_hot_root,
            paths.memory_warm_root,
            paths.index_root,
            paths.session_root,
            paths.cache_root,
            paths.archive_root,
        ]

    def is_forbidden(self, candidate: str | Path) -> bool:
        path = _path(str(candidate))
        for root in self._forbidden_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def is_managed(self, candidate: str | Path) -> bool:
        path = _path(str(candidate))
        for root in self._managed_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def ensure_allowed_write(self, candidate: str | Path) -> Path:
        path = _path(str(candidate))
        if self.is_forbidden(path):
            raise PermissionError(f"Refusing to write inside forbidden zone: {path}")
        if not self.is_managed(path):
            raise PermissionError(f"Refusing to write outside managed roots: {path}")
        return path


def ensure_project_roots(paths: ProjectPaths) -> dict[str, str]:
    managed = [
        paths.runtime_root,
        paths.openclaw_runtime_root,
        paths.openclaw_state_root,
        paths.memory_hot_root,
        paths.memory_warm_root,
        paths.index_root,
        paths.session_root,
        paths.cache_root,
        paths.archive_root,
        paths.archive_episodes_root,
        paths.archive_evidence_root,
        paths.archive_screens_root,
        paths.archive_reports_root,
        paths.archive_logs_root,
        paths.archive_snapshots_root,
        paths.runtime_artifact_root,
        paths.memory_artifact_root,
        paths.openmemory_db_path.parent,
        paths.journal_file_path.parent,
        paths.bootstrap_state_path.parent,
        paths.health_snapshot_path.parent,
        paths.structured_log_path.parent,
        paths.api_runs_root,
        paths.learning_root,
        paths.learning_decision_records_root,
        paths.memory_os_root,
        paths.memory_blocks_root,
        paths.memory_graph_root,
        paths.api_runs_terminal_snapshot_path.parent,
        paths.openclaw_reports_root,
        paths.openclaw_replay_root,
        paths.openclaw_live_root,
    ]
    for root in managed:
        root.mkdir(parents=True, exist_ok=True)
    return {str(root): "ready" for root in managed}
