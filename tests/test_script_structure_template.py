"""Per-channel structure template: the Channel's beats are the single source.

The template drives the prompt (what labels the LLM writes) and the parser (how
the body is split), while a beat->role mapper keeps the virality scorer — which
reasons about hook/build/climax/cta — working on any structure.
"""

from __future__ import annotations

import unittest

from scriptase.modules.script.engine import (
    DEFAULT_SECTIONS,
    map_beats_to_roles,
    parse_story_sections,
    strip_section_labels,
)
from scriptase.modules.script.prompts import build_story_system_prompt


class DefaultShapeTests(unittest.TestCase):
    def test_default_sections_and_roles_are_identical(self):
        body = "Hook: A.\n\nBuild: B.\n\nClimax: C.\n\nCTA: D."
        p = parse_story_sections(body)
        self.assertEqual(list(p["sections"]), ["hook", "build", "climax", "cta"])
        self.assertEqual(p["sections"], p["roles"])
        self.assertEqual(tuple(p["labels"]), DEFAULT_SECTIONS)


class CustomTemplateTests(unittest.TestCase):
    LABELS = ["Hook", "Turn", "Why", "Reframe", "Landing"]
    BODY = ("Hook: A grab.\n\nTurn: A pivot.\n\nWhy: A reason.\n\n"
            "Reframe: A new lens.\n\nLanding: A close.")

    def test_parser_keys_by_the_custom_labels(self):
        p = parse_story_sections(self.BODY, self.LABELS)
        self.assertEqual(list(p["sections"]), ["hook", "turn", "why", "reframe", "landing"])

    def test_role_mapping_first_is_hook_last_is_cta(self):
        p = parse_story_sections(self.BODY, self.LABELS)
        roles = p["roles"]
        self.assertEqual(roles["hook"], "A grab.")      # first beat
        self.assertEqual(roles["cta"], "A close.")       # last beat
        self.assertEqual(roles["climax"], "A new lens.")  # last middle beat
        self.assertIn("A pivot.", roles["build"])         # earlier middles join into build

    def test_mapper_respects_exact_role_names(self):
        # A beat literally named 'cta' keeps the cta role even if not last.
        sections = {"hook": "h", "cta": "early cta", "outro": "o"}
        roles = map_beats_to_roles(sections, ["Hook", "CTA", "Outro"])
        self.assertEqual(roles["cta"], "early cta")


class PromptTests(unittest.TestCase):
    def test_prompt_uses_the_default_beats_when_none_given(self):
        sp = build_story_system_prompt("cinematic", "psychology", 60, "english")
        self.assertIn("Hook:", sp)
        self.assertIn("Build:", sp)
        self.assertIn("CTA:", sp)

    def test_prompt_uses_the_channel_template_beats(self):
        sp = build_story_system_prompt(
            "cinematic", "philosophy", 60, "english",
            sections=["Hook", "Turn", "Why", "Reframe", "Landing"],
        )
        for beat in ("Hook:", "Turn:", "Why:", "Reframe:", "Landing:"):
            self.assertIn(beat, sp)
        # The default-only beats are not demanded when the template omits them.
        self.assertNotIn("Climax:", sp)


class StripTests(unittest.TestCase):
    def test_strips_custom_template_labels_for_narration(self):
        body = "Hook: A.\n\nTurn: B.\n\nLanding: C."
        clean = strip_section_labels(body, ["Hook", "Turn", "Landing"])
        for label in ("Hook:", "Turn:", "Landing:"):
            self.assertNotIn(label, clean)
        self.assertIn("A.", clean)


if __name__ == "__main__":
    unittest.main()
