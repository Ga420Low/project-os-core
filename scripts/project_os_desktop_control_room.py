from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _default_config(repo_root: Path) -> tuple[str, str]:
    return (
        str(repo_root / "config" / "storage_roots.local.json"),
        str(repo_root / "config" / "runtime_policy.local.json"),
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from project_os_core.desktop.control_room import DesktopControlRoomService
    from project_os_core.services import build_app_services

    default_config_path, default_policy_path = _default_config(repo_root)
    parser = argparse.ArgumentParser(prog="project-os-desktop-control-room")
    parser.add_argument("--config-path", default=default_config_path)
    parser.add_argument("--policy-path", default=default_policy_path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    startup = subparsers.add_parser("startup-status")
    startup.add_argument("--limit", type=int, default=8)

    runtime_payload = subparsers.add_parser("runtime-payload")
    runtime_payload.add_argument("--limit", type=int, default=8)

    screen_payload = subparsers.add_parser("screen-payload")
    screen_payload.add_argument("--screen", required=True)
    screen_payload.add_argument("--limit", type=int, default=8)

    action = subparsers.add_parser("action")
    action.add_argument("--action", required=True)

    subparsers.add_parser("load-workspace")

    save = subparsers.add_parser("save-workspace")
    save.add_argument("--file")
    save.add_argument("--payload")

    args = parser.parse_args()
    services = build_app_services(config_path=args.config_path, policy_path=args.policy_path)
    try:
        desktop = DesktopControlRoomService(services)
        if args.command == "startup-status":
            print(json.dumps(desktop.build_startup_payload(limit=max(1, int(args.limit))), indent=2, ensure_ascii=True, sort_keys=True))
            return 0
        if args.command == "runtime-payload":
            print(json.dumps(desktop.build_runtime_payload(limit=max(1, int(args.limit))), indent=2, ensure_ascii=True, sort_keys=True))
            return 0
        if args.command == "screen-payload":
            print(
                json.dumps(
                    desktop.build_screen_payload(args.screen, limit=max(1, int(args.limit))),
                    indent=2,
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "action":
            print(json.dumps(desktop.perform_action(args.action), indent=2, ensure_ascii=True, sort_keys=True))
            return 0
        if args.command == "load-workspace":
            print(json.dumps(desktop.load_workspace_state(), indent=2, ensure_ascii=True, sort_keys=True))
            return 0
        if args.command == "save-workspace":
            payload = _read_payload(args)
            print(json.dumps(desktop.save_workspace_state(payload), indent=2, ensure_ascii=True, sort_keys=True))
            return 0
        raise ValueError(f"Unsupported command: {args.command}")
    finally:
        services.close()


def _read_payload(args) -> dict[str, object]:
    if args.payload:
        parsed = json.loads(args.payload)
    elif args.file:
        parsed = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        parsed = json.loads(sys.stdin.read() or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Workspace payload must be a JSON object.")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
