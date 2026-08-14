"""Step 3.5: pre-flight budget check refuses work before the provider is called.

Done when: a Job whose next stage would exceed its budget is refused before the
provider is called.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import create_workflow
from scriptase.engine.templates import full_video_template
from scriptase.jobs import store as job_store
from scriptase.jobs.budget import (
    BudgetExceededError,
    check_budget_preflight,
    check_job_next_stage_budget,
    estimate_stage_generations,
    next_provider_stage,
)
from scriptase.jobs.orchestration import JobOrchestrationError, start_job
from scriptase.jobs.store import create_job, default_draft, get_job, update_job


def _tiny_workflow(*, workflow_id: str | None = None) -> dict:
    doc = {
        "schema_version": 1,
        "name": "tiny",
        "description": "",
        "nodes": [{
            "id": "t",
            "type": "trigger.manual",
            "type_version": 1,
            "name": "t",
            "position": {"x": 0, "y": 0},
            "configuration": {},
            "disabled": False,
        }],
        "edges": [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
    }
    if workflow_id:
        doc["workflow_id"] = workflow_id
    return doc


class BudgetPreflightUnitTests(unittest.TestCase):
    def test_no_ceiling_always_admits(self):
        check_budget_preflight(
            {
                "id": "job_AAAAAA",
                "channel_snapshot": {"budget": {}},
                "budget_spent": {"generations": 99, "cost": 999.0},
            },
            estimated_generations=10,
            estimated_cost=50.0,
        )

    def test_generation_ceiling_refuses_projected_overrun(self):
        with self.assertRaises(BudgetExceededError) as ctx:
            check_budget_preflight(
                {
                    "id": "job_BBBBBB",
                    "channel_snapshot": {
                        "budget": {
                            "max_generations": 3,
                            "max_cost": None,
                            "currency": "USD",
                        }
                    },
                    "budget_spent": {"generations": 2, "cost": 0.0},
                },
                estimated_generations=2,
                stage_key="images",
            )
        err = ctx.exception
        self.assertEqual(err.code, "BUDGET_EXCEEDED")
        self.assertEqual(err.details["axis"], "generations")
        self.assertEqual(err.details["stage_key"], "images")
        self.assertEqual(err.details["ceiling"], 3)

    def test_cost_ceiling_refuses_projected_overrun(self):
        with self.assertRaises(BudgetExceededError) as ctx:
            check_budget_preflight(
                {
                    "id": "job_CCCCCC",
                    "channel_snapshot": {
                        "budget": {
                            "max_generations": None,
                            "max_cost": 1.5,
                            "currency": "USD",
                        }
                    },
                    "budget_spent": {"generations": 0, "cost": 1.0},
                },
                estimated_generations=0,
                estimated_cost=0.6,
            )
        self.assertEqual(ctx.exception.details["axis"], "cost")

    def test_exact_ceiling_admits_zero_estimate_but_blocks_positive(self):
        payload = {
            "id": "job_DDDDDD",
            "channel_snapshot": {
                "budget": {
                    "max_generations": 2,
                    "max_cost": None,
                    "currency": "USD",
                }
            },
            "budget_spent": {"generations": 2, "cost": 0.0},
        }
        check_budget_preflight(payload, estimated_generations=0)
        with self.assertRaises(BudgetExceededError):
            check_budget_preflight(payload, estimated_generations=1)

    def test_next_stage_estimate_for_full_pipeline(self):
        workflow = full_video_template()
        # Default full-video template feeds script.input (no story.generate),
        # so the first billed stage is Voice (tts.generate).
        stage, estimate = next_provider_stage(workflow)
        self.assertEqual(stage, "voice")
        self.assertGreaterEqual(estimate, 1)
        self.assertEqual(estimate_stage_generations(workflow, "voice"), 1)
        self.assertEqual(estimate_stage_generations(workflow, "images"), 1)

    def test_check_job_next_stage_budget_raises_before_provider(self):
        workflow = full_video_template()
        payload = {
            "id": "job_EEEEEE",
            "channel_snapshot": {
                "budget": {
                    "max_generations": 0,
                    "max_cost": None,
                    "currency": "USD",
                }
            },
            "budget_spent": {"generations": 0, "cost": 0.0},
        }
        with self.assertRaises(BudgetExceededError) as ctx:
            check_job_next_stage_budget(payload, workflow)
        self.assertEqual(ctx.exception.code, "BUDGET_EXCEEDED")
        self.assertEqual(ctx.exception.details.get("stage_key"), "voice")


class BudgetJobStartTests(unittest.TestCase):
    def setUp(self):
        # ignore_cleanup_errors: Windows refuses rmtree while a pool worker still
        # holds a handle under output/workflows (async start tests).
        self.temp = tempfile.TemporaryDirectory(
            prefix="scriptase_budget_",
            ignore_cleanup_errors=True,
        )
        root = self.temp.name
        self._managers: list[ExecutionManager] = []

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

        from scriptase.engine import persistence as workflow_persistence

        self._wf_mod = workflow_persistence
        self.old_workflows_dir = workflow_persistence.WORKFLOWS_DIR
        self.old_executions_dir = workflow_persistence.EXECUTIONS_DIR
        self.output_dir = os.path.join(root, "output")
        self.workflows_dir = os.path.join(self.output_dir, "workflows")
        workflow_persistence.WORKFLOWS_DIR = self.workflows_dir
        workflow_persistence.EXECUTIONS_DIR = os.path.join(
            self.workflows_dir, "executions"
        )
        os.makedirs(workflow_persistence.EXECUTIONS_DIR, exist_ok=True)

        draft = full_video_template()
        draft.pop("template_id", None)
        for node in draft["nodes"]:
            if node["type"] == "script.input":
                node["configuration"] = {
                    **(node.get("configuration") or {}),
                    "text": "Budget preflight narration.",
                }
        self.workflow = create_workflow(draft)
        self.workflow_id = self.workflow["workflow_id"]

    def tearDown(self):
        # Stop leftover pool workers before restoring paths / removing the tree.
        for manager in self._managers:
            for execution_id, handle in manager.active.items():
                try:
                    manager.stop(execution_id)
                except Exception:
                    pass
                thread = handle.thread
                if thread is not None and thread.is_alive():
                    thread.join(timeout=5.0)
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        self._wf_mod.WORKFLOWS_DIR = self.old_workflows_dir
        self._wf_mod.EXECUTIONS_DIR = self.old_executions_dir
        try:
            self.temp.cleanup()
        except OSError:
            shutil.rmtree(self.temp.name, ignore_errors=True)

    def _manager(self, **kwargs) -> ExecutionManager:
        manager = ExecutionManager(output_dir=self.output_dir, **kwargs)
        self._managers.append(manager)
        return manager

    def _make_channel(self, *, max_generations=None, max_cost=None):
        draft = channel_default_draft(name="Budget Channel")
        draft["budget"] = {
            "max_generations": max_generations,
            "max_cost": max_cost,
            "currency": "USD",
        }
        draft["default_workflow_id"] = self.workflow_id
        return create_channel(draft)

    def _make_job(self, channel, *, generations=0, cost=0.0):
        draft = default_draft(
            channel_id=channel.id,
            source={"mode": "topic", "topic": "budget test"},
            workflow_id=self.workflow_id,
        )
        job = create_job(draft)
        if generations or cost:
            job = update_job(
                job.id,
                budget_spent={"generations": generations, "cost": cost},
            )
        return job

    def test_start_refused_when_max_generations_zero(self):
        channel = self._make_channel(max_generations=0)
        job = self._make_job(channel)

        provider_calls = []

        def resolver(_node):
            def execute(_inputs, _config, context):
                provider_calls.append(context.execution_id)
                return {"control": {"ok": True}}

            return execute

        manager = self._manager(executor_resolver=resolver)
        with self.assertRaises(JobOrchestrationError) as ctx:
            start_job(job.id, manager=manager, workflow=self.workflow)
        self.assertEqual(ctx.exception.code, "BUDGET_EXCEEDED")
        self.assertEqual(provider_calls, [])
        refreshed = get_job(job.id)
        self.assertIsNone(refreshed.execution_id)
        self.assertEqual(refreshed.status_reason, "budget")

    def test_start_refused_when_spent_blocks_next_stage(self):
        channel = self._make_channel(max_generations=2)
        # Script stage costs 1 generation; spent=2 at ceiling → refuse.
        job = self._make_job(channel, generations=2)

        provider_calls = []

        def resolver(_node):
            def execute(_inputs, _config, _context):
                provider_calls.append("called")
                return {"control": {"ok": True}}

            return execute

        manager = self._manager(executor_resolver=resolver)
        with self.assertRaises(JobOrchestrationError) as ctx:
            start_job(job.id, manager=manager, workflow=self.workflow)
        self.assertEqual(ctx.exception.code, "BUDGET_EXCEEDED")
        self.assertEqual(provider_calls, [])

    def test_start_admits_when_budget_has_room(self):
        channel = self._make_channel(max_generations=10)
        job = self._make_job(channel, generations=0)

        def resolver(_node):
            def execute(_inputs, _config, _context):
                return {"control": {"ok": True}}

            return execute

        manager = self._manager(executor_resolver=resolver)
        # Tiny workflow has no provider stages; ceiling is present but free.
        tiny = _tiny_workflow(workflow_id=self.workflow_id)
        started = start_job(job.id, manager=manager, workflow=tiny, wait=True)
        self.assertIn(started.status, {"completed", "failed", "cancelled"})
        self.assertIsNotNone(started.execution_id)

    def test_start_admits_under_ceiling_with_provider_stage(self):
        """Next stage fits under the ceiling → admission proceeds (provider may run)."""
        channel = self._make_channel(max_generations=5)
        job = self._make_job(channel, generations=0)

        provider_calls = []

        def resolver(node):
            def execute(_inputs, _config, context):
                provider_calls.append(node.get("type"))
                # Minimal stubs so prepare_workflow graph can finish nodes that
                # only need control passthrough; full pipeline may fail later.
                return {"control": {"ok": True}}

            return execute

        manager = self._manager(executor_resolver=resolver)
        # start_job itself must not raise BUDGET_EXCEEDED.
        started = start_job(job.id, manager=manager, workflow=self.workflow)
        self.assertIsNotNone(started.execution_id)
        self.assertNotEqual(started.status_reason, "budget")
        # Admission is the assertion; cancel the background full-pipeline run
        # so tearDown can remove the temp tree on Windows.
        if started.execution_id:
            try:
                manager.stop(started.execution_id)
            except Exception:
                pass
            handle = manager.active.get(started.execution_id)
            if handle is not None and handle.thread is not None:
                handle.thread.join(timeout=5.0)


if __name__ == "__main__":
    unittest.main()
