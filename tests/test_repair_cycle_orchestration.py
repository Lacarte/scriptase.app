"""Step 11.3 — the Repair Router fires from job orchestration.

Done when: a bad scene image is repaired at the responsible node only,
re-reviewed, and the Job continues; and an issue that exceeds ``max_repairs``
escalates instead of looping.

Escalation is proved first, deliberately. This step introduces re-execution
into a path that had never re-executed, and a cycle that cannot stop is worse
than one that cannot start.
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib

from scriptase.artifacts import store as artifact_store
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_draft
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.models import workflow_draft
from scriptase.engine.persistence import create_workflow
from scriptase.engine.registry import get_node_type
from scriptase.jobs import store as job_store
from scriptase.jobs.orchestration import (
    review_node_ids,
    run_job_repair_cycles,
    start_job,
    workflow_for_repair,
)
from scriptase.jobs.store import create_job, default_draft as job_draft, get_job
from scriptase.review import store as issue_store
from scriptase.review.history import list_repair_history

SCENE_ID = "scn_R11301"
PROJECT_ID = "pm_RPR113"


def _png(width: int, height: int) -> bytes:
    """A real, decodable PNG of the requested shape.

    The defect under repair is a still generated at the wrong aspect ratio —
    the `aspect_ratio` validator owns it and the §12.2 table routes that to the
    Storyboard node, which is the whole point of the exercise. A corrupt file
    would route to Export instead (`readable_media` → render/codec).
    """
    scanlines = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# Probe graph: sample scenes → Storyboard → Review
# ---------------------------------------------------------------------------


def _node(node_id: str, type_key: str, x: int, configuration: dict) -> dict:
    definition = get_node_type(type_key)
    return {
        "id": node_id,
        "type": type_key,
        "type_version": definition["type_version"],
        "name": definition["display_name"],
        "position": {"x": x, "y": 0},
        "configuration": configuration,
        "disabled": False,
    }


def _edge(edge_id: str, source: str, source_port: str, target: str, target_port: str) -> dict:
    return {
        "id": edge_id,
        "source_node": source,
        "source_port": source_port,
        "target_node": target,
        "target_port": target_port,
        "edge_type": "data",
    }


def _probe_workflow() -> dict:
    document = workflow_draft(name="Repair probe")
    document["nodes"] = [
        _node("n_scenes", "stub.input", 0, {
            "port_type": "scenes",
            "payload": {"scenes": [
                {"index": 0, "id": SCENE_ID, "image_prompt": "a lighthouse"},
            ]},
        }),
        _node("n_images", "storyboard.generate", 240, {"aspect_ratio": "9:16"}),
        _node("n_review", "review.run", 480, {
            "subject": "images", "aspect_ratio": "9:16",
        }),
    ]
    document["edges"] = [
        _edge("e1", "n_scenes", "value", "n_images", "scenes"),
        _edge("e2", "n_images", "images", "n_review", "images"),
        _edge("e3", "n_scenes", "value", "n_review", "scenes"),
    ]
    return document


class _StubPipeline:
    """Executors for the probe graph, with a Storyboard that ships a bad still.

    ``fix_after`` is how many runs of the image node it takes before the still
    comes out at the expected 9:16. ``None`` means it never does — the
    escalation case.
    """

    def __init__(self, output_dir: str, *, fix_after: int | None):
        self.output_dir = output_dir
        self.fix_after = fix_after
        self.scene_runs = 0
        self.image_runs = 0
        self.review_runs = 0

    def __call__(self, node):
        node_type = node.get("type")
        if node_type == "stub.input":
            return self._scenes
        if node_type == "storyboard.generate":
            return self._images
        if node_type == "review.run":
            return self._review
        raise AssertionError(f"unexpected node type in the probe graph: {node_type}")

    def _scenes(self, inputs, config, context):
        self.scene_runs += 1
        return {"value": dict(config.get("payload") or {})}

    def _images(self, inputs, config, context):
        self.image_runs += 1
        correct = self.fix_after is not None and self.image_runs > self.fix_after
        project = getattr(context, "project_id", None) or PROJECT_ID
        relative = f"storyboard/{project}/{SCENE_ID}.png"
        path = os.path.join(self.output_dir, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            # Square instead of 9:16 until the repair lands.
            handle.write(_png(90, 160) if correct else _png(64, 64))
        return {
            "control": {"ok": True},
            "images": {
                "total": 1,
                "ready": 1,
                "errors": 0,
                "artifact_refs": [relative],
                "scene_statuses": {
                    "0": {
                        "status": "ready",
                        "scene_id": SCENE_ID,
                        "artifact_ref": relative,
                    }
                },
            },
        }

    def _review(self, inputs, config, context):
        from scriptase.engine.adapters import review as review_adapter

        self.review_runs += 1
        return review_adapter.run(inputs, config, context)


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


class _IsolatedRun(unittest.TestCase):
    """Every store and engine root under one temp directory."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_repair_")
        root = self.temp.name

        from scriptase.engine import persistence as workflow_persistence
        from scriptase.review import gates as review_gates
        from scriptase.review import history as repair_history

        self.old_issues = issue_store._issues_dir
        issue_store._issues_dir = os.path.join(root, "issues")

        self.old_jobs = job_store._jobs_dir
        self.old_job_trash = job_store._trash_dir
        job_store._jobs_dir = os.path.join(root, "jobs")
        job_store._trash_dir = os.path.join(root, "trash", "jobs")

        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(root, "channels")
        channel_store._trash_dir = os.path.join(root, "trash", "channels")

        self._wf = workflow_persistence
        self.old_workflows = workflow_persistence.WORKFLOWS_DIR
        self.old_executions = workflow_persistence.EXECUTIONS_DIR
        self.run_dir = os.path.join(root, "output")
        workflow_persistence.WORKFLOWS_DIR = os.path.join(self.run_dir, "workflows")
        workflow_persistence.EXECUTIONS_DIR = os.path.join(
            self.run_dir, "workflows", "executions"
        )

        self._history = repair_history
        self.old_history = repair_history._history_dir
        repair_history._history_dir = os.path.join(root, "repair_history")

        self.old_artifacts = artifact_store._artifacts_dir
        artifact_store._artifacts_dir = os.path.join(root, "artifacts")

        # The validators rebase every artifact_ref onto the managed root while
        # the node cache checks artifact integrity against the engine's output
        # dir. Point both at the same temp root or a still that is genuinely
        # unchanged reads as a cache miss and the repair looks unbounded.
        self._gates = review_gates
        self.old_gate_root = review_gates.OUTPUT_DIR
        review_gates.OUTPUT_DIR = self.run_dir

        for path in (
            issue_store._issues_dir,
            job_store._jobs_dir,
            channel_store._channels_dir,
            workflow_persistence.EXECUTIONS_DIR,
            repair_history._history_dir,
            artifact_store._artifacts_dir,
        ):
            os.makedirs(path, exist_ok=True)

        os.makedirs(self.run_dir, exist_ok=True)
        self.projects: list[str] = []
        self.workflow = create_workflow(_probe_workflow())

    def tearDown(self):
        issue_store._issues_dir = self.old_issues
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        self._wf.WORKFLOWS_DIR = self.old_workflows
        self._wf.EXECUTIONS_DIR = self.old_executions
        self._history._history_dir = self.old_history
        artifact_store._artifacts_dir = self.old_artifacts
        self._gates.OUTPUT_DIR = self.old_gate_root
        self.temp.cleanup()

    # -- helpers ------------------------------------------------------------

    def _job(self, *, max_repairs: int = 2, max_generations: int | None = None):
        draft = channel_draft(name=f"Repair {max_repairs}/{max_generations}")
        draft["review_policy"] = {
            "thresholds": {},
            "max_repairs": max_repairs,
            "escalation": "human",
            "human_checkpoints": [],
        }
        if max_generations is not None:
            draft["budget"] = {
                "max_generations": max_generations,
                "max_cost": None,
                "currency": "USD",
            }
        channel = create_channel(draft)
        return create_job(job_draft(
            channel_id=channel.id,
            # Automatic: Manual stamps an approval checkpoint and the run would
            # pause before Review ever executed.
            execution_mode="automatic",
            source={"mode": "paste", "pasted_script": "Narration."},
            workflow_id=self.workflow["workflow_id"],
        ))

    def _manager(self, pipeline):
        return ExecutionManager(
            output_dir=self.run_dir, executor_resolver=pipeline
        )

    def _project(self) -> str:
        # A distinct project per run: the node cache is keyed by it, so two
        # runs in one test would otherwise be pure cache hits.
        project = f"pm_RPR{len(self.projects) + 1:03d}"
        self.projects.append(project)
        return project

    def _run(self, *, fix_after: int | None, max_repairs: int = 2, repair: bool = True):
        job = self._job(max_repairs=max_repairs)
        pipeline = _StubPipeline(self.run_dir, fix_after=fix_after)
        finished = start_job(
            job.id,
            manager=self._manager(pipeline),
            project_id=self._project(),
            wait=True,
            timeout=60.0,
            workflow=self.workflow,
            repair=repair,
        )
        return finished, pipeline


# ---------------------------------------------------------------------------
# The bound comes first
# ---------------------------------------------------------------------------


class EscalationBoundTests(_IsolatedRun):
    def test_an_issue_that_exceeds_max_repairs_escalates_instead_of_looping(self):
        max_repairs = 2
        finished, pipeline = self._run(fix_after=None, max_repairs=max_repairs)

        issues = issue_store.list_issues(job_id=finished.id)
        self.assertTrue(issues, "the broken still should have produced an issue")
        self.assertTrue(
            any(issue.status == "escalated" for issue in issues),
            [(issue.id, issue.status, issue.attempt_count) for issue in issues],
        )
        self.assertFalse(
            [issue for issue in issues if issue.status in {"open", "repairing"}],
            "no issue may be left open once the cycle stops",
        )

        # Bounded: the original run plus at most one attempt per allowed repair.
        self.assertGreater(pipeline.image_runs, 1, "at least one repair was tried")
        self.assertLessEqual(pipeline.image_runs, 1 + max_repairs)

        # The Job stopped for a human rather than quietly reporting success.
        self.assertEqual(finished.status, "awaiting_approval")

    def test_a_lower_ceiling_means_strictly_fewer_provider_calls(self):
        _strict, strict_pipeline = self._run(fix_after=None, max_repairs=1)
        _loose, loose_pipeline = self._run(fix_after=None, max_repairs=3)
        self.assertLess(strict_pipeline.image_runs, loose_pipeline.image_runs)

    def test_max_repairs_zero_never_re_executes(self):
        finished, pipeline = self._run(fix_after=None, max_repairs=0)
        self.assertEqual(pipeline.image_runs, 1)
        self.assertTrue(issue_store.list_issues(job_id=finished.id))

    def test_a_job_at_its_generation_ceiling_refuses_before_calling_a_provider(self):
        job = self._job(max_repairs=3, max_generations=1)
        pipeline = _StubPipeline(self.run_dir, fix_after=None)
        manager = self._manager(pipeline)
        start_job(
            job.id,
            manager=manager,
            project_id=self._project(),
            wait=True,
            timeout=60.0,
            workflow=self.workflow,
            repair=False,
        )
        runs_before = pipeline.image_runs
        # The run consumed the Job's single allowed generation.
        job_store.update_job(
            job.id,
            budget_spent={"generations": 1, "cost": 0.0},
            allow_terminal=True,
        )

        outcome = run_job_repair_cycles(job.id, manager=manager, timeout=60.0)
        self.assertEqual(outcome["stop_reason"], "budget")
        self.assertEqual(
            pipeline.image_runs, runs_before, "no provider ran past the ceiling"
        )
        self.assertEqual(get_job(job.id).status_reason, "budget")


# ---------------------------------------------------------------------------
# Then the repair
# ---------------------------------------------------------------------------


class TargetedRepairTests(_IsolatedRun):
    def test_a_bad_still_is_repaired_at_the_responsible_node_and_the_job_continues(self):
        finished, pipeline = self._run(fix_after=1, max_repairs=3)

        # Repaired at the responsible node only: Storyboard re-ran, its
        # upstream was reused from the cache rather than regenerated.
        self.assertEqual(pipeline.image_runs, 2)
        self.assertEqual(pipeline.scene_runs, 1)
        # Re-reviewed against the repaired still.
        self.assertGreaterEqual(pipeline.review_runs, 2)

        issues = issue_store.list_issues(job_id=finished.id)
        self.assertTrue(issues)
        self.assertFalse(
            [issue for issue in issues if issue.status in {"open", "repairing"}],
            "the repaired defect should not still be open",
        )
        self.assertTrue(any(issue.status == "resolved" for issue in issues))

        # The Job continued rather than stopping for a human.
        self.assertEqual(finished.status, "completed")

    def test_the_repair_is_recorded_against_the_routed_node(self):
        finished, _pipeline = self._run(fix_after=1, max_repairs=3)
        entries = list_repair_history(job_id=finished.id)
        self.assertTrue(entries, "an admitted repair must leave history")
        self.assertTrue(
            any(entry.routed_to_node_type == "storyboard.generate" for entry in entries),
            [entry.routed_to_node_type for entry in entries],
        )
        self.assertTrue(
            all(entry.routed_to_node_type != "review.run" for entry in entries),
            "the node that reported the defect is never the repair target",
        )

    def test_a_clean_run_never_starts_a_cycle(self):
        finished, pipeline = self._run(fix_after=0, max_repairs=3)
        self.assertEqual(finished.status, "completed")
        self.assertEqual(pipeline.image_runs, 1)
        self.assertEqual(pipeline.review_runs, 1)
        self.assertEqual(issue_store.list_issues(job_id=finished.id), [])


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


class RepairPlumbingTests(_IsolatedRun):
    def test_a_job_with_no_issues_short_circuits(self):
        job = self._job()
        outcome = run_job_repair_cycles(job.id, workflow=self.workflow)
        self.assertEqual(outcome["stop_reason"], "no_issues")
        self.assertEqual(outcome["cycles"], [])

    def test_repair_runs_drop_approval_checkpoints(self):
        document = dict(self.workflow)
        document["extensions"] = {"approval_checkpoints": ["n_images"]}
        self.assertEqual(
            workflow_for_repair(document)["extensions"]["approval_checkpoints"], []
        )
        # The source document is untouched.
        self.assertEqual(document["extensions"]["approval_checkpoints"], ["n_images"])

    def test_review_nodes_are_found_by_type_and_honour_disabled(self):
        self.assertEqual(review_node_ids(self.workflow), ["n_review"])
        disabled = {
            **self.workflow,
            "nodes": [
                {**node, "disabled": node["id"] == "n_review"}
                for node in self.workflow["nodes"]
            ],
        }
        self.assertEqual(review_node_ids(disabled), [])


if __name__ == "__main__":
    unittest.main()
