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

PROJECT_SCOPE_HINTS: tuple[str, ...] = (
    "project os",
    "mon projet",
    "my project",
    "notre projet",
)

PROJECT_GLOBAL_HINTS: tuple[str, ...] = (
    "roadmap",
    "global",
    "overall",
    "full system",
    "whole project",
    "grand projet",
    "audit de mon projet",
    "audit of my project",
    "ce qu on pourrait ameliorer",
    "what to improve overall",
    "how to reach the full system",
)

COMPONENT_HINTS: tuple[str, ...] = SYSTEM_HINTS + (
    "memoire",
    "memory",
    "router",
    "routing",
    "orchestration",
    "eval",
    "evals",
    "grader",
    "graders",
    "verification",
    "verifier",
    "desktop",
    "discord",
    "gateway",
    "worker",
    "workers",
    "learning",
    "feature",
    "features",
    "piece",
    "pieces",
    "subsystem",
    "subsystems",
    "component",
    "components",
)

_VALID_RESEARCH_PROFILES = {"project_audit", "component_discovery", "domain_audit"}
_VALID_RESEARCH_INTENSITIES = {"simple", "complex", "extreme"}

_EXPLICIT_PROJECT_AUDIT_HINTS: tuple[str, ...] = (
    "project audit",
    "audit projet",
    "audit project os",
    "audit global",
    "global audit",
    "overall audit",
    "whole project audit",
    "mode project audit",
)
_EXPLICIT_COMPONENT_DISCOVERY_HINTS: tuple[str, ...] = (
    "component discovery",
    "audit systeme",
    "system audit",
    "audit subsystem",
    "subsystem audit",
    "feature audit",
    "audit feature",
    "stack audit",
    "mode component discovery",
)
_EXPLICIT_DOMAIN_AUDIT_HINTS: tuple[str, ...] = (
    "domain audit",
    "audit domaine",
    "audit externe",
    "external audit",
    "mode domain audit",
)

_SIMPLE_INTENSITY_HINTS: tuple[str, ...] = (
    "simple",
    "lite",
    "light",
    "leger",
    "legere",
    "normal",
)
_COMPLEX_INTENSITY_HINTS: tuple[str, ...] = (
    "complexe",
    "complex",
    "committee",
    "comite",
)
_EXTREME_INTENSITY_HINTS: tuple[str, ...] = (
    "extreme",
    "war room",
    "warroom",
)


@dataclass(slots=True)
class DetectedResearchIntent:
    title: str
    kind: str
    research_profile: str
    research_intensity: str
    question: str
    keywords: list[str]
    normalized_text: str
    recommended_profile: str
    recommended_intensity: str
    explicit_profile: str | None = None
    explicit_intensity: str | None = None


@dataclass(slots=True)
class ResearchScaffoldRequest:
    title: str
    kind: str = "audit"
    research_profile: str | None = None
    research_intensity: str | None = None
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


def _contains_any(normalized: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in normalized for phrase in phrases)


def infer_research_profile(*, raw: str, normalized: str | None = None, kind: str = "audit") -> str:
    normalized_text = normalized or _normalize_text(raw)
    normalized_kind = str(kind or "audit").strip().lower()
    if normalized_kind == "system":
        return "component_discovery"
    has_project_scope = _contains_any(normalized_text, PROJECT_SCOPE_HINTS)
    has_project_global_scope = _contains_any(normalized_text, PROJECT_GLOBAL_HINTS)
    has_component_scope = _contains_any(normalized_text, COMPONENT_HINTS)
    if has_project_scope and has_project_global_scope:
        return "project_audit"
    if has_component_scope:
        return "component_discovery"
    if has_project_scope:
        return "project_audit"
    return "domain_audit"


def detect_explicit_research_profile(raw: str, *, normalized: str | None = None) -> str | None:
    normalized_text = normalized or _normalize_text(raw)
    if _contains_any(normalized_text, _EXPLICIT_PROJECT_AUDIT_HINTS):
        return "project_audit"
    if _contains_any(normalized_text, _EXPLICIT_COMPONENT_DISCOVERY_HINTS):
        return "component_discovery"
    if _contains_any(normalized_text, _EXPLICIT_DOMAIN_AUDIT_HINTS):
        return "domain_audit"
    return None


def detect_explicit_research_intensity(raw: str, *, normalized: str | None = None) -> str | None:
    normalized_text = normalized or _normalize_text(raw)
    if _contains_any(normalized_text, _EXTREME_INTENSITY_HINTS):
        return "extreme"
    if _contains_any(normalized_text, _COMPLEX_INTENSITY_HINTS):
        return "complex"
    if _contains_any(normalized_text, _SIMPLE_INTENSITY_HINTS):
        return "simple"
    return None


def infer_research_intensity(
    *,
    raw: str,
    kind: str = "audit",
    research_profile: str | None = None,
    normalized: str | None = None,
) -> str:
    normalized_text = normalized or _normalize_text(raw)
    explicit = detect_explicit_research_intensity(raw, normalized=normalized_text)
    if explicit:
        return explicit
    profile = str(research_profile or "").strip().lower() or infer_research_profile(
        raw=raw,
        normalized=normalized_text,
        kind=kind,
    )
    if profile in {"project_audit", "component_discovery"}:
        return "complex"
    return "simple"


def parse_research_mode_selection(
    text: str,
    *,
    kind: str = "audit",
    fallback_profile: str | None = None,
    fallback_intensity: str | None = None,
) -> dict[str, str | None]:
    raw = str(text or "").strip()
    normalized = _normalize_text(raw)
    explicit_profile = detect_explicit_research_profile(raw, normalized=normalized)
    explicit_intensity = detect_explicit_research_intensity(raw, normalized=normalized)
    selected_profile = explicit_profile or (
        fallback_profile if str(fallback_profile or "").strip().lower() in _VALID_RESEARCH_PROFILES else None
    )
    selected_intensity = explicit_intensity or (
        fallback_intensity if str(fallback_intensity or "").strip().lower() in _VALID_RESEARCH_INTENSITIES else None
    )
    recommended_profile = infer_research_profile(raw=raw, normalized=normalized, kind=kind)
    recommended_intensity = infer_research_intensity(
        raw=raw,
        kind=kind,
        research_profile=selected_profile or recommended_profile,
        normalized=normalized,
    )
    return {
        "selected_profile": selected_profile,
        "selected_intensity": selected_intensity,
        "recommended_profile": recommended_profile,
        "recommended_intensity": recommended_intensity,
    }


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
    hinted_kind = "system" if any(hint in normalized for hint in SYSTEM_HINTS) else "audit"
    explicit_profile = detect_explicit_research_profile(raw, normalized=normalized)
    explicit_intensity = detect_explicit_research_intensity(raw, normalized=normalized)
    provisional_profile = explicit_profile or infer_research_profile(raw=raw, normalized=normalized, kind="audit")
    kind = "system" if hinted_kind == "system" and provisional_profile == "component_discovery" else "audit"
    recommended_profile = infer_research_profile(raw=raw, normalized=normalized, kind=kind)
    recommended_intensity = infer_research_intensity(
        raw=raw,
        normalized=normalized,
        kind=kind,
        research_profile=recommended_profile,
    )
    research_profile = explicit_profile or recommended_profile
    research_intensity = explicit_intensity or recommended_intensity
    title = _infer_research_title(raw=raw, normalized=normalized, kind=kind, research_profile=research_profile)
    return DetectedResearchIntent(
        title=title,
        kind=kind,
        research_profile=research_profile,
        research_intensity=research_intensity,
        question=raw,
        keywords=matched_keywords,
        normalized_text=normalized,
        recommended_profile=recommended_profile,
        recommended_intensity=recommended_intensity,
        explicit_profile=explicit_profile,
        explicit_intensity=explicit_intensity,
    )


def _infer_research_title(*, raw: str, normalized: str, kind: str, research_profile: str) -> str:
    if research_profile == "project_audit" and (
        "project os" in normalized or "mon projet" in normalized or "my project" in normalized
    ):
        return "Project OS Strategic Audit"
    overrides: list[tuple[tuple[str, ...], str, str | None, str | None]] = [
        (("memoire",), "Memory Systems", None, "component_discovery"),
        (("memory",), "Memory Systems", None, "component_discovery"),
        (("uefn", "computer use"), "UEFN Computer Use Stack", None, "component_discovery"),
        (("uefn", "gui"), "UEFN Computer Use Stack", None, "component_discovery"),
        (("openclaw",), "OpenClaw Upstream", None, None),
        (("discord",), "Discord Operations", None, None),
        (("router", "orchestration"), "Routing And Orchestration Systems", None, "component_discovery"),
        (("routing", "orchestration"), "Routing And Orchestration Systems", None, "component_discovery"),
        (("eval", "grader"), "Eval And Grader Systems", None, "component_discovery"),
        (("apprentissage",), "Learning Runtime Systems", None, "component_discovery"),
        (("learning",), "Learning Runtime Systems", None, "component_discovery"),
    ]
    for tokens, title, required_kind, required_profile in overrides:
        if all(token in normalized for token in tokens) and (required_kind is None or required_kind == kind) and (
            required_profile is None or required_profile == research_profile
        ):
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
            f"- `research_profile={request.research_profile or 'domain_audit'}`",
            f"- `research_intensity={request.research_intensity or 'simple'}`",
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
            f"- `research_profile={request.research_profile or 'component_discovery'}`",
            f"- `research_intensity={request.research_intensity or 'complex'}`",
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
    research_profile = str(request.research_profile or "").strip().lower() or infer_research_profile(
        raw=str(request.question or request.title or "").strip(),
        kind=kind,
    )
    if research_profile not in _VALID_RESEARCH_PROFILES:
        raise ValueError("Research scaffold profile must be project_audit, component_discovery, or domain_audit.")
    if research_profile != "component_discovery":
        kind = "audit"
    research_intensity = str(request.research_intensity or "").strip().lower() or infer_research_intensity(
        raw=str(request.question or request.title or "").strip(),
        kind=kind,
        research_profile=research_profile,
    )
    if research_intensity not in _VALID_RESEARCH_INTENSITIES:
        raise ValueError("Research scaffold intensity must be simple, complex, or extreme.")
    normalized = ResearchScaffoldRequest(
        title=request.title.strip(),
        kind=kind,
        research_profile=research_profile,
        research_intensity=research_intensity,
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
            "research_profile": normalized.research_profile,
            "research_intensity": normalized.research_intensity,
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
        "research_profile": normalized.research_profile,
        "research_intensity": normalized.research_intensity,
        "title": normalized.title,
        "keywords": normalized.keywords or list(DEFAULT_RESEARCH_KEYWORDS),
        "recent_days": normalized.recent_days,
        "core_packages": _core_packages(repo_root),
        "created": True,
    }
