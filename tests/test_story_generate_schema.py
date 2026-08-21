"""StoryGenerateRequest normalization — the Channel-value mismatches that used
to 400 the Script (S1) Auto flow.

A Channel stores its language as an ISO code ("en") and its niche as a niche tag
("dark_psychology"); the story engine speaks full names ("english") and real
story categories ("psychology"). The request schema must reconcile both instead
of rejecting a Channel's own saved values.
"""

from __future__ import annotations

import unittest

from scriptase.modules.script.schemas import StoryGenerateRequest


class LanguageNormalizationTests(unittest.TestCase):
    def test_iso_code_becomes_full_name(self):
        r = StoryGenerateRequest(story_category="psychology", language="en")
        self.assertEqual(r.language, "english")

    def test_other_iso_codes(self):
        self.assertEqual(StoryGenerateRequest(story_category="psychology", language="fr").language, "french")
        self.assertEqual(StoryGenerateRequest(story_category="psychology", language="es").language, "spanish")

    def test_full_names_pass_through(self):
        self.assertEqual(StoryGenerateRequest(story_category="psychology", language="english").language, "english")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(StoryGenerateRequest(story_category="psychology", language="klingon").language, "english")


class CategoryNormalizationTests(unittest.TestCase):
    def test_niche_tag_resolves_to_its_real_category(self):
        # This is the exact value the White Room -- Psychology channel sends.
        r = StoryGenerateRequest(story_category="dark_psychology", niche_preset="dark_psychology")
        self.assertEqual(r.story_category, "psychology")

    def test_valid_category_passes_through(self):
        self.assertEqual(StoryGenerateRequest(story_category="history").story_category, "history")

    def test_unresolvable_category_falls_back(self):
        r = StoryGenerateRequest(story_category="totally_made_up_xyz")
        self.assertEqual(r.story_category, "motivation")


class TheExactFailingPayloadTests(unittest.TestCase):
    def test_white_room_psychology_auto_payload_is_accepted(self):
        # The precise body that returned 400 BAD REQUEST from /api/story/generate.
        r = StoryGenerateRequest(
            niche_preset="dark_psychology",
            preset_style="cinematic",
            story_category="dark_psychology",
            story_tone="suspenseful",
            language="en",
            duration=50,
        )
        self.assertEqual(r.language, "english")
        self.assertEqual(r.story_category, "psychology")
        self.assertEqual(r.preset_style, "cinematic")

    def test_unknown_preset_style_falls_back_not_400(self):
        r = StoryGenerateRequest(story_category="psychology", preset_style="not_a_real_style")
        self.assertEqual(r.preset_style, "cinematic")


if __name__ == "__main__":
    unittest.main()
