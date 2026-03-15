from __future__ import annotations

from pathlib import Path

from project_os_core.docs_audit import audit_docs


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_docs_audit_ignores_historical_docs_by_default(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\n")
    _write(tmp_path / "PROJECT_OS_MASTER_MACHINE.md", "# Master\n")
    _write(tmp_path / "docs" / "guide.md", "# Guide\nSee [ok](./other.md)\n")
    _write(tmp_path / "docs" / "other.md", "# Other\n")
    _write(tmp_path / "docs" / "audits" / "historical.md", "Mode `infisical_first`\n")

    report = audit_docs(tmp_path)

    assert report["verdict"] == "OK"
    assert report["findings"] == []


def test_docs_audit_reports_broken_links_and_known_drift_patterns(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\n")
    _write(tmp_path / "PROJECT_OS_MASTER_MACHINE.md", "# Master\n")
    _write(
        tmp_path / "docs" / "guide.md",
        "# Guide\n"
        "See [missing](./missing.md)\n"
        "Legacy #general channel\n"
        "Mode `infisical_first`\n",
    )

    report = audit_docs(tmp_path)

    assert report["verdict"] == "a_corriger"
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["local_links"]["status"] == "a_corriger"
    assert checks["known_drift_patterns"]["status"] == "a_corriger"
    finding_checks = {item["check"] for item in report["findings"]}
    assert "missing_local_link" in finding_checks
    assert "legacy_discord_channels" in finding_checks
    assert "stale_infisical_mode" in finding_checks
