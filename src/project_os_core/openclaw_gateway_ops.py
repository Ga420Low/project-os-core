from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "storage_roots.local.json"
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "runtime_policy.local.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Project OS gateway operator helper. "
            "Use this instead of hunting for OpenClaw + Project OS gateway commands."
        )
    )
    parser.add_argument(
        "--openclaw-bin",
        default=resolve_openclaw_bin(),
        help="Path to the OpenClaw CLI. Defaults to openclaw.cmd on Windows when available.",
    )
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python executable used to call project_os_entry.py.",
    )
    parser.add_argument(
        "--config-path",
        default=str(DEFAULT_CONFIG_PATH),
        help="Project OS storage roots config path.",
    )
    parser.add_argument(
        "--policy-path",
        default=str(DEFAULT_POLICY_PATH),
        help="Project OS runtime policy path.",
    )
    parser.add_argument(
        "--gateway-token",
        default=resolve_env_var("OPENCLAW_GATEWAY_TOKEN"),
        help="Gateway token. Defaults to OPENCLAW_GATEWAY_TOKEN from process or Windows user env.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show OpenClaw gateway status.")
    status_parser.add_argument("--json", action="store_true", help="Print raw gateway status JSON.")

    restart_parser = subparsers.add_parser("restart", help="Restart the OpenClaw gateway, then show status.")
    restart_parser.add_argument("--json", action="store_true", help="Print raw gateway status JSON after restart.")

    start_parser = subparsers.add_parser("start", help="Start the OpenClaw gateway, then show status.")
    start_parser.add_argument("--json", action="store_true", help="Print raw gateway status JSON after start.")

    subparsers.add_parser("stop", help="Stop the OpenClaw gateway.")

    doctor_parser = subparsers.add_parser("doctor", help="Run Project OS OpenClaw doctor.")
    doctor_parser.add_argument("--with-system-doctor", action="store_true")

    truth_parser = subparsers.add_parser("truth-health", help="Run Project OS truth-health for a channel.")
    truth_parser.add_argument("--channel", default="discord")
    truth_parser.add_argument("--max-age-hours", type=int)

    validate_parser = subparsers.add_parser("validate-live", help="Run Project OS validate-live for a channel.")
    validate_parser.add_argument("--channel", default="discord")
    validate_parser.add_argument("--payload-file")
    validate_parser.add_argument("--max-age-hours", type=int)

    heal_parser = subparsers.add_parser("self-heal", help="Run Project OS OpenClaw self-heal.")
    heal_parser.add_argument("--ignore-cooldown", action="store_true")

    calibration_parser = subparsers.add_parser(
        "discord-calibration",
        help="Run Project OS Discord calibration summary.",
    )
    calibration_parser.add_argument("--limit", type=int, default=6)
    calibration_parser.add_argument("--log-lines", type=int, default=20)
    calibration_parser.add_argument("--json", action="store_true")

    quickcheck_parser = subparsers.add_parser(
        "quickcheck",
        help="Run gateway status + Project OS truth-health in one shot.",
    )
    quickcheck_parser.add_argument("--channel", default="discord")
    quickcheck_parser.add_argument("--json", action="store_true", help="Print raw gateway status JSON first.")

    return parser.parse_args(argv)


def resolve_openclaw_bin() -> str:
    explicit = os.environ.get("PROJECT_OS_OPENCLAW_BIN", "").strip()
    if explicit:
        return explicit
    candidates = ["openclaw.cmd", "openclaw"] if os.name == "nt" else ["openclaw", "openclaw.cmd"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return candidates[0]


def resolve_env_var(name: str) -> str | None:
    current = os.environ.get(name, "").strip()
    if current:
        return current
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except Exception:
        return None
    return str(value).strip() or None


def _project_os_entry_path() -> Path:
    return REPO_ROOT / "scripts" / "project_os_entry.py"


def _run_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def _ensure_success(result: subprocess.CompletedProcess[str], *, label: str) -> None:
    if result.returncode == 0:
        return
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    details = stderr or stdout or f"exit code {result.returncode}"
    raise SystemExit(f"{label} failed: {details}")


def _build_openclaw_command(args: argparse.Namespace, *extra: str, include_token: bool = False) -> list[str]:
    command = [str(args.openclaw_bin), *extra]
    if include_token and args.gateway_token:
        command.extend(["--token", str(args.gateway_token)])
    return command


def _build_project_os_command(args: argparse.Namespace, *extra: str) -> list[str]:
    return [
        str(args.python_bin),
        str(_project_os_entry_path()),
        "--config-path",
        str(args.config_path),
        "--policy-path",
        str(args.policy_path),
        *extra,
    ]


def _render_status_summary(payload: dict[str, Any]) -> str:
    service = payload.get("service") if isinstance(payload.get("service"), dict) else {}
    gateway = payload.get("gateway") if isinstance(payload.get("gateway"), dict) else {}
    port = payload.get("port") if isinstance(payload.get("port"), dict) else {}
    rpc = payload.get("rpc") if isinstance(payload.get("rpc"), dict) else {}
    hints = port.get("hints") if isinstance(port.get("hints"), list) else []
    lines = [
        "[project-os-gateway-op]",
        f"loaded: {service.get('loaded')}",
        f"runtime_status: {((service.get('runtime') or {}).get('status') if isinstance(service.get('runtime'), dict) else None) or 'unknown'}",
        f"port: {port.get('status') or 'unknown'} ({gateway.get('port') or 'unknown'})",
        f"rpc_ok: {rpc.get('ok')}",
        f"probe_url: {gateway.get('probeUrl') or 'unknown'}",
    ]
    if hints:
        lines.append(f"hint: {hints[0]}")
    if not rpc.get("ok") and rpc.get("error"):
        lines.append(f"rpc_error: {rpc['error']}")
    return "\n".join(lines)


def _load_json_output(result: subprocess.CompletedProcess[str], *, label: str) -> dict[str, Any]:
    _ensure_success(result, label=label)
    payload = (result.stdout or "").strip()
    if not payload:
        raise SystemExit(f"{label} returned no JSON output.")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"{label} returned non-object JSON.")
    return parsed


def run_status(args: argparse.Namespace) -> int:
    result = _run_command(
        _build_openclaw_command(args, "gateway", "status", "--json", include_token=True),
        cwd=REPO_ROOT,
    )
    payload = _load_json_output(result, label="gateway status")
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(_render_status_summary(payload))
    return 0


def _run_and_print(command: list[str], *, cwd: Path, label: str) -> subprocess.CompletedProcess[str]:
    result = _run_command(command, cwd=cwd)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    _ensure_success(result, label=label)
    return result


def run_start_like(args: argparse.Namespace, verb: str) -> int:
    _run_and_print(_build_openclaw_command(args, "gateway", verb), cwd=REPO_ROOT, label=f"gateway {verb}")
    status_args = argparse.Namespace(**vars(args))
    return run_status(status_args)


def run_doctor(args: argparse.Namespace) -> int:
    command = _build_project_os_command(args, "openclaw", "doctor")
    if args.with_system_doctor:
        command.append("--with-system-doctor")
    _run_and_print(command, cwd=REPO_ROOT, label="openclaw doctor")
    return 0


def run_truth_health(args: argparse.Namespace) -> int:
    command = _build_project_os_command(args, "openclaw", "truth-health", "--channel", str(args.channel))
    if args.max_age_hours is not None:
        command.extend(["--max-age-hours", str(int(args.max_age_hours))])
    _run_and_print(command, cwd=REPO_ROOT, label="openclaw truth-health")
    return 0


def run_validate_live(args: argparse.Namespace) -> int:
    command = _build_project_os_command(args, "openclaw", "validate-live", "--channel", str(args.channel))
    if args.payload_file:
        command.extend(["--payload-file", str(args.payload_file)])
    if args.max_age_hours is not None:
        command.extend(["--max-age-hours", str(int(args.max_age_hours))])
    _run_and_print(command, cwd=REPO_ROOT, label="openclaw validate-live")
    return 0


def run_self_heal(args: argparse.Namespace) -> int:
    command = _build_project_os_command(args, "openclaw", "self-heal")
    if args.ignore_cooldown:
        command.append("--ignore-cooldown")
    _run_and_print(command, cwd=REPO_ROOT, label="openclaw self-heal")
    return 0


def run_discord_calibration(args: argparse.Namespace) -> int:
    command = _build_project_os_command(
        args,
        "openclaw",
        "discord-calibration",
        "--limit",
        str(int(args.limit)),
        "--log-lines",
        str(int(args.log_lines)),
    )
    if args.json:
        command.append("--json")
    _run_and_print(command, cwd=REPO_ROOT, label="openclaw discord-calibration")
    return 0


def run_quickcheck(args: argparse.Namespace) -> int:
    status_result = _run_command(
        _build_openclaw_command(args, "gateway", "status", "--json", include_token=True),
        cwd=REPO_ROOT,
    )
    payload = _load_json_output(status_result, label="gateway status")
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(_render_status_summary(payload))
    truth_args = argparse.Namespace(**vars(args), max_age_hours=None)
    return run_truth_health(truth_args)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "status":
        return run_status(args)
    if args.command == "restart":
        return run_start_like(args, "restart")
    if args.command == "start":
        return run_start_like(args, "start")
    if args.command == "stop":
        _run_and_print(_build_openclaw_command(args, "gateway", "stop"), cwd=REPO_ROOT, label="gateway stop")
        return 0
    if args.command == "doctor":
        return run_doctor(args)
    if args.command == "truth-health":
        return run_truth_health(args)
    if args.command == "validate-live":
        return run_validate_live(args)
    if args.command == "self-heal":
        return run_self_heal(args)
    if args.command == "discord-calibration":
        return run_discord_calibration(args)
    if args.command == "quickcheck":
        return run_quickcheck(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
