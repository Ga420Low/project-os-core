from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.openclaw_gateway_ops import (
    parse_args,
    _build_openclaw_command,
    _build_project_os_command,
    _render_status_summary,
)


class OpenClawGatewayOpsTests(unittest.TestCase):
    def test_parse_args_quickcheck_defaults_to_discord(self):
        args = parse_args(["quickcheck"])

        self.assertEqual(args.command, "quickcheck")
        self.assertEqual(args.channel, "discord")

    def test_build_openclaw_command_adds_token_when_requested(self):
        args = parse_args(["status"])
        args.openclaw_bin = "openclaw.cmd"
        args.gateway_token = "token-123"

        command = _build_openclaw_command(args, "gateway", "status", "--json", include_token=True)

        self.assertEqual(
            command,
            ["openclaw.cmd", "gateway", "status", "--json", "--token", "token-123"],
        )

    def test_build_project_os_command_uses_project_entry(self):
        args = parse_args(["truth-health"])
        args.python_bin = "py"

        command = _build_project_os_command(args, "openclaw", "truth-health", "--channel", "discord")

        self.assertEqual(command[0], "py")
        self.assertIn("project_os_entry.py", command[1])
        self.assertIn("openclaw", command)
        self.assertIn("truth-health", command)

    def test_render_status_summary_highlights_rpc_and_port(self):
        payload = {
            "service": {"loaded": True, "runtime": {"status": "unknown"}},
            "gateway": {"port": 18789, "probeUrl": "ws://127.0.0.1:18789"},
            "port": {"status": "busy", "hints": ["Gateway already running locally."]},
            "rpc": {"ok": True},
        }

        rendered = _render_status_summary(payload)

        self.assertIn("loaded: True", rendered)
        self.assertIn("port: busy (18789)", rendered)
        self.assertIn("rpc_ok: True", rendered)
        self.assertIn("hint: Gateway already running locally.", rendered)


if __name__ == "__main__":
    unittest.main()
