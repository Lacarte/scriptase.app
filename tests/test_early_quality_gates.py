"""Step 7.4 — Early quality gates.

Done when: a deliberately bad source image is caught and repaired before any
video generation call, proven by asserting the video provider was never
invoked.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from PIL import Image

from scriptase.engine.adapters import AdapterContext, AdapterError
from scriptase.engine.adapters import video as video_adapter
from scriptase.review.gates import (
    QUALITY_GATE_FAILED,
    GateUnit,
    QualityGateResult,
    enforce_image_gate_for_video,
    resolve_managed_path,
    run_image_gate,
    run_video_gate,
    units_from_storyboard,
    units_from_video_assets,
)
from scriptase.review.technical import TechnicalIssue


def _write_png(path: str, width: int, height: int, color=(30, 60, 90)) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Image.new("RGB", (width, height), color).save(path, format="PNG")
    return path


def _write_garbage(path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"not-a-real-image-payload")
    return path


class GateUnitHelpersTests(unittest.TestCase):
    def test_units_from_storyboard_artifact_refs(self):
        units = units_from_storyboard(
            {
                "ready": 1,
                "total": 1,
                "artifact_refs": ["storyboard/job/0/still.png"],
            },
            aspect_ratio="9:16",
        )
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].path_ref, "storyboard/job/0/still.png")
        self.assertEqual(units[0].aspect_ratio, "9:16")

    def test_units_from_storyboard_scene_statuses(self):
        units = units_from_storyboard(
            {
                "scene_statuses": {
                    "0": {
                        "scene_id": "scn_AAAAAA",
                        "local_path": "/output/storyboard/pm_X/0/a.png",
                        "status": "ready",
                    }
                }
            }
        )
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].scene_id, "scn_AAAAAA")
        self.assertEqual(units[0].path_ref, "storyboard/pm_X/0/a.png")

    def test_resolve_managed_path_rejects_outside_output(self):
        # Absolute path outside OUTPUT_DIR must not be accepted.
        outside = os.path.abspath(os.path.join(tempfile.gettempdir(), "escape.png"))
        # Only reject when the path is absolute and not under managed prefixes
        # resolved via OUTPUT_DIR — outside temp is not managed.
        result = resolve_managed_path(outside)
        # May return None (rejected) or a path only if temp coincides with OUTPUT.
        if result is not None:
            from config import OUTPUT_DIR

            root = os.path.abspath(OUTPUT_DIR)
            self.assertEqual(os.path.commonpath([root, result]), root)


class ImageGateTests(unittest.TestCase):
    def test_good_image_passes(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_gate_") as tmp:
            path = _write_png(os.path.join(tmp, "ok.png"), 90, 160)
            result = run_image_gate(
                [
                    GateUnit(
                        path=path,
                        path_ref="storyboard/ok.png",
                        scene_id="scn_GOOD01",
                        aspect_ratio="9:16",
                    )
                ]
            )
            self.assertTrue(result.passed)
            self.assertEqual(result.gate, "image")
            self.assertEqual(result.units_checked, 1)
            self.assertEqual(result.repairs_attempted, 0)

    def test_missing_image_blocks(self):
        missing = os.path.join(
            tempfile.gettempdir(), "scriptase_gate_no_such_still.png"
        )
        if os.path.exists(missing):
            os.remove(missing)
        result = run_image_gate(
            [
                GateUnit(
                    path=missing,
                    path_ref="storyboard/missing.png",
                    scene_id="scn_MISS01",
                )
            ]
        )
        self.assertFalse(result.passed)
        self.assertGreaterEqual(len(result.blocking_issues), 1)
        issue = result.blocking_issues[0]
        check_id = getattr(issue, "check_id", None) or (
            issue.get("check_id") if isinstance(issue, dict) else None
        )
        self.assertEqual(check_id, "file_exists")

    def test_unreadable_image_blocks(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_gate_") as tmp:
            path = _write_garbage(os.path.join(tmp, "broken.png"))
            result = run_image_gate(
                [GateUnit(path=path, path_ref="storyboard/broken.png")]
            )
            self.assertFalse(result.passed)
            check_ids = {
                getattr(i, "check_id", None)
                or (i.get("check_id") if isinstance(i, dict) else None)
                for i in result.blocking_issues
            }
            self.assertIn("readable_media", check_ids)

    def test_wrong_aspect_ratio_blocks(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_gate_") as tmp:
            # Square when 9:16 is required.
            path = _write_png(os.path.join(tmp, "square.png"), 100, 100)
            result = run_image_gate(
                [
                    GateUnit(
                        path=path,
                        path_ref="storyboard/square.png",
                        aspect_ratio="9:16",
                    )
                ]
            )
            self.assertFalse(result.passed)
            check_ids = {
                getattr(i, "check_id", None)
                or (i.get("check_id") if isinstance(i, dict) else None)
                for i in result.blocking_issues
            }
            self.assertIn("aspect_ratio", check_ids)

    def test_bad_image_repaired_before_pass(self):
        """Deliberately bad still is repaired; gate passes after rewrite."""
        with tempfile.TemporaryDirectory(prefix="scriptase_gate_") as tmp:
            bad_path = _write_garbage(os.path.join(tmp, "scene.png"))
            good_path = os.path.join(tmp, "scene_fixed.png")
            repair_calls: list[str] = []

            def repair(unit: GateUnit, issues) -> GateUnit:
                repair_calls.append(unit.path)
                self.assertTrue(issues)
                _write_png(good_path, 90, 160)
                return GateUnit(
                    path=good_path,
                    path_ref="storyboard/scene_fixed.png",
                    scene_id=unit.scene_id,
                    aspect_ratio="9:16",
                )

            result = run_image_gate(
                [
                    GateUnit(
                        path=bad_path,
                        path_ref="storyboard/scene.png",
                        scene_id="scn_REPAIR",
                        aspect_ratio="9:16",
                    )
                ],
                repair=repair,
                max_repairs=1,
            )
            self.assertTrue(result.passed, result.to_details())
            self.assertEqual(result.repairs_attempted, 1)
            self.assertEqual(result.units_repaired, 1)
            self.assertEqual(repair_calls, [bad_path])

    def test_repair_exhausted_still_blocks(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_gate_") as tmp:
            bad_path = _write_garbage(os.path.join(tmp, "still_bad.png"))

            def repair_noop(unit: GateUnit, issues) -> GateUnit | None:
                # Pretend repair ran but left the file broken.
                return GateUnit(
                    path=bad_path,
                    path_ref=unit.path_ref,
                    scene_id=unit.scene_id,
                )

            result = run_image_gate(
                [GateUnit(path=bad_path, path_ref="storyboard/still_bad.png")],
                repair=repair_noop,
                max_repairs=1,
            )
            self.assertFalse(result.passed)
            self.assertEqual(result.repairs_attempted, 1)


class VideoGateTests(unittest.TestCase):
    def test_missing_video_blocks_before_final_review(self):
        missing = os.path.join(
            tempfile.gettempdir(), "scriptase_gate_no_such_clip.mp4"
        )
        if os.path.exists(missing):
            os.remove(missing)
        result = run_video_gate(
            [
                GateUnit(
                    path=missing,
                    path_ref="animator/missing.mp4",
                    scene_id="scn_VID001",
                )
            ]
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.gate, "video")
        self.assertGreaterEqual(len(result.blocking_issues), 1)

    def test_units_from_video_assets(self):
        units = units_from_video_assets(
            {
                "artifact_refs": [
                    "animator/pm_X/0/clip.mp4",
                    "animator/pm_X/job.json",
                ]
            },
            aspect_ratio="9:16",
        )
        self.assertGreaterEqual(len(units), 1)
        self.assertTrue(
            any(
                (u.path_ref or "").endswith(".mp4") or "clip" in (u.path_ref or "")
                for u in units
            )
        )


class VideoProviderNeverInvokedTests(unittest.TestCase):
    """Done-when: bad source image is caught/repaired; video provider never runs
    while the image is bad — and never runs at all when the gate blocks."""

    def setUp(self):
        self.ctx = AdapterContext(project_id="pm_GATE74", node_id="n_animator")
        self.scenes = {
            "scenes": [
                {
                    "index": 0,
                    "id": "scn_GATE74",
                    "scene_id": "scn_GATE74",
                    "image_prompt": "a quiet harbor at dusk",
                    "motion_prompt": "slow pan across the water",
                }
            ]
        }

    def test_bad_image_blocks_video_provider_never_invoked(self):
        """Deliberately bad still → QUALITY_GATE_FAILED; run_manifest_job unused."""
        from config import OUTPUT_DIR

        ref = "storyboard/pm_GATE74/0/bad.png"
        abs_path = os.path.join(OUTPUT_DIR, *ref.split("/"))
        _write_garbage(abs_path)

        video_calls: list[dict] = []

        def fake_run(**kwargs):
            video_calls.append(kwargs)
            return {"total": 1, "ready": 1, "errors": 0}

        original = video_adapter.run_manifest_job
        video_adapter.run_manifest_job = fake_run
        try:
            with self.assertRaises(AdapterError) as ctx:
                video_adapter.generate(
                    {
                        "scenes": self.scenes,
                        "storyboard": {
                            "ready": 1,
                            "total": 1,
                            "artifact_refs": [ref],
                        },
                    },
                    {"provider_id": "grok_automa", "aspect_ratio": "9:16"},
                    self.ctx,
                )
            self.assertEqual(ctx.exception.code, QUALITY_GATE_FAILED)
            details = ctx.exception.details or {}
            self.assertEqual(details.get("gate"), "image")
            self.assertFalse(details.get("passed"))
            self.assertGreaterEqual(details.get("blocking_issue_count", 0), 1)
            # Proof: video provider path never entered.
            self.assertEqual(video_calls, [])
        finally:
            video_adapter.run_manifest_job = original
            try:
                os.remove(abs_path)
            except OSError:
                pass

    def test_repair_runs_before_any_video_call(self):
        """Repair callback fires while video provider is still untouched."""
        from config import OUTPUT_DIR

        ref = "storyboard/pm_GATE74/0/repair_me.png"
        abs_path = os.path.join(OUTPUT_DIR, *ref.split("/"))
        _write_garbage(abs_path)

        video_calls: list[int] = []
        repair_saw_video_idle: list[bool] = []

        def fake_run(**kwargs):
            video_calls.append(1)
            return {"total": 1, "ready": 1, "errors": 0}

        def repair(unit: GateUnit, issues) -> GateUnit:
            # Done-when proof: video must not have been invoked yet.
            repair_saw_video_idle.append(len(video_calls) == 0)
            _write_png(abs_path, 90, 160)
            return GateUnit(
                path=abs_path,
                path_ref=ref,
                scene_id=unit.scene_id,
                aspect_ratio="9:16",
            )

        original = video_adapter.run_manifest_job
        video_adapter.run_manifest_job = fake_run
        try:
            result = video_adapter.generate(
                {
                    "scenes": self.scenes,
                    "storyboard": {
                        "ready": 1,
                        "total": 1,
                        "artifact_refs": [ref],
                    },
                },
                {
                    "provider_id": "grok_automa",
                    "aspect_ratio": "9:16",
                    "image_gate_repair": repair,
                    "image_gate_max_repairs": 1,
                },
                self.ctx,
            )
            self.assertEqual(result["assets"]["ready"], 1)
            self.assertEqual(repair_saw_video_idle, [True])
            # Video runs only after repair made the still valid.
            self.assertEqual(video_calls, [1])
        finally:
            video_adapter.run_manifest_job = original
            try:
                os.remove(abs_path)
            except OSError:
                pass

    def test_retired_text_to_video_provider_never_reaches_the_image_gate(self):
        video_calls: list[int] = []

        def fake_run(**kwargs):
            video_calls.append(1)
            return {"total": 1, "ready": 1, "errors": 0}

        original = video_adapter.run_manifest_job
        video_adapter.run_manifest_job = fake_run
        try:
            with self.assertRaises(AdapterError) as caught:
                video_adapter.generate(
                    {"scenes": self.scenes},
                    {"provider_id": "kie_ai"},
                    self.ctx,
                )
            self.assertEqual(caught.exception.code, "PROVIDER_REQUEST_INVALID")
            self.assertEqual(video_calls, [])
        finally:
            video_adapter.run_manifest_job = original


class EnforceImageGateHelpersTests(unittest.TestCase):
    def test_returns_none_without_storyboard(self):
        result = enforce_image_gate_for_video(
            {"scenes": {"scenes": []}},
            {},
            AdapterContext(project_id="pm_GATE74"),
        )
        self.assertIsNone(result)

    def test_skip_quality_gate_config(self):
        result = enforce_image_gate_for_video(
            {
                "storyboard": {
                    "ready": 1,
                    "total": 1,
                    "artifact_refs": ["storyboard/x/nope.png"],
                }
            },
            {"skip_quality_gate": True},
            AdapterContext(project_id="pm_GATE74"),
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.passed)
        self.assertEqual(result.units_checked, 0)

    def test_to_details_has_no_absolute_paths(self):
        result = QualityGateResult(
            gate="image",
            passed=False,
            issues=[
                TechnicalIssue(
                    check_id="file_exists",
                    severity="critical",
                    reason="missing",
                    path_ref=r"D:\secrets\scene.png",
                    observed={"exists": False},
                    expected={"exists": True},
                )
            ],
        )
        details = result.to_details()
        blob = str(details)
        self.assertNotIn("D:\\", blob)
        self.assertNotIn("D:/", blob)


if __name__ == "__main__":
    unittest.main()
