from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.local_model import LocalModelClient


class LocalModelClientTests(unittest.TestCase):
    def test_health_reports_ready_when_model_is_available(self):
        client = LocalModelClient(
            enabled=True,
            provider="ollama",
            base_url="http://127.0.0.1:11434",
            model="qwen2.5:14b",
        )
        client._request_json = lambda path, timeout_seconds, body=None: {  # type: ignore[method-assign]
            "models": [{"name": "qwen2.5:14b"}]
        }

        health = client.health(force=True)

        self.assertEqual(health["status"], "ready")
        self.assertEqual(health["reason"], "model_ready")
        self.assertEqual(health["model"], "qwen2.5:14b")

    def test_chat_returns_text_payload(self):
        client = LocalModelClient(
            enabled=True,
            provider="ollama",
            base_url="http://127.0.0.1:11434",
            model="qwen2.5:14b",
        )
        client._request_json = lambda path, timeout_seconds, body=None: {  # type: ignore[method-assign]
            "model": "qwen2.5:14b",
            "message": {"content": "OK_LOCAL"},
        }

        response = client.chat(message="ping", system="system prompt")

        self.assertEqual(response.content, "OK_LOCAL")
        self.assertEqual(response.provider, "ollama")
        self.assertEqual(response.model, "qwen2.5:14b")


if __name__ == "__main__":
    unittest.main()
