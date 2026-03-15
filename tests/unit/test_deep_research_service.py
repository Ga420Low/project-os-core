from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

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
    return services


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
                "question": "Deep research sur les meilleurs systemes de memoire pour Project OS.",
                "recent_days": 30,
                "dossier_path": str(dossier_path),
                "dossier_relative_path": "docs/systems/MEMORY_SYSTEMS_DOSSIER.md",
                "doc_name": "MEMORY_SYSTEMS_DOSSIER.md",
                "reply_target": "channel:123456",
                "reply_to": "discord-message-1",
            }
            structured = {
                "summary": "Prioriser une memoire typée et des workflows promus depuis les runs acceptes.",
                "why_now": ["Le repo a deja `memory` et `learning`, mais pas de dossier comparatif durable."],
                "repo_fit": ["Les principaux touchpoints sont `memory`, `learning` et `docs/workflow`."],
                "priority_actions": [
                    "Auditer un bridge typed memory dans `memory`.",
                    "Definir un test de promotion workflow dans `learning`.",
                ],
                "recommendations": [
                    {
                        "bucket": "a_faire",
                        "system_name": "Typed Memory Runtime",
                        "decision": "ADAPT",
                        "why": ["Le pattern colle a l'etat actuel du repo."],
                        "what_to_take": ["Typologie `profile/behavior/skill/event/task`."],
                        "what_not_to_take": ["Ne pas importer un second runtime canonique."],
                        "fork_signal": ["Aucun fork visible ne bat clairement l'upstream; garder l'idee, pas le package entier."],
                        "project_os_touchpoints": ["`memory`", "`learning`", "`docs/systems`"],
                        "proofs": ["Ecrire un test de promotion de workflow en memoire procedurale."],
                        "sources": [
                            {
                                "title": "Memory Source",
                                "url": "https://example.com/memory",
                                "publisher": "Example",
                                "published_at": "2026-03-10",
                                "why": "Base conceptuelle pour la memoire typee.",
                            }
                        ],
                    },
                    {
                        "bucket": "a_etudier",
                        "system_name": "Workflow Memory",
                        "decision": "DEFER",
                        "why": ["Pertinent, mais a tester apres la couche typed memory."],
                        "what_to_take": ["La promotion des runs acceptes en workflow memory."],
                        "what_not_to_take": ["Pas de dependence lourde tant que les evals ne sont pas posees."],
                        "fork_signal": ["Satellites interessants, mais rien a reprendre tel quel."],
                        "project_os_touchpoints": ["`learning`", "`mission`"],
                        "proofs": ["Comparer deux runs avant/apres promotion workflow."],
                        "sources": [
                            {
                                "title": "Workflow Source",
                                "url": "https://example.com/workflow",
                                "publisher": "Example",
                                "published_at": "2026-03-12",
                                "why": "Supporte la promotion de workflows.",
                            }
                        ],
                    },
                ],
                "risks": ["Attention a la duplication entre memoire et dossier doc."],
                "open_questions": ["Quel verifier utilisera les nouveaux records ?"],
                "global_sources": [
                    {
                        "title": "Global Source",
                        "url": "https://example.com/global",
                        "publisher": "Example",
                        "published_at": "2026-03-15",
                        "why": "Vue globale des systemes memoire.",
                    }
                ],
                "metadata": {"model": "gpt-5", "tool_type": "web_search"},
            }

            with patch.object(
                services.deep_research,
                "_call_research_model",
                return_value=(structured, {"response_id": "resp_123"}, {"input_tokens": 1200, "output_tokens": 800}),
            ):
                payload = services.deep_research.run_job_request(request=request, job_root=job_root)

            assert payload["status"] == "completed"
            assert dossier_path.exists()
            content = dossier_path.read_text(encoding="utf-8")
            assert "# Memory Systems" in content
            assert "## A faire" in content
            assert "Typed Memory Runtime" in content
            assert "## Sources globales" in content

            deliveries = services.api_runs.list_operator_deliveries(limit=10)["deliveries"]
            assert len(deliveries) == 1
            delivery = deliveries[0]
            assert delivery["payload"]["target"] == "channel:123456"
            assert delivery["payload"]["reply_to"] == "discord-message-1"
            manifest = delivery["payload"]["response_manifest"]
            assert manifest["delivery_mode"] == "direct_attachment"
            assert manifest["attachments"][0]["path"] == str(dossier_path)

            status_payload = json.loads((job_root / "status.json").read_text(encoding="utf-8"))
            assert status_payload["status"] == "completed"
        finally:
            services.close()
