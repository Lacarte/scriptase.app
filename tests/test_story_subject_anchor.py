"""The channel description must anchor the story's subject for themed channels.

Regression: "Code Cosmos — Curiosity" (a code/cosmos channel) generated a script
about round tables vs. square tables. Its niche (`curiosity_facts`) has no topic
bank, so it fell through to the broad `curiosity` category bank — full of generic
everyday-curiosity topics — while the channel's real subject lived only in its
description and was used as a weak "emotional compatibility" note.

The fix: for a niche that owns no topic bank, the description becomes a hard
SUBJECT ANCHOR and the generic topic/concept hints are reframed as angles *within*
that subject. For a niche that already owns a topic bank (dark_psychology, …) the
niche *is* the subject, so the description stays a soft note and nothing changes.

No provider credits are spent — this exercises prompt assembly only.
"""

from __future__ import annotations

import unittest

from scriptase.modules.script.prompts import (
    _build_topic_coverage_block,
    build_story_user_prompt,
)


class SubjectAnchorTests(unittest.TestCase):
    def test_unbanked_niche_anchors_on_description(self):
        block = _build_topic_coverage_block(
            "code_cosmos",
            "curiosity",
            "English",
            niche_preset="code_cosmos_curiosity",
            concept_family="strange design choices in daily life",
        )
        # The channel's real subject is stated as a non-negotiable anchor.
        self.assertIn("SUBJECT ANCHOR", block)
        self.assertIn("programmer's eyes", block)
        # The generic concept is subordinated to the anchor, not the story's core.
        self.assertNotIn("Center the whole story on this fresh concept", block)
        self.assertIn("ANGLE FOR THIS RUN", block)
        # Topic coverage is fenced to the subject rather than adopted literally.
        self.assertIn("only within the subject", block)

    def test_banked_niche_keeps_description_soft(self):
        block = _build_topic_coverage_block(
            "dark_psychology",
            "psychology",
            "English",
            niche_preset="dark_psychology_stickman",
            concept_family="mirroring, charm, and strategic imitation",
        )
        # A niche that owns a topic bank is the subject; its (visual) description
        # stays a soft compatibility note and the concept still drives the run.
        self.assertNotIn("SUBJECT ANCHOR", block)
        self.assertIn("NICHE FIT", block)
        self.assertIn("Center the whole story on this fresh concept", block)

    def test_full_prompt_carries_the_anchor(self):
        prompt = build_story_user_prompt(
            preset_style="code_cosmos",
            story_category="curiosity",
            duration=45,
            language="English",
            niche_preset="code_cosmos_curiosity",
        )
        self.assertIn("SUBJECT ANCHOR", prompt)
        self.assertIn("Cosmic code meets big questions", prompt)


if __name__ == "__main__":
    unittest.main()
