from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from project_os_core.services import build_app_services


def _build_services(tmp_path: Path):
    storage_payload = {
        "runtime_root": str(tmp_path / "runtime"),
        "memory_hot_root": str(tmp_path / "memory_hot"),
        "memory_warm_root": str(tmp_path / "memory_warm"),
        "index_root": str(tmp_path / "indexes"),
        "session_root": str(tmp_path / "sessions"),
        "cache_root": str(tmp_path / "cache"),
        "archive_drive": "Z:",
        "archive_do_not_touch_root": str(tmp_path / "archive" / "DO_NOT_TOUCH"),
        "archive_root": str(tmp_path / "archive"),
        "archive_episodes_root": str(tmp_path / "archive" / "episodes"),
        "archive_evidence_root": str(tmp_path / "archive" / "evidence"),
        "archive_screens_root": str(tmp_path / "archive" / "screens"),
        "archive_reports_root": str(tmp_path / "archive" / "reports"),
        "archive_logs_root": str(tmp_path / "archive" / "logs"),
        "archive_snapshots_root": str(tmp_path / "archive" / "snapshots"),
    }
    config_path = tmp_path / "storage_roots.json"
    config_path.write_text(json.dumps(storage_payload), encoding="utf-8")

    policy_payload = {
        "secret_config": {
            "mode": "infisical_first",
            "required_secret_names": ["OPENAI_API_KEY"],
            "local_fallback_path": str(tmp_path / "secrets.json"),
        },
        "embedding_policy": {
            "provider_mode": "local_hash",
            "quality": "balanced",
            "local_model": "local-hash-v1",
            "local_dimensions": 64,
        },
    }
    policy_path = tmp_path / "runtime_policy.json"
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
    services = build_app_services(config_path=str(config_path), policy_path=str(policy_path))
    services.secret_resolver.write_local_fallback("OPENAI_API_KEY", "sk-test-secret")
    services.secret_resolver.write_local_fallback("ANTHROPIC_API_KEY", "sk-ant-test")
    return services


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _planner_payload() -> dict[str, object]:
    return {
        "mission": "Produce a grounded deep research dossier.",
        "why_this_mode": ["Multiple evidence lanes are required for the selected intensity."],
        "angles": ["repo_fit", "external_leverage", "proofs"],
        "required_lanes": ["repo", "official_docs", "github"],
        "optional_lanes": ["papers"],
        "parallel_groups": [["official_docs", "github"]],
        "must_prove": ["Why the recommendation matters for Project OS."],
        "must_refute": ["Refactor-only advice without external leverage."],
        "lane_priority": ["official_docs", "github", "repo", "papers"],
        "needs_papers": False,
        "needs_github_depth": True,
        "avoid": ["Generic best practices."],
        "scout_focus": ["official_docs", "github"],
    }


def _complex_scout_bundle() -> dict[str, object]:
    return {
        "repo": {
            "lane": "repo",
            "summary": "Repo context lane.",
            "key_findings": ["`memory` and `learning` are already present."],
            "candidate_systems": ["memory", "learning"],
            "sources": [
                {
                    "title": "docs/workflow/DEEP_RESEARCH_PROTOCOL.md",
                    "url": "",
                    "publisher": "local_repo",
                    "published_at": "local",
                    "why": "Local protocol reference.",
                }
            ],
            "warnings": [],
        },
        "official_docs": {
            "lane": "official_docs",
            "summary": "Official documentation lane.",
            "key_findings": ["Primary docs support typed memory patterns."],
            "candidate_systems": ["typed memory"],
            "sources": [
                {
                    "title": "Official Memory Docs",
                    "url": "https://openai.com/index/introducing-deep-research/",
                    "publisher": "OpenAI",
                    "published_at": "2025-02-02",
                    "why": "Primary workflow reference.",
                }
            ],
            "warnings": [],
        },
        "github": {
            "lane": "github",
            "summary": "GitHub ecosystem lane.",
            "key_findings": ["One repo is worth adapting, not importing wholesale."],
            "candidate_systems": ["typed memory runtime"],
            "sources": [
                {
                    "title": "Example Memory Repo",
                    "url": "https://github.com/example/memory",
                    "publisher": "GitHub",
                    "published_at": "2026-03-10",
                    "why": "GitHub signal for typed memory runtime.",
                }
            ],
            "warnings": [],
        },
    }


def _extreme_scout_bundle() -> dict[str, object]:
    bundle = _complex_scout_bundle()
    bundle["papers"] = {
        "lane": "papers",
        "summary": "Papers and benchmarks lane.",
        "key_findings": ["Benchmarks support stronger verifier gates and agent boundaries."],
        "candidate_systems": ["verifier gate"],
        "sources": [
            {
                "title": "Agent Systems Paper",
                "url": "https://arxiv.org/abs/2501.00001",
                "publisher": "arXiv",
                "published_at": "2025-01-02",
                "why": "Supports multi-agent system framing.",
            }
        ],
        "warnings": [],
    }
    return bundle


def _skeptic_payload() -> dict[str, object]:
    return {
        "risks": ["Do not confuse local hardening with strategic leverage."],
        "contradictions": [],
        "weak_points": ["One recommendation still needs proof."],
        "corrections": ["Keep external leverage explicit in the final report."],
    }


def _cheap_swarm_payload() -> dict[str, object]:
    return {
        "mission": "Widen discovery before the expert synthesis.",
        "broad_signals": [
            "Official documentation and strong GitHub satellites should dominate the evidence mix.",
            "Papers should only survive if they add a real systems angle.",
        ],
        "lane_briefs": [
            {
                "lane": "official_docs",
                "query_focus": ["official APIs", "official standards", "product docs"],
                "must_prove": ["What changes current public practice."],
                "seed_sources": [
                    {
                        "title": "Official Docs Seed",
                        "url": "https://openai.com/index/new-tools-and-features-in-the-responses-api/",
                        "publisher": "OpenAI",
                        "published_at": "2025-03-11",
                        "why": "Primary source for the active API path.",
                    }
                ],
                "avoid": ["Do not treat mirrors as primary evidence."],
            },
            {
                "lane": "github",
                "query_focus": ["forks", "satellites", "wrappers"],
                "must_prove": ["What to steal, not just what is popular."],
                "seed_sources": [
                    {
                        "title": "GitHub Seed",
                        "url": "https://github.com/example/verifier",
                        "publisher": "GitHub",
                        "published_at": "2026-03-10",
                        "why": "Seed repo for verifier patterns.",
                    }
                ],
                "avoid": ["Do not keep dead forks."],
            },
            {
                "lane": "papers",
                "query_focus": ["benchmarks", "agent patterns"],
                "must_prove": ["What actually changes system design."],
                "seed_sources": [
                    {
                        "title": "Paper Seed",
                        "url": "https://arxiv.org/abs/2501.00001",
                        "publisher": "arXiv",
                        "published_at": "2025-01-02",
                        "why": "Seed paper for agent-system framing.",
                    }
                ],
                "avoid": ["Do not keep benchmark-only hype."],
            },
        ],
        "watchouts": ["Small blogs and mirrors should stay weak signals unless corroborated."],
    }


def _research_model_stub(services, structured: dict[str, object], response_id: str, usage: dict[str, int] | None = None):
    def _side_effect(*, response_continuity=None, continuity_anchor=None, **_: object):
        if isinstance(response_continuity, dict) and response_continuity.get("enabled"):
            services.deep_research._record_response_continuity(
                response_continuity=response_continuity,
                anchor=str(continuity_anchor or "final_synthesis"),
                phase=str(continuity_anchor or "final_synthesis"),
                model="gpt-5",
                response_id=response_id,
                previous_response_id=None,
                stored=True,
            )
        return structured, {"response_id": response_id}, usage or {"input_tokens": 1200, "output_tokens": 800}

    return _side_effect


def test_deep_research_run_job_request_writes_dossier_and_enqueues_delivery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        services = _build_services(tmp_path)
        try:
            repo_root = tmp_path / "repo"
            _write(repo_root / "AGENTS.md", "# Agents\n")
            _write(repo_root / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md", "# Deep Research\n")
            _write(repo_root / "docs" / "workflow" / "ROADMAP_AUTHORING_STANDARD.md", "# Roadmap\n")
            _write(repo_root / "docs" / "systems" / "README.md", "# Systems\n")
            _write(repo_root / "src" / "project_os_core" / "memory" / "__init__.py", "")
            _write(repo_root / "src" / "project_os_core" / "learning" / "__init__.py", "")
            dossier_path = repo_root / "docs" / "systems" / "MEMORY_SYSTEMS_DOSSIER.md"
            _write(dossier_path, "# Memory Systems\n\n## Statut\n\n- `draft`\n")

            services.deep_research.repo_root = repo_root

            job_root = services.path_policy.ensure_allowed_write(services.paths.runtime_root / "deep_research" / "job_test")
            job_root.mkdir(parents=True, exist_ok=True)
            request = {
                "job_id": "deep_research_job_test",
                "title": "Memory Systems",
                "kind": "system",
                "research_profile": "component_discovery",
                "research_intensity": "complex",
                "question": "Deep research sur les meilleurs systemes de memoire pour Project OS.",
                "recent_days": 30,
                "dossier_path": str(dossier_path),
                "dossier_relative_path": "docs/systems/MEMORY_SYSTEMS_DOSSIER.md",
                "doc_name": "MEMORY_SYSTEMS_DOSSIER.md",
                "reply_target": "channel:123456",
                "reply_to": "discord-message-1",
                "seo_slug": "memory-systems",
                "archive_stem": "2026-03-16-memory-systems-system-dossier",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
            structured = {
                "research_profile": "component_discovery",
                "research_intensity": "complex",
                "seo_title": "Memory Systems 2026 - typed memory, workflow memory and Project OS fit",
                "summary": "Prioritize typed memory and workflows promoted from accepted runs.",
                "why_now": ["The repo already has `memory` and `learning`, but no durable comparison dossier."],
                "repo_fit": ["The main touchpoints are `memory`, `learning`, and `docs/workflow`."],
                "priority_actions": [
                    "Audit a typed-memory bridge inside `memory`.",
                    "Define a workflow-promotion test inside `learning`.",
                ],
                "component_discovery_block": {
                    "blind_spots": [
                        "Project OS is still underweighting typed procedural memory compared with stronger public stacks.",
                    ],
                    "external_leverage": [
                        "Typed memory runtimes and workflow memory patterns can shorten design loops.",
                    ],
                    "underbuilt_layers": [
                        "No canonical typed-memory dossier or structured workflow promotion contract exists yet.",
                    ],
                    "priority_ladder": {
                        "highest_leverage_now": [
                            "Audit a typed-memory bridge inside `memory`.",
                            "Define a workflow-promotion test inside `learning`.",
                        ],
                        "major_system_next": [
                            "Compare typed-memory candidates against workflow-promotion behavior.",
                        ],
                        "watch_and_prepare": [
                            "Track stronger fork or satellite signals before importing heavy dependencies.",
                        ],
                    },
                    "observed_runtime_issues": [
                        "No runtime issue was observed in this synthetic unit scenario.",
                    ],
                    "stop_doing_or_deprioritize": [
                        "Do not keep expanding prose-only memory docs without executable proofs.",
                    ],
                    "success_metrics": [
                        "At least one workflow promotion test passes in `learning`.",
                    ],
                },
                "recommendations": [
                    {
                        "bucket": "a_faire",
                        "system_name": "Typed Memory Runtime",
                        "decision": "ADAPT",
                        "goal_link": ["memory", "evals"],
                        "roi": ["Make procedural memory reusable by verifiers and future managers."],
                        "sequence_role": "highest_leverage_now",
                        "scope_level": "memory",
                        "evidence_basis": ["repo", "web"],
                        "blind_spot_addressed": "Project OS has not yet turned memory into a typed operational substrate.",
                        "why": ["The pattern fits the current repo state."],
                        "what_to_take": ["A `profile/behavior/skill/event/task` memory taxonomy."],
                        "what_not_to_take": ["Do not import a second canonical runtime."],
                        "fork_signal": ["No visible fork clearly beats the upstream GitHub repo; keep the idea, not the whole package."],
                        "project_os_touchpoints": ["`memory`", "`learning`", "`docs/systems`"],
                        "proofs": ["Write a workflow promotion test for procedural memory."],
                        "sources": [
                            {
                                "title": "Memory Source",
                                "url": "https://github.com/example/memory",
                                "publisher": "Example",
                                "published_at": "2026-03-10",
                                "why": "Conceptual basis for typed memory.",
                            }
                        ],
                    },
                    {
                        "bucket": "a_etudier",
                        "system_name": "Workflow Memory",
                        "decision": "DEFER",
                        "goal_link": ["memory", "evals"],
                        "roi": ["Improve reuse once typed memory and evals are both stable."],
                        "sequence_role": "major_system_next",
                        "scope_level": "platform",
                        "evidence_basis": ["repo", "web"],
                        "blind_spot_addressed": "Workflow reuse is still implicit and weakly benchmarked.",
                        "why": ["Relevant, but best tested after the typed-memory layer."],
                        "what_to_take": ["Promotion of accepted runs into workflow memory."],
                        "what_not_to_take": ["No heavy dependency before evals are in place."],
                        "fork_signal": ["Interesting GitHub satellites exist, but nothing to take as-is."],
                        "project_os_touchpoints": ["`learning`", "`mission`"],
                        "proofs": ["Compare two runs before and after workflow promotion."],
                        "sources": [
                            {
                                "title": "Workflow Source",
                                "url": "https://github.com/example/workflow",
                                "publisher": "Example",
                                "published_at": "2026-03-12",
                                "why": "Supports workflow promotion.",
                            }
                        ],
                    },
                ],
                "risks": ["Watch for duplication between memory and the documentation dossier."],
                "open_questions": ["Which verifier will use the new records?"],
                "global_sources": [
                    {
                        "title": "Global Source",
                        "url": "https://example.com/global",
                        "publisher": "Example",
                        "published_at": "2026-03-15",
                        "why": "Global view of memory systems.",
                    }
                ],
                "metadata": {"model": "gpt-5", "tool_type": "web_search"},
            }
            reader_structured = {
                **structured,
                "seo_title": "Systemes de memoire 2026 - memoire typee, workflow memory et fit Project OS",
                "summary": "Prioriser une memoire typee et des workflows promus depuis les runs acceptes.",
                "why_now": ["Le repo a deja `memory` et `learning`, mais pas de dossier comparatif durable."],
                "repo_fit": ["Les principaux touchpoints sont `memory`, `learning` et `docs/workflow`."],
                "priority_actions": [
                    "Auditer un bridge typed memory dans `memory`.",
                    "Definir un test de promotion workflow dans `learning`.",
                ],
                "recommendations": [
                    {
                        **structured["recommendations"][0],
                        "why": ["Le pattern colle a l'etat actuel du repo."],
                        "what_to_take": ["Une typologie `profile/behavior/skill/event/task`."],
                        "what_not_to_take": ["Ne pas importer un second runtime canonique."],
                        "fork_signal": ["Aucun fork visible ne bat clairement l'upstream ; garder l'idee, pas le package entier."],
                        "proofs": ["Ecrire un test de promotion de workflow en memoire procedurale."],
                        "sources": [
                            {
                                **structured["recommendations"][0]["sources"][0],
                                "why": "Base conceptuelle pour la memoire typee.",
                            }
                        ],
                    },
                    {
                        **structured["recommendations"][1],
                        "why": ["Pertinent, mais a tester apres la couche typed memory."],
                        "what_to_take": ["La promotion des runs acceptes en workflow memory."],
                        "what_not_to_take": ["Pas de dependance lourde tant que les evals ne sont pas posees."],
                        "fork_signal": ["Satellites interessants, mais rien a reprendre tel quel."],
                        "proofs": ["Comparer deux runs avant/apres promotion workflow."],
                        "sources": [
                            {
                                **structured["recommendations"][1]["sources"][0],
                                "why": "Supporte la promotion de workflows.",
                            }
                        ],
                    },
                ],
                "risks": ["Attention a la duplication entre memoire et dossier doc."],
                "open_questions": ["Quel verifier utilisera les nouveaux records ?"],
                "global_sources": [
                    {
                        **structured["global_sources"][0],
                        "why": "Vue globale des systemes memoire.",
                    }
                ],
            }

            with patch.object(
                services.deep_research,
                "_call_research_model",
                side_effect=_research_model_stub(
                    services,
                    structured,
                    "resp_123",
                    {"input_tokens": 1200, "output_tokens": 800},
                ),
            ), patch.object(
                services.deep_research,
                "_run_planner_pass",
                return_value=_planner_payload(),
            ), patch.object(
                services.deep_research,
                "_run_scout_bundle",
                return_value=(_complex_scout_bundle(), []),
            ), patch.object(
                services.deep_research,
                "_run_skeptic_pass",
                return_value=_skeptic_payload(),
            ), patch.object(
                services.deep_research,
                "_translate_structured_for_reader",
                return_value=reader_structured,
            ):
                payload = services.deep_research.run_job_request(request=request, job_root=job_root)

            assert payload["status"] == "completed"
            assert dossier_path.exists()
            content = dossier_path.read_text(encoding="utf-8")
            assert "# Memory Systems 2026 - typed memory, workflow memory and Project OS fit" in content
            assert "## Blind Spots" in content
            assert "## External Leverage" in content
            assert "## Stop Doing or Deprioritize" in content
            assert "## Recommendations" in content
            assert "Typed Memory Runtime" in content
            assert "## Sources" in content
            assert "research_profile: `component_discovery`" in content
            assert "research_intensity: `complex`" in content

            deliveries = services.api_runs.list_operator_deliveries(limit=10)["deliveries"]
            assert len(deliveries) == 1
            delivery = deliveries[0]
            assert delivery["payload"]["target"] == "channel:123456"
            assert delivery["payload"]["reply_to"] == "discord-message-1"
            manifest = delivery["payload"]["response_manifest"]
            assert manifest["delivery_mode"] == "direct_attachment"
            assert manifest["attachments"][0]["mime_type"] == "application/pdf"
            assert manifest["attachments"][1]["path"] == str(dossier_path)

            pdf_path = Path(payload["pdf_path"])
            assert pdf_path.exists()
            assert pdf_path.read_bytes().startswith(b"%PDF")
            archive_root = Path(payload["archive_root"])
            assert archive_root.exists()
            assert "memory-systems-2026-typed-memory-workflow-memory-and-project-os-fit-system-dossier" in archive_root.name
            archive_manifest = json.loads((archive_root / "manifest.json").read_text(encoding="utf-8"))
            assert archive_manifest["seo_slug"] == "memory-systems-2026-typed-memory-workflow-memory-and-project-os-fit"
            assert archive_manifest["repo_dossier_path"] == str(dossier_path)
            assert archive_manifest["research_profile"] == "component_discovery"
            assert archive_manifest["research_intensity"] == "complex"
            assert archive_manifest["reader_language"] == "fr"
            assert archive_manifest["canonical_language"] == "en"

            status_payload = json.loads((job_root / "status.json").read_text(encoding="utf-8"))
            assert status_payload["status"] == "completed"
            assert status_payload["research_profile"] == "component_discovery"
            assert status_payload["research_intensity"] == "complex"
            assert status_payload["pdf_path"] == str(pdf_path)
        finally:
            services.close()


def test_deep_research_project_audit_renders_strategic_sections() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        services = _build_services(tmp_path)
        try:
            repo_root = tmp_path / "repo"
            _write(repo_root / "AGENTS.md", "# Agents\n")
            _write(repo_root / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md", "# Deep Research\n")
            _write(repo_root / "docs" / "roadmap" / "BUILD_STATUS_CHECKLIST.md", "# Checklist\n")
            _write(repo_root / "src" / "project_os_core" / "gateway" / "__init__.py", "")
            _write(repo_root / "src" / "project_os_core" / "mission" / "__init__.py", "")
            dossier_path = repo_root / "docs" / "audits" / "PROJECT_OS_STRATEGIC_AUDIT_AUDIT_2026-03-16.md"
            _write(dossier_path, "# Project OS Strategic Audit\n\n## Status\n\n- `draft`\n")
            services.deep_research.repo_root = repo_root

            job_root = services.path_policy.ensure_allowed_write(services.paths.runtime_root / "deep_research" / "job_project_audit")
            job_root.mkdir(parents=True, exist_ok=True)
            request = {
                "job_id": "deep_research_project_audit",
                "title": "Project OS Strategic Audit",
                "kind": "audit",
                "research_profile": "project_audit",
                "research_intensity": "extreme",
                "question": "Deep research pour un audit de mon projet de ce qu'on pourrait ameliorer.",
                "recent_days": 30,
                "dossier_path": str(dossier_path),
                "dossier_relative_path": "docs/audits/PROJECT_OS_STRATEGIC_AUDIT_AUDIT_2026-03-16.md",
                "doc_name": "PROJECT_OS_STRATEGIC_AUDIT_AUDIT_2026-03-16.md",
                "reply_target": "channel:9999",
                "reply_to": "discord-message-project",
                "seo_slug": "project-os-strategic-audit",
                "archive_stem": "2026-03-16-project-os-strategic-audit-deep-research-audit",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
            structured = {
                "research_profile": "project_audit",
                "research_intensity": "extreme",
                "seo_title": "Project OS 2026 - strategic audit for master-agent autonomy",
                "summary": "Re-rank the roadmap around the master agent, manager agents, and execution surfaces.",
                "priority_actions": [
                    "Stabilize verification between router and execution.",
                ],
                "project_audit_block": {
                    "north_star": "Build a master agent that supervises manager agents across local surfaces with bounded autonomy.",
                    "system_thesis": [
                        "Project OS should become a control plane, not only a gateway plus chat runtime.",
                    ],
                    "platform_layers": [
                        "Master-agent orchestration",
                        "Manager-agent contracts",
                        "Execution surfaces",
                    ],
                    "capability_gaps": [
                        "No canonical verifier gate spans all execution lanes.",
                        "Manager-agent hierarchy is still implicit.",
                        "Execution surfaces remain fragmented.",
                    ],
                    "priority_ladder": {
                        "foundational_now": [
                            "Install a canonical verifier gate before every autonomous execution path.",
                        ],
                        "system_next": [
                            "Define manager-agent contracts and routing boundaries.",
                        ],
                        "expansion_later": [
                            "Expand execution surfaces into desktop, browser, and VM operators.",
                        ],
                    },
                    "observed_runtime_issues": [
                        "Discord delivery duplication proves the operator path is still not fully idempotent.",
                    ],
                    "success_metrics": [
                        "Every autonomous action passes through one verifier gate.",
                        "Manager-agent contracts are represented in canonical docs and runtime payloads.",
                        "Execution surfaces can be evaluated under a shared trace format.",
                    ],
                },
                "recommendations": [
                    {
                        "bucket": "a_faire",
                        "system_name": "Verifier Gate Canonicalization",
                        "decision": "ADAPT",
                        "goal_link": ["master_agent", "verification", "operator_control"],
                        "roi": ["Turns autonomy from optimistic execution into bounded execution."],
                        "sequence_role": "foundational_now",
                        "scope_level": "platform",
                        "evidence_basis": ["repo", "web", "logs"],
                        "why": ["This is the main reliability choke point for the grand system."],
                        "what_to_take": ["A single mandatory gate between route, plan, and execution."],
                        "what_not_to_take": ["Do not scatter verifier logic across managers and adapters."],
                        "fork_signal": ["No meaningful fork beats upstream verifier patterns; the value is in canonicalization."],
                        "project_os_touchpoints": ["`router`", "`gateway`", "`api_runs`"],
                        "proofs": ["Block any autonomous action that skips verifier evidence."],
                        "sources": [
                            {
                                "title": "Verifier Source",
                                "url": "https://github.com/example/verifier",
                                "publisher": "Example",
                                "published_at": "2026-03-10",
                                "why": "Reference verifier design.",
                            }
                        ],
                    }
                ],
                "risks": ["The repo still risks over-investing in local hardening without system contracts."],
                "open_questions": ["Which execution surfaces deserve first-class manager agents first?"],
                "global_sources": [
                    {
                        "title": "Strategic Source",
                        "url": "https://example.com/strategic",
                        "publisher": "Example",
                        "published_at": "2026-03-14",
                        "why": "System strategy reference.",
                    },
                    {
                        "title": "Agent Systems Paper",
                        "url": "https://arxiv.org/abs/2501.00001",
                        "publisher": "arXiv",
                        "published_at": "2025-01-02",
                        "why": "Supports the multi-agent system framing.",
                    },
                ],
                "metadata": {"model": "gpt-5", "tool_type": "web_search"},
            }
            reader_structured = {
                **structured,
                "seo_title": "Project OS 2026 - audit strategique pour une autonomie multi-agents",
                "summary": "Reclasser la feuille de route autour du master agent, des manager agents et des surfaces d execution.",
                "project_audit_block": {
                    **structured["project_audit_block"],
                    "north_star": "Construire un master agent qui supervise des manager agents sur plusieurs surfaces locales avec autonomie bornee.",
                    "system_thesis": [
                        "Project OS doit devenir un plan de controle, pas seulement un gateway avec chat runtime.",
                    ],
                    "capability_gaps": [
                        "Aucun verifier gate canonique ne couvre toutes les lanes d execution.",
                        "La hierarchie master/manager est encore implicite.",
                        "Les surfaces d execution restent fragmentees.",
                    ],
                    "priority_ladder": {
                        "foundational_now": [
                            "Installer un verifier gate canonique avant toute execution autonome.",
                        ],
                        "system_next": [
                            "Definir des contrats de manager agents et leurs frontieres de routage.",
                        ],
                        "expansion_later": [
                            "Etendre les surfaces d execution vers desktop, navigateur et VM.",
                        ],
                    },
                    "observed_runtime_issues": [
                        "La duplication Discord prouve que le chemin operateur n est pas encore totalement idempotent.",
                    ],
                    "success_metrics": [
                        "Chaque action autonome passe par un verifier gate unique.",
                        "Les contrats manager-agent existent dans la doc canonique et les payloads runtime.",
                        "Les surfaces d execution partagent un format de trace commun.",
                    ],
                },
                "recommendations": [
                    {
                        **structured["recommendations"][0],
                        "roi": ["Transformer l autonomie en execution bornee et verifiable."],
                        "why": ["C est le principal point d etranglement de fiabilite du grand systeme."],
                        "what_to_take": ["Un gate obligatoire entre route, plan et execution."],
                        "what_not_to_take": ["Ne pas eparpiller la logique de verification dans chaque manager."],
                        "fork_signal": ["Aucun fork significatif ne bat les patterns upstream ; la valeur est dans la canonicalisation."],
                        "proofs": ["Bloquer toute action autonome sans preuve de verification."],
                    }
                ],
                "risks": ["Le repo peut encore surinvestir dans du hardening local sans contrats systeme."],
                "open_questions": ["Quelles surfaces d execution meritent d abord un manager agent dedié ?"],
            }
            mesh_manifest = {
                "mesh_level": "child_worker_mesh",
                "concurrency_cap": 4,
                "planned_lanes": ["repo", "official_docs", "github", "papers"],
                "launched_lanes": ["cheap_scout_swarm", "repo", "official_docs", "github", "papers"],
                "completed_lanes": ["cheap_scout_swarm", "repo", "official_docs", "github", "papers"],
                "failed_lanes": [],
                "lane_roots": {},
            }

            with patch.object(
                services.deep_research,
                "_call_research_model",
                side_effect=_research_model_stub(
                    services,
                    structured,
                    "resp_project",
                    {"input_tokens": 1600, "output_tokens": 900},
                ),
            ), patch.object(
                services.deep_research,
                "_run_planner_pass",
                return_value=_planner_payload(),
            ), patch.object(
                services.deep_research,
                "_run_extreme_lane_mesh",
                return_value=(_cheap_swarm_payload(), _extreme_scout_bundle(), [], mesh_manifest),
            ), patch.object(
                services.deep_research,
                "_run_lane_via_child",
                return_value={
                    **_skeptic_payload(),
                    "status": "completed",
                    "_response_id": "resp_skeptic",
                    "_stored": True,
                },
            ), patch.object(
                services.deep_research,
                "_translate_structured_for_reader",
                return_value=reader_structured,
            ):
                payload = services.deep_research.run_job_request(request=request, job_root=job_root)

            assert payload["status"] == "completed"
            content = dossier_path.read_text(encoding="utf-8")
            assert "## North Star" in content
            assert "## System Thesis" in content
            assert "## Platform Layers" in content
            assert "## Capability Gaps" in content
            assert "## Observed Runtime Issues" in content
            assert "### Cheap Scout Swarm" in content
            assert "### Lane Status" in content
            delivery = services.api_runs.list_operator_deliveries(limit=10)["deliveries"][0]
            payload_summary = delivery["payload"].get("response_manifest", {}).get("discord_summary") or delivery["payload"].get("text", "")
            summary = str(payload_summary)
            assert "Cap nord:" in summary
            assert "Debloque surtout:" in summary
            assert "Incident runtime observe:" in summary
        finally:
            services.close()


def test_component_discovery_validation_requires_external_leverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        services = _build_services(Path(tmp))
        try:
            structured = {
                "research_profile": "component_discovery",
                "research_intensity": "complex",
                "seo_title": "Bad Component Audit",
                "summary": "Too local.",
                "priority_actions": ["Refactor local code."],
                "component_discovery_block": {
                    "blind_spots": ["Missing external view."],
                    "external_leverage": ["Need external leverage."],
                    "underbuilt_layers": ["One layer."],
                    "priority_ladder": {
                        "highest_leverage_now": ["Refactor local code."],
                        "major_system_next": ["Later."],
                        "watch_and_prepare": ["Watch."],
                    },
                    "observed_runtime_issues": ["None."],
                    "stop_doing_or_deprioritize": ["Local-only thinking."],
                    "success_metrics": ["One metric."],
                },
                "recommendations": [
                    {
                        "bucket": "a_faire",
                        "system_name": "Local Refactor",
                        "decision": "ADAPT",
                        "goal_link": ["memory"],
                        "roi": ["Minor cleanup."],
                        "sequence_role": "highest_leverage_now",
                        "scope_level": "memory",
                        "evidence_basis": ["repo"],
                        "blind_spot_addressed": "None really.",
                        "why": ["Local cleanup only."],
                        "what_to_take": ["Refactor."],
                        "what_not_to_take": ["Nothing external."],
                        "fork_signal": ["No fork signal."],
                        "project_os_touchpoints": ["`memory`"],
                        "proofs": ["Run tests."],
                        "sources": [
                            {
                                "title": "Local Doc",
                                "url": "https://example.com/local",
                                "publisher": "Example",
                                "published_at": "2026-03-16",
                                "why": "Not enough.",
                            }
                        ],
                    }
                ],
                "risks": ["Weak."],
                "open_questions": ["None."],
                "global_sources": [
                    {
                        "title": "Global",
                        "url": "https://example.com/global",
                        "publisher": "Example",
                        "published_at": "2026-03-16",
                        "why": "Global.",
                    }
                ],
                "source_trust_summary": {
                    "counts": {"trusted_primary": 1, "trusted_ecosystem": 0, "neutral_secondary": 0, "weak_signal": 0, "quarantined": 0},
                    "evidence_manifest": [{"lane": "repo", "source_count": 1, "trusted_primary": 1}],
                },
                "source_reputation_summary": {
                    "score_mode": "medium",
                    "counts": {"trusted_primary": 1, "trusted_ecosystem": 0, "neutral_secondary": 0, "weak_signal": 0, "quarantined": 0},
                    "evidence_manifest": [{"lane": "repo", "title": "Global", "url": "https://example.com/global", "publisher": "Example", "published_at": "2026-03-16", "trust_class": "trusted_primary", "reputation_score": 84.0}],
                    "trusted_domains": ["example.com"],
                    "trusted_lanes": ["repo"],
                    "lane_counts": {"repo": 1},
                    "domain_counts": {"example.com": 1},
                    "observation_count": 1,
                    "average_score": 84.0,
                    "history_used": False,
                    "contradiction_count": 0,
                    "contradiction_notes": [],
                },
                "execution_plan": {
                    "mode": "complex",
                    "requested_mode": "complex",
                    "effective_mode": "complex",
                    "research_profile": "component_discovery",
                    "mesh_level": "in_process_parallel",
                    "phases": ["planner", "repo_scout", "official_docs", "github_scout", "synthesizer"],
                    "scout_lanes": ["repo", "official_docs", "github", "skeptic"],
                    "safety_gate": {"enabled": True, "mandatory": False},
                    "lane_status": {
                        "repo": {"status": "completed", "source_count": 1, "trusted_source_count": 1, "warning_count": 0},
                        "official_docs": {"status": "completed", "source_count": 1, "trusted_source_count": 1, "warning_count": 0},
                    },
                    "response_continuity": {
                        "enabled": True,
                        "scope": "planner_to_final_synthesis",
                        "strategy": "responses_previous_response_id",
                        "anchors": ["planner", "official_docs_scout", "final_synthesis"],
                        "trail_count": 3,
                        "notes": [],
                    },
                },
                "evidence_manifest": [{"lane": "repo", "source_count": 1, "trusted_primary": 1}],
                "metadata": {"model": "gpt-5", "tool_type": "web_search"},
            }
            with pytest.raises(RuntimeError, match="GitHub/fork/satellite-driven leverage|external evidence"):
                services.deep_research._validate_structured_result(
                    request={
                        "kind": "system",
                        "research_profile": "component_discovery",
                        "research_intensity": "complex",
                        "question": "deep research on memory systems",
                    },
                    structured=structured,
                )
        finally:
            services.close()


def test_deep_research_repo_context_includes_runtime_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        services = _build_services(tmp_path)
        try:
            repo_root = tmp_path / "repo"
            _write(repo_root / "AGENTS.md", "# Agents\n")
            _write(repo_root / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md", "# Deep Research\n")
            _write(repo_root / "src" / "project_os_core" / "gateway" / "__init__.py", "")
            services.deep_research.repo_root = repo_root
            services.journal.append(
                "deep_research_auxiliary_phase_failed",
                "deep_research",
                {
                    "job_id": "job_123",
                    "phase": "planner",
                    "error_type": "RuntimeError",
                    "error": "synthetic failure",
                    "research_profile": "component_discovery",
                    "research_intensity": "complex",
                },
            )

            context = services.deep_research._build_repo_context(
                {
                    "kind": "system",
                    "research_profile": "component_discovery",
                    "research_intensity": "complex",
                    "question": "deep research on memory systems",
                    "dossier_path": str(repo_root / "docs" / "systems" / "MEMORY_SYSTEMS_DOSSIER.md"),
                }
            )

            assert context["runtime_evidence"]
            assert "deep_research_auxiliary_phase_failed" in context["runtime_evidence"][0]["event_type"]
            assert "phase=planner" in context["runtime_evidence"][0]["summary"]
        finally:
            services.close()


def test_deep_research_complex_planner_failure_degrades_and_still_publishes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        services = _build_services(tmp_path)
        try:
            repo_root = tmp_path / "repo"
            _write(repo_root / "AGENTS.md", "# Agents\n")
            _write(repo_root / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md", "# Deep Research\n")
            _write(repo_root / "docs" / "systems" / "README.md", "# Systems\n")
            _write(repo_root / "src" / "project_os_core" / "memory" / "__init__.py", "")
            dossier_path = repo_root / "docs" / "systems" / "MEMORY_SYSTEMS_DOSSIER.md"
            _write(dossier_path, "# Memory Systems\n\n## Status\n\n- `draft`\n")
            services.deep_research.repo_root = repo_root

            job_root = services.path_policy.ensure_allowed_write(services.paths.runtime_root / "deep_research" / "job_degraded")
            job_root.mkdir(parents=True, exist_ok=True)
            request = {
                "job_id": "deep_research_job_degraded",
                "title": "Memory Systems",
                "kind": "system",
                "research_profile": "component_discovery",
                "research_intensity": "complex",
                "question": "Deep research sur les meilleurs systemes de memoire pour Project OS.",
                "recent_days": 30,
                "dossier_path": str(dossier_path),
                "dossier_relative_path": "docs/systems/MEMORY_SYSTEMS_DOSSIER.md",
                "doc_name": "MEMORY_SYSTEMS_DOSSIER.md",
                "reply_target": "channel:123456",
                "reply_to": "discord-message-1",
                "seo_slug": "memory-systems",
                "archive_stem": "2026-03-16-memory-systems-system-dossier",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
            structured = {
                "research_profile": "component_discovery",
                "research_intensity": "complex",
                "seo_title": "Memory Systems 2026 - typed memory, workflow memory and Project OS fit",
                "summary": "Prioritize typed memory and workflow promotion over prose-only documentation.",
                "priority_actions": [
                    "Audit a typed-memory bridge inside `memory`.",
                ],
                "component_discovery_block": {
                    "blind_spots": ["Project OS still underweights typed operational memory."],
                    "external_leverage": ["Typed memory runtimes and workflow promotion patterns can shorten design loops."],
                    "underbuilt_layers": ["No canonical typed-memory dossier exists yet."],
                    "priority_ladder": {
                        "highest_leverage_now": ["Audit a typed-memory bridge inside `memory`."],
                        "major_system_next": ["Define workflow promotion tests in `learning`."],
                        "watch_and_prepare": ["Track stronger satellites before importing dependencies."],
                    },
                    "observed_runtime_issues": ["Planner lane degraded during the run; synthesis fell back to a lighter path."],
                    "stop_doing_or_deprioritize": ["Do not keep expanding prose-only docs without proofs."],
                    "success_metrics": ["At least one workflow promotion test passes in `learning`."],
                },
                "recommendations": [
                    {
                        "bucket": "a_faire",
                        "system_name": "Typed Memory Runtime",
                        "decision": "ADAPT",
                        "goal_link": ["memory", "evals"],
                        "roi": ["Make procedural memory reusable by verifiers and future managers."],
                        "sequence_role": "highest_leverage_now",
                        "scope_level": "memory",
                        "evidence_basis": ["repo", "web"],
                        "blind_spot_addressed": "Project OS has not yet turned memory into a typed operational substrate.",
                        "why": ["The pattern fits the current repo state."],
                        "what_to_take": ["A `profile/behavior/skill/event/task` taxonomy."],
                        "what_not_to_take": ["Do not import a second canonical runtime."],
                        "fork_signal": ["No visible fork clearly beats the upstream GitHub repo; keep the idea, not the whole package."],
                        "project_os_touchpoints": ["`memory`", "`docs/systems`"],
                        "proofs": ["Write a workflow promotion test for procedural memory."],
                        "sources": [
                            {
                                "title": "Memory Source",
                                "url": "https://github.com/example/memory",
                                "publisher": "Example",
                                "published_at": "2026-03-10",
                                "why": "Conceptual basis for typed memory.",
                            }
                        ],
                    }
                ],
                "risks": ["Watch for duplication between memory code and the dossier."],
                "open_questions": ["Which verifier will consume the records first?"],
                "global_sources": [
                    {
                        "title": "Global Source",
                        "url": "https://example.com/global",
                        "publisher": "Example",
                        "published_at": "2026-03-15",
                        "why": "Global view of memory systems.",
                    }
                ],
                "metadata": {"model": "gpt-5", "tool_type": "web_search"},
            }
            reader_structured = {
                **structured,
                "seo_title": "Systemes de memoire 2026 - memoire typee et workflow memory pour Project OS",
                "summary": "Prioriser une memoire typee et la promotion de workflows plutot qu une documentation seulement textuelle.",
            }

            with patch.object(
                services.deep_research,
                "_run_planner_pass",
                side_effect=RuntimeError("quota exhausted"),
            ), patch.object(
                services.deep_research,
                "_call_research_model",
                side_effect=_research_model_stub(
                    services,
                    structured,
                    "resp_degraded",
                    {"input_tokens": 900, "output_tokens": 700},
                ),
            ), patch.object(
                services.deep_research,
                "_translate_structured_for_reader",
                return_value=reader_structured,
            ):
                payload = services.deep_research.run_job_request(request=request, job_root=job_root)

            assert payload["status"] == "completed"
            content = dossier_path.read_text(encoding="utf-8")
            assert "quality_gate: `degraded`" in content
            assert "planner auxiliary pass failed" in content
            status_payload = json.loads((job_root / "status.json").read_text(encoding="utf-8"))
            assert status_payload["status"] == "completed"
            result_payload = json.loads((job_root / "result.json").read_text(encoding="utf-8"))
            assert result_payload["quality_gate"]["status"] == "degraded"
            assert result_payload["execution_plan"]["effective_mode"] == "simple"
        finally:
            services.close()


def test_extreme_lane_failure_degrades_without_collapsing_to_simple() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        services = _build_services(tmp_path)
        try:
            repo_root = tmp_path / "repo"
            _write(repo_root / "AGENTS.md", "# Agents\n")
            _write(repo_root / "docs" / "workflow" / "DEEP_RESEARCH_PROTOCOL.md", "# Deep Research\n")
            _write(repo_root / "docs" / "systems" / "README.md", "# Systems\n")
            _write(repo_root / "src" / "project_os_core" / "gateway" / "__init__.py", "")
            dossier_path = repo_root / "docs" / "audits" / "PROJECT_OS_EXTREME_AUDIT_AUDIT_2026-03-16.md"
            _write(dossier_path, "# Project OS Extreme Audit\n\n## Status\n\n- `draft`\n")
            services.deep_research.repo_root = repo_root

            job_root = services.path_policy.ensure_allowed_write(services.paths.runtime_root / "deep_research" / "job_extreme_partial")
            job_root.mkdir(parents=True, exist_ok=True)
            request = {
                "job_id": "deep_research_job_extreme_partial",
                "title": "Project OS Extreme Audit",
                "kind": "audit",
                "research_profile": "project_audit",
                "research_intensity": "extreme",
                "question": "Deep research pour un audit extreme de mon projet.",
                "recent_days": 30,
                "dossier_path": str(dossier_path),
                "dossier_relative_path": "docs/audits/PROJECT_OS_EXTREME_AUDIT_AUDIT_2026-03-16.md",
                "doc_name": "PROJECT_OS_EXTREME_AUDIT_AUDIT_2026-03-16.md",
                "reply_target": "channel:9999",
                "reply_to": "discord-message-project",
                "seo_slug": "project-os-extreme-audit",
                "archive_stem": "2026-03-16-project-os-extreme-audit-deep-research-audit",
                "created_at": "2026-03-16T00:00:00+00:00",
            }
            structured = {
                "research_profile": "project_audit",
                "research_intensity": "extreme",
                "seo_title": "Project OS 2026 - extreme audit for master-agent autonomy",
                "summary": "Keep the war-room run evidence-led even when one scout lane degrades.",
                "priority_actions": ["Stabilize verifier and execution contracts."],
                "project_audit_block": {
                    "north_star": "Build a master agent that supervises manager agents across local surfaces with bounded autonomy.",
                    "system_thesis": ["Project OS should become a control plane with verifiable autonomy."],
                    "platform_layers": ["Master-agent orchestration", "Execution surfaces", "Verification"],
                    "capability_gaps": ["One scout lane can still fail during the run.", "Execution surfaces remain fragmented."],
                    "priority_ladder": {
                        "foundational_now": ["Install one verifier gate before autonomous execution."],
                        "system_next": ["Harden manager-agent contracts."],
                        "expansion_later": ["Expand desktop and VM operators."],
                    },
                    "observed_runtime_issues": ["One GitHub scout lane degraded during the run and remained visible in the dossier."],
                    "success_metrics": ["Extreme runs keep partial evidence instead of collapsing to simple mode."],
                },
                "recommendations": [
                    {
                        "bucket": "a_faire",
                        "system_name": "Verifier Gate Canonicalization",
                        "decision": "ADAPT",
                        "goal_link": ["master_agent", "verification"],
                        "roi": ["Keep autonomy bounded and auditable."],
                        "sequence_role": "foundational_now",
                        "scope_level": "platform",
                        "evidence_basis": ["repo", "web", "logs"],
                        "why": ["This remains the main reliability choke point."],
                        "what_to_take": ["A single mandatory gate between route, plan, and execution."],
                        "what_not_to_take": ["Do not scatter verifier logic."],
                        "fork_signal": ["Satellite wrappers are useful, but the value is in canonicalization."],
                        "project_os_touchpoints": ["`router`", "`gateway`", "`api_runs`"],
                        "proofs": ["Block any autonomous action without verifier evidence."],
                        "sources": [
                            {
                                "title": "Verifier Source",
                                "url": "https://github.com/example/verifier",
                                "publisher": "Example",
                                "published_at": "2026-03-10",
                                "why": "Reference verifier design.",
                            }
                        ],
                    }
                ],
                "risks": ["A degraded lane should not masquerade as a full success."],
                "open_questions": ["Which scout lane deserves extra redundancy first?"],
                "global_sources": [
                    {
                        "title": "Strategic Source",
                        "url": "https://openai.com/index/new-tools-and-features-in-the-responses-api/",
                        "publisher": "OpenAI",
                        "published_at": "2025-03-11",
                        "why": "Primary source for the active API path.",
                    },
                    {
                        "title": "Agent Systems Paper",
                        "url": "https://arxiv.org/abs/2501.00001",
                        "publisher": "arXiv",
                        "published_at": "2025-01-02",
                        "why": "Supports the multi-agent system framing.",
                    },
                ],
                "metadata": {"model": "gpt-5", "tool_type": "web_search"},
            }
            reader_structured = {
                **structured,
                "seo_title": "Project OS 2026 - audit extreme pour une autonomie multi-agents",
                "summary": "Garder le run War Room ancre dans les preuves meme si une lane scout degrade.",
            }
            mesh_manifest = {
                "mesh_level": "child_worker_mesh",
                "concurrency_cap": 4,
                "planned_lanes": ["repo", "official_docs", "github", "papers"],
                "launched_lanes": ["cheap_scout_swarm", "repo", "official_docs", "github", "papers"],
                "completed_lanes": ["cheap_scout_swarm", "repo", "official_docs", "papers"],
                "failed_lanes": ["github"],
                "lane_roots": {},
            }
            degraded_bundle = _extreme_scout_bundle()
            degraded_bundle["github"] = {
                "lane": "github",
                "summary": "github scout degraded before full depth.",
                "key_findings": [],
                "candidate_systems": ["verifier"],
                "sources": [
                    {
                        "title": "GitHub Seed",
                        "url": "https://github.com/example/verifier",
                        "publisher": "GitHub",
                        "published_at": "2026-03-10",
                        "why": "Seed repo for verifier patterns.",
                    }
                ],
                "warnings": ["synthetic github scout failure"],
                "status": "degraded",
            }

            with patch.object(
                services.deep_research,
                "_call_research_model",
                side_effect=_research_model_stub(
                    services,
                    structured,
                    "resp_extreme_partial",
                    {"input_tokens": 1700, "output_tokens": 950},
                ),
            ), patch.object(
                services.deep_research,
                "_run_planner_pass",
                return_value=_planner_payload(),
            ), patch.object(
                services.deep_research,
                "_run_extreme_lane_mesh",
                return_value=(
                    _cheap_swarm_payload(),
                    degraded_bundle,
                    ["github auxiliary pass failed with RuntimeError: synthetic github scout failure"],
                    mesh_manifest,
                ),
            ), patch.object(
                services.deep_research,
                "_run_lane_via_child",
                return_value={
                    **_skeptic_payload(),
                    "status": "completed",
                    "_response_id": "resp_skeptic",
                    "_stored": True,
                },
            ), patch.object(
                services.deep_research,
                "_translate_structured_for_reader",
                return_value=reader_structured,
            ):
                payload = services.deep_research.run_job_request(request=request, job_root=job_root)

            assert payload["status"] == "completed"
            result_payload = json.loads((job_root / "result.json").read_text(encoding="utf-8"))
            assert result_payload["quality_gate"]["status"] == "degraded"
            assert result_payload["execution_plan"]["effective_mode"] == "extreme"
            assert result_payload["execution_plan"]["cheap_scout_summary"]["status"] == "completed"
            assert result_payload["execution_plan"]["lane_status"]["github"]["status"] == "degraded"
            assert (job_root / "cheap_scout_swarm.json").exists()
        finally:
            services.close()


def test_extreme_validation_requires_trusted_domain_and_lane_diversity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        services = _build_services(Path(tmp))
        try:
            structured = {
                "research_profile": "project_audit",
                "research_intensity": "extreme",
                "seo_title": "Bad Extreme Audit",
                "summary": "Too concentrated on one source family.",
                "priority_actions": ["Do one thing."],
                "project_audit_block": {
                    "north_star": "Build a master agent with manager agents and bounded autonomy.",
                    "system_thesis": ["One thesis."],
                    "platform_layers": ["Verification"],
                    "capability_gaps": ["Not enough diversity."],
                    "priority_ladder": {
                        "foundational_now": ["Fix verifier."],
                        "system_next": ["Add managers."],
                        "expansion_later": ["Expand surfaces."],
                    },
                    "observed_runtime_issues": ["None."],
                    "success_metrics": ["One metric."],
                },
                "recommendations": [
                    {
                        "bucket": "a_faire",
                        "system_name": "Verifier",
                        "decision": "ADAPT",
                        "goal_link": ["master_agent", "verification"],
                        "roi": ["Help."],
                        "sequence_role": "foundational_now",
                        "scope_level": "platform",
                        "evidence_basis": ["repo", "web"],
                        "why": ["Needed."],
                        "what_to_take": ["A gate."],
                        "what_not_to_take": ["Sprawl."],
                        "fork_signal": ["No fork beats upstream."],
                        "project_os_touchpoints": ["`router`"],
                        "proofs": ["Gate all actions."],
                        "sources": [
                            {
                                "title": "Verifier Source",
                                "url": "https://github.com/example/verifier",
                                "publisher": "Example",
                                "published_at": "2026-03-10",
                                "why": "Reference.",
                            }
                        ],
                    }
                ],
                "risks": ["Weak diversity."],
                "open_questions": ["None."],
                "global_sources": [
                    {
                        "title": "Same Domain 1",
                        "url": "https://github.com/example/verifier",
                        "publisher": "GitHub",
                        "published_at": "2026-03-10",
                        "why": "One domain.",
                    },
                    {
                        "title": "Same Domain 2",
                        "url": "https://github.com/example/verifier-two",
                        "publisher": "GitHub",
                        "published_at": "2026-03-10",
                        "why": "Still one domain.",
                    },
                ],
                "source_trust_summary": {
                    "counts": {"trusted_primary": 1, "trusted_ecosystem": 1, "neutral_secondary": 0, "weak_signal": 0, "quarantined": 0},
                    "evidence_manifest": [
                        {"lane": "github", "title": "Same Domain 1", "url": "https://github.com/example/verifier", "publisher": "GitHub", "published_at": "2026-03-10", "trust_class": "trusted_ecosystem"},
                        {"lane": "github", "title": "Same Domain 2", "url": "https://github.com/example/verifier-two", "publisher": "GitHub", "published_at": "2026-03-10", "trust_class": "trusted_ecosystem"},
                    ],
                    "trusted_domains": ["github.com"],
                    "trusted_lanes": ["github"],
                    "lane_counts": {"github": 2},
                    "domain_counts": {"github.com": 2},
                },
                "source_reputation_summary": {
                    "score_mode": "full",
                    "counts": {"trusted_primary": 1, "trusted_ecosystem": 1, "neutral_secondary": 0, "weak_signal": 0, "quarantined": 0},
                    "evidence_manifest": [
                        {"lane": "github", "title": "Same Domain 1", "url": "https://github.com/example/verifier", "publisher": "GitHub", "published_at": "2026-03-10", "trust_class": "trusted_ecosystem", "reputation_score": 72.0},
                        {"lane": "github", "title": "Same Domain 2", "url": "https://github.com/example/verifier-two", "publisher": "GitHub", "published_at": "2026-03-10", "trust_class": "trusted_ecosystem", "reputation_score": 72.0},
                    ],
                    "trusted_domains": ["github.com"],
                    "trusted_lanes": ["github"],
                    "lane_counts": {"github": 2},
                    "domain_counts": {"github.com": 2},
                    "observation_count": 2,
                    "average_score": 72.0,
                    "history_used": False,
                    "contradiction_count": 0,
                    "contradiction_notes": [],
                },
                "execution_plan": {
                    "mode": "extreme",
                    "requested_mode": "extreme",
                    "effective_mode": "extreme",
                    "research_profile": "project_audit",
                    "mesh_level": "child_worker_mesh",
                    "phases": ["planner", "repo_scout", "official_docs_scout", "github_scout", "cheap_scout_swarm", "papers_scout", "source_safety_gate", "skeptic", "expert_synthesis"],
                    "scout_lanes": ["repo", "official_docs", "github", "papers"],
                    "safety_gate": {"enabled": True, "mandatory": True},
                    "cheap_scout_summary": {"status": "completed", "lane_brief_count": 3, "broad_signal_count": 2, "watchouts": []},
                    "mesh_manifest": {
                        "launched_lanes": ["cheap_scout_swarm", "repo", "official_docs", "github", "papers", "skeptic"],
                        "completed_lanes": ["cheap_scout_swarm", "repo", "official_docs", "github", "papers", "skeptic"],
                        "failed_lanes": [],
                        "concurrency_cap": 4,
                    },
                    "lane_status": {
                        "repo": {"status": "completed", "source_count": 1, "trusted_source_count": 1, "warning_count": 0},
                        "github": {"status": "completed", "source_count": 2, "trusted_source_count": 2, "warning_count": 0},
                    },
                    "response_continuity": {
                        "enabled": True,
                        "scope": "planner_to_final_synthesis",
                        "strategy": "responses_previous_response_id",
                        "anchors": ["planner", "cheap_scout_swarm", "github_scout", "skeptic", "final_synthesis"],
                        "trail_count": 5,
                        "notes": [],
                    },
                    "contradiction_signal": ["no material contradiction found"],
                },
                "evidence_manifest": [
                    {"lane": "github", "title": "Same Domain 1", "url": "https://github.com/example/verifier", "publisher": "GitHub", "published_at": "2026-03-10", "trust_class": "trusted_ecosystem"},
                    {"lane": "github", "title": "Same Domain 2", "url": "https://github.com/example/verifier-two", "publisher": "GitHub", "published_at": "2026-03-10", "trust_class": "trusted_ecosystem"},
                ],
                "metadata": {"model": "gpt-5", "tool_type": "web_search"},
            }
            with pytest.raises(RuntimeError, match="trusted evidence from at least two unique domains|trusted evidence across at least two scout lanes"):
                services.deep_research._validate_structured_result(
                    request={
                        "kind": "audit",
                        "research_profile": "project_audit",
                        "research_intensity": "extreme",
                        "question": "deep research extreme audit for project os",
                    },
                    structured=structured,
                )
        finally:
            services.close()


def test_response_continuity_helpers_record_and_summarize() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        services = _build_services(Path(tmp))
        try:
            continuity = services.deep_research._new_response_continuity(research_intensity="extreme")
            assert continuity["enabled"] is True

            services.deep_research._record_response_continuity(
                response_continuity=continuity,
                anchor="planner",
                phase="planner",
                model="gpt-5",
                response_id="resp_plan",
                previous_response_id=None,
                stored=True,
            )
            services.deep_research._record_response_continuity(
                response_continuity=continuity,
                anchor="cheap_scout_swarm",
                phase="cheap_scout_swarm",
                model="gpt-5",
                response_id="resp_swarm",
                previous_response_id="resp_plan",
                stored=True,
            )

            assert services.deep_research._resolve_continuity_previous_response_id(
                response_continuity=continuity,
                anchor_candidates=["cheap_scout_swarm", "planner"],
            ) == "resp_swarm"

            summary = services.deep_research._summarize_response_continuity(continuity)
            assert summary["enabled"] is True
            assert summary["strategy"] == "responses_previous_response_id"
            assert "planner" in summary["anchors"]
            assert "cheap_scout_swarm" in summary["anchors"]
            assert summary["trail_count"] == 2
        finally:
            services.close()


def test_run_scout_bundle_uses_swarm_anchor_for_previous_response_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        services = _build_services(Path(tmp))
        try:
            continuity = services.deep_research._new_response_continuity(research_intensity="extreme")
            services.deep_research._record_response_continuity(
                response_continuity=continuity,
                anchor="planner",
                phase="planner",
                model="gpt-5",
                response_id="resp_plan",
                previous_response_id=None,
                stored=True,
            )
            services.deep_research._record_response_continuity(
                response_continuity=continuity,
                anchor="cheap_scout_swarm",
                phase="cheap_scout_swarm",
                model="gpt-5",
                response_id="resp_swarm",
                previous_response_id="resp_plan",
                stored=True,
            )
            seen_previous_ids: list[str | None] = []

            def _auxiliary_side_effect(*, previous_anchor_candidates=None, response_continuity=None, metadata=None, **_: object) -> dict[str, object]:
                seen_previous_ids.append(
                    services.deep_research._resolve_continuity_previous_response_id(
                        response_continuity=response_continuity,
                        anchor_candidates=previous_anchor_candidates,
                    )
                )
                phase = str((metadata or {}).get("phase") or "unknown")
                return {
                    "lane": phase,
                    "summary": f"{phase} lane",
                    "key_findings": ["finding"],
                    "candidate_systems": ["system"],
                    "sources": [],
                    "warnings": [],
                }

            with patch.object(services.deep_research, "_call_auxiliary_model", side_effect=_auxiliary_side_effect):
                bundle, failures = services.deep_research._run_scout_bundle(
                    request={
                        "kind": "system",
                        "research_profile": "component_discovery",
                        "research_intensity": "extreme",
                        "question": "deep research on memory systems",
                    },
                    repo_context={"core_packages": ["memory"]},
                    execution_plan={"mode": "extreme", "scout_lanes": ["repo", "official_docs", "github", "papers"]},
                    planner_payload=_planner_payload(),
                    cheap_scout_swarm_payload=_cheap_swarm_payload(),
                    response_continuity=continuity,
                )

            assert not failures
            assert bundle["official_docs"]["status"] == "completed"
            assert seen_previous_ids == ["resp_swarm", "resp_swarm", "resp_swarm"]
        finally:
            services.close()


def test_run_lane_request_repo_writes_lane_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        services = _build_services(tmp_path)
        try:
            lane_root = services.path_policy.ensure_allowed_write(services.paths.runtime_root / "deep_research" / "lane_repo")
            lane_root.mkdir(parents=True, exist_ok=True)
            payload = services.deep_research.run_lane_request(
                lane_request={
                    "lane": "repo",
                    "request": {"job_id": "job_repo_lane"},
                    "repo_context": {
                        "current_branch": "main",
                        "core_packages": ["memory", "learning"],
                        "local_refs": [],
                    },
                    "execution_plan": {"mode": "extreme"},
                },
                lane_root=lane_root,
            )
            assert payload["status"] == "completed"
            result_payload = json.loads((lane_root / "result.json").read_text(encoding="utf-8"))
            assert result_payload["lane"] == "repo"
            assert result_payload["status"] == "completed"
            status_payload = json.loads((lane_root / "status.json").read_text(encoding="utf-8"))
            assert status_payload["status"] == "completed"
        finally:
            services.close()


def test_source_reputation_persists_history_across_runs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        services = _build_services(Path(tmp))
        try:
            request = {
                "job_id": "deep_research_job_reputation",
                "research_intensity": "extreme",
            }
            execution_plan = {"mode": "extreme"}
            scout_bundle = {
                "github": {
                    "lane": "github",
                    "sources": [
                        {
                            "title": "Verifier Repo",
                            "url": "https://github.com/example/verifier?utm_source=test",
                            "publisher": "GitHub",
                            "published_at": "2026-03-10",
                            "why": "Reference.",
                        }
                    ],
                }
            }
            first = services.deep_research._apply_source_trust_gate_to_scouts(
                request=request,
                execution_plan=execution_plan,
                scout_bundle=scout_bundle,
            )
            second = services.deep_research._apply_source_trust_gate_to_scouts(
                request={**request, "job_id": "deep_research_job_reputation_2"},
                execution_plan=execution_plan,
                scout_bundle=scout_bundle,
            )
            first_source = first["github"]["source_trust"][0]
            second_source = second["github"]["source_trust"][0]
            assert first_source["normalized_url"] == "https://github.com/example/verifier"
            assert second_source["history_used"] is True
            row = services.journal.database.fetchone(
                """
                SELECT observation_count
                FROM deep_research_source_reputation
                WHERE normalized_source_id = ?
                """,
                (first_source["normalized_source_id"],),
            )
            assert row is not None
            assert int(row["observation_count"] or 0) >= 2
        finally:
            services.close()


def test_extreme_estimate_uses_anthropic_debug_route() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        services = _build_services(Path(tmp))
        try:
            estimate = services.deep_research.estimate_run(
                request={
                    "kind": "audit",
                    "question": "Deep research extreme audit of Project OS autonomy and manager agents.",
                    "research_profile": "project_audit",
                    "research_intensity": "extreme",
                }
            )
            assert estimate["estimated_api_provider"] == "anthropic"
            assert estimate["estimated_api_model"] == "claude-sonnet-4-20250514"
            assert estimate["execution_plan"]["provider_route"]["research_provider"] == "anthropic"
        finally:
            services.close()


def test_extreme_auxiliary_anthropic_debug_logs_include_counted_tokens() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        services = _build_services(Path(tmp))
        try:
            debug_root = services.path_policy.ensure_allowed_write(
                services.paths.runtime_root / "deep_research" / "debug_test"
            )
            debug_root.mkdir(parents=True, exist_ok=True)

            class _FakeCountTokens:
                def model_dump(self):
                    return {"input_tokens": 321}

            class _FakeResponse:
                id = "msg_debug_1"
                usage = {"input_tokens": 330, "output_tokens": 120, "server_tool_use": {"web_search_requests": 2}}
                content = [{"type": "text", "text": '{"mission":"ok","broad_signals":[],"lane_briefs":[],"watchouts":[]}'}]

                def model_dump(self):
                    return {"id": self.id, "usage": self.usage, "content": self.content}

            class _FakeMessages:
                def count_tokens(self, **kwargs):
                    return _FakeCountTokens()

                def create(self, **kwargs):
                    return _FakeResponse()

            class _FakeAnthropicClient:
                def __init__(self):
                    self.messages = _FakeMessages()

            with patch.object(services.deep_research, "_anthropic_client", return_value=_FakeAnthropicClient()):
                payload = services.deep_research._call_auxiliary_model(
                    prompt="Return strict JSON only.",
                    schema=services.deep_research._cheap_scout_swarm_schema(),
                    schema_name="project_os_deep_research_cheap_scout_swarm",
                    description="Cheap scout swarm for testing",
                    attempts=[("gpt-5.4", {"type": "web_search_preview", "search_context_size": "high"}, "low")],
                    metadata={
                        "job_id": "deep_research_job_debug",
                        "kind": "audit",
                        "research_profile": "project_audit",
                        "research_intensity": "extreme",
                        "phase": "cheap_scout_swarm",
                        "debug_root": str(debug_root),
                    },
                    response_continuity=services.deep_research._new_response_continuity(research_intensity="extreme"),
                    continuity_anchor="cheap_scout_swarm",
                )

            assert payload["_provider"] == "anthropic"
            log_path = debug_root / "model_debug.jsonl"
            assert log_path.exists()
            entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            assert entries[-1]["provider"] == "anthropic"
            assert entries[-1]["counted_input_tokens"] == 321
            assert entries[-1]["estimated_cost_eur"] > 0
        finally:
            services.close()
