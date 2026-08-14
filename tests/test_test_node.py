"""Step 4.2 — Test Node panel: isolated run never advances the Job.

Done when: testing a node leaves the Job's status, current stage, and
artifact set unchanged, proven by a test asserting all three before and
after.

Also covers:
- sample bindings stamp ``from_sample_data`` on the execution record
- ``POST /api/jobs/<id>/test-node`` returns 202 without rewriting Job fields
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from scriptase.artifacts import store as artifact_store
from scriptase.artifacts.store import register_artifact
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import create_workflow
from scriptase.engine.templates import full_video_template
from scriptase.jobs import store as job_store
from scriptase.jobs.orchestration import run_node_test
from scriptase.jobs.store import (
    add_artifact_ids,
    create_job,
    default_draft,
    get_job,
    update_job,
)


def _full_video_draft(*, script_text: str = "Test Node isolation script.") -> dict:
    draft = full_video_template()
    draft.pop("template_id", None)
    for node in draft["nodes"]:
        if node["type"] == "script.input":
            node["configuration"] = {
                **(node.get("configuration") or {}),
                "text": script_text,
            }
    return draft


def _wait(manager: ExecutionManager, execution_id: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    handle = None
    while time.time() < deadline:
        handle = manager.active.get(execution_id)
        if handle is not None and handle.thread is not None:
            break
        time.sleep(0.01)
    assert handle is not None, f"execution {execution_id} never became active"
    handle.thread.join(timeout=timeout)
    while time.time() < deadline:
        record = handle.scheduler.record.to_dict()
        if record.get("status") in {"succeeded", "failed", "cancelled", "partial"}:
            return record
        time.sleep(0.02)
    return handle.scheduler.record.to_dict()


class TestNodeTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_test_node_")
        root = self.temp.name

        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(root, "channels")
        channel_store._trash_dir = os.path.join(root, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)

        self.old_jobs = job_store._jobs_dir
        self.old_job_trash = job_store._trash_dir
        job_store._jobs_dir = os.path.join(root, "jobs")
        job_store._trash_dir = os.path.join(root, "trash", "jobs")
        os.makedirs(job_store._jobs_dir, exist_ok=True)

        self.old_artifacts = artifact_store._artifacts_dir
        self.old_output = artifact_store._output_dir
        self.output_dir = os.path.join(root, "output")
        artifact_store._output_dir = self.output_dir
        artifact_store._artifacts_dir = os.path.join(self.output_dir, "artifacts")
        os.makedirs(artifact_store._artifacts_dir, exist_ok=True)

        from scriptase.engine import persistence as workflow_persistence

        self._wf_mod = workflow_persistence
        self.old_workflows_dir = workflow_persistence.WORKFLOWS_DIR
        self.old_executions_dir = workflow_persistence.EXECUTIONS_DIR
        self.workflows_dir = os.path.join(self.output_dir, "workflows")
        workflow_persistence.WORKFLOWS_DIR = self.workflows_dir
        workflow_persistence.EXECUTIONS_DIR = os.path.join(
            self.workflows_dir, "executions"
        )
        os.makedirs(workflow_persistence.EXECUTIONS_DIR, exist_ok=True)

        self.workflow = create_workflow(_full_video_draft())
        draft = channel_default_draft(name="Test Node Channel")
        draft["default_workflow_id"] = self.workflow["workflow_id"]
        self.channel = create_channel(draft)

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        artifact_store._artifacts_dir = self.old_artifacts
        artifact_store._output_dir = self.old_output
        self._wf_mod.WORKFLOWS_DIR = self.old_workflows_dir
        self._wf_mod.EXECUTIONS_DIR = self.old_executions_dir
        self.temp.cleanup()

    def _create_job_with_progress(self):
        """Job mid-run: status running, stage voice, one artifact, linked exec."""
        job = create_job(
            default_draft(
                channel_id=self.channel.id,
                execution_mode="manual",
                source={
                    "mode": "paste",
                    "pasted_script": "A short script for Test Node isolation.",
                },
                workflow_id=self.workflow["workflow_id"],
            )
        )
        # Seed a real artifact on the Job so the set is non-empty.
        blob = os.path.join(self.output_dir, "stories", "seed.txt")
        os.makedirs(os.path.dirname(blob), exist_ok=True)
        with open(blob, "w", encoding="utf-8") as handle:
            handle.write("seed narration")
        art = register_artifact(
            job_id=job.id,
            kind="script",
            path="stories/seed.txt",
            provenance_ref="seed",
        )
        job = add_artifact_ids(job.id, [art.id])
        job = update_job(
            job.id,
            status="running",
            current_stage="voice",
            execution_id="ex_TEST01",
            started_at=job.created_at or "2026-01-01T00:00:00Z",
        )
        return job, art


class TestNodeNeverAdvancesJobTests(TestNodeTestBase):
    """Done-when: status, current_stage, artifact set unchanged after test."""

    def test_testing_a_node_leaves_job_status_stage_and_artifacts_unchanged(self):
        job, art = self._create_job_with_progress()
        before = get_job(job.id)
        before_status = before.status
        before_stage = before.current_stage
        before_artifacts = list(before.artifacts)
        before_execution_id = before.execution_id

        self.assertEqual(before_status, "running")
        self.assertEqual(before_stage, "voice")
        self.assertEqual(before_artifacts, [art.id])
        self.assertEqual(before_execution_id, "ex_TEST01")

        # Locate the script.input node — it needs no external inputs.
        script_node = next(
            n for n in self.workflow["nodes"] if n["type"] == "script.input"
        )

        manager = ExecutionManager(output_dir=self.output_dir)
        result = run_node_test(
            job.id,
            target_node_ids=[script_node["id"]],
            manager=manager,
            wait=True,
            timeout=15.0,
        )

        after = get_job(job.id)
        self.assertEqual(after.status, before_status)
        self.assertEqual(after.current_stage, before_stage)
        self.assertEqual(list(after.artifacts), before_artifacts)
        # Linked production execution_id is also untouched.
        self.assertEqual(after.execution_id, before_execution_id)

        # The exploratory run itself still produced a real execution record.
        self.assertNotEqual(result["execution_id"], before_execution_id)
        self.assertEqual(result["run_mode"], "node_isolated")
        self.assertIn(result["status"], {"succeeded", "partial", "failed"})
        # Job object returned matches the store.
        self.assertEqual(result["job"].status, before_status)
        self.assertEqual(result["job"].current_stage, before_stage)
        self.assertEqual(list(result["job"].artifacts), before_artifacts)

    def test_sample_bindings_stamp_from_sample_data(self):
        """Stub/sample-derived output is never mistaken for real output."""
        job, _art = self._create_job_with_progress()

        # Tiny isolated animator node — inputs from sample bindings only.
        workflow = {
            "schema_version": 1,
            "name": "Sample-fed test",
            "description": "",
            "nodes": [
                {
                    "id": "n_viewer",
                    "type": "stub.output",
                    "type_version": 1,
                    "name": "Viewer",
                    "position": {"x": 0, "y": 0},
                    "configuration": {"port_type": "generic_json"},
                    "disabled": False,
                }
            ],
            "edges": [],
            "variables": {},
        }

        manager = ExecutionManager(output_dir=self.output_dir)
        # Override executor via the manager is fine; stub.output is built-in.
        result = run_node_test(
            job.id,
            target_node_ids=["n_viewer"],
            input_bindings={
                "n_viewer": {
                    "value": {"source": "sample", "port_type": "generic_json"},
                }
            },
            manager=manager,
            wait=True,
            timeout=15.0,
            workflow=workflow,
        )
        record = result.get("execution") or {}
        node = (record.get("nodes") or {}).get("n_viewer") or {}
        self.assertEqual(record.get("run_mode"), "node_isolated")
        self.assertEqual(node.get("status"), "succeeded", record)
        self.assertTrue(
            node.get("from_sample_data"),
            "sample binding must stamp from_sample_data on the node record",
        )
        # Job still frozen.
        after = get_job(job.id)
        self.assertEqual(after.status, "running")
        self.assertEqual(after.current_stage, "voice")


class TestNodeApiTests(TestNodeTestBase):
    def setUp(self):
        super().setUp()
        from app import create_app
        from scriptase.jobs import orchestration as orch

        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        # Route uses the module-level execution_manager; point it at the temp root.
        self._manager = ExecutionManager(output_dir=self.output_dir)
        self._old_manager = orch.execution_manager
        orch.execution_manager = self._manager

    def tearDown(self):
        from scriptase.jobs import orchestration as orch

        orch.execution_manager = self._old_manager
        super().tearDown()

    def test_api_test_node_returns_202_and_leaves_job_unchanged(self):
        job, art = self._create_job_with_progress()
        script_node = next(
            n for n in self.workflow["nodes"] if n["type"] == "script.input"
        )

        response = self.client.post(
            f"/api/jobs/{job.id}/test-node",
            json={
                "target_node_ids": [script_node["id"]],
                "wait": True,
                "timeout": 15,
            },
        )
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        body = response.get_json()
        self.assertIn("execution_id", body)
        self.assertEqual(body["run_mode"], "node_isolated")
        self.assertEqual(body["job"]["status"], "running")
        self.assertEqual(body["job"]["current_stage"], "voice")
        self.assertEqual(body["job"]["artifacts"], [art.id])
        self.assertEqual(body["job"]["execution_id"], "ex_TEST01")

        reloaded = get_job(job.id)
        self.assertEqual(reloaded.status, "running")
        self.assertEqual(reloaded.current_stage, "voice")
        self.assertEqual(list(reloaded.artifacts), [art.id])


if __name__ == "__main__":
    unittest.main()
