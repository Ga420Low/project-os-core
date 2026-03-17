from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    from project_os_core.openclaw_gateway_ops import main as gateway_main

    return gateway_main()


if __name__ == "__main__":
    raise SystemExit(main())
