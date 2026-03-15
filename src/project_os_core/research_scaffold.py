from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any
import unicodedata


DEFAULT_RESEARCH_KEYWORDS: tuple[str, ...] = (
    "deep research",
    "recherche approfondie",
    "audit profond",
    "fouille github",
    "cherche les pepites",
    "regarde les forks",
    "va chercher plus loin",
)

_DEEP_RESEARCH_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bdeep\s+research\b", "deep research"),
    (r"\brecherche\s+appro?n?fond\w*\b", "recherche approfondie"),
    (r"\brecherche\s+en\s+profondeur\b", "recherche approfondie"),
    (r"\baudit\s+profond\w*\b", "audit profond"),
    (r"\bfouille\s+github\b", "fouille github"),
    (r"\bcherche\s+(?:les\s+)?pepites\b", "cherche les pepites"),
    (r"\bregarde\s+(?:les\s+)?forks\b", "regarde les forks"),
    (r"\bva\s+chercher\s+plus\s+loin\b", "va chercher plus loin"),
)

SYSTEM_HINTS: tuple[str, ...] = (
    "systeme",
    "systemes",
    "system",
    "systems",
    "stack",
    "stacks",
    "categorie",
    "categories",
    "category",
    "framework",
    "frameworks",
)


@dataclass(slots=True)
class DetectedResearchIntent:
    title: str
    kind: str
    question: str
    keywords: list[str]
    normalized_text: str


@dataclass(slots=True)
class ResearchScaffoldRequest:
    title: str
    kind: str = "audit"
    slug: str | None = None
    question: str | None = None
    keywords: list[str] = field(default_factory=list)
    recent_days: int = 30
    overwrite: bool = False


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or "deep_research"


def _file_stem(value: str) -> str:
    return _slugify(value).upper()


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_value.lower()
    return re.sub(r"\s+", " ", lowered).strip()


def _relative_markdown_link(base_dir: Path, target: Path) -> str:
    return Path(os.path.relpath(target, start=base_dir)).as_posix()


def _core_packages(repo_root: Path) -> list[str]:
    package_root = repo_root / "src" / "project_os_core"
    if not package_root.exists():
        return []
    names = sorted(path.name for path in package_root.iterdir() if path.is_dir() and not path.name.startswith("__"))
    return names


def _existing_local_refs(repo_root: Path) -> list[Path]:
    candidates = [
        repo_root / "AGENTS.md",
        repo_root / "PROJECT_OS_MASTER_MACHINE.md",
        repo_root / "docs" / "roadmap" / "BUILD_STATUS_CHECKLIST.md",
        repo_root / "docs" / "workflow" / "ROADMAP_AUTHORING_STANDARD.md",
        repo_root / "docs" / "workflow" / "SYSTEM_DOSSIER_AUTHORING_STANDARD.md",
        repo_root / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md",
        repo_root / "docs" / "systems" / "README.md",
    ]
    return [path for path in candidates if path.exists()]


def core_packages(repo_root: Path) -> list[str]:
    return _core_packages(repo_root)


def existing_local_refs(repo_root: Path) -> list[Path]:
    return _existing_local_refs(repo_root)


def _destination_path(repo_root: Path, request: ResearchScaffoldRequest) -> Path:
    stem = _file_stem(request.slug or request.title)
    today = datetime.now(timezone.utc).date().isoformat()
    if request.kind == "system":
        return repo_root / "docs" / "systems" / f"{stem}_DOSSIER.md"
    return repo_root / "docs" / "audits" / f"{stem}_AUDIT_{today}.md"


def _build_protocol_lines() -> list[str]:
    return [
        "1. `repo-first` : inspecter d'abord le code, les docs et les contraintes reelles de `Project OS` avant de chercher des briques externes.",
        "2. `sources primaires + recence` : privilegier docs officielles, papiers originaux, repos officiels, changelogs et pages produit recentes.",
        "3. `lane GitHub upstream` : lire le `README`, verifier licence, surface d'installation, activite recente, releases, security/dependency graph si disponible.",
        "4. `lane forks et satellites` : verifier les forks actifs et les repos satellites, puis dire explicitement s'il n'existe pas de vraie pepite au-dela de l'upstream.",
        "5. `lane integration Project OS` : classer chaque piste en `KEEP`, `ADAPT`, `DEFER` ou `REJECT`, avec les packages ou docs impactes dans le repo.",
        "6. `lane preuve` : pour toute recommandation actionnable, definir une preuve ou un test concret a obtenir sur la machine ou dans le repo.",
    ]


def detect_deep_research_request(text: str) -> DetectedResearchIntent | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    normalized = _normalize_text(raw)
    matched_keywords: list[str] = []
    for pattern, keyword in _DEEP_RESEARCH_PATTERNS:
        if re.search(pattern, normalized) and keyword not in matched_keywords:
            matched_keywords.append(keyword)
    if not matched_keywords:
        return None
    kind = "system" if any(hint in normalized for hint in SYSTEM_HINTS) else "audit"
    title = _infer_research_title(raw=raw, normalized=normalized, kind=kind)
    return DetectedResearchIntent(
        title=title,
        kind=kind,
        question=raw,
        keywords=matched_keywords,
        normalized_text=normalized,
    )


def _infer_research_title(*, raw: str, normalized: str, kind: str) -> str:
    overrides: list[tuple[tuple[str, ...], str, str | None]] = [
        (("memoire",), "Memory Systems", "system"),
        (("memory",), "Memory Systems", "system"),
        (("uefn", "computer use"), "UEFN Computer Use Stack", "system"),
        (("uefn", "gui"), "UEFN Computer Use Stack", "system"),
        (("openclaw",), "OpenClaw Upstream", None),
        (("discord",), "Discord Operations", None),
        (("router", "orchestration"), "Routing And Orchestration Systems", "system"),
        (("routing", "orchestration"), "Routing And Orchestration Systems", "system"),
        (("eval", "grader"), "Eval And Grader Systems", "system"),
        (("apprentissage",), "Learning Runtime Systems", "system"),
        (("learning",), "Learning Runtime Systems", "system"),
    ]
    for tokens, title, required_kind in overrides:
        if all(token in normalized for token in tokens) and (required_kind is None or required_kind == kind):
            return title
    cleaned = _strip_research_prefixes(raw)
    words = re.findall(r"[A-Za-z0-9]+", cleaned)
    if not words:
        return "Deep Research Topic" if kind == "audit" else "Research System"
    selected = words[: min(6, len(words))]
    return " ".join(item.capitalize() for item in selected)


def _strip_research_prefixes(value: str) -> str:
    cleaned = value.strip()
    patterns = [
        r"(?i)\bdeep research\b",
        r"(?i)\brecherche appro?n?fond\w*\b",
        r"(?i)\brecherche en profondeur\b",
        r"(?i)\baudit profond\b",
        r"(?i)\bfouille github\b",
        r"(?i)\bcherche les pepites\b",
        r"(?i)\bregarde les forks\b",
        r"(?i)\bva chercher plus loin\b",
        r"(?i)^\s*sur\b",
        r"(?i)\bpour le projet\b",
        r"(?i)\bles meilleurs?\b",
        r"(?i)\bmeilleurs?\b",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" .:-")


def _build_audit_template(repo_root: Path, destination: Path, request: ResearchScaffoldRequest) -> str:
    keywords = request.keywords or list(DEFAULT_RESEARCH_KEYWORDS)
    question = request.question or "A preciser pendant la recherche."
    package_lines = [f"- `{name}`" for name in _core_packages(repo_root)] or ["- `src/project_os_core/` a inspecter"]
    local_refs = [
        f"- [{path.name}]({_relative_markdown_link(destination.parent, path)})"
        for path in _existing_local_refs(repo_root)
    ]
    protocol_lines = [f"- {line}" for line in _build_protocol_lines()]
    keyword_lines = [f"- `{item}`" for item in keywords]
    return "\n".join(
        [
            f"# {request.title}",
            "",
            "## Statut",
            "",
            "- `draft`",
            "",
            "## But",
            "",
            "- produire une recherche approfondie avec un standard reutilisable",
            "- relier les sources externes au repo reel avant toute recommandation",
            "",
            "## Question de recherche",
            "",
            f"- {question}",
            "",
            "## Declencheurs",
            "",
            *keyword_lines,
            "",
            "## Point de depart reel",
            "",
            "Packages coeur detectes:",
            "",
            *package_lines,
            "",
            "References locales a relire avant synthese:",
            "",
            *(local_refs or ["- aucune reference locale detectee automatiquement"]),
            "",
            "## Protocole obligatoire",
            "",
            *protocol_lines,
            "",
            "## Checklist d'execution",
            "",
            "- [ ] relire les references locales pertinentes",
            "- [ ] identifier les contraintes reelles du repo avant la veille externe",
            "- [ ] collecter des sources primaires recentes avec dates explicites",
            "- [ ] inspecter les repos GitHub officiels, leurs `README`, licences et activite",
            "- [ ] verifier les forks, la network graph et les satellites utiles",
            "- [ ] classer `KEEP / ADAPT / DEFER / REJECT`",
            "- [ ] dire ou chaque recommandation entre dans `Project OS`",
            "- [ ] definir les preuves ou tests concrets a obtenir",
            "",
            "## Resultats",
            "",
            "### Synthese",
            "",
            "- a remplir",
            "",
            "### Ce qu'on recupere",
            "",
            "- a remplir",
            "",
            "### Ce qu'on n'importe pas",
            "",
            "- a remplir",
            "",
            "### Impact Project OS",
            "",
            "- packages ou docs a etendre",
            "",
            "### Preuves a obtenir",
            "",
            "- a remplir",
            "",
            "## Sources",
            "",
            "- [DEEP_RESEARCH_PROTOCOL.md]("
            + _relative_markdown_link(destination.parent, repo_root / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md")
            + ")",
        ]
    ).rstrip() + "\n"


def _build_system_template(repo_root: Path, destination: Path, request: ResearchScaffoldRequest) -> str:
    keywords = request.keywords or list(DEFAULT_RESEARCH_KEYWORDS)
    question = request.question or "A preciser pendant la recherche."
    package_lines = [f"- `{name}`" for name in _core_packages(repo_root)] or ["- `src/project_os_core/` a inspecter"]
    local_refs = [
        f"- [{path.name}]({_relative_markdown_link(destination.parent, path)})"
        for path in _existing_local_refs(repo_root)
    ]
    protocol_lines = [f"- {line}" for line in _build_protocol_lines()]
    keyword_lines = [f"- `{item}`" for item in keywords]
    return "\n".join(
        [
            f"# {request.title}",
            "",
            "## Statut",
            "",
            "- `draft`",
            "",
            "## But",
            "",
            "- classer un systeme externe ou une stack en `A faire / A etudier / A rejeter`",
            "- garder la recherche alignee sur `Project OS` au lieu d'empiler de la hype",
            "",
            "## Question de recherche",
            "",
            f"- {question}",
            "",
            "## Declencheurs",
            "",
            *keyword_lines,
            "",
            "## Point de depart reel",
            "",
            "Packages coeur detectes:",
            "",
            *package_lines,
            "",
            "References locales a relire avant synthese:",
            "",
            *(local_refs or ["- aucune reference locale detectee automatiquement"]),
            "",
            "## Protocole obligatoire",
            "",
            *protocol_lines,
            "",
            "## A faire",
            "",
            "### Systeme ou repo",
            "",
            "Etat:",
            "",
            "- `A_FAIRE`",
            "",
            "Pourquoi il compte:",
            "",
            "- a remplir",
            "",
            "Ce qu'on recupere:",
            "",
            "- a remplir",
            "",
            "Ce qu'on n'importe pas:",
            "",
            "- a remplir",
            "",
            "Preuves a obtenir:",
            "",
            "- a remplir",
            "",
            "Ou ca entre dans Project OS:",
            "",
            "- a remplir",
            "",
            "Sources primaires:",
            "",
            "- a remplir",
            "",
            "## A etudier",
            "",
            "- a remplir",
            "",
            "## A rejeter pour maintenant",
            "",
            "- a remplir",
            "",
            "## Sources",
            "",
            "- [DEEP_RESEARCH_PROTOCOL.md]("
            + _relative_markdown_link(destination.parent, repo_root / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md")
            + ")",
        ]
    ).rstrip() + "\n"


def scaffold_research(repo_root: Path, request: ResearchScaffoldRequest) -> dict[str, Any]:
    kind = str(request.kind or "audit").strip().lower()
    if kind not in {"audit", "system"}:
        raise ValueError("Research scaffold kind must be 'audit' or 'system'.")
    normalized = ResearchScaffoldRequest(
        title=request.title.strip(),
        kind=kind,
        slug=request.slug.strip() if request.slug else None,
        question=request.question.strip() if request.question else None,
        keywords=[item.strip() for item in request.keywords if item.strip()],
        recent_days=max(1, int(request.recent_days)),
        overwrite=bool(request.overwrite),
    )
    if not normalized.title:
        raise ValueError("Research scaffold title is required.")
    destination = _destination_path(repo_root, normalized)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not normalized.overwrite:
        return {
            "path": str(destination),
            "kind": normalized.kind,
            "title": normalized.title,
            "keywords": normalized.keywords or list(DEFAULT_RESEARCH_KEYWORDS),
            "recent_days": normalized.recent_days,
            "core_packages": _core_packages(repo_root),
            "created": False,
        }
    content = (
        _build_system_template(repo_root, destination, normalized)
        if normalized.kind == "system"
        else _build_audit_template(repo_root, destination, normalized)
    )
    destination.write_text(content, encoding="utf-8")
    return {
        "path": str(destination),
        "kind": normalized.kind,
        "title": normalized.title,
        "keywords": normalized.keywords or list(DEFAULT_RESEARCH_KEYWORDS),
        "recent_days": normalized.recent_days,
        "core_packages": _core_packages(repo_root),
        "created": True,
    }
