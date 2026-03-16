from __future__ import annotations

from pathlib import Path

from project_os_core.research_scaffold import ResearchScaffoldRequest, detect_deep_research_request, scaffold_research


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scaffold_research_audit_creates_prefilled_doc(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\n")
    _write(tmp_path / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md", "# Deep Research\n")
    _write(tmp_path / "docs" / "workflow" / "ROADMAP_AUTHORING_STANDARD.md", "# Roadmap\n")
    _write(tmp_path / "src" / "project_os_core" / "router" / "__init__.py", "")
    _write(tmp_path / "src" / "project_os_core" / "learning" / "__init__.py", "")

    payload = scaffold_research(
        tmp_path,
        ResearchScaffoldRequest(
            title="UEFN Bridge Review",
            kind="audit",
            question="Verifier les meilleurs bridges plugin-free pour UEFN.",
            keywords=["deep research", "regarde les forks"],
        ),
    )

    generated = Path(payload["path"])
    assert generated.exists()
    assert payload["research_profile"] == "component_discovery"
    content = generated.read_text(encoding="utf-8")
    assert "# UEFN Bridge Review" in content
    assert "research_profile=component_discovery" in content
    assert "Verifier les meilleurs bridges plugin-free pour UEFN." in content
    assert "`router`" in content
    assert "`learning`" in content
    assert "`deep research`" in content
    assert "[DEEP_RESEARCH_PROTOCOL.md]" in content


def test_scaffold_research_system_uses_system_destination(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "# Agents\n")
    _write(tmp_path / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md", "# Deep Research\n")
    _write(tmp_path / "src" / "project_os_core" / "api_runs" / "__init__.py", "")

    payload = scaffold_research(
        tmp_path,
        ResearchScaffoldRequest(
            title="Research Mode System",
            kind="system",
        ),
    )

    generated = Path(payload["path"])
    assert generated.exists()
    assert generated.parent.name == "systems"
    assert generated.name.endswith("_DOSSIER.md")
    assert payload["research_profile"] == "component_discovery"
    content = generated.read_text(encoding="utf-8")
    assert "## A faire" in content
    assert "## A etudier" in content


def test_detect_deep_research_request_infers_memory_system_doc() -> None:
    detected = detect_deep_research_request(
        "Deep research sur les meilleurs systemes de memoire pour le projet, regarde les forks."
    )

    assert detected is not None
    assert detected.kind == "system"
    assert detected.research_profile == "component_discovery"
    assert detected.title == "Memory Systems"
    assert "deep research" in detected.keywords


def test_detect_deep_research_request_accepts_common_french_typo() -> None:
    detected = detect_deep_research_request(
        "recherche appronfondie legeres sur les tomates"
    )

    assert detected is not None
    assert detected.kind == "audit"
    assert detected.research_profile == "domain_audit"
    assert detected.title == "Legeres Sur Les Tomates"
    assert "recherche approfondie" in detected.keywords


def test_detect_deep_research_request_infers_project_audit_profile() -> None:
    detected = detect_deep_research_request(
        "recherche approfondie pour un audit de mon projet de ce qu'on pourrait ameliorer"
    )

    assert detected is not None
    assert detected.kind == "audit"
    assert detected.research_profile == "project_audit"
    assert detected.title == "Project OS Strategic Audit"


def test_detect_deep_research_request_keeps_project_audit_in_audit_lane_even_with_system_wording() -> None:
    detected = detect_deep_research_request(
        "deep research sur mon projet pour atteindre le full system et la roadmap globale"
    )

    assert detected is not None
    assert detected.kind == "audit"
    assert detected.research_profile == "project_audit"
    assert detected.title == "Project OS Strategic Audit"


def test_detect_deep_research_request_infers_component_profile_inside_audit_kind() -> None:
    detected = detect_deep_research_request(
        "deep research sur mon projet pour ameliorer le gateway discord et les workers"
    )

    assert detected is not None
    assert detected.kind == "audit"
    assert detected.research_profile == "component_discovery"
    assert detected.title == "Discord Operations"
