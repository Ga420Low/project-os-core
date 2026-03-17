from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..services import AppServices


DEFAULT_TERMINAL_ROLE = {
    "role_id": "master_codex",
    "kind": "master_codex",
    "title": "Codex",
    "command": "codex",
    "cwd": None,
    "persistent": True,
}

DEFAULT_WORKSPACE_STATE: dict[str, Any] = {
    "schema_version": "1",
    "last_active_tab": "Home",
    "theme_variant": "hybrid_luxe",
    "motion_mode": "full",
    "last_selected_workspace_root": None,
    "terminal_layout_mode": "anchored_bottom",
    "terminal_dock_preset": "focus",
    "preferred_monitor_mode": "single_screen",
    "selected_run_id": None,
    "selected_thread_key": None,
    "persistent_panels": [deepcopy(DEFAULT_TERMINAL_ROLE)],
    "window": {"width": 1600, "height": 980, "maximized": False},
    "updated_at": None,
}

STATUS_RANK = {"ok": 0, "warning": 1, "error": 2}
ACTION_RANK = {
    "refresh_startup": 0,
    "restart_gateway": 1,
    "open_master_terminal": 2,
    "reset_panel_layout": 3,
}


@dataclass(slots=True)
class DesktopControlRoomService:
    services: AppServices

    @property
    def state_root(self) -> Path:
        return self.services.path_policy.ensure_allowed_write(self.services.paths.runtime_root / "desktop_control_room")

    @property
    def workspace_state_path(self) -> Path:
        return self.state_root / "workspace_state.json"

    @property
    def repo_root(self) -> Path:
        return self.services.config.repo_root

    @property
    def gateway_operator_path(self) -> Path:
        return self.repo_root / "scripts" / "project_os_gateway_op.py"

    def load_workspace_state(self) -> dict[str, Any]:
        self.state_root.mkdir(parents=True, exist_ok=True)
        if not self.workspace_state_path.exists():
            state = self._default_state()
            state["restore_status"] = "default_created"
            return state
        try:
            payload = json.loads(self.workspace_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = self._default_state()
            state["restore_status"] = "corrupt_fallback"
            return state
        state = self._normalize_state(payload if isinstance(payload, dict) else {})
        state["restore_status"] = "restored"
        return state

    def save_workspace_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.state_root.mkdir(parents=True, exist_ok=True)
        state = self._normalize_state(payload)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.workspace_state_path.write_text(
            json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return state

    def build_startup_payload(self, *, limit: int = 8) -> dict[str, Any]:
        return self.build_runtime_payload(limit=limit)

    def perform_action(self, action: str) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()
        created_at = datetime.now(timezone.utc).isoformat()
        if normalized == "refresh_startup":
            return {
                "ok": True,
                "action": normalized,
                "summary": "Self-check relance.",
                "detail": "Le renderer peut recharger le payload startup immediatement.",
                "created_at": created_at,
            }
        if normalized == "restart_gateway":
            result = self._run_gateway_operator("restart")
            return {
                "ok": bool(result.get("ok")),
                "action": normalized,
                "summary": "Gateway relance." if result.get("ok") else "La relance du gateway a echoue.",
                "detail": self._text(result.get("stdout") or result.get("stderr"), "Aucun detail renvoye."),
                "created_at": created_at,
            }
        if normalized in {"reset_panel_layout", "reset_workspace"}:
            current = self.load_workspace_state()
            reset_state = self._default_state()
            for key in ("last_selected_workspace_root", "selected_run_id", "selected_thread_key"):
                reset_state[key] = current.get(key)
            saved = self.save_workspace_state(reset_state)
            saved["restore_status"] = "restored"
            return {
                "ok": True,
                "action": "reset_panel_layout",
                "summary": "Le layout local a ete reinitialise.",
                "detail": f'Workspace sauvegarde avec {len(as_list(saved.get("persistent_panels")))} panel(s) persistant(s).',
                "created_at": created_at,
            }
        raise ValueError(f"Unsupported desktop action: {action}")

    def build_runtime_payload(self, *, limit: int = 8) -> dict[str, Any]:
        workspace_state = self.load_workspace_state()
        session_summary, session_issue = self._load_session_summary()
        monitor_snapshot, monitor_issue = self._load_monitor_snapshot(limit=limit)
        gateway_payload, gateway_runtime_card = self._build_gateway_runtime_check()
        gateway_truth_payload, gateway_truth_card = self._build_gateway_truth_check()
        runtime_paths_card = self._build_runtime_paths_check()
        restore_card = self._build_restore_check(workspace_state)
        dashboard_source_card = self._build_dashboard_source_check(
            session_summary=session_summary,
            session_issue=session_issue,
            monitor_snapshot=monitor_snapshot,
            monitor_issue=monitor_issue,
        )
        core_commands_card, command_state = self._build_core_commands_check()
        master_terminal_card = self._build_master_terminal_check(workspace_state=workspace_state, command_state=command_state)
        startup_cards = [
            gateway_runtime_card,
            gateway_truth_card,
            runtime_paths_card,
            restore_card,
            dashboard_source_card,
            master_terminal_card,
            core_commands_card,
        ]
        startup_status = self._aggregate_status([card.get("status") for card in startup_cards])
        discord_activity = self._build_discord_activity(limit=limit)
        current_run = safe_dict(monitor_snapshot.get("current_run"))
        cost_summary = {
            "daily_spend_estimate_eur": float(monitor_snapshot.get("daily_spend_estimate_eur") or 0.0),
            "monthly_spend_estimate_eur": float(monitor_snapshot.get("monthly_spend_estimate_eur") or 0.0),
            "current_run_estimate_eur": float(current_run.get("estimated_cost_eur") or 0.0),
        }
        codex_usage_status = self._build_codex_usage_status(command_state=command_state)
        conversation_summary = self._build_conversation_summary(limit=limit)
        startup_health = {
            "startup_run_id": datetime.now(timezone.utc).strftime("startup_%Y%m%d%H%M%S"),
            "overall_status": startup_status,
            "status_text": self._status_text(startup_status),
            "gateway_status": gateway_runtime_card.get("status", "unknown"),
            "gateway_truth_status": gateway_truth_card.get("status", "unknown"),
            "runtime_paths_status": runtime_paths_card.get("status", "unknown"),
            "session_restore_status": restore_card.get("status", "unknown"),
            "session_restore_mode": str(workspace_state.get("restore_status") or "restored"),
            "dashboard_source_status": dashboard_source_card.get("status", "unknown"),
            "master_terminal_status": master_terminal_card.get("status", "unknown"),
            "core_commands_status": core_commands_card.get("status", "unknown"),
            "warnings": [card["summary"] for card in startup_cards if card.get("status") != "ok"],
            "cards": startup_cards,
            "actions": self._build_global_actions(
                gateway_runtime_card=gateway_runtime_card,
                gateway_truth_card=gateway_truth_card,
                restore_card=restore_card,
                master_terminal_card=master_terminal_card,
                command_state=command_state,
            ),
            "operator_message": self._startup_operator_message(startup_cards, startup_status),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        recent_runs = as_list(monitor_snapshot.get("latest_runs"))
        cost_lanes = self._build_cost_lane_summary(
            cost_summary=cost_summary,
            codex_usage_status=codex_usage_status,
            startup_health=startup_health,
            recent_runs=recent_runs,
        )
        founder_sidebar = self._build_founder_sidebar_context(
            workspace_state=workspace_state,
            session_summary=session_summary,
            current_run=current_run,
            conversation_summary=conversation_summary,
        )
        home_summary = {
            "gateway": gateway_payload,
            "gateway_truth": gateway_truth_payload,
            "active_runs_count": len(as_list(session_summary.get("active_runs"))),
            "pending_clarifications_count": len(as_list(session_summary.get("pending_clarifications"))),
            "pending_contracts_count": len(as_list(session_summary.get("pending_contracts"))),
            "pending_approvals_count": len(as_list(session_summary.get("pending_approvals"))),
            "daily_spend_eur": float(session_summary.get("daily_spend_eur") or 0.0),
            "current_run_id": current_run.get("run_id"),
            "current_objective": current_run.get("objective"),
        }
        runtime_payload = {
            "schema_version": "1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workspace_state": workspace_state,
            "startup_health": startup_health,
            "home_summary": home_summary,
            "session_summary": session_summary,
            "recent_runs": recent_runs,
            "discord_activity": discord_activity,
            "cost_summary": cost_summary,
            "codex_usage_status": codex_usage_status,
            "conversation_summary": conversation_summary,
            "cost_lanes": cost_lanes,
            "founder_sidebar": founder_sidebar,
        }
        runtime_payload["views"] = self._build_views(
            workspace_state=workspace_state,
            startup_health=startup_health,
            home_summary=home_summary,
            session_summary=session_summary,
            recent_runs=recent_runs,
            discord_activity=discord_activity,
            cost_summary=cost_summary,
            codex_usage_status=codex_usage_status,
            conversation_summary=conversation_summary,
            cost_lanes=cost_lanes,
            founder_sidebar=founder_sidebar,
        )
        runtime_payload["runtime_adapter_status"] = {
            "source_mode": "local_only",
            "llm_calls_required": False,
            "gateway_status": gateway_runtime_card.get("status", "unknown"),
            "screen_payloads": sorted(runtime_payload["views"].keys()),
        }
        runtime_payload["replay_summary"] = {
            "items": [self._run_item(run) for run in recent_runs[: min(limit, 8)]],
            "status": "ready",
            "summary": "Les runs recents exposent des entrees rejouables cote app sans appel modele.",
        }
        return runtime_payload

    def build_screen_payload(self, screen: str, *, limit: int = 8) -> dict[str, Any]:
        payload = self.build_runtime_payload(limit=limit)
        views = payload.get("views", {})
        key = str(screen or "").strip().lower()
        if key not in views:
            raise ValueError(f"Unsupported screen payload: {screen}")
        return {
            "screen": key,
            "generated_at": payload["generated_at"],
            "workspace_state": payload["workspace_state"],
            "payload": views[key],
        }

    def _build_gateway_runtime_check(self) -> tuple[dict[str, Any], dict[str, Any]]:
        result = self._run_gateway_operator("status", "--json")
        if not result.get("ok"):
            summary = self._text(result.get("stderr") or result.get("stdout"), "Le probe gateway n'a rien renvoye.")
            gateway_payload = {
                "verdict": "ERROR",
                "status": "error",
                "summary": f"Le gateway n'est pas lisible localement: {summary}",
                "detail": summary,
                "probe_url": None,
                "rpc_ok": False,
            }
            return gateway_payload, self._check_card(
                check_id="gateway_runtime",
                label="Gateway",
                status="error",
                summary=gateway_payload["summary"],
                detail=summary,
                actions=[self._action("restart_gateway", "Relancer le gateway"), self._action("refresh_startup", "Relancer le self-check")],
            )
        payload = safe_dict(result.get("payload"))
        service = safe_dict(payload.get("service"))
        runtime = safe_dict(service.get("runtime"))
        gateway = safe_dict(payload.get("gateway"))
        port = safe_dict(payload.get("port"))
        rpc = safe_dict(payload.get("rpc"))
        loaded = bool(service.get("loaded"))
        runtime_status = self._text(runtime.get("status"), "unknown")
        port_status = self._text(port.get("status"), "unknown")
        rpc_ok = bool(rpc.get("ok"))
        if loaded and rpc_ok and runtime_status.lower() in {"running", "ready", "ok", "healthy"} and port_status.lower() not in {"error", "blocked", "closed"}:
            status = "ok"
            summary = "Gateway reachable et repond au probe local."
        else:
            status = "warning"
            summary = f"Gateway visible mais non pret: runtime={runtime_status}, rpc={rpc_ok}, port={port_status}."
        detail_bits = [
            f"loaded={loaded}",
            f"runtime={runtime_status}",
            f"port={port_status}",
            f"rpc_ok={rpc_ok}",
        ]
        probe_url = gateway.get("probeUrl")
        if probe_url:
            detail_bits.append(f"probe={probe_url}")
        detail = " | ".join(detail_bits)
        gateway_payload = {
            "verdict": status.upper(),
            "status": status,
            "summary": summary,
            "detail": detail,
            "probe_url": probe_url,
            "rpc_ok": rpc_ok,
        }
        actions = [self._action("refresh_startup", "Relancer le self-check")]
        if status != "ok":
            actions.insert(0, self._action("restart_gateway", "Relancer le gateway"))
        return gateway_payload, self._check_card(
            check_id="gateway_runtime",
            label="Gateway",
            status=status,
            summary=summary,
            detail=detail,
            actions=actions,
        )

    def _build_gateway_truth_check(self) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            truth_health = self.services.openclaw.truth_health(channel="discord", max_age_hours=24)
            status = "ok" if truth_health.verdict == "OK" else "warning"
            gateway_payload = {
                "verdict": truth_health.verdict,
                "status": status,
                "summary": truth_health.summary,
                "evidence_refs": list(truth_health.evidence_refs),
                "actionable_fixes": list(truth_health.actionable_fixes),
            }
            actions = [self._action("refresh_startup", "Relancer le self-check")]
            if status != "ok":
                actions.insert(0, self._action("restart_gateway", "Relancer le gateway"))
            return gateway_payload, self._check_card(
                check_id="gateway_truth",
                label="Discord live proof",
                status=status,
                summary=truth_health.summary,
                detail=" | ".join(list(truth_health.evidence_refs)[:3]) if truth_health.evidence_refs else "Aucune evidence live referencee.",
                actions=actions,
            )
        except Exception as exc:  # pragma: no cover - defensive integration fallback
            summary = self._text(exc, "Le check truth-health a echoue.")
            payload = {"verdict": "ERROR", "status": "error", "summary": summary, "evidence_refs": [], "actionable_fixes": []}
            return (
                payload,
                self._check_card(
                    check_id="gateway_truth",
                    label="Discord live proof",
                    status="error",
                    summary=f"Le check truth-health a echoue: {summary}",
                    detail=summary,
                    actions=[self._action("restart_gateway", "Relancer le gateway"), self._action("refresh_startup", "Relancer le self-check")],
                ),
            )

    def _build_discord_activity(self, *, limit: int) -> dict[str, Any]:
        try:
            snapshot = self.services.openclaw.discord_calibration_snapshot(limit=min(limit, 6), log_lines=8, max_age_hours=24)
        except Exception as exc:  # pragma: no cover - defensive integration fallback
            snapshot = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "error",
                "error": str(exc),
                "recent_events": [],
                "recent_deliveries": [],
            }
        snapshot["recent_event_items"] = [
            self._discord_event_item(item) for item in as_list(snapshot.get("recent_events"))[: min(limit, 6)]
        ]
        snapshot["recent_delivery_items"] = [
            self._discord_delivery_item(item) for item in as_list(snapshot.get("recent_deliveries"))[: min(limit, 6)]
        ]
        return snapshot

    def _load_session_summary(self) -> tuple[dict[str, Any], str | None]:
        try:
            session_snapshot = self.services.session_state.load()
            return (
                {
                    "active_runs": list(getattr(session_snapshot, "active_runs", []) or []),
                    "pending_clarifications": list(getattr(session_snapshot, "pending_clarifications", []) or []),
                    "pending_contracts": list(getattr(session_snapshot, "pending_contracts", []) or []),
                    "pending_approvals": list(getattr(session_snapshot, "pending_approvals", []) or []),
                    "pending_deliveries": int(getattr(session_snapshot, "pending_deliveries", 0) or 0),
                    "active_missions": list(getattr(session_snapshot, "active_missions", []) or []),
                    "last_founder_message_at": getattr(session_snapshot, "last_founder_message_at", None),
                    "daily_spend_eur": float(getattr(session_snapshot, "daily_spend_eur", 0.0) or 0.0),
                },
                None,
            )
        except Exception as exc:  # pragma: no cover - defensive integration fallback
            return (
                {
                    "active_runs": [],
                    "pending_clarifications": [],
                    "pending_contracts": [],
                    "pending_approvals": [],
                    "pending_deliveries": 0,
                    "active_missions": [],
                    "last_founder_message_at": None,
                    "daily_spend_eur": 0.0,
                },
                str(exc),
            )

    def _load_monitor_snapshot(self, *, limit: int) -> tuple[dict[str, Any], str | None]:
        try:
            snapshot = self.services.api_runs.monitor_snapshot(limit=limit)
            return safe_dict(snapshot), None
        except Exception as exc:  # pragma: no cover - defensive integration fallback
            return (
                {
                    "latest_runs": [],
                    "current_run": {},
                    "daily_spend_estimate_eur": 0.0,
                    "monthly_spend_estimate_eur": 0.0,
                },
                str(exc),
            )

    def _build_views(
        self,
        *,
        workspace_state: dict[str, Any],
        startup_health: dict[str, Any],
        home_summary: dict[str, Any],
        session_summary: dict[str, Any],
        recent_runs: list[Any],
        discord_activity: dict[str, Any],
        cost_summary: dict[str, Any],
        codex_usage_status: dict[str, Any],
        conversation_summary: dict[str, Any],
        cost_lanes: dict[str, Any],
        founder_sidebar: dict[str, Any],
    ) -> dict[str, Any]:
        gateway = safe_dict(home_summary.get("gateway"))
        gateway_truth = safe_dict(home_summary.get("gateway_truth"))
        session_items = [self._run_item(item) for item in as_list(session_summary.get("active_runs"))]
        recent_run_items = [self._run_item(item) for item in as_list(recent_runs)]
        pending_clarifications = [self._work_item(item, fallback_kind="clarification") for item in as_list(session_summary.get("pending_clarifications"))]
        pending_contracts = [self._work_item(item, fallback_kind="contract") for item in as_list(session_summary.get("pending_contracts"))]
        pending_approvals = [self._work_item(item, fallback_kind="approval") for item in as_list(session_summary.get("pending_approvals"))]
        active_missions = [self._mission_item(item) for item in as_list(session_summary.get("active_missions"))]
        persistent_panels = [self._panel_item(item) for item in as_list(workspace_state.get("persistent_panels"))]
        startup_cards = [safe_dict(item) for item in as_list(startup_health.get("cards"))]
        startup_checks = [{"label": self._text(card.get("label"), "Check"), "value": self._text(card.get("status"), "unknown")} for card in startup_cards]
        overall_status = self._text(startup_health.get("overall_status"), "warning")
        health_strip = [self._status_strip_item(card) for card in startup_cards[:5]]
        sidebar_highlights = as_list(founder_sidebar.get("highlights"))
        roadmap_items = as_list(founder_sidebar.get("roadmaps"))
        pinned_topics = as_list(conversation_summary.get("pinned_topics"))
        recent_conversations = as_list(conversation_summary.get("home_exchanges"))
        return {
            "home": {
                "operator_question": "Est-ce que Project OS est vivant, clair et pret pour la session ?",
                "headline": "Project OS pret pour reprendre la session"
                if overall_status == "ok"
                else "Project OS en mode degrade lisible",
                "summary": self._text(
                    startup_health.get("operator_message"),
                    "Le control room lit le runtime local, le gateway et le contexte session sans appel modele.",
                ),
                "story": [
                    f"{len(session_items)} run(s) actif(s) visibles dans la session locale.",
                    f"{len(recent_run_items)} run(s) recent(s) disponibles pour suivi ou replay.",
                    self._text(gateway_truth.get("summary"), "Aucune preuve live Discord recente."),
                    self._text(codex_usage_status.get("summary"), "Statut Codex indisponible."),
                ],
                "metrics": [
                    {"id": "gateway", "label": "Gateway", "value": self._status_badge(self._text(gateway.get("status"), "warning")), "detail": self._text(gateway.get("summary"), "Aucun resume")},
                    {"id": "session", "label": "Current Session", "value": str(home_summary.get("active_runs_count", 0)), "detail": "runs actifs"},
                    {"id": "daily_cost", "label": "Daily Cost", "value": eur(cost_summary.get("daily_spend_estimate_eur")), "detail": "source locale"},
                    {"id": "restore", "label": "Restore", "value": self._status_badge(self._text(startup_health.get("session_restore_status"), "warning")), "detail": self._text(startup_health.get("session_restore_mode"), "workspace local")},
                ],
                "startup_checks": startup_checks,
                "health_cards": startup_cards,
                "health_strip": health_strip,
                "cost_strip": as_list(cost_lanes.get("cards")),
                "actions": as_list(startup_health.get("actions")),
                "current_session_items": session_items,
                "recent_run_items": recent_run_items[:6],
                "discord_items": as_list(discord_activity.get("recent_event_items") or discord_activity.get("recent_delivery_items"))[:6],
                "runtime_facts": [
                    {"label": "Workspace root", "value": self._text(workspace_state.get("last_selected_workspace_root"), "non selectionne")},
                    {"label": "Selected run", "value": self._text(workspace_state.get("selected_run_id"), "aucun")},
                    {"label": "Selected thread", "value": self._text(workspace_state.get("selected_thread_key"), "aucun")},
                    {"label": "Founder message", "value": self._text(session_summary.get("last_founder_message_at"), "aucun signal recent")},
                    {"label": "Pending deliveries", "value": str(session_summary.get("pending_deliveries", 0))},
                    {"label": "Window", "value": f'{int(workspace_state.get("window", {}).get("width", 0))} x {int(workspace_state.get("window", {}).get("height", 0))}'},
                ],
                "conversation_items": recent_conversations,
                "conversation_note": self._text(
                    conversation_summary.get("home_note"),
                    "Rappel local des derniers echanges fondateur/agent, sans sync artificielle avec le lane Codex.",
                ),
                "sidebar": {
                    "highlights": sidebar_highlights,
                    "roadmaps": roadmap_items,
                    "pinned_topics": pinned_topics[:6],
                },
            },
            "session": {
                "operator_question": "Qu'est-ce qui attend vraiment le fondateur maintenant ?",
                "summary_cards": [
                    {"label": "Clarifications", "value": str(len(pending_clarifications)), "detail": "points a lever"},
                    {"label": "Contracts", "value": str(len(pending_contracts)), "detail": "cadres a confirmer"},
                    {"label": "Approvals", "value": str(len(pending_approvals)), "detail": "go techniques"},
                    {"label": "Missions", "value": str(len(active_missions)), "detail": "travail en cours"},
                ],
                "clarifications": pending_clarifications,
                "contracts": pending_contracts,
                "approvals": pending_approvals,
                "missions": active_missions,
            },
            "runs": {
                "operator_question": "Quels runs meritent ton attention ou une action ?",
                "items": recent_run_items,
                "summary": f"{len(recent_run_items)} runs recents exposes par le runtime local.",
                "summary_cards": [
                    {"label": "Visible", "value": str(len(recent_run_items)), "detail": "runs dans la vue"},
                    {"label": "Actifs", "value": str(len(session_items)), "detail": "runs encore vivants"},
                    {"label": "Replay", "value": str(len([item for item in recent_run_items if item.get('run_id')])), "detail": "entrees actionnables"},
                ],
            },
            "discord": {
                "operator_question": "Que se passe-t-il sur la surface distante sans ouvrir Discord ?",
                "events": as_list(discord_activity.get("recent_event_items")),
                "deliveries": as_list(discord_activity.get("recent_delivery_items")),
                "gateway": {
                    "status": self._text(safe_dict(discord_activity.get("gateway_status")).get("healthy"), "unknown"),
                    "summary": self._text(safe_dict(discord_activity.get("live_proof")).get("summary"), "Aucune preuve live recente."),
                },
                "summary_cards": [
                    {"label": "Events", "value": str(len(as_list(discord_activity.get("recent_event_items")))), "detail": "messages/reponses recentes"},
                    {"label": "Deliveries", "value": str(len(as_list(discord_activity.get("recent_delivery_items")))), "detail": "sorties operateur"},
                    {"label": "Gateway", "value": self._text(safe_dict(discord_activity.get("gateway_status")).get("healthy"), "unknown"), "detail": "sante live"},
                ],
            },
            "costs": {
                "operator_question": "Qu'est-ce qui coute, et qu'est-ce qui reste juste de la supervision locale ?",
                "today": eur(cost_summary.get("daily_spend_estimate_eur")),
                "month": eur(cost_summary.get("monthly_spend_estimate_eur")),
                "current_run": eur(cost_summary.get("current_run_estimate_eur")),
                "note": "Les montants affiches ici viennent du runtime local. Le lane Codex reste un signal separe, pas un cout API.",
                "lane_cards": as_list(cost_lanes.get("cards")),
                "boundary": [
                    {"label": "UI source", "value": "local state only"},
                    {"label": "Idle cost", "value": "quasi nul"},
                    {"label": "Codex usage", "value": self._text(codex_usage_status.get("summary"), "indisponible")},
                    {"label": "API refresh", "value": "aucun appel modele pour rafraichir"},
                    {"label": "Current lane", "value": "human codex + runtime local + remote activity visible"},
                ],
                "markers": as_list(cost_lanes.get("markers")),
            },
            "terminals": {
                "operator_question": "Ou parle-t-on au lane principal, et quels terminaux secondaires peut-on lancer proprement ?",
                "persistent_panels": persistent_panels,
                "layout_mode": self._text(workspace_state.get("terminal_layout_mode"), "anchored_bottom"),
                "monitor_mode": self._text(workspace_state.get("preferred_monitor_mode"), "single_screen"),
                "master_lane": "Codex embarque dans la zone ancree de l'app.",
                "summary_cards": [
                    {"label": "Persistent", "value": str(len(persistent_panels)), "detail": "panels restaures"},
                    {"label": "Layout", "value": self._text(workspace_state.get("terminal_layout_mode"), "anchored_bottom"), "detail": "placement principal"},
                    {"label": "Monitor", "value": self._text(workspace_state.get("preferred_monitor_mode"), "single_screen"), "detail": "mode d'ecran"},
                ],
            },
            "conversations": {
                "operator_question": "Quels echanges recents et quels gros sujets doivent rester visibles sans fouiller SQLite ?",
                "summary_cards": [
                    {"label": "Recent", "value": str(len(as_list(conversation_summary.get("recent_exchanges")))), "detail": "echanges visibles"},
                    {"label": "7 days", "value": str(len(as_list(conversation_summary.get("weekly_exchanges")))), "detail": "fenetre chaude"},
                    {"label": "Pinned", "value": str(len(pinned_topics)), "detail": "sujets importants"},
                    {"label": "Archive", "value": str(len(as_list(conversation_summary.get("archive_exchanges")))), "detail": "plus anciens"},
                ],
                "note": self._text(
                    conversation_summary.get("note"),
                    "Les echanges restent dans la verite locale; la vue desktop expose juste un rappel lisible.",
                ),
                "recent_exchanges": as_list(conversation_summary.get("recent_exchanges")),
                "weekly_exchanges": as_list(conversation_summary.get("weekly_exchanges")),
                "archive_exchanges": as_list(conversation_summary.get("archive_exchanges")),
                "pinned_topics": pinned_topics,
            },
            "settings": {
                "operator_question": "Quel est l'etat local exact stocke pour la coque desktop ?",
                "workspace_state_json": json.dumps(workspace_state, indent=2, ensure_ascii=True, sort_keys=True),
            },
        }

    def _build_cost_lane_summary(
        self,
        *,
        cost_summary: dict[str, Any],
        codex_usage_status: dict[str, Any],
        startup_health: dict[str, Any],
        recent_runs: list[Any],
    ) -> dict[str, Any]:
        cards = [
            {
                "id": "api_today",
                "label": "API Today",
                "value": eur(cost_summary.get("daily_spend_estimate_eur")),
                "detail": "depense modele visible localement",
            },
            {
                "id": "api_month",
                "label": "API Month",
                "value": eur(cost_summary.get("monthly_spend_estimate_eur")),
                "detail": "projection locale",
            },
            {
                "id": "current_run",
                "label": "Current Run",
                "value": eur(cost_summary.get("current_run_estimate_eur")),
                "detail": "cout estime du run en focus",
            },
            {
                "id": "codex_usage",
                "label": "Codex CLI",
                "value": self._codex_usage_value(codex_usage_status),
                "detail": self._text(codex_usage_status.get("remaining_hint"), self._text(codex_usage_status.get("summary"), "signal indisponible")),
            },
        ]
        recent_api_runs = len([item for item in recent_runs if safe_dict(item).get("run_id") or safe_dict(item).get("run_request_id")])
        markers = [
            {"label": "Human lane", "value": "Codex embarque", "detail": "separe des couts API"},
            {"label": "Refresh UI", "value": "0 model call", "detail": "lecture SQLite + runtime local"},
            {"label": "Replay", "value": "peut couter", "detail": "relance potentiellement un worker/API"},
            {"label": "Remote surface", "value": "Discord visible", "detail": "conversation distante, pas dashboard systeme"},
            {"label": "Recent API runs", "value": str(recent_api_runs), "detail": "lots visibles dans la coque"},
        ]
        note = (
            "L'app desktop reste local-first. Les cartes couts affichent seulement les signaux runtime et "
            "gardent Codex CLI sur une ligne separee."
        )
        return {
            "cards": cards,
            "markers": markers,
            "note": note,
            "overall_status": self._text(startup_health.get("overall_status"), "warning"),
        }

    def _build_founder_sidebar_context(
        self,
        *,
        workspace_state: dict[str, Any],
        session_summary: dict[str, Any],
        current_run: dict[str, Any],
        conversation_summary: dict[str, Any],
    ) -> dict[str, Any]:
        ledgers = as_list(conversation_summary.get("topic_ledgers"))
        latest_pdf = self._latest_pdf_reference(ledgers)
        roadmaps = self._recent_roadmaps(limit=5)
        current_roadmap = roadmaps[0] if roadmaps else {"title": "Aucune roadmap", "detail": "docs/roadmap vide"}
        objective = self._text(
            current_run.get("objective")
            or safe_dict((as_list(session_summary.get("active_missions")) or [{}])[0]).get("objective")
            or safe_dict((as_list(conversation_summary.get("pinned_topics")) or [{}])[0]).get("title"),
            "Aucun objectif courant detecte",
        )
        mode = self._text(
            current_run.get("mode")
            or safe_dict((ledgers or [{}])[0]).get("mode")
            or safe_dict((as_list(conversation_summary.get("pinned_topics")) or [{}])[0]).get("mode"),
            "mode libre",
        )
        highlights = [
            {"label": "Mode", "value": mode, "detail": "session fondateur visible"},
            {"label": "Objective", "value": objective, "detail": "ce qui merite le prochain mouvement"},
            {"label": "Latest PDF", "value": self._text(latest_pdf.get("title"), "aucun PDF"), "detail": self._text(latest_pdf.get("detail"), "pas de PDF canonique recent")},
            {"label": "Roadmap now", "value": self._text(current_roadmap.get("title"), "aucune roadmap"), "detail": self._text(current_roadmap.get("detail"), "aucune modification recente")},
            {"label": "Selected thread", "value": self._text(workspace_state.get("selected_thread_key"), "aucun"), "detail": "focus manuel local"},
        ]
        return {
            "highlights": highlights,
            "roadmaps": roadmaps,
        }

    def _build_conversation_summary(self, *, limit: int) -> dict[str, Any]:
        exchange_rows = self.services.database.fetchall(
            """
            SELECT
                ce.surface,
                ce.channel,
                ce.conversation_key,
                ce.message_json,
                ce.created_at,
                gdr.reply_json,
                tl.active_subject,
                tl.last_authoritative_reply_summary,
                tl.mode
            FROM channel_events AS ce
            LEFT JOIN gateway_dispatch_results AS gdr
              ON gdr.channel_event_id = ce.event_id
            LEFT JOIN thread_ledgers AS tl
              ON tl.surface = ce.surface
             AND tl.channel = ce.channel
             AND tl.conversation_key = ce.conversation_key
            ORDER BY ce.created_at DESC
            LIMIT ?
            """,
            (max(24, min(60, int(limit) * 6)),),
        )
        exchange_items = [self._conversation_exchange_item(row) for row in exchange_rows]
        exchange_items = [item for item in exchange_items if item]
        ledgers_rows = self.services.database.fetchall(
            """
            SELECT
                surface,
                channel,
                conversation_key,
                active_subject,
                last_authoritative_reply_summary,
                last_pdf_artifact_id,
                mode,
                decisions_json,
                questions_json,
                updated_at
            FROM thread_ledgers
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(18, min(40, int(limit) * 4)),),
        )
        topic_ledgers = [self._ledger_topic_item(row) for row in ledgers_rows]
        pinned_topics = self._pick_pinned_topics(topic_ledgers)
        weekly_exchanges = [item for item in exchange_items if item.get("age_days", 99) <= 7]
        archive_exchanges = [item for item in exchange_items if item.get("age_days", 99) > 7]
        return {
            "signal": "canonical_local",
            "home_note": "Les 5-10 derniers echanges sont visibles ici comme rappel; l'archive reste disponible dans l'onglet Conversations.",
            "note": "Les echanges sont lus depuis les evenements canoniques et les thread ledgers. Rien n'est synthetise par le chat UI.",
            "home_exchanges": exchange_items[: min(max(limit, 5), 10)],
            "recent_exchanges": exchange_items[:18],
            "weekly_exchanges": weekly_exchanges[:18],
            "archive_exchanges": archive_exchanges[:18],
            "pinned_topics": pinned_topics[:8],
            "topic_ledgers": topic_ledgers,
        }

    def _conversation_exchange_item(self, row: Any) -> dict[str, Any] | None:
        message_payload = self._json_object(row["message_json"])
        reply_payload = self._json_object(row["reply_json"])
        founder_text = self._truncate(
            self._text(message_payload.get("text") or safe_dict(message_payload.get("message")).get("text"), ""),
            220,
        )
        reply_text = self._truncate(
            self._text(
                reply_payload.get("summary")
                or reply_payload.get("reply_summary")
                or reply_payload.get("text")
                or row["last_authoritative_reply_summary"],
                "",
            ),
            220,
        )
        active_subject = self._truncate(self._text(row["active_subject"], ""), 100)
        if not founder_text and not reply_text and not active_subject:
            return None
        created_at = self._text(row["created_at"], datetime.now(timezone.utc).isoformat())
        age_days = self._age_in_days(created_at)
        age_band = "fresh" if age_days <= 1 else "week" if age_days <= 7 else "archive"
        channel = self._text(row["channel"], "local")
        mode = self._text(row["mode"], "")
        title = active_subject or self._truncate(founder_text or reply_text, 96)
        subtitle_bits = [channel]
        if mode:
            subtitle_bits.append(mode)
        subtitle_bits.append(self._relative_age_label(created_at, age_days))
        return {
            "title": title,
            "subtitle": " | ".join(subtitle_bits),
            "detail": founder_text or "Aucun texte fondateur stocke sur cet echange.",
            "reply": reply_text or "Aucune reponse autoritative capturee.",
            "age_band": age_band,
            "age_days": age_days,
            "badge": "7j+" if age_band == "archive" else "live",
            "conversation_key": row["conversation_key"],
            "mode": mode or None,
        }

    def _ledger_topic_item(self, row: Any) -> dict[str, Any]:
        decisions = as_list(self._json_load(row["decisions_json"], fallback=[]))
        questions = as_list(self._json_load(row["questions_json"], fallback=[]))
        updated_at = self._text(row["updated_at"], datetime.now(timezone.utc).isoformat())
        detail = self._text(row["last_authoritative_reply_summary"], "")
        if not detail and decisions:
            detail = self._truncate(str(decisions[0]), 140)
        if not detail and questions:
            detail = self._truncate(str(questions[0]), 140)
        title = self._text(row["active_subject"], "Sujet sans titre")
        tag = self._topic_tag(
            title=title,
            detail=detail,
            pdf_artifact_id=row["last_pdf_artifact_id"],
            decisions=decisions,
        )
        return {
            "title": self._truncate(title, 100),
            "subtitle": " | ".join(
                [
                    self._text(row["channel"], "surface"),
                    self._text(row["mode"], "mode libre"),
                    self._relative_age_label(updated_at, self._age_in_days(updated_at)),
                ]
            ),
            "detail": self._truncate(detail or "Aucun resume autoritatif recent.", 180),
            "badge": tag,
            "mode": self._text(row["mode"], ""),
            "conversation_key": row["conversation_key"],
            "updated_at": updated_at,
            "last_pdf_artifact_id": row["last_pdf_artifact_id"],
            "pin_score": self._topic_pin_score(
                title=title,
                detail=detail,
                pdf_artifact_id=row["last_pdf_artifact_id"],
                decisions=decisions,
            ),
        }

    def _pick_pinned_topics(self, topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = sorted(
            topics,
            key=lambda item: (
                int(item.get("pin_score") or 0),
                self._text(item.get("updated_at"), ""),
            ),
            reverse=True,
        )
        seen: set[str] = set()
        pinned: list[dict[str, Any]] = []
        for item in ranked:
            key = self._text(item.get("conversation_key"), "")
            if not key or key in seen:
                continue
            seen.add(key)
            if int(item.get("pin_score") or 0) <= 0 and len(pinned) >= 4:
                continue
            pinned.append(item)
            if len(pinned) >= 8:
                break
        return pinned

    def _recent_roadmaps(self, *, limit: int) -> list[dict[str, Any]]:
        roadmap_root = self.repo_root / "docs" / "roadmap"
        if not roadmap_root.exists():
            return []
        files = sorted(
            (item for item in roadmap_root.glob("*.md") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[: max(1, int(limit))]
        items: list[dict[str, Any]] = []
        for path in files:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            items.append(
                {
                    "title": path.stem.replace("_", " "),
                    "subtitle": path.name,
                    "detail": f"maj {self._relative_age_label(modified.isoformat(), self._age_in_days(modified.isoformat()))}",
                    "path": str(path),
                }
            )
        return items

    def _latest_pdf_reference(self, ledgers: list[dict[str, Any]]) -> dict[str, Any]:
        artifact_id = next((self._text(item.get("last_pdf_artifact_id"), "") for item in ledgers if item.get("last_pdf_artifact_id")), "")
        row = None
        if artifact_id:
            row = self.services.database.fetchone(
                """
                SELECT artifact_id, source_locator, cold_path, created_at
                FROM artifact_ledger_entries
                WHERE artifact_id = ?
                LIMIT 1
                """,
                (artifact_id,),
            )
        if row is None:
            row = self.services.database.fetchone(
                """
                SELECT artifact_id, source_locator, cold_path, created_at
                FROM artifact_ledger_entries
                WHERE lower(COALESCE(source_locator, '')) LIKE '%.pdf'
                   OR lower(COALESCE(cold_path, '')) LIKE '%.pdf'
                   OR artifact_kind IN ('report', 'pdf')
                ORDER BY created_at DESC
                LIMIT 1
                """,
            )
        if row is None:
            return {}
        locator = self._text(row["source_locator"] or row["cold_path"], str(row["artifact_id"]))
        title = Path(locator).name if locator else str(row["artifact_id"])
        return {
            "title": title,
            "detail": locator,
        }

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _json_load(value: Any, *, fallback: Any) -> Any:
        if value is None:
            return fallback
        if isinstance(value, (dict, list)):
            return value
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
        return parsed

    def _status_strip_item(self, card: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": card.get("id"),
            "label": self._text(card.get("label"), "Check"),
            "value": self._text(card.get("status_badge"), self._status_badge(self._text(card.get("status"), "warning"))),
            "detail": self._truncate(self._text(card.get("summary"), "Aucun resume"), 92),
            "status": self._text(card.get("status"), "warning"),
        }

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= max(0, int(limit)):
            return text
        return text[: max(0, int(limit)) - 1].rstrip() + "..."

    @staticmethod
    def _age_in_days(value: str) -> int:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return 99
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        return max(0, int(delta.total_seconds() // 86400))

    @staticmethod
    def _relative_age_label(value: str, age_days: int | None = None) -> str:
        normalized_days = age_days if age_days is not None else DesktopControlRoomService._age_in_days(value)
        if normalized_days <= 0:
            return "aujourd'hui"
        if normalized_days == 1:
            return "hier"
        if normalized_days <= 7:
            return f"{normalized_days}j"
        return f"{normalized_days}j archive"

    @staticmethod
    def _topic_tag(*, title: str, detail: str, pdf_artifact_id: Any, decisions: list[Any]) -> str:
        lowered = f"{title} {detail}".lower()
        if pdf_artifact_id:
            return "PDF"
        if any(keyword in lowered for keyword in ("roadmap", "pack", "implementation", "plan")):
            return "PLAN"
        if decisions:
            return "DECISION"
        return "THREAD"

    @staticmethod
    def _topic_pin_score(*, title: str, detail: str, pdf_artifact_id: Any, decisions: list[Any]) -> int:
        lowered = f"{title} {detail}".lower()
        score = 0
        if pdf_artifact_id:
            score += 3
        if decisions:
            score += 2
        if any(keyword in lowered for keyword in ("roadmap", "pack", "implementation", "desktop", "control room", "discord", "openclaw", "incident", "eval")):
            score += 3
        if any(keyword in lowered for keyword in ("objectif", "objective", "pdf", "rapport", "plan")):
            score += 1
        return score

    @staticmethod
    def _codex_usage_value(payload: dict[str, Any]) -> str:
        ratio = payload.get("usage_ratio")
        if isinstance(ratio, (int, float)):
            return f"{round(float(ratio) * 100)}%"
        return "signal"

    def _build_runtime_paths_check(self) -> dict[str, Any]:
        targets = [
            ("Storage config", Path(self.services.config.storage_config_path)),
            ("Runtime policy", Path(self.services.config.runtime_policy_path)),
            ("Runtime root", self.services.paths.runtime_root),
            ("Session root", self.services.paths.session_root),
            ("API runs root", self.services.paths.api_runs_root),
            ("OpenClaw state", self.services.paths.openclaw_state_root),
            ("Desktop state", self.state_root),
        ]
        details: list[str] = []
        failed = False
        for label, path in targets:
            try:
                if label in {"Storage config", "Runtime policy"}:
                    if not path.exists():
                        failed = True
                        details.append(f"{label}: missing ({path})")
                    else:
                        details.append(f"{label}: ok")
                else:
                    path.mkdir(parents=True, exist_ok=True)
                    details.append(f"{label}: ok")
            except OSError as exc:
                failed = True
                details.append(f"{label}: {exc}")
        status = "error" if failed else "ok"
        summary = "Les chemins runtime requis sont lisibles et preparables." if not failed else "Au moins un chemin runtime requis est indisponible."
        return self._check_card(
            check_id="runtime_paths",
            label="Runtime paths",
            status=status,
            summary=summary,
            detail=" | ".join(details[:4]) if details else "Aucun detail",
            actions=[self._action("refresh_startup", "Relancer le self-check")],
        )

    def _build_restore_check(self, workspace_state: dict[str, Any]) -> dict[str, Any]:
        restore_status = self._text(workspace_state.get("restore_status"), "restored")
        if restore_status == "restored":
            status = "ok"
            summary = "Le workspace local a ete restaure."
        elif restore_status == "default_created":
            status = "warning"
            summary = "Aucun workspace precedent detecte; une base propre a ete creee."
        else:
            status = "warning"
            summary = "Le workspace local etait corrompu; l'app a rebascule sur un fallback propre."
        detail = f"mode={restore_status} | panels={len(as_list(workspace_state.get('persistent_panels')))}"
        actions = [self._action("refresh_startup", "Relancer le self-check")]
        if status != "ok":
            actions.append(self._action("reset_panel_layout", "Reset layout"))
        return self._check_card(
            check_id="restore_state",
            label="Restore state",
            status=status,
            summary=summary,
            detail=detail,
            actions=actions,
        )

    def _build_dashboard_source_check(
        self,
        *,
        session_summary: dict[str, Any],
        session_issue: str | None,
        monitor_snapshot: dict[str, Any],
        monitor_issue: str | None,
    ) -> dict[str, Any]:
        issue_bits = [item for item in [session_issue, monitor_issue] if item]
        if not issue_bits:
            status = "ok"
            summary = f"{len(as_list(monitor_snapshot.get('latest_runs')))} run(s) recents lisibles depuis le monitor local."
        elif len(issue_bits) == 1:
            status = "warning"
            summary = "Une source locale de supervision est degradee, mais l'app reste exploitable."
        else:
            status = "error"
            summary = "Les sources locales de supervision sont degradees."
        detail_bits = [
            f"session_runs={len(as_list(session_summary.get('active_runs')))}",
            f"monitor_runs={len(as_list(monitor_snapshot.get('latest_runs')))}",
        ]
        detail_bits.extend(issue_bits[:2])
        return self._check_card(
            check_id="dashboard_source",
            label="Dashboard source",
            status=status,
            summary=summary,
            detail=" | ".join(detail_bits),
            actions=[self._action("refresh_startup", "Relancer le self-check")],
        )

    def _build_core_commands_check(self) -> tuple[dict[str, Any], dict[str, bool]]:
        codex_command = shutil.which("codex")
        git_command = shutil.which("git")
        openclaw_command = shutil.which(str(self.services.config.openclaw_config.binary_command))
        python_available = Path(sys.executable).exists()
        command_state = {
            "python": python_available,
            "git": bool(git_command),
            "codex": bool(codex_command),
            "openclaw": bool(openclaw_command),
        }
        missing = [label for label, ok in [("Python", python_available), ("Git", bool(git_command)), ("Codex", bool(codex_command)), ("OpenClaw", bool(openclaw_command))] if not ok]
        status = "ok" if not missing else "warning"
        summary = "Les commandes coeur sont disponibles." if not missing else f"Certaines commandes coeur manquent: {', '.join(missing)}."
        detail = " | ".join(
            [
                f"python={sys.executable}",
                f"git={'ok' if git_command else 'missing'}",
                f"codex={'ok' if codex_command else 'missing'}",
                f"openclaw={'ok' if openclaw_command else 'missing'}",
            ]
        )
        return (
            self._check_card(
                check_id="core_commands",
                label="Core commands",
                status=status,
                summary=summary,
                detail=detail,
                actions=[self._action("refresh_startup", "Relancer le self-check")],
            ),
            command_state,
        )

    def _build_master_terminal_check(self, *, workspace_state: dict[str, Any], command_state: dict[str, bool]) -> dict[str, Any]:
        persistent_panels = as_list(workspace_state.get("persistent_panels"))
        master_present = any(
            str(item.get("role_id") or item.get("roleId") or item.get("kind") or "").strip().lower() == "master_codex"
            for item in persistent_panels
            if isinstance(item, dict)
        )
        codex_available = bool(command_state.get("codex"))
        if master_present and codex_available:
            status = "ok"
            summary = "Le terminal maitre Codex est configure et la commande locale est resolue."
        elif master_present:
            status = "warning"
            summary = "Le terminal maitre est configure, mais la commande Codex est introuvable."
        else:
            status = "warning"
            summary = "Le terminal maitre n'est plus epingle dans le layout persistant."
        detail = f"master_panel={master_present} | codex_command={codex_available}"
        actions = [self._action("refresh_startup", "Relancer le self-check")]
        if codex_available:
            actions.insert(0, self._action("open_master_terminal", "Rouvrir le terminal maitre"))
        if not master_present:
            actions.append(self._action("reset_panel_layout", "Reset layout"))
        return self._check_card(
            check_id="master_terminal",
            label="Master terminal",
            status=status,
            summary=summary,
            detail=detail,
            actions=actions,
        )

    def _build_codex_usage_status(self, *, command_state: dict[str, bool]) -> dict[str, Any]:
        if not command_state.get("codex"):
            return {
                "status": "warning",
                "summary": "Codex CLI introuvable localement. Le lane maitre restera degrade tant que `codex` n'est pas resolu.",
                "usage_ratio": None,
                "remaining_hint": None,
                "estimated": False,
            }
        return {
            "status": "unavailable",
            "summary": "Aucune source locale canonique des limites Codex CLI n'est encore branchee.",
            "usage_ratio": None,
            "remaining_hint": None,
            "estimated": False,
        }

    def _build_global_actions(
        self,
        *,
        gateway_runtime_card: dict[str, Any],
        gateway_truth_card: dict[str, Any],
        restore_card: dict[str, Any],
        master_terminal_card: dict[str, Any],
        command_state: dict[str, bool],
    ) -> list[dict[str, str]]:
        actions = [self._action("refresh_startup", "Relancer le self-check")]
        if gateway_runtime_card.get("status") != "ok" or gateway_truth_card.get("status") != "ok":
            actions.append(self._action("restart_gateway", "Relancer le gateway"))
        if command_state.get("codex"):
            actions.append(self._action("open_master_terminal", "Rouvrir le terminal maitre"))
        if restore_card.get("status") != "ok" or master_terminal_card.get("status") != "ok":
            actions.append(self._action("reset_panel_layout", "Reset layout"))
        deduped: dict[str, dict[str, str]] = {}
        for item in actions:
            action_id = item.get("action")
            if action_id and action_id not in deduped:
                deduped[action_id] = item
        return sorted(deduped.values(), key=lambda item: ACTION_RANK.get(item.get("action", ""), 100))

    @staticmethod
    def _aggregate_status(statuses: list[Any]) -> str:
        worst = "ok"
        worst_rank = STATUS_RANK[worst]
        for raw in statuses:
            normalized = str(raw or "warning").strip().lower()
            rank = STATUS_RANK.get(normalized, STATUS_RANK["warning"])
            if rank > worst_rank:
                worst = normalized if normalized in STATUS_RANK else "warning"
                worst_rank = rank
        return worst

    @staticmethod
    def _startup_operator_message(cards: list[dict[str, Any]], overall_status: str) -> str:
        if overall_status == "ok":
            return "Le control room est pret. Le runtime local, le gateway et les sources de supervision repondent."
        first_problem = next((card for card in cards if card.get("status") != "ok"), None)
        if first_problem:
            return f"{first_problem.get('label')}: {first_problem.get('summary')}"
        return "Le control room est en mode degrade lisible."

    @staticmethod
    def _status_text(status: str) -> str:
        return {
            "ok": "Pret",
            "warning": "Mode degrade",
            "error": "Attention requise",
        }.get(str(status or "").strip().lower(), "Inconnu")

    @staticmethod
    def _status_badge(status: str) -> str:
        return {
            "ok": "OK",
            "warning": "WATCH",
            "error": "ERROR",
        }.get(str(status or "").strip().lower(), str(status or "UNKNOWN").upper())

    @classmethod
    def _check_card(
        cls,
        *,
        check_id: str,
        label: str,
        status: str,
        summary: str,
        detail: str,
        actions: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        normalized_status = str(status or "warning").strip().lower()
        return {
            "id": check_id,
            "label": label,
            "status": normalized_status if normalized_status in STATUS_RANK else "warning",
            "status_badge": cls._status_badge(normalized_status),
            "summary": summary,
            "detail": detail,
            "actions": actions or [],
        }

    @staticmethod
    def _action(action: str, label: str) -> dict[str, str]:
        return {"action": action, "label": label}

    def _run_gateway_operator(self, command: str, *extra: str) -> dict[str, Any]:
        cmd = [
            sys.executable,
            str(self.gateway_operator_path),
            "--config-path",
            str(self.services.config.storage_config_path),
            "--policy-path",
            str(self.services.config.runtime_policy_path),
            command,
            *extra,
        ]
        timeout_seconds = 15 if command == "status" else 45
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                check=False,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - defensive integration fallback
            return {"ok": False, "stdout": "", "stderr": str(exc), "payload": None}
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        payload = None
        if result.returncode == 0 and "--json" in extra:
            payload = self._extract_json_payload(stdout)
            if payload is None:
                return {"ok": False, "stdout": stdout, "stderr": "Gateway helper returned invalid JSON.", "payload": None}
        return {"ok": result.returncode == 0, "stdout": stdout, "stderr": stderr, "payload": payload}

    @staticmethod
    def _extract_json_payload(text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                parsed = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _default_state() -> dict[str, Any]:
        state = deepcopy(DEFAULT_WORKSPACE_STATE)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        return state

    @staticmethod
    def _text(value: Any, fallback: str) -> str:
        if value is None:
            return fallback
        text = str(value).strip()
        return text or fallback

    def _normalize_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = self._default_state()
        if not isinstance(payload, dict):
            return state
        for key in (
            "last_active_tab",
            "theme_variant",
            "motion_mode",
            "last_selected_workspace_root",
            "terminal_layout_mode",
            "terminal_dock_preset",
            "preferred_monitor_mode",
            "selected_run_id",
            "selected_thread_key",
        ):
            if key in payload:
                value = payload.get(key)
                state[key] = str(value) if value is not None else None
        window_payload = payload.get("window")
        if isinstance(window_payload, dict):
            state["window"] = {
                "width": int(window_payload.get("width") or state["window"]["width"]),
                "height": int(window_payload.get("height") or state["window"]["height"]),
                "maximized": bool(window_payload.get("maximized")),
            }
        panels_payload = payload.get("persistent_panels")
        if isinstance(panels_payload, list) and panels_payload:
            panels: list[dict[str, Any]] = []
            for item in panels_payload:
                if not isinstance(item, dict):
                    continue
                panels.append(
                    {
                        "role_id": str(item.get("role_id") or item.get("kind") or "panel"),
                        "kind": str(item.get("kind") or "special_run"),
                        "title": str(item.get("title") or item.get("kind") or "Panel"),
                        "command": str(item.get("command") or ""),
                        "cwd": str(item.get("cwd")) if item.get("cwd") else None,
                        "persistent": bool(item.get("persistent", True)),
                    }
                )
            if panels:
                state["persistent_panels"] = panels
        return state

    def _run_item(self, item: Any) -> dict[str, Any]:
        record = item if isinstance(item, dict) else {}
        identifier = self._text(record.get("run_id") or record.get("run_request_id"), "run")
        subtitle_bits = [
            self._text(record.get("status"), "unknown"),
            eur(record.get("estimated_cost_eur") or 0.0),
        ]
        if record.get("branch_name"):
            subtitle_bits.append(self._text(record.get("branch_name"), "branch"))
        return {
            "title": identifier,
            "subtitle": " - ".join(subtitle_bits),
            "detail": self._text(record.get("objective") or record.get("mode"), "Aucun objectif"),
            "run_id": record.get("run_id") or record.get("run_request_id"),
            "status": self._text(record.get("status"), "unknown"),
            "badge": "API lane" if record.get("run_id") or record.get("run_request_id") else "Local",
            "cost_hint": "Replay peut relancer un worker/API." if record.get("run_id") or record.get("run_request_id") else "Lecture locale seulement.",
            "actions": [
                {"action": "open_artifact", "enabled": bool(record.get("run_id") or record.get("run_request_id")), "cost_scope": "local"},
                {"action": "view_trace", "enabled": bool(record.get("run_id") or record.get("run_request_id")), "cost_scope": "local"},
                {"action": "replay_run", "enabled": bool(record.get("run_id") or record.get("run_request_id")), "cost_scope": "api_possible"},
            ],
        }

    def _work_item(self, item: Any, *, fallback_kind: str) -> dict[str, Any]:
        record = item if isinstance(item, dict) else {}
        return {
            "title": self._text(record.get("title") or record.get("run_id") or record.get("kind"), fallback_kind),
            "subtitle": self._text(record.get("status"), "En attente"),
            "detail": self._text(record.get("summary") or record.get("question") or record.get("objective"), "Aucun detail"),
        }

    def _mission_item(self, item: Any) -> dict[str, Any]:
        record = item if isinstance(item, dict) else {}
        return {
            "title": self._text(record.get("mission_run_id") or record.get("mission_id"), "mission"),
            "subtitle": self._text(record.get("status"), "Mission active"),
            "detail": self._text(record.get("objective"), "Aucun objectif"),
        }

    def _panel_item(self, item: Any) -> dict[str, Any]:
        record = item if isinstance(item, dict) else {}
        return {
            "title": self._text(record.get("title"), "Panel"),
            "subtitle": self._text(record.get("kind"), "special_run"),
            "detail": self._text(record.get("command"), "command"),
        }

    def _discord_event_item(self, item: Any) -> dict[str, Any]:
        record = item if isinstance(item, dict) else {}
        return {
            "title": self._text(record.get("channel") or record.get("thread_id"), "discord"),
            "subtitle": self._text(record.get("reply_kind") or record.get("event_id"), "event"),
            "detail": self._text(record.get("summary") or record.get("reply_summary") or record.get("text"), "Aucun resume"),
        }

    def _discord_delivery_item(self, item: Any) -> dict[str, Any]:
        record = item if isinstance(item, dict) else {}
        return {
            "title": self._text(record.get("title") or record.get("kind"), "delivery"),
            "subtitle": f'{self._text(record.get("status"), "unknown")} - {self._text(record.get("channel_hint"), "discord")}',
            "detail": self._text(record.get("summary"), "Aucun resume"),
        }


def eur(value: Any) -> str:
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"{amount:.2f} EUR"


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
