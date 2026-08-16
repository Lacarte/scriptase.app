"""Step 16.1 — Deterministic scoring module.

Done when: a known-strong and a known-weak script produce clearly separated
scores with per-dimension reasons, and identical input always scores
identically.
"""

from __future__ import annotations

import unittest

from scriptase.modules.script.prompts import WORDS_PER_SECOND, _ANGLE_STARTERS
from scriptase.modules.viral import (
    DIMENSION_IDS,
    DIMENSION_WEIGHTS,
    SCORER_ID,
    ViralScore,
    band_for,
    score_script,
    score_story_payload,
)
from scriptase.modules.viral.archetypes import ARCHETYPES, match_archetypes
from scriptase.modules.viral.scoring import SECTION_KEYS, build_doc, split_sentences

# A script that does everything the writer was told to do: archetype-led hook,
# open loops through the middle, a one-line CTA, and 125 words for 50 seconds.
STRONG_SECTIONS = {
    "hook": (
        "A 2019 study found that most people don't know their first ten minutes "
        "awake decide the whole day. But here's the thing."
    ),
    "build": (
        "You wake up, and your brain is still running on the last thing it touched. "
        "Reach for your phone and you hand that window to a stranger's algorithm. "
        "Most people call it harmless. But what most people don't realize is that "
        "the first input sets the emotional baseline for every decision that follows. "
        "Skip it for one morning and you will feel the difference by noon."
    ),
    "climax": (
        "Researchers tracked this for a year and the pattern held: the people who "
        "protected those ten minutes reported sharper focus and lower stress every "
        "single week."
    ),
    "cta": "Tomorrow, leave the phone face down and ask yourself what changed.",
}
STRONG_DURATION = 50

# The same subject announced instead of told: a greeting opener, two rambling
# sentences, no climax, no CTA, no curiosity gap anywhere.
WEAK_SECTIONS = {
    "hook": (
        "Hey everyone, in this video I want to talk about morning routines and why "
        "they matter for productivity in general."
    ),
    "build": (
        "Morning routines are something that a lot of people have talked about over "
        "the years and there are many different opinions about what works best for "
        "different people depending on their schedule, their job, their family "
        "situation, and a number of other factors that are worth considering "
        "carefully. Some people wake up early and some people wake up late, and both "
        "of these approaches can work depending on the person and their circumstances "
        "and preferences over time."
    ),
    "climax": "",
    "cta": "",
}
WEAK_DURATION = 50


def _story_text(sections: dict[str, str]) -> str:
    """Rebuild the labelled narration the script engine emits."""
    labels = {"hook": "Hook", "build": "Build", "climax": "Climax", "cta": "CTA"}
    return "\n\n".join(
        f"{labels[key]}: {sections[key]}" for key in SECTION_KEYS if sections[key]
    )


def _reason_codes(score: ViralScore, dimension_id: str) -> list[str]:
    dimension = score.dimension(dimension_id)
    assert dimension is not None, dimension_id
    return [reason.code for reason in dimension.reasons]


class ArchetypeTests(unittest.TestCase):
    """The fifteen detectors must stay pinned to `_ANGLE_STARTERS`."""

    def test_one_detector_per_angle_starter_in_order(self):
        self.assertEqual(len(ARCHETYPES), 15)
        self.assertEqual(len(_ANGLE_STARTERS), len(ARCHETYPES))
        self.assertEqual([a.starter for a in ARCHETYPES], list(_ANGLE_STARTERS))

    def test_archetype_ids_are_unique(self):
        ids = [a.id for a in ARCHETYPES]
        self.assertEqual(len(set(ids)), len(ids))

    def test_representative_openings_match_their_archetype(self):
        cases = {
            "little_known_fact": "Most people don't know this happens every single night.",
            "personal_anecdote": "I spent four years believing my father about this.",
            "provocative_question": "Why does nobody question the thing you do every morning?",
            "sensory_scene": "Picture this: the air is damp and you can smell the rain.",
            "controversial_claim": "Everything you know about sleep is a lie.",
            "historical_event": "In 1908 an entire forest fell and nobody was there.",
            "what_if": "What if the safest room in your house was the worst one?",
            "belief_subversion": "You believe willpower runs out, but actually the opposite happens.",
            "countdown_list": "Three signs your body is already ahead of you.",
            "mid_action": "She was already halfway down the stairs when the alarm went off.",
            "impossible_science": "Physicists ran the experiment and the particles arrived early.",
            "intimate_confession": "I never told anyone how ashamed that made me.",
            "contradictory_truths": "It is both the safest and the deadliest place on earth.",
            "warning_prediction": "This is a warning about something that will collapse first.",
            "universal_unspoken": "We all do it and nobody talks about it out loud.",
        }
        self.assertEqual(set(cases), {a.id for a in ARCHETYPES})
        for archetype_id, opening in cases.items():
            with self.subTest(archetype=archetype_id):
                matched = {m.id for m in match_archetypes(opening)}
                self.assertIn(archetype_id, matched)

    def test_empty_opening_matches_nothing(self):
        self.assertEqual(match_archetypes(""), [])
        self.assertEqual(match_archetypes("   "), [])

    def test_match_order_is_stable_and_by_confidence(self):
        opening = "A 2019 study found that most people don't know the truth."
        matches = match_archetypes(opening)
        self.assertGreaterEqual(len(matches), 2)
        confidences = [m.confidence for m in matches]
        self.assertEqual(confidences, sorted(confidences, reverse=True))
        self.assertEqual(matches, match_archetypes(opening))


class StrongVersusWeakTests(unittest.TestCase):
    """The headline requirement: clear separation with reasons on both sides."""

    def setUp(self):
        self.strong = score_script(
            sections=STRONG_SECTIONS,
            story_text=_story_text(STRONG_SECTIONS),
            target_duration=STRONG_DURATION,
        )
        self.weak = score_script(
            sections=WEAK_SECTIONS,
            story_text=_story_text(WEAK_SECTIONS),
            target_duration=WEAK_DURATION,
        )

    def test_strong_script_scores_high(self):
        self.assertGreaterEqual(self.strong.score, 75)
        self.assertEqual(self.strong.band, "strong")

    def test_weak_script_scores_low(self):
        self.assertLessEqual(self.weak.score, 45)
        self.assertIn(self.weak.band, ("poor", "weak"))

    def test_scores_are_clearly_separated(self):
        self.assertGreaterEqual(self.strong.score - self.weak.score, 30)

    def test_every_dimension_reports_reasons(self):
        for score in (self.strong, self.weak):
            self.assertEqual([d.id for d in score.dimensions], list(DIMENSION_IDS))
            for dimension in score.dimensions:
                with self.subTest(scored=score.score, dimension=dimension.id):
                    self.assertTrue(dimension.reasons)

    def test_strong_script_reasons_are_positive_where_it_counts(self):
        self.assertIn("archetype_matched", _reason_codes(self.strong, "opening_line"))
        self.assertIn("hook_position_ideal", _reason_codes(self.strong, "hook"))
        self.assertIn("word_rate_on_target", _reason_codes(self.strong, "pacing"))
        self.assertIn("open_loops_found", _reason_codes(self.strong, "open_loops"))
        self.assertIn("cta_action_signal", _reason_codes(self.strong, "cta"))
        self.assertIn("section_balance_ideal", _reason_codes(self.strong, "balance"))

    def test_weak_script_reasons_name_each_failure(self):
        self.assertIn("opening_generic", _reason_codes(self.weak, "opening_line"))
        self.assertIn("archetype_none", _reason_codes(self.weak, "opening_line"))
        self.assertIn("open_loops_none", _reason_codes(self.weak, "open_loops"))
        self.assertIn("cta_missing", _reason_codes(self.weak, "cta"))
        self.assertIn("sentences_too_long", _reason_codes(self.weak, "pacing"))
        missing = [
            reason.detail.get("section")
            for reason in self.weak.dimension("balance").reasons
            if reason.code == "section_missing"
        ]
        self.assertEqual(sorted(missing), ["climax", "cta"])

    def test_points_reconcile_with_the_headline_score(self):
        for score in (self.strong, self.weak):
            total = sum(d.points for d in score.dimensions)
            self.assertEqual(score.score, max(0, min(100, round(total))))


class DeterminismTests(unittest.TestCase):
    """Identical input always scores identically."""

    def _score(self, sections=STRONG_SECTIONS, **kwargs):
        return score_script(
            sections=sections,
            story_text=_story_text(sections),
            target_duration=STRONG_DURATION,
            **kwargs,
        )

    def test_repeated_scoring_is_byte_identical(self):
        first = self._score().model_dump()
        for _ in range(5):
            self.assertEqual(self._score().model_dump(), first)

    def test_weak_script_is_also_stable(self):
        first = self._score(WEAK_SECTIONS).model_dump()
        self.assertEqual(self._score(WEAK_SECTIONS).model_dump(), first)

    def test_section_key_order_does_not_change_the_score(self):
        reversed_sections = {key: STRONG_SECTIONS[key] for key in reversed(SECTION_KEYS)}
        self.assertEqual(
            self._score(reversed_sections).model_dump(),
            self._score().model_dump(),
        )

    def test_surrounding_whitespace_does_not_change_the_score(self):
        padded = {key: f"  {value}\n\n " for key, value in STRONG_SECTIONS.items()}
        self.assertEqual(
            self._score(padded).model_dump(),
            self._score().model_dump(),
        )

    def test_scorer_identity_is_stamped(self):
        score = self._score()
        self.assertEqual(score.scorer, SCORER_ID)
        self.assertGreaterEqual(score.scorer_version, 1)

    def test_round_trips_through_its_own_schema(self):
        score = self._score()
        self.assertEqual(ViralScore.model_validate(score.model_dump()), score)


class DimensionBehaviourTests(unittest.TestCase):
    """Each dimension moves for the reason it claims to measure."""

    def _score(self, sections, duration=STRONG_DURATION, **kwargs):
        return score_script(
            sections=sections,
            story_text=_story_text(sections),
            target_duration=duration,
            **kwargs,
        )

    def test_removing_the_hook_costs_the_hook_dimension(self):
        without = {**STRONG_SECTIONS, "hook": ""}
        base = self._score(STRONG_SECTIONS).dimension("hook").score
        stripped = self._score(without)
        self.assertEqual(stripped.dimension("hook").score, 0.0)
        self.assertIn("hook_missing", _reason_codes(stripped, "hook"))
        self.assertGreater(base, stripped.dimension("hook").score)

    def test_a_hook_that_is_not_first_loses_position_credit(self):
        shuffled = _story_text(
            {**STRONG_SECTIONS, "hook": ""}
        ) + "\n\nHook: " + STRONG_SECTIONS["hook"]
        score = score_script(
            sections=STRONG_SECTIONS,
            story_text=shuffled,
            target_duration=STRONG_DURATION,
        )
        self.assertIn("hook_not_first", _reason_codes(score, "hook"))
        self.assertLess(
            score.dimension("hook").score,
            self._score(STRONG_SECTIONS).dimension("hook").score,
        )

    def test_generic_opener_outscored_by_archetype_opener(self):
        generic = {**STRONG_SECTIONS, "hook": "So today I want to talk about mornings."}
        self.assertGreater(
            self._score(STRONG_SECTIONS).dimension("opening_line").score,
            self._score(generic).dimension("opening_line").score,
        )

    def test_word_rate_penalised_in_both_directions(self):
        on_target = self._score(STRONG_SECTIONS, duration=STRONG_DURATION)
        too_short = self._score(STRONG_SECTIONS, duration=120)
        too_long = self._score(STRONG_SECTIONS, duration=20)
        self.assertIn("word_rate_on_target", _reason_codes(on_target, "pacing"))
        self.assertIn("word_rate_under", _reason_codes(too_short, "pacing"))
        self.assertIn("word_rate_over", _reason_codes(too_long, "pacing"))
        self.assertGreater(on_target.dimension("pacing").score, too_short.dimension("pacing").score)
        self.assertGreater(on_target.dimension("pacing").score, too_long.dimension("pacing").score)

    def test_word_rate_measures_against_the_shared_words_per_second(self):
        score = self._score(STRONG_SECTIONS)
        words = score.metrics["total_words"]
        self.assertEqual(score.metrics["estimated_duration"], round(words / WORDS_PER_SECOND, 2))

    def test_stripping_open_loops_zeroes_that_dimension(self):
        flat = {
            **STRONG_SECTIONS,
            "hook": "A 2019 study found that most people don't know their first ten minutes awake decide the whole day.",
            "build": (
                "You wake up, and your brain is still running on the last thing it touched. "
                "Reach for your phone and you hand that window to a stranger's algorithm. "
                "Most people call it harmless. The first input sets the emotional baseline "
                "for every decision that follows. Skip it for one morning and you will feel "
                "the difference by noon."
            ),
        }
        score = self._score(flat)
        self.assertEqual(score.dimension("open_loops").score, 0.0)
        self.assertIn("open_loops_none", _reason_codes(score, "open_loops"))

    def test_cta_without_an_action_signal_scores_below_one_with(self):
        passive = {**STRONG_SECTIONS, "cta": "That is how the morning works."}
        self.assertGreater(
            self._score(STRONG_SECTIONS).dimension("cta").score,
            self._score(passive).dimension("cta").score,
        )
        self.assertIn("cta_no_action_signal", _reason_codes(self._score(passive), "cta"))

    def test_balance_penalises_a_bloated_section(self):
        bloated = {**STRONG_SECTIONS, "hook": STRONG_SECTIONS["build"] * 2}
        score = self._score(bloated)
        codes = _reason_codes(score, "balance")
        self.assertIn("section_share_high", codes)
        self.assertLess(
            score.dimension("balance").score,
            self._score(STRONG_SECTIONS).dimension("balance").score,
        )

    def test_narrative_roles_sharpen_hook_position(self):
        leading = self._score(STRONG_SECTIONS, narrative_roles=["hook", "buildup", "peak", "cta"])
        trailing = self._score(STRONG_SECTIONS, narrative_roles=["buildup", "hook", "peak", "cta"])
        self.assertIn("hook_role_leads", _reason_codes(leading, "hook"))
        self.assertIn("hook_role_not_first", _reason_codes(trailing, "hook"))
        self.assertGreater(leading.dimension("hook").score, trailing.dimension("hook").score)

    def test_narrative_roles_are_ignored_when_absent(self):
        self.assertEqual(
            self._score(STRONG_SECTIONS, narrative_roles=[]).model_dump(),
            self._score(STRONG_SECTIONS).model_dump(),
        )


class InputHandlingTests(unittest.TestCase):
    """Partial and degenerate input must score rather than raise."""

    def test_unlabelled_story_text_alone_still_scores(self):
        score = score_script(
            story_text="Most people don't know this. But here's the thing: it changes everything.",
            target_duration=15,
        )
        self.assertGreater(score.score, 0)
        self.assertEqual(score.metrics["section_words"]["build"], score.metrics["total_words"])

    def test_sections_alone_still_scores(self):
        with_text = score_script(
            sections=STRONG_SECTIONS,
            story_text=_story_text(STRONG_SECTIONS),
            target_duration=STRONG_DURATION,
        )
        without_text = score_script(sections=STRONG_SECTIONS, target_duration=STRONG_DURATION)
        self.assertEqual(without_text.score, with_text.score)

    def test_empty_script_scores_zero_without_raising(self):
        score = score_script(sections={}, story_text="", target_duration=45)
        self.assertEqual(score.score, 0)
        self.assertEqual(score.band, "poor")
        self.assertEqual(score.metrics["total_words"], 0)

    def test_non_positive_target_duration_is_clamped(self):
        self.assertEqual(
            score_script(sections=STRONG_SECTIONS, target_duration=0).metrics["target_duration"], 1
        )

    def test_story_payload_adapter_reads_the_script_service_shape(self):
        payload = {
            "sections": STRONG_SECTIONS,
            "story_text": _story_text(STRONG_SECTIONS),
            "metadata": {"duration": STRONG_DURATION},
        }
        self.assertEqual(
            score_story_payload(payload).model_dump(),
            score_script(
                sections=STRONG_SECTIONS,
                story_text=_story_text(STRONG_SECTIONS),
                target_duration=STRONG_DURATION,
            ).model_dump(),
        )

    def test_story_payload_without_duration_falls_back(self):
        score = score_story_payload({"sections": STRONG_SECTIONS, "story_text": ""})
        self.assertEqual(score.metrics["target_duration"], 45)

    def test_labels_are_stripped_before_counting_words(self):
        doc = build_doc(STRONG_SECTIONS, _story_text(STRONG_SECTIONS), STRONG_DURATION)
        self.assertNotIn("Hook:", doc.story_text)
        self.assertNotIn("CTA:", doc.story_text)
        self.assertEqual(doc.total_words, sum(doc.section_words.values()))

    def test_sentence_split_handles_all_terminators(self):
        self.assertEqual(
            split_sentences("One. Two! Three? Four\u2026 Five"),
            ["One.", "Two!", "Three?", "Four\u2026", "Five"],
        )


class ContractTests(unittest.TestCase):
    """The shapes step 16.2 and 16.3 will build on."""

    def test_weights_cover_every_dimension_and_sum_to_one(self):
        self.assertEqual(tuple(DIMENSION_WEIGHTS), DIMENSION_IDS)
        self.assertEqual(round(sum(DIMENSION_WEIGHTS.values()), 6), 1.0)

    def test_bands_partition_the_range(self):
        self.assertEqual(band_for(100), "strong")
        self.assertEqual(band_for(75), "strong")
        self.assertEqual(band_for(74), "solid")
        self.assertEqual(band_for(60), "solid")
        self.assertEqual(band_for(59), "weak")
        self.assertEqual(band_for(40), "weak")
        self.assertEqual(band_for(39), "poor")
        self.assertEqual(band_for(0), "poor")

    def test_reasons_carry_codes_not_prose(self):
        score = score_script(
            sections=WEAK_SECTIONS,
            story_text=_story_text(WEAK_SECTIONS),
            target_duration=WEAK_DURATION,
        )
        for dimension in score.dimensions:
            for reason in dimension.reasons:
                with self.subTest(dimension=dimension.id, code=reason.code):
                    self.assertRegex(reason.code, r"^[a-z][a-z0-9_]*$")
                    self.assertIn(reason.impact, ("positive", "negative"))

    def test_score_carries_the_metrics_it_was_computed_from(self):
        score = score_script(
            sections=STRONG_SECTIONS,
            story_text=_story_text(STRONG_SECTIONS),
            target_duration=STRONG_DURATION,
        )
        self.assertEqual(
            set(score.metrics),
            {
                "total_words",
                "estimated_duration",
                "target_duration",
                "section_words",
                "section_shares",
                "sentences",
                "opening_line",
            },
        )
        self.assertEqual(score.metrics["target_duration"], STRONG_DURATION)


if __name__ == "__main__":
    unittest.main()
