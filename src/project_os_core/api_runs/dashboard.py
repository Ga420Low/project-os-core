from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_OPERATOR_BEACONS: dict[str, float] = {}
_OPERATOR_BEACON_LOCK = threading.Lock()


def build_dashboard_payload(services, *, limit: int = 8) -> dict[str, Any]:
    snapshot = services.api_runs.monitor_snapshot(limit=limit)
    current_run = snapshot.get("current_run")
    current_contract = snapshot.get("current_contract")
    current_artifacts: list[dict[str, Any]] = []
    current_preview: dict[str, Any] | None = None
    current_completion: dict[str, Any] | None = None
    current_blockage: dict[str, Any] | None = None
    current_clarification: dict[str, Any] | None = None
    terminal_text = services.api_runs.render_terminal_dashboard(limit=limit)
    gateway_reply_audit = _build_gateway_reply_audit(services, limit=limit)

    if current_run and current_run.get("run_id"):
        current_artifacts = services.api_runs.show_artifacts(run_id=str(current_run["run_id"])).get("artifacts", [])
        structured_path = current_run.get("structured_output_path")
        if structured_path:
            current_preview = _load_structured_preview(Path(str(structured_path)))
        completion_path = next((item.get("path") for item in current_artifacts if item.get("artifact_kind") == "rapport_final"), None)
        blockage_path = next((item.get("path") for item in current_artifacts if item.get("artifact_kind") == "blocage"), None)
        clarification_path = next((item.get("path") for item in current_artifacts if item.get("artifact_kind") == "clarification"), None)
        if completion_path:
            current_completion = _load_optional_json(Path(str(completion_path)))
        if blockage_path:
            current_blockage = _load_optional_json(Path(str(blockage_path)))
        if clarification_path:
            current_clarification = _load_optional_json(Path(str(clarification_path)))

    status_counts = dict(snapshot.get("status_counts") or {})
    review_counts = dict(snapshot.get("review_counts") or {})
    operator_delivery_counts = dict(snapshot.get("operator_delivery_counts") or {})
    if not status_counts or not review_counts:
        for item in snapshot.get("latest_runs", []):
            status = str(item.get("status") or "unknown")
            review = str(item.get("review_verdict") or "pending")
            status_counts[status] = status_counts.get(status, 0) + 1
            review_counts[review] = review_counts.get(review, 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": snapshot,
        "terminal_text": terminal_text,
        "current_artifacts": _attach_file_links(current_artifacts),
        "current_preview": current_preview,
        "current_completion": current_completion,
        "current_blockage": current_blockage,
        "current_clarification": current_clarification,
        "status_counts": status_counts,
        "review_counts": review_counts,
        "operator_delivery_counts": operator_delivery_counts,
        "operator_delivery_health": snapshot.get("operator_delivery_health", {}),
        "no_loss_audit": snapshot.get("no_loss_audit", {}),
        "gateway_reply_audit": gateway_reply_audit,
        "lane_policy": {
            "coding_lane": "repo_cli",
            "desktop_lane": "future_computer_use",
            "discord_surface": "mandatory",
            "voice_mode": "future_ready",
            "memory_sync": "selective_sync",
        },
    }


def _build_gateway_reply_audit(services, *, limit: int = 8) -> dict[str, Any]:
    rows = services.database.fetchall(
        """
        SELECT
            ce.created_at,
            ce.channel,
            gdr.reply_json,
            gdr.metadata_json
        FROM gateway_dispatch_results AS gdr
        JOIN channel_events AS ce ON ce.event_id = gdr.channel_event_id
        ORDER BY ce.created_at DESC
        LIMIT ?
        """,
        (max(1, limit),),
    )
    items: list[dict[str, Any]] = []
    mode_counts: dict[str, int] = {}
    reply_kind_counts: dict[str, int] = {}
    manifest_count = 0
    artifact_summary_count = 0
    manifest_gap_count = 0
    for row in rows:
        reply_payload = json.loads(row["reply_json"]) if row["reply_json"] else {}
        reply_metadata = (
            reply_payload.get("metadata")
            if isinstance(reply_payload.get("metadata"), dict)
            else {}
        )
        response_manifest = (
            reply_payload.get("response_manifest")
            if isinstance(reply_payload.get("response_manifest"), dict)
            else {}
        )
        delivery_mode = str(
            response_manifest.get("delivery_mode")
            or reply_metadata.get("response_delivery_mode")
            or "inline_text"
        )
        reply_kind = str(reply_payload.get("reply_kind") or "unknown")
        attachment_count = (
            len(response_manifest.get("attachments") or [])
            if isinstance(response_manifest.get("attachments"), list)
            else 0
        )
        response_manifest_id = str(
            response_manifest.get("metadata", {}).get("manifest_artifact_id")
            if isinstance(response_manifest.get("metadata"), dict)
            else ""
        ).strip() or None
        review_artifact_id = str(response_manifest.get("review_artifact_id") or "").strip() or None
        if response_manifest:
            manifest_count += 1
        if delivery_mode == "artifact_summary":
            artifact_summary_count += 1
            if not response_manifest_id or not review_artifact_id:
                manifest_gap_count += 1
        mode_counts[delivery_mode] = mode_counts.get(delivery_mode, 0) + 1
        reply_kind_counts[reply_kind] = reply_kind_counts.get(reply_kind, 0) + 1
        items.append(
            {
                "created_at": str(row["created_at"]),
                "channel": str(row["channel"] or ""),
                "reply_kind": reply_kind,
                "delivery_mode": delivery_mode,
                "summary": str(reply_payload.get("summary") or ""),
                "manifest_artifact_id": response_manifest_id,
                "review_artifact_id": review_artifact_id,
                "attachment_count": attachment_count,
            }
        )
    status = "breach" if manifest_gap_count > 0 else ("attention" if artifact_summary_count > 0 else "ok")
    return {
        "status": status,
        "reply_kind_counts": reply_kind_counts,
        "delivery_mode_counts": mode_counts,
        "manifest_count": manifest_count,
        "artifact_summary_count": artifact_summary_count,
        "manifest_gap_count": manifest_gap_count,
        "recent_replies": items,
    }


def ensure_dashboard_running(
    *,
    repo_root: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    limit: int = 8,
    refresh_seconds: int = 4,
    open_browser: bool = True,
    require_visible_ui: bool = True,
    wait_seconds: float = 6.0,
    recent_beacon_grace_seconds: int = 1800,
    visibility_state_path: Path | None = None,
) -> dict[str, Any]:
    url = f"http://{host}:{port}/"
    visibility_status = _recent_operator_visibility(
        visibility_state_path,
        max_age_seconds=recent_beacon_grace_seconds,
    )
    if _dashboard_reachable(host, port) and (not require_visible_ui or visibility_status["fresh"]):
        return {
            "url": url,
            "ready": True,
            "ui_visible": True,
            "beacon_token": None,
            "reason": "recent_operator_beacon" if visibility_status["fresh"] else "dashboard_reachable",
            "visibility": visibility_status,
        }

    if not _dashboard_reachable(host, port):
        entry = repo_root / "scripts" / "project_os_entry.py"
        command = [
            sys.executable,
            str(entry),
            "api-runs",
            "dashboard",
            "--host",
            host,
            "--port",
            str(port),
            "--limit",
            str(limit),
            "--refresh-seconds",
            str(refresh_seconds),
        ]
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            cwd=str(repo_root),
            creationflags=creationflags,
        )
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if _dashboard_reachable(host, port):
                break
            time.sleep(0.25)
    visibility_status = _recent_operator_visibility(
        visibility_state_path,
        max_age_seconds=recent_beacon_grace_seconds,
    )
    if _dashboard_reachable(host, port) and (not require_visible_ui or visibility_status["fresh"]):
        return {
            "url": url,
            "ready": True,
            "ui_visible": True,
            "beacon_token": None,
            "reason": "recent_operator_beacon" if visibility_status["fresh"] else "dashboard_reachable",
            "visibility": visibility_status,
        }
    beacon_token = f"focus_{time.time_ns()}"
    focus_url = f"{url}?focus={beacon_token}"
    ui_visible = True
    if require_visible_ui:
        browser_attempts = 2 if open_browser else 1
        attempt_timeout = max(1.0, wait_seconds / max(1, browser_attempts))
        ui_visible = False
        for attempt_index in range(browser_attempts):
            if open_browser:
                _launch_operator_dashboard(focus_url)
            ui_visible = _wait_for_operator_beacon(
                beacon_token,
                timeout_seconds=attempt_timeout,
                state_path=visibility_state_path,
            )
            if ui_visible:
                break
    elif open_browser:
        _launch_operator_dashboard(url)
    visibility_status = _recent_operator_visibility(
        visibility_state_path,
        max_age_seconds=recent_beacon_grace_seconds,
    )
    reachable = _dashboard_reachable(host, port)
    return {
        "url": url,
        "ready": reachable and ui_visible,
        "ui_visible": ui_visible,
        "beacon_token": beacon_token if require_visible_ui else None,
        "reason": "beacon_verified" if reachable and ui_visible else ("browser_beacon_missing" if reachable else "dashboard_unreachable"),
        "visibility": visibility_status,
    }


def _dashboard_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.75):
            return True
    except OSError:
        return False


def _launch_operator_dashboard(url: str) -> None:
    try:
        if sys.platform.startswith("win"):
            launch_attempts = [
                ["cmd", "/c", "start", "", url],
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    f"Start-Process '{url}'",
                ],
            ]
            for command in launch_attempts:
                try:
                    subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                    )
                    return
                except Exception:
                    continue
        webbrowser.open(url, new=1)
    except Exception:
        try:
            webbrowser.open(url, new=1)
        except Exception:
            pass


def _mark_operator_beacon(token: str, *, state_path: Path | None = None) -> None:
    with _OPERATOR_BEACON_LOCK:
        _OPERATOR_BEACONS[token] = time.time()
    _write_visibility_state(state_path, token)


def _wait_for_operator_beacon(token: str, *, timeout_seconds: float, state_path: Path | None = None) -> bool:
    deadline = time.time() + timeout_seconds
    state_max_age_seconds = max(2, int(timeout_seconds) + 2)
    while time.time() < deadline:
        with _OPERATOR_BEACON_LOCK:
            if token in _OPERATOR_BEACONS:
                _OPERATOR_BEACONS.pop(token, None)
                _write_visibility_state(state_path, token)
                return True
        visibility_status = _recent_operator_visibility(
            state_path,
            max_age_seconds=state_max_age_seconds,
        )
        if visibility_status.get("fresh") and visibility_status.get("token") == token:
            return True
        time.sleep(0.1)
    return False


def _recent_operator_visibility(state_path: Path | None, *, max_age_seconds: int) -> dict[str, Any]:
    if state_path is None or not state_path.exists():
        return {"fresh": False, "last_seen_at": None, "token": None, "age_seconds": None}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        last_seen_at = str(payload.get("last_seen_at") or "")
        token = str(payload.get("token") or "")
        if not last_seen_at:
            return {"fresh": False, "last_seen_at": None, "token": token or None, "age_seconds": None}
        seen = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
        age_seconds = max(0.0, (datetime.now(timezone.utc) - seen).total_seconds())
        return {
            "fresh": age_seconds <= max(0, max_age_seconds),
            "last_seen_at": last_seen_at,
            "token": token or None,
            "age_seconds": round(age_seconds, 3),
        }
    except Exception:
        return {"fresh": False, "last_seen_at": None, "token": None, "age_seconds": None}


def _write_visibility_state(state_path: Path | None, token: str) -> None:
    if state_path is None:
        return
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "token": token,
        }
        state_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        return


def render_dashboard_html(payload: dict[str, Any], *, refresh_seconds: int = 4) -> str:
    snapshot = payload["snapshot"]
    budget = snapshot["budget"]
    current_run = snapshot.get("current_run")
    current_contract = snapshot.get("current_contract")
    latest_runs = snapshot.get("latest_runs", [])
    current_artifacts = payload.get("current_artifacts", [])
    current_preview = payload.get("current_preview")
    current_completion = payload.get("current_completion")
    current_blockage = payload.get("current_blockage")
    current_clarification = payload.get("current_clarification")
    terminal_text = str(payload.get("terminal_text") or "").strip()
    operator_delivery_health = payload.get("operator_delivery_health") or {}
    no_loss_audit = payload.get("no_loss_audit") or {}
    gateway_reply_audit = payload.get("gateway_reply_audit") or {}

    def badge(value: str | None, *, kind: str = "status") -> str:
        safe = (value or "pending").lower()
        return f'<span class="badge {kind}-{_html_escape(safe)}">{_html_escape(value or "pending")}</span>'

    def progress(current: float, limit: float) -> float:
        if not limit:
            return 0.0
        return max(0.0, min(100.0, (current / limit) * 100.0))

    current_html = '<div class="empty">Aucun run API enregistre pour le moment.</div>'
    if current_run:
        current_html = f"""
        <div class="head-row">
          {badge(current_run.get("status"))}
          {badge(current_run.get("review_verdict"), kind="review")}
          <span class="pill">mode {_html_escape(str(current_run.get("mode") or ""))}</span>
          <span class="pill">branche {_html_escape(str(current_run.get("branch_name") or ""))}</span>
          <span class="pill">phase {_html_escape(str(current_run.get("phase") or "preparation"))}</span>
          <span class="pill">garde {_html_escape(str(current_run.get("operator_guard_reason") or "unknown"))}</span>
          <span class="pill">signal {_html_escape(str(current_run.get("lifecycle_event_kind") or "n/a"))}</span>
          <span class="pill">livraison {_html_escape(str(current_run.get("operator_delivery_status") or "none"))}</span>
          <span class="pill">no-loss {_html_escape(str(current_run.get("operator_delivery_no_loss_state") or "none"))}</span>
        </div>
        <div class="objective">{_html_escape(str(current_run.get("objective") or ""))}</div>
        <div class="meta-grid">
          <div><strong>ID du run</strong><span class="mono-small">{_html_escape(str(current_run.get("run_id") or ""))}</span></div>
          <div><strong>Cree le</strong><span class="mono-small">{_html_escape(str(current_run.get("created_at") or ""))}</span></div>
          <div><strong>Cout estime</strong><span>{float(current_run.get("estimated_cost_eur") or 0):.4f} EUR</span></div>
          <div><strong>Contrat</strong><span class="mono-small">{_html_escape(str(current_run.get("contract_status") or "sans_contrat"))}</span></div>
          <div><strong>Garde</strong><span class="mono-small">{_html_escape(str(current_run.get("operator_guard_reason") or "unknown"))}</span></div>
          <div><strong>Canal humain</strong><span class="mono-small">{_html_escape(str(current_run.get("operator_channel_hint") or "n/a"))}</span></div>
          <div><strong>Livraison</strong><span class="mono-small">{_html_escape(str(current_run.get("operator_delivery_status") or "none"))}</span></div>
          <div><strong>No-loss</strong><span class="mono-small">{_html_escape(str(current_run.get("operator_delivery_no_loss_state") or "none"))}</span></div>
        </div>
        <div class="meta" style="margin-top:10px;">{_html_escape(str(current_run.get("machine_summary") or "Le dashboard attend un nouvel evenement machine."))}</div>
        {('<div class="meta" style="margin-top:10px;"><strong>Question bloquante:</strong> ' + _html_escape(str(current_run.get("clarification_question") or "")) + '</div>') if current_run.get("status") == "clarification_required" else ''}
        """

    artifact_items = "".join(
        f"<li><strong>{_html_escape(str(item.get('artifact_kind') or 'artifact'))}</strong><br>"
        f"<a href=\"{_html_escape(str(item.get('link') or item.get('path') or ''))}\" target=\"_blank\" rel=\"noreferrer\">"
        f"{_html_escape(str(item.get('path') or 'missing'))}</a></li>"
        for item in current_artifacts
    ) or '<li class="empty">Aucun artefact pour le run en cours.</li>'

    preview_sections: list[str] = []
    if current_preview:
        if current_preview.get("decision"):
            preview_sections.append(f"<li><strong>Decision</strong><br>{_html_escape(str(current_preview['decision']))}</li>")
        if current_preview.get("why"):
            preview_sections.append(f"<li><strong>Pourquoi</strong><br><span class=\"wrap\">{_html_escape(str(current_preview['why']))}</span></li>")
        for title, key in (("Plan du patch", "patch_outline"), ("Tests", "tests"), ("Risques", "risks")):
            values = current_preview.get(key) or []
            if values:
                items = "<br>".join(f"- <span class=\"wrap\">{_html_escape(str(value))}</span>" for value in values)
                preview_sections.append(f"<li><strong>{title}</strong><br>{items}</li>")
    preview_html = "".join(preview_sections) or '<li class="empty">Aucun apercu structure pour le moment.</li>'

    completion_html = '<li class="empty">Aucun rapport final pour le moment.</li>'
    if current_completion:
        done_items = "<br>".join(f"- <span class=\"wrap\">{_html_escape(str(item))}</span>" for item in current_completion.get("done_items", []))
        test_items = "<br>".join(f"- <span class=\"wrap\">{_html_escape(str(item))}</span>" for item in current_completion.get("test_summary", []))
        risk_items = "<br>".join(f"- <span class=\"wrap\">{_html_escape(str(item))}</span>" for item in current_completion.get("risks", []))
        completion_html = f"""
        <li><strong>Verdict</strong><br>{_html_escape(str(current_completion.get('verdict') or ''))}</li>
        <li><strong>Resume</strong><br><span class="wrap">{_html_escape(str(current_completion.get('summary') or ''))}</span></li>
        <li><strong>Ce qui a ete fait</strong><br>{done_items or '<span class="empty">Aucun point.</span>'}</li>
        <li><strong>Tests</strong><br>{test_items or '<span class="empty">Aucun test resume.</span>'}</li>
        <li><strong>Risques</strong><br>{risk_items or '<span class="empty">Aucun risque resume.</span>'}</li>
        <li><strong>Suite recommandee</strong><br><span class="wrap">{_html_escape(str(current_completion.get('next_action') or ''))}</span></li>
        """

    blockage_html = '<li class="empty">Aucun blocage final pour le moment.</li>'
    if current_blockage:
        choice_items = "<br>".join(f"- <span class=\"wrap\">{_html_escape(str(item))}</span>" for item in current_blockage.get("choices", []))
        blockage_html = f"""
        <li><strong>Cause</strong><br><span class="wrap">{_html_escape(str(current_blockage.get('cause') or ''))}</span></li>
        <li><strong>Impact</strong><br><span class="wrap">{_html_escape(str(current_blockage.get('impact') or ''))}</span></li>
        <li><strong>Choix</strong><br>{choice_items or '<span class="empty">Aucun choix propose.</span>'}</li>
        <li><strong>Recommendation</strong><br><span class="wrap">{_html_escape(str(current_blockage.get('recommendation') or ''))}</span></li>
        """

    clarification_html = '<li class="empty">Aucune clarification active pour le moment.</li>'
    if current_clarification:
        clarification_html = f"""
        <li><strong>Cause</strong><br><span class="wrap">{_html_escape(str(current_clarification.get('cause') or ''))}</span></li>
        <li><strong>Impact</strong><br><span class="wrap">{_html_escape(str(current_clarification.get('impact') or ''))}</span></li>
        <li><strong>Question</strong><br><span class="wrap">{_html_escape(str(current_clarification.get('question_for_founder') or ''))}</span></li>
        <li><strong>Contrat recommande</strong><br><span class="wrap">{_html_escape(str(current_clarification.get('recommended_contract_change') or ''))}</span></li>
        <li><strong>Re-go requis</strong><br>{'oui' if current_clarification.get('requires_reapproval') else 'non'}</li>
        """

    history_items = "".join(
        f"""
        <li class="history-card">
          <div class="history-row">
            <strong>{_html_escape(str(item.get('mode') or ''))}</strong>
            {badge(str(item.get('status') or 'pending'))}
            {badge(str(item.get('review_verdict') or 'pending'), kind='review')}
          </div>
          <div class="meta">{_html_escape(str(item.get('created_at') or ''))}</div>
          <div class="meta">garde {_html_escape(str(item.get('operator_guard_reason') or 'unknown'))}</div>
          <div class="meta">branche <span class="mono-small">{_html_escape(str(item.get('branch_name') or ''))}</span> · {float(item.get('estimated_cost_eur') or 0):.4f} EUR</div>
          <div class="history-objective">{_html_escape(str(item.get('objective') or ''))}</div>
        </li>
        """
        for item in latest_runs
    ) or '<li class="empty">Aucun run API pour le moment.</li>'

    status_counts = "<br>".join(
        f"{_html_escape(key)}: {value}" for key, value in sorted(payload.get("status_counts", {}).items())
    ) or "aucun run"
    review_counts = "<br>".join(
        f"{_html_escape(key)}: {value}" for key, value in sorted(payload.get("review_counts", {}).items())
    ) or "aucune revue"
    operator_delivery_counts = "<br>".join(
        f"{_html_escape(key)}: {value}" for key, value in sorted(payload.get("operator_delivery_counts", {}).items())
    ) or "aucune livraison"
    operator_delivery_health_counts = "<br>".join(
        f"{_html_escape(key)}: {value}"
        for key, value in sorted((operator_delivery_health.get("counts") or {}).items())
    ) or "aucun signal"
    gateway_reply_modes = "<br>".join(
        f"{_html_escape(key)}: {value}"
        for key, value in sorted((gateway_reply_audit.get("delivery_mode_counts") or {}).items())
    ) or "aucune reponse"
    gateway_reply_items = "".join(
        f"""
        <li class="history-card">
          <div class="history-row">
            {badge(str(item.get('reply_kind') or 'unknown'))}
            <span class="pill">mode {_html_escape(str(item.get('delivery_mode') or 'inline_text'))}</span>
            <span class="pill">pieces {int(item.get('attachment_count') or 0)}</span>
          </div>
          <div class="meta">{_html_escape(str(item.get('created_at') or ''))} · {_html_escape(str(item.get('channel') or ''))}</div>
          <div class="history-objective">{_html_escape(str(item.get('summary') or ''))}</div>
        </li>
        """
        for item in (gateway_reply_audit.get("recent_replies") or [])
    ) or '<li class="empty">Aucune reponse Discord recente.</li>'
    lane_policy = payload["lane_policy"]

    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{refresh_seconds}">
  <title>Project OS Agent API</title>
  <style>
    :root {{
      color-scheme: dark;
      --panel: rgba(12, 20, 31, 0.95);
      --panel2: rgba(16, 26, 39, 0.97);
      --line: rgba(255,255,255,0.08);
      --text: #eef5ff;
      --muted: #8fa3bc;
      --accent: #62efd3;
      --accent2: #4ba8ff;
      font-family: "Segoe UI", Inter, system-ui, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(75,168,255,0.18), transparent 24%),
        radial-gradient(circle at top right, rgba(98,239,211,0.16), transparent 22%),
        linear-gradient(180deg, #051018, #09141d 55%, #0a1319);
      color: var(--text);
    }}
    .shell {{ max-width: 1440px; margin: 0 auto; padding: 18px; }}
    .hero, .panel, .rail-nav, details.compact {{ background: var(--panel); border: 1px solid var(--line); border-radius: 20px; }}
    .hero {{ display: flex; justify-content: space-between; gap: 14px; padding: 16px 18px; margin-bottom: 14px; }}
    .hero h1 {{ margin: 0 0 6px; font-size: clamp(24px, 3vw, 34px); letter-spacing: -0.04em; }}
    .hero p, .meta, .empty {{ color: var(--muted); }}
    .top-pills, .head-row, .hero-side, .history-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .pill, .badge {{ padding: 8px 12px; border-radius: 999px; border: 1px solid var(--line); font-size: 12px; }}
    .pill {{ background: rgba(255,255,255,0.03); }}
    .badge {{ font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
    .status-running {{ background: rgba(75,168,255,0.18); color: #c6e0ff; }}
    .status-completed, .status-reviewed {{ background: rgba(123,255,158,0.14); color: #d5ffe1; }}
    .status-failed, .status-stopped {{ background: rgba(255,125,154,0.18); color: #ffd5df; }}
    .status-paused {{ background: rgba(255,203,107,0.16); color: #ffe5b8; }}
    .review-accepted {{ background: rgba(123,255,158,0.14); color: #d5ffe1; }}
    .review-accepted_with_reserves, .review-needs_revision {{ background: rgba(255,203,107,0.16); color: #ffe5b8; }}
    .review-needs_clarification {{ background: rgba(255,215,130,0.18); color: #ffe9c5; }}
    .review-rejected {{ background: rgba(255,125,154,0.18); color: #ffd5df; }}
    .review-pending {{ background: rgba(255,255,255,0.04); color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(320px, 0.95fr); gap: 16px; align-items: start; }}
    .stack, .side-rail {{ display: grid; gap: 14px; }}
    .panel header {{ display: flex; justify-content: space-between; gap: 12px; padding: 14px 16px 8px; }}
    .panel h2, .panel h3, details.compact summary {{ margin: 0; }}
    .body {{ padding: 0 16px 16px; }}
    .meta-grid, .budget-grid, .policy-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
    .mini-card, .meta-grid > div, .artifact-list li, .preview-list li, .history-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 11px;
      background: rgba(255,255,255,0.02);
    }}
    .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }}
    .value {{ font-size: 22px; font-weight: 800; letter-spacing: -0.03em; }}
    .progress {{ margin-top: 10px; height: 8px; border-radius: 999px; overflow: hidden; background: rgba(255,255,255,0.06); }}
    .progress span {{ display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); }}
    .objective {{ font-size: 18px; line-height: 1.35; margin: 12px 0; }}
    .meta-grid strong {{ display: block; font-size: 12px; text-transform: uppercase; color: var(--muted); margin-bottom: 4px; }}
    .mono-small {{
      font: 11px/1.55 "Cascadia Code", Consolas, monospace;
      word-break: break-all;
      overflow-wrap: anywhere;
      display: block;
    }}
    .wrap {{
      word-break: break-word;
      overflow-wrap: anywhere;
    }}
    .terminal {{
      margin-top: 12px;
      border: 1px solid rgba(98,239,211,0.18);
      border-radius: 18px;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(4,10,16,0.96), rgba(7,14,23,0.96));
    }}
    .terminal-top {{
      display: flex; justify-content: space-between; align-items: center; gap: 12px;
      padding: 10px 14px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,0.025);
    }}
    .terminal-dots {{ display: flex; gap: 8px; }}
    .terminal-dots span {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
    .terminal-dots span:nth-child(1) {{ background: #ff7d9a; }}
    .terminal-dots span:nth-child(2) {{ background: #ffcb6b; }}
    .terminal-dots span:nth-child(3) {{ background: #7bff9e; }}
    .terminal pre {{
      margin: 0; padding: 14px; font: 12px/1.5 "Cascadia Code", Consolas, monospace;
      color: #dbf7ff; white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow: auto;
    }}
    .side-rail {{ position: sticky; top: 16px; }}
    .rail-nav {{ display: grid; gap: 8px; padding: 12px; background: var(--panel2); }}
    .rail-nav a {{
      display: block; padding: 9px 11px; border-radius: 12px; text-decoration: none; color: var(--text);
      background: rgba(255,255,255,0.02); border: 1px solid var(--line); font-size: 13px;
    }}
    .rail-nav a:hover {{ color: var(--accent); border-color: rgba(98,239,211,0.26); }}
    details.compact {{ overflow: hidden; background: var(--panel2); }}
    details.compact summary {{
      cursor: pointer; list-style: none; padding: 14px 16px; font-weight: 700;
      display: flex; justify-content: space-between; align-items: center; gap: 12px;
    }}
    details.compact summary::-webkit-details-marker {{ display: none; }}
    details.compact[open] summary {{ border-bottom: 1px solid var(--line); }}
    .compact-body {{ padding: 14px 16px 16px; }}
    .artifact-list, .preview-list, .history-list {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
    .artifact-list a {{ color: var(--accent); word-break: break-all; overflow-wrap: anywhere; text-decoration: none; font-size: 12px; }}
    .history-objective {{ margin-top: 8px; color: var(--muted); line-height: 1.45; word-break: break-word; overflow-wrap: anywhere; }}
    .footer {{ margin-top: 16px; text-align: center; color: var(--muted); font-size: 13px; }}
    @media (max-width: 1024px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .hero {{ display: block; }}
      .side-rail {{ position: static; }}
      .terminal pre {{ max-height: 280px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div>
        <div class="top-pills" style="margin-bottom: 10px;">
          <span class="pill">Lead Agent</span>
          <span class="pill">Repo/CLI d'abord</span>
          <span class="pill">Discord obligatoire</span>
          <span class="pill">Voix prete plus tard</span>
        </div>
        <h1>Project OS Agent API</h1>
        <p>Le run en cours est au centre. Les details restent a droite pour limiter le scroll et garder l'activite de l'API lisible d'un coup d'oeil.</p>
      </div>
      <div class="hero-side">
        <span class="pill">actualise {_html_escape(str(payload['generated_at']))}</span>
        <span class="pill">jour {float(budget['daily_spend_estimate_eur']):.4f} / {float(budget['daily_soft_limit_eur']):.2f} EUR</span>
      </div>
    </section>
    <div class="grid">
      <div class="stack">
        <section class="panel">
          <header><h2>Execution en cours</h2><div class="meta">Auto-refresh {refresh_seconds}s</div></header>
          <div class="body">
            {current_html}
            <div class="terminal" id="terminal">
              <div class="terminal-top">
                <div class="terminal-dots"><span></span><span></span><span></span></div>
                <div class="meta">Terminal live</div>
              </div>
              <pre>{_html_escape(terminal_text or "Aucun terminal pour le moment.")}</pre>
            </div>
          </div>
        </section>
      </div>
      <aside class="side-rail">
        <nav class="rail-nav">
          <a href="#budget">Budget</a>
          <a href="#contract">Contrat</a>
          <a href="#preview">Apercu</a>
          <a href="#no-loss">No-loss</a>
          <a href="#completion">Rapport final</a>
          <a href="#clarification">Clarification</a>
          <a href="#blockage">Blocage</a>
          <a href="#artifacts">Artefacts</a>
          <a href="#history">Historique</a>
          <a href="#policy">Regles</a>
          <a href="#terminal">Terminal</a>
        </nav>
        <details class="compact" id="budget" open>
          <summary>Budget et sante <span class="meta">couts et verdicts</span></summary>
          <div class="compact-body">
            <div class="budget-grid">
              <div class="mini-card">
                <div class="label">Depense du jour</div>
                <div class="value">{float(budget['daily_spend_estimate_eur']):.4f} EUR</div>
                <div class="progress"><span style="width:{progress(float(budget['daily_spend_estimate_eur']), float(budget['daily_soft_limit_eur'])):.2f}%"></span></div>
                <div class="meta">seuil souple {float(budget['daily_soft_limit_eur']):.2f} EUR</div>
              </div>
              <div class="mini-card">
                <div class="label">Depense du mois</div>
                <div class="value">{float(budget['monthly_spend_estimate_eur']):.4f} EUR</div>
                <div class="progress"><span style="width:{progress(float(budget['monthly_spend_estimate_eur']), float(budget['monthly_limit_eur'])):.2f}%"></span></div>
                <div class="meta">limite {float(budget['monthly_limit_eur']):.2f} EUR</div>
              </div>
              <div class="mini-card"><div class="label">Statuts</div><div class="meta">{status_counts}</div></div>
              <div class="mini-card"><div class="label">Verdicts</div><div class="meta">{review_counts}</div></div>
              <div class="mini-card"><div class="label">Livraisons</div><div class="meta">{operator_delivery_counts}</div></div>
              <div class="mini-card"><div class="label">Sante delivery</div><div class="meta">{operator_delivery_health_counts}</div></div>
            </div>
          </div>
        </details>
        <details class="compact" id="contract" open>
          <summary>Contrat de run <span class="meta">but, go, limites</span></summary>
          <div class="compact-body">
            {('<div class="mini-card"><div class="label">Contrat courant</div><div class="wrap"><strong>' + _html_escape(str(current_contract.get("status") or "")) + '</strong><br>' + _html_escape(str(current_contract.get("summary") or "")) + '<br><span class="meta">decision fondateur: ' + _html_escape(str(current_contract.get("founder_decision") or "en_attente")) + '</span></div></div>') if current_contract else '<div class="empty">Aucun contrat recent.</div>'}
          </div>
        </details>
        <details class="compact" id="preview" open>
          <summary>Apercu structure <span class="meta">decision, tests, risques</span></summary>
          <div class="compact-body"><ul class="preview-list">{preview_html}</ul></div>
        </details>
        <details class="compact" id="no-loss" open>
          <summary>No-loss et UX Discord <span class="meta">publication, artefacts, replays</span></summary>
          <div class="compact-body">
            <div class="policy-grid" style="margin-bottom: 12px;">
              <div class="mini-card"><div class="label">Audit no-loss</div><div class="value">{_html_escape(str(no_loss_audit.get('status') or 'unknown'))}</div><div class="meta">silent risks {int(no_loss_audit.get('silent_loss_risk_count') or 0)}</div></div>
              <div class="mini-card"><div class="label">Dead letters</div><div class="value">{int(no_loss_audit.get('dead_letter_count') or 0)}</div><div class="meta">replayables {int(no_loss_audit.get('replayable_count') or 0)}</div></div>
              <div class="mini-card"><div class="label">Artifacts Discord</div><div class="value">{int(gateway_reply_audit.get('artifact_summary_count') or 0)}</div><div class="meta">manifest gaps {int(gateway_reply_audit.get('manifest_gap_count') or 0)}</div></div>
              <div class="mini-card"><div class="label">Modes de reponse</div><div class="meta">{gateway_reply_modes}</div></div>
            </div>
            <ul class="history-list">{gateway_reply_items}</ul>
          </div>
        </details>
        <details class="compact" id="completion">
          <summary>Rapport final <span class="meta">francais simple</span></summary>
          <div class="compact-body"><ul class="preview-list">{completion_html}</ul></div>
        </details>
        <details class="compact" id="clarification">
          <summary>Clarification <span class="meta">question et re-go</span></summary>
          <div class="compact-body"><ul class="preview-list">{clarification_html}</ul></div>
        </details>
        <details class="compact" id="blockage">
          <summary>Blocage <span class="meta">si le run a casse</span></summary>
          <div class="compact-body"><ul class="preview-list">{blockage_html}</ul></div>
        </details>
        <details class="compact" id="artifacts">
          <summary>Artefacts <span class="meta">sorties du run courant</span></summary>
          <div class="compact-body"><ul class="artifact-list">{artifact_items}</ul></div>
        </details>
        <details class="compact" id="history">
          <summary>Runs recents <span class="meta">historique compact</span></summary>
          <div class="compact-body"><ul class="history-list">{history_items}</ul></div>
        </details>
        <details class="compact" id="policy">
          <summary>Regles du run <span class="meta">posture d'execution</span></summary>
          <div class="compact-body">
            <div class="policy-grid">
              <div class="mini-card"><div class="label">Lane code</div><div class="value">{_html_escape(str(lane_policy['coding_lane']))}</div></div>
              <div class="mini-card"><div class="label">Lane desktop</div><div class="value">{_html_escape(str(lane_policy['desktop_lane']))}</div></div>
              <div class="mini-card"><div class="label">Discord</div><div class="value">{_html_escape(str(lane_policy['discord_surface']))}</div></div>
              <div class="mini-card"><div class="label">Voix</div><div class="value">{_html_escape(str(lane_policy['voice_mode']))}</div></div>
              <div class="mini-card"><div class="label">Sync memoire</div><div class="value">{_html_escape(str(lane_policy['memory_sync']))}</div></div>
            </div>
          </div>
        </details>
      </aside>
    </div>
    <div class="footer">Le runtime Project OS et le repo restent la source de verite.</div>
  </div>
  <script>
    (function () {{
      try {{
        const params = new URLSearchParams(window.location.search);
        const focus = params.get("focus");
        if (focus) {{
          fetch("/api/operator-beacon?token=" + encodeURIComponent(focus), {{
            method: "GET",
            cache: "no-store",
          }}).catch(() => null);
        }}
      }} catch (_err) {{
        // ignore beacon errors, UI still renders
      }}
    }})();
  </script>
</body>
</html>"""


def serve_dashboard(
    services,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    limit: int = 8,
    refresh_seconds: int = 4,
    open_browser: bool = False,
    visibility_state_path: Path | None = None,
) -> int:
    handler = _make_handler(
        services=services,
        limit=limit,
        refresh_seconds=refresh_seconds,
        visibility_state_path=visibility_state_path,
    )
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"Project OS API dashboard running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _make_handler(*, services, limit: int, refresh_seconds: int, visibility_state_path: Path | None):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    payload = build_dashboard_payload(services, limit=limit)
                    self._send_html(render_dashboard_html(payload, refresh_seconds=refresh_seconds))
                    return
                if parsed.path == "/api/snapshot":
                    requested_limit = _int_query_value(parsed.query, "limit", default=limit)
                    self._send_json(build_dashboard_payload(services, limit=requested_limit))
                    return
                if parsed.path == "/api/artifacts":
                    run_id = parse_qs(parsed.query).get("run_id", [""])[0]
                    if not run_id:
                        self._send_json({"error": "run_id is required"}, status=400)
                        return
                    payload = services.api_runs.show_artifacts(run_id=run_id)
                    self._send_json(_attach_file_links(payload))
                    return
                if parsed.path == "/api/operator-beacon":
                    token = parse_qs(parsed.query).get("token", [""])[0]
                    if not token:
                        self._send_json({"error": "token is required"}, status=400)
                        return
                    _mark_operator_beacon(token, state_path=visibility_state_path)
                    self._send_json({"ok": True, "token": token})
                    return
                self._send_json({"error": "not_found"}, status=404)
            except Exception as exc:  # pragma: no cover
                services.logger.log(
                    "ERROR",
                    "api_run_dashboard_http_error",
                    path=parsed.path,
                    error=str(exc),
                )
                self._send_json({"error": "dashboard_error", "message": "internal server error"}, status=500)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: Any, *, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def _attach_file_links(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_attach_file_links(item) for item in payload]
    if isinstance(payload, dict):
        enriched = {key: _attach_file_links(value) for key, value in payload.items()}
        path_value = enriched.get("path")
        if isinstance(path_value, str) and path_value:
            try:
                enriched["link"] = Path(path_value).resolve(strict=False).as_uri()
            except ValueError:
                enriched["link"] = path_value
        return enriched
    return payload


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_structured_preview(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    return {
        "decision": payload.get("decision"),
        "why": payload.get("why"),
        "patch_outline": payload.get("patch_outline") or [],
        "tests": payload.get("tests") or [],
        "risks": payload.get("risks") or [],
    }


def _int_query_value(query: str, key: str, *, default: int) -> int:
    value = parse_qs(query).get(key, [default])[0]
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
