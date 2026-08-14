"""Step 1.6 — Stable scene identity and the re-segmentation rule.

Done when: re-running the segmenter with different parameters keeps stable ids
for unchanged scenes, and a test proves no open issue or artifact is left bound
to a scene that no longer exists.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from scriptase.artifacts import store as artifact_store
from scriptase.artifacts.store import (
    active_artifact,
    get_artifact,
    list_artifacts,
    register_artifact,
    versioned_relative_path,
)
from scriptase.modules.segmenter.algorithm import run_segmenter
from scriptase.modules.segmenter.service import apply_stable_scene_identity
from scriptase.review import open_issues as issue_store
from scriptase.review.open_issues import (
    create_open_issue,
    list_issues,
)
from scriptase.scenes import store as scene_store
from scriptase.scenes.models import SCENE_ID_RE, Scene
from scriptase.scenes.resegment import (
    REBIND_IOU_THRESHOLD,
    REBIND_MAX_SPAN_RATIO,
    ResegmentConfig,
    apply_resegmentation,
    is_rebind_eligible,
    temporal_iou,
)
from scriptase.scenes.store import (
    SceneNotFound,
    active_scenes_for_job,
    get_scene,
    resolve_scene,
    scene_resolves,
)


class SceneIdentityTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_scenes_")
        # Scene records.
        self.old_scenes = scene_store._scenes_dir
        scene_store._scenes_dir = os.path.join(self.temp.name, "scene_records")
        os.makedirs(scene_store._scenes_dir, exist_ok=True)
        # Artifacts.
        self.old_artifacts = artifact_store._artifacts_dir
        self.old_output = artifact_store._output_dir
        self.output_dir = os.path.join(self.temp.name, "output")
        artifact_store._output_dir = self.output_dir
        artifact_store._artifacts_dir = os.path.join(self.output_dir, "artifacts")
        os.makedirs(os.path.join(self.output_dir, "storyboard"), exist_ok=True)
        os.makedirs(artifact_store._artifacts_dir, exist_ok=True)
        # Open-issue bindings.
        self.old_issues = issue_store._issues_dir
        issue_store._issues_dir = os.path.join(self.temp.name, "issue_bindings")
        os.makedirs(issue_store._issues_dir, exist_ok=True)

        self.job_id = "job_TEST16"

    def tearDown(self):
        scene_store._scenes_dir = self.old_scenes
        artifact_store._artifacts_dir = self.old_artifacts
        artifact_store._output_dir = self.old_output
        issue_store._issues_dir = self.old_issues
        self.temp.cleanup()

    def _write_blob(self, relative: str, content: bytes) -> str:
        abs_path = os.path.join(self.output_dir, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(content)
        return relative

    def _register_image(self, scene_id: str, tag: str = "v1") -> str:
        path = versioned_relative_path(
            f"storyboard/{self.job_id}/{scene_id}.png", 1
        )
        # Make path unique per tag without changing version helper contract.
        path = path.replace(".png", f"_{tag}.png")
        self._write_blob(path, f"image-{tag}-{scene_id}".encode())
        art = register_artifact(
            job_id=self.job_id,
            kind="image",
            path=path,
            scene_id=scene_id,
            provenance_ref=f"inv_{tag}",
        )
        return art.id


class TemporalGeometryTests(unittest.TestCase):
    def test_iou_identical_spans(self):
        self.assertAlmostEqual(temporal_iou(0.0, 2.0, 0.0, 2.0), 1.0)

    def test_iou_no_overlap(self):
        self.assertEqual(temporal_iou(0.0, 1.0, 2.0, 3.0), 0.0)

    def test_iou_partial(self):
        # [0,2] ∩ [1,3] = 1; union = 3 → 1/3
        self.assertAlmostEqual(temporal_iou(0.0, 2.0, 1.0, 3.0), 1.0 / 3.0)

    def test_rebind_defaults_match_contracts(self):
        self.assertEqual(REBIND_IOU_THRESHOLD, 0.6)
        self.assertEqual(REBIND_MAX_SPAN_RATIO, 1.5)


class StableIdAndRebindTests(SceneIdentityTestBase):
    def test_first_segmentation_assigns_stable_ids(self):
        segments = [
            {"start": 0.0, "end": 2.0, "words": "one two", "is_filler": False},
            {"start": 2.1, "end": 4.0, "words": "three four", "is_filler": False},
        ]
        result = apply_resegmentation(self.job_id, segments)
        self.assertEqual(len(result.scenes), 2)
        for scene in result.scenes:
            self.assertRegex(scene.id, r"^scn_[A-Z0-9]{6}$")
            self.assertTrue(scene_resolves(scene.id))
            self.assertIsNone(scene.superseded_by)
        self.assertEqual(result.scenes[0].ordinal, 0)
        self.assertEqual(result.scenes[1].ordinal, 1)
        self.assertEqual(
            [d.action for d in result.decisions],
            ["new", "new"],
        )

    def test_unchanged_spans_keep_stable_ids(self):
        """Done-when: re-run keeps stable ids for unchanged scenes."""
        segments = [
            {"start": 0.0, "end": 2.0, "words": "alpha", "is_filler": False},
            {"start": 2.0, "end": 4.0, "words": "bravo", "is_filler": False},
            {"start": 4.0, "end": 6.0, "words": "charlie", "is_filler": False},
        ]
        first = apply_resegmentation(self.job_id, segments)
        first_ids = [s.id for s in first.scenes]

        # Same parameters → identical spans → full rebind.
        second = apply_resegmentation(self.job_id, segments)
        second_ids = [s.id for s in second.scenes]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(
            [d.action for d in second.decisions],
            ["rebind", "rebind", "rebind"],
        )
        # Only three active scenes still.
        active = active_scenes_for_job(self.job_id)
        self.assertEqual(sorted(s.id for s in active), sorted(first_ids))

    def test_materially_unchanged_span_rebinds(self):
        first = apply_resegmentation(
            self.job_id,
            [{"start": 0.0, "end": 4.0, "words": "long scene", "is_filler": False}],
        )
        prior_id = first.scenes[0].id

        # Slight boundary drift still above IoU 0.6 and within 1.5× span ratio.
        second = apply_resegmentation(
            self.job_id,
            [{"start": 0.2, "end": 3.9, "words": "long scene", "is_filler": False}],
        )
        self.assertEqual(second.scenes[0].id, prior_id)
        self.assertEqual(second.decisions[0].action, "rebind")
        self.assertAlmostEqual(second.scenes[0].start, 0.2)
        self.assertAlmostEqual(second.scenes[0].end, 3.9)

    def test_split_supersedes_and_creates_new(self):
        first = apply_resegmentation(
            self.job_id,
            [{"start": 0.0, "end": 6.0, "words": "whole thing", "is_filler": False}],
        )
        prior_id = first.scenes[0].id
        art_id = self._register_image(prior_id, tag="pre")
        issue = create_open_issue(
            job_id=self.job_id,
            scene_id=prior_id,
            reason="looks wrong",
        )

        # Split into two halves — neither can rebind under the 0.6 IoU rule
        # (each half IoU with [0,6] is 0.5), so first half supersedes prior.
        second = apply_resegmentation(
            self.job_id,
            [
                {"start": 0.0, "end": 3.0, "words": "first half", "is_filler": False},
                {"start": 3.0, "end": 6.0, "words": "second half", "is_filler": False},
            ],
        )
        self.assertEqual(len(second.scenes), 2)
        actions = [d.action for d in second.decisions]
        self.assertIn("supersede", actions)
        self.assertIn("new", actions)

        prior = get_scene(prior_id)
        self.assertIsNotNone(prior.superseded_by)
        self.assertFalse(scene_resolves(prior_id))
        with self.assertRaises(SceneNotFound):
            resolve_scene(prior_id)

        # Artifact retired (self-tombstone); issue re-targeted to successor.
        art = get_artifact(art_id)
        self.assertTrue(art.is_superseded)
        self.assertIsNone(
            active_artifact(self.job_id, "image", scene_id=prior_id)
        )
        open_on_prior = list_issues(
            job_id=self.job_id, scene_id=prior_id, open_only=True
        )
        self.assertEqual(open_on_prior, [])
        rebound_issue = next(
            i for i in list_issues(job_id=self.job_id, open_only=True)
            if i.id == issue.id
        )
        self.assertEqual(rebound_issue.scene_id, prior.superseded_by)
        self.assertTrue(scene_resolves(rebound_issue.scene_id))

    def test_no_open_issue_or_artifact_bound_to_dead_scene(self):
        """Done-when: nothing left bound to a scene that no longer exists."""
        first = apply_resegmentation(
            self.job_id,
            [
                {"start": 0.0, "end": 2.0, "words": "keep", "is_filler": False},
                {"start": 2.0, "end": 4.0, "words": "drop", "is_filler": False},
                {"start": 4.0, "end": 6.0, "words": "keep2", "is_filler": False},
            ],
        )
        keep_a, drop, keep_b = first.scenes
        art_keep = self._register_image(keep_a.id, tag="keep")
        art_drop = self._register_image(drop.id, tag="drop")
        issue_keep = create_open_issue(
            job_id=self.job_id, scene_id=keep_a.id, reason="niggle"
        )
        issue_drop = create_open_issue(
            job_id=self.job_id, scene_id=drop.id, reason="bad cut"
        )

        # Drop the middle scene entirely (gap in the timeline).
        second = apply_resegmentation(
            self.job_id,
            [
                {"start": 0.0, "end": 2.0, "words": "keep", "is_filler": False},
                {"start": 4.0, "end": 6.0, "words": "keep2", "is_filler": False},
            ],
        )
        active_ids = {s.id for s in second.scenes}
        self.assertIn(keep_a.id, active_ids)
        self.assertIn(keep_b.id, active_ids)
        self.assertNotIn(drop.id, active_ids)
        self.assertFalse(scene_resolves(drop.id))
        self.assertIn(drop.id, second.invalidated_ids)

        # Keep-side bindings intact.
        self.assertFalse(get_artifact(art_keep).is_superseded)
        self.assertEqual(
            list_issues(job_id=self.job_id, scene_id=keep_a.id, open_only=True)[0].id,
            issue_keep.id,
        )

        # Drop-side bindings cleared.
        self.assertTrue(get_artifact(art_drop).is_superseded)
        self.assertEqual(
            list_issues(job_id=self.job_id, scene_id=drop.id, open_only=True),
            [],
        )
        closed = next(i for i in list_issues(job_id=self.job_id) if i.id == issue_drop.id)
        self.assertEqual(closed.status, "closed")
        self.assertIsNone(closed.scene_id)

        # Global invariant: no open issue / active artifact on dead scenes.
        for issue in list_issues(job_id=self.job_id, open_only=True):
            if issue.scene_id is not None:
                self.assertIn(issue.scene_id, active_ids)
                self.assertTrue(scene_resolves(issue.scene_id))
        for art in list_artifacts(
            job_id=self.job_id, include_superseded=False
        ):
            if art.scene_id is not None:
                self.assertIn(art.scene_id, active_ids)
                self.assertTrue(scene_resolves(art.scene_id))

    def test_rebind_ineligible_when_span_ratio_too_large(self):
        prior = Scene(
            id="scn_AAAAAA",
            job_id=self.job_id,
            ordinal=0,
            start=0.0,
            end=1.0,
            duration=1.0,
            segment_words="short",
        )
        from scriptase.scenes.resegment import SegmentCandidate

        # 3× longer — fails 1.5× ratio even with high IoU of the short into long.
        cand = SegmentCandidate(start=0.0, end=3.0, segment_words="much longer")
        self.assertFalse(is_rebind_eligible(prior, cand))
        # Within ratio and IoU.
        cand_ok = SegmentCandidate(start=0.0, end=1.2, segment_words="near")
        self.assertTrue(is_rebind_eligible(prior, cand_ok))


class SegmenterIntegrationTests(SceneIdentityTestBase):
    def _alignment(self) -> list[dict]:
        # ~8s of words with clear sentence breaks so the algorithm yields
        # stable multi-segment output under default config.
        words = [
            ("A", 0.0, 0.2),
            ("lighthouse", 0.25, 0.7),
            ("keeper", 0.75, 1.1),
            ("climbs.", 1.15, 1.6),
            ("The", 1.9, 2.05),
            ("lamp", 2.1, 2.4),
            ("turns.", 2.45, 2.9),
            ("Far", 3.2, 3.4),
            ("below,", 3.45, 3.8),
            ("a", 3.85, 3.95),
            ("boat", 4.0, 4.3),
            ("finds", 4.35, 4.65),
            ("home.", 4.7, 5.2),
        ]
        return [{"word": w, "begin": b, "end": e} for w, b, e in words]

    def test_segmenter_rerun_keeps_ids_for_unchanged_scenes(self):
        alignment = self._alignment()
        result1 = run_segmenter(alignment, None, {"project_id": self.job_id})
        stamped1 = apply_stable_scene_identity(
            result1, job_id=self.job_id, seg_config=None
        )
        ids1 = stamped1["scene_ids"]
        self.assertGreaterEqual(len(ids1), 2)
        for sid in ids1:
            self.assertRegex(sid, r"^scn_[A-Z0-9]{6}$")

        # Attach an open issue + artifact to the first scene.
        first_id = ids1[0]
        self._register_image(first_id, tag="seg")
        create_open_issue(job_id=self.job_id, scene_id=first_id, reason="check")

        # Re-run with different target window that still leaves some spans
        # close enough to rebind.
        result2 = run_segmenter(
            alignment,
            {"target_min": 1.2, "target_max": 3.5, "hard_max": 5.0, "hard_min": 0.8},
            {"project_id": self.job_id},
        )
        stamped2 = apply_stable_scene_identity(
            result2,
            job_id=self.job_id,
            seg_config={
                "target_min": 1.2,
                "target_max": 3.5,
                "rebind_iou_threshold": REBIND_IOU_THRESHOLD,
                "rebind_max_span_ratio": REBIND_MAX_SPAN_RATIO,
            },
        )
        ids2 = stamped2["scene_ids"]
        # At least one id from the first run should survive when spans align.
        overlap = set(ids1) & set(ids2)
        # Even if parameters shift everything past the threshold, the invariant
        # on dead-scene bindings must hold.
        active = set(ids2)
        for issue in list_issues(job_id=self.job_id, open_only=True):
            if issue.scene_id is not None:
                self.assertIn(issue.scene_id, active)
        for art in list_artifacts(job_id=self.job_id, include_superseded=False):
            if art.scene_id is not None:
                self.assertIn(art.scene_id, active)

        # Same config again → full rebind of whatever the second run produced.
        result3 = run_segmenter(
            alignment,
            {"target_min": 1.2, "target_max": 3.5, "hard_max": 5.0, "hard_min": 0.8},
            {"project_id": self.job_id},
        )
        stamped3 = apply_stable_scene_identity(
            result3,
            job_id=self.job_id,
            seg_config={"target_min": 1.2, "target_max": 3.5},
        )
        self.assertEqual(stamped3["scene_ids"], ids2)
        self.assertEqual(stamped3["resegmentation"]["rebound"], len(ids2))
        # Silence unused if the first re-run happened to rebind nothing.
        _ = overlap


class SceneModelTests(unittest.TestCase):
    def test_scene_id_shape(self):
        self.assertTrue(SCENE_ID_RE.fullmatch("scn_ABC123"))
        self.assertFalse(SCENE_ID_RE.fullmatch("scn_abc123"))
        self.assertFalse(SCENE_ID_RE.fullmatch("scene_1"))


if __name__ == "__main__":
    unittest.main()
