from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover - optional dependency in tests
    Anthropic = None  # type: ignore[assignment]

from openai import OpenAI

from .api_runs.service import ApiRunService
from .costing import estimate_text_tokens, estimate_usage_cost_eur
from .deep_research_pdf import build_archive_stem, build_seo_slug, render_deep_research_pdf
from .models import (
    ApiRunStatus,
    OperatorChannelHint,
    OutputQuarantineReason,
    RunLifecycleEventKind,
    TraceEntityKind,
    TraceRelationKind,
    new_id,
)
from .observability import StructuredLogger
from .paths import PathPolicy, ProjectPaths
from .research_scaffold import (
    core_packages,
    existing_local_refs,
    infer_research_intensity,
    infer_research_profile,
)
from .runtime.journal import LocalJournal
from .secrets import SecretResolver

_MAX_LOCAL_REF_CHARS = 2_800
_MAX_LOCAL_REF_COUNT = 7
_MAX_DIRTY_FILE_LINES = 40
_MAX_RUNTIME_EVIDENCE = 8
_COMPLEX_MAX_WORKERS = 3
_EXTREME_MAX_WORKERS = 4
_VALID_RESEARCH_PROFILES = {"project_audit", "component_discovery", "domain_audit"}
_VALID_RESEARCH_INTENSITIES = {"simple", "complex", "extreme"}


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
        research_model: str,
        scout_model: str,
        translation_model: str,
        extreme_debug_enabled: bool,
        extreme_debug_provider: str,
        extreme_debug_model: str,
        extreme_debug_log_enabled: bool,
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
        self.research_model = str(research_model).strip() or "gpt-5"
        self.scout_model = str(scout_model).strip() or self.research_model
        self.translation_model = str(translation_model).strip() or self.research_model
        self.extreme_debug_enabled = bool(extreme_debug_enabled)
        self.extreme_debug_provider = str(extreme_debug_provider).strip().lower() or "anthropic"
        self.extreme_debug_model = str(extreme_debug_model).strip() or "claude-haiku-4-5-20251001"
        self.extreme_debug_log_enabled = bool(extreme_debug_log_enabled)

    def launch_job_from_gateway(self, *, event, scaffold: dict[str, Any]) -> dict[str, Any]:
        job_id = new_id("deep_research")
        job_root = self._job_root(job_id)
        created_at = datetime.now(timezone.utc).isoformat()
        title = str(scaffold.get("title") or "Deep Research").strip()
        kind = str(scaffold.get("kind") or "audit").strip().lower()
        question = str(event.message.text or "").strip()
        research_profile = self._request_research_profile(
            kind=kind,
            question=question,
            research_profile=scaffold.get("research_profile"),
        )
        research_intensity = self._request_research_intensity(
            kind=kind,
            question=question,
            research_profile=research_profile,
            research_intensity=scaffold.get("research_intensity"),
        )
        research_route = self._research_route(research_intensity=research_intensity)
        request = {
            "job_id": job_id,
            "title": title,
            "kind": kind,
            "research_profile": research_profile,
            "research_intensity": research_intensity,
            "recommended_profile": str(scaffold.get("recommended_profile") or research_profile),
            "recommended_intensity": str(scaffold.get("recommended_intensity") or research_intensity),
            "question": question,
            "keywords": [str(item).strip() for item in scaffold.get("keywords", []) if str(item).strip()],
            "recent_days": int(scaffold.get("recent_days") or 30),
            "dossier_path": str(scaffold.get("path") or ""),
            "dossier_relative_path": str(scaffold.get("relative_path") or "").strip() or None,
            "doc_name": str(scaffold.get("doc_name") or Path(str(scaffold.get("path") or "")).name).strip() or None,
            "seo_slug": build_seo_slug(title),
            "archive_stem": build_archive_stem(title=title, kind=kind, created_at=created_at),
            "source_surface": str(event.surface or "").strip(),
            "source_channel": str(event.message.channel or "").strip(),
            "actor_id": str(event.message.actor_id or "").strip(),
            "source_event_id": str(event.event_id or "").strip(),
            "source_message_id": str(event.message.metadata.get("message_id") or event.message.message_id or "").strip(),
            "reply_to": self._reply_to_for_event(event),
            "reply_target": self._reply_target_for_event(event),
            "created_at": created_at,
            "estimated_api_provider": research_route["provider"],
            "estimated_api_model": research_route["model"],
            "estimated_api_label": research_route["label"],
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
                "research_profile": research_profile,
                "research_intensity": research_intensity,
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

    def run_lane_path(self, *, lane_request_path: str) -> dict[str, Any]:
        request_path = self.path_policy.ensure_allowed_write(lane_request_path)
        if not request_path.exists():
            raise FileNotFoundError(f"Unknown deep research lane payload: {request_path}")
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise RuntimeError("Deep research lane payload must be a JSON object.")
        return self.run_lane_request(lane_request=request, lane_root=request_path.parent)

    def run_lane_request(self, *, lane_request: dict[str, Any], lane_root: Path) -> dict[str, Any]:
        lane = str(lane_request.get("lane") or lane_request.get("phase") or "").strip().lower()
        if not lane:
            raise RuntimeError("Deep research lane payload is missing `lane`.")
        started_at = datetime.now(timezone.utc).isoformat()
        self._write_managed_json(
            lane_root / "status.json",
            {
                "lane": lane,
                "status": "running",
                "updated_at": started_at,
            },
        )
        try:
            request = dict(lane_request.get("request") or {})
            request["_debug_root"] = str(lane_root)
            repo_context = dict(lane_request.get("repo_context") or {})
            execution_plan = dict(lane_request.get("execution_plan") or {})
            planner_payload = dict(lane_request.get("planner_payload") or {})
            cheap_scout_swarm_payload = dict(lane_request.get("cheap_scout_swarm_payload") or {})
            lane_brief = dict(lane_request.get("lane_brief") or {})
            previous_response_id = str(lane_request.get("previous_response_id") or "").strip() or None

            payload: dict[str, Any]
            raw_response: dict[str, Any] | None = None
            if lane == "repo":
                payload = self._build_repo_scout(repo_context=repo_context, execution_plan=execution_plan)
            elif lane == "cheap_scout_swarm":
                payload = self._run_cheap_scout_swarm(
                    request=request,
                    repo_context=repo_context,
                    execution_plan=execution_plan,
                    planner_payload=planner_payload,
                    previous_response_id_override=previous_response_id,
                    force_store=True,
                )
                raw_response = {"phase": "cheap_scout_swarm", "response_id": payload.get("_response_id")}
            elif lane == "skeptic":
                scout_bundle = dict(lane_request.get("scout_bundle") or {})
                payload = self._run_skeptic_pass(
                    request=request,
                    execution_plan=execution_plan,
                    planner_payload=planner_payload,
                    scout_bundle=scout_bundle,
                    previous_response_id_override=previous_response_id,
                    force_store=True,
                )
                raw_response = {"phase": "skeptic", "response_id": payload.get("_response_id")}
            else:
                payload = self._run_external_scout_lane(
                    lane=lane,
                    request=request,
                    repo_context=repo_context,
                    execution_plan=execution_plan,
                    planner_payload=planner_payload,
                    lane_brief=lane_brief,
                    previous_response_id_override=previous_response_id,
                    force_store=True,
                )
                raw_response = {"phase": lane, "response_id": payload.get("_response_id")}

            result = {
                **payload,
                "status": str(payload.get("status") or "completed").strip().lower() or "completed",
                "_response_id": str(payload.get("_response_id") or "").strip() or None,
                "_previous_response_id": previous_response_id,
                "_stored": bool(payload.get("_stored")),
                "_provider": str(payload.get("_provider") or "").strip() or None,
                "_model": str(payload.get("_model") or "").strip() or None,
                "_lane_root": str(lane_root),
            }
            self._write_managed_json(lane_root / "result.json", result)
            if raw_response is not None:
                self._write_managed_json(lane_root / "response.json", raw_response)
            completed_payload = {
                "lane": lane,
                "status": result["status"],
                "response_id": result.get("_response_id"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_managed_json(lane_root / "status.json", completed_payload)
            return completed_payload
        except Exception as exc:
            error_payload = {
                "lane": lane,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_managed_json(lane_root / "status.json", error_payload)
            self._write_managed_json(lane_root / "result.json", error_payload)
            raise

    def run_job_request(self, *, request: dict[str, Any], job_root: Path) -> dict[str, Any]:
        request = dict(request)
        request["_debug_root"] = str(job_root)
        job_id = str(request.get("job_id") or new_id("deep_research"))
        self._write_managed_json(
            job_root / "status.json",
            {"job_id": job_id, "status": "running", "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        try:
            repo_context = self._build_repo_context(request)
            self._write_managed_json(job_root / "repo_context.json", repo_context)
            execution_plan = self._build_execution_plan(request=request, repo_context=repo_context)
            self._write_managed_json(job_root / "execution_plan.json", execution_plan)
            self._write_mesh_manifest(job_root=job_root, manifest=dict(execution_plan.get("mesh_manifest") or {}))
            prompt, structured, raw_payload, usage = self._run_research_pipeline(
                request=request,
                repo_context=repo_context,
                execution_plan=execution_plan,
                job_root=job_root,
            )
            self._write_managed_json(job_root / "execution_plan.json", execution_plan)
            self._write_mesh_manifest(job_root=job_root, manifest=dict(execution_plan.get("mesh_manifest") or {}))
            self._write_managed_text(job_root / "prompt.md", prompt)
            self._write_managed_json(job_root / "response.json", raw_payload)
            structured = self._enrich_structured_result(
                request=request,
                structured=structured,
                execution_plan=execution_plan,
            )
            self._validate_structured_result(request=request, structured=structured)
            self._write_managed_json(job_root / "result.json", structured)
            reader_structured = self._translate_structured_for_reader(request=request, structured=structured)
            reader_structured = self._apply_reader_overrides(
                canonical=structured,
                translated=reader_structured,
            )
            self._validate_structured_result(request=request, structured=reader_structured)
            self._write_managed_json(job_root / "reader_fr.json", reader_structured)
            usage_summary = self._summarize_model_debug_entries(job_root=job_root)
            self._write_managed_json(job_root / "usage_summary.json", usage_summary)
            dossier_path = self._validated_dossier_path(str(request.get("dossier_path") or ""))
            dossier_markdown = self._render_dossier_markdown(
                request=request,
                repo_context=repo_context,
                structured=structured,
                dossier_path=dossier_path,
            )
            self._write_repo_markdown(dossier_path, dossier_markdown)
            archive_bundle = self._archive_bundle(
                request=request,
                job_root=job_root,
                dossier_path=dossier_path,
                dossier_markdown=dossier_markdown,
                structured=structured,
                reader_structured=reader_structured,
                repo_context=repo_context,
            )
            summary_text = self._completion_summary(request=request, structured=reader_structured)
            attachments = [
                {
                    "path": str(archive_bundle["pdf_path"]),
                    "name": str(Path(str(archive_bundle["pdf_path"])).name),
                    "mime_type": "application/pdf",
                },
                {
                    "path": str(dossier_path),
                    "name": str(request.get("doc_name") or dossier_path.name),
                    "mime_type": "text/markdown",
                },
            ]
            delivery = self.api_runs.publish_operator_update(
                title=f"Deep research terminee: {reader_structured.get('seo_title') or structured.get('seo_title') or request['title']}",
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
                    "archive_path": archive_bundle["archive_relative_path"],
                    "archive_root": archive_bundle["archive_root"],
                    "pdf_path": str(archive_bundle["pdf_path"]),
                    "usage": usage,
                    "usage_summary": usage_summary,
                    "model": structured.get("metadata", {}).get("model"),
                    "tool_type": structured.get("metadata", {}).get("tool_type"),
                    "research_profile": structured.get("research_profile") or request.get("research_profile"),
                    "research_intensity": structured.get("research_intensity") or request.get("research_intensity"),
                    "canonical_language": "en",
                    "reader_language": "fr",
                },
            )
            payload = {
                "job_id": job_id,
                "status": "completed",
                "research_profile": structured.get("research_profile") or request.get("research_profile"),
                "research_intensity": structured.get("research_intensity") or request.get("research_intensity"),
                "dossier_path": str(dossier_path),
                "archive_root": archive_bundle["archive_root"],
                "archive_relative_path": archive_bundle["archive_relative_path"],
                "pdf_path": str(archive_bundle["pdf_path"]),
                "delivery_id": delivery.get("delivery_id"),
                "usage": usage,
                "usage_summary": usage_summary,
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

    def _spawn_lane_worker(self, lane_request_path: Path) -> subprocess.Popen[Any]:
        entrypoint = self.repo_root / "scripts" / "project_os_entry.py"
        command = [
            sys.executable,
            str(entrypoint),
            "--config-path",
            str(self.config_path),
            "--policy-path",
            str(self.policy_path),
            "research",
            "run-lane",
            "--lane-request",
            str(lane_request_path),
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

    def _lane_root(self, *, job_root: Path, lane: str) -> Path:
        return self.path_policy.ensure_allowed_write(job_root / "lanes" / str(lane).strip().lower())

    def _write_mesh_manifest(self, *, job_root: Path, manifest: dict[str, Any]) -> None:
        self._write_managed_json(job_root / "mesh_manifest.json", manifest)

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

    def _request_research_profile(self, *, kind: str, question: str, research_profile: Any = None) -> str:
        profile = str(research_profile or "").strip().lower()
        if profile in _VALID_RESEARCH_PROFILES:
            return profile
        inferred = infer_research_profile(raw=question, kind=kind)
        return inferred if inferred in _VALID_RESEARCH_PROFILES else "domain_audit"

    def _request_research_intensity(
        self,
        *,
        kind: str,
        question: str,
        research_profile: str,
        research_intensity: Any = None,
    ) -> str:
        intensity = str(research_intensity or "").strip().lower()
        if intensity in _VALID_RESEARCH_INTENSITIES:
            return intensity
        inferred = infer_research_intensity(
            raw=question,
            kind=kind,
            research_profile=research_profile,
        )
        return inferred if inferred in _VALID_RESEARCH_INTENSITIES else "simple"

    def _provider_available(self, provider: str) -> bool:
        normalized = str(provider or "").strip().lower()
        if normalized == "openai":
            return self.secret_resolver.lookup("OPENAI_API_KEY").available
        if normalized == "anthropic":
            return Anthropic is not None and self.secret_resolver.lookup("ANTHROPIC_API_KEY").available
        return False

    def _research_route(
        self,
        *,
        research_intensity: str,
        translation: bool = False,
    ) -> dict[str, Any]:
        intensity = str(research_intensity or "").strip().lower()
        if (
            not translation
            and intensity == "extreme"
            and self.extreme_debug_enabled
            and self.extreme_debug_provider == "anthropic"
            and self._provider_available("anthropic")
        ):
            return {
                "provider": "anthropic",
                "model": self.extreme_debug_model,
                "label": f"anthropic/{self.extreme_debug_model}",
                "debug": True,
                "research_model": self.extreme_debug_model,
            }
        target_model = self.translation_model if translation else self.research_model
        return {
            "provider": "openai",
            "model": target_model,
            "label": f"openai/{target_model}",
            "debug": False,
            "research_model": target_model,
        }

    def _research_route_for_request(self, request: dict[str, Any], *, translation: bool = False) -> dict[str, Any]:
        return self._research_route(
            research_intensity=self._request_research_intensity(
                kind=str(request.get("kind") or "audit"),
                question=str(request.get("question") or request.get("title") or ""),
                research_profile=self._request_research_profile(
                    kind=str(request.get("kind") or "audit"),
                    question=str(request.get("question") or request.get("title") or ""),
                    research_profile=request.get("research_profile") or request.get("recommended_profile"),
                ),
                research_intensity=request.get("research_intensity") or request.get("recommended_intensity"),
            ),
            translation=translation,
        )

    def _openai_planner_model(self) -> str:
        return self.research_model

    def _openai_scout_model(self, *, lane: str | None = None) -> str:
        normalized_lane = str(lane or "").strip().lower()
        if normalized_lane == "cheap_scout_swarm":
            return self.scout_model
        return self.research_model

    def _openai_translation_candidates(self) -> list[str]:
        candidates = [self.translation_model, self.research_model, "gpt-5"]
        ordered: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = str(candidate or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _update_continuity_strategy_for_provider(
        self,
        *,
        response_continuity: dict[str, Any] | None,
        provider: str,
    ) -> None:
        if not isinstance(response_continuity, dict) or not bool(response_continuity.get("enabled")):
            return
        normalized = str(provider or "").strip().lower()
        notes = response_continuity.setdefault("notes", [])
        if not isinstance(notes, list):
            notes = []
            response_continuity["notes"] = notes
        if normalized == "anthropic":
            response_continuity["strategy"] = "manual_prompt_chain"
            note = "Anthropic debug route records per-phase anchors and carries curated context through prompts."
            if note not in notes:
                notes.append(note)
        elif normalized == "openai":
            response_continuity["strategy"] = "responses_previous_response_id"

    @staticmethod
    def _sanitize_previous_response_id_for_provider(provider: str, response_id: str | None) -> str | None:
        candidate = str(response_id or "").strip()
        if not candidate:
            return None
        normalized_provider = str(provider or "").strip().lower()
        if normalized_provider == "openai":
            return candidate if candidate.startswith("resp_") else None
        if normalized_provider == "anthropic":
            return candidate if candidate.startswith("msg_") else None
        return candidate

    def _debug_root_from_path(self, raw_path: Any) -> Path | None:
        text = str(raw_path or "").strip()
        if not text:
            return None
        try:
            return self.path_policy.ensure_allowed_write(Path(text))
        except Exception:
            return None

    def _append_model_debug_entry(self, *, debug_root: Path | None, entry: dict[str, Any]) -> None:
        if not self.extreme_debug_log_enabled or debug_root is None:
            return
        debug_root.mkdir(parents=True, exist_ok=True)
        path = self.path_policy.ensure_allowed_write(debug_root / "model_debug.jsonl")
        line = json.dumps(entry, ensure_ascii=True, sort_keys=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _collect_model_debug_entries(self, *, job_root: Path) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in [job_root / "model_debug.jsonl", *sorted((job_root / "lanes").glob("*/model_debug.jsonl"))]:
            if not path.exists():
                continue
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                text = raw_line.strip()
                if not text:
                    continue
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        parsed.setdefault("log_path", str(path))
                        entries.append(parsed)
                except Exception:
                    continue
        return entries

    def _summarize_model_debug_entries(self, *, job_root: Path) -> dict[str, Any]:
        entries = self._collect_model_debug_entries(job_root=job_root)
        total_cost = 0.0
        total_counted_input_tokens = 0
        total_actual_input_tokens = 0
        total_actual_output_tokens = 0
        providers: dict[str, dict[str, Any]] = {}
        phases: dict[str, dict[str, Any]] = {}
        for entry in entries:
            provider = str(entry.get("provider") or "unknown").strip().lower()
            phase = str(entry.get("phase") or "unknown").strip().lower()
            cost = float(entry.get("estimated_cost_eur") or 0.0)
            counted_input_tokens = int(entry.get("counted_input_tokens") or 0)
            usage = entry.get("actual_usage") if isinstance(entry.get("actual_usage"), dict) else {}
            actual_input_tokens = int(usage.get("input_tokens") or 0)
            actual_output_tokens = int(usage.get("output_tokens") or 0)
            total_cost += cost
            total_counted_input_tokens += counted_input_tokens
            total_actual_input_tokens += actual_input_tokens
            total_actual_output_tokens += actual_output_tokens
            provider_bucket = providers.setdefault(
                provider,
                {
                    "call_count": 0,
                    "estimated_cost_eur": 0.0,
                    "counted_input_tokens": 0,
                    "actual_input_tokens": 0,
                    "actual_output_tokens": 0,
                },
            )
            provider_bucket["call_count"] += 1
            provider_bucket["estimated_cost_eur"] = round(float(provider_bucket["estimated_cost_eur"]) + cost, 6)
            provider_bucket["counted_input_tokens"] += counted_input_tokens
            provider_bucket["actual_input_tokens"] += actual_input_tokens
            provider_bucket["actual_output_tokens"] += actual_output_tokens
            phase_bucket = phases.setdefault(phase, {"call_count": 0, "provider": provider, "estimated_cost_eur": 0.0})
            phase_bucket["call_count"] += 1
            phase_bucket["estimated_cost_eur"] = round(float(phase_bucket["estimated_cost_eur"]) + cost, 6)
        return {
            "entry_count": len(entries),
            "estimated_total_cost_eur": round(total_cost, 6),
            "counted_input_tokens": total_counted_input_tokens,
            "actual_input_tokens": total_actual_input_tokens,
            "actual_output_tokens": total_actual_output_tokens,
            "providers": providers,
            "phases": phases,
        }

    @staticmethod
    def _extract_anthropic_text_blocks(response_payload: Any) -> str:
        content = getattr(response_payload, "content", None)
        if content is None and isinstance(response_payload, dict):
            content = response_payload.get("content")
        blocks: list[str] = []
        for item in content or []:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    blocks.append(str(item["text"]))
                continue
            if getattr(item, "type", None) == "text" and getattr(item, "text", None):
                blocks.append(str(item.text))
        if not blocks:
            raise RuntimeError("Anthropic Messages API returned no text content")
        return "\n".join(blocks).strip()

    @staticmethod
    def _extract_anthropic_usage(response_payload: Any) -> dict[str, Any]:
        usage_obj = getattr(response_payload, "usage", None)
        if usage_obj is None and isinstance(response_payload, dict):
            usage_obj = response_payload.get("usage")
        if usage_obj is None:
            return {}
        if hasattr(usage_obj, "model_dump"):
            dumped = usage_obj.model_dump()
            if isinstance(dumped, dict):
                return dumped
        if isinstance(usage_obj, dict):
            return dict(usage_obj)
        usage: dict[str, Any] = {}
        for field in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            value = getattr(usage_obj, field, None)
            if value is not None:
                usage[field] = value
        return usage

    def _anthropic_client(self) -> Any:
        if Anthropic is None:
            raise RuntimeError("anthropic package is not installed")
        api_key = self.secret_resolver.get_required("ANTHROPIC_API_KEY")
        return Anthropic(api_key=api_key)

    def _anthropic_web_search_tool(self, *, phase: str) -> dict[str, Any]:
        max_uses = 2
        if phase in {"cheap_scout_swarm", "official_docs", "github", "papers"}:
            max_uses = 4
        elif phase == "final_synthesis":
            max_uses = 3
        return {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_uses,
        }

    def _count_anthropic_tokens(
        self,
        *,
        model: str,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        client = self._anthropic_client()
        response = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            tools=tools or [],
        )
        if hasattr(response, "model_dump"):
            dumped = response.model_dump()
            if isinstance(dumped, dict):
                return dumped
        if isinstance(response, dict):
            return dict(response)
        return {"input_tokens": getattr(response, "input_tokens", None)}

    @staticmethod
    def _anthropic_tooling_cost_eur(usage: dict[str, Any]) -> float:
        server_tool_use = usage.get("server_tool_use") if isinstance(usage, dict) else None
        if not isinstance(server_tool_use, dict):
            return 0.0
        web_search_requests = int(server_tool_use.get("web_search_requests") or 0)
        if web_search_requests <= 0:
            return 0.0
        usd = (web_search_requests / 1000.0) * 10.0
        return round(usd * 0.92, 6)

    def _estimate_provider_usage_cost_eur(self, *, provider: str, model: str | None, usage: dict[str, Any]) -> float:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        base_cost = estimate_usage_cost_eur(model=model, input_tokens=input_tokens, output_tokens=output_tokens)
        if str(provider or "").strip().lower() == "anthropic":
            return round(base_cost + self._anthropic_tooling_cost_eur(usage), 6)
        return base_cost

    def estimate_run(self, *, request: dict[str, Any]) -> dict[str, Any]:
        kind = str(request.get("kind") or "audit").strip().lower() or "audit"
        question = str(request.get("question") or request.get("title") or "").strip()
        research_profile = self._request_research_profile(
            kind=kind,
            question=question,
            research_profile=request.get("research_profile") or request.get("recommended_profile"),
        )
        research_intensity = self._request_research_intensity(
            kind=kind,
            question=question,
            research_profile=research_profile,
            research_intensity=request.get("research_intensity") or request.get("recommended_intensity"),
        )
        execution_plan = self._build_execution_plan(
            request={
                **request,
                "kind": kind,
                "question": question,
                "research_profile": research_profile,
                "research_intensity": research_intensity,
            },
            repo_context={},
        )
        keyword_count = len([item for item in request.get("keywords", []) if str(item).strip()])
        recent_days = int(request.get("recent_days") or 30)
        research_route = self._research_route(research_intensity=research_intensity)
        phase_costs = {
            "repo_context": 0.04,
            "single_research_pass": 0.35,
            "light_source_scoring": 0.03,
            "reader_translation": 0.12,
            "render_and_archive": 0.03,
            "planner": 0.10,
            "repo_scout": 0.03,
            "official_docs_scout": 0.18,
            "github_scout": 0.16,
            "skeptic_optional": 0.06,
            "expert_synthesis": 0.24,
            "cheap_scout_swarm": 0.08,
            "papers_scout": 0.18,
            "source_safety_gate": 0.04,
            "skeptic": 0.06,
        }
        base = {"audit": 0.28, "system": 0.32}.get(kind, 0.30)
        profile_cost = {
            "domain_audit": 0.05,
            "component_discovery": 0.12,
            "project_audit": 0.18,
        }.get(research_profile, 0.08)
        estimated_cost = base + profile_cost
        estimated_cost += sum(phase_costs.get(str(phase), 0.05) for phase in execution_plan.get("phases", []))
        estimated_cost += max(len(self._as_token_list(execution_plan.get("scout_lanes"))) - 1, 0) * 0.10
        estimated_cost += min(keyword_count, 8) * 0.02
        if recent_days > 45:
            estimated_cost += 0.06
        mesh_level = str(execution_plan.get("mesh_level") or "single").strip().lower()
        estimated_cost += {"single": 0.0, "in_process_parallel": 0.16, "child_worker_mesh": 0.38}.get(mesh_level, 0.0)
        if bool(execution_plan.get("planner_required")):
            estimated_cost += 0.06
        if research_intensity in {"complex", "extreme"}:
            estimated_cost += 0.05  # reputation scoring / persistence overhead
            estimated_cost += 0.03  # continuity / metadata overhead
        if research_intensity == "extreme":
            estimated_cost += 0.08  # mesh coordination
            estimated_cost -= 0.06  # continuity savings vs fully stateless equivalent
        if bool((execution_plan.get("safety_gate") or {}).get("mandatory")):
            estimated_cost += 0.08
        time_score = float(len(execution_plan.get("phases", [])))
        time_score += max(len(self._as_token_list(execution_plan.get("scout_lanes"))) - 1, 0) * 0.9
        if recent_days > 45:
            time_score += 0.4
        if research_profile == "project_audit":
            time_score += 0.5
        if mesh_level == "in_process_parallel":
            time_score -= 1.1
        elif mesh_level == "child_worker_mesh":
            time_score -= 1.6
        if bool((execution_plan.get("safety_gate") or {}).get("mandatory")):
            time_score += 0.7
        estimated_time_band = "long" if time_score >= 9.5 else "moyen"
        return {
            "kind": kind,
            "research_profile": research_profile,
            "research_intensity": research_intensity,
            "estimated_cost_eur": round(estimated_cost, 2),
            "estimated_time_band": estimated_time_band,
            "estimated_api_provider": research_route["provider"],
            "estimated_api_model": research_route["model"],
            "estimated_api_label": research_route["label"],
            "execution_plan": execution_plan,
        }

    def _recent_runtime_evidence(self, *, limit: int = _MAX_RUNTIME_EVIDENCE) -> list[dict[str, Any]]:
        rows = self.journal.database.fetchall(
            """
            SELECT event_type, source, payload_json, created_at
            FROM journal_events
            ORDER BY created_at DESC
            LIMIT 48
            """
        )
        evidence: list[dict[str, Any]] = []
        for row in rows:
            event_type = str(row["event_type"] or "").strip()
            source = str(row["source"] or "").strip()
            if not self._is_runtime_evidence_event(event_type=event_type, source=source):
                continue
            payload: dict[str, Any] = {}
            raw_payload = str(row["payload_json"] or "").strip()
            if raw_payload:
                try:
                    parsed = json.loads(raw_payload)
                    if isinstance(parsed, dict):
                        payload = parsed
                except Exception:
                    payload = {}
            evidence.append(
                {
                    "created_at": str(row["created_at"] or "").strip(),
                    "source": source,
                    "event_type": event_type,
                    "summary": self._summarize_runtime_event(event_type=event_type, payload=payload),
                }
            )
            if len(evidence) >= limit:
                break
        return evidence

    def _is_runtime_evidence_event(self, *, event_type: str, source: str) -> bool:
        normalized_source = str(source or "").strip().lower()
        normalized_type = str(event_type or "").strip().lower()
        if normalized_source not in {"gateway", "deep_research", "api_runs"}:
            return False
        return any(
            token in normalized_type
            for token in (
                "deep_research",
                "delivery",
                "approval",
                "failed",
                "backlog",
                "launch",
                "selection",
                "runtime",
            )
        )

    def _summarize_runtime_event(self, *, event_type: str, payload: dict[str, Any]) -> str:
        important_keys = (
            "status",
            "phase",
            "error_type",
            "error",
            "research_profile",
            "research_intensity",
            "delivery_id",
            "reply_target",
        )
        parts = [f"event={event_type}"]
        for key in important_keys:
            value = payload.get(key)
            text = str(value or "").strip()
            if text:
                parts.append(f"{key}={text}")
        if len(parts) == 1 and payload:
            first_key = next(iter(payload.keys()))
            first_value = str(payload.get(first_key) or "").strip()
            if first_value:
                parts.append(f"{first_key}={first_value}")
        return " | ".join(parts)

    def _record_auxiliary_failure(self, *, request: dict[str, Any], phase: str, exc: Exception) -> str:
        note = f"{phase} auxiliary pass failed with {type(exc).__name__}: {exc}"
        self.journal.append(
            "deep_research_auxiliary_phase_failed",
            "deep_research",
            {
                "job_id": str(request.get("job_id") or "").strip() or None,
                "phase": phase,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "research_profile": request.get("research_profile"),
                "research_intensity": request.get("research_intensity"),
            },
        )
        return note

    def _empty_source_trust_summary(self) -> dict[str, Any]:
        return {
            "score_mode": "none",
            "counts": {
                "trusted_primary": 0,
                "trusted_ecosystem": 0,
                "neutral_secondary": 0,
                "weak_signal": 0,
                "quarantined": 0,
            },
            "evidence_manifest": [],
            "trusted_domains": [],
            "trusted_lanes": [],
            "lane_counts": {},
            "domain_counts": {},
            "observation_count": 0,
            "average_score": 0.0,
            "history_used": False,
            "contradiction_count": 0,
            "contradiction_notes": [],
        }

    def _reputation_mode(self, *, research_intensity: str) -> str:
        intensity = str(research_intensity or "").strip().lower()
        if intensity == "simple":
            return "light"
        if intensity == "complex":
            return "medium"
        return "full"

    def _normalize_source_url(self, url: str) -> str:
        raw = str(url or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path or ""
        query_pairs = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=False)
            if not key.lower().startswith(("utm_", "fbclid", "gclid", "session", "sid", "ref"))
        ]
        if netloc == "github.com":
            segments = [segment for segment in path.split("/") if segment]
            if len(segments) >= 2:
                path = "/" + "/".join(segments[:2])
        if netloc == "arxiv.org":
            match = re.search(r"/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?", path)
            if match:
                path = f"/abs/{match.group(1)}"
        normalized = urlunparse((scheme, netloc, path.rstrip("/"), "", urlencode(query_pairs), ""))
        return normalized.rstrip("?")

    def _source_kind(self, *, domain: str, publisher: str, normalized_url: str) -> str:
        lowered_domain = str(domain or "").lower()
        lowered_publisher = str(publisher or "").lower()
        lowered_url = str(normalized_url or "").lower()
        if not lowered_url:
            return "local_repo" if lowered_publisher == "local_repo" else "unknown"
        if "github.com" in lowered_domain:
            return "github_repo"
        if "arxiv.org" in lowered_domain:
            return "paper"
        if lowered_domain.endswith(".gov") or lowered_domain.endswith(".edu"):
            return "official_doc"
        if any(token in lowered_domain for token in ("docs.", "readthedocs.io", "openai.com", "anthropic.com")):
            return "official_doc"
        if any(token in lowered_domain for token in ("pypi.org", "npmjs.com", "huggingface.co")):
            return "ecosystem_registry"
        if any(token in lowered_domain for token in ("medium.com", "substack.com", "dev.to", "youtube.com")):
            return "blog"
        return "web_page"

    def _normalized_source_identity(self, source: dict[str, Any]) -> dict[str, Any]:
        normalized_url = self._normalize_source_url(str(source.get("url") or ""))
        publisher = str(source.get("publisher") or "").strip()
        title = str(source.get("title") or "").strip()
        domain = self._domain_from_source_url(normalized_url)
        source_kind = self._source_kind(domain=domain, publisher=publisher, normalized_url=normalized_url)
        if normalized_url:
            raw_id = normalized_url
        else:
            fallback = f"{publisher}:{title}".strip(":")
            raw_id = re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-") or "unknown-source"
        normalized_source_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        return {
            "normalized_source_id": normalized_source_id,
            "normalized_url": normalized_url or None,
            "domain": domain or None,
            "publisher": publisher or None,
            "source_kind": source_kind,
        }

    def _seed_trust_score(self, trust_class: str) -> float:
        mapping = {
            "trusted_primary": 84.0,
            "trusted_ecosystem": 72.0,
            "neutral_secondary": 54.0,
            "weak_signal": 28.0,
            "quarantined": 5.0,
        }
        return mapping.get(str(trust_class or "").strip().lower(), 28.0)

    def _freshness_score(self, published_at: str) -> float:
        raw = str(published_at or "").strip()
        if not raw or raw.lower() in {"local", "undated"}:
            return 0.0
        try:
            candidate = raw.replace("Z", "+00:00")
            if len(candidate) == 10:
                dt = datetime.fromisoformat(candidate + "T00:00:00+00:00")
            else:
                dt = datetime.fromisoformat(candidate)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            age_days = max((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days, 0)
        except Exception:
            return 0.0
        if age_days <= 30:
            return 8.0
        if age_days <= 180:
            return 5.0
        if age_days <= 365:
            return 2.5
        return 0.0

    def _ecosystem_score(self, source: dict[str, Any], *, normalized: dict[str, Any]) -> float:
        domain = str(normalized.get("domain") or "").lower()
        title = str(source.get("title") or "").lower()
        if "github.com" in domain:
            if any(token in title for token in ("release", "changelog", "docs")):
                return 4.0
            return 6.0
        if any(token in domain for token in ("pypi.org", "npmjs.com", "huggingface.co")):
            return 4.0
        return 0.0

    def _claim_family(self, source: dict[str, Any]) -> str:
        title = str(source.get("title") or "").strip().lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", title)
        tokens = [token for token in normalized.split() if len(token) >= 4][:8]
        return "-".join(tokens) if tokens else "unknown"

    def _load_source_reputation(self, normalized_source_id: str) -> sqlite3.Row | None:
        return self.journal.database.fetchone(
            """
            SELECT *
            FROM deep_research_source_reputation
            WHERE normalized_source_id = ?
            """,
            (normalized_source_id,),
        )

    def _history_score(self, row: sqlite3.Row | None) -> float:
        if row is None:
            return 0.0
        observation_count = int(row["observation_count"] or 0)
        trusted_count = int(row["trusted_count"] or 0)
        weak_count = int(row["weak_count"] or 0)
        quarantined_count = int(row["quarantined_count"] or 0)
        contradicted_count = int(row["contradicted_count"] or 0)
        history = min(observation_count, 8) * 1.2
        history += trusted_count * 0.8
        history -= weak_count * 0.6
        history -= quarantined_count * 2.0
        history -= contradicted_count * 1.4
        return max(min(history, 12.0), -12.0)

    def _reputation_class_from_score(self, score: float) -> str:
        if score >= 80.0:
            return "trusted_primary"
        if score >= 65.0:
            return "trusted_ecosystem"
        if score >= 45.0:
            return "neutral_secondary"
        if score >= 20.0:
            return "weak_signal"
        return "quarantined"

    def _persist_source_observation(
        self,
        *,
        request: dict[str, Any],
        lane: str,
        normalized: dict[str, Any],
        source: dict[str, Any],
        trust_class: str,
        score: float,
        corroborated: bool,
        contradicted: bool,
    ) -> None:
        observed_at = datetime.now(timezone.utc).isoformat()
        observation_id = new_id("src_obs")
        metadata = {
            "title": str(source.get("title") or "").strip(),
            "url": str(source.get("url") or "").strip(),
            "published_at": str(source.get("published_at") or "").strip(),
            "why": str(source.get("why") or "").strip(),
        }
        self.journal.database.execute(
            """
            INSERT INTO deep_research_source_observations (
                observation_id,
                run_id,
                normalized_source_id,
                normalized_url,
                domain,
                publisher,
                source_kind,
                lane,
                trust_class,
                reputation_class,
                score,
                corroborated,
                contradicted,
                published_at,
                observed_at,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                str(request.get("job_id") or "").strip() or None,
                normalized["normalized_source_id"],
                normalized.get("normalized_url"),
                normalized.get("domain"),
                normalized.get("publisher"),
                normalized["source_kind"],
                lane,
                trust_class,
                trust_class,
                float(score),
                1 if corroborated else 0,
                1 if contradicted else 0,
                str(source.get("published_at") or "").strip() or None,
                observed_at,
                json.dumps(metadata, ensure_ascii=True, sort_keys=True),
            ),
        )
        existing = self._load_source_reputation(normalized["normalized_source_id"])
        first_seen_at = str(existing["first_seen_at"]) if existing is not None else observed_at
        observation_count = int(existing["observation_count"] or 0) + 1 if existing is not None else 1
        trusted_count = int(existing["trusted_count"] or 0) + (1 if trust_class in {"trusted_primary", "trusted_ecosystem"} else 0) if existing is not None else (1 if trust_class in {"trusted_primary", "trusted_ecosystem"} else 0)
        weak_count = int(existing["weak_count"] or 0) + (1 if trust_class == "weak_signal" else 0) if existing is not None else (1 if trust_class == "weak_signal" else 0)
        quarantined_count = int(existing["quarantined_count"] or 0) + (1 if trust_class == "quarantined" else 0) if existing is not None else (1 if trust_class == "quarantined" else 0)
        corroborated_count = int(existing["corroborated_count"] or 0) + (1 if corroborated else 0) if existing is not None else (1 if corroborated else 0)
        contradicted_count = int(existing["contradicted_count"] or 0) + (1 if contradicted else 0) if existing is not None else (1 if contradicted else 0)
        self.journal.database.upsert(
            "deep_research_source_reputation",
            {
                "normalized_source_id": normalized["normalized_source_id"],
                "normalized_url": normalized.get("normalized_url"),
                "domain": normalized.get("domain"),
                "publisher": normalized.get("publisher"),
                "source_kind": normalized["source_kind"],
                "first_seen_at": first_seen_at,
                "last_seen_at": observed_at,
                "observation_count": observation_count,
                "trusted_count": trusted_count,
                "weak_count": weak_count,
                "quarantined_count": quarantined_count,
                "corroborated_count": corroborated_count,
                "contradicted_count": contradicted_count,
                "latest_published_at": str(source.get("published_at") or "").strip() or None,
                "last_score": float(score),
                "last_trust_class": trust_class,
                "metadata_json": json.dumps({"last_lane": lane}, ensure_ascii=True, sort_keys=True),
            },
            conflict_columns="normalized_source_id",
        )

    def _score_source_record(
        self,
        *,
        request: dict[str, Any],
        lane: str,
        source: dict[str, Any],
        claim_families: dict[str, set[str]],
        research_intensity: str,
    ) -> dict[str, Any]:
        normalized = self._normalized_source_identity(source)
        base_trust_class = self._classify_source_trust(source)
        score = self._seed_trust_score(base_trust_class)
        score += self._freshness_score(str(source.get("published_at") or "").strip())
        score_mode = self._reputation_mode(research_intensity=research_intensity)
        family = self._claim_family(source)
        corroborated_domains = claim_families.get(family, set())
        corroborated = len(corroborated_domains) >= 2
        contradiction_penalty = 0.0
        history_used = False
        if score_mode in {"medium", "full"} and corroborated:
            score += 6.0
        if score_mode == "full":
            score += self._ecosystem_score(source, normalized=normalized)
            history_row = self._load_source_reputation(normalized["normalized_source_id"])
            history_score = self._history_score(history_row)
            history_used = history_row is not None
            score += history_score
        score -= contradiction_penalty
        score = max(min(score, 100.0), 0.0)
        trust_class = self._reputation_class_from_score(score)
        self._persist_source_observation(
            request=request,
            lane=lane,
            normalized=normalized,
            source=source,
            trust_class=trust_class,
            score=score,
            corroborated=corroborated,
            contradicted=False,
        )
        return {
            **source,
            **normalized,
            "claim_family": family,
            "trust_class": trust_class,
            "reputation_class": trust_class,
            "reputation_score": round(score, 2),
            "score_mode": score_mode,
            "history_used": history_used,
            "corroborated": corroborated,
            "contradicted": False,
            "contradiction_penalty": contradiction_penalty,
        }

    def _build_claim_family_domains(self, scout_bundle: dict[str, Any]) -> dict[str, set[str]]:
        families: dict[str, set[str]] = {}
        for payload in scout_bundle.values():
            if not isinstance(payload, dict):
                continue
            for source in [item for item in payload.get("sources", []) if isinstance(item, dict)]:
                family = self._claim_family(source)
                normalized = self._normalized_source_identity(source)
                domain = str(normalized.get("domain") or "").strip()
                if not domain:
                    continue
                families.setdefault(family, set()).add(domain)
        return families

    def _new_response_continuity(self, *, research_intensity: str) -> dict[str, Any]:
        enabled = str(research_intensity or "").strip().lower() in {"complex", "extreme"}
        return {
            "enabled": enabled,
            "scope": "planner_to_final_synthesis" if enabled else "disabled",
            "strategy": "responses_previous_response_id" if enabled else "none",
            "anchors": {},
            "trail": [],
            "notes": [
                "Planner, scout, skeptic, and final synthesis passes reuse prior Responses state when available."
            ]
            if enabled
            else [],
        }

    def _resolve_continuity_previous_response_id(
        self,
        *,
        response_continuity: dict[str, Any] | None,
        anchor_candidates: list[str] | tuple[str, ...] | None,
    ) -> str | None:
        if not isinstance(response_continuity, dict) or not bool(response_continuity.get("enabled")):
            return None
        anchors = response_continuity.get("anchors")
        if not isinstance(anchors, dict):
            return None
        for candidate in anchor_candidates or ():
            payload = anchors.get(str(candidate))
            if not isinstance(payload, dict):
                continue
            response_id = str(payload.get("response_id") or "").strip()
            if response_id:
                return response_id
        return None

    def _record_response_continuity(
        self,
        *,
        response_continuity: dict[str, Any] | None,
        anchor: str,
        phase: str,
        model: str,
        response_id: str | None,
        previous_response_id: str | None,
        stored: bool,
    ) -> None:
        if not isinstance(response_continuity, dict) or not bool(response_continuity.get("enabled")):
            return
        anchors = response_continuity.setdefault("anchors", {})
        trail = response_continuity.setdefault("trail", [])
        payload = {
            "phase": phase,
            "model": model,
            "response_id": str(response_id or "").strip() or None,
            "previous_response_id": str(previous_response_id or "").strip() or None,
            "stored": bool(stored),
        }
        if isinstance(anchors, dict):
            anchors[str(anchor)] = payload
        if isinstance(trail, list):
            trail.append({"anchor": str(anchor), **payload})

    def _summarize_response_continuity(self, response_continuity: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(response_continuity, dict):
            return {"enabled": False, "scope": "disabled", "strategy": "none", "anchors": [], "trail_count": 0, "notes": []}
        anchors = response_continuity.get("anchors")
        anchor_names = [str(key) for key in anchors.keys()] if isinstance(anchors, dict) else []
        trail = response_continuity.get("trail")
        return {
            "enabled": bool(response_continuity.get("enabled")),
            "scope": str(response_continuity.get("scope") or "disabled"),
            "strategy": str(response_continuity.get("strategy") or "none"),
            "anchors": anchor_names,
            "trail_count": len(trail) if isinstance(trail, list) else 0,
            "notes": self._as_token_list(response_continuity.get("notes")),
        }

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
        runtime_evidence = self._recent_runtime_evidence()
        return {
            "repo_root": str(self.repo_root),
            "research_profile": self._request_research_profile(
                kind=str(request.get("kind") or "audit"),
                question=str(request.get("question") or ""),
                research_profile=request.get("research_profile"),
            ),
            "research_intensity": self._request_research_intensity(
                kind=str(request.get("kind") or "audit"),
                question=str(request.get("question") or ""),
                research_profile=self._request_research_profile(
                    kind=str(request.get("kind") or "audit"),
                    question=str(request.get("question") or ""),
                    research_profile=request.get("research_profile"),
                ),
                research_intensity=request.get("research_intensity"),
            ),
            "current_branch": self._git_output("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": self._git_lines("status", "--short")[:_MAX_DIRTY_FILE_LINES],
            "core_packages": core_packages(self.repo_root),
            "local_refs": refs,
            "dossier_excerpt": self._read_excerpt(dossier_path, 4_200) if dossier_path.exists() else "",
            "runtime_evidence": runtime_evidence,
        }

    def _render_prompt(
        self,
        *,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        execution_plan: dict[str, Any] | None = None,
        planner_payload: dict[str, Any] | None = None,
        scout_bundle: dict[str, Any] | None = None,
    ) -> str:
        question = str(request.get("question") or "").strip()
        kind = str(request.get("kind") or "audit").strip()
        research_profile = self._request_research_profile(
            kind=kind,
            question=question,
            research_profile=request.get("research_profile"),
        )
        research_intensity = self._request_research_intensity(
            kind=kind,
            question=question,
            research_profile=research_profile,
            research_intensity=request.get("research_intensity"),
        )
        recent_days = int(request.get("recent_days") or 30)
        profile_guidance = self._profile_prompt_guidance(research_profile)
        profile_output = self._profile_output_requirements(research_profile)
        execution_blob = json.dumps(execution_plan or {}, ensure_ascii=True, indent=2, sort_keys=True)
        planner_blob = json.dumps(planner_payload or {}, ensure_ascii=True, indent=2, sort_keys=True)
        scout_blob = json.dumps(scout_bundle or {}, ensure_ascii=True, indent=2, sort_keys=True)
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
            - write every human-language string in English because the markdown dossier is the machine-readable canonical artifact
            - keep enum values like `a_faire`, `a_etudier`, `a_rejeter`, `KEEP`, `ADAPT`, `DEFER`, `REJECT` unchanged
            - if `runtime_evidence` is present in the repo snapshot, ground `observed_runtime_issues` in that evidence and do not invent incidents beyond it

            Research kind:
            - {kind}

            Research profile:
            - {research_profile}

            Research intensity:
            - {research_intensity}

            Research question:
            - {question}

            Freshness target:
            - prioritize discoveries and updates from the last {recent_days} days when discussing current tooling or releases
            - for foundational papers and stable repos, older sources are acceptable

            Profile-specific guidance:
            {profile_guidance}

            Repo snapshot:
            {json.dumps(repo_context, ensure_ascii=True, indent=2, sort_keys=True)}

            Execution plan:
            {execution_blob}

            Planner brief:
            {planner_blob}

            Scout bundle:
            {scout_blob}

            Output requirements:
            - return strict JSON only
            - provide a strong human-readable, SEO-friendly dossier title in `seo_title`
            - 3 to 8 recommendations maximum
            - `bucket` must be one of `a_faire`, `a_etudier`, or `a_rejeter`
            - `decision` must be one of `KEEP`, `ADAPT`, `DEFER`, or `REJECT`
            - every recommendation must include 1 to 4 primary sources with working URLs
            - `project_os_touchpoints` must name concrete packages, docs, or refactors inside Project OS
            - `proofs` must be executable checks, tests, or review gates
            - `research_profile` in the JSON must exactly match `{research_profile}`
            - `research_intensity` in the JSON must exactly match `{research_intensity}`
            - recommendation fields `goal_link`, `roi`, `sequence_role`, `scope_level`, and `evidence_basis` are mandatory
            {profile_output}
            """
        ).strip()

    def _profile_prompt_guidance(self, research_profile: str) -> str:
        if research_profile == "project_audit":
            return textwrap.dedent(
                """
                - optimize for the full ambitious Project OS system, not a local hardening memo
                - evaluate the repo as a path toward a master agent supervising specialized manager agents
                - separate foundational substrate, manager-agent architecture, execution surfaces, verification/evals/memory, and profile-specific work
                - external research can challenge current repo ambition, but the audit remains system-building first
                - do not let UEFN dominate unless the evidence makes it the relevant proving ground
                - if the current repo is under-ambitious relative to the goal, say so explicitly
                """
            ).strip()
        if research_profile == "component_discovery":
            return textwrap.dedent(
                """
                - optimize for finding what Project OS is underthinking in this subsystem or feature area
                - aggressively search upstream repos, active forks, satellites, plugins, wrappers, recent releases, and strong alternatives
                - emphasize what to steal, what to adapt, what is overhyped, and where Project OS is behind public practice
                - do not stop at popular repos; check if smaller repos or satellites are strategically sharper
                - explicitly say when no fork beats upstream or when a satellite matters more than the main repo
                - this mode is discovery-heavy, not just local refactor advice
                """
            ).strip()
        return textwrap.dedent(
            """
            - if the topic is outside pure software, prioritize a user-useful domain synthesis first, then explain Project OS fit second
            - use the recommendation buckets as domain lanes when relevant, not only as software tooling buckets
            - avoid turning the whole report into meta-commentary about Project OS when the subject is broader than the repo itself
            """
        ).strip()

    def _profile_output_requirements(self, research_profile: str) -> str:
        if research_profile == "project_audit":
            return textwrap.dedent(
                """
                - include `project_audit_block` with `north_star`, `system_thesis`, `platform_layers`, `capability_gaps`, `priority_ladder`, `observed_runtime_issues`, and `success_metrics`
                - `project_audit_block.priority_ladder` must contain `foundational_now`, `system_next`, and `expansion_later`
                - recommendations should connect to the larger Project OS architecture, not only local cleanup
                """
            ).strip()
        if research_profile == "component_discovery":
            return textwrap.dedent(
                """
                - include `component_discovery_block` with `blind_spots`, `external_leverage`, `underbuilt_layers`, `priority_ladder`, `observed_runtime_issues`, `stop_doing_or_deprioritize`, and `success_metrics`
                - `component_discovery_block.priority_ladder` must contain `highest_leverage_now`, `major_system_next`, and `watch_and_prepare`
                - at least one recommendation must clearly show GitHub/fork/satellite-driven leverage
                - every `a_faire` item must state `blind_spot_addressed`
                """
            ).strip()
        return textwrap.dedent(
            """
            - keep the structure lightweight and synthesis-first
            - keep Project OS fit secondary to the domain answer
            """
        ).strip()

    def _build_execution_plan(self, *, request: dict[str, Any], repo_context: dict[str, Any]) -> dict[str, Any]:
        kind = str(request.get("kind") or "audit").strip().lower()
        question = str(request.get("question") or "").strip()
        research_profile = self._request_research_profile(
            kind=kind,
            question=question,
            research_profile=request.get("research_profile"),
        )
        research_intensity = self._request_research_intensity(
            kind=kind,
            question=question,
            research_profile=research_profile,
            research_intensity=request.get("research_intensity"),
        )
        research_route = self._research_route(research_intensity=research_intensity)
        plan: dict[str, Any] = {
            "mode": research_intensity,
            "requested_mode": research_intensity,
            "effective_mode": research_intensity,
            "kind": kind,
            "research_profile": research_profile,
            "recommended_profile": str(request.get("recommended_profile") or research_profile),
            "recommended_intensity": str(request.get("recommended_intensity") or research_intensity),
            "phases": [],
            "scout_lanes": [],
            "safety_gate": {"enabled": research_intensity in {"complex", "extreme"}, "mandatory": research_intensity == "extreme"},
            "publisher": {"markdown_language": "en", "pdf_language": "fr"},
            "mesh_level": "single",
            "provider_route": {
                "research_provider": research_route["provider"],
                "research_model": research_route["model"],
                "scout_model": self.scout_model if research_route["provider"] == "openai" else research_route["model"],
                "research_label": research_route["label"],
                "translation_provider": "openai",
                "translation_model": self._translation_attempts()[0],
            },
            "planner_required": False,
            "planner_contract": {},
            "parallel_groups": [],
            "mesh_manifest": {"launched_lanes": [], "concurrency_cap": 1},
            "lane_status": {},
            "source_reputation_summary": self._empty_source_trust_summary(),
            "degraded": False,
            "degradation_notes": [],
        }
        if research_intensity == "simple":
            plan["phases"] = [
                "repo_context",
                "single_research_pass",
                "light_source_scoring",
                "reader_translation",
                "render_and_archive",
            ]
            plan["scout_lanes"] = ["repo_context"]
            return plan
        plan["planner_required"] = True
        plan["phases"] = [
            "planner",
            "repo_scout",
            "official_docs_scout",
            "github_scout",
            "source_safety_gate",
        ]
        plan["scout_lanes"] = ["repo", "official_docs", "github"]
        if research_intensity == "complex":
            plan["mesh_level"] = "in_process_parallel"
            plan["parallel_groups"] = [["official_docs", "github"]]
            plan["mesh_manifest"] = {
                "launched_lanes": [],
                "concurrency_cap": _COMPLEX_MAX_WORKERS,
            }
            plan["phases"].extend(["skeptic_optional", "expert_synthesis", "reader_translation", "render_and_archive"])
            return plan
        plan["mesh_level"] = "child_worker_mesh"
        plan["parallel_groups"] = [["repo", "official_docs", "github", "papers"]]
        plan["mesh_manifest"] = {
            "launched_lanes": [],
            "concurrency_cap": _EXTREME_MAX_WORKERS,
        }
        plan["phases"].extend(
            [
                "cheap_scout_swarm",
                "papers_scout",
                "source_safety_gate",
                "skeptic",
                "expert_synthesis",
                "reader_translation",
                "render_and_archive",
            ]
        )
        plan["scout_lanes"] = ["repo", "official_docs", "github", "papers"]
        plan["cheap_scout_swarm"] = ["official_docs", "github", "papers"]
        return plan

    def _run_research_pipeline(
        self,
        *,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        execution_plan: dict[str, Any],
        job_root: Path,
    ) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        research_intensity = str(execution_plan.get("mode") or "simple").strip().lower()
        if research_intensity == "simple":
            prompt = self._render_prompt(request=request, repo_context=repo_context, execution_plan=execution_plan)
            structured, raw_payload, usage = self._call_research_model(request=request, prompt=prompt)
            return prompt, structured, raw_payload, usage

        planner_payload: dict[str, Any] = {}
        cheap_scout_swarm_payload: dict[str, Any] = {}
        scout_bundle: dict[str, Any] = {}
        trust_bundle: dict[str, Any] = {}
        skeptic_payload: dict[str, Any] = {}
        auxiliary_failures: list[str] = []
        response_continuity = self._new_response_continuity(research_intensity=research_intensity)
        try:
            planner_payload = self._run_planner_pass(
                request=request,
                repo_context=repo_context,
                execution_plan=execution_plan,
                response_continuity=response_continuity,
            )
            self._apply_planner_contract(execution_plan=execution_plan, planner_payload=planner_payload)
        except Exception as exc:
            auxiliary_failures.append(self._record_auxiliary_failure(request=request, phase="planner", exc=exc))
            execution_plan["effective_mode"] = "simple"
            execution_plan["degraded"] = True
            execution_plan["degradation_notes"] = auxiliary_failures
            execution_plan["source_trust_summary"] = self._empty_source_trust_summary()
            execution_plan["source_reputation_summary"] = execution_plan["source_trust_summary"]
            execution_plan["response_continuity"] = self._summarize_response_continuity(response_continuity)
            prompt = self._render_prompt(request=request, repo_context=repo_context, execution_plan=execution_plan)
            structured, raw_payload, usage = self._call_research_model(request=request, prompt=prompt)
            raw_payload["execution_plan"] = execution_plan
            raw_payload["planner_payload"] = planner_payload
            raw_payload["cheap_scout_swarm"] = cheap_scout_swarm_payload
            raw_payload["scout_bundle"] = scout_bundle
            raw_payload["trusted_scout_bundle"] = trust_bundle
            raw_payload["skeptic_payload"] = skeptic_payload
            raw_payload["auxiliary_failures"] = auxiliary_failures
            return prompt, structured, raw_payload, usage
        if research_intensity == "extreme":
            try:
                cheap_scout_swarm_payload, scout_bundle, scout_failures, mesh_manifest = self._run_extreme_lane_mesh(
                    request=request,
                    repo_context=repo_context,
                    execution_plan=execution_plan,
                    planner_payload=planner_payload,
                    job_root=job_root,
                    response_continuity=response_continuity,
                )
                execution_plan["mesh_manifest"] = mesh_manifest
                self._write_mesh_manifest(job_root=job_root, manifest=mesh_manifest)
                execution_plan["cheap_scout_summary"] = {
                    "status": "completed",
                    "lane_brief_count": len(
                        [item for item in cheap_scout_swarm_payload.get("lane_briefs", []) if isinstance(item, dict)]
                    ),
                    "broad_signal_count": len(self._as_token_list(cheap_scout_swarm_payload.get("broad_signals"))),
                    "watchouts": self._as_token_list(cheap_scout_swarm_payload.get("watchouts")),
                }
                if scout_failures:
                    auxiliary_failures.extend(scout_failures)
                    execution_plan["degraded"] = True
                    execution_plan["degradation_notes"] = auxiliary_failures
            except Exception as exc:
                auxiliary_failures.append(self._record_auxiliary_failure(request=request, phase="child_worker_mesh", exc=exc))
                execution_plan["degraded"] = True
                execution_plan["degradation_notes"] = auxiliary_failures
                execution_plan["cheap_scout_summary"] = {
                    "status": "degraded",
                    "lane_brief_count": 0,
                    "broad_signal_count": 0,
                    "watchouts": [auxiliary_failures[-1]],
                }
                scout_bundle = {
                    "repo": self._build_repo_scout(repo_context=repo_context, execution_plan=execution_plan),
                }
        else:
            try:
                scout_bundle, scout_failures = self._run_scout_bundle(
                    request=request,
                    repo_context=repo_context,
                    execution_plan=execution_plan,
                    planner_payload=planner_payload,
                    cheap_scout_swarm_payload=cheap_scout_swarm_payload,
                    response_continuity=response_continuity,
                )
                if scout_failures:
                    auxiliary_failures.extend(scout_failures)
                    execution_plan["degraded"] = True
                    execution_plan["degradation_notes"] = auxiliary_failures
            except Exception as exc:
                auxiliary_failures.append(self._record_auxiliary_failure(request=request, phase="scout_bundle", exc=exc))
                execution_plan["effective_mode"] = "simple"
                execution_plan["degraded"] = True
                execution_plan["degradation_notes"] = auxiliary_failures
                execution_plan["source_trust_summary"] = self._empty_source_trust_summary()
                execution_plan["source_reputation_summary"] = execution_plan["source_trust_summary"]
                execution_plan["response_continuity"] = self._summarize_response_continuity(response_continuity)
                prompt = self._render_prompt(
                    request=request,
                    repo_context=repo_context,
                    execution_plan=execution_plan,
                    planner_payload=planner_payload,
                )
                structured, raw_payload, usage = self._call_research_model(request=request, prompt=prompt)
                raw_payload["execution_plan"] = execution_plan
                raw_payload["planner_payload"] = planner_payload
                raw_payload["cheap_scout_swarm"] = cheap_scout_swarm_payload
                raw_payload["scout_bundle"] = scout_bundle
                raw_payload["trusted_scout_bundle"] = trust_bundle
                raw_payload["skeptic_payload"] = skeptic_payload
                raw_payload["auxiliary_failures"] = auxiliary_failures
                return prompt, structured, raw_payload, usage
        trust_bundle = self._apply_source_trust_gate_to_scouts(
            request=request,
            execution_plan=execution_plan,
            scout_bundle=scout_bundle,
        )
        execution_plan["source_trust_summary"] = trust_bundle.get("source_trust_summary", {})
        execution_plan["source_reputation_summary"] = execution_plan["source_trust_summary"]
        execution_plan["lane_status"] = self._summarize_lane_status(trust_bundle)
        try:
            if research_intensity == "extreme":
                previous_for_skeptic = self._resolve_continuity_previous_response_id(
                    response_continuity=response_continuity,
                    anchor_candidates=["papers_scout", "github_scout", "official_docs_scout", "cheap_scout_swarm", "planner"],
                )
                skeptic_result = self._run_lane_via_child(
                    job_root=job_root,
                    lane_request={
                        "lane": "skeptic",
                        "request": request,
                        "execution_plan": execution_plan,
                        "planner_payload": planner_payload,
                        "scout_bundle": trust_bundle,
                        "previous_response_id": previous_for_skeptic,
                    },
                )
                skeptic_payload = dict(skeptic_result)
                self._record_child_lane_anchor(
                    response_continuity=response_continuity,
                    anchor="skeptic",
                    phase="skeptic",
                    lane_result=skeptic_result,
                )
                mesh_manifest = execution_plan.get("mesh_manifest")
                if isinstance(mesh_manifest, dict):
                    mesh_manifest.setdefault("launched_lanes", []).append("skeptic")
                    mesh_manifest.setdefault("completed_lanes", []).append("skeptic")
                    mesh_manifest.setdefault("lane_roots", {})["skeptic"] = str(self._lane_root(job_root=job_root, lane="skeptic"))
                    self._write_mesh_manifest(job_root=job_root, manifest=mesh_manifest)
            else:
                skeptic_payload = self._run_skeptic_pass(
                    request=request,
                    execution_plan=execution_plan,
                    planner_payload=planner_payload,
                    scout_bundle=trust_bundle,
                    response_continuity=response_continuity,
                )
        except Exception as exc:
            auxiliary_failures.append(self._record_auxiliary_failure(request=request, phase="skeptic", exc=exc))
            execution_plan["degraded"] = True
            execution_plan["degradation_notes"] = auxiliary_failures
            skeptic_payload = {
                "risks": [auxiliary_failures[-1]],
                "contradictions": [],
                "weak_points": ["Skeptic pass unavailable; final synthesis is based on planner and scout lanes only."],
                "corrections": ["Keep the final report conservative and evidence-led."],
            }
        self._apply_skeptic_contradictions(
            execution_plan=execution_plan,
            trust_bundle=trust_bundle,
            skeptic_payload=skeptic_payload,
        )
        execution_plan["response_continuity"] = self._summarize_response_continuity(response_continuity)
        prompt = self._render_prompt(
            request=request,
            repo_context=repo_context,
            execution_plan=execution_plan,
            planner_payload={**planner_payload, "skeptic": skeptic_payload},
            scout_bundle=trust_bundle,
        )
        structured, raw_payload, usage = self._call_research_model(
            request=request,
            prompt=prompt,
            response_continuity=response_continuity,
            continuity_anchor="final_synthesis",
            previous_anchor_candidates=["skeptic", "papers_scout", "github_scout", "official_docs_scout", "cheap_scout_swarm", "planner"],
        )
        execution_plan["response_continuity"] = self._summarize_response_continuity(response_continuity)
        raw_payload["execution_plan"] = execution_plan
        raw_payload["planner_payload"] = planner_payload
        raw_payload["cheap_scout_swarm"] = cheap_scout_swarm_payload
        raw_payload["scout_bundle"] = scout_bundle
        raw_payload["trusted_scout_bundle"] = trust_bundle
        raw_payload["skeptic_payload"] = skeptic_payload
        raw_payload["auxiliary_failures"] = auxiliary_failures
        self._write_managed_json(job_root / "planner.json", planner_payload)
        if cheap_scout_swarm_payload:
            self._write_managed_json(job_root / "cheap_scout_swarm.json", cheap_scout_swarm_payload)
        self._write_managed_json(job_root / "scouts.json", scout_bundle)
        self._write_managed_json(job_root / "trusted_scouts.json", trust_bundle)
        self._write_managed_json(job_root / "skeptic.json", skeptic_payload)
        return prompt, structured, raw_payload, usage

    def _run_planner_pass(
        self,
        *,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        execution_plan: dict[str, Any],
        response_continuity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt = textwrap.dedent(
            f"""
            You are the planning lead for a Project OS deep research run.

            Produce a concise execution brief for the final synthesis model.

            Required output:
            - mission
            - why_this_mode
            - angles
            - required_lanes
            - optional_lanes
            - parallel_groups
            - must_prove
            - must_refute
            - lane_priority
            - needs_papers
            - needs_github_depth
            - avoid
            - scout_focus

            Question:
            {request.get('question') or ''}

            Research profile:
            {request.get('research_profile') or execution_plan.get('research_profile')}

            Research intensity:
            {request.get('research_intensity') or execution_plan.get('mode')}

            Repo context:
            {json.dumps(repo_context, ensure_ascii=True, indent=2, sort_keys=True)}

            Execution plan:
            {json.dumps(execution_plan, ensure_ascii=True, indent=2, sort_keys=True)}
            """
        ).strip()
        return self._call_auxiliary_model(
            prompt=prompt,
            schema=self._planner_schema(),
            schema_name="project_os_deep_research_planner",
            description="Planner brief for a Project OS deep research run",
            attempts=[
                (
                    self._openai_planner_model(),
                    None,
                    "high"
                    if str(request.get("research_intensity") or execution_plan.get("mode") or "").strip().lower() == "extreme"
                    else "medium",
                )
            ],
            metadata={
                "job_id": str(request.get("job_id") or ""),
                "kind": str(request.get("kind") or "audit"),
                "research_profile": str(request.get("research_profile") or ""),
                "research_intensity": str(request.get("research_intensity") or ""),
                "phase": "planner",
                "debug_root": str(request.get("_debug_root") or ""),
            },
            response_continuity=response_continuity,
            continuity_anchor="planner",
        )

    def _run_cheap_scout_swarm(
        self,
        *,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        execution_plan: dict[str, Any],
        planner_payload: dict[str, Any],
        response_continuity: dict[str, Any] | None = None,
        previous_response_id_override: str | None = None,
        force_store: bool | None = None,
    ) -> dict[str, Any]:
        prompt = textwrap.dedent(
            f"""
            You are the cheap scout swarm for a Project OS deep research war-room run.

            Your job is not to produce the final answer. Your job is to widen discovery cheaply, rank promising directions,
            and seed the specialist lanes with the best candidate sources.

            Return strict JSON only.

            Rules:
            - keep the discovery broad but disciplined
            - prioritize official docs, official repos, strong upstreams, meaningful forks, and strong satellites
            - explicitly flag suspicious or weak sources
            - produce lane-specific briefs for `official_docs`, `github`, and `papers`
            - the specialist scouts will go deeper later; do not write a full synthesis here

            Question:
            {request.get('question') or ''}

            Planner brief:
            {json.dumps(planner_payload, ensure_ascii=True, indent=2, sort_keys=True)}

            Repo context:
            {json.dumps(repo_context, ensure_ascii=True, indent=2, sort_keys=True)}

            Execution plan:
            {json.dumps(execution_plan, ensure_ascii=True, indent=2, sort_keys=True)}
            """
        ).strip()
        return self._call_auxiliary_model(
            prompt=prompt,
            schema=self._cheap_scout_swarm_schema(),
            schema_name="project_os_deep_research_cheap_scout_swarm",
            description="Cheap scout swarm for a Project OS deep research war-room run",
            attempts=[(self._openai_scout_model(lane="cheap_scout_swarm"), {"type": "web_search_preview", "search_context_size": "high"}, "low")],
            metadata={
                "job_id": str(request.get("job_id") or ""),
                "kind": str(request.get("kind") or "audit"),
                "research_profile": str(request.get("research_profile") or ""),
                "research_intensity": str(request.get("research_intensity") or ""),
                "phase": "cheap_scout_swarm",
                "debug_root": str(request.get("_debug_root") or ""),
            },
            response_continuity=response_continuity,
            continuity_anchor="cheap_scout_swarm",
            previous_anchor_candidates=["planner"],
            previous_response_id_override=previous_response_id_override,
            force_store=force_store,
        )

    def _run_external_scout_lane(
        self,
        *,
        lane: str,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        execution_plan: dict[str, Any],
        planner_payload: dict[str, Any],
        lane_brief: dict[str, Any],
        response_continuity: dict[str, Any] | None = None,
        previous_response_id_override: str | None = None,
        force_store: bool | None = None,
    ) -> dict[str, Any]:
        question = str(request.get("question") or "").strip()
        prompt = textwrap.dedent(
            f"""
            You are the {lane} scout for a Project OS deep research run.

            Return strict JSON only.

            Focus:
            - gather high-value findings for the lane
            - prefer primary sources with dates
            - surface what to steal or adapt
            - explicitly flag weak or suspicious sources

            Question:
            {question}

            Planner brief:
            {json.dumps(planner_payload, ensure_ascii=True, indent=2, sort_keys=True)}

            Swarm brief:
            {json.dumps(lane_brief, ensure_ascii=True, indent=2, sort_keys=True)}

            Repo context:
            {json.dumps(repo_context, ensure_ascii=True, indent=2, sort_keys=True)}
            """
        ).strip()
        payload = self._call_auxiliary_model(
            prompt=prompt,
            schema=self._scout_schema(),
            schema_name=f"project_os_{lane}_scout",
            description=f"{lane} scout findings for Project OS deep research",
            attempts=[
                (
                    self._openai_scout_model(lane=lane),
                    {"type": "web_search_preview", "search_context_size": "high"},
                    "high"
                    if str(execution_plan.get("mode") or "").strip().lower() == "extreme" and lane in {"official_docs", "github"}
                    else "medium",
                )
            ],
            metadata={
                "kind": str(request.get("kind") or "audit"),
                "research_profile": str(request.get("research_profile") or ""),
                "research_intensity": str(request.get("research_intensity") or ""),
                "phase": lane,
                "job_id": str(request.get("job_id") or ""),
                "debug_root": str(request.get("_debug_root") or ""),
            },
            response_continuity=response_continuity,
            continuity_anchor=f"{lane}_scout",
            previous_anchor_candidates=["cheap_scout_swarm", "planner"],
            previous_response_id_override=previous_response_id_override,
            force_store=force_store,
        )
        return {**payload, "status": "completed"}

    def _run_scout_bundle(
        self,
        *,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        execution_plan: dict[str, Any],
        planner_payload: dict[str, Any],
        cheap_scout_swarm_payload: dict[str, Any] | None = None,
        response_continuity: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        bundle: dict[str, Any] = {
            "repo": self._build_repo_scout(repo_context=repo_context, execution_plan=execution_plan),
        }
        failures: list[str] = []
        lane_briefs = self._lane_briefs_from_swarm(cheap_scout_swarm_payload or {})
        external_lanes = [str(lane).strip() for lane in execution_plan.get("scout_lanes", []) if str(lane).strip() and str(lane).strip() != "repo"]
        if str(execution_plan.get("mode") or "").strip().lower() == "complex" and external_lanes:
            max_workers = min(_COMPLEX_MAX_WORKERS, len(external_lanes))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self._run_external_scout_lane,
                        lane=lane,
                        request=request,
                        repo_context=repo_context,
                        execution_plan=execution_plan,
                        planner_payload=planner_payload,
                        lane_brief=lane_briefs.get(lane, {}),
                        response_continuity=response_continuity,
                    ): lane
                    for lane in external_lanes
                }
                for future in as_completed(futures):
                    lane = futures[future]
                    try:
                        bundle[lane] = future.result()
                    except Exception as exc:
                        note = self._record_auxiliary_failure(request=request, phase=lane, exc=exc)
                        failures.append(note)
                        bundle[lane] = self._fallback_scout_payload(lane=lane, lane_brief=lane_briefs.get(lane, {}), note=note)
        else:
            for lane in external_lanes:
                lane_brief = lane_briefs.get(str(lane), {})
                try:
                    bundle[lane] = self._run_external_scout_lane(
                        lane=lane,
                        request=request,
                        repo_context=repo_context,
                        execution_plan=execution_plan,
                        planner_payload=planner_payload,
                        lane_brief=lane_brief,
                        response_continuity=response_continuity,
                    )
                except Exception as exc:
                    note = self._record_auxiliary_failure(request=request, phase=lane, exc=exc)
                    failures.append(note)
                    bundle[lane] = self._fallback_scout_payload(lane=lane, lane_brief=lane_brief, note=note)
        return bundle, failures

    def _build_repo_scout(self, *, repo_context: dict[str, Any], execution_plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "lane": "repo",
            "summary": "Local repo scout assembled from current repo context and loaded references.",
            "key_findings": [
                f"Active branch: {repo_context.get('current_branch') or 'unknown'}",
                f"Detected core packages: {', '.join(repo_context.get('core_packages', [])[:8]) or 'none'}",
                f"Intensity plan: {execution_plan.get('mode') or 'simple'}",
            ],
            "candidate_systems": [str(item) for item in repo_context.get("core_packages", [])[:8]],
            "sources": [
                {
                    "title": str(item.get("relative_path") or item.get("path") or "Local Ref").strip(),
                    "url": "",
                    "publisher": "local_repo",
                    "published_at": "local",
                    "why": "Loaded directly from the current Project OS repo snapshot.",
                }
                for item in repo_context.get("local_refs", [])[:6]
                if isinstance(item, dict)
            ],
            "warnings": [],
            "status": "completed",
        }

    def _lane_briefs_from_swarm(self, cheap_scout_swarm_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        lane_briefs: dict[str, dict[str, Any]] = {}
        for item in cheap_scout_swarm_payload.get("lane_briefs", []):
            if not isinstance(item, dict):
                continue
            lane = str(item.get("lane") or "").strip()
            if lane:
                lane_briefs[lane] = item
        return lane_briefs

    def _fallback_scout_payload(self, *, lane: str, lane_brief: dict[str, Any], note: str) -> dict[str, Any]:
        seed_sources = [item for item in lane_brief.get("seed_sources", []) if isinstance(item, dict)]
        query_focus = self._as_token_list(lane_brief.get("query_focus"))
        warnings = [note, "Lane degraded; treat this lane as incomplete and keep the final synthesis conservative."]
        warnings.extend(self._as_token_list(lane_brief.get("avoid")))
        return {
            "lane": lane,
            "summary": f"{lane} scout degraded before full depth. The expert synthesis should treat this lane as partial.",
            "key_findings": [],
            "candidate_systems": query_focus[:6],
            "sources": seed_sources[:6],
            "warnings": warnings,
            "status": "degraded",
        }

    def _summarize_lane_status(self, scout_bundle: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for lane, payload in scout_bundle.items():
            if not isinstance(payload, dict) or lane == "source_trust_summary":
                continue
            trusted_sources = [item for item in payload.get("source_trust", payload.get("sources", [])) if isinstance(item, dict)]
            summary[lane] = {
                "status": str(payload.get("status") or "completed").strip().lower() or "completed",
                "source_count": len([item for item in payload.get("sources", []) if isinstance(item, dict)]),
                "trusted_source_count": len(
                    [
                        item
                        for item in trusted_sources
                        if str(item.get("trust_class") or "").strip().lower() in {"trusted_primary", "trusted_ecosystem"}
                    ]
                ),
                "warning_count": len(self._as_token_list(payload.get("warnings"))),
            }
        return summary

    def _run_skeptic_pass(
        self,
        *,
        request: dict[str, Any],
        execution_plan: dict[str, Any],
        planner_payload: dict[str, Any],
        scout_bundle: dict[str, Any],
        response_continuity: dict[str, Any] | None = None,
        previous_response_id_override: str | None = None,
        force_store: bool | None = None,
    ) -> dict[str, Any]:
        if str(execution_plan.get("mode") or "").strip().lower() == "simple":
            return {}
        prompt = textwrap.dedent(
            f"""
            You are the skeptic for a Project OS deep research run.

            Attack hype, duplication, weak proof, and bad fit.

            Return strict JSON only with:
            - risks
            - contradictions
            - weak_points
            - corrections

            Planner brief:
            {json.dumps(planner_payload, ensure_ascii=True, indent=2, sort_keys=True)}

            Scout bundle:
            {json.dumps(scout_bundle, ensure_ascii=True, indent=2, sort_keys=True)}
            """
        ).strip()
        return self._call_auxiliary_model(
            prompt=prompt,
            schema=self._skeptic_schema(),
            schema_name="project_os_deep_research_skeptic",
            description="Skeptic review for Project OS deep research",
            attempts=[(self._openai_planner_model(), None, "low")],
            metadata={
                "job_id": str(request.get("job_id") or ""),
                "kind": str(request.get("kind") or "audit"),
                "research_profile": str(request.get("research_profile") or ""),
                "research_intensity": str(request.get("research_intensity") or ""),
                "phase": "skeptic",
                "debug_root": str(request.get("_debug_root") or ""),
            },
            response_continuity=response_continuity,
            continuity_anchor="skeptic",
            previous_anchor_candidates=["cheap_scout_swarm", "planner"],
            previous_response_id_override=previous_response_id_override,
            force_store=force_store,
        )

    def _run_lane_via_child(self, *, job_root: Path, lane_request: dict[str, Any], timeout_seconds: int = 900) -> dict[str, Any]:
        lane = str(lane_request.get("lane") or lane_request.get("phase") or "").strip().lower()
        lane_root = self._lane_root(job_root=job_root, lane=lane)
        lane_root.mkdir(parents=True, exist_ok=True)
        request_path = lane_root / "request.json"
        self._write_managed_json(request_path, lane_request)
        process = self._spawn_lane_worker(request_path)
        return_code = process.wait(timeout=timeout_seconds)
        result_path = lane_root / "result.json"
        status_path = lane_root / "status.json"
        result_payload: dict[str, Any] = {}
        if result_path.exists():
            try:
                parsed = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    result_payload = parsed
            except Exception:
                result_payload = {}
        if return_code != 0:
            error_type = str(result_payload.get("error_type") or "LaneWorkerError").strip()
            error = str(result_payload.get("error") or f"lane {lane} failed with exit code {return_code}").strip()
            raise RuntimeError(f"{error_type}: {error}")
        if not result_payload:
            status_payload = {}
            if status_path.exists():
                try:
                    parsed = json.loads(status_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        status_payload = parsed
                except Exception:
                    status_payload = {}
            result_payload = status_payload
        return result_payload

    def _record_child_lane_anchor(
        self,
        *,
        response_continuity: dict[str, Any] | None,
        anchor: str,
        phase: str,
        lane_result: dict[str, Any],
    ) -> None:
        response_id = str(lane_result.get("_response_id") or lane_result.get("response_id") or "").strip() or None
        if not response_id:
            return
        self._record_response_continuity(
            response_continuity=response_continuity,
            anchor=anchor,
            phase=phase,
            model=str(lane_result.get("_model") or lane_result.get("model") or self.research_model),
            response_id=response_id,
            previous_response_id=str(lane_result.get("_previous_response_id") or "").strip() or None,
            stored=bool(lane_result.get("_stored")),
        )

    def _run_extreme_lane_mesh(
        self,
        *,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        execution_plan: dict[str, Any],
        planner_payload: dict[str, Any],
        job_root: Path,
        response_continuity: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], list[str], dict[str, Any]]:
        failures: list[str] = []
        mesh_manifest: dict[str, Any] = {
            "mesh_level": "child_worker_mesh",
            "concurrency_cap": _EXTREME_MAX_WORKERS,
            "planned_lanes": self._as_token_list(execution_plan.get("scout_lanes")),
            "launched_lanes": [],
            "completed_lanes": [],
            "failed_lanes": [],
            "lane_roots": {},
        }
        cheap_scout_swarm_payload: dict[str, Any] = {}
        previous_for_swarm = self._resolve_continuity_previous_response_id(
            response_continuity=response_continuity,
            anchor_candidates=["planner"],
        )
        cheap_request = {
            "lane": "cheap_scout_swarm",
            "request": request,
            "repo_context": repo_context,
            "execution_plan": execution_plan,
            "planner_payload": planner_payload,
            "previous_response_id": previous_for_swarm,
        }
        cheap_result = self._run_lane_via_child(job_root=job_root, lane_request=cheap_request)
        mesh_manifest["launched_lanes"].append("cheap_scout_swarm")
        mesh_manifest["completed_lanes"].append("cheap_scout_swarm")
        mesh_manifest["lane_roots"]["cheap_scout_swarm"] = str(self._lane_root(job_root=job_root, lane="cheap_scout_swarm"))
        cheap_scout_swarm_payload = dict(cheap_result)
        self._record_child_lane_anchor(
            response_continuity=response_continuity,
            anchor="cheap_scout_swarm",
            phase="cheap_scout_swarm",
            lane_result=cheap_result,
        )
        lane_briefs = self._lane_briefs_from_swarm(cheap_scout_swarm_payload)
        previous_for_scouts = self._resolve_continuity_previous_response_id(
            response_continuity=response_continuity,
            anchor_candidates=["cheap_scout_swarm", "planner"],
        )
        scout_bundle: dict[str, Any] = {}
        scout_lanes = [lane for lane in self._as_token_list(execution_plan.get("scout_lanes")) if lane]
        futures: dict[Any, tuple[str, Path]] = {}
        with ThreadPoolExecutor(max_workers=min(_EXTREME_MAX_WORKERS, max(len(scout_lanes), 1))) as executor:
            for lane in scout_lanes:
                lane_root = self._lane_root(job_root=job_root, lane=lane)
                mesh_manifest["lane_roots"][lane] = str(lane_root)
                mesh_manifest["launched_lanes"].append(lane)
                lane_request = {
                    "lane": lane,
                    "request": request,
                    "repo_context": repo_context,
                    "execution_plan": execution_plan,
                    "planner_payload": planner_payload,
                    "lane_brief": lane_briefs.get(lane, {}),
                    "previous_response_id": previous_for_scouts,
                }
                futures[executor.submit(self._run_lane_via_child, job_root=job_root, lane_request=lane_request)] = (lane, lane_root)
            for future in as_completed(futures):
                lane, _lane_root = futures[future]
                try:
                    lane_result = future.result()
                    scout_bundle[lane] = dict(lane_result)
                    mesh_manifest["completed_lanes"].append(lane)
                    self._record_child_lane_anchor(
                        response_continuity=response_continuity,
                        anchor=f"{lane}_scout",
                        phase=lane,
                        lane_result=lane_result,
                    )
                except Exception as exc:
                    note = self._record_auxiliary_failure(request=request, phase=lane, exc=exc)
                    failures.append(note)
                    mesh_manifest["failed_lanes"].append(lane)
                    scout_bundle[lane] = self._fallback_scout_payload(lane=lane, lane_brief=lane_briefs.get(lane, {}), note=note)
        return cheap_scout_swarm_payload, scout_bundle, failures, mesh_manifest

    def _apply_skeptic_contradictions(
        self,
        *,
        execution_plan: dict[str, Any],
        trust_bundle: dict[str, Any],
        skeptic_payload: dict[str, Any],
    ) -> None:
        summary = dict(trust_bundle.get("source_trust_summary") or {})
        contradictions = self._as_token_list(skeptic_payload.get("contradictions"))
        summary["contradiction_count"] = len(contradictions)
        summary["contradiction_notes"] = contradictions[:8]
        execution_plan["contradiction_signal"] = contradictions or ["no material contradiction found"]
        trust_bundle["source_trust_summary"] = summary
        execution_plan["source_trust_summary"] = summary
        execution_plan["source_reputation_summary"] = summary

    def _apply_source_trust_gate_to_scouts(
        self,
        *,
        request: dict[str, Any],
        execution_plan: dict[str, Any],
        scout_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        trusted_bundle: dict[str, Any] = {}
        claim_families = self._build_claim_family_domains(scout_bundle)
        research_intensity = str(execution_plan.get("mode") or "simple").strip().lower()
        for lane, payload in scout_bundle.items():
            if not isinstance(payload, dict):
                continue
            trusted_sources: list[dict[str, Any]] = []
            source_trust: list[dict[str, Any]] = []
            for source in [item for item in payload.get("sources", []) if isinstance(item, dict)]:
                trusted_source = self._score_source_record(
                    request=request,
                    lane=lane,
                    source=source,
                    claim_families=claim_families,
                    research_intensity=research_intensity,
                )
                source_trust.append(trusted_source)
                if str(trusted_source.get("trust_class") or "").strip().lower() != "quarantined":
                    trusted_sources.append(trusted_source)
            trusted_bundle[lane] = {
                **payload,
                "sources": trusted_sources,
                "source_trust": source_trust,
            }
        trusted_bundle["source_trust_summary"] = self._summarize_source_trust(
            scout_bundle=trusted_bundle,
            research_intensity=research_intensity,
        )
        return trusted_bundle

    def _classify_source_trust(self, source: dict[str, Any]) -> str:
        url = str(source.get("url") or "").strip().lower()
        publisher = str(source.get("publisher") or "").strip().lower()
        domain = str(urlparse(url).netloc or "").strip().lower()
        if not url:
            return "trusted_primary" if publisher == "local_repo" else "weak_signal"
        if domain.endswith(".gov") or domain.endswith(".edu") or "arxiv.org" in domain or "openai.com" in domain or "anthropic.com" in domain:
            return "trusted_primary"
        if "github.com" in domain or "pypi.org" in domain or "npmjs.com" in domain or "huggingface.co" in domain:
            return "trusted_ecosystem"
        if domain.endswith(".org") or domain.startswith("docs.") or publisher.startswith("docs"):
            return "trusted_ecosystem"
        if any(token in domain for token in ("medium.com", "substack.com", "dev.to", "youtube.com")):
            return "weak_signal"
        if any(token in domain for token in (".zip", ".click", ".xyz", ".top", ".lol", ".ru")):
            return "quarantined"
        return "neutral_secondary"

    def _summarize_source_trust(self, *, scout_bundle: dict[str, Any], research_intensity: str) -> dict[str, Any]:
        counts = {
            "trusted_primary": 0,
            "trusted_ecosystem": 0,
            "neutral_secondary": 0,
            "weak_signal": 0,
            "quarantined": 0,
        }
        evidence_manifest: list[dict[str, Any]] = []
        lane_counts: dict[str, int] = {}
        domain_counts: dict[str, int] = {}
        trusted_domains: set[str] = set()
        trusted_lanes: set[str] = set()
        score_total = 0.0
        score_count = 0
        history_used = False
        contradiction_notes: list[str] = []
        for lane, payload in scout_bundle.items():
            if not isinstance(payload, dict) or lane == "source_trust_summary":
                continue
            for source in [item for item in payload.get("source_trust", []) if isinstance(item, dict)]:
                trust_class = str(source.get("trust_class") or "weak_signal").strip().lower()
                if trust_class in counts:
                    counts[trust_class] += 1
                lane_counts[lane] = lane_counts.get(lane, 0) + 1
                domain = self._domain_from_source_url(str(source.get("url") or "").strip())
                if domain:
                    domain_counts[domain] = domain_counts.get(domain, 0) + 1
                if trust_class in {"trusted_primary", "trusted_ecosystem"}:
                    if domain:
                        trusted_domains.add(domain)
                    trusted_lanes.add(lane)
                score_total += float(source.get("reputation_score") or 0.0)
                score_count += 1
                history_used = history_used or bool(source.get("history_used"))
                if bool(source.get("contradicted")):
                    contradiction_notes.append(str(source.get("title") or source.get("url") or "source"))
                evidence_manifest.append(
                    {
                        "lane": lane,
                        "title": str(source.get("title") or "").strip(),
                        "url": str(source.get("url") or "").strip(),
                        "publisher": str(source.get("publisher") or "").strip(),
                        "published_at": str(source.get("published_at") or "").strip(),
                        "trust_class": trust_class,
                        "reputation_score": float(source.get("reputation_score") or 0.0),
                    }
                )
        return {
            "score_mode": self._reputation_mode(research_intensity=research_intensity),
            "counts": counts,
            "evidence_manifest": evidence_manifest,
            "trusted_domains": sorted(trusted_domains),
            "trusted_lanes": sorted(trusted_lanes),
            "lane_counts": lane_counts,
            "domain_counts": domain_counts,
            "observation_count": score_count,
            "average_score": round(score_total / score_count, 2) if score_count else 0.0,
            "history_used": history_used,
            "contradiction_count": len(contradiction_notes),
            "contradiction_notes": contradiction_notes[:8],
        }

    def _domain_from_source_url(self, url: str) -> str:
        domain = str(urlparse(str(url or "").strip()).netloc or "").strip().lower()
        return domain.removeprefix("www.")

    def _enrich_structured_result(
        self,
        *,
        request: dict[str, Any],
        structured: dict[str, Any],
        execution_plan: dict[str, Any],
    ) -> dict[str, Any]:
        enriched = dict(structured)
        enriched["research_profile"] = self._request_research_profile(
            kind=str(request.get("kind") or "audit"),
            question=str(request.get("question") or ""),
            research_profile=structured.get("research_profile") or request.get("research_profile"),
        )
        enriched["research_intensity"] = self._request_research_intensity(
            kind=str(request.get("kind") or "audit"),
            question=str(request.get("question") or ""),
            research_profile=enriched["research_profile"],
            research_intensity=request.get("research_intensity"),
        )
        enriched["recommended_profile"] = str(request.get("recommended_profile") or enriched["research_profile"])
        enriched["recommended_intensity"] = str(request.get("recommended_intensity") or enriched["research_intensity"])
        enriched["execution_plan"] = execution_plan
        trust_summary = execution_plan.get("source_trust_summary")
        if not trust_summary:
            trust_summary = self._build_source_trust_summary_from_structured(enriched)
        enriched["source_trust_summary"] = trust_summary
        enriched["source_reputation_summary"] = execution_plan.get("source_reputation_summary") or trust_summary
        enriched["evidence_manifest"] = trust_summary.get("evidence_manifest", [])
        degradation_notes = self._as_token_list(execution_plan.get("degradation_notes"))
        enriched["quality_gate"] = {
            "status": "degraded" if bool(execution_plan.get("degraded")) else "ok",
            "notes": degradation_notes,
        }
        return enriched

    def _build_source_trust_summary_from_structured(self, structured: dict[str, Any]) -> dict[str, Any]:
        scout_bundle = {"structured": {"source_trust": []}}
        for source in [item for item in structured.get("global_sources", []) if isinstance(item, dict)]:
            scout_bundle["structured"]["source_trust"].append(
                {
                    **source,
                    **self._normalized_source_identity(source),
                    "trust_class": self._classify_source_trust(source),
                    "reputation_score": self._seed_trust_score(self._classify_source_trust(source)),
                }
            )
        for item in [entry for entry in structured.get("recommendations", []) if isinstance(entry, dict)]:
            for source in [entry for entry in item.get("sources", []) if isinstance(entry, dict)]:
                scout_bundle["structured"]["source_trust"].append(
                    {
                        **source,
                        **self._normalized_source_identity(source),
                        "trust_class": self._classify_source_trust(source),
                        "reputation_score": self._seed_trust_score(self._classify_source_trust(source)),
                    }
                )
        return self._summarize_source_trust(
            scout_bundle=scout_bundle,
            research_intensity=str(structured.get("research_intensity") or "simple"),
        )

    def _apply_reader_overrides(self, *, canonical: dict[str, Any], translated: dict[str, Any]) -> dict[str, Any]:
        merged = dict(translated)
        for key in (
            "research_profile",
            "research_intensity",
            "recommended_profile",
            "recommended_intensity",
            "source_trust_summary",
            "source_reputation_summary",
            "execution_plan",
            "evidence_manifest",
            "quality_gate",
            "metadata",
        ):
            if key in canonical:
                merged[key] = canonical[key]
        canonical_recommendations = [item for item in canonical.get("recommendations", []) if isinstance(item, dict)]
        translated_recommendations = [item for item in merged.get("recommendations", []) if isinstance(item, dict)]
        if len(canonical_recommendations) == len(translated_recommendations):
            for canonical_item, translated_item in zip(canonical_recommendations, translated_recommendations):
                for key in ("goal_link", "sequence_role", "scope_level", "evidence_basis"):
                    translated_item[key] = canonical_item.get(key)
        return merged

    def _call_auxiliary_model(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        schema_name: str,
        description: str,
        attempts: list[tuple[str, dict[str, Any] | None, str]],
        metadata: dict[str, Any],
        response_continuity: dict[str, Any] | None = None,
        continuity_anchor: str | None = None,
        previous_anchor_candidates: list[str] | tuple[str, ...] | None = None,
        previous_response_id_override: str | None = None,
        force_store: bool | None = None,
    ) -> dict[str, Any]:
        phase = str(metadata.get("phase") or schema_name).strip() or schema_name
        route = self._research_route(research_intensity=str(metadata.get("research_intensity") or "simple"))
        self._update_continuity_strategy_for_provider(
            response_continuity=response_continuity,
            provider=str(route["provider"]),
        )
        debug_root = self._debug_root_from_path(metadata.get("debug_root"))
        last_error: Exception | None = None
        previous_response_id = str(previous_response_id_override or "").strip() or self._resolve_continuity_previous_response_id(
            response_continuity=response_continuity,
            anchor_candidates=previous_anchor_candidates,
        )
        previous_response_id = self._sanitize_previous_response_id_for_provider(str(route["provider"]), previous_response_id)
        should_store = bool(force_store) if force_store is not None else bool(response_continuity and response_continuity.get("enabled"))
        if str(route["provider"]) == "anthropic":
            anthropic_tools = (
                [self._anthropic_web_search_tool(phase=phase)]
                if any(tool_payload for _, tool_payload, _ in attempts)
                else []
            )
            counted_tokens: dict[str, Any] = {}
            counted_input_tokens = 0
            try:
                counted_tokens = self._count_anthropic_tokens(
                    model=str(route["model"]),
                    prompt=prompt,
                    tools=anthropic_tools,
                )
                counted_input_tokens = int(counted_tokens.get("input_tokens") or 0)
            except Exception as exc:
                counted_tokens = {"error": str(exc)}
                counted_input_tokens = estimate_text_tokens(prompt)
            try:
                client = self._anthropic_client()
                response = client.messages.create(
                    model=str(route["model"]),
                    max_tokens=2200,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                    tools=anthropic_tools,
                )
                raw_payload = response.model_dump() if hasattr(response, "model_dump") else {"repr": repr(response)}
                output_text = self._extract_anthropic_text_blocks(response)
                payload = self._parse_json_object(
                    output_text,
                    quarantine_context={
                        "request": metadata,
                        "source_system": "deep_research",
                        "source_entity_kind": TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        "source_entity_id": str(metadata.get("job_id") or ""),
                        "provider": "anthropic",
                        "model": str(route["model"]),
                        "phase": phase,
                        "schema_name": schema_name,
                        "raw_payload": raw_payload,
                    },
                )
                if not isinstance(payload, dict):
                    raise RuntimeError(f"{schema_name} returned a non-object payload.")
                response_id = str(getattr(response, "id", None) or "").strip() or None
                usage = self._extract_anthropic_usage(response)
                estimated_cost_eur = self._estimate_provider_usage_cost_eur(
                    provider="anthropic",
                    model=str(route["model"]),
                    usage=usage,
                )
                self._record_response_continuity(
                    response_continuity=response_continuity,
                    anchor=str(continuity_anchor or schema_name),
                    phase=phase,
                    model=str(route["model"]),
                    response_id=response_id,
                    previous_response_id=previous_response_id,
                    stored=False,
                )
                self._append_model_debug_entry(
                    debug_root=debug_root,
                    entry={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "phase": phase,
                        "provider": "anthropic",
                        "model": str(route["model"]),
                        "schema_name": schema_name,
                        "prompt_chars": len(prompt),
                        "estimated_local_tokens": estimate_text_tokens(prompt),
                        "counted_input_tokens": counted_input_tokens,
                        "count_tokens_response": counted_tokens,
                        "actual_usage": usage,
                        "estimated_cost_eur": estimated_cost_eur,
                        "response_id": response_id,
                        "previous_response_id": previous_response_id,
                        "stored": False,
                    },
                )
                payload["_response_id"] = response_id
                payload["_previous_response_id"] = previous_response_id
                payload["_stored"] = False
                payload["_provider"] = "anthropic"
                payload["_model"] = str(route["model"])
                return payload
            except Exception as exc:
                self._append_model_debug_entry(
                    debug_root=debug_root,
                    entry={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "phase": phase,
                        "provider": "anthropic",
                        "model": str(route["model"]),
                        "schema_name": schema_name,
                        "prompt_chars": len(prompt),
                        "estimated_local_tokens": estimate_text_tokens(prompt),
                        "counted_input_tokens": counted_input_tokens,
                        "count_tokens_response": counted_tokens,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                last_error = exc
        api_key = self.secret_resolver.get_required("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        for model_name, tool_payload, reasoning_effort in attempts:
            try:
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "reasoning": {"effort": reasoning_effort},
                    "input": prompt,
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": schema_name,
                            "schema": schema,
                            "strict": True,
                            "description": description,
                        },
                        "verbosity": "medium",
                    },
                    "store": should_store,
                    "metadata": metadata,
                }
                if tool_payload:
                    kwargs["tools"] = [tool_payload]
                if previous_response_id:
                    kwargs["previous_response_id"] = previous_response_id
                response = client.responses.create(**kwargs)
                raw_payload = response.model_dump() if hasattr(response, "model_dump") else {"repr": repr(response)}
                output_text = getattr(response, "output_text", None) or ""
                if not output_text:
                    self._record_output_quarantine(
                        request=metadata,
                        source_system="deep_research",
                        source_entity_kind=TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        source_entity_id=str(metadata.get("job_id") or ""),
                        reason_code=OutputQuarantineReason.MISSING_OUTPUT_TEXT.value,
                        provider="openai",
                        model=model_name,
                        phase=phase,
                        schema_name=schema_name,
                        raw_payload=raw_payload,
                        previous_response_id=previous_response_id,
                        error=f"{schema_name} returned no output_text.",
                    )
                    raise RuntimeError(f"{schema_name} returned no output_text.")
                payload = self._parse_json_object(
                    str(output_text),
                    quarantine_context={
                        "request": metadata,
                        "source_system": "deep_research",
                        "source_entity_kind": TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        "source_entity_id": str(metadata.get("job_id") or ""),
                        "provider": "openai",
                        "model": model_name,
                        "phase": phase,
                        "schema_name": schema_name,
                        "raw_payload": raw_payload,
                        "previous_response_id": previous_response_id,
                        "response_id": str(getattr(response, "id", None) or "").strip() or None,
                    },
                )
                if not isinstance(payload, dict):
                    raise RuntimeError(f"{schema_name} returned a non-object payload.")
                self._record_response_continuity(
                    response_continuity=response_continuity,
                    anchor=str(continuity_anchor or schema_name),
                    phase=phase,
                    model=model_name,
                    response_id=str(getattr(response, "id", None) or "").strip() or None,
                    previous_response_id=previous_response_id,
                    stored=should_store,
                )
                self._append_model_debug_entry(
                    debug_root=debug_root,
                    entry={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "phase": phase,
                        "provider": "openai",
                        "model": model_name,
                        "schema_name": schema_name,
                        "prompt_chars": len(prompt),
                        "estimated_local_tokens": estimate_text_tokens(prompt),
                        "tool_type": str(tool_payload["type"]) if tool_payload else None,
                        "response_id": str(getattr(response, "id", None) or "").strip() or None,
                        "previous_response_id": previous_response_id,
                        "stored": should_store,
                    },
                )
                payload["_response_id"] = str(getattr(response, "id", None) or "").strip() or None
                payload["_previous_response_id"] = previous_response_id
                payload["_stored"] = should_store
                payload["_provider"] = "openai"
                payload["_model"] = model_name
                return payload
            except Exception as exc:
                last_error = exc
                self._append_model_debug_entry(
                    debug_root=debug_root,
                    entry={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "phase": phase,
                        "provider": "openai",
                        "model": model_name,
                        "schema_name": schema_name,
                        "prompt_chars": len(prompt),
                        "estimated_local_tokens": estimate_text_tokens(prompt),
                        "tool_type": str(tool_payload["type"]) if tool_payload else None,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
        raise RuntimeError(f"{schema_name} failed after all attempts.") from last_error

    def _planner_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mission": {"type": "string"},
                "why_this_mode": {"type": "array", "items": {"type": "string"}},
                "angles": {"type": "array", "items": {"type": "string"}},
                "required_lanes": {"type": "array", "items": {"type": "string"}},
                "optional_lanes": {"type": "array", "items": {"type": "string"}},
                "parallel_groups": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                "must_prove": {"type": "array", "items": {"type": "string"}},
                "must_refute": {"type": "array", "items": {"type": "string"}},
                "lane_priority": {"type": "array", "items": {"type": "string"}},
                "needs_papers": {"type": "boolean"},
                "needs_github_depth": {"type": "boolean"},
                "avoid": {"type": "array", "items": {"type": "string"}},
                "scout_focus": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "mission",
                "why_this_mode",
                "angles",
                "required_lanes",
                "optional_lanes",
                "parallel_groups",
                "must_prove",
                "must_refute",
                "lane_priority",
                "needs_papers",
                "needs_github_depth",
                "avoid",
                "scout_focus",
            ],
        }

    def _apply_planner_contract(self, *, execution_plan: dict[str, Any], planner_payload: dict[str, Any]) -> None:
        mode = str(execution_plan.get("mode") or "simple").strip().lower()
        allowed_lanes = {"repo", "official_docs", "github", "papers"}
        required_lanes = [
            lane
            for lane in self._as_token_list(planner_payload.get("required_lanes"))
            if lane in allowed_lanes
        ]
        optional_lanes = [
            lane
            for lane in self._as_token_list(planner_payload.get("optional_lanes"))
            if lane in allowed_lanes and lane not in required_lanes
        ]
        if "repo" not in required_lanes:
            required_lanes.insert(0, "repo")
        scout_lanes = list(required_lanes)
        if mode == "complex":
            if bool(planner_payload.get("needs_papers")) and "papers" not in scout_lanes:
                scout_lanes.append("papers")
            for lane in ("official_docs", "github"):
                if lane not in scout_lanes:
                    scout_lanes.append(lane)
        elif mode == "extreme":
            for lane in ("official_docs", "github", "papers"):
                if lane not in scout_lanes:
                    scout_lanes.append(lane)
        execution_plan["scout_lanes"] = scout_lanes
        raw_parallel_groups = planner_payload.get("parallel_groups")
        parallel_groups: list[list[str]] = []
        if isinstance(raw_parallel_groups, list):
            for item in raw_parallel_groups:
                if not isinstance(item, list):
                    continue
                group = [lane for lane in (str(part).strip() for part in item) if lane in scout_lanes]
                if group:
                    parallel_groups.append(group)
        if not parallel_groups:
            external_lanes = [lane for lane in scout_lanes if lane != "repo"]
            if external_lanes:
                parallel_groups = [external_lanes]
        execution_plan["parallel_groups"] = parallel_groups
        execution_plan["planner_contract"] = {
            "required_lanes": required_lanes,
            "optional_lanes": optional_lanes,
            "parallel_groups": parallel_groups,
            "must_prove": self._as_token_list(planner_payload.get("must_prove")),
            "must_refute": self._as_token_list(planner_payload.get("must_refute")),
            "lane_priority": [lane for lane in self._as_token_list(planner_payload.get("lane_priority")) if lane in scout_lanes],
            "needs_papers": bool(planner_payload.get("needs_papers")),
            "needs_github_depth": bool(planner_payload.get("needs_github_depth")),
        }
        mesh_manifest = execution_plan.get("mesh_manifest")
        if isinstance(mesh_manifest, dict):
            mesh_manifest["planned_lanes"] = scout_lanes
            mesh_manifest["parallel_groups"] = parallel_groups

    def _scout_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "lane": {"type": "string"},
                "summary": {"type": "string"},
                "key_findings": {"type": "array", "items": {"type": "string"}},
                "candidate_systems": {"type": "array", "items": {"type": "string"}},
                "sources": {
                    "type": "array",
                    "items": {
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
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["lane", "summary", "key_findings", "candidate_systems", "sources", "warnings"],
        }

    def _cheap_scout_swarm_schema(self) -> dict[str, Any]:
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
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mission": {"type": "string"},
                "broad_signals": {"type": "array", "items": {"type": "string"}},
                "lane_briefs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "lane": {"type": "string", "enum": ["official_docs", "github", "papers"]},
                            "query_focus": {"type": "array", "items": {"type": "string"}},
                            "must_prove": {"type": "array", "items": {"type": "string"}},
                            "seed_sources": {"type": "array", "items": source_schema},
                            "avoid": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["lane", "query_focus", "must_prove", "seed_sources", "avoid"],
                    },
                },
                "watchouts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["mission", "broad_signals", "lane_briefs", "watchouts"],
        }

    def _skeptic_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "risks": {"type": "array", "items": {"type": "string"}},
                "contradictions": {"type": "array", "items": {"type": "string"}},
                "weak_points": {"type": "array", "items": {"type": "string"}},
                "corrections": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["risks", "contradictions", "weak_points", "corrections"],
        }

    def _call_research_model(
        self,
        *,
        request: dict[str, Any],
        prompt: str,
        response_continuity: dict[str, Any] | None = None,
        continuity_anchor: str | None = None,
        previous_anchor_candidates: list[str] | tuple[str, ...] | None = None,
        previous_response_id_override: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        route = self._research_route_for_request(request)
        self._update_continuity_strategy_for_provider(
            response_continuity=response_continuity,
            provider=str(route["provider"]),
        )
        debug_root = self._debug_root_from_path(request.get("_debug_root"))
        attempts: list[dict[str, Any]] = []
        last_error: Exception | None = None
        previous_response_id = str(previous_response_id_override or "").strip() or self._resolve_continuity_previous_response_id(
            response_continuity=response_continuity,
            anchor_candidates=previous_anchor_candidates,
        )
        previous_response_id = self._sanitize_previous_response_id_for_provider(str(route["provider"]), previous_response_id)
        should_store = bool(response_continuity and response_continuity.get("enabled"))
        if str(route["provider"]) == "anthropic":
            anthropic_tools = [self._anthropic_web_search_tool(phase=str(continuity_anchor or "final_synthesis"))]
            counted_tokens: dict[str, Any] = {}
            counted_input_tokens = 0
            try:
                counted_tokens = self._count_anthropic_tokens(
                    model=str(route["model"]),
                    prompt=prompt,
                    tools=anthropic_tools,
                )
                counted_input_tokens = int(counted_tokens.get("input_tokens") or 0)
            except Exception as exc:
                counted_tokens = {"error": str(exc)}
                counted_input_tokens = estimate_text_tokens(prompt)
            try:
                client = self._anthropic_client()
                response = client.messages.create(
                    model=str(route["model"]),
                    max_tokens=7000,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                    tools=anthropic_tools,
                )
                raw_payload = response.model_dump() if hasattr(response, "model_dump") else {"repr": repr(response)}
                raw_payload["attempts"] = attempts
                output_text = self._extract_anthropic_text_blocks(response)
                structured = self._parse_json_object(
                    str(output_text),
                    quarantine_context={
                        "request": request,
                        "source_system": "deep_research",
                        "source_entity_kind": TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        "source_entity_id": str(request.get("job_id") or ""),
                        "provider": "anthropic",
                        "model": str(route["model"]),
                        "phase": str(continuity_anchor or "final_synthesis"),
                        "schema_name": "project_os_deep_research_result",
                        "raw_payload": raw_payload,
                    },
                )
                structured["metadata"] = {
                    **dict(structured.get("metadata") or {}),
                    "provider": "anthropic",
                    "model": str(route["model"]),
                    "tool_type": "web_search_20250305",
                }
                response_id = str(getattr(response, "id", None) or "").strip() or None
                self._record_response_continuity(
                    response_continuity=response_continuity,
                    anchor=str(continuity_anchor or "final_synthesis"),
                    phase=str(continuity_anchor or "final_synthesis"),
                    model=str(route["model"]),
                    response_id=response_id,
                    previous_response_id=previous_response_id,
                    stored=False,
                )
                usage = self._extract_anthropic_usage(response)
                estimated_cost_eur = self._estimate_provider_usage_cost_eur(
                    provider="anthropic",
                    model=str(route["model"]),
                    usage=usage,
                )
                self._append_model_debug_entry(
                    debug_root=debug_root,
                    entry={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "phase": str(continuity_anchor or "final_synthesis"),
                        "provider": "anthropic",
                        "model": str(route["model"]),
                        "prompt_chars": len(prompt),
                        "estimated_local_tokens": estimate_text_tokens(prompt),
                        "counted_input_tokens": counted_input_tokens,
                        "count_tokens_response": counted_tokens,
                        "actual_usage": usage,
                        "estimated_cost_eur": estimated_cost_eur,
                        "response_id": response_id,
                        "previous_response_id": previous_response_id,
                        "stored": False,
                    },
                )
                return structured, raw_payload, usage
            except Exception as exc:
                self._append_model_debug_entry(
                    debug_root=debug_root,
                    entry={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "phase": str(continuity_anchor or "final_synthesis"),
                        "provider": "anthropic",
                        "model": str(route["model"]),
                        "prompt_chars": len(prompt),
                        "estimated_local_tokens": estimate_text_tokens(prompt),
                        "counted_input_tokens": counted_input_tokens,
                        "count_tokens_response": counted_tokens,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                last_error = exc
        api_key = self.secret_resolver.get_required("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        for model_name, tool_payload in self._research_attempts():
            try:
                kwargs: dict[str, Any] = {
                    "model": model_name,
                    "reasoning": {"effort": self.default_reasoning_effort},
                    "input": prompt,
                    "tools": [tool_payload],
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "project_os_deep_research_result",
                            "schema": self._output_schema(),
                            "strict": True,
                            "description": "Structured output for a Project OS deep research dossier",
                        },
                        "verbosity": "high",
                    },
                    "store": should_store,
                    "metadata": {
                        "job_id": str(request.get("job_id") or ""),
                        "kind": str(request.get("kind") or "audit"),
                        "research_profile": str(request.get("research_profile") or ""),
                    },
                }
                if previous_response_id:
                    kwargs["previous_response_id"] = previous_response_id
                response = client.responses.create(**kwargs)
                raw_payload = response.model_dump() if hasattr(response, "model_dump") else {"repr": repr(response)}
                raw_payload["attempts"] = attempts
                output_text = getattr(response, "output_text", None) or raw_payload.get("output_text")
                if not output_text:
                    self._record_output_quarantine(
                        request=request,
                        source_system="deep_research",
                        source_entity_kind=TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        source_entity_id=str(request.get("job_id") or ""),
                        reason_code=OutputQuarantineReason.MISSING_OUTPUT_TEXT.value,
                        provider="openai",
                        model=model_name,
                        phase=str(continuity_anchor or "final_synthesis"),
                        schema_name="project_os_deep_research_result",
                        raw_payload=raw_payload,
                        previous_response_id=previous_response_id,
                        error="Deep research response returned no output_text.",
                    )
                    raise RuntimeError("Deep research response returned no output_text.")
                structured = self._parse_json_object(
                    str(output_text),
                    quarantine_context={
                        "request": request,
                        "source_system": "deep_research",
                        "source_entity_kind": TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        "source_entity_id": str(request.get("job_id") or ""),
                        "provider": "openai",
                        "model": model_name,
                        "phase": str(continuity_anchor or "final_synthesis"),
                        "schema_name": "project_os_deep_research_result",
                        "raw_payload": raw_payload,
                        "response_id": str(getattr(response, "id", None) or "").strip() or None,
                        "previous_response_id": previous_response_id,
                    },
                )
                structured["metadata"] = {
                    **dict(structured.get("metadata") or {}),
                    "provider": "openai",
                    "model": model_name,
                    "tool_type": str(tool_payload["type"]),
                }
                self._record_response_continuity(
                    response_continuity=response_continuity,
                    anchor=str(continuity_anchor or "final_synthesis"),
                    phase=str(continuity_anchor or "final_synthesis"),
                    model=model_name,
                    response_id=str(getattr(response, "id", None) or "").strip() or None,
                    previous_response_id=previous_response_id,
                    stored=should_store,
                )
                usage = self._extract_usage(raw_payload, response)
                self._append_model_debug_entry(
                    debug_root=debug_root,
                    entry={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "phase": str(continuity_anchor or "final_synthesis"),
                        "provider": "openai",
                        "model": model_name,
                        "prompt_chars": len(prompt),
                        "estimated_local_tokens": estimate_text_tokens(prompt),
                        "tool_type": str(tool_payload["type"]),
                        "response_id": str(getattr(response, "id", None) or "").strip() or None,
                        "previous_response_id": previous_response_id,
                        "stored": should_store,
                        "actual_usage": usage,
                        "estimated_cost_eur": self._estimate_provider_usage_cost_eur(
                            provider="openai",
                            model=model_name,
                            usage=usage,
                        ),
                    },
                )
                return structured, raw_payload, usage
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
                self._append_model_debug_entry(
                    debug_root=debug_root,
                    entry={
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "phase": str(continuity_anchor or "final_synthesis"),
                        "provider": "openai",
                        "model": model_name,
                        "prompt_chars": len(prompt),
                        "estimated_local_tokens": estimate_text_tokens(prompt),
                        "tool_type": str(tool_payload["type"]),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
        detail = "; ".join(f"{item['model']}:{item['tool_type']} -> {item['error_type']}" for item in attempts)
        raise RuntimeError(f"Deep research OpenAI call failed after fallbacks. {detail}") from last_error

    def _translate_structured_for_reader(self, *, request: dict[str, Any], structured: dict[str, Any]) -> dict[str, Any]:
        api_key = self.secret_resolver.get_required("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        prompt = textwrap.dedent(
            f"""
            You translate a Project OS deep research JSON payload from English into French for the human-reader PDF.

            Translation rules:
            - preserve the JSON structure exactly
            - translate every human-language string into French
            - keep enum values unchanged: `a_faire`, `a_etudier`, `a_rejeter`, `KEEP`, `ADAPT`, `DEFER`, `REJECT`
            - keep URLs, absolute dates, code identifiers, file paths, package names, API names, and product names unchanged unless a natural French sentence requires surrounding translation
            - `seo_title` should become a natural French reader title, not a slug
            - `metadata` values must stay unchanged

            Return strict JSON only.

            Source JSON:
            {json.dumps(structured, ensure_ascii=True, indent=2, sort_keys=True)}
            """
        ).strip()
        attempts: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for model_name in self._translation_attempts():
            try:
                response = client.responses.create(
                    model=model_name,
                    reasoning={"effort": "low"},
                    input=prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "project_os_deep_research_reader_fr",
                            "schema": self._output_schema(),
                            "strict": True,
                            "description": "French reader-facing version of the canonical English deep research payload",
                        },
                        "verbosity": "medium",
                    },
                    store=False,
                    metadata={
                        "job_id": str(request.get("job_id") or ""),
                        "kind": str(request.get("kind") or "audit"),
                        "research_profile": str(request.get("research_profile") or ""),
                        "translation_target": "fr",
                    },
                )
                output_text = getattr(response, "output_text", None) or ""
                if not output_text:
                    raw_payload = response.model_dump() if hasattr(response, "model_dump") else {"repr": repr(response)}
                    self._record_output_quarantine(
                        request=request,
                        source_system="deep_research_translation",
                        source_entity_kind=TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        source_entity_id=str(request.get("job_id") or ""),
                        reason_code=OutputQuarantineReason.MISSING_OUTPUT_TEXT.value,
                        provider="openai",
                        model=model_name,
                        phase="reader_translation",
                        schema_name="project_os_deep_research_reader_fr",
                        raw_payload=raw_payload,
                        error="Reader translation returned no output_text.",
                    )
                    raise RuntimeError("Reader translation returned no output_text.")
                translated = self._parse_json_object(
                    str(output_text),
                    quarantine_context={
                        "request": request,
                        "source_system": "deep_research_translation",
                        "source_entity_kind": TraceEntityKind.DEEP_RESEARCH_JOB.value,
                        "source_entity_id": str(request.get("job_id") or ""),
                        "provider": "openai",
                        "model": model_name,
                        "phase": "reader_translation",
                        "schema_name": "project_os_deep_research_reader_fr",
                        "raw_payload": response.model_dump() if hasattr(response, "model_dump") else {"repr": repr(response)},
                        "response_id": str(getattr(response, "id", None) or "").strip() or None,
                    },
                )
                translated["metadata"] = dict(structured.get("metadata") or {})
                return translated
            except Exception as exc:
                attempts.append(
                    {
                        "model": model_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                last_error = exc
        self.logger.log(
            "warning",
            "deep_research_reader_translation_failed",
            job_id=str(request.get("job_id") or ""),
            errors=attempts,
        )
        self.journal.append(
            "deep_research_reader_translation_failed",
            "deep_research",
            {
                "job_id": str(request.get("job_id") or ""),
                "errors": attempts,
            },
        )
        return structured

    def _research_attempts(self) -> list[tuple[str, dict[str, Any]]]:
        candidates = [
            (self.research_model, {"type": "web_search", "search_context_size": "high"}),
            (self.research_model, {"type": "web_search_preview", "search_context_size": "high"}),
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

    def _translation_attempts(self) -> list[str]:
        return self._openai_translation_candidates()

    def _extract_usage(self, raw_payload: dict[str, Any], response: Any) -> dict[str, Any]:
        usage = raw_payload.get("usage")
        if usage is None and hasattr(response, "usage") and getattr(response, "usage") is not None:
            usage_obj = getattr(response, "usage")
            usage = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else dict(usage_obj)
        return dict(usage or {})

    @staticmethod
    def _preview_text(value: Any, *, max_chars: int = 16_000) -> str | None:
        text = str(value or "")
        if not text:
            return None
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars].rstrip()}...[truncated]"

    def _record_output_quarantine(
        self,
        *,
        request: dict[str, Any],
        source_system: str,
        source_entity_kind: str,
        source_entity_id: str,
        reason_code: str,
        provider: str | None,
        model: str | None,
        phase: str | None,
        schema_name: str | None,
        raw_payload: dict[str, Any] | None = None,
        output_text: str | None = None,
        response_id: str | None = None,
        previous_response_id: str | None = None,
        error: str,
    ) -> str:
        resolved_entity_id = source_entity_id or "unknown_deep_research_job"
        quarantine_id = self.journal.database.record_output_quarantine(
            source_system=source_system,
            source_entity_kind=source_entity_kind,
            source_entity_id=resolved_entity_id,
            reason_code=reason_code,
            provider=provider,
            model=model,
            response_id=response_id,
            previous_response_id=previous_response_id,
            record_locator=str(request.get("job_id") or request.get("title") or "").strip() or None,
            payload={
                "raw_payload": raw_payload or {},
                "output_text_preview": self._preview_text(output_text),
            },
            metadata={
                "job_id": str(request.get("job_id") or "").strip() or None,
                "phase": phase,
                "schema_name": schema_name,
                "error": error,
            },
        )
        self.journal.database.record_trace_edge(
            parent_id=resolved_entity_id,
            parent_kind=source_entity_kind,
            child_id=quarantine_id,
            child_kind=TraceEntityKind.OUTPUT_QUARANTINE.value,
            relation=TraceRelationKind.QUARANTINED_AS.value,
            metadata={"reason_code": reason_code, "phase": phase},
        )
        self.logger.log(
            "WARNING",
            "deep_research_output_quarantined",
            quarantine_id=quarantine_id,
            source_system=source_system,
            reason_code=reason_code,
            job_id=str(request.get("job_id") or "").strip() or None,
            provider=provider,
            model=model,
            phase=phase,
        )
        return quarantine_id

    def _parse_json_object(self, output_text: str, *, quarantine_context: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = output_text.strip()
        if not raw:
            if quarantine_context:
                self._record_output_quarantine(
                    request=dict(quarantine_context.get("request") or {}),
                    source_system=str(quarantine_context.get("source_system") or "deep_research"),
                    source_entity_kind=str(quarantine_context.get("source_entity_kind") or TraceEntityKind.DEEP_RESEARCH_JOB.value),
                    source_entity_id=str(quarantine_context.get("source_entity_id") or ""),
                    reason_code=OutputQuarantineReason.MISSING_OUTPUT_TEXT.value,
                    provider=str(quarantine_context.get("provider") or "").strip() or None,
                    model=str(quarantine_context.get("model") or "").strip() or None,
                    phase=str(quarantine_context.get("phase") or "").strip() or None,
                    schema_name=str(quarantine_context.get("schema_name") or "").strip() or None,
                    raw_payload=dict(quarantine_context.get("raw_payload") or {}),
                    output_text=output_text,
                    response_id=str(quarantine_context.get("response_id") or "").strip() or None,
                    previous_response_id=str(quarantine_context.get("previous_response_id") or "").strip() or None,
                    error="Deep research output is empty.",
                )
            raise RuntimeError("Deep research output is empty.")
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            if quarantine_context:
                self._record_output_quarantine(
                    request=dict(quarantine_context.get("request") or {}),
                    source_system=str(quarantine_context.get("source_system") or "deep_research"),
                    source_entity_kind=str(quarantine_context.get("source_entity_kind") or TraceEntityKind.DEEP_RESEARCH_JOB.value),
                    source_entity_id=str(quarantine_context.get("source_entity_id") or ""),
                    reason_code=OutputQuarantineReason.INVALID_JSON.value,
                    provider=str(quarantine_context.get("provider") or "").strip() or None,
                    model=str(quarantine_context.get("model") or "").strip() or None,
                    phase=str(quarantine_context.get("phase") or "").strip() or None,
                    schema_name=str(quarantine_context.get("schema_name") or "").strip() or None,
                    raw_payload=dict(quarantine_context.get("raw_payload") or {}),
                    output_text=output_text,
                    response_id=str(quarantine_context.get("response_id") or "").strip() or None,
                    previous_response_id=str(quarantine_context.get("previous_response_id") or "").strip() or None,
                    error="Deep research output is not valid JSON.",
                )
            raise RuntimeError("Deep research output is not valid JSON.")
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            if quarantine_context:
                self._record_output_quarantine(
                    request=dict(quarantine_context.get("request") or {}),
                    source_system=str(quarantine_context.get("source_system") or "deep_research"),
                    source_entity_kind=str(quarantine_context.get("source_entity_kind") or TraceEntityKind.DEEP_RESEARCH_JOB.value),
                    source_entity_id=str(quarantine_context.get("source_entity_id") or ""),
                    reason_code=OutputQuarantineReason.INVALID_JSON.value,
                    provider=str(quarantine_context.get("provider") or "").strip() or None,
                    model=str(quarantine_context.get("model") or "").strip() or None,
                    phase=str(quarantine_context.get("phase") or "").strip() or None,
                    schema_name=str(quarantine_context.get("schema_name") or "").strip() or None,
                    raw_payload=dict(quarantine_context.get("raw_payload") or {}),
                    output_text=output_text,
                    response_id=str(quarantine_context.get("response_id") or "").strip() or None,
                    previous_response_id=str(quarantine_context.get("previous_response_id") or "").strip() or None,
                    error=str(exc),
                )
            raise RuntimeError("Deep research output is not valid JSON.") from exc
        if not isinstance(payload, dict):
            if quarantine_context:
                self._record_output_quarantine(
                    request=dict(quarantine_context.get("request") or {}),
                    source_system=str(quarantine_context.get("source_system") or "deep_research"),
                    source_entity_kind=str(quarantine_context.get("source_entity_kind") or TraceEntityKind.DEEP_RESEARCH_JOB.value),
                    source_entity_id=str(quarantine_context.get("source_entity_id") or ""),
                    reason_code=OutputQuarantineReason.NON_OBJECT_PAYLOAD.value,
                    provider=str(quarantine_context.get("provider") or "").strip() or None,
                    model=str(quarantine_context.get("model") or "").strip() or None,
                    phase=str(quarantine_context.get("phase") or "").strip() or None,
                    schema_name=str(quarantine_context.get("schema_name") or "").strip() or None,
                    raw_payload=dict(quarantine_context.get("raw_payload") or {}),
                    output_text=output_text,
                    response_id=str(quarantine_context.get("response_id") or "").strip() or None,
                    previous_response_id=str(quarantine_context.get("previous_response_id") or "").strip() or None,
                    error="Deep research output root must be a JSON object.",
                )
            raise RuntimeError("Deep research output root must be a JSON object.")
        return payload

    def _validate_structured_result(self, *, request: dict[str, Any], structured: dict[str, Any]) -> None:
        expected_profile = self._request_research_profile(
            kind=str(request.get("kind") or "audit"),
            question=str(request.get("question") or ""),
            research_profile=request.get("research_profile"),
        )
        expected_intensity = self._request_research_intensity(
            kind=str(request.get("kind") or "audit"),
            question=str(request.get("question") or ""),
            research_profile=expected_profile,
            research_intensity=request.get("research_intensity"),
        )
        actual_profile = str(structured.get("research_profile") or "").strip().lower()
        actual_intensity = str(structured.get("research_intensity") or "").strip().lower()
        if actual_profile != expected_profile:
            raise RuntimeError(
                f"Deep research profile mismatch: expected {expected_profile}, got {actual_profile or 'missing'}."
            )
        if actual_intensity != expected_intensity:
            raise RuntimeError(
                f"Deep research intensity mismatch: expected {expected_intensity}, got {actual_intensity or 'missing'}."
            )
        recommendations = [item for item in structured.get("recommendations", []) if isinstance(item, dict)]
        if not recommendations:
            raise RuntimeError("Deep research output must include at least one recommendation.")
        if expected_profile == "project_audit":
            self._validate_project_audit(structured=structured, recommendations=recommendations)
        elif expected_profile == "component_discovery":
            self._validate_component_discovery(structured=structured, recommendations=recommendations)
        else:
            self._validate_domain_audit(structured=structured)
        self._validate_intensity_contract(
            structured=structured,
            recommendations=recommendations,
            research_profile=expected_profile,
            research_intensity=expected_intensity,
        )

    def _validate_intensity_contract(
        self,
        *,
        structured: dict[str, Any],
        recommendations: list[dict[str, Any]],
        research_profile: str,
        research_intensity: str,
    ) -> None:
        execution_plan = structured.get("execution_plan")
        if not isinstance(execution_plan, dict):
            raise RuntimeError("Deep research result must include `execution_plan`.")
        requested_mode = str(execution_plan.get("requested_mode") or execution_plan.get("mode") or "").strip().lower()
        effective_mode = str(execution_plan.get("effective_mode") or execution_plan.get("mode") or "").strip().lower()
        degraded = bool(execution_plan.get("degraded"))
        if requested_mode != research_intensity:
            raise RuntimeError("Deep research execution plan intensity does not match the request.")
        trust_summary = structured.get("source_trust_summary")
        if not isinstance(trust_summary, dict):
            raise RuntimeError("Deep research result must include `source_trust_summary`.")
        reputation_summary = structured.get("source_reputation_summary")
        if research_intensity in {"complex", "extreme"} and not isinstance(reputation_summary, dict):
            raise RuntimeError("Complex and extreme deep research results must include `source_reputation_summary`.")
        evidence_manifest = structured.get("evidence_manifest")
        if not isinstance(evidence_manifest, list):
            raise RuntimeError("Deep research result must include `evidence_manifest`.")
        if degraded:
            if not self._as_token_list(execution_plan.get("degradation_notes")):
                raise RuntimeError("Degraded deep research runs must record degradation notes.")
            if effective_mode not in _VALID_RESEARCH_INTENSITIES:
                raise RuntimeError("Degraded deep research runs must record a valid effective mode.")
            return
        if effective_mode != research_intensity:
            raise RuntimeError("Deep research effective execution mode does not match the request.")
        if research_intensity == "simple":
            if research_profile != "domain_audit" and not evidence_manifest and not bool(structured.get("repo_fit")):
                raise RuntimeError("Simple deep research still requires at least one external source unless the question is repo-only.")
            return
        if research_intensity == "complex":
            if str(execution_plan.get("mesh_level") or "").strip().lower() != "in_process_parallel":
                raise RuntimeError("Complex deep research must use the in-process parallel committee mesh.")
            if len(self._as_token_list(execution_plan.get("scout_lanes"))) < 3:
                raise RuntimeError("Complex deep research requires a committee-light scout plan.")
            lane_status = execution_plan.get("lane_status")
            if not isinstance(lane_status, dict) or len(lane_status) < 2:
                raise RuntimeError("Complex deep research must report lane status.")
            successful = sum(
                1
                for payload in lane_status.values()
                if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "completed"
            )
            if successful < 2:
                raise RuntimeError("Complex deep research requires at least two successful scout lanes unless degraded.")
            continuity = execution_plan.get("response_continuity")
            if not isinstance(continuity, dict) or not bool(continuity.get("enabled")):
                raise RuntimeError("Complex deep research must record response continuity metadata.")
            if "final_synthesis" not in self._as_token_list(continuity.get("anchors")):
                raise RuntimeError("Complex deep research continuity must reach final synthesis.")
            return
        if research_intensity == "extreme":
            if str(execution_plan.get("mesh_level") or "").strip().lower() != "child_worker_mesh":
                raise RuntimeError("Extreme deep research must use the child-worker mesh.")
            if not bool((execution_plan.get("safety_gate") or {}).get("mandatory")):
                raise RuntimeError("Extreme deep research requires a mandatory source safety gate.")
            cheap_scout_summary = execution_plan.get("cheap_scout_summary")
            if not isinstance(cheap_scout_summary, dict):
                raise RuntimeError("Extreme deep research requires a cheap scout swarm summary.")
            counts = trust_summary.get("counts") if isinstance(trust_summary, dict) else {}
            trusted_count = int(counts.get("trusted_primary", 0)) + int(counts.get("trusted_ecosystem", 0))
            if trusted_count < 2:
                raise RuntimeError("Extreme deep research requires at least two trusted sources after the safety gate.")
            trusted_domains = self._as_token_list(trust_summary.get("trusted_domains"))
            if len(trusted_domains) < 2:
                raise RuntimeError("Extreme deep research requires trusted evidence from at least two unique domains.")
            trusted_lanes = self._as_token_list(trust_summary.get("trusted_lanes"))
            if len(trusted_lanes) < 2:
                raise RuntimeError("Extreme deep research requires trusted evidence across at least two scout lanes.")
            if str(cheap_scout_summary.get("status") or "").strip().lower() != "completed":
                raise RuntimeError("Extreme deep research requires a completed cheap scout swarm unless the run is degraded.")
            if int(cheap_scout_summary.get("lane_brief_count") or 0) < 2:
                raise RuntimeError("Extreme deep research requires the cheap scout swarm to seed at least two specialist lanes.")
            mesh_manifest = execution_plan.get("mesh_manifest")
            if not isinstance(mesh_manifest, dict):
                raise RuntimeError("Extreme deep research requires mesh artifacts in `mesh_manifest`.")
            launched_lanes = self._as_token_list(mesh_manifest.get("launched_lanes"))
            if len(launched_lanes) < 4:
                raise RuntimeError("Extreme deep research must launch multiple child lanes.")
            lane_status = execution_plan.get("lane_status")
            if not isinstance(lane_status, dict) or not lane_status:
                raise RuntimeError("Extreme deep research must report lane status.")
            continuity = execution_plan.get("response_continuity")
            if not isinstance(continuity, dict) or not bool(continuity.get("enabled")):
                raise RuntimeError("Extreme deep research must record response continuity metadata.")
            if "final_synthesis" not in self._as_token_list(continuity.get("anchors")):
                raise RuntimeError("Extreme deep research continuity must reach final synthesis.")
            contradiction_signal = self._as_token_list(execution_plan.get("contradiction_signal"))
            if not contradiction_signal:
                raise RuntimeError("Extreme deep research must include a contradiction signal, even if none were found.")
            if not isinstance(structured.get("global_sources"), list) or len(structured.get("global_sources", [])) < 2:
                raise RuntimeError("Extreme deep research requires a stronger multi-source synthesis.")
            if research_profile == "component_discovery" and not any(self._recommendation_has_ecosystem_signal(item) for item in recommendations):
                raise RuntimeError("Extreme component discovery requires clear ecosystem leverage.")

    def _validate_project_audit(self, *, structured: dict[str, Any], recommendations: list[dict[str, Any]]) -> None:
        block = structured.get("project_audit_block")
        if not isinstance(block, dict):
            raise RuntimeError("Project audit output must include `project_audit_block`.")
        for key in ("north_star", "system_thesis", "platform_layers", "capability_gaps", "priority_ladder", "observed_runtime_issues", "success_metrics"):
            value = block.get(key)
            if key == "north_star":
                if not str(value or "").strip():
                    raise RuntimeError("Project audit block requires a non-empty `north_star`.")
            elif not value:
                raise RuntimeError(f"Project audit block requires `{key}`.")
        actionable = [
            item
            for item in recommendations
            if str(item.get("bucket") or "").strip().lower() == "a_faire"
        ] or recommendations
        if all(str(item.get("scope_level") or "").strip().lower() == "local_hardening" for item in actionable):
            raise RuntimeError("Project audit drifted into local hardening only.")
        if not any(
            any(
                token in {"master_agent", "manager_agents", "execution_surfaces", "verification", "memory", "evals", "operator_control"}
                for token in self._as_token_list(item.get("goal_link"))
            )
            for item in actionable
        ):
            raise RuntimeError("Project audit recommendations do not connect to the larger Project OS architecture.")

    def _validate_component_discovery(self, *, structured: dict[str, Any], recommendations: list[dict[str, Any]]) -> None:
        block = structured.get("component_discovery_block")
        if not isinstance(block, dict):
            raise RuntimeError("Component discovery output must include `component_discovery_block`.")
        for key in (
            "blind_spots",
            "external_leverage",
            "underbuilt_layers",
            "priority_ladder",
            "observed_runtime_issues",
            "stop_doing_or_deprioritize",
            "success_metrics",
        ):
            if not block.get(key):
                raise RuntimeError(f"Component discovery block requires `{key}`.")
        if not any(self._recommendation_has_ecosystem_signal(item) for item in recommendations):
            raise RuntimeError("Component discovery output must include GitHub/fork/satellite-driven leverage.")
        actionable = [
            item
            for item in recommendations
            if str(item.get("bucket") or "").strip().lower() == "a_faire"
        ] or recommendations
        if not any("web" in self._as_token_list(item.get("evidence_basis")) for item in actionable):
            raise RuntimeError("Component discovery requires external evidence on at least one actionable recommendation.")
        if not any(self._recommendation_has_ecosystem_signal(item) for item in actionable):
            raise RuntimeError("Component discovery actionable items must include at least one ecosystem signal.")
        for item in actionable:
            if not str(item.get("blind_spot_addressed") or "").strip():
                raise RuntimeError("Each actionable component discovery item must include `blind_spot_addressed`.")

    def _validate_domain_audit(self, *, structured: dict[str, Any]) -> None:
        domain_text = " ".join(
            [
                str(structured.get("summary") or "").strip(),
                " ".join(self._as_token_list(structured.get("why_now"))),
                " ".join(self._as_token_list(structured.get("repo_fit"))),
            ]
        ).lower()
        if domain_text.count("project os") > 5:
            raise RuntimeError("Domain audit drifted into Project OS meta-commentary.")

    def _recommendation_has_ecosystem_signal(self, item: dict[str, Any]) -> bool:
        for line in self._as_token_list(item.get("fork_signal")):
            lowered = line.lower()
            if any(token in lowered for token in ("fork", "satellite", "plugin", "wrapper", "github", "upstream")):
                return True
        for source in [source for source in item.get("sources", []) if isinstance(source, dict)]:
            url = str(source.get("url") or "").strip().lower()
            if "github.com" in url:
                return True
        return False

    def _as_token_list(self, payload: Any) -> list[str]:
        if isinstance(payload, str):
            text = payload.strip()
            return [text] if text else []
        if isinstance(payload, list):
            return [str(item).strip() for item in payload if str(item).strip()]
        return []

    def _render_dossier_markdown(
        self,
        *,
        request: dict[str, Any],
        repo_context: dict[str, Any],
        structured: dict[str, Any],
        dossier_path: Path,
    ) -> str:
        kind = str(request.get("kind") or "audit").strip().lower()
        research_profile = self._request_research_profile(
            kind=kind,
            question=str(request.get("question") or ""),
            research_profile=structured.get("research_profile") or request.get("research_profile"),
        )
        research_intensity = self._request_research_intensity(
            kind=kind,
            question=str(request.get("question") or ""),
            research_profile=research_profile,
            research_intensity=structured.get("research_intensity") or request.get("research_intensity"),
        )
        recommendations = [item for item in structured.get("recommendations", []) if isinstance(item, dict)]
        grouped = {
            "a_faire": [item for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_faire"],
            "a_etudier": [item for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_etudier"],
            "a_rejeter": [item for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_rejeter"],
        }
        lines = [
            f"# {structured.get('seo_title') or request['title']}",
            "",
            "## Status",
            "",
            "- `completed`",
            f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
            f"- type: `{kind}`",
            f"- research_profile: `{research_profile}`",
            f"- research_intensity: `{research_intensity}`",
            f"- seo_slug: `{request.get('seo_slug') or build_seo_slug(str(structured.get('seo_title') or request['title']))}`",
            "- canonical_language: `en`",
        ]
        quality_gate = structured.get("quality_gate") or {}
        quality_status = str(quality_gate.get("status") or "").strip()
        if quality_status:
            lines.append(f"- quality_gate: `{quality_status}`")
        for note in self._as_token_list(quality_gate.get("notes"))[:3]:
            lines.append(f"- quality_note: {note}")
        lines.extend(
            [
                "",
                "## Research Question",
                "",
                f"- {str(request.get('question') or '').strip()}",
                "",
                "## Executive Summary",
                "",
                *self._bulletize(structured.get("summary"), fallback="- missing summary"),
                "",
            ]
        )
        lines.extend(self._render_execution_plan_sections(structured=structured))
        lines.extend(self._render_profile_sections(research_profile=research_profile, structured=structured))
        lines.extend(self._render_repo_snapshot(repo_context=repo_context, dossier_path=dossier_path))
        lines.extend(["", "## Recommendations", ""])
        lines.extend(["### Do Now", ""])
        lines.extend(self._render_recommendation_group(grouped["a_faire"], research_profile=research_profile))
        lines.extend(["", "### Study Later", ""])
        lines.extend(self._render_recommendation_group(grouped["a_etudier"], research_profile=research_profile))
        lines.extend(["", "### Reject For Now", ""])
        lines.extend(self._render_recommendation_group(grouped["a_rejeter"], research_profile=research_profile))
        if research_profile == "component_discovery":
            block = structured.get("component_discovery_block") or {}
            lines.extend(["", "## Stop Doing or Deprioritize", ""])
            lines.extend(self._bulletize(block.get("stop_doing_or_deprioritize")))
        if research_profile in {"project_audit", "component_discovery"}:
            lines.extend(["", "## Success Metrics", ""])
            lines.extend(self._bulletize((structured.get(f"{research_profile}_block") or {}).get("success_metrics")))
        lines.extend(["", "## Risks", ""])
        lines.extend(self._bulletize(structured.get("risks")))
        lines.extend(["", "## Open Questions", ""])
        lines.extend(self._bulletize(structured.get("open_questions")))
        lines.extend(["", "## Sources", ""])
        lines.extend(self._render_source_list(structured.get("global_sources")))
        if kind == "system":
            lines.extend(["", "## Local References Reviewed", ""])
            for ref in repo_context.get("local_refs", []):
                relative = self._relative_link(dossier_path.parent, Path(str(ref["path"])))
                lines.append(f"- [{ref['relative_path']}]({relative})")
        return "\n".join(lines).rstrip() + "\n"

    def _render_execution_plan_sections(self, *, structured: dict[str, Any]) -> list[str]:
        execution_plan = structured.get("execution_plan") or {}
        source_reputation = structured.get("source_reputation_summary") or structured.get("source_trust_summary") or {}
        counts = source_reputation.get("counts") if isinstance(source_reputation, dict) else {}
        lines = [
            "## Execution Plan",
            "",
            f"- requested_mode: `{str(execution_plan.get('requested_mode') or execution_plan.get('mode') or structured.get('research_intensity') or 'simple').strip()}`",
            f"- effective_mode: `{str(execution_plan.get('effective_mode') or execution_plan.get('mode') or structured.get('research_intensity') or 'simple').strip()}`",
            f"- mesh_level: `{str(execution_plan.get('mesh_level') or 'single').strip()}`",
            f"- recommended_profile: `{str(structured.get('recommended_profile') or structured.get('research_profile') or 'domain_audit').strip()}`",
            f"- recommended_intensity: `{str(structured.get('recommended_intensity') or structured.get('research_intensity') or 'simple').strip()}`",
            "",
            "### Phases",
            "",
            *self._bulletize(execution_plan.get("phases")),
            "",
        ]
        if bool(execution_plan.get("degraded")):
            lines.extend(["### Degradation Notes", "", *self._bulletize(execution_plan.get("degradation_notes")), ""])
        provider_route = execution_plan.get("provider_route")
        if isinstance(provider_route, dict) and provider_route:
            lines.extend(
                [
                    "### Provider Route",
                    "",
                    f"- research_provider: `{str(provider_route.get('research_provider') or 'openai').strip()}`",
                    f"- research_model: `{str(provider_route.get('research_model') or self.research_model).strip()}`",
                    f"- scout_model: `{str(provider_route.get('scout_model') or self.scout_model).strip()}`",
                    f"- translation_provider: `{str(provider_route.get('translation_provider') or 'openai').strip()}`",
                    f"- translation_model: `{str(provider_route.get('translation_model') or '').strip()}`",
                    "",
                ]
            )
        response_continuity = execution_plan.get("response_continuity")
        if isinstance(response_continuity, dict) and response_continuity:
            lines.extend(
                [
                    "### Response Continuity",
                    "",
                    f"- enabled: `{str(bool(response_continuity.get('enabled'))).lower()}`",
                    f"- scope: `{str(response_continuity.get('scope') or 'disabled').strip()}`",
                    f"- strategy: `{str(response_continuity.get('strategy') or 'none').strip()}`",
                    f"- anchors: `{len(self._as_token_list(response_continuity.get('anchors')) if isinstance(response_continuity, dict) else [])}`",
                    f"- trail_count: `{int(response_continuity.get('trail_count') or 0)}`",
                    "",
                ]
            )
            if self._as_token_list(response_continuity.get("notes")):
                lines.extend(["#### Continuity Notes", "", *self._bulletize(response_continuity.get("notes")), ""])
        cheap_scout_summary = execution_plan.get("cheap_scout_summary")
        if isinstance(cheap_scout_summary, dict) and cheap_scout_summary:
            lines.extend(
                [
                    "### Cheap Scout Swarm",
                    "",
                    f"- status: `{str(cheap_scout_summary.get('status') or 'unknown').strip()}`",
                    f"- lane_brief_count: `{int(cheap_scout_summary.get('lane_brief_count') or 0)}`",
                    f"- broad_signal_count: `{int(cheap_scout_summary.get('broad_signal_count') or 0)}`",
                    "",
                ]
            )
            if self._as_token_list(cheap_scout_summary.get("watchouts")):
                lines.extend(["#### Swarm Watchouts", "", *self._bulletize(cheap_scout_summary.get("watchouts")), ""])
        if self._as_token_list(execution_plan.get("scout_lanes")):
            lines.extend(["### Scout Lanes", "", *self._bulletize(execution_plan.get("scout_lanes")), ""])
        mesh_manifest = execution_plan.get("mesh_manifest")
        if isinstance(mesh_manifest, dict) and mesh_manifest:
            lines.extend(
                [
                    "### Mesh Manifest",
                    "",
                    f"- concurrency_cap: `{int(mesh_manifest.get('concurrency_cap') or 1)}`",
                    f"- launched_lanes: `{len(self._as_token_list(mesh_manifest.get('launched_lanes')) if isinstance(mesh_manifest, dict) else [])}`",
                    f"- completed_lanes: `{len(self._as_token_list(mesh_manifest.get('completed_lanes')) if isinstance(mesh_manifest, dict) else [])}`",
                    f"- failed_lanes: `{len(self._as_token_list(mesh_manifest.get('failed_lanes')) if isinstance(mesh_manifest, dict) else [])}`",
                    "",
                ]
            )
        lane_status = execution_plan.get("lane_status")
        if isinstance(lane_status, dict) and lane_status:
            lines.extend(["### Lane Status", ""])
            for lane, payload in lane_status.items():
                if not isinstance(payload, dict):
                    continue
                lines.append(
                    "- "
                    + f"`{lane}`: status=`{str(payload.get('status') or 'unknown').strip()}`"
                    + f", sources=`{int(payload.get('source_count') or 0)}`"
                    + f", trusted_sources=`{int(payload.get('trusted_source_count') or 0)}`"
                    + f", warnings=`{int(payload.get('warning_count') or 0)}`"
                )
            lines.append("")
        lines.extend(
            [
                "## Source Reputation Summary",
                "",
                f"- trusted_primary: `{int(counts.get('trusted_primary', 0))}`",
                f"- trusted_ecosystem: `{int(counts.get('trusted_ecosystem', 0))}`",
                f"- neutral_secondary: `{int(counts.get('neutral_secondary', 0))}`",
                f"- weak_signal: `{int(counts.get('weak_signal', 0))}`",
                f"- quarantined: `{int(counts.get('quarantined', 0))}`",
                f"- trusted_domains: `{len(self._as_token_list(source_reputation.get('trusted_domains')) if isinstance(source_reputation, dict) else [])}`",
                f"- trusted_lanes: `{len(self._as_token_list(source_reputation.get('trusted_lanes')) if isinstance(source_reputation, dict) else [])}`",
                f"- score_mode: `{str(source_reputation.get('score_mode') or 'none').strip()}`",
                f"- average_score: `{float(source_reputation.get('average_score') or 0.0):.2f}`",
                f"- contradiction_count: `{int(source_reputation.get('contradiction_count') or 0)}`",
                "",
            ]
        )
        contradiction_signal = self._as_token_list(execution_plan.get("contradiction_signal"))
        if contradiction_signal:
            lines.extend(["### Contradiction Signal", "", *self._bulletize(contradiction_signal), ""])
        return lines

    def _render_profile_sections(self, *, research_profile: str, structured: dict[str, Any]) -> list[str]:
        if research_profile == "project_audit":
            block = structured.get("project_audit_block") or {}
            return [
                "## North Star",
                "",
                *self._bulletize(block.get("north_star")),
                "",
                "## System Thesis",
                "",
                *self._bulletize(block.get("system_thesis")),
                "",
                "## Platform Layers",
                "",
                *self._bulletize(block.get("platform_layers")),
                "",
                "## Capability Gaps",
                "",
                *self._bulletize(block.get("capability_gaps")),
                "",
                "## Priority Ladder",
                "",
                "### Foundational Now",
                "",
                *self._bulletize((block.get("priority_ladder") or {}).get("foundational_now")),
                "",
                "### System Next",
                "",
                *self._bulletize((block.get("priority_ladder") or {}).get("system_next")),
                "",
                "### Expansion Later",
                "",
                *self._bulletize((block.get("priority_ladder") or {}).get("expansion_later")),
                "",
                "## Observed Runtime Issues",
                "",
                *self._bulletize(block.get("observed_runtime_issues")),
                "",
            ]
        if research_profile == "component_discovery":
            block = structured.get("component_discovery_block") or {}
            return [
                "## Blind Spots",
                "",
                *self._bulletize(block.get("blind_spots")),
                "",
                "## External Leverage",
                "",
                *self._bulletize(block.get("external_leverage")),
                "",
                "## Underbuilt Layers",
                "",
                *self._bulletize(block.get("underbuilt_layers")),
                "",
                "## Priority Ladder",
                "",
                "### Highest Leverage Now",
                "",
                *self._bulletize((block.get("priority_ladder") or {}).get("highest_leverage_now")),
                "",
                "### Major System Next",
                "",
                *self._bulletize((block.get("priority_ladder") or {}).get("major_system_next")),
                "",
                "### Watch and Prepare",
                "",
                *self._bulletize((block.get("priority_ladder") or {}).get("watch_and_prepare")),
                "",
                "## Observed Runtime Issues",
                "",
                *self._bulletize(block.get("observed_runtime_issues")),
                "",
            ]
        return [
            "## Why This Matters",
            "",
            *self._bulletize(structured.get("why_now")),
            "",
            "## Project OS Fit",
            "",
            *self._bulletize(structured.get("repo_fit")),
            "",
            "## Priority Actions",
            "",
            *self._bulletize(structured.get("priority_actions")),
            "",
        ]

    def _render_repo_snapshot(self, *, repo_context: dict[str, Any], dossier_path: Path) -> list[str]:
        lines = [
            "",
            "## Repo Snapshot",
            "",
            f"- active_branch: `{repo_context.get('current_branch') or 'unknown'}`",
            f"- research_profile: `{repo_context.get('research_profile') or 'unknown'}`",
            "- detected_core_packages:",
        ]
        lines.extend([f"  - `{item}`" for item in repo_context.get("core_packages", [])] or ["  - none detected"])
        lines.extend(["- observed_dirty_files:"])
        lines.extend([f"  - `{item}`" for item in repo_context.get("dirty_files", [])[:12]] or ["  - none observed"])
        if repo_context.get("local_refs"):
            lines.extend(["- local_refs_loaded:"])
            for ref in repo_context.get("local_refs", [])[:6]:
                relative = self._relative_link(dossier_path.parent, Path(str(ref["path"])))
                lines.append(f"  - [{ref['relative_path']}]({relative})")
        if repo_context.get("runtime_evidence"):
            lines.extend(["- runtime_evidence:"])
            for item in repo_context.get("runtime_evidence", [])[:6]:
                created_at = str(item.get("created_at") or "").strip()
                event_type = str(item.get("event_type") or "").strip()
                summary = str(item.get("summary") or "").strip()
                lines.append(f"  - `{created_at}` {event_type}: {summary}")
        return lines

    def _render_recommendation_group(self, items: list[dict[str, Any]], *, research_profile: str) -> list[str]:
        if not items:
            return ["- no recommendation kept in this category"]
        lines: list[str] = []
        for item in items:
            system_name = str(item.get("system_name") or "Unnamed System").strip()
            decision = str(item.get("decision") or "ADAPT").strip().upper()
            sequence_role = str(item.get("sequence_role") or "-").strip()
            scope_level = str(item.get("scope_level") or "-").strip()
            lines.extend(
                [
                    f"### {system_name}",
                    "",
                    "Decision:",
                    "",
                    f"- `{decision}`",
                    "",
                    "Sequence Role:",
                    "",
                    f"- `{sequence_role}`",
                    "",
                    "Scope Level:",
                    "",
                    f"- `{scope_level}`",
                    "",
                    "Goal Link:",
                    "",
                    *self._bulletize(item.get("goal_link")),
                    "",
                    "Expected ROI:",
                    "",
                    *self._bulletize(item.get("roi")),
                    "",
                    "Why It Matters:",
                    "",
                    *self._bulletize(item.get("why")),
                    "",
                    "What To Take:",
                    "",
                    *self._bulletize(item.get("what_to_take")),
                    "",
                    "What Not To Import:",
                    "",
                    *self._bulletize(item.get("what_not_to_take")),
                    "",
                    "Fork / Satellite Signal:",
                    "",
                    *self._bulletize(item.get("fork_signal")),
                    "",
                    "Evidence Basis:",
                    "",
                    *self._bulletize(item.get("evidence_basis")),
                    "",
                    "Where It Fits In Project OS:",
                    "",
                    *self._bulletize(item.get("project_os_touchpoints")),
                    "",
                    "Proofs To Obtain:",
                    "",
                    *self._bulletize(item.get("proofs")),
                    "",
                    "Primary Sources:",
                    "",
                ]
            )
            if research_profile == "component_discovery" or str(item.get("blind_spot_addressed") or "").strip():
                lines[-2:-2] = [
                    "Blind Spot Addressed:",
                    "",
                    *self._bulletize(item.get("blind_spot_addressed")),
                    "",
                ]
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
        return rendered or ["- missing source"]

    def _completion_summary(self, *, request: dict[str, Any], structured: dict[str, Any]) -> str:
        research_profile = self._request_research_profile(
            kind=str(request.get("kind") or "audit"),
            question=str(request.get("question") or ""),
            research_profile=structured.get("research_profile") or request.get("research_profile"),
        )
        research_intensity = self._request_research_intensity(
            kind=str(request.get("kind") or "audit"),
            question=str(request.get("question") or ""),
            research_profile=research_profile,
            research_intensity=structured.get("research_intensity") or request.get("research_intensity"),
        )
        recommendations = [item for item in structured.get("recommendations", []) if isinstance(item, dict)]
        counts = {
            "a_faire": sum(1 for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_faire"),
            "a_etudier": sum(1 for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_etudier"),
            "a_rejeter": sum(1 for item in recommendations if str(item.get("bucket") or "").strip().lower() == "a_rejeter"),
        }
        display_title = str(structured.get("seo_title") or request["title"]).strip()
        lines = [
            f"[Project OS] Deep research terminee: {display_title}",
            f"Dossier mis a jour: {request.get('dossier_relative_path') or request.get('doc_name') or request.get('dossier_path')}",
            f"Profile: {research_profile} | Intensite: {research_intensity}",
            f"Buckets: A faire={counts['a_faire']} | A etudier={counts['a_etudier']} | A rejeter={counts['a_rejeter']}",
        ]
        execution_plan = structured.get("execution_plan") or {}
        lane_summary = execution_plan.get("lane_status") if isinstance(execution_plan, dict) else {}
        if isinstance(lane_summary, dict) and lane_summary:
            completed = sum(1 for payload in lane_summary.values() if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "completed")
            degraded = sum(1 for payload in lane_summary.values() if isinstance(payload, dict) and str(payload.get("status") or "").strip().lower() == "degraded")
            lines.append(f"Lanes: completed={completed} | degraded={degraded}")
        if research_profile == "project_audit":
            north_star = str(((structured.get("project_audit_block") or {}).get("north_star")) or "").strip()
            if north_star:
                lines.append(f"Cap nord: {north_star}")
            for item in ((structured.get("project_audit_block") or {}).get("priority_ladder") or {}).get("foundational_now", [])[:3]:
                text = str(item or "").strip()
                if text:
                    lines.append(f"- {text}")
            unlock_line = self._first_goal_link(recommendations)
            if unlock_line:
                lines.append(f"Debloque surtout: {unlock_line}")
        elif research_profile == "component_discovery":
            for item in ((structured.get("component_discovery_block") or {}).get("priority_ladder") or {}).get("highest_leverage_now", [])[:3]:
                text = str(item or "").strip()
                if text:
                    lines.append(f"- {text}")
            top_systems = [str(item.get("system_name") or "").strip() for item in recommendations if str(item.get("system_name") or "").strip()][:2]
            if top_systems:
                lines.append(f"Pepites externes: {', '.join(top_systems)}")
        else:
            for item in structured.get("priority_actions", [])[:3]:
                text = str(item or "").strip()
                if text:
                    lines.append(f"- {text}")
        runtime_lines = self._observed_runtime_issues(structured=structured, research_profile=research_profile)
        if runtime_lines:
            lines.append(f"Incident runtime observe: {runtime_lines[0]}")
        quality_gate = structured.get("quality_gate") or {}
        if str(quality_gate.get("status") or "").strip().lower() == "degraded":
            quality_notes = self._as_token_list(quality_gate.get("notes"))
            if quality_notes:
                lines.append(f"Qualite: run degrade, preuve partielle. {quality_notes[0]}")
        lines.append("Rapport PDF et Markdown joints a ce message.")
        return "\n".join(lines)

    def _first_goal_link(self, recommendations: list[dict[str, Any]]) -> str:
        for item in recommendations:
            goal_links = self._as_token_list(item.get("goal_link"))
            if goal_links:
                return ", ".join(goal_links[:3])
        return ""

    def _observed_runtime_issues(self, *, structured: dict[str, Any], research_profile: str) -> list[str]:
        if research_profile == "project_audit":
            return self._as_token_list((structured.get("project_audit_block") or {}).get("observed_runtime_issues"))
        if research_profile == "component_discovery":
            return self._as_token_list((structured.get("component_discovery_block") or {}).get("observed_runtime_issues"))
        return []

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
                f"Profile: {request.get('research_profile') or 'domain_audit'}",
                f"Intensite: {request.get('research_intensity') or 'simple'}",
                "La recherche web part maintenant, puis le dossier final reviendra ici avec le PDF et le fichier Markdown.",
            ]
        )

    def _archive_bundle(
        self,
        *,
        request: dict[str, Any],
        job_root: Path,
        dossier_path: Path,
        dossier_markdown: str,
        structured: dict[str, Any],
        reader_structured: dict[str, Any],
        repo_context: dict[str, Any],
    ) -> dict[str, Any]:
        canonical_title = str(structured.get("seo_title") or request.get("title") or "Deep Research").strip()
        display_title = str(reader_structured.get("seo_title") or canonical_title).strip()
        kind = str(request.get("kind") or "audit").strip().lower()
        stem = build_archive_stem(title=canonical_title, kind=kind, created_at=str(request.get("created_at") or ""))
        archive_root = self.path_policy.ensure_allowed_write(
            self.paths.archive_reports_root
            / "deep_research"
            / kind
            / stem[:4]
            / stem
        )
        archive_root.mkdir(parents=True, exist_ok=True)
        markdown_path = self.path_policy.ensure_allowed_write(archive_root / f"{stem}.md")
        pdf_path = self.path_policy.ensure_allowed_write(archive_root / f"{stem}.pdf")
        markdown_path.write_text(dossier_markdown, encoding="utf-8")
        render_deep_research_pdf(
            pdf_path,
            display_title=display_title,
            request=request,
            structured=reader_structured,
            repo_context=repo_context,
            dossier_relative_path=str(request.get("dossier_relative_path") or "").strip() or None,
            archive_relative_path=self._archive_relative_path(archive_root),
        )
        for artifact_name in (
            "request.json",
            "repo_context.json",
            "execution_plan.json",
            "mesh_manifest.json",
            "cheap_scout_swarm.json",
            "prompt.md",
            "response.json",
            "result.json",
            "reader_fr.json",
            "status.json",
            "launch.json",
            "usage_summary.json",
            "model_debug.jsonl",
        ):
            source = job_root / artifact_name
            if source.exists():
                shutil.copy2(source, archive_root / artifact_name)
        lane_root = job_root / "lanes"
        if lane_root.exists():
            archive_lane_root = archive_root / "lanes"
            if archive_lane_root.exists():
                shutil.rmtree(archive_lane_root)
            shutil.copytree(lane_root, archive_lane_root)
        manifest = {
            "title": canonical_title,
            "reader_title_fr": display_title,
            "seo_slug": build_seo_slug(canonical_title),
            "kind": kind,
            "research_profile": str(request.get("research_profile") or structured.get("research_profile") or "").strip() or None,
            "research_intensity": str(request.get("research_intensity") or structured.get("research_intensity") or "").strip() or None,
            "recommended_profile": str(request.get("recommended_profile") or structured.get("recommended_profile") or "").strip() or None,
            "recommended_intensity": str(request.get("recommended_intensity") or structured.get("recommended_intensity") or "").strip() or None,
            "question": str(request.get("question") or "").strip(),
            "repo_dossier_path": str(dossier_path),
            "repo_dossier_relative_path": str(request.get("dossier_relative_path") or "").strip() or None,
            "archive_root": str(archive_root),
            "archive_relative_path": self._archive_relative_path(archive_root),
            "markdown_path": str(markdown_path),
            "pdf_path": str(pdf_path),
            "usage_summary_path": str(archive_root / "usage_summary.json") if (archive_root / "usage_summary.json").exists() else None,
            "created_at": str(request.get("created_at") or datetime.now(timezone.utc).isoformat()),
            "model": structured.get("metadata", {}).get("model"),
            "tool_type": structured.get("metadata", {}).get("tool_type"),
            "global_sources": structured.get("global_sources", []),
            "source_trust_summary": structured.get("source_trust_summary", {}),
            "source_reputation_summary": structured.get("source_reputation_summary", {}),
            "execution_plan": structured.get("execution_plan", {}),
            "evidence_manifest": structured.get("evidence_manifest", []),
            "quality_gate": structured.get("quality_gate", {}),
            "canonical_language": "en",
            "reader_language": "fr",
        }
        self._write_managed_json(archive_root / "manifest.json", manifest)
        return {
            "archive_root": str(archive_root),
            "archive_relative_path": manifest["archive_relative_path"],
            "markdown_path": markdown_path,
            "pdf_path": pdf_path,
        }

    def _archive_relative_path(self, destination: Path) -> str:
        try:
            return destination.resolve(strict=False).relative_to(self.paths.archive_root).as_posix()
        except ValueError:
            return destination.resolve(strict=False).as_posix()

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
                "goal_link": {"type": "array", "items": {"type": "string"}},
                "roi": {"type": "array", "items": {"type": "string"}},
                "sequence_role": {
                    "type": "string",
                    "enum": ["foundational_now", "system_next", "expansion_later", "highest_leverage_now", "major_system_next", "watch_and_prepare", "off_path"],
                },
                "scope_level": {
                    "type": "string",
                    "enum": ["platform", "agent_architecture", "execution_surface", "evals", "memory", "ops", "profile", "manager_layer", "surface_profile", "local_hardening"],
                },
                "evidence_basis": {"type": "array", "items": {"type": "string", "enum": ["repo", "web", "runtime", "logs"]}},
                "blind_spot_addressed": {"type": "string"},
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
                "goal_link",
                "roi",
                "sequence_role",
                "scope_level",
                "evidence_basis",
                "why",
                "what_to_take",
                "what_not_to_take",
                "fork_signal",
                "project_os_touchpoints",
                "proofs",
                "sources",
            ],
        }
        project_priority_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "foundational_now": {"type": "array", "items": {"type": "string"}},
                "system_next": {"type": "array", "items": {"type": "string"}},
                "expansion_later": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["foundational_now", "system_next", "expansion_later"],
        }
        component_priority_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "highest_leverage_now": {"type": "array", "items": {"type": "string"}},
                "major_system_next": {"type": "array", "items": {"type": "string"}},
                "watch_and_prepare": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["highest_leverage_now", "major_system_next", "watch_and_prepare"],
        }
        project_block_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "north_star": {"type": "string"},
                "system_thesis": {"type": "array", "items": {"type": "string"}},
                "platform_layers": {"type": "array", "items": {"type": "string"}},
                "capability_gaps": {"type": "array", "items": {"type": "string"}},
                "priority_ladder": project_priority_schema,
                "observed_runtime_issues": {"type": "array", "items": {"type": "string"}},
                "success_metrics": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "north_star",
                "system_thesis",
                "platform_layers",
                "capability_gaps",
                "priority_ladder",
                "observed_runtime_issues",
                "success_metrics",
            ],
        }
        component_block_schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "blind_spots": {"type": "array", "items": {"type": "string"}},
                "external_leverage": {"type": "array", "items": {"type": "string"}},
                "underbuilt_layers": {"type": "array", "items": {"type": "string"}},
                "priority_ladder": component_priority_schema,
                "observed_runtime_issues": {"type": "array", "items": {"type": "string"}},
                "stop_doing_or_deprioritize": {"type": "array", "items": {"type": "string"}},
                "success_metrics": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "blind_spots",
                "external_leverage",
                "underbuilt_layers",
                "priority_ladder",
                "observed_runtime_issues",
                "stop_doing_or_deprioritize",
                "success_metrics",
            ],
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "research_profile": {"type": "string", "enum": ["project_audit", "component_discovery", "domain_audit"]},
                "research_intensity": {"type": "string", "enum": ["simple", "complex", "extreme"]},
                "seo_title": {"type": "string"},
                "summary": {"type": "string"},
                "why_now": {"type": "array", "items": {"type": "string"}},
                "repo_fit": {"type": "array", "items": {"type": "string"}},
                "priority_actions": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": recommendation_schema},
                "risks": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
                "global_sources": {"type": "array", "items": source_schema},
                "project_audit_block": project_block_schema,
                "component_discovery_block": component_block_schema,
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
                "research_profile",
                "research_intensity",
                "seo_title",
                "summary",
                "priority_actions",
                "recommendations",
                "risks",
                "open_questions",
                "global_sources",
                "metadata",
            ],
        }
