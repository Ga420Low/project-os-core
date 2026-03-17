from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.gateway.service import GatewayService


class GatewayClarificationFallbackTests(unittest.TestCase):
    def test_brain_clarification_question_falls_back_when_kind_requires_it(self):
        candidate = SimpleNamespace(
            metadata={
                "brain_resolution_kind": "clarification_needed",
                "brain_clarification_question": "",
            }
        )

        question = GatewayService._brain_clarification_question(candidate)

        self.assertEqual(
            question,
            "Tu parles de ma derniere reponse, ou d'autre chose exactement ?",
        )

    def test_brain_clarification_question_keeps_explicit_question(self):
        candidate = SimpleNamespace(
            metadata={
                "brain_resolution_kind": "clarification_needed",
                "brain_clarification_question": "Tu parles de quel PDF exactement ?",
            }
        )

        question = GatewayService._brain_clarification_question(candidate)

        self.assertEqual(question, "Tu parles de quel PDF exactement ?")


if __name__ == "__main__":
    unittest.main()
