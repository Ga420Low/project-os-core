from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ..models import (
    ActionRiskClass,
    ChannelEvent,
    ConversationThreadRef,
    OperatorMessage,
    RuntimeState,
    RuntimeVerdict,
    new_id,
    to_jsonable,
)
from ..services import AppServices, build_app_services


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "storage_roots.local.json"
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "runtime_policy.local.json"
DEFAULT_SMOKE_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
PERSONA_DELIVERY_MODES = ("inline_text", "thread_chunked_text", "artifact_summary")
_MISSING = object()


@dataclass(slots=True, frozen=True)
class TurnExpectation:
    expected_reply_kind: str | None = None
    expected_provider: str | None = None
    expected_delivery_modes: tuple[str, ...] = ()
    required_summary_terms: tuple[str, ...] = ()
    required_summary_any: tuple[str, ...] = ()
    forbidden_summary_terms: tuple[str, ...] = ()
    required_paths: dict[str, Any] = field(default_factory=dict)
    required_path_any_of: dict[str, tuple[Any, ...]] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SmokeTurn:
    prompt: str
    expectation: TurnExpectation
    target_profile: str = "core"
    requested_worker: str | None = None
    risk_class: ActionRiskClass | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    patched_scaffold_payload: dict[str, Any] | None = None
    stub_simple_chat_response: str | None = None


@dataclass(slots=True, frozen=True)
class SmokeScenario:
    scenario_id: str
    description: str
    turns: tuple[SmokeTurn, ...]
    layer: str = "smoke"
    required_runtime_profiles: tuple[str, ...] = ("core",)
    requires_anthropic: bool = False
    scenario_stub_simple_chat_response: str | None = None
    default_enabled: bool = True


def visible_smoke_scenarios() -> tuple[SmokeScenario, ...]:
    deep_research_base_payload = {
        "path": "D:\\ProjectOS\\project-os-core\\docs\\systems\\MEMORY_SYSTEMS_DOSSIER.md",
        "relative_path": "docs/systems/MEMORY_SYSTEMS_DOSSIER.md",
        "doc_name": "MEMORY_SYSTEMS_DOSSIER.md",
        "kind": "system",
        "title": "Memory Systems",
        "keywords": ["deep research", "memoire", "discord"],
        "recent_days": 30,
        "created": True,
        "recommended_profile": "component_discovery",
        "recommended_intensity": "complex",
    }
    return (
        SmokeScenario(
            scenario_id="natural_reply_hides_plumbing",
            description="Une question standard doit rester naturelle et cacher la tuyauterie interne.",
            layer="smoke",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="Explique-moi en 5 lignes le but du nettoyage visible de la facade Discord.",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=("inline_text", "thread_chunked_text"),
                        forbidden_summary_terms=(
                            "api utilisee",
                            "provider:",
                            "route_reason",
                            "query_scope",
                            "mode selectionne",
                            "[local / ollama]",
                            "[local s3 / ollama]",
                        ),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="provider_disclosure_on_demand",
            description="Le provider/modele reste masque par defaut mais devient accessible sur demande explicite.",
            layer="smoke",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="Explique-moi brievement le principe d'une facade conversationnelle naturelle sur Discord.",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=("inline_text", "thread_chunked_text"),
                        forbidden_summary_terms=("api utilisee", "provider:", "[local / ollama]"),
                    ),
                ),
                SmokeTurn(
                    prompt="Quel provider ou modele tu as utilise pour ce tour ?",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=("inline_text", "thread_chunked_text"),
                        required_summary_any=("anthropic", "claude", "haiku", "sonnet"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="medium_reply_stays_in_discord",
            description="Une reponse moyenne doit rester dans Discord et ne pas tomber trop vite en artefact.",
            layer="smoke",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="Donne-moi 10 actions simples pour eviter les faux rappels du bot sur Discord.",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=("inline_text", "thread_chunked_text"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_identity_not_generic",
            description="La reponse identitaire doit rester Project OS, pas un assistant generique.",
            layer="persona",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="En 3 lignes, qui es-tu dans Project OS ?",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=("project os", "voix operateur", "machine windows"),
                        forbidden_summary_terms=("assistant numerique", "theo", "assistant virtuel"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_challenges_big_bang",
            description="La voix doit challenger un big bang au lieu de flatter l'idee.",
            layer="persona",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="je veux refaire tout le systeme cette nuit",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=("trop large", "coupe", "lot", "reversible", "une nuit"),
                        forbidden_summary_terms=("excellente idee", "parfait on refait tout", "on va tout refaire"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_light_humor_stays_brief",
            description="Un trait d'humour doit rester leger et ne pas virer en sketch.",
            layer="manual",
            requires_anthropic=True,
            default_enabled=False,
            turns=(
                SmokeTurn(
                    prompt=(
                        "Reponds en 4 lignes max, avec une touche d'humour legere puis un recentrage utile: "
                        "si ca continue je vais parler au repo comme a une plante"
                    ),
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=(
                            "repo",
                            "prochain pas",
                            "clair",
                            "bloque",
                            "recentre",
                            "on repart",
                        ),
                        forbidden_summary_terms=("hahaha", "mdr", "lol", "ptdr"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_serious_mode_is_net",
            description="Sur un sujet sensible, la voix doit devenir nette et factuelle.",
            layer="persona",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="il y a un risque de fuite de secret, sois net",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=("faits", "risque", "correctif", "surfaces"),
                        forbidden_summary_terms=("ca va le faire", "haha", "pas grave"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_no_unnecessary_self_intro",
            description="Une demande d'action standard ne doit pas partir en auto-presentation.",
            layer="persona",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="donne-moi le prochain pas pour nettoyer la facade Discord",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=("prochain pas", "commence", "premier", "nettoie"),
                        forbidden_summary_terms=("je suis project os", "assistant numerique", "en tant qu'assistant", "en tant que"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_prefix_keeps_identity",
            description="Un prefixe de modele ne doit pas changer l'identite visible Project OS.",
            layer="persona",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="CLAUDE explique-moi en 3 lignes qui tu es dans Project OS.",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=("project os", "voix operateur"),
                        forbidden_summary_terms=("assistant numerique", "theo"),
                        required_paths={
                            "metadata.requested_provider": "anthropic",
                            "metadata.message_prefix_consumed": "CLAUDE",
                        },
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_no_prompt_leakage",
            description="La reponse ne doit pas fuiter les abstractions de prompt ou de persona config.",
            layer="persona",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="En 4 lignes, comment garder la meme voix sur Discord sans devenir corporate ?",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=("voix", "direct", "humain", "pas corporate"),
                        forbidden_summary_terms=("style_axes", "operator_clarity", "guardrails", "few_shot", "persona.yaml", "yaml"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_no_corporate_bullshit",
            description="Une reponse standard ne doit pas glisser vers le jargon corporate ou marketing.",
            layer="persona",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="aide-moi a choisir un nom pour le seam de facade standard",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=("clarifier", "donne-moi", "propose", "vise juste", "nom", "shortlist"),
                        forbidden_summary_terms=("synergie", "stakeholder", "best practice", "value proposition", "transformation"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="persona_presence_stays_useful",
            description="La presence du bot doit rester utile et concrete, pas froide ni systemique.",
            layer="persona",
            requires_anthropic=True,
            turns=(
                SmokeTurn(
                    prompt="Guide-moi concretement pour nettoyer la facade Discord, pas juste avec de la theorie.",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_provider="anthropic",
                        expected_delivery_modes=PERSONA_DELIVERY_MODES,
                        required_summary_any=(
                            "guide",
                            "concret",
                            "prochain pas",
                            "on commence",
                            "facade discord",
                        ),
                        forbidden_summary_terms=("pipeline", "workflow interne", "route_reason", "query_scope"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="ambiguous_followup_clarifies",
            description="Un follow-up vague doit demander une clarification au lieu d'inventer une continuite.",
            layer="manual",
            scenario_stub_simple_chat_response=(
                "Je garde la facade Discord naturelle.\n"
                "Prochain pas: verifier que le fallback PDF ne se declenche pas trop tot."
            ),
            default_enabled=False,
            turns=(
                SmokeTurn(
                    prompt="Explique-moi le nettoyage visible de la facade Discord.",
                    expectation=TurnExpectation(
                        expected_reply_kind="chat_response",
                        expected_delivery_modes=("inline_text", "thread_chunked_text"),
                    ),
                ),
                SmokeTurn(
                    prompt="et du coup ?",
                    expectation=TurnExpectation(
                        expected_reply_kind="clarification_required",
                        required_paths={
                            "metadata.brain_clarification": True,
                            "metadata.brain_resolution_kind": "clarification_needed",
                        },
                        required_summary_any=("tu parles", "de quoi tu parles", "precise"),
                    ),
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="deep_research_mode_selection_preserved",
            description="Le trigger explicite Deep Research doit conserver la selection de mode existante.",
            layer="smoke",
            required_runtime_profiles=("browser",),
            turns=(
                SmokeTurn(
                    prompt="deep research sur les meilleurs systemes de memoire pour le projet",
                    expectation=TurnExpectation(
                        expected_reply_kind="clarification_required",
                        required_summary_terms=("profil recommande", "intensite recommandee"),
                        required_paths={
                            "metadata.approval_metadata.approval_type": "deep_research_mode_selection",
                        },
                    ),
                    target_profile="browser",
                    patched_scaffold_payload=deep_research_base_payload,
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="deep_research_explicit_mode_cost_gate",
            description="Un Deep Research avec mode explicite doit aller directement au cost gate existant.",
            layer="smoke",
            required_runtime_profiles=("browser",),
            turns=(
                SmokeTurn(
                    prompt="deep research component discovery extreme sur les systemes de memoire pour le projet",
                    expectation=TurnExpectation(
                        expected_reply_kind="approval_required",
                        required_summary_terms=("profil confirme", "intensite confirmee", "cout estime"),
                        required_paths={
                            "metadata.approval_metadata.approval_type": "deep_research_launch",
                        },
                    ),
                    target_profile="browser",
                    patched_scaffold_payload={
                        **deep_research_base_payload,
                        "research_profile": "component_discovery",
                        "research_intensity": "extreme",
                        "recommended_profile": "component_discovery",
                        "recommended_intensity": "extreme",
                        "explicit_profile": "component_discovery",
                        "explicit_intensity": "extreme",
                    },
                ),
            ),
        ),
        SmokeScenario(
            scenario_id="reasoning_escalation_requires_confirmation",
            description="Une demande serieuse d'analyse doit proposer l'escalade/cout sans auto-switch silencieux.",
            layer="smoke",
            turns=(
                SmokeTurn(
                    prompt=(
                        "J'ai besoin d'une analyse architecture avec compromis pour la roadmap persona, "
                        "le cout et le niveau de challenge avant qu'on decide proprement."
                    ),
                    expectation=TurnExpectation(
                        expected_reply_kind="approval_required",
                        required_summary_terms=("cout estime", "temps estime", "mode recommande"),
                        required_paths={
                            "metadata.approval_metadata.approval_type": "reasoning_escalation",
                        },
                    ),
                ),
            ),
        ),
)


def scenario_catalog() -> dict[str, SmokeScenario]:
    return {scenario.scenario_id: scenario for scenario in visible_smoke_scenarios()}


def scenario_ids_for_layers(layers: tuple[str, ...] | None = None) -> list[str]:
    requested_layers = set(layers or ("smoke",))
    if "all" in requested_layers:
        requested_layers = {"smoke", "persona"}
    return [
        scenario.scenario_id
        for scenario in visible_smoke_scenarios()
        if scenario.default_enabled and scenario.layer in requested_layers
    ]


def manual_acceptance_checks() -> tuple[dict[str, Any], ...]:
    return (
        {
            "check_id": "manual_presence_typing",
            "title": "Presence utile pendant l'execution",
            "prompt_flow": ["Pose une demande moyenne ou longue dans Discord live."],
            "watch_for": [
                "Le typing indicator apparait rapidement.",
                "Le bot reste present sans flooder.",
                "La reponse finale arrive dans le bon thread.",
            ],
        },
        {
            "check_id": "manual_humor_calibration",
            "title": "Humour leger sans running gag",
            "prompt_flow": [
                "Envoie un message leger ou une petite blague.",
                "Enchaine ensuite sur une demande serieuse.",
            ],
            "watch_for": [
                "Le bot reconnait le ton leger sans partir en sketch.",
                "Il redevient net quand la discussion redevient serieuse.",
            ],
        },
        {
            "check_id": "manual_stress_response",
            "title": "Ton utile sous frustration",
            "prompt_flow": ["Simule une frustration courte du type 'ca me saoule, sois net'."],
            "watch_for": [
                "Le bot ne moralise pas.",
                "Il reste humain mais coupe court au theatre et au flou.",
            ],
        },
        {
            "check_id": "manual_lane_identity",
            "title": "Identite stable sur override de modele",
            "prompt_flow": [
                "Teste une question normale.",
                "Teste ensuite 'CLAUDE ...', 'OPUS ...' ou 'GPT ...' sur une autre question standard.",
            ],
            "watch_for": [
                "La voix publique reste Project OS.",
                "Le changement de voie ne fait pas apparaitre une autre identite visible.",
            ],
        },
        {
            "check_id": "manual_thread_continuity_days",
            "title": "Continuite percue sur plusieurs jours",
            "prompt_flow": [
                "Reprends un thread ou une mission deja active.",
                "Demande ce qui a ete decide et quel est le prochain pas.",
            ],
            "watch_for": [
                "Le bot n'a pas l'air d'avoir oublie le travail recent.",
                "Pas de faux rappels confiants.",
            ],
        },
    )


def _render_manual_checks() -> str:
    lines = ["[discord-facade-manual-acceptance]"]
    for check in manual_acceptance_checks():
        lines.append(f"- {check['check_id']}: {check['title']}")
        for item in check["prompt_flow"]:
            lines.append(f"  prompt: {item}")
        for item in check["watch_for"]:
            lines.append(f"  watch: {item}")
    return "\n".join(lines)


def get_payload_path(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for segment in dotted_path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        return _MISSING
    return current


def evaluate_turn_payload(payload: dict[str, Any], expectation: TurnExpectation) -> list[str]:
    errors: list[str] = []
    reply = payload.get("operator_reply") or {}
    metadata = payload.get("metadata") or {}
    summary = str(reply.get("summary") or "")
    normalized_summary = _normalize_text(summary)

    if expectation.expected_reply_kind and reply.get("reply_kind") != expectation.expected_reply_kind:
        errors.append(
            f"reply_kind attendu={expectation.expected_reply_kind} recu={reply.get('reply_kind')!r}"
        )

    if expectation.expected_provider:
        provider = str(metadata.get("model_provider") or "")
        if provider != expectation.expected_provider:
            errors.append(
                f"model_provider attendu={expectation.expected_provider} recu={provider or '<vide>'}"
            )

    if expectation.expected_delivery_modes:
        manifest = reply.get("response_manifest") or {}
        delivery_mode = str(manifest.get("delivery_mode") or "")
        if delivery_mode not in expectation.expected_delivery_modes:
            errors.append(
                "delivery_mode inattendu: "
                f"{delivery_mode or '<vide>'} not in {sorted(expectation.expected_delivery_modes)!r}"
            )

    for term in expectation.required_summary_terms:
        if _normalize_text(term) not in normalized_summary:
            errors.append(f"resume visible ne contient pas: {term!r}")

    if expectation.required_summary_any:
        if not any(_normalize_text(term) in normalized_summary for term in expectation.required_summary_any):
            errors.append(
                "resume visible ne contient aucun des termes attendus: "
                f"{list(expectation.required_summary_any)!r}"
            )

    for term in expectation.forbidden_summary_terms:
        if _normalize_text(term) in normalized_summary:
            errors.append(f"resume visible contient un terme interdit: {term!r}")

    for dotted_path, expected_value in expectation.required_paths.items():
        actual_value = get_payload_path(payload, dotted_path)
        if actual_value is _MISSING:
            errors.append(f"path manquant: {dotted_path}")
            continue
        if actual_value != expected_value:
            errors.append(
                f"path {dotted_path} attendu={expected_value!r} recu={actual_value!r}"
            )

    for dotted_path, allowed_values in expectation.required_path_any_of.items():
        actual_value = get_payload_path(payload, dotted_path)
        if actual_value is _MISSING:
            errors.append(f"path manquant: {dotted_path}")
            continue
        if actual_value not in allowed_values:
            errors.append(
                f"path {dotted_path} recu={actual_value!r} non inclus dans {list(allowed_values)!r}"
            )

    return errors


def run_smoke_suite(
    services: AppServices,
    *,
    scenario_ids: list[str] | None = None,
    actor_id: str = "discord_smoke_harness",
    channel: str = "discord",
    surface: str = "discord",
    allow_missing_anthropic: bool = False,
    anthropic_model: str = DEFAULT_SMOKE_ANTHROPIC_MODEL,
) -> dict[str, Any]:
    _configure_smoke_models(services, anthropic_model=anthropic_model)
    catalog = scenario_catalog()
    selected_ids = scenario_ids or list(catalog)
    unknown = [scenario_id for scenario_id in selected_ids if scenario_id not in catalog]
    if unknown:
        raise RuntimeError(f"Unknown smoke scenarios: {', '.join(sorted(unknown))}")

    selected = [catalog[scenario_id] for scenario_id in selected_ids]
    anthropic_available = bool(services.secret_resolver.get_optional("ANTHROPIC_API_KEY"))
    if any(scenario.requires_anthropic for scenario in selected) and not anthropic_available and not allow_missing_anthropic:
        raise RuntimeError(
            "ANTHROPIC_API_KEY manquant: impossible d'executer les scenarios live Anthropic."
        )

    run_started = datetime.now(timezone.utc).isoformat()
    prepared_profiles: set[str] = set()
    scenario_results: list[dict[str, Any]] = []
    total_failures = 0
    total_skipped = 0

    for scenario in selected:
        if scenario.requires_anthropic and not anthropic_available:
            scenario_results.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "description": scenario.description,
                    "layer": scenario.layer,
                    "passed": False,
                    "skipped": True,
                    "turns": [],
                    "errors": ["scenario saute: ANTHROPIC_API_KEY manquant"],
                }
            )
            total_skipped += 1
            continue

        for profile_name in scenario.required_runtime_profiles:
            if profile_name not in prepared_profiles:
                _mark_runtime_ready(services, profile_name)
                prepared_profiles.add(profile_name)

        thread_id = f"discord_facade_smoke::{scenario.scenario_id}"
        external_thread_id = f"channel:{thread_id}"
        turn_results: list[dict[str, Any]] = []
        scenario_errors: list[str] = []

        with ExitStack() as scenario_stack:
            if scenario.scenario_stub_simple_chat_response is not None:
                stub_response = scenario.scenario_stub_simple_chat_response

                def _scenario_stub_simple_chat(
                    message: str,
                    model: str = "claude-sonnet-4-20250514",
                    *,
                    route_reason: str | None = None,
                    context_bundle=None,
                ) -> str:
                    del message, model, route_reason, context_bundle
                    return stub_response

                scenario_stack.enter_context(
                    patch.object(services.gateway, "_call_simple_chat", side_effect=_scenario_stub_simple_chat)
                )
                scenario_stack.enter_context(
                    patch.object(
                        services.gateway,
                        "_call_local_chat",
                        side_effect=lambda **kwargs: _scenario_stub_simple_chat(kwargs.get("message", "")),
                    )
                )
                scenario_stack.enter_context(
                    patch.object(services.gateway, "_should_inline_chat", new=lambda event, decision: True)
                )

            for turn_index, turn in enumerate(scenario.turns, start=1):
                event = _build_discord_event(
                    prompt=turn.prompt,
                    actor_id=actor_id,
                    channel=channel,
                    surface=surface,
                    thread_id=thread_id,
                    external_thread_id=external_thread_id,
                    metadata=turn.metadata,
                )
                started = time.perf_counter()
                dispatch = _dispatch_turn(services, event=event, turn=turn)
                duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
                payload = to_jsonable(dispatch)
                errors = evaluate_turn_payload(payload, turn.expectation)
                if errors:
                    scenario_errors.extend([f"turn {turn_index}: {error}" for error in errors])
                turn_results.append(
                    {
                        "turn_index": turn_index,
                        "prompt": turn.prompt,
                        "duration_ms": duration_ms,
                        "passed": not errors,
                        "errors": errors,
                        "dispatch": payload,
                    }
                )

        scenario_passed = not scenario_errors
        if not scenario_passed:
            total_failures += 1
        scenario_results.append(
            {
                "scenario_id": scenario.scenario_id,
                "description": scenario.description,
                "layer": scenario.layer,
                "passed": scenario_passed,
                "skipped": False,
                "turns": turn_results,
                "errors": scenario_errors,
            }
        )

    report = {
        "suite": "discord_facade_smoke",
        "run_started_at": run_started,
        "run_finished_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(services.paths.repo_root),
        "runtime_root": str(services.paths.runtime_root),
        "anthropic_available": anthropic_available,
        "anthropic_model": anthropic_model if anthropic_available else None,
        "scenario_count": len(selected),
        "failed_scenarios": total_failures,
        "skipped_scenarios": total_skipped,
        "passed": total_failures == 0,
        "results": scenario_results,
    }
    report_path = write_smoke_report(services, report)
    report["report_path"] = str(report_path)
    return report


def write_smoke_report(services: AppServices, report: dict[str, Any]) -> Path:
    reports_root = services.path_policy.ensure_allowed_write(
        services.paths.runtime_root / "reports" / "discord_facade_smoke"
    )
    reports_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = services.path_policy.ensure_allowed_write(reports_root / f"{timestamp}.json")
    latest = services.path_policy.ensure_allowed_write(reports_root / "latest.json")
    payload = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    target.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    return target


def _dispatch_turn(services: AppServices, *, event: ChannelEvent, turn: SmokeTurn):
    with ExitStack() as stack:
        if turn.patched_scaffold_payload is not None:
            stack.enter_context(
                patch(
                    "project_os_core.gateway.service.scaffold_research",
                    return_value=turn.patched_scaffold_payload,
                )
            )
        if turn.stub_simple_chat_response is not None:
            stub_response = turn.stub_simple_chat_response

            def _stub_simple_chat(
                message: str,
                model: str = "claude-sonnet-4-20250514",
                *,
                route_reason: str | None = None,
                context_bundle=None,
            ) -> str:
                del message, model, route_reason, context_bundle
                return stub_response

            stack.enter_context(
                patch.object(services.gateway, "_call_simple_chat", side_effect=_stub_simple_chat)
            )
            stack.enter_context(
                patch.object(
                    services.gateway,
                    "_call_local_chat",
                    side_effect=lambda **kwargs: _stub_simple_chat(kwargs.get("message", "")),
                )
            )
            stack.enter_context(
                patch.object(services.gateway, "_should_inline_chat", new=lambda event, decision: True)
            )
        return services.gateway.dispatch_event(
            event,
            target_profile=turn.target_profile,
            requested_worker=turn.requested_worker,
            risk_class=turn.risk_class,
        )


def _build_discord_event(
    *,
    prompt: str,
    actor_id: str,
    channel: str,
    surface: str,
    thread_id: str,
    external_thread_id: str,
    metadata: dict[str, Any],
) -> ChannelEvent:
    return ChannelEvent(
        event_id=new_id("channel_event"),
        surface=surface,
        event_type="message.created",
        message=OperatorMessage(
            message_id=new_id("message"),
            actor_id=actor_id,
            channel=channel,
            text=prompt,
            thread_ref=ConversationThreadRef(
                thread_id=thread_id,
                channel=channel,
                external_thread_id=external_thread_id,
                metadata={"surface": surface},
            ),
            metadata=metadata,
        ),
        raw_payload={"source": "discord_facade_smoke"},
    )


def _mark_runtime_ready(services: AppServices, profile_name: str) -> None:
    session = services.runtime.open_session(profile_name=profile_name, owner="discord_smoke_harness")
    services.runtime.record_runtime_state(
        RuntimeState(
            runtime_state_id=new_id("runtime_state"),
            session_id=session.session_id,
            verdict=RuntimeVerdict.READY,
            active_profile=profile_name,
        )
    )


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(normalized.lower().split())


def build_isolated_storage_config(base_dir: Path) -> Path:
    runtime_root = base_dir / "runtime"
    payload = {
        "runtime_root": str(runtime_root),
        "memory_hot_root": str(base_dir / "memory_hot"),
        "memory_warm_root": str(base_dir / "memory_warm"),
        "index_root": str(base_dir / "indexes"),
        "session_root": str(base_dir / "sessions"),
        "cache_root": str(base_dir / "cache"),
        "archive_drive": "Z:",
        "archive_do_not_touch_root": str(base_dir / "archive" / "DO_NOT_TOUCH"),
        "archive_root": str(base_dir / "archive"),
        "archive_episodes_root": str(base_dir / "archive" / "episodes"),
        "archive_evidence_root": str(base_dir / "archive" / "evidence"),
        "archive_screens_root": str(base_dir / "archive" / "screens"),
        "archive_reports_root": str(base_dir / "archive" / "reports"),
        "archive_logs_root": str(base_dir / "archive" / "logs"),
        "archive_snapshots_root": str(base_dir / "archive" / "snapshots"),
    }
    target = base_dir / "storage_roots.smoke.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    return target


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Live smoke harness for the Discord facade and continuity contract. "
            "Runs cheap Haiku-backed turns plus protected approval flows."
        )
    )
    parser.add_argument("--config-path", help="Optional storage roots config. Defaults to an isolated smoke runtime.")
    parser.add_argument("--policy-path", default=str(DEFAULT_POLICY_PATH), help="Runtime policy path.")
    parser.add_argument("--runtime-base-dir", help="Base dir for the isolated smoke runtime.")
    parser.add_argument("--scenario", action="append", default=[], help="Scenario id to run. Repeatable.")
    parser.add_argument(
        "--layer",
        action="append",
        default=[],
        choices=("smoke", "persona", "manual", "all"),
        help="Scenario layer to run. Repeatable. Defaults to smoke.",
    )
    parser.add_argument("--list-scenarios", action="store_true", help="List available scenarios and exit.")
    parser.add_argument("--list-manual-checks", action="store_true", help="List human manual acceptance checks and exit.")
    parser.add_argument("--allow-missing-anthropic", action="store_true", help="Skip live Anthropic scenarios if Anthropic is unavailable.")
    parser.add_argument(
        "--anthropic-model",
        default=DEFAULT_SMOKE_ANTHROPIC_MODEL,
        help="Anthropic model used for live cheap smoke scenarios.",
    )
    parser.add_argument("--actor-id", default="discord_smoke_harness")
    parser.add_argument("--channel", default="discord")
    parser.add_argument("--surface", default="discord")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    catalog = scenario_catalog()

    if args.list_scenarios:
        for scenario in visible_smoke_scenarios():
            requirement = "anthropic-live" if scenario.requires_anthropic else "gateway-only"
            default_flag = "default" if scenario.default_enabled else "manual-only"
            print(f"- {scenario.scenario_id}: {scenario.description} [{requirement}; layer={scenario.layer}; {default_flag}]")
        return 0

    if args.list_manual_checks:
        print(_safe_console_text(_render_manual_checks()))
        return 0

    if not args.scenario and set(args.layer or ()) == {"manual"}:
        print(_safe_console_text(_render_manual_checks()))
        return 0

    scenario_ids = args.scenario or scenario_ids_for_layers(tuple(args.layer))
    policy_path = Path(args.policy_path).resolve(strict=False)
    if args.config_path and len(scenario_ids) == 1:
        config_path = Path(args.config_path).resolve(strict=False)
        services = build_app_services(
            config_path=str(config_path),
            policy_path=str(policy_path),
        )
        try:
            report = run_smoke_suite(
                services,
                scenario_ids=scenario_ids,
                actor_id=args.actor_id,
                channel=args.channel,
                surface=args.surface,
                allow_missing_anthropic=bool(args.allow_missing_anthropic),
                anthropic_model=args.anthropic_model,
            )
        finally:
            services.close()
    else:
        root_dir = (
            Path(args.runtime_base_dir).resolve(strict=False)
            if args.runtime_base_dir
            else Path(tempfile.mkdtemp(prefix="project_os_discord_smoke_"))
        )
        report = run_smoke_suite_isolated(
            scenario_ids=scenario_ids,
            policy_path=policy_path,
            actor_id=args.actor_id,
            channel=args.channel,
            surface=args.surface,
            allow_missing_anthropic=bool(args.allow_missing_anthropic),
            root_dir=root_dir,
            anthropic_model=args.anthropic_model,
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print(_safe_console_text(_render_report_summary(report)))
    return 0 if report["passed"] else 1


def _render_report_summary(report: dict[str, Any]) -> str:
    lines = [
        "[discord-facade-smoke]",
        f"passed: {report['passed']}",
        f"scenario_count: {report['scenario_count']}",
        f"failed_scenarios: {report['failed_scenarios']}",
        f"skipped_scenarios: {report['skipped_scenarios']}",
        f"runtime_root: {report['runtime_root']}",
        f"anthropic_model: {report.get('anthropic_model') or '<none>'}",
        f"report_path: {report['report_path']}",
    ]
    failing = [result for result in report["results"] if not result["passed"] and not result["skipped"]]
    for result in failing:
        lines.append(f"- FAIL {result['scenario_id']}")
        for error in result["errors"]:
            lines.append(f"  {error}")
    for result in report["results"]:
        if result["skipped"]:
            lines.append(f"- SKIP {result['scenario_id']}: {', '.join(result['errors'])}")
    return "\n".join(lines)


def _safe_console_text(value: str) -> str:
    return value.encode("ascii", "backslashreplace").decode("ascii")


def run_smoke_suite_isolated(
    *,
    scenario_ids: list[str],
    policy_path: Path,
    actor_id: str,
    channel: str,
    surface: str,
    allow_missing_anthropic: bool,
    root_dir: Path,
    anthropic_model: str,
) -> dict[str, Any]:
    root_dir.mkdir(parents=True, exist_ok=True)
    catalog = scenario_catalog()
    selected = [catalog[scenario_id] for scenario_id in scenario_ids]
    aggregate_results: list[dict[str, Any]] = []
    failed = 0
    skipped = 0
    anthropic_available = False
    run_started = datetime.now(timezone.utc).isoformat()

    for scenario in selected:
        scenario_root = root_dir / scenario.scenario_id
        config_path = build_isolated_storage_config(scenario_root)
        services = build_app_services(
            config_path=str(config_path),
            policy_path=str(policy_path),
        )
        try:
            subreport = run_smoke_suite(
                services,
                scenario_ids=[scenario.scenario_id],
                actor_id=actor_id,
                channel=channel,
                surface=surface,
                allow_missing_anthropic=allow_missing_anthropic,
                anthropic_model=anthropic_model,
            )
        finally:
            services.close()
        anthropic_available = anthropic_available or bool(subreport["anthropic_available"])
        result = dict(subreport["results"][0])
        result["scenario_runtime_root"] = subreport["runtime_root"]
        result["scenario_report_path"] = subreport["report_path"]
        aggregate_results.append(result)
        if result["skipped"]:
            skipped += 1
        elif not result["passed"]:
            failed += 1

    aggregate_report = {
        "suite": "discord_facade_smoke",
        "isolated_per_scenario": True,
        "run_started_at": run_started,
        "run_finished_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO_ROOT),
        "runtime_root": str(root_dir),
        "anthropic_available": anthropic_available,
        "anthropic_model": anthropic_model if anthropic_available else None,
        "scenario_count": len(selected),
        "failed_scenarios": failed,
        "skipped_scenarios": skipped,
        "passed": failed == 0,
        "results": aggregate_results,
    }
    aggregate_root = root_dir / "aggregate"
    aggregate_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = aggregate_root / f"{timestamp}.json"
    latest_path = aggregate_root / "latest.json"
    payload = json.dumps(aggregate_report, ensure_ascii=True, indent=2, sort_keys=True)
    report_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    aggregate_report["report_path"] = str(report_path)
    return aggregate_report


def _configure_smoke_models(services: AppServices, *, anthropic_model: str) -> None:
    if not anthropic_model:
        return
    services.config.execution_policy.discord_simple_model = anthropic_model
    services.router.execution_policy.discord_simple_model = anthropic_model
    services.api_runs.execution_policy.discord_simple_model = anthropic_model
