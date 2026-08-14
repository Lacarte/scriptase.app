"""Step 5.4: Prompt evaluation harness.

Done when:
  * a deliberate prompt regression is caught by the harness offline
  * no provider credits are spent
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scriptase.providers import fixtures as provider_fixtures
from scriptase.providers.prompt_eval import (
    SCENE_DIRECTOR_PROMPT_MARKERS,
    build_sample_scene_director_prompt,
    check,
    compare_structure,
    evaluate_all,
    evaluate_case,
    evaluate_prompt_contracts,
    extract_scene_structure,
    list_cases,
    load_expected_structure,
    resolve_payload,
    validate_prompt_eval_fixtures,
)


class StructureExtractionTests(unittest.TestCase):
    def test_extract_from_raw_response_fixture(self):
        raw = provider_fixtures.load_fixture(
            "scene_director", "n8n", "raw_response.json"
        )
        structure = extract_scene_structure(raw)
        self.assertEqual(structure["scene_count"], 5)
        self.assertEqual(
            structure["roles"],
            ["hook", "buildup", "text_accent", "peak", "cta"],
        )
        self.assertEqual(
            structure["types"],
            ["video", "video", "text", "video", "image"],
        )
        self.assertTrue(all(structure["nonempty_prompts"]))
        # Free-form prompt text is never carried as an equality axis.
        self.assertNotIn("image_prompts", structure)
        self.assertNotIn("image_prompt", structure)

    def test_extract_from_result_envelope(self):
        envelope = provider_fixtures.load_fixture(
            "scene_director", "n8n", "expected_result.json"
        )
        structure = extract_scene_structure(envelope)
        self.assertEqual(structure["scene_count"], 5)
        self.assertEqual(structure["indexes"], [0, 1, 2, 3, 4])

    def test_compare_ignores_freeform_prompt_wording(self):
        """Two payloads with different image_prompt text but same structure pass."""
        a = {
            "scenes": [
                {
                    "index": 0,
                    "narrative_role": "hook",
                    "type_of_scene": "video",
                    "image_prompt": "wide, red corridor, cool light",
                },
                {
                    "index": 1,
                    "narrative_role": "cta",
                    "type_of_scene": "image",
                    "image_prompt": "close-up, face in mirror",
                },
            ]
        }
        b = {
            "scenes": [
                {
                    "index": 0,
                    "narrative_role": "hook",
                    "type_of_scene": "video",
                    "image_prompt": "COMPLETELY DIFFERENT WORDING for scene zero",
                },
                {
                    "index": 1,
                    "narrative_role": "cta",
                    "type_of_scene": "image",
                    "image_prompt": "and also totally different for scene one",
                },
            ]
        }
        expected = {
            "scene_count": 2,
            "roles": ["hook", "cta"],
            "types": ["video", "image"],
            "rules": {"nonempty_image_prompt": True, "first_not_text": True},
        }
        self.assertEqual(compare_structure(a, expected), [])
        self.assertEqual(compare_structure(b, expected), [])


class GoldenCaseTests(unittest.TestCase):
    def test_fixture_tree_is_valid(self):
        problems = validate_prompt_eval_fixtures()
        self.assertEqual(problems, [], msg="\n".join(problems))

    def test_cases_are_registered(self):
        cases = list_cases()
        self.assertIn(("scene_director", "notice_pattern"), cases)
        self.assertIn(("scene_director", "notice_pattern_envelope"), cases)
        self.assertIn(("scene_director", "offline_planner_notice"), cases)

    def test_every_case_passes_offline(self):
        for domain, case_id in list_cases():
            with self.subTest(case=f"{domain}/{case_id}"):
                report = evaluate_case(domain, case_id)
                self.assertEqual(report.credits_spent, 0)
                self.assertTrue(
                    report.ok,
                    msg=f"{report.summary()}\n"
                    + "\n".join(d.format() for d in report.drifts),
                )

    def test_evaluate_all_includes_prompt_contract(self):
        reports = evaluate_all()
        ids = {(r.domain, r.case_id) for r in reports}
        self.assertIn(("scene_director", "prompt_contract"), ids)
        for report in reports:
            self.assertEqual(report.credits_spent, 0)
            self.assertTrue(
                report.ok,
                msg=f"{report.summary()}\n"
                + "\n".join(d.format() for d in report.drifts),
            )

    def test_check_cli_is_green(self):
        self.assertEqual(check(), 0)

    def test_offline_planner_does_not_touch_network(self):
        """resolve_payload for offline_planner must not call requests."""
        case = {
            "domain": "scene_director",
            "source": {
                "kind": "offline_planner",
                "script": "One beat only.",
                "segments": [{"index": 0, "words": "One beat only."}],
                "visual_direction": {
                    "style": "cinematic",
                    "pattern": [
                        {"narrative_role": "hook", "shot": "wide"},
                    ],
                },
            },
        }
        with mock.patch("requests.post") as post:
            with mock.patch("requests.get") as get:
                payload = resolve_payload(case)
                post.assert_not_called()
                get.assert_not_called()
        self.assertEqual(len(payload["scenes"]), 1)
        self.assertTrue(payload["scenes"][0]["image_prompt"])


class DeliberateRegressionTests(unittest.TestCase):
    """The done-when: a deliberate prompt regression is caught offline."""

    def test_scene_count_regression_is_caught(self):
        raw = provider_fixtures.load_fixture(
            "scene_director", "n8n", "raw_response.json"
        )
        broken = dict(raw)
        broken["scenes"] = list(raw["scenes"])[:-1]  # drop the CTA scene
        expected = load_expected_structure("scene_director", "notice_pattern")
        drifts = compare_structure(broken, expected)
        self.assertTrue(drifts)
        paths = {d.path for d in drifts}
        self.assertTrue(
            any("scene_count" in p or "roles" in p or "types" in p for p in paths),
            msg=f"expected structural drift, got: {drifts}",
        )

    def test_first_scene_text_regression_is_caught(self):
        scenes = [
            {
                "index": 0,
                "narrative_role": "hook",
                "type_of_scene": "text",  # violates first_not_text
                "image_prompt": "blurred bg",
                "text_content": "HOOK",
            },
            {
                "index": 1,
                "narrative_role": "cta",
                "type_of_scene": "video",
                "image_prompt": "wide ending",
            },
        ]
        expected = {
            "scene_count": 2,
            "rules": {"first_not_text": True, "last_not_text": True},
        }
        drifts = compare_structure({"scenes": scenes}, expected)
        self.assertTrue(any("first_not_text" in d.path for d in drifts))

    def test_role_vocabulary_regression_is_caught(self):
        scenes = [
            {
                "index": 0,
                "narrative_role": "not_a_real_role",
                "type_of_scene": "video",
                "image_prompt": "wide shot of something",
            },
        ]
        expected = {"rules": {"roles_in_vocabulary": True}}
        drifts = compare_structure({"scenes": scenes}, expected)
        self.assertTrue(any("roles" in d.path for d in drifts))

    def test_empty_image_prompt_regression_is_caught(self):
        scenes = [
            {
                "index": 0,
                "narrative_role": "hook",
                "type_of_scene": "video",
                "image_prompt": "   ",
            },
        ]
        expected = {"rules": {"nonempty_image_prompt": True}}
        drifts = compare_structure({"scenes": scenes}, expected)
        self.assertTrue(any("image_prompt" in d.path for d in drifts))

    def test_prompt_marker_regression_is_caught(self):
        """Deleting a required instructional marker fails the prompt contract."""
        good = build_sample_scene_director_prompt()
        self.assertTrue(evaluate_prompt_contracts(prompt_text=good).ok)

        marker = "Return exactly ONE scene for every input segment"
        self.assertIn(marker, good)
        broken = good.replace(marker, "Return some scenes somehow")
        report = evaluate_prompt_contracts(prompt_text=broken)
        self.assertFalse(report.ok)
        self.assertEqual(report.credits_spent, 0)
        self.assertTrue(
            any(marker in str(d.expected) for d in report.drifts),
            msg=f"expected marker drift, got: {report.drifts}",
        )

    def test_every_required_marker_is_present_in_live_builder(self):
        prompt = build_sample_scene_director_prompt()
        for marker in SCENE_DIRECTOR_PROMPT_MARKERS:
            with self.subTest(marker=marker[:48]):
                self.assertIn(marker, prompt)

    def test_harness_detects_regression_in_temp_case_tree(self):
        """End-to-end: plant a broken case on disk and watch evaluate_case fail."""
        good_raw = provider_fixtures.load_fixture(
            "scene_director", "n8n", "raw_response.json"
        )
        broken = dict(good_raw)
        # Collapse all roles to the same illegal value — structural drift.
        broken_scenes = []
        for scene in good_raw["scenes"]:
            row = dict(scene)
            row["narrative_role"] = "illegal_role"
            broken_scenes.append(row)
        broken["scenes"] = broken_scenes

        with tempfile.TemporaryDirectory() as tmp:
            case_root = Path(tmp)
            case_dir = case_root / "scene_director" / "deliberate_break"
            case_dir.mkdir(parents=True)
            (case_dir / "case.json").write_text(
                json.dumps({
                    "id": "deliberate_break",
                    "domain": "scene_director",
                    "source": {
                        "kind": "inline",
                        "scenes": broken["scenes"],
                    },
                }),
                encoding="utf-8",
            )
            (case_dir / "expected_structure.json").write_text(
                json.dumps({
                    "scene_count": 5,
                    "roles": ["hook", "buildup", "text_accent", "peak", "cta"],
                    "rules": {"roles_in_vocabulary": True},
                }),
                encoding="utf-8",
            )
            report = evaluate_case(
                "scene_director", "deliberate_break", root=str(case_root)
            )
            self.assertEqual(report.credits_spent, 0)
            self.assertFalse(report.ok, msg="deliberate regression must fail")
            self.assertGreaterEqual(len(report.drifts), 1)


class NoCreditsSpentTests(unittest.TestCase):
    def test_evaluate_all_never_calls_outbound_http(self):
        with mock.patch("requests.post") as post:
            with mock.patch("requests.get") as get:
                with mock.patch("requests.request") as request:
                    reports = evaluate_all()
                    post.assert_not_called()
                    get.assert_not_called()
                    request.assert_not_called()
        self.assertTrue(reports)
        self.assertTrue(all(r.credits_spent == 0 for r in reports))


if __name__ == "__main__":
    unittest.main()
