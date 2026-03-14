from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


RESERVED_SECTION_HEADINGS: tuple[str, ...] = (
    "Description",
    "Impact",
    "Root Cause",
    "Resolution",
    "Regression Coverage",
    "Durable Lesson",
    "Reusable Pattern",
    "Eval Scenario",
)
OPTIONAL_SECTION_HEADINGS: tuple[str, ...] = ("Repeated Pattern",)
ALL_SECTION_HEADINGS: tuple[str, ...] = RESERVED_SECTION_HEADINGS + OPTIONAL_SECTION_HEADINGS
_SECTION_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
_PLACEHOLDER_VALUES = {"", "todo", "tbd", "pending", "placeholder", "fill me", "to fill"}
_NO_SIGNAL_VALUES = {"n/a", "na", "none", "not applicable"}


def normalize_issue_text(text: str | None) -> str:
    return str(text or "").replace("\r\n", "\n").strip()


def parse_issue_sections(body: str | None) -> dict[str, str]:
    normalized = normalize_issue_text(body)
    matches = list(_SECTION_RE.finditer(normalized))
    sections = {heading: "" for heading in ALL_SECTION_HEADINGS}
    if not matches:
        return sections
    for index, match in enumerate(matches):
        heading = match.group(2).strip()
        if heading not in sections:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        sections[heading] = normalized[start:end].strip()
    return sections


def section_is_filled(value: str | None) -> bool:
    lowered = normalize_issue_text(value).lower()
    return lowered not in _PLACEHOLDER_VALUES


def section_has_signal(value: str | None) -> bool:
    lowered = normalize_issue_text(value).lower()
    return lowered not in _PLACEHOLDER_VALUES and lowered not in _NO_SIGNAL_VALUES


def labels_to_severity(labels: list[str]) -> str:
    lowered = {item.lower() for item in labels}
    if "p1-critical" in lowered:
        return "critical"
    if "p2-important" in lowered:
        return "high"
    if "p3-minor" in lowered:
        return "medium"
    return "info"


def labels_to_modules(labels: list[str]) -> list[str]:
    modules = [item.split("module:", 1)[1] for item in labels if item.startswith("module:")]
    return sorted({module.strip() for module in modules if module.strip()})


def issue_matches_learning_labels(labels: list[str], label_filter: list[str]) -> bool:
    lowered = {item.lower() for item in labels}
    targets = {item.lower() for item in label_filter}
    return bool(lowered & targets)


def payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class ParsedGitHubIssue:
    repo: str
    issue_number: int
    issue_id: str
    title: str
    state: str
    labels: list[str]
    body: str
    url: str | None = None
    closed_at: str | None = None
    updated_at: str | None = None
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def issue_ref(self) -> str:
        return f"github:{self.repo}#{self.issue_number}"

    @property
    def scope_label(self) -> str:
        modules = labels_to_modules(self.labels)
        return ",".join(modules) if modules else "general"

    @property
    def content_sha256(self) -> str:
        return payload_sha256(
            {
                "repo": self.repo,
                "issue_number": self.issue_number,
                "title": self.title,
                "state": self.state,
                "labels": sorted(self.labels),
                "body": self.body,
                "closed_at": self.closed_at,
                "updated_at": self.updated_at,
            }
        )


def parse_issue_payload(payload: dict[str, Any], *, repo: str) -> ParsedGitHubIssue:
    labels = [str(item.get("name")) for item in payload.get("labels", []) if item.get("name")]
    body = normalize_issue_text(payload.get("body"))
    return ParsedGitHubIssue(
        repo=repo,
        issue_number=int(payload["number"]),
        issue_id=str(payload.get("node_id") or payload.get("id") or payload["number"]),
        title=str(payload.get("title") or "").strip(),
        state=str(payload.get("state") or "").strip(),
        labels=labels,
        body=body,
        url=str(payload.get("html_url")) if payload.get("html_url") else None,
        closed_at=str(payload.get("closed_at")) if payload.get("closed_at") else None,
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") else None,
        sections=parse_issue_sections(body),
    )
