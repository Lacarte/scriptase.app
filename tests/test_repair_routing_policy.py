"""Step 8.1 — Repair routing policy.

Done when: every issue type in the §12.2 table routes to its owning node,
enforced by a table-driven test.

The ownership table lives in ``scriptase.review.policy`` and is the single
source of truth — no if/elif trees in the engine decide where a repair goes.
"""

from __future__ import annotations

import unittest

from scriptase.review.models import ISSUE_TYPES, ReviewIssueDraft
from scriptase.review.policy import (
    CHECK_ID_PROBLEM,
    ISSUE_TYPE_DEFAULT_PROBLEM,
    NODE_TYPE_OWNER,
    OWNERSHIP_BY_PROBLEM,
    OWNERSHIP_TABLE,
    OWNERS,
    PROBLEM_ALIGNMENT,
    PROBLEM_CAPTION_BRANDING,
    PROBLEM_IMAGE_SUBJECT_STYLE,
    PROBLEM_KEYS,
    PROBLEM_MOTION,
    PROBLEM_PRONUNCIATION_VOICE,
    PROBLEM_RENDER_CODEC,
    PROBLEM_SCENE_BOUNDARIES,
    PROBLEM_SCRIPT_CONTENT,
    PROBLEM_VISUAL_CONCEPT,
    RoutingDecision,
    UnknownRoutingProblem,
    UnroutableIssue,
    assert_routing_table_complete,
    ownership_rows,
    route_issue,
    route_problem,
)

# ---------------------------------------------------------------------------
# §12.2 table as frozen in contracts.md — the done-when fixture.
# (description, expected_owner_label, expected_owner_id, expected_primary_node)
# ---------------------------------------------------------------------------

SECTION_12_2_ROWS: tuple[tuple[str, str, str, str], ...] = (
    (
        "Script too long, wrong tone, weak hook",
        "Script",
        "script",
        "story.generate",
    ),
    (
        "Pronunciation or voice problem",
        "TTS",
        "tts",
        "tts.generate",
    ),
    (
        "Words do not align with audio",
        "Timing",
        "timing",
        "timing.align",
    ),
    (
        "Poor or overlong scene boundaries",
        "Segmenter",
        "segmenter",
        "segment.run",
    ),
    (
        "Visual concept does not represent narration",
        "Scene Director",
        "scene_director",
        "scenes.blueprint",
    ),
    (
        "Wrong character, object, or style in a still",
        "Image Generator",
        "image",
        "storyboard.generate",
    ),
    (
        "Motion deformation, instability, poor animation",
        "Video Generator",
        "video",
        "animator.generate",
    ),
    (
        "Caption outside safe area, branding missing",
        "Assembly",
        "composer",
        "assemble.project",
    ),
    (
        "Render corruption, codec failure",
        "Export",
        "export",
        "export.video",
    ),
)

# Parallel problem keys in table order (must stay aligned with SECTION_12_2_ROWS).
SECTION_12_2_PROBLEM_KEYS: tuple[str, ...] = (
    PROBLEM_SCRIPT_CONTENT,
    PROBLEM_PRONUNCIATION_VOICE,
    PROBLEM_ALIGNMENT,
    PROBLEM_SCENE_BOUNDARIES,
    PROBLEM_VISUAL_CONCEPT,
    PROBLEM_IMAGE_SUBJECT_STYLE,
    PROBLEM_MOTION,
    PROBLEM_CAPTION_BRANDING,
    PROBLEM_RENDER_CODEC,
)


class OwnershipTableStructureTests(unittest.TestCase):
    """The module table itself is complete and matches §12.2."""

    def test_assert_routing_table_complete_passes(self):
        assert_routing_table_complete()  # raises on drift

    def test_problem_keys_cover_section_12_2(self):
        self.assertEqual(len(OWNERSHIP_TABLE), len(SECTION_12_2_ROWS))
        self.assertEqual(tuple(PROBLEM_KEYS), SECTION_12_2_PROBLEM_KEYS)
        self.assertEqual(len(OWNERS), 9)

    def test_ownership_rows_snapshot_matches_table(self):
        rows = ownership_rows()
        self.assertEqual(len(rows), len(OWNERSHIP_TABLE))
        for snapshot, row in zip(rows, OWNERSHIP_TABLE):
            self.assertEqual(snapshot["problem_key"], row.problem_key)
            self.assertEqual(snapshot["owner"], row.owner)
            self.assertEqual(snapshot["label"], row.label)
            self.assertEqual(snapshot["node_types"][0], row.node_types[0])


class Section12_2TableDrivenTests(unittest.TestCase):
    """Done-when: every §12.2 row routes to its owning node via the table."""

    def test_every_section_12_2_row_routes_to_owning_node(self):
        self.assertEqual(len(SECTION_12_2_ROWS), len(OWNERSHIP_TABLE))
        self.assertEqual(len(SECTION_12_2_ROWS), len(SECTION_12_2_PROBLEM_KEYS))

        for index, (description, label, owner, primary_node) in enumerate(
            SECTION_12_2_ROWS
        ):
            problem_key = SECTION_12_2_PROBLEM_KEYS[index]
            with self.subTest(problem_key=problem_key, description=description):
                decision = route_problem(problem_key)
                self.assertIsInstance(decision, RoutingDecision)
                self.assertEqual(decision.problem_key, problem_key)
                self.assertEqual(decision.owner, owner)
                self.assertEqual(decision.label, label)
                self.assertEqual(decision.routed_to_node_type, primary_node)
                self.assertEqual(decision.node_types[0], primary_node)
                self.assertIn(primary_node, decision.node_types)
                # Description is the human §12.2 wording (allow minor punctuation).
                self.assertEqual(
                    decision.description.casefold().replace("/", ","),
                    description.casefold().replace("/", ","),
                )
                # Table lookup, not a free-form branch label.
                self.assertEqual(decision.source, "problem_key")

    def test_ownership_table_descriptions_align_with_contracts(self):
        for index, row in enumerate(OWNERSHIP_TABLE):
            expected_description = SECTION_12_2_ROWS[index][0]
            with self.subTest(problem_key=row.problem_key):
                self.assertEqual(
                    row.description.casefold().replace("/", ","),
                    expected_description.casefold().replace("/", ","),
                )
                self.assertEqual(row.label, SECTION_12_2_ROWS[index][1])
                self.assertEqual(row.owner, SECTION_12_2_ROWS[index][2])
                self.assertEqual(
                    row.node_types[0], SECTION_12_2_ROWS[index][3]
                )


class IssueTypeDefaultRoutingTests(unittest.TestCase):
    """Every contracts.md issue_type has a default owner via the table."""

    def test_every_issue_type_has_default_problem(self):
        for issue_type in ISSUE_TYPES:
            with self.subTest(issue_type=issue_type):
                self.assertIn(issue_type, ISSUE_TYPE_DEFAULT_PROBLEM)
                problem = ISSUE_TYPE_DEFAULT_PROBLEM[issue_type]
                self.assertIn(problem, OWNERSHIP_BY_PROBLEM)

    def test_route_issue_by_issue_type_defaults(self):
        # One representative draft per issue_type — table-driven over ISSUE_TYPES.
        expectations = {
            "script_defect": ("script", "story.generate"),
            "audio_defect": ("tts", "tts.generate"),
            "timing_drift": ("timing", "timing.align"),
            "segmentation_defect": ("segmenter", "segment.run"),
            "visual_mismatch": ("image", "storyboard.generate"),
            "continuity_break": ("scene_director", "scenes.blueprint"),
            "motion_defect": ("video", "animator.generate"),
            "technical_defect": ("export", "export.video"),
            "policy_violation": ("composer", "assemble.project"),
        }
        self.assertEqual(set(expectations), set(ISSUE_TYPES))

        for issue_type, (owner, node_type) in expectations.items():
            with self.subTest(issue_type=issue_type):
                draft = ReviewIssueDraft.model_validate(
                    {
                        "job_id": "job_ROUTE1",
                        "issue_type": issue_type,
                        "severity": "high",
                        "confidence": 0.9,
                        "reason": f"Fixture for {issue_type}",
                        "suggested_action": "regenerate",
                    }
                )
                decision = route_issue(draft)
                self.assertEqual(decision.owner, owner)
                self.assertEqual(decision.routed_to_node_type, node_type)
                self.assertEqual(decision.source, "issue_type")
                self.assertEqual(decision.issue_type, issue_type)

    def test_route_issue_accepts_plain_mapping(self):
        decision = route_issue(
            {
                "issue_type": "motion_defect",
                "severity": "critical",
                "reason": "Warped face",
            }
        )
        self.assertEqual(decision.owner, "video")
        self.assertEqual(decision.routed_to_node_type, "animator.generate")


class DisambiguationTests(unittest.TestCase):
    """visual_mismatch concept vs subject, and technical check_id overrides."""

    def test_observed_problem_key_overrides_visual_mismatch_to_scene_director(self):
        decision = route_issue(
            {
                "issue_type": "visual_mismatch",
                "severity": "high",
                "reason": "Blueprint concept does not match narration.",
                "observed": {"problem_key": PROBLEM_VISUAL_CONCEPT},
            }
        )
        self.assertEqual(decision.owner, "scene_director")
        self.assertEqual(decision.routed_to_node_type, "scenes.blueprint")
        self.assertEqual(decision.source, "observed")
        self.assertEqual(decision.problem_key, PROBLEM_VISUAL_CONCEPT)

    def test_routing_problem_alias_accepted(self):
        decision = route_issue(
            {
                "issue_type": "visual_mismatch",
                "severity": "medium",
                "reason": "alias path",
                "observed": {"routing_problem": PROBLEM_CAPTION_BRANDING},
            }
        )
        self.assertEqual(decision.owner, "composer")
        self.assertEqual(decision.source, "observed")

    def test_check_id_routes_readable_media_to_export(self):
        decision = route_issue(
            {
                "issue_type": "technical_defect",
                "severity": "critical",
                "reason": "Unreadable container",
                "check_id": "readable_media",
            }
        )
        self.assertEqual(decision.owner, "export")
        self.assertEqual(decision.source, "check_id")
        self.assertEqual(decision.check_id, "readable_media")

    def test_check_id_routes_resolution_to_image(self):
        decision = route_issue(
            {
                "issue_type": "technical_defect",
                "severity": "high",
                "reason": "Wrong resolution",
                "check_id": "resolution",
            }
        )
        self.assertEqual(decision.owner, "image")
        self.assertEqual(decision.routed_to_node_type, "storyboard.generate")
        self.assertEqual(decision.source, "check_id")

    def test_check_id_routes_duration_to_video(self):
        decision = route_issue(
            {
                "issue_type": "technical_defect",
                "severity": "high",
                "reason": "Clip too short",
                "check_id": "duration",
            }
        )
        self.assertEqual(decision.owner, "video")
        self.assertEqual(decision.source, "check_id")

    def test_every_known_check_id_maps_to_a_table_row(self):
        for check_id, problem_key in CHECK_ID_PROBLEM.items():
            with self.subTest(check_id=check_id):
                self.assertIn(problem_key, OWNERSHIP_BY_PROBLEM)
                decision = route_issue(
                    {
                        "issue_type": "technical_defect",
                        "severity": "high",
                        "reason": f"check {check_id}",
                        "check_id": check_id,
                    }
                )
                self.assertEqual(decision.problem_key, problem_key)


class ErrorAndHelperTests(unittest.TestCase):
    def test_unknown_problem_key_raises(self):
        with self.assertRaises(UnknownRoutingProblem) as ctx:
            route_problem("not_a_real_problem")
        self.assertEqual(ctx.exception.problem_key, "not_a_real_problem")

    def test_unknown_observed_problem_key_raises(self):
        with self.assertRaises(UnknownRoutingProblem):
            route_issue(
                {
                    "issue_type": "script_defect",
                    "severity": "low",
                    "reason": "x",
                    "observed": {"problem_key": "nope"},
                }
            )

    def test_missing_issue_type_raises_unroutable(self):
        with self.assertRaises(UnroutableIssue):
            route_issue({"severity": "low", "reason": "no type"})

    def test_decision_to_dict_exposes_history_fields(self):
        decision = route_problem(PROBLEM_MOTION)
        payload = decision.to_dict()
        self.assertEqual(payload["routed_to_node_type"], "animator.generate")
        self.assertEqual(payload["owner"], "video")
        self.assertEqual(payload["stage_key"], "videos")
        self.assertIn("animator.generate", payload["node_types"])

    def test_node_type_owner_reverse_map(self):
        self.assertEqual(NODE_TYPE_OWNER["tts.generate"], "tts")
        self.assertEqual(NODE_TYPE_OWNER["scenes.blueprint"], "scene_director")
        self.assertEqual(NODE_TYPE_OWNER["export.video"], "export")


if __name__ == "__main__":
    unittest.main()
