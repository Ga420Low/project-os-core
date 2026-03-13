from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import CanonicalDatabase, dump_json
from .models import HealthSnapshot, new_id, to_jsonable, utc_now_iso
from .paths import PathPolicy, ProjectPaths


class StructuredLogger:
    def __init__(self, paths: ProjectPaths, path_policy: PathPolicy):
        self.paths = paths
        self.path_policy = path_policy
        self.log_path = path_policy.ensure_allowed_write(paths.structured_log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, event_type: str, **fields: Any) -> dict[str, Any]:
        payload = {
            "timestamp": utc_now_iso(),
            "level": level,
            "event_type": event_type,
            **fields,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
            handle.flush()
        return payload


def write_health_snapshot(
    *,
    database: CanonicalDatabase,
    paths: ProjectPaths,
    path_policy: PathPolicy,
    overall_status: str,
    payload: dict[str, Any],
) -> HealthSnapshot:
    snapshot = HealthSnapshot(
        snapshot_id=new_id("health"),
        overall_status=overall_status,
        payload=payload,
        path=str(path_policy.ensure_allowed_write(paths.health_snapshot_path)),
    )
    snapshot_path = Path(snapshot.path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(to_jsonable(snapshot), ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    database.execute(
        """
        INSERT INTO health_snapshots(snapshot_id, overall_status, payload_json, path, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            snapshot.snapshot_id,
            snapshot.overall_status,
            dump_json(snapshot.payload),
            snapshot.path,
            snapshot.created_at,
        ),
    )
    return snapshot
