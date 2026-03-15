from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any


_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_MOJIBAKE_PATTERN = re.compile(r"Ã|Â|�")


@dataclass(slots=True)
class KnownDriftRule:
    name: str
    pattern: re.Pattern[str]
    message: str


@dataclass(slots=True)
class DocAuditFinding:
    check: str
    path: str
    message: str
    line: int | None = None
    excerpt: str | None = None


_KNOWN_DRIFT_RULES: tuple[KnownDriftRule, ...] = (
    KnownDriftRule(
        name="legacy_discord_channels",
        pattern=re.compile(r"#general|#decisions|#ops-log"),
        message="Legacy Discord channels should not appear in active docs.",
    ),
    KnownDriftRule(
        name="stale_reviewer_translator_state",
        pattern=re.compile(r"a implementer via `_call_reviewer\(\)`|a implementer via `_call_translator\(\)`"),
        message="Reviewer/translator are implemented and should not be described as pending in active docs.",
    ),
    KnownDriftRule(
        name="stale_infisical_mode",
        pattern=re.compile(r"\binfisical_first\b"),
        message="Active docs should describe the current Infisical machine-first required mode.",
    ),
    KnownDriftRule(
        name="stale_openclaw_bootstrap_state",
        pattern=re.compile(r"ouvrir le chantier du lot 4|prochain chantier doit etre le branchement live `OpenClaw`"),
        message="Active docs should not describe OpenClaw live bootstrap as the next unfinished lot.",
    ),
    KnownDriftRule(
        name="obsolete_test_count",
        pattern=re.compile(r"\b27 tests?\b"),
        message="Docs should not pin obsolete absolute test counts.",
    ),
)


def _is_historical(relative_path: Path) -> bool:
    parts = {part.lower() for part in relative_path.parts}
    return "audits" in parts or "archive" in parts


def _iter_doc_paths(repo_root: Path, include_historical: bool) -> list[Path]:
    docs_root = repo_root / "docs"
    files = sorted(docs_root.rglob("*.md"))
    files.extend(
        path
        for path in (
            repo_root / "PROJECT_OS_MASTER_MACHINE.md",
            repo_root / "AGENTS.md",
        )
        if path.exists()
    )
    if include_historical:
        return files
    result: list[Path] = []
    for path in files:
        relative = path.relative_to(repo_root)
        if _is_historical(relative):
            continue
        result.append(path)
    return result


def _is_external_link(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target)) or target.startswith("mailto:")


def _resolve_link(base_file: Path, target: str) -> Path:
    clean = target.split("#", 1)[0].strip()
    if Path(clean).is_absolute():
        return Path(clean)
    return (base_file.parent / clean).resolve(strict=False)


def _check_missing_links(path: Path) -> list[DocAuditFinding]:
    findings: list[DocAuditFinding] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for match in _LINK_PATTERN.finditer(line):
            target = match.group(1).strip()
            if not target or target.startswith("#") or _is_external_link(target):
                continue
            resolved = _resolve_link(path, target)
            if not resolved.exists():
                findings.append(
                    DocAuditFinding(
                        check="missing_local_link",
                        path=str(path),
                        line=line_no,
                        message="Local markdown link target does not exist.",
                        excerpt=target,
                    )
                )
    return findings


def _check_mojibake(path: Path) -> list[DocAuditFinding]:
    findings: list[DocAuditFinding] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _MOJIBAKE_PATTERN.search(line):
            findings.append(
                DocAuditFinding(
                    check="mojibake",
                    path=str(path),
                    line=line_no,
                    message="Potential encoding corruption detected.",
                    excerpt=line.strip(),
                )
            )
    return findings


def _check_known_drifts(path: Path) -> list[DocAuditFinding]:
    findings: list[DocAuditFinding] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for rule in _KNOWN_DRIFT_RULES:
            if rule.pattern.search(line):
                findings.append(
                    DocAuditFinding(
                        check=rule.name,
                        path=str(path),
                        line=line_no,
                        message=rule.message,
                        excerpt=line.strip(),
                    )
                )
    return findings


def audit_docs(repo_root: Path, include_historical: bool = False) -> dict[str, Any]:
    files = _iter_doc_paths(repo_root, include_historical=include_historical)
    findings: list[DocAuditFinding] = []
    for path in files:
        findings.extend(_check_missing_links(path))
        findings.extend(_check_mojibake(path))
        findings.extend(_check_known_drifts(path))
    checks = [
        {
            "name": "scope",
            "status": "ok",
            "message": "Documentation scope resolved.",
            "details": {
                "include_historical": include_historical,
                "files_scanned": len(files),
            },
        },
        {
            "name": "local_links",
            "status": "ok" if not any(item.check == "missing_local_link" for item in findings) else "a_corriger",
            "message": "Local markdown links are valid." if not any(item.check == "missing_local_link" for item in findings) else "Some local markdown links are broken.",
            "details": {
                "count": sum(1 for item in findings if item.check == "missing_local_link"),
            },
        },
        {
            "name": "encoding",
            "status": "ok" if not any(item.check == "mojibake" for item in findings) else "a_corriger",
            "message": "No mojibake detected." if not any(item.check == "mojibake" for item in findings) else "Potential mojibake detected.",
            "details": {
                "count": sum(1 for item in findings if item.check == "mojibake"),
            },
        },
        {
            "name": "known_drift_patterns",
            "status": "ok" if not any(item.check not in {"missing_local_link", "mojibake"} for item in findings) else "a_corriger",
            "message": "No known active-doc drift patterns detected." if not any(item.check not in {"missing_local_link", "mojibake"} for item in findings) else "Known active-doc drift patterns detected.",
            "details": {
                "count": sum(1 for item in findings if item.check not in {"missing_local_link", "mojibake"}),
            },
        },
    ]
    verdict = "OK" if not findings else "a_corriger"
    return {
        "verdict": verdict,
        "summary": "Active documentation is coherent." if verdict == "OK" else "Documentation drift detected.",
        "checks": checks,
        "findings": [asdict(item) for item in findings],
        "metadata": {
            "repo_root": str(repo_root),
            "include_historical": include_historical,
            "files_scanned": len(files),
        },
    }
