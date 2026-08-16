"""Step 13.2 — a one-shot provider override on a test run.

Done when: one node can be tested against two instances back to back, each
result recording which instance produced it, with the saved node config
unchanged.

The override is resolved for a single execution. It is injected into the
*resolved* configuration after schema validation, which is why it can never be
saved onto a node: ``validate_workflow`` rejects unknown configuration fields,
so ``provider_instance_override`` has no legal home in a stored workflow.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest

from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.adapters.common import (
    PROVIDER_OVERRIDE_KEY,
    provider_id,
    provider_selection_reason,
    request_provider_override,
)
from scriptase.engine.execution import ExecutionManager, ExecutionRequestError
from scriptase.engine.persistence import create_workflow
from scriptase.jobs import store as job_store
from scriptase.jobs.orchestration import run_node_test
from scriptase.jobs.store import create_job, default_draft

NODE_ID = "n_story"
SAVED_INSTANCE = "gemini"
INSTANCE_A = "script_alpha"
INSTANCE_B = "script_beta"


def _story_workflow() -> dict:
    """One provider node with no required inputs — runnable in isolation."""
    return {
        "schema_version": 1,
        "name": "Provider override probe",
        "description": "",
        "nodes": [
            {
                "id": NODE_ID,
                "type": "story.generate",
                "type_version": 1,
                "name": "Story Generator",
                "position": {"x": 0, "y": 0},
                "configuration": {
                    "provider_id": SAVED_INSTANCE,
                    "story_category": "motivation",
                    "idea": "A short probe script.",
                },
                "disabled": False,
            }
        ],
        "edges": [],
        "variables": {},
    }


class _RecordingExecutor:
    """Stands in for a script provider; reports what the platform selected."""

    def __init__(self):
        self.runs: list[dict] = []

    def resolver(self, _node):
        return self

    def __call__(self, _inputs, config, context):
        selected = provider_id("script", config)
        reason = provider_selection_reason(config)
        self.runs.append({"node_id": context.node_id, "instance": selected, "reason": reason})
        return {
            "control": {"ok": True},
            "script": f"script from {selected}",
            "story": {
                "provenance": {
                    "domain": "script",
                    "provider_id": selected,
                    "provider_instance_id": selected,
                    "invocation_id": f"inv_{len(self.runs)}",
                    "selection_reason": reason,
                }
            },
        }


class ProviderOverrideUnitTests(unittest.TestCase):
    """The single resolution point every adapter funnels through."""

    def test_override_outranks_the_saved_provider_id(self):
        config = {"provider_id": SAVED_INSTANCE, PROVIDER_OVERRIDE_KEY: INSTANCE_A}
        self.assertEqual(provider_id("script", config), INSTANCE_A)

    def test_no_override_keeps_the_saved_provider_id(self):
        self.assertEqual(provider_id("script", {"provider_id": SAVED_INSTANCE}), SAVED_INSTANCE)

    def test_selection_reason_is_request_only_under_an_override(self):
        self.assertEqual(provider_selection_reason({}), "node_config")
        self.assertEqual(
            provider_selection_reason({PROVIDER_OVERRIDE_KEY: INSTANCE_A}), "request"
        )

    def test_blank_override_is_not_an_override(self):
        self.assertEqual(request_provider_override({PROVIDER_OVERRIDE_KEY: "   "}), "")
        self.assertEqual(
            provider_id("script", {"provider_id": SAVED_INSTANCE, PROVIDER_OVERRIDE_KEY: ""}),
            SAVED_INSTANCE,
        )


class ProviderOverrideTestRunBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_provider_override_")
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

        from scriptase.engine import persistence as workflow_persistence

        self._wf_mod = workflow_persistence
        self.old_workflows_dir = workflow_persistence.WORKFLOWS_DIR
        self.old_executions_dir = workflow_persistence.EXECUTIONS_DIR
        self.output_dir = os.path.join(root, "output")
        self.workflows_dir = os.path.join(self.output_dir, "workflows")
        workflow_persistence.WORKFLOWS_DIR = self.workflows_dir
        workflow_persistence.EXECUTIONS_DIR = os.path.join(self.workflows_dir, "executions")
        os.makedirs(workflow_persistence.EXECUTIONS_DIR, exist_ok=True)

        self.workflow = create_workflow(_story_workflow())
        self.executor = _RecordingExecutor()
        self.manager = ExecutionManager(
            output_dir=self.output_dir, executor_resolver=self.executor.resolver
        )

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        self._wf_mod.WORKFLOWS_DIR = self.old_workflows_dir
        self._wf_mod.EXECUTIONS_DIR = self.old_executions_dir
        self.temp.cleanup()

    def _wait(self, execution_id: str, timeout: float = 15.0) -> dict:
        deadline = time.time() + timeout
        handle = None
        while time.time() < deadline:
            handle = self.manager.active.get(execution_id)
            if handle is not None and handle.thread is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(handle, f"execution {execution_id} never became active")
        handle.thread.join(timeout=timeout)
        return handle.scheduler.record.to_dict()

    def _run_with(self, instance_id: str) -> dict:
        execution_id, _project = self.manager.start(
            self.workflow,
            run_mode="node_isolated",
            target_node_ids=[NODE_ID],
            provider_instance_id=instance_id,
        )
        record = self._wait(execution_id)
        self.assertEqual(record["status"], "succeeded", record)
        return record["nodes"][NODE_ID]

    def _saved_configuration(self) -> dict:
        path = os.path.join(self.workflows_dir, f"{self.workflow['workflow_id']}.json")
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        node = next(item for item in document["nodes"] if item["id"] == NODE_ID)
        return node["configuration"]


class ProviderOverrideExecutionTests(ProviderOverrideTestRunBase):
    """Done-when: two instances back to back, saved node config unchanged."""

    def test_two_instances_back_to_back_each_record_their_own(self):
        before = self._saved_configuration()

        first = self._run_with(INSTANCE_A)
        second = self._run_with(INSTANCE_B)

        # Each run actually reached the provider with its own instance — the
        # second is not a cache replay of the first.
        self.assertEqual(
            [run["instance"] for run in self.executor.runs], [INSTANCE_A, INSTANCE_B]
        )
        self.assertEqual([run["reason"] for run in self.executor.runs], ["request", "request"])
        self.assertFalse(first["cache"]["hit"])
        self.assertFalse(second["cache"]["hit"], second["cache"])
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

        # Each result records which instance produced it, and why.
        self.assertEqual(first["cost"]["provider_instance_id"], INSTANCE_A)
        self.assertEqual(second["cost"]["provider_instance_id"], INSTANCE_B)
        self.assertEqual(first["cost"]["selection_reason"], "request")
        self.assertEqual(second["cost"]["selection_reason"], "request")

        # The saved node configuration never moved.
        after = self._saved_configuration()
        self.assertEqual(after, before)
        self.assertEqual(after["provider_id"], SAVED_INSTANCE)
        self.assertNotIn(PROVIDER_OVERRIDE_KEY, after)

    def test_no_override_runs_the_saved_provider_with_node_config_reason(self):
        execution_id, _project = self.manager.start(
            self.workflow, run_mode="node_isolated", target_node_ids=[NODE_ID]
        )
        record = self._wait(execution_id)
        node = record["nodes"][NODE_ID]
        self.assertEqual(record["status"], "succeeded", record)
        self.assertEqual(self.executor.runs[0]["instance"], SAVED_INSTANCE)
        self.assertEqual(self.executor.runs[0]["reason"], "node_config")
        self.assertEqual(node["cost"]["selection_reason"], "node_config")

    def test_an_override_without_targets_is_refused(self):
        """A full run has no node under test; repointing every provider is not
        an override, it is a silent reconfiguration."""
        with self.assertRaises(ExecutionRequestError) as caught:
            self.manager.start(
                self.workflow,
                run_mode="full",
                target_node_ids=[],
                provider_instance_id=INSTANCE_A,
            )
        self.assertEqual(caught.exception.code, "BAD_REQUEST")

    def test_an_override_on_an_unknown_node_is_refused(self):
        with self.assertRaises(ExecutionRequestError) as caught:
            self.manager.start(
                self.workflow,
                run_mode="node_isolated",
                target_node_ids=["n_missing"],
                provider_instance_id=INSTANCE_A,
            )
        self.assertEqual(caught.exception.code, "BAD_REQUEST")


class ProviderOverrideJobTestNodeTests(ProviderOverrideTestRunBase):
    """The Job-scoped Test Node path (step 4.2) carries the override too."""

    def setUp(self):
        super().setUp()
        draft = channel_default_draft(name="Provider Override Channel")
        draft["default_workflow_id"] = self.workflow["workflow_id"]
        self.channel = create_channel(draft)
        self.job = create_job(
            default_draft(
                channel_id=self.channel.id,
                execution_mode="manual",
                source={"mode": "topic", "topic": "A short probe topic."},
                workflow_id=self.workflow["workflow_id"],
            )
        )

    def test_test_node_honours_the_override_without_touching_the_job(self):
        result = run_node_test(
            self.job.id,
            target_node_ids=[NODE_ID],
            provider_instance_id=INSTANCE_B,
            manager=self.manager,
            wait=True,
            timeout=20.0,
        )
        self.assertEqual(result["provider_instance_id"], INSTANCE_B)
        node = (result["execution"]["nodes"] or {})[NODE_ID]
        self.assertEqual(node["status"], "succeeded", result["execution"])
        self.assertEqual(self.executor.runs[-1]["instance"], INSTANCE_B)
        self.assertEqual(node["cost"]["provider_instance_id"], INSTANCE_B)
        self.assertEqual(node["cost"]["selection_reason"], "request")
        self.assertEqual(self._saved_configuration()["provider_id"], SAVED_INSTANCE)


class ProviderOverrideApiTests(ProviderOverrideTestRunBase):
    def setUp(self):
        super().setUp()
        from app import create_app
        from scriptase.jobs import orchestration as orch

        draft = channel_default_draft(name="Provider Override API Channel")
        draft["default_workflow_id"] = self.workflow["workflow_id"]
        self.channel = create_channel(draft)
        self.job = create_job(
            default_draft(
                channel_id=self.channel.id,
                execution_mode="manual",
                source={"mode": "topic", "topic": "A short probe topic."},
                workflow_id=self.workflow["workflow_id"],
            )
        )
        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self._orch = orch
        self._old_manager = orch.execution_manager
        orch.execution_manager = self.manager

    def tearDown(self):
        self._orch.execution_manager = self._old_manager
        super().tearDown()

    def test_api_accepts_a_provider_instance_id(self):
        response = self.client.post(
            f"/api/jobs/{self.job.id}/test-node",
            json={
                "target_node_ids": [NODE_ID],
                "provider_instance_id": INSTANCE_A,
                "wait": True,
                "timeout": 20,
            },
        )
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual(body["provider_instance_id"], INSTANCE_A)
        self.assertEqual(self.executor.runs[-1]["instance"], INSTANCE_A)
        self.assertEqual(self._saved_configuration()["provider_id"], SAVED_INSTANCE)

    def test_api_rejects_a_non_string_provider_instance_id(self):
        response = self.client.post(
            f"/api/jobs/{self.job.id}/test-node",
            json={"target_node_ids": [NODE_ID], "provider_instance_id": 7},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "BAD_REQUEST")


if __name__ == "__main__":
    unittest.main()
