"""Step 11.2 — ReviewIssues emitted during a real run.

Done when: a Job run against a deliberately broken artifact ends with persisted
ReviewIssues carrying target node, target artifact, severity, and confidence.

Step 11.1 registered the Review node but its findings lived and died on the
`issues` port. These tests hold the write path: persistence through
`scriptase/review/store.py`, the Job link the stage projection reads, and the
re-review rule that keeps a repair loop bounded (11.3 depends on it).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from config import OUTPUT_DIR
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_draft
from scriptase.engine.adapters import AdapterContext
from scriptase.engine.adapters import review as review_adapter
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.models import workflow_draft
from scriptase.engine.persistence import create_workflow, load_execution
from scriptase.engine.registry import get_node_type
from scriptase.jobs import store as job_store
from scriptase.jobs.orchestration import prepare_workflow_for_job, start_job
from scriptase.jobs.routes import _owning_job_id
from scriptase.jobs.stage_projection import project_stages
from scriptase.jobs.store import create_job, default_draft as job_draft
from scriptase.review import store as issue_store
from scriptase.review.emission import emit_review_issues, issue_identity
from scriptase.review.technical import TechnicalIssue

# The gate rebases any path onto the managed root, so a fixture the validators
# can actually open has to live under OUTPUT_DIR (same reason as step 11.1).
FIXTURE_REF = "storyboard/pm_REV112"
FIXTURE_ROOT = os.path.join(OUTPUT_DIR, *FIXTURE_REF.split("/"))


def _write_broken_image(name: str = "broken.png") -> str:
    """A file that exists and is readable but is not decodable media."""
    os.makedirs(FIXTURE_ROOT, exist_ok=True)
    with open(os.path.join(FIXTURE_ROOT, name), "wb") as handle:
        handle.write(b"not-a-real-image-payload")
    return f"{FIXTURE_REF}/{name}"


def _technical(**overrides) -> TechnicalIssue:
    payload = {
        "check_id": "readable_media",
        "issue_type": "technical_defect",
        "severity": "critical",
        "confidence": 1.0,
        "reason": "Image could not be decoded.",
        "suggested_action": "regenerate",
        "scene_id": "scn_BAD001",
        "target_node_id": "n_storyboard",
        "target_artifact_id": "art_BAD001",
        "observed": {"decoded": False},
        "expected": {"decoded": True},
    }
    payload.update(overrides)
    return TechnicalIssue.model_validate(payload)


class IsolatedStoresMixin(unittest.TestCase):
    """Redirect the issue and job stores at a temp root."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_emission_")
        root = self.temp.name

        self.old_issues_dir = issue_store._issues_dir
        issue_store._issues_dir = os.path.join(root, "issues")
        os.makedirs(issue_store._issues_dir, exist_ok=True)

        self.old_jobs_dir = job_store._jobs_dir
        self.old_jobs_trash = job_store._trash_dir
        job_store._jobs_dir = os.path.join(root, "jobs")
        job_store._trash_dir = os.path.join(root, "trash", "jobs")
        os.makedirs(job_store._jobs_dir, exist_ok=True)

    def tearDown(self):
        issue_store._issues_dir = self.old_issues_dir
        job_store._jobs_dir = self.old_jobs_dir
        job_store._trash_dir = self.old_jobs_trash
        self.temp.cleanup()


# ---------------------------------------------------------------------------
# The write path
# ---------------------------------------------------------------------------


class EmissionTests(IsolatedStoresMixin):
    JOB_ID = "job_EMT112"

    def setUp(self):
        super().setUp()
        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(self.temp.name, "channels")
        channel_store._trash_dir = os.path.join(self.temp.name, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        super().tearDown()

    def test_technical_findings_become_durable_review_issues(self):
        emitted = emit_review_issues(
            self.JOB_ID, technical=[_technical()], attach_to_job=False
        )
        self.assertEqual(len(emitted), 1)

        stored = issue_store.get_issue(emitted[0].id)
        self.assertEqual(stored.job_id, self.JOB_ID)
        self.assertEqual(stored.target_node_id, "n_storyboard")
        self.assertEqual(stored.target_artifact_id, "art_BAD001")
        self.assertEqual(stored.severity, "critical")
        self.assertEqual(stored.confidence, 1.0)
        self.assertEqual(stored.check_id, "readable_media")
        self.assertEqual(stored.status, "open")

    def test_semantic_findings_persist_through_the_structured_boundary(self):
        emitted = emit_review_issues(
            self.JOB_ID,
            semantic=[{
                "issue_type": "visual_mismatch",
                "severity": "medium",
                "confidence": 0.62,
                "reason": "subject drifted from the prompt",
                "suggested_action": "re-prompt",
                "scene_id": "scn_SEM001",
                "target_node_id": "n_storyboard",
                "target_artifact_id": "art_SEM001",
            }],
            attach_to_job=False,
        )
        stored = issue_store.get_issue(emitted[0].id)
        self.assertEqual(stored.issue_type, "visual_mismatch")
        self.assertEqual(stored.confidence, 0.62)
        # job_id is filled from the call even though the finding omitted it.
        self.assertEqual(stored.job_id, self.JOB_ID)

    def test_free_text_is_rejected_before_anything_is_written(self):
        with self.assertRaises(TypeError):
            emit_review_issues(
                self.JOB_ID, semantic=["the image looks wrong"], attach_to_job=False
            )
        self.assertEqual(issue_store.list_issues(job_id=self.JOB_ID), [])

    def test_emission_refuses_a_run_with_no_owning_job(self):
        with self.assertRaises(ValueError):
            emit_review_issues("", technical=[_technical()])

    def test_re_review_reuses_the_open_issue(self):
        """Otherwise every repair cycle resets attempt_count — an unbounded loop."""
        first = emit_review_issues(
            self.JOB_ID, technical=[_technical()], attach_to_job=False
        )
        issue_store.update_issue(first[0].id, attempt_count=1)

        second = emit_review_issues(
            self.JOB_ID, technical=[_technical()], attach_to_job=False
        )
        self.assertEqual([i.id for i in second], [first[0].id])
        self.assertEqual(len(issue_store.list_issues(job_id=self.JOB_ID)), 1)
        self.assertEqual(issue_store.get_issue(first[0].id).attempt_count, 1)

    def test_a_different_defect_on_the_same_scene_is_its_own_issue(self):
        emit_review_issues(self.JOB_ID, technical=[_technical()], attach_to_job=False)
        emit_review_issues(
            self.JOB_ID,
            technical=[_technical(check_id="aspect_ratio", severity="high")],
            attach_to_job=False,
        )
        self.assertEqual(len(issue_store.list_issues(job_id=self.JOB_ID)), 2)

    def test_a_defect_that_returns_after_resolution_is_new(self):
        first = emit_review_issues(
            self.JOB_ID, technical=[_technical()], attach_to_job=False
        )
        issue_store.update_issue(first[0].id, status="resolved")

        second = emit_review_issues(
            self.JOB_ID, technical=[_technical()], attach_to_job=False
        )
        self.assertNotEqual(second[0].id, first[0].id)

    def test_identity_ignores_how_severe_this_measurement_happened_to_be(self):
        self.assertEqual(
            issue_identity(_technical(severity="critical", confidence=1.0)),
            issue_identity(_technical(severity="high", confidence=0.4)),
        )

    def test_issue_ids_are_linked_onto_the_job(self):
        channel = create_channel(channel_draft(name="Emission"))
        job = create_job(job_draft(
            channel_id=channel.id,
            source={"mode": "paste", "pasted_script": "text"},
        ))
        emitted = emit_review_issues(job.id, technical=[_technical()])
        self.assertEqual(job_store.get_job(job.id).issues, [emitted[0].id])

    def test_a_missing_job_never_loses_the_issue(self):
        emitted = emit_review_issues(
            "job_GHOST1", technical=[_technical(target_node_id="n_x")]
        )
        self.assertTrue(issue_store.get_issue(emitted[0].id))


# ---------------------------------------------------------------------------
# The node only writes when a Job owns the run
# ---------------------------------------------------------------------------


class AdapterPersistenceScopeTests(IsolatedStoresMixin):
    def setUp(self):
        super().setUp()
        self.broken = _write_broken_image()

    def tearDown(self):
        shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)
        super().tearDown()

    def _run(self, context):
        return review_adapter.run(
            {"images": {"scene_statuses": {"0": {
                "scene_id": "scn_BAD001", "artifact_ref": self.broken,
            }}}},
            {"subject": "images"},
            context,
        )

    def test_a_canvas_run_reports_without_writing(self):
        """ReviewIssues are Job-keyed; a project id is not a substitute."""
        payload = self._run(
            AdapterContext(project_id="pm_REV112", node_id="n_review")
        )["issues"]
        self.assertGreaterEqual(payload["issue_count"], 1)
        self.assertEqual(payload["issue_ids"], [])
        self.assertEqual(issue_store.list_issues(), [])

    def test_a_job_run_persists_and_reports_the_ids(self):
        payload = self._run(AdapterContext(
            project_id="pm_REV112", node_id="n_review", job_id="job_ADP112"
        ))["issues"]
        self.assertEqual(len(payload["issue_ids"]), payload["issue_count"])
        for issue_id in payload["issue_ids"]:
            self.assertEqual(issue_store.get_issue(issue_id).job_id, "job_ADP112")


# ---------------------------------------------------------------------------
# Done-when: a real Job run against a deliberately broken artifact
# ---------------------------------------------------------------------------


def _review_workflow() -> dict:
    document = workflow_draft(name="Review probe")
    definition = get_node_type("review.run")
    document["nodes"] = [{
        "id": "n_review",
        "type": "review.run",
        "type_version": definition["type_version"],
        "name": definition["display_name"],
        "position": {"x": 0, "y": 0},
        "configuration": {"subject": "images", "aspect_ratio": "9:16"},
        "disabled": False,
    }]
    document["edges"] = []
    return document


class JobRunEmitsIssuesTests(IsolatedStoresMixin):
    """The done-when, driven through `start_job` rather than the adapter."""

    def setUp(self):
        super().setUp()
        root = self.temp.name

        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(root, "channels")
        channel_store._trash_dir = os.path.join(root, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)

        from scriptase.engine import persistence as workflow_persistence

        self._wf = workflow_persistence
        self.old_workflows = workflow_persistence.WORKFLOWS_DIR
        self.old_executions = workflow_persistence.EXECUTIONS_DIR
        self.run_dir = os.path.join(root, "output")
        workflow_persistence.WORKFLOWS_DIR = os.path.join(self.run_dir, "workflows")
        workflow_persistence.EXECUTIONS_DIR = os.path.join(
            self.run_dir, "workflows", "executions"
        )
        os.makedirs(workflow_persistence.EXECUTIONS_DIR, exist_ok=True)

        self.broken = _write_broken_image()
        self.workflow = create_workflow(_review_workflow())
        self.channel = create_channel(channel_draft(name="Broken art"))
        self.job = create_job(job_draft(
            channel_id=self.channel.id,
            # Automatic: Manual mode stamps an approval checkpoint and the run
            # would pause before Review ever executed.
            execution_mode="automatic",
            source={"mode": "paste", "pasted_script": "Narration."},
            workflow_id=self.workflow["workflow_id"],
        ))

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        self._wf.WORKFLOWS_DIR = self.old_workflows
        self._wf.EXECUTIONS_DIR = self.old_executions
        shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)
        super().tearDown()

    def _run_job(self):
        manager = ExecutionManager(output_dir=self.run_dir)
        return start_job(
            self.job.id,
            manager=manager,
            project_id="pm_REV112",
            force=True,
            wait=True,
            timeout=30.0,
            workflow=self.workflow,
            # These tests are about emission. Step 11.3 would take the findings
            # from here and escalate them (the graph has no Export node to
            # repair a codec defect at), which is its own done-when.
            repair=False,
            input_overrides={"n_review": {"images": {
                "total": 1, "ready": 1, "errors": 0,
                "scene_statuses": {"0": {
                    "status": "ready",
                    "scene_id": "scn_BAD001",
                    "artifact_ref": self.broken,
                }},
            }}},
        )

    def test_the_run_ends_with_persisted_issues(self):
        finished = self._run_job()
        self.assertEqual(finished.status, "completed")

        self.assertTrue(finished.issues, "Job should carry the emitted issue ids")
        issues = [issue_store.get_issue(iid) for iid in finished.issues]
        for issue in issues:
            self.assertEqual(issue.job_id, self.job.id)
            self.assertEqual(issue.target_node_id, "n_review")
            self.assertIn(issue.severity, {"low", "medium", "high", "critical"})
            self.assertGreater(issue.confidence, 0.0)
            self.assertEqual(issue.status, "open")
        self.assertTrue(
            any(issue.check_id == "readable_media" for issue in issues),
            [issue.check_id for issue in issues],
        )
        # Same set from the store's own Job filter — the ids are not a
        # write-only side channel on the Job document.
        self.assertEqual(
            {issue.id for issue in issue_store.list_issues(job_id=self.job.id)},
            set(finished.issues),
        )

    def test_the_projection_carries_the_issues_onto_the_review_stage(self):
        finished = self._run_job()
        execution = load_execution(finished.execution_id)
        snapshot = execution["workflow_snapshot"]

        self.assertEqual(_owning_job_id(snapshot), self.job.id)
        projection = project_stages(
            snapshot, execution=execution, job_id=_owning_job_id(snapshot)
        )
        review_stage = next(
            stage for stage in projection["stages"] if stage["key"] == "review"
        )
        self.assertEqual(set(review_stage["issues"]), set(finished.issues))

    def test_the_owning_job_id_reaches_the_node_context(self):
        """`extensions.job_id` is the only route from Job to adapter."""
        prepared = prepare_workflow_for_job(self.job, self.workflow)
        self.assertEqual(prepared["extensions"]["job_id"], self.job.id)


if __name__ == "__main__":
    unittest.main()
