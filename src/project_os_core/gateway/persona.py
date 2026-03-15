from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..config import repo_root
from ..models import SensitivityClass


@dataclass(frozen=True, slots=True)
class PersonaIdentity:
    name: str
    public_title: str
    role: str
    mission: str
    voice: str
    stance: str


@dataclass(frozen=True, slots=True)
class PersonaAxis:
    key: str
    minimum: int
    maximum: int
    default: int
    description: str


@dataclass(frozen=True, slots=True)
class PersonaGuardrails:
    anti_patterns: tuple[str, ...]
    truth_rules: tuple[str, ...]
    model_override_rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonaExample:
    title: str
    founder_message: str
    good_reply: str
    avoid_reply: str | None = None


@dataclass(frozen=True, slots=True)
class LocalLaneConfig:
    baseline: str
    sensitivity_overrides: dict[SensitivityClass, str]


@dataclass(frozen=True, slots=True)
class PersonaSpec:
    version: str
    version_hash: str
    identity: PersonaIdentity
    style_axes: tuple[PersonaAxis, ...]
    guardrails: PersonaGuardrails
    local_lane: LocalLaneConfig
    few_shot_examples: tuple[PersonaExample, ...]
    source_path: Path | None = None

    def render_shared_prompt(self) -> str:
        axis_lines = "\n".join(
            f"- {axis.key}: {axis.default}/{axis.maximum} - {axis.description}" for axis in self.style_axes
        )
        anti_pattern_lines = "\n".join(f"- {item}" for item in self.guardrails.anti_patterns)
        truth_lines = "\n".join(f"- {item}" for item in self.guardrails.truth_rules)
        override_lines = "\n".join(f"- {item}" for item in self.guardrails.model_override_rules)
        example_blocks = "\n".join(
            self._render_example(example)
            for example in self.few_shot_examples
        )
        return (
            f"<persona version=\"{self.version}\" hash=\"{self.version_hash}\">\n"
            "<identity>\n"
            f"name: {self.identity.name}\n"
            f"public_title: {self.identity.public_title}\n"
            f"role: {self.identity.role}\n"
            f"mission: {self.identity.mission}\n"
            f"voice: {self.identity.voice}\n"
            f"stance: {self.identity.stance}\n"
            "</identity>\n"
            "<style_axes>\n"
            f"{axis_lines}\n"
            "</style_axes>\n"
            "<instructions>\n"
            "Parle en francais naturel, net et humain.\n"
            "Adapte-toi au ton du fondateur: tres net si le sujet est serieux, plus souple si le message est leger.\n"
            "Reste centre sur le confort de travail, la comprehension humaine, l'objectivite et le bon prochain pas.\n"
            "Tu n'es ni un assistant web public ni le decideur final.\n"
            "Tu aides a clarifier, challenger, traduire et formuler le bon prochain pas pour Project OS.\n"
            "</instructions>\n"
            "<anti_patterns>\n"
            f"{anti_pattern_lines}\n"
            "</anti_patterns>\n"
            "<truth_rules>\n"
            f"{truth_lines}\n"
            "</truth_rules>\n"
            "<model_override_rules>\n"
            f"{override_lines}\n"
            "</model_override_rules>\n"
            "<examples>\n"
            f"{example_blocks}\n"
            "</examples>\n"
            "</persona>"
        )

    def render_anthropic_system(self) -> list[dict[str, object]]:
        return [
            {
                "type": "text",
                "text": self.render_shared_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def render_openai_developer(self) -> str:
        return self.render_shared_prompt()

    def render_local_system(self, sensitivity: SensitivityClass) -> str:
        extra = self.local_lane.sensitivity_overrides.get(sensitivity) or self.local_lane.sensitivity_overrides.get(
            SensitivityClass.S1, ""
        )
        return (
            f"{self.local_lane.baseline} "
            f"Identite: {self.identity.public_title}. "
            f"Voix: {self.identity.voice}. "
            f"Posture: {self.identity.stance}. "
            "Ne promets pas d'actions non executees. "
            "Ne te presente pas comme un assistant generique. "
            f"{extra}"
        ).strip()

    @staticmethod
    def _render_example(example: PersonaExample) -> str:
        avoid = f"\n<avoid_reply>{example.avoid_reply}</avoid_reply>" if example.avoid_reply else ""
        return (
            "<example>\n"
            f"<title>{example.title}</title>\n"
            f"<founder_message>{example.founder_message}</founder_message>\n"
            f"<good_reply>{example.good_reply}</good_reply>{avoid}\n"
            "</example>"
        )


def default_persona_path() -> Path:
    return repo_root() / "config" / "project_os_persona.yaml"


def load_persona_spec(path: str | Path | None = None) -> PersonaSpec:
    resolved = Path(path) if path else default_persona_path()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("project_os_persona.yaml must contain a top-level mapping.")
    canonical_payload = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    version_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()[:12]
    return PersonaSpec(
        version=str(payload.get("version") or "unknown"),
        version_hash=version_hash,
        identity=_parse_identity(payload.get("identity")),
        style_axes=_parse_style_axes(payload.get("style_axes")),
        guardrails=_parse_guardrails(payload.get("guardrails")),
        local_lane=_parse_local_lane(payload.get("local_lane")),
        few_shot_examples=_parse_examples(payload.get("few_shot_examples")),
        source_path=resolved,
    )


def _parse_identity(raw: Any) -> PersonaIdentity:
    payload = _require_mapping(raw, "identity")
    return PersonaIdentity(
        name=_require_text(payload, "name"),
        public_title=_require_text(payload, "public_title"),
        role=_require_text(payload, "role"),
        mission=_require_text(payload, "mission"),
        voice=_require_text(payload, "voice"),
        stance=_require_text(payload, "stance"),
    )


def _parse_style_axes(raw: Any) -> tuple[PersonaAxis, ...]:
    payload = _require_mapping(raw, "style_axes")
    axes: list[PersonaAxis] = []
    for key, value in payload.items():
        axis_payload = _require_mapping(value, f"style_axes.{key}")
        minimum = _require_int(axis_payload, "min", f"style_axes.{key}")
        maximum = _require_int(axis_payload, "max", f"style_axes.{key}")
        default = _require_int(axis_payload, "default", f"style_axes.{key}")
        if minimum > default or default > maximum:
            raise ValueError(f"style_axes.{key} has invalid min/default/max ordering.")
        axes.append(
            PersonaAxis(
                key=str(key),
                minimum=minimum,
                maximum=maximum,
                default=default,
                description=_require_text(axis_payload, "description"),
            )
        )
    return tuple(axes)


def _parse_guardrails(raw: Any) -> PersonaGuardrails:
    payload = _require_mapping(raw, "guardrails")
    return PersonaGuardrails(
        anti_patterns=_require_text_list(payload.get("anti_patterns"), "guardrails.anti_patterns"),
        truth_rules=_require_text_list(payload.get("truth_rules"), "guardrails.truth_rules"),
        model_override_rules=_require_text_list(
            payload.get("model_override_rules"), "guardrails.model_override_rules"
        ),
    )


def _parse_local_lane(raw: Any) -> LocalLaneConfig:
    payload = _require_mapping(raw, "local_lane")
    raw_overrides = _require_mapping(payload.get("sensitivity_overrides"), "local_lane.sensitivity_overrides")
    overrides: dict[SensitivityClass, str] = {}
    for key, value in raw_overrides.items():
        try:
            normalized = str(key).strip().lower()
            sensitivity = {
                "s1": SensitivityClass.S1,
                "s2": SensitivityClass.S2,
                "s3": SensitivityClass.S3,
                SensitivityClass.S1.value: SensitivityClass.S1,
                SensitivityClass.S2.value: SensitivityClass.S2,
                SensitivityClass.S3.value: SensitivityClass.S3,
            }[normalized]
        except Exception as exc:
            raise ValueError(f"Unknown local lane sensitivity override '{key}'.") from exc
        overrides[sensitivity] = str(value).strip()
    return LocalLaneConfig(
        baseline=_require_text(payload, "baseline"),
        sensitivity_overrides=overrides,
    )


def _parse_examples(raw: Any) -> tuple[PersonaExample, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("few_shot_examples must be a non-empty list.")
    examples: list[PersonaExample] = []
    for index, item in enumerate(raw):
        payload = _require_mapping(item, f"few_shot_examples[{index}]")
        examples.append(
            PersonaExample(
                title=_require_text(payload, "title"),
                founder_message=_require_text(payload, "founder_message"),
                good_reply=_require_text(payload, "good_reply"),
                avoid_reply=str(payload.get("avoid_reply") or "").strip() or None,
            )
        )
    return tuple(examples)


def _require_mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping.")
    return raw


def _require_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"Missing required text field '{key}'.")
    return value


def _require_int(payload: dict[str, Any], key: str, label: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{label}.{key} must be an integer.")
    return value


def _require_text_list(raw: Any, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label} must be a non-empty list.")
    values = tuple(str(item).strip() for item in raw if str(item).strip())
    if not values:
        raise ValueError(f"{label} must contain at least one non-empty item.")
    return values
