from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .debug_discord_audit import build_discord_debug_audit_report
from .debug_health import build_debug_system_report
from .debug_resilience import build_resilience_report
from .docs_audit import audit_docs

_CHECKLIST_ITEM_PATTERN = re.compile(r"^(\s*)- \[(x| )\] (.+)$")
_FORGOTTEN_PATTERN = re.compile(
    r"rappel|relancer|preuve operateur manuelle|execution live finale|checks manuels",
    re.IGNORECASE,
)
_UNVERIFIED_PATTERN = re.compile(
    r"preuve|audit|validate|doctor|manual|live|verification|verifie|check",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ChecklistNode:
    text: str
    checked: bool
    indent: int
    section: str
    line_no: int
    children: list["ChecklistNode"] = field(default_factory=list)
    parent: "ChecklistNode | None" = None

    @property
    def level(self) -> int:
        return max(0, self.indent // 2)


def build_project_review_report(
    services,
    *,
    checklist_path: str | None = None,
    include_historical_docs: bool = False,
    limit: int = 12,
) -> dict[str, Any]:
    repo_root = Path(services.config.repo_root)
    checklist_target = (
        Path(checklist_path).resolve(strict=False)
        if checklist_path
        else repo_root / "docs" / "roadmap" / "BUILD_STATUS_CHECKLIST.md"
    )
    checklist = _summarize_checklist(checklist_target, limit=limit)
    docs_report = audit_docs(repo_root, include_historical=include_historical_docs)
    debug_report = build_debug_system_report(services, limit=limit)
    resilience_report = build_resilience_report(services, limit=limit)
    discord_audit = build_discord_debug_audit_report(services, limit=limit)
    scheduler = _build_scheduler_summary(services, limit=limit)
    founder_review = _build_founder_review_items(
        checklist=checklist,
        docs_report=docs_report,
        debug_report=debug_report,
        resilience_report=resilience_report,
        discord_audit=discord_audit,
        scheduler=scheduler,
        limit=limit,
    )
    status = _determine_project_review_status(
        docs_report=docs_report,
        debug_report=debug_report,
        resilience_report=resilience_report,
        discord_audit=discord_audit,
        checklist=checklist,
        founder_review=founder_review,
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": {
            "done_count": checklist["summary"]["done_count"],
            "partial_count": checklist["summary"]["partial_count"],
            "forgotten_count": checklist["summary"]["forgotten_count"],
            "non_verified_count": checklist["summary"]["non_verified_count"],
            "founder_review_count": len(founder_review),
        },
        "sources": {
            "checklist": {
                "path": str(checklist_target),
                "status": checklist["status"],
                "total_items": checklist["summary"]["total_items"],
            },
            "docs_audit": {
                "status": str(docs_report.get("verdict") or "").lower(),
                "findings_count": len(list(docs_report.get("findings") or [])),
            },
            "debug_system": {
                "status": str(debug_report.get("status") or "").lower(),
            },
            "debug_resilience": {
                "status": str(resilience_report.get("status") or "").lower(),
            },
            "discord_audit": {
                "status": str(discord_audit.get("status") or "").lower(),
                "decision": str(discord_audit.get("decision") or ""),
            },
            "scheduler": {
                "status": scheduler["status"],
                "enabled_count": scheduler["enabled_count"],
                "overdue_count": scheduler["overdue_count"],
            },
        },
        "done": checklist["done"],
        "partial": checklist["partial"],
        "forgotten": checklist["forgotten"],
        "non_verified": checklist["non_verified"],
        "founder_review": founder_review,
        "checklist": checklist,
        "docs_audit": docs_report,
        "debug_system": debug_report,
        "debug_resilience": resilience_report,
        "discord_audit": discord_audit,
        "scheduler": scheduler,
    }
    artifact_paths = _write_project_review_artifacts(services, report=report)
    report["artifact_json_path"] = artifact_paths["json"]
    report["artifact_markdown_path"] = artifact_paths["markdown"]
    services.journal.append(
        "project_review_report_generated",
        "project_review",
        {
            "status": status,
            "artifact_json_path": artifact_paths["json"],
            "artifact_markdown_path": artifact_paths["markdown"],
        },
    )
    return report


def render_project_review_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    sources = report.get("sources") if isinstance(report.get("sources"), dict) else {}
    lines = [
        "# Project Review Loop",
        "",
        f"- Generated: {report.get('generated_at')}",
        f"- Status: `{report.get('status')}`",
        f"- JSON: `{report.get('artifact_json_path') or '<pending>'}`",
        "",
        "## Snapshot",
        "",
        f"- Done: {summary.get('done_count', 0)}",
        f"- Partiel: {summary.get('partial_count', 0)}",
        f"- Oublie: {summary.get('forgotten_count', 0)}",
        f"- Non verifie: {summary.get('non_verified_count', 0)}",
        f"- A revoir avec le fondateur: {summary.get('founder_review_count', 0)}",
        "",
        "## Sources automatiques",
        "",
        f"- Checklist: `{sources.get('checklist', {}).get('status', 'unknown')}`",
        f"- Docs audit: `{sources.get('docs_audit', {}).get('status', 'unknown')}`",
        f"- Debug system: `{sources.get('debug_system', {}).get('status', 'unknown')}`",
        f"- Debug resilience: `{sources.get('debug_resilience', {}).get('status', 'unknown')}`",
        f"- Discord audit: `{sources.get('discord_audit', {}).get('status', 'unknown')}`",
        f"- Scheduler: `{sources.get('scheduler', {}).get('status', 'unknown')}`",
        "",
    ]
    _append_review_section(lines, "Done", report.get("done"))
    _append_review_section(lines, "Partiel", report.get("partial"))
    _append_review_section(lines, "Oublie", report.get("forgotten"))
    _append_review_section(lines, "Non verifie", report.get("non_verified"))
    _append_review_section(lines, "A revoir avec le fondateur", report.get("founder_review"))
    return "\n".join(lines).strip() + "\n"


def _append_review_section(lines: list[str], title: str, items: Any) -> None:
    lines.append(f"## {title}")
    lines.append("")
    normalized_items = list(items or [])
    if not normalized_items:
        lines.append("- none")
        lines.append("")
        return
    for item in normalized_items:
        if isinstance(item, dict):
            label = str(item.get("path") or item.get("text") or item.get("message") or item.get("title") or "").strip()
            detail = str(item.get("message") or item.get("notes") or item.get("status") or "").strip()
            lines.append(f"- {label}")
            if detail:
                lines.append(f"  - {detail}")
        else:
            lines.append(f"- {str(item)}")
    lines.append("")


def _summarize_checklist(path: Path, *, limit: int) -> dict[str, Any]:
    roots = _parse_checklist(path)
    nodes = _flatten_nodes(roots)
    done = [_serialize_item(node) for node in nodes if node.level == 0 and _node_state(node) == "done"][:limit]
    partial = [_serialize_item(node) for node in nodes if node.level == 0 and _node_state(node) == "partial"][:limit]
    forgotten = [_serialize_item(node) for node in nodes if _node_state(node) != "done" and _FORGOTTEN_PATTERN.search(node.text)][:limit]
    non_verified = [
        _serialize_item(node)
        for node in nodes
        if _node_state(node) != "done" and _UNVERIFIED_PATTERN.search(node.text) and not _FORGOTTEN_PATTERN.search(node.text)
    ][:limit]
    done_count = sum(1 for node in nodes if node.level == 0 and _node_state(node) == "done")
    partial_count = sum(1 for node in nodes if node.level == 0 and _node_state(node) == "partial")
    forgotten_count = sum(1 for node in nodes if _node_state(node) != "done" and _FORGOTTEN_PATTERN.search(node.text))
    non_verified_count = sum(
        1
        for node in nodes
        if _node_state(node) != "done" and _UNVERIFIED_PATTERN.search(node.text) and not _FORGOTTEN_PATTERN.search(node.text)
    )
    status = "attention" if partial_count > 0 or forgotten_count > 0 or non_verified_count > 0 else "ok"
    return {
        "status": status,
        "summary": {
            "total_items": len(nodes),
            "done_count": done_count,
            "partial_count": partial_count,
            "forgotten_count": forgotten_count,
            "non_verified_count": non_verified_count,
        },
        "done": done,
        "partial": partial,
        "forgotten": forgotten,
        "non_verified": non_verified,
    }


def _parse_checklist(path: Path) -> list[ChecklistNode]:
    if not path.exists():
        return []
    roots: list[ChecklistNode] = []
    stack: list[ChecklistNode] = []
    current_section = "Checklist"
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            current_section = stripped.lstrip("#").strip() or current_section
        match = _CHECKLIST_ITEM_PATTERN.match(raw_line)
        if not match:
            continue
        indent = len(match.group(1))
        checked = match.group(2) == "x"
        text = match.group(3).strip()
        node = ChecklistNode(
            text=text,
            checked=checked,
            indent=indent,
            section=current_section,
            line_no=line_no,
        )
        while stack and stack[-1].indent >= indent:
            stack.pop()
        if stack:
            node.parent = stack[-1]
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def _flatten_nodes(nodes: list[ChecklistNode]) -> list[ChecklistNode]:
    flattened: list[ChecklistNode] = []
    for node in nodes:
        flattened.append(node)
        flattened.extend(_flatten_nodes(node.children))
    return flattened


def _node_state(node: ChecklistNode) -> str:
    if not node.children:
        return "done" if node.checked else "open"
    child_states = [_node_state(child) for child in node.children]
    if node.checked and all(state == "done" for state in child_states):
        return "done"
    if not node.checked and all(state == "open" for state in child_states):
        return "open"
    return "partial"


def _serialize_item(node: ChecklistNode) -> dict[str, Any]:
    return {
        "text": node.text,
        "path": " > ".join(reversed(_node_ancestors(node))),
        "section": node.section,
        "line": node.line_no,
        "status": _node_state(node),
    }


def _node_ancestors(node: ChecklistNode) -> list[str]:
    items = [node.text]
    current = node.parent
    while current is not None:
        items.append(current.text)
        current = current.parent
    return items


def _build_scheduler_summary(services, *, limit: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    tasks = services.scheduler.list_tasks()
    overdue: list[dict[str, Any]] = []
    disabled: list[dict[str, Any]] = []
    for task in tasks:
        if task.enabled and task.next_run_at:
            try:
                next_run = datetime.fromisoformat(task.next_run_at)
            except ValueError:
                next_run = None
            if next_run is not None and next_run <= now:
                overdue.append(
                    {
                        "name": task.name,
                        "next_run_at": task.next_run_at,
                        "last_status": task.last_status,
                    }
                )
        if not task.enabled:
            disabled.append(
                {
                    "name": task.name,
                    "last_status": task.last_status,
                }
            )
    status = "breach" if overdue else ("attention" if disabled else "ok")
    return {
        "status": status,
        "enabled_count": sum(1 for task in tasks if task.enabled),
        "disabled_count": sum(1 for task in tasks if not task.enabled),
        "overdue_count": len(overdue),
        "overdue_tasks": overdue[:limit],
        "disabled_tasks": disabled[:limit],
    }


def _build_founder_review_items(
    *,
    checklist: dict[str, Any],
    docs_report: dict[str, Any],
    debug_report: dict[str, Any],
    resilience_report: dict[str, Any],
    discord_audit: dict[str, Any],
    scheduler: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    discord_status = str(discord_audit.get("status") or "").lower()
    if discord_status != "coherent":
        items.append(
            {
                "title": "Discord audit final",
                "message": str(discord_audit.get("next_step") or "Relire le dernier audit Discord."),
            }
        )
    if str(docs_report.get("verdict") or "").lower() != "ok":
        items.append(
            {
                "title": "Documentation drift",
                "message": "Le docs audit detecte des derives. Relire les findings avant de conclure un lot.",
            }
        )
    if str(debug_report.get("status") or "").lower() == "breach":
        items.append(
            {
                "title": "Debug system en breach",
                "message": "Le socle debug local n'est pas vert. Relire observability doctor avant de continuer.",
            }
        )
    if str(resilience_report.get("status") or "").lower() == "breach":
        items.append(
            {
                "title": "Resilience en breach",
                "message": "Le systeme demande une reparation ou une re-verification avant de poursuivre.",
            }
        )
    if int(scheduler.get("overdue_count") or 0) > 0:
        items.append(
            {
                "title": "Scheduler en retard",
                "message": "Certaines taches planifiees sont overdue. Verifier le tick scheduler et les locks runtime.",
            }
        )
    for item in list(checklist.get("forgotten") or [])[:limit]:
        items.append(
            {
                "title": str(item.get("path") or item.get("text") or "Checklist reminder"),
                "message": "Point en attente detecte dans la checklist. Ne pas le laisser sortir du radar.",
            }
        )
    return items[:limit]


def _determine_project_review_status(
    *,
    docs_report: dict[str, Any],
    debug_report: dict[str, Any],
    resilience_report: dict[str, Any],
    discord_audit: dict[str, Any],
    checklist: dict[str, Any],
    founder_review: list[dict[str, Any]],
) -> str:
    docs_status = str(docs_report.get("verdict") or "").lower()
    debug_status = str(debug_report.get("status") or "").lower()
    resilience_status = str(resilience_report.get("status") or "").lower()
    discord_status = str(discord_audit.get("status") or "").lower()
    if debug_status == "breach" or resilience_status == "breach" or discord_status == "non_coherent":
        return "breach"
    if (
        docs_status != "ok"
        or checklist["status"] != "ok"
        or discord_status != "coherent"
        or founder_review
        or debug_status == "attention"
        or resilience_status == "attention"
    ):
        return "attention"
    return "ok"


def _write_project_review_artifacts(services, *, report: dict[str, Any]) -> dict[str, str]:
    reports_root = services.path_policy.ensure_allowed_write(
        services.paths.runtime_root / "reports" / "project_review"
    )
    reports_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_target = services.path_policy.ensure_allowed_write(reports_root / f"{timestamp}.json")
    json_latest = services.path_policy.ensure_allowed_write(reports_root / "latest.json")
    markdown_target = services.path_policy.ensure_allowed_write(reports_root / f"{timestamp}.md")
    markdown_latest = services.path_policy.ensure_allowed_write(reports_root / "latest.md")

    report["artifact_json_path"] = str(json_target)
    report["artifact_markdown_path"] = str(markdown_target)
    rendered_json = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    rendered_markdown = render_project_review_markdown(report)
    json_target.write_text(rendered_json, encoding="utf-8")
    json_latest.write_text(rendered_json, encoding="utf-8")
    markdown_target.write_text(rendered_markdown, encoding="utf-8")
    markdown_latest.write_text(rendered_markdown, encoding="utf-8")
    return {
        "json": str(json_target),
        "markdown": str(markdown_target),
    }
