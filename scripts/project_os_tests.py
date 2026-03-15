from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY = REPO_ROOT / "scripts" / "project_os_entry.py"
CONFIG_PATH = REPO_ROOT / "config" / "storage_roots.local.json"
POLICY_PATH = REPO_ROOT / "config" / "runtime_policy.local.json"


SUITE_COMMANDS = {
    "smoke": [
        (
            "pytest smoke (critical core surfaces)",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_router.py",
                "tests/unit/test_mission_chain.py",
                "tests/unit/test_api_run_service.py",
                "tests/unit/test_api_run_dashboard.py",
                "-q",
                "--maxfail=1",
            ],
        )
    ],
    "gateway": [
        (
            "pytest gateway surfaces",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_router.py",
                "tests/unit/test_openclaw_live.py",
                "tests/unit/test_openclaw_gateway_adapter.py",
                "tests/unit/test_api_run_service.py",
                "-q",
            ],
        )
    ],
    "full": [
        (
            "pytest full (unit + integration)",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit",
                "tests/integration",
                "-q",
            ],
        )
    ],
    "all": [
        (
            "pytest smoke (critical core surfaces)",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_router.py",
                "tests/unit/test_mission_chain.py",
                "tests/unit/test_api_run_service.py",
                "tests/unit/test_api_run_dashboard.py",
                "-q",
                "--maxfail=1",
            ],
        ),
        (
            "pytest gateway surfaces",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_router.py",
                "tests/unit/test_openclaw_live.py",
                "tests/unit/test_openclaw_gateway_adapter.py",
                "tests/unit/test_api_run_service.py",
                "-q",
            ],
        ),
        (
            "pytest full (unit + integration)",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit",
                "tests/integration",
                "-q",
            ],
        ),
    ],
}

SUITE_ESTIMATES = {
    "smoke": "~ 2 min",
    "gateway": "~ 3 min",
    "full": "several minutes",
    "all": "long run",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Canonical local test runner for Project OS. "
            "Use this instead of invoking the PowerShell wrapper directly."
        )
    )
    parser.add_argument(
        "-Suite",
        "--suite",
        choices=sorted(SUITE_COMMANDS),
        default="smoke",
        help="Test suite to execute.",
    )
    parser.add_argument(
        "-WithStrictDoctor",
        "--with-strict-doctor",
        action="store_true",
        help="Run doctor --strict after the requested suite.",
    )
    parser.add_argument(
        "-WithOpenClawDoctor",
        "--with-openclaw-doctor",
        action="store_true",
        help="Run openclaw doctor after the requested suite.",
    )
    parser.add_argument(
        "-WithDocAudit",
        "--with-doc-audit",
        action="store_true",
        help="Run docs audit after the requested suite.",
    )
    return parser.parse_args()


def _run_checked(label: str, command: list[str]) -> None:
    started = time.perf_counter()
    print(f"[Project OS][tests] {label}", flush=True)
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    duration = time.perf_counter() - started
    if completed.returncode != 0:
        raise SystemExit(
            f"{label} failed with exit code {completed.returncode} after {duration:.2f}s."
        )
    print(f"[Project OS][tests] {label} OK in {duration:.2f}s", flush=True)


def main() -> int:
    args = _parse_args()
    estimate = SUITE_ESTIMATES[args.suite]
    print(
        f"[Project OS][tests] suite '{args.suite}' selected "
        f"(expected duration: {estimate})",
        flush=True,
    )

    for label, command in SUITE_COMMANDS[args.suite]:
        _run_checked(label, command)

    if args.with_strict_doctor:
        _run_checked(
            "doctor --strict",
            [
                sys.executable,
                str(ENTRY),
                "--config-path",
                str(CONFIG_PATH),
                "--policy-path",
                str(POLICY_PATH),
                "doctor",
                "--strict",
            ],
        )

    if args.with_openclaw_doctor:
        _run_checked(
            "openclaw doctor",
            [
                sys.executable,
                str(ENTRY),
                "--config-path",
                str(CONFIG_PATH),
                "--policy-path",
                str(POLICY_PATH),
                "openclaw",
                "doctor",
            ],
        )

    if args.with_doc_audit:
        _run_checked(
            "docs audit",
            [sys.executable, str(ENTRY), "docs", "audit"],
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
