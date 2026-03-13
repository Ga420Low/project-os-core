from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..database import CanonicalDatabase, dump_json
from ..models import new_id, utc_now_iso


class LocalJournal:
    def __init__(self, database: CanonicalDatabase, file_path: Path):
        self.database = database
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, source: str, payload: dict[str, Any]) -> str:
        event_id = new_id("event")
        entry = {
            "event_id": event_id,
            "event_type": event_type,
            "source": source,
            "payload": payload,
            "created_at": utc_now_iso(),
        }
        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.database.execute(
            """
            INSERT INTO journal_events(event_id, event_type, source, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                entry["event_id"],
                entry["event_type"],
                entry["source"],
                dump_json(entry["payload"]),
                entry["created_at"],
            ),
        )
        return event_id
