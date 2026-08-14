"""Step 7.2 — ReviewIssue schema and store.

Done when: review returns only structured issues, enforced by a schema test
that rejects a free-text result.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from pydantic import ValidationError

from scriptase.review import store as issue_store
from scriptase.review.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.review.models import (
    ISSUE_SCHEMA_VERSION,
    ISSUE_TYPES,
    ReviewIssue,
    ReviewIssueDraft,
    assert_structured_review_result,
    parse_issue,
    technical_to_draft,
    validation_problems,
)
from scriptase.review.store import (
    IssueNotFound,
    IssueValidationError,
    close_issues_for_scene,
    create_from_review_result,
    create_from_technical,
    create_open_issue,
    create_review_issue,
    get_issue,
    list_issues,
    retarget_issues,
    update_issue,
)
from scriptase.review.technical import TechnicalIssue


class ReviewIssueStoreTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_issues_")
        self.old_dir = issue_store._issues_dir
        issue_store._issues_dir = os.path.join(self.temp.name, "issues")
        os.makedirs(issue_store._issues_dir, exist_ok=True)

    def tearDown(self):
        issue_store._issues_dir = self.old_dir
        self.temp.cleanup()

    def _structured_draft(self, **overrides) -> dict:
        payload = {
            "job_id": "job_TEST72",
            "scene_id": "scn_AAAAAA",
            "target_node_id": "node_image_1",
            "target_artifact_id": "art_AAAAAA",
            "issue_type": "visual_mismatch",
            "severity": "high",
            "confidence": 0.91,
            "reason": "Subject wardrobe does not match the SceneSpec.",
            "suggested_action": "regenerate",
            "repair_instruction": "Keep framing and lighting; fix wardrobe colour to navy.",
            "attempt_count": 0,
            "status": "open",
            "observed": {"wardrobe": "red"},
            "expected": {"wardrobe": "navy"},
        }
        payload.update(overrides)
        return payload


class FreeTextRejectionTests(ReviewIssueStoreTestBase):
    """Done-when: schema rejects free-text review results."""

    def test_assert_rejects_plain_string_result(self):
        with self.assertRaises(TypeError) as ctx:
            assert_structured_review_result("looks bad, please regenerate everything")
        self.assertIn("free-text", str(ctx.exception).lower())

    def test_assert_rejects_list_of_strings(self):
        with self.assertRaises(TypeError):
            assert_structured_review_result(["motion is wobbly"])

    def test_assert_rejects_envelope_with_string_issues(self):
        with self.assertRaises(TypeError):
            assert_structured_review_result({"issues": "everything failed"})

    def test_assert_rejects_missing_structured_fields(self):
        with self.assertRaises(ValidationError):
            assert_structured_review_result(
                [{"reason": "bad still", "message": "free form only"}]
            )

    def test_assert_rejects_reason_only_dict(self):
        with self.assertRaises(ValidationError):
            assert_structured_review_result(
                [
                    {
                        "job_id": "job_TEST72",
                        "reason": "just a sentence, no machine fields",
                    }
                ]
            )

    def test_create_from_review_result_rejects_free_text(self):
        with self.assertRaises(TypeError):
            create_from_review_result("the video is blurry")
        self.assertEqual(list_issues(job_id="job_TEST72"), [])

    def test_create_rejects_incomplete_draft(self):
        with self.assertRaises(IssueValidationError) as ctx:
            create_review_issue({"job_id": "job_TEST72", "reason": "incomplete"})
        problems = ctx.exception.problems
        self.assertTrue(problems)
        locs = {".".join(str(p) for p in item.get("loc", ())) for item in problems}
        self.assertTrue(
            any("issue_type" in loc or "severity" in loc for loc in locs),
            f"expected structured-field errors, got {problems}",
        )

    def test_structured_envelope_is_accepted_and_persisted(self):
        created = create_from_review_result(
            {
                "status": "succeeded",
                "issues": [self._structured_draft()],
            },
            job_id="job_TEST72",
        )
        self.assertEqual(len(created), 1)
        issue = created[0]
        self.assertRegex(issue.id, r"^iss_[A-Z0-9]{6}$")
        self.assertEqual(issue.issue_type, "visual_mismatch")
        self.assertEqual(issue.severity, "high")
        self.assertAlmostEqual(issue.confidence, 0.91)
        self.assertEqual(issue.suggested_action, "regenerate")
        self.assertEqual(issue.target_node_id, "node_image_1")
        self.assertEqual(issue.target_artifact_id, "art_AAAAAA")
        self.assertEqual(issue.scene_id, "scn_AAAAAA")
        self.assertEqual(issue.status, "open")
        self.assertEqual(issue.schema_version, ISSUE_SCHEMA_VERSION)

        reloaded = get_issue(issue.id)
        self.assertEqual(reloaded.to_document(), issue.to_document())


class SchemaAndStoreTests(ReviewIssueStoreTestBase):
    def test_create_and_reload_full_schema(self):
        issue = create_review_issue(self._structured_draft())
        path = os.path.join(issue_store._issues_dir, f"{issue.id}.json")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(raw["schema_version"], SCHEMA_VERSION)
        for field in (
            "target_node_id",
            "target_artifact_id",
            "issue_type",
            "severity",
            "confidence",
            "reason",
            "suggested_action",
            "repair_instruction",
            "attempt_count",
            "status",
            "created_at",
        ):
            self.assertIn(field, raw)

        parsed = parse_issue(raw)
        self.assertIsInstance(parsed, ReviewIssue)
        self.assertEqual(parsed.id, issue.id)

    def test_all_issue_types_round_trip(self):
        for issue_type in ISSUE_TYPES:
            issue = create_review_issue(
                self._structured_draft(
                    issue_type=issue_type,
                    reason=f"Fixture for {issue_type}",
                )
            )
            self.assertEqual(get_issue(issue.id).issue_type, issue_type)

    def test_open_issue_compat_creates_full_document(self):
        issue = create_open_issue(
            job_id="job_TEST72",
            scene_id="scn_BBBBBB",
            reason="looks wrong",
        )
        self.assertEqual(issue.issue_type, "technical_defect")
        self.assertEqual(issue.severity, "medium")
        self.assertEqual(issue.scene_id, "scn_BBBBBB")
        self.assertTrue(issue.is_open)
        self.assertEqual(issue.schema_version, ISSUE_SCHEMA_VERSION)

    def test_retarget_and_close_keep_structured_fields(self):
        issue = create_open_issue(
            job_id="job_TEST72",
            scene_id="scn_OLD001",
            reason="motion defect",
        )
        retargeted = retarget_issues("job_TEST72", "scn_OLD001", "scn_NEW001")
        self.assertEqual(len(retargeted), 1)
        self.assertEqual(retargeted[0].scene_id, "scn_NEW001")
        self.assertEqual(retargeted[0].issue_type, "technical_defect")
        self.assertIn("retargeted", retargeted[0].reason)

        issue2 = create_open_issue(
            job_id="job_TEST72",
            scene_id="scn_DROP01",
            reason="dead scene",
        )
        closed = close_issues_for_scene("job_TEST72", "scn_DROP01")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0].status, "closed")
        self.assertIsNone(closed[0].scene_id)
        self.assertIsNotNone(closed[0].resolved_at)
        self.assertEqual(get_issue(issue2.id).status, "closed")

    def test_update_status_and_attempt_count(self):
        issue = create_review_issue(self._structured_draft())
        repairing = update_issue(issue.id, status="repairing", attempt_count=1)
        self.assertEqual(repairing.status, "repairing")
        self.assertEqual(repairing.attempt_count, 1)
        self.assertIsNone(repairing.resolved_at)

        resolved = update_issue(issue.id, status="resolved")
        self.assertEqual(resolved.status, "resolved")
        self.assertIsNotNone(resolved.resolved_at)

    def test_list_filters(self):
        a = create_review_issue(self._structured_draft(scene_id="scn_A1A1A1"))
        b = create_review_issue(
            self._structured_draft(
                scene_id="scn_B2B2B2",
                target_node_id="node_video_1",
                issue_type="motion_defect",
            )
        )
        update_issue(b.id, status="resolved")

        open_only = list_issues(job_id="job_TEST72", open_only=True)
        self.assertEqual([i.id for i in open_only], [a.id])
        by_scene = list_issues(job_id="job_TEST72", scene_id="scn_B2B2B2")
        self.assertEqual(len(by_scene), 1)
        self.assertEqual(by_scene[0].id, b.id)

    def test_missing_issue_raises(self):
        with self.assertRaises(IssueNotFound) as ctx:
            get_issue("iss_ZZZZZZ")
        self.assertEqual(ctx.exception.code, "ISSUE_NOT_FOUND")

    def test_technical_issue_persists_as_review_issue(self):
        technical = TechnicalIssue(
            check_id="resolution",
            severity="high",
            confidence=1.0,
            reason="Media resolution does not match expectation.",
            suggested_action="regenerate",
            repair_instruction="Regenerate at 1080x1920.",
            target_node_id="node_image_1",
            target_artifact_id="art_CCCCCC",
            scene_id="scn_CCCCCC",
            observed={"width": 640, "height": 480},
            expected={"width": 1080, "height": 1920},
        )
        draft = technical_to_draft(technical, job_id="job_TEST72")
        self.assertIsInstance(draft, ReviewIssueDraft)
        self.assertEqual(draft.issue_type, "technical_defect")
        self.assertEqual(draft.check_id, "resolution")

        created = create_from_technical("job_TEST72", [technical])
        self.assertEqual(len(created), 1)
        issue = created[0]
        self.assertEqual(issue.check_id, "resolution")
        self.assertEqual(issue.observed["width"], 640)
        self.assertEqual(issue.expected["height"], 1920)
        self.assertEqual(issue.target_artifact_id, "art_CCCCCC")


class MigrationTests(ReviewIssueStoreTestBase):
    def test_thin_v1_binding_migrates_to_full_schema(self):
        issue_id = "iss_MIG001"
        v1 = {
            "id": issue_id,
            "schema_version": 1,
            "job_id": "job_TEST72",
            "scene_id": "scn_MIG001",
            "status": "open",
            "reason": "legacy binding",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        path = os.path.join(issue_store._issues_dir, f"{issue_id}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(v1, handle)

        migrated, changed = apply_migrations(v1)
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["issue_type"], "technical_defect")
        self.assertNotIn("updated_at", migrated)

        loaded = get_issue(issue_id)
        self.assertEqual(loaded.schema_version, 2)
        self.assertEqual(loaded.issue_type, "technical_defect")
        self.assertEqual(loaded.reason, "legacy binding")
        self.assertTrue(loaded.is_open)
        # Migration rewrite is durable.
        with open(path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["schema_version"], 2)

    def test_validation_problems_are_structured(self):
        try:
            ReviewIssue.model_validate({"id": "bad", "job_id": "x"})
        except ValidationError as exc:
            problems = validation_problems(exc)
            self.assertTrue(problems)
            self.assertIn("loc", problems[0])
            self.assertIn("msg", problems[0])
        else:
            self.fail("expected ValidationError")


if __name__ == "__main__":
    unittest.main()
