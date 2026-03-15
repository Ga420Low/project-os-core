from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from project_os_core.gateway.persona import default_persona_path, load_persona_spec
from project_os_core.models import SensitivityClass


class GatewayPersonaTests(unittest.TestCase):
    def test_persona_yaml_loads_and_exposes_axes(self):
        spec = load_persona_spec()

        self.assertEqual(spec.identity.name, "Project OS")
        self.assertGreaterEqual(len(spec.style_axes), 6)
        axis_keys = {axis.key for axis in spec.style_axes}
        self.assertIn("directness", axis_keys)
        self.assertIn("operator_clarity", axis_keys)
        self.assertTrue(spec.source_path)
        self.assertEqual(spec.source_path, default_persona_path())

    def test_anthropic_renderer_marks_persona_block_cacheable(self):
        spec = load_persona_spec()

        blocks = spec.render_anthropic_system()

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["cache_control"], {"type": "ephemeral"})
        self.assertIn("<persona", str(blocks[0]["text"]))
        self.assertIn("Project OS", str(blocks[0]["text"]))

    def test_local_renderer_applies_sensitivity_overlay(self):
        spec = load_persona_spec()

        s2_prompt = spec.render_local_system(SensitivityClass.S2)
        s3_prompt = spec.render_local_system(SensitivityClass.S3)

        self.assertIn("donnees personnelles ou sensibles", s2_prompt)
        self.assertIn("doit rester local", s3_prompt)
        self.assertIn("Project OS", s3_prompt)
