from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from project_os_core.github.validation import validate_issue_resolution_body


def _validate_body(body: str) -> int:
    result = validate_issue_resolution_body(body)
    if result["valid"]:
        print("issue resolution sections complete")
        return 0
    missing = ", ".join(result["missing_sections"])
    print(f"missing required resolution sections: {missing}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate GitHub issue resolution sections.")
    parser.add_argument("--event-path")
    parser.add_argument("--body-file")
    args = parser.parse_args(argv)

    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
        return _validate_body(body)

    if not args.event_path:
        raise SystemExit("either --event-path or --body-file is required")

    event = json.loads(Path(args.event_path).read_text(encoding="utf-8"))
    issue = event.get("issue") or {}
    action = str(event.get("action") or "")
    state = str(issue.get("state") or "")
    if state != "closed" and action != "closed":
        print("issue is not closed; skipping validation")
        return 0
    return _validate_body(str(issue.get("body") or ""))


if __name__ == "__main__":
    raise SystemExit(main())
