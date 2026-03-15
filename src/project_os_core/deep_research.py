from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from .api_runs.service import ApiRunService
from .models import ApiRunStatus, OperatorChannelHint, RunLifecycleEventKind, new_id
from .observability import StructuredLogger
from .paths import PathPolicy, ProjectPaths
from .research_scaffold import core_packages, existing_local_refs
from .runtime.journal import LocalJournal
from .secrets import SecretResolver

_MAX_LOCAL_REF_CHARS = 2_800
_MAX_LOCAL_REF_COUNT = 7
_MAX_DIRTY_FILE_LINES = 40


class DeepResearchService:
    """Owns deep-research jobs triggered from Discord/OpenClaw ingress."""

    def __init__(
        self,
        *,
        paths: ProjectPaths,
        path_policy: PathPolicy,
        secret_resolver: SecretResolver,
        journal: LocalJournal,
        logger: StructuredLogger,
        api_runs: ApiRunService,
        config_path: Path,
        policy_path: Path,
        default_model: str,
        default_reasoning_effort: str,
    ) -> None:
        self.paths = paths
        self.path_policy = path_policy
        self.secret_resolver = secret_resolver
        self.journal = journal
        self.logger = logger
        self.api_runs = api_runs
        self.repo_root = paths.repo_root
        self.config_path = Path(config_path).resolve(strict=False)
        self.policy_path = Path(policy_path).resolve(strict=False)
        self.default_model = str(default_model).strip() or "gpt-5"
        self.default_reasoning_effort = str(default_reasoning_effort).strip() or "high"

    def launch_job_from_gateway(self, *, event, scaffold: dict[str, Any]) -> dict[str, Any]:
        job_id = new_id("deep_research")
        job_root = self._job_root(job_id)
        request = {
            "job_id": job_id,
            "title": str(scaffold.get("title") or "Deep Research").strip(),
            "kind": str(scaffold.get("kind") or "audit").strip().lower(),
            "question": str(event.message.text or "").strip(),
            "keywords": [str(item).strip() for item in scaffold.get("keywords", []) if str(item).strip()],
            "recent_days": int(scaffold.get("recent_days") or 30),
            "dossier_path": str(scaffold.get("path") or ""),
            "dossier_relative_path": str(scaffold.get("relative_path") or "").strip() or None,
            "doc_name": str(scaffold.get("doc_name") or Path(str(scaffold.get("path") or "")).name).strip() or None,
            "source_surface": str(event.surface or "").strip(),
            "source_channel": str(event.message.channel or "").strip(),
            "actor_id": str(event.message.actor_id or "").strip(),
            "source_event_id": str(event.event_id or "").strip(),
            "source_message_id": str(event.message.metadata.get("message_id") or event.message.message_id or "").strip(),
            "reply_to": self._reply_to_for_event(event),
            "reply_target": self._reply_target_for_event(event),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        request_path = job_root / "request.json"
        self._write_managed_json(request_path, request)

        self.api_runs.publish_operator_update(
            title=f"Deep research lancee: {request['title']}",
            summary=self._launch_summary(request),
            text=self._launch_summary(request),
            kind=RunLifecycleEventKind.RUN_STARTED,
            status=ApiRunStatus.RUNNING,
            channel_hint=OperatorChannelHint.RUNS_LIVE,
            target=request["reply_target"],
            reply_to=request["reply_to"],
            metadata={
                "source": "deep_research",
                "deep_research_job_id": job_id,
                "dossier_relative_path": request["dossier_relative_path"],
                "source_event_id": request["source_event_id"],
            },
        )
        process = self._spawn_detached_job(request_path)
        payload = {
            **request,
            "job_path": str(request_path),
            "job_root": str(job_root),
            "launched": True,
            "pid": int(process.pid) if process and process.pid else None,
        }
        self._write_managed_json(job_root / "launch.json", payload)
        self.journal.append(
            "deep_research_job_launched",
            "deep_research",
            {
                "job_id": job_id,
                "job_path": str(request_path),
                "dossier_path": request["dossier_path"],
                "reply_target": request["reply_target"],
            },
        )
        return payload

    def run_job_path(self, *, job_path: str) -> dict[str, Any]:
        request_path = self.path_policy.ensure_allowed_write(job_path)
        if not request_path.exists():
            raise FileNotFoundError(f"Unknown deep research job payload: {request_path}")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise RuntimeError("Deep research payload must be a JSON object.")
        return self.run_job_request(request=request, job_root=request_path.parent)

    def run_job_request(self, *, request: dict[str, Any], job_root: Path) -> dict[str, Any]:
        job_id = str(request.get("job_id") or new_id("deep_research"))
        self._write_managed_json(
            job_root / "status.json",
            {"job_id": job_id, "status": "running", "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        try:
            repo_context = self._build_repo_context(request)
            self._write_managed_json(job_root / "repo_context.json", repo_context)
            prompt = self._render_prompt(request=request, repo_context=repo_context)
            self._write_managed_text(job_root / "prompt.md", prompt)
            structured, raw_payload, usage = self._call_research_model(request=request, prompt=prompt)
            self._write_managed_json(job_root / "response.json", raw_payload)
            self._write_managed_json(job_root / "result.json", structured)
            dossier_path = self._validated_dossier_path(str(request.get("dossier_path") or ""))
            dossier_markdown = self._render_dossier_markdown(
                request=request,
                repo_context=repo_context,
                structured=structured,
                dossier_path=dossier_path,
            )
            self._write_repo_markdown(dossier_path, dossier_markdown)
            summary_text = self._completion_summary(request=request, structured=structured)
            attachments = [
                {
                    "path": str(dossier_path),
                    "name": str(request.get("doc_name") or dossier_path.name),
                    "mime_type": "text/markdown",
                }
            ]
            delivery = self.api_runs.publish_operator_update(
                title=f"Deep research terminee: {request['title']}",
                summary=summary_text,
                text=summary_text,
                kind=RunLifecycleEventKind.RUN_COMPLETED,
                status=ApiRunStatus.COMPLETED,
                channel_hint=OperatorChannelHint.RUNS_LIVE,
                target=str(request.get("reply_target") or "").strip() or None,
                reply_to=str(request.get("reply_to") or "").strip() or None,
                attachments=attachments,
                metadata={
                    "source": "deep_research",
                    "deep_research_job_id": job_id,
                    "dossier_path": str(dossier_path),
                    "dossier_relative_path": request.get("dossier_relative_path"),
                    "usage": usage,
                    "model": structured.get("metadata", {}).get("model"),
                    "tool_type": structured.get("metadata", {}).get("tool_type"),
                },
            )
            payload = {
                "job_id": job_id,
                "status": "completed",
                "dossier_path": str(dossier_path),
                "delivery_id": delivery.get("delivery_id"),
                "usage": usage,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_managed_json(job_root / "status.json", payload)
            self.journal.append(
                "deep_research_job_completed",
                "deep_research",
                {
                    "job_id": job_id,
                    "dossier_path": str(dossier_path),
                    "delivery_id": payload["delivery_id"],
                },
            )
            return payload
        except Exception as exc:
            error_payload = {
                "job_id": job_id,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "failed_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_managed_json(job_root / "status.json", error_payload)
            self.api_runs.publish_operator_update(
                title=f"Deep research echouee: {request.get('title') or 'Deep Research'}",
                summary=self._failure_summary(request=request, error_payload=error_payload),
                text=self._failure_summary(request=request, error_payload=error_payload),
                kind=RunLifecycleEventKind.RUN_FAILED,
                status=ApiRunStatus.FAILED,
                channel_hint=OperatorChannelHint.RUNS_LIVE,
                target=str(request.get("reply_target") or "").strip() or None,
                reply_to=str(request.get("reply_to") or "").strip() or None,
                metadata={
                    "source": "deep_research",
                    "deep_research_job_id": job_id,
                    "dossier_relative_path": request.get("dossier_relative_path"),
                    "error_type": error_payload["error_type"],
                },
            )
            self.journal.append(
                "deep_research_job_failed",
                "deep_research",
                {
                    "job_id": job_id,
                    "error_type": error_payload["error_type"],
                    "error": error_payload["error"],
                },
            )
            raise

    def _spawn_detached_job(self, request_path: Path) -> subprocess.Popen[Any]:
        entrypoint = self.repo_root / "scripts" / "project_os_entry.py"
        command = [
            sys.executable,
            str(entrypoint),
            "--config-path",
            str(self.config_path),
            "--policy-path",
            str(self.policy_path),
            "research",
            "run-job",
            "--job-path",
            str(request_path),
        ]
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(
            command,
            cwd=str(self.repo_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=dict(os.environ),
            creationflags=creationflags,
        )

    def _reply_to_for_event(self, event) -> str | None:
        message_id = str(event.message.metadata.get("message_id") or event.message.message_id or "").strip()
        return message_id or None

    def _reply_target_for_event(self, event) -> str | None:
        metadata = event.message.metadata if isinstance(event.message.metadata, dict) else {}
        context = metadata.get("context") if isinstance(metadata.get("context"), dict) else {}
        candidates = [
            event.message.thread_ref.external_thread_id,
            context.get("conversationId"),
            metadata.get("originating_to"),
            metadata.get("to"),
        ]
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return text
        return None

    def _build_repo_context(self, request: dict[str, Any]) -> dict[str, Any]:
        refs = []
        for path in existing_local_refs(self.repo_root)[:_MAX_LOCAL_REF_COUNT]:
            refs.append(
                {
                    "path": str(path),
                    "relative_path": path.resolve(strict=False).relative_to(self.repo_root).as_posix(),
                    "excerpt": self._read_excerpt(path, _MAX_LOCAL_REF_CHARS),
                }
            )
        dossier_path = self._validated_dossier_path(str(request.get("dossier_path") or ""))
        return {
            "repo_root": str(self.repo_root),
            "current_branch": self._git_output("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": self._git_lines("status", "--short")[:_MAX_DIRTY_FILE_LINES],
            "core_packages": core_packages(self.repo_root),
            "local_refs": refs,
            "dossier_excerpt": self._read_excerpt(dossier_path, 4_200) if dossier_path.exists() else "",
        }

    def _render_prompt(self, *, request: dict[str, Any], repo_context: dict[str, Any]) -> str:
        question = str(request.get("question") or "").strip()
        kind = str(request.get("kind") or "audit").strip()
        recent_days = int(request.get("recent_days") or 30)
        return textwrap.dedent(
            f"""
            You are the deep research engine for Project OS.

            Goal:
            - produce a high-signal research dossier that is coherent with the current Project OS repo
            - use web search aggressively, including official docs, papers, GitHub upstream repos, active forks, and satellites
            - explicitly say when no fork or satellite is stronger than the upstream

            Non-negotiable rules:
            - start from the repo snapshot below before recommending anything
            - prefer primary sources and concrete dates; use absolute dates like 2026-03-15 when recency matters
            - focus on integration value for Project OS, not generic hype
            - for every actionable recommendation, define concrete proofs or tests to obtain
            - if a repo looks exciting but does not fit Project OS today, put it in `a_etudier` or `a_rejeter`
            - do not invent local files; only reference repo touchpoints that appear in the repo snapshot or are obvious package/doc extensions

            Research kind:
            - {kind}

            Research question:
            - {question}

            Freshness target:
            - prioritize discoveries and updates from the last {recent_days} days when discussing current tooling or releases
            - for foundational papers and stable repos, older sources are acceptable

            Repo snapshot:
            {json.dumps(repo_context, ensure_ascii=True, indent=2, sort_keys=True)}

            Output requirements:
            - return strict JSON only
            - 3 to 8 recommendations maximum
            - `bucket` must be one of `a_faire`, `a_etudier`, or `a_rejeter`
            - `decision` must be one of `KEEP`, `ADAPT`, `DEFER`, or `REJECT`
            - every recommendation must include 1 to 4 primary sources with working URLs
            - `project_os_touchpoints` must name concrete packages, docs, or refactors inside Project OS
            - `proofs` must be executable checks, tests, or review gates
            """
        ).strip()

    def _call_research_model(self, *, request: dict[str, Any], prompt: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        api_key = self.secret_resolver.get_required("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        attempts: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for model_name, tool_payload in self._research_attempts():
            try:
                response = client.responses.create(
                    model=model_name,
                    reasoning={"effort": self.default_reasoning_effort},
                    input=prompt,
                    tools=[tool_payload],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "project_os_deep_research_result",
                            "schema": self._output_schema(),
                            "strict": True,
                            "description": "Structured output for a Project OS deep research dossier",
                        },
                        "verbosity": "high",
                    },
                    store=False,
                    metadata={
                        "job_id": str(request.get("job_id") or ""),
                        "kind": str(request.get("kind") or "audit"),
                    },
                )
                raw_payload = response.model_dump() if hasattr(response, "model_dump") else {"repr": repr(response)}
                raw_payload["attempts"] = attempts
                output_text = getattr(response, "output_text", None) or raw_payload.get("output_text")
                if not output_text:
                    raise RuntimeError("Deep research response returned no output_text.")
                structured = self._parse_json_object(str(output_text))
                structured["metadata"] = {
                    **dict(structured.get("metadata") or {}),
                    "model": model_name,
                    "tool_type": str(tool_payload["type"]),
                }
                return structured, raw_payload, self._extract_usage(raw_payload, response)
            except Exception as exc:
                attempts.append(
                    {
                        "model": model_name,
                        "tool_type": str(tool_payload["type"]),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                last_error = exc
        detail = "; ".join(f"{item['model']}:{item['tool_type']} -> {item['error_type']}" for item in attempts)
        raise RuntimeError(f"Deep research OpenAI call failed after fallbacks. {detail}") from last_error

    def _research_attempts(self) -> list[tuple[str, dict[str, Any]]]:
        candidates = [
            (self.default_model, {"type": "web_search", "search_context_size": "high"}),
            (self.default_model, {"type": "web_search_preview", "search_context_size": "high"}),
            ("gpt-5", {"type": "web_search", "search_context_size": "high"}),
            ("gpt-5", {"type": "web_search_preview", "search_context_size": "high"}),
        ]
        unique: list[tuple[str, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        for model_name, payload in candidates:
            key = (str(model_name).strip(), str(payload["type"]).strip())
            if not key[0] or key in seen:
                continue
            seen.add(key)
            unique.append((key[0], payload))
        return unique

    def _extract_usage(self, raw_payload: dict[str, Any], response: Any) -> dict[str, Any]:
        usage = raw_payload.get("usage")
        if usage is None and hasattr(response, "usage") and getattr(response, "usage") is not None:
            usage_obj = getattr(response, "usage")
            usage = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else dict(usage_obj)
        return dict(usage or {})

    def _parse_json_object(self, output_text: str) -> dict[str, Any]:
        raw = output_text.strip()
        if not raw:
            raise RuntimeError("Deep research output is empty.")
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            raise RuntimeError("Deep research output is not valid JSON.")
        payload = json.loads(raw[start : end + 1])
        if not isinstance(payload, dict):
            raise RuntimeError("Deep research output root must be a JSON object.")
        return payload

    def _render_dossier_markdown(
        self,
        *,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        structured: dict[str, Any],
        dossier_path: Path,
    ) -> str:
        kind = str(request.get("kind") or "audit").strip().lower()
        recommendations = [item for item in structured.get("recommendations", []) if isinstance(item, dict)]
        grouped = {
            "a_faire": [item for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_faire"],
            "a_etudier": [item for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_etudier"],
            "a_rejeter": [item for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_rejeter"],
        }
        lines = [
            f"# {request['title']}",
            "",
            "## Statut",
            "",
            "- `completed`",
            f"- genere le {datetime.now(timezone.utc).isoformat()}",
            f"- type: `{kind}`",
            "",
            "## Question de recherche",
            "",
            f"- {str(request.get('question') or '').strip()}",
            "",
            "## Synthese",
            "",
            *self._bulletize(structured.get("summary"), fallback="- synthese manquante"),
            "",
            "## Pourquoi on fait ca",
            "",
            *self._bulletize(structured.get("why_now")),
            "",
            "## Coherence Project OS",
            "",
            *self._bulletize(structured.get("repo_fit")),
            "",
            "## Point de depart repo",
            "",
            f"- branche active: `{repo_context.get('current_branch') or 'unknown'}`",
            "- packages coeur detectes:",
            *[f"  - `{item}`" for item in repo_context.get("core_packages", [])],
            "- fichiers modifies observes:",
            *[f"  - `{item}`" for item in repo_context.get("dirty_files", [])[:12]],
            "",
            "## A faire",
            "",
        ]
        lines.extend(self._render_recommendation_group(grouped["a_faire"]))
        lines.extend(["", "## A etudier", ""])
        lines.extend(self._render_recommendation_group(grouped["a_etudier"]))
        lines.extend(["", "## A rejeter pour maintenant", ""])
        lines.extend(self._render_recommendation_group(grouped["a_rejeter"]))
        lines.extend(
            [
                "",
                "## Preuves transverses a obtenir",
                "",
                *self._bulletize(structured.get("priority_actions")),
                "",
                "## Risques et angles morts",
                "",
                *self._bulletize(structured.get("risks")),
                "",
                "## Questions ouvertes",
                "",
                *self._bulletize(structured.get("open_questions")),
                "",
                "## Sources globales",
                "",
            ]
        )
        lines.extend(self._render_source_list(structured.get("global_sources")))
        if kind == "system":
            lines.extend(["", "## References locales relues", ""])
            for ref in repo_context.get("local_refs", []):
                relative = self._relative_link(dossier_path.parent, Path(str(ref["path"])))
                lines.append(f"- [{ref['relative_path']}]({relative})")
        return "\n".join(lines).rstrip() + "\n"

    def _render_recommendation_group(self, items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["- aucune piste retenue dans cette categorie"]
        lines: list[str] = []
        for item in items:
            system_name = str(item.get("system_name") or "Systeme non nomme").strip()
            decision = str(item.get("decision") or "ADAPT").strip().upper()
            lines.extend(
                [
                    f"### {system_name}",
                    "",
                    "Etat:",
                    "",
                    f"- `{decision}`",
                    "",
                    "Pourquoi il compte:",
                    "",
                    *self._bulletize(item.get("why")),
                    "",
                    "Ce qu'on recupere:",
                    "",
                    *self._bulletize(item.get("what_to_take")),
                    "",
                    "Ce qu'on n'importe pas:",
                    "",
                    *self._bulletize(item.get("what_not_to_take")),
                    "",
                    "Signal forks / satellites:",
                    "",
                    *self._bulletize(item.get("fork_signal")),
                    "",
                    "Ou ca entre dans Project OS:",
                    "",
                    *self._bulletize(item.get("project_os_touchpoints")),
                    "",
                    "Preuves a obtenir:",
                    "",
                    *self._bulletize(item.get("proofs")),
                    "",
                    "Sources primaires:",
                    "",
                ]
            )
            lines.extend(self._render_source_list(item.get("sources")))
            lines.append("")
        return lines[:-1] if lines and lines[-1] == "" else lines

    def _render_source_list(self, payload: Any) -> list[str]:
        items = payload if isinstance(payload, list) else []
        rendered: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("url") or "Source").strip()
            url = str(item.get("url") or "").strip()
            publisher = str(item.get("publisher") or "").strip()
            published_at = str(item.get("published_at") or "").strip()
            why = str(item.get("why") or "").strip()
            meta_parts = [part for part in (publisher, published_at) if part]
            meta_suffix = f" - {' | '.join(meta_parts)}" if meta_parts else ""
            why_suffix = f" - {why}" if why else ""
            if url:
                rendered.append(f"- [{title}]({url}){meta_suffix}{why_suffix}")
            else:
                rendered.append(f"- {title}{meta_suffix}{why_suffix}")
        return rendered or ["- source manquante"]

    def _completion_summary(self, *, request: dict[str, Any], structured: dict[str, Any]) -> str:
        recommendations = [item for item in structured.get("recommendations", []) if isinstance(item, dict)]
        counts = {
            "a_faire": sum(1 for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_faire"),
            "a_etudier": sum(1 for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_etudier"),
            "a_rejeter": sum(1 for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_rejeter"),
        }
        lines = [
            f"[Project OS] Deep research terminee: {request['title']}",
            f"Dossier mis a jour: {request.get('dossier_relative_path') or request.get('doc_name') or request.get('dossier_path')}",
            f"Buckets: A faire={counts['a_faire']} | A etudier={counts['a_etudier']} | A rejeter={counts['a_rejeter']}",
        ]
        for item in structured.get("priority_actions", [])[:3]:
            text = str(item or "").strip()
            if text:
                lines.append(f"- {text}")
        lines.append("Rapport Markdown joint a ce message.")
        return "\n".join(lines)

    def _failure_summary(self, *, request: dict[str, Any], error_payload: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"[Project OS] Deep research echouee: {request.get('title') or 'Deep Research'}",
                f"Dossier cible: {request.get('dossier_relative_path') or request.get('doc_name') or request.get('dossier_path')}",
                f"Erreur: {error_payload['error_type']} - {error_payload['error']}",
                "Le scaffold du dossier est conserve, mais la synthese finale n'a pas ete ecrite.",
            ]
        )

    def _launch_summary(self, request: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"[Project OS] Deep research lancee: {request['title']}",
                f"Dossier: {request.get('dossier_relative_path') or request.get('doc_name') or request.get('dossier_path')}",
                "La recherche web part maintenant, puis le dossier final reviendra ici avec le fichier Markdown.",
            ]
        )

    def _relative_link(self, base_dir: Path, target: Path) -> str:
        return os.path.relpath(target.resolve(strict=False), start=base_dir.resolve(strict=False)).replace("\\", "/")

    def _validated_dossier_path(self, raw_path: str) -> Path:
        dossier_path = Path(raw_path).resolve(strict=False)
        try:
            relative = dossier_path.relative_to(self.repo_root)
        except ValueError as exc:
            raise PermissionError(f"Deep research dossier path must stay inside repo_root: {dossier_path}") from exc
        if relative.parts[:2] not in {("docs", "systems"), ("docs", "audits")}:
            raise PermissionError(f"Deep research dossier path must stay under docs/systems or docs/audits: {dossier_path}")
        if dossier_path.suffix.lower() != ".md":
            raise PermissionError(f"Deep research dossier path must be a markdown file: {dossier_path}")
        return dossier_path

    def _write_repo_markdown(self, destination: Path, content: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_suffix(f"{destination.suffix}.tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(destination)

    def _read_excerpt(self, path: Path, max_chars: int) -> str:
        try:
            payload = path.read_text(encoding="utf-8")
        except Exception:
            return ""
        if len(payload) <= max_chars:
            return payload
        return f"{payload[:max_chars].rstrip()}\n...[truncated]"

    def _git_output(self, *args: str) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except Exception:
            return ""
        return completed.stdout.strip()

    def _git_lines(self, *args: str) -> list[str]:
        output = self._git_output(*args)
        return [line for line in output.splitlines() if line.strip()]

    def _job_root(self, job_id: str) -> Path:
        folder = self.path_policy.ensure_allowed_write(self.paths.runtime_root / "deep_research" / job_id)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _write_managed_json(self, destination: Path, payload: Any) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = self.path_policy.ensure_allowed_write(destination)
        target.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    def _write_managed_text(self, destination: Path, payload: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = self.path_policy.ensure_allowed_write(destination)
        target.write_text(payload, encoding="utf-8")

    def _bulletize(self, payload: Any, *, fallback: str = "- a remplir") -> list[str]:
        if isinstance(payload, str):
            text = payload.strip()
            return [f"- {text}"] if text else [fallback]
        if isinstance(payload, list):
            rendered = [f"- {str(item).strip()}" for item in payload if str(item).strip()]
            return rendered or [fallback]
        return [fallback]

    def _output_schema(self) -> dict[str, Any]:
        source_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "url": {"type": "string"},
                "publisher": {"type": "string"},
                "published_at": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["title", "url", "publisher", "published_at", "why"],
        }
        recommendation_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "bucket": {"type": "string", "enum": ["a_faire", "a_etudier", "a_rejeter"]},
                "system_name": {"type": "string"},
                "decision": {"type": "string", "enum": ["KEEP", "ADAPT", "DEFER", "REJECT"]},
                "why": {"type": "array", "items": {"type": "string"}},
                "what_to_take": {"type": "array", "items": {"type": "string"}},
                "what_not_to_take": {"type": "array", "items": {"type": "string"}},
                "fork_signal": {"type": "array", "items": {"type": "string"}},
                "project_os_touchpoints": {"type": "array", "items": {"type": "string"}},
                "proofs": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": source_schema},
            },
            "required": [
                "bucket",
                "system_name",
                "decision",
                "why",
                "what_to_take",
                "what_not_to_take",
                "fork_signal",
                "project_os_touchpoints",
                "proofs",
                "sources",
            ],
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "why_now": {"type": "array", "items": {"type": "string"}},
                "repo_fit": {"type": "array", "items": {"type": "string"}},
                "priority_actions": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": recommendation_schema},
                "risks": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "global_sources": {"type": "array", "items": source_schema},
                "metadata": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "model": {"type": "string"},
                        "tool_type": {"type": "string"},
                    },
                    "required": ["model", "tool_type"],
                },
            },
            "required": [
                "summary",
                "why_now",
                "repo_fit",
                "priority_actions",
                "recommendations",
                "risks",
                "open_questions",
                "global_sources",
                "metadata",
            ],
        }
