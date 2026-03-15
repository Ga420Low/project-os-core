from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class HandoffContract:
    version: str
    task_id: str | None
    source_model: str
    target_model: str | None
    raw_user_intent: str
    decisions_taken: list[str] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)
    context_snapshot: str = ""
    style_overrides: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
