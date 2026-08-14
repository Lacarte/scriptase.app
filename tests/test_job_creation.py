"""Step 2.5 — Job creation API and Paste Script without a script provider.

Done when: a Job created with Paste Script runs to export with no script
provider configured or reachable.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from unittest import mock

from app import create_app
from scriptase.artifacts import store as artifact_store
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import create_workflow
from scriptase.engine.registry import get_node_type
from scriptase.engine.templates import full_video_template
from scriptase.jobs import store as job_store
from scriptase.jobs.orchestration import prepare_workflow_for_job, start_job
from scriptase.jobs.source_modes import (
    SOURCE_MODE_CATALOG,
    source_mode_requires_provider,
    validate_job_source,
)
from scriptase.jobs.store import create_job, default_draft, get_job
from scriptase.providers import hub as provider_hub


# ---------------------------------------------------------------------------
# Deterministic stub executor (no real providers)
# ---------------------------------------------------------------------------

_PORT_DEFAULTS = {
    "control": {"ok": True},
    "settings": {"channel_name": "stub", "tone": "calm", "style": "cinematic"},
    "script": "Deterministic narration for the Paste Script Job test.",
    "audio": {"filename": "voice.wav"},
    "metadata": {"duration": 1.0},
    "alignment": {"words": []},
    "segments": {"segments": []},
    "scenes": {"scenes": [{"id": "s1", "image_prompt": "p"}]},
    "images": {"ready": 1, "total": 1},
    "assets": {"ready": 1, "total": 1},
    "captions": {"cues": []},
    "track": {"title": "ambient"},
    "project": {"assembled_data": {"scenes": [{"id": 1, "duration": 1}]}},
    "video": {"filename": "final.mp4"},
    "value": {"filename": "final.mp4"},
}


def _write_blob(output_dir: str, relative: str, content: bytes) -> str:
    abs_path = os.path.join(output_dir, relative.replace("/", os.sep))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as handle:
        handle.write(content)
    return relative.replace("\\", "/")


def _deterministic_resolver(output_dir: str, *, forbidden_types=None):
    forbidden = set(forbidden_types or ())

    def resolve(node):
        node_type = node.get("type")
        node_id = node.get("id")

        def execute(inputs, config, context):
            if node_type in forbidden:
                raise AssertionError(
                    f"script provider path executed ({node_type}) but Paste "
                    f"mode must not call a script provider"
                )
            definition = get_node_type(node_type) or {}
            result = {}
            project_id = getattr(context, "project_id", None) or "pm_TEST0"
            for port in definition.get("outputs", []):
                port_id = port["id"]
                if port_id == "script" and node_type == "script.input":
                    result[port_id] = str((config or {}).get("text") or "")
                    continue
                payload = deepcopy(_PORT_DEFAULTS.get(port_id, {"ok": True}))
                result[port_id] = payload
            # Stable export artifact for the done-when check.
            if node_type == "export.video":
                rel = f"exports/{project_id}_final.mp4"
                _write_blob(output_dir, rel, b"FAKEMP4-paste-export")
                result["video"] = {
                    "filename": f"{project_id}_final.mp4",
                    "artifact_refs": [rel],
                }
            if node_type == "script.input":
                # Capture that we never needed a provider package.
                result["script"] = str((config or {}).get("text") or "")
            return result

        return execute

    return resolve


def _wait(manager: ExecutionManager, execution_id: str, timeout: float = 15.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        handle = manager.active.get(execution_id)
        if handle is None:
            time.sleep(0.02)
            continue
        status = handle.scheduler.record.status
        if status in {"succeeded", "partial", "failed", "cancelled"}:
            return
        time.sleep(0.02)
    raise TimeoutError(f"execution {execution_id} did not finish")


class SourceModeCatalogTests(unittest.TestCase):
    def test_catalog_covers_contract_modes(self):
        modes = {entry["mode"] for entry in SOURCE_MODE_CATALOG}
        self.assertEqual(
            modes,
            {"automatic", "topic", "idea", "paste", "manual"},
        )
        self.assertFalse(source_mode_requires_provider("paste"))
        self.assertFalse(source_mode_requires_provider("manual"))
        self.assertTrue(source_mode_requires_provider("topic"))
        self.assertTrue(source_mode_requires_provider("idea"))
        self.assertTrue(source_mode_requires_provider("automatic"))

    def test_validate_job_source_paste_requires_text(self):
        self.assertTrue(validate_job_source({"mode": "paste", "pasted_script": ""}))
        self.assertFalse(
            validate_job_source({"mode": "paste", "pasted_script": "Hello world."})
        )
        self.assertTrue(validate_job_source({"mode": "topic", "topic": ""}))
        self.assertFalse(validate_job_source({"mode": "topic", "topic": "stoicism"}))


class JobApiTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_job_api_")
        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        self.old_jobs = job_store._jobs_dir
        self.old_job_trash = job_store._trash_dir
        channel_store._channels_dir = os.path.join(self.temp.name, "channels")
        channel_store._trash_dir = os.path.join(self.temp.name, "trash", "channels")
        job_store._jobs_dir = os.path.join(self.temp.name, "jobs")
        job_store._trash_dir = os.path.join(self.temp.name, "trash", "jobs")
        os.makedirs(channel_store._channels_dir, exist_ok=True)
        os.makedirs(job_store._jobs_dir, exist_ok=True)

        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        draft = channel_default_draft(name="API Channel")
        draft["content"] = {
            "niche": "philosophy",
            "language": "en",
            "tone": "calm",
            "duration_target": 60,
        }
        draft["visual_direction"] = {
            "style": "cinematic",
            "pattern": [{"narrative_role": "hook", "shot": "wide"}],
            "palette": "",
        }
        self.channel = create_channel(draft)

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        self.temp.cleanup()


class JobApiTests(JobApiTestBase):
    def test_defaults_catalog(self):
        resp = self.client.get("/api/jobs/defaults")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        modes = {m["mode"] for m in data["source_modes"]}
        self.assertEqual(modes, {"automatic", "topic", "idea", "paste", "manual"})
        paste = next(m for m in data["source_modes"] if m["mode"] == "paste")
        self.assertFalse(paste["provider_required"])
        self.assertIn("execution_modes", data)
        self.assertEqual(data["defaults"]["source"]["mode"], "paste")

    def test_create_list_get_delete_paste_job(self):
        body = {
            "job": {
                "channel_id": self.channel.id,
                "execution_mode": "manual",
                "source": {
                    "mode": "paste",
                    "pasted_script": "What Marcus Aurelius teaches about control.",
                },
            }
        }
        resp = self.client.post("/api/jobs", json=body)
        self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))
        job = resp.get_json()["job"]
        self.assertEqual(job["source"]["mode"], "paste")
        self.assertEqual(job["status"], "queued")
        self.assertNotIn("api_key", str(job.get("channel_snapshot")))
        # Secrets must never appear.
        self.assertEqual(resp.headers.get("Location"), f"/api/jobs/{job['id']}")

        listed = self.client.get("/api/jobs")
        self.assertEqual(listed.status_code, 200)
        ids = [item["id"] for item in listed.get_json()["jobs"]]
        self.assertIn(job["id"], ids)
        self.assertEqual(
            next(item for item in listed.get_json()["jobs"] if item["id"] == job["id"])[
                "source_mode"
            ],
            "paste",
        )

        got = self.client.get(f"/api/jobs/{job['id']}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["job"]["id"], job["id"])

        deleted = self.client.delete(f"/api/jobs/{job['id']}")
        self.assertEqual(deleted.status_code, 200)
        missing = self.client.get(f"/api/jobs/{job['id']}")
        self.assertEqual(missing.status_code, 404)

    def test_create_rejects_paste_without_text(self):
        resp = self.client.post("/api/jobs", json={
            "job": {
                "channel_id": self.channel.id,
                "source": {"mode": "paste", "pasted_script": ""},
            }
        })
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json()
        self.assertEqual(body["error"]["code"], "JOB_INVALID")

    def test_create_rejects_topic_without_topic(self):
        resp = self.client.post("/api/jobs", json={
            "job": {
                "channel_id": self.channel.id,
                "source": {"mode": "topic", "topic": ""},
            }
        })
        self.assertEqual(resp.status_code, 422)


class PasteScriptNoProviderTests(unittest.TestCase):
    """Done-when: Paste Script Job runs to export with no script provider."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_paste_")
        self.output_dir = os.path.join(self.temp.name, "output")
        os.makedirs(self.output_dir, exist_ok=True)

        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        self.old_jobs = job_store._jobs_dir
        self.old_job_trash = job_store._trash_dir
        self.old_art_out = artifact_store._output_dir
        self.old_art_dir = artifact_store._artifacts_dir

        channel_store._channels_dir = os.path.join(self.temp.name, "channels")
        channel_store._trash_dir = os.path.join(self.temp.name, "trash", "channels")
        job_store._jobs_dir = os.path.join(self.temp.name, "jobs")
        job_store._trash_dir = os.path.join(self.temp.name, "trash", "jobs")
        artifact_store._output_dir = self.output_dir
        artifact_store._artifacts_dir = os.path.join(self.output_dir, "artifacts")
        os.makedirs(channel_store._channels_dir, exist_ok=True)
        os.makedirs(job_store._jobs_dir, exist_ok=True)
        os.makedirs(artifact_store._artifacts_dir, exist_ok=True)

        # Persist a full-video workflow (script.input spine — no story.generate).
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

        template = full_video_template()
        template.pop("template_id", None)
        self.workflow = create_workflow(template)

        draft = channel_default_draft(name="Paste Channel")
        draft["default_workflow_id"] = self.workflow["workflow_id"]
        draft["content"] = {
            "niche": "philosophy",
            "language": "en",
            "tone": "educational",
            "duration_target": 60,
        }
        draft["visual_direction"] = {
            "style": "cinematic",
            "pattern": [{"narrative_role": "hook", "shot": "wide"}],
            "palette": "",
        }
        # Intentionally no script provider instance reference.
        draft["provider_defaults"] = {}
        self.channel = create_channel(draft)

        self.pasted = (
            "What Marcus Aurelius teaches about control of the mind. "
            "The obstacle is the way."
        )

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        artifact_store._output_dir = self.old_art_out
        artifact_store._artifacts_dir = self.old_art_dir
        self._wf_mod.WORKFLOWS_DIR = self.old_workflows_dir
        self._wf_mod.EXECUTIONS_DIR = self.old_executions_dir
        self.temp.cleanup()

    def test_prepare_paste_fills_script_input_and_skips_provider(self):
        job = create_job(default_draft(
            channel_id=self.channel.id,
            execution_mode="manual",
            workflow_id=self.workflow["workflow_id"],
            source={"mode": "paste", "pasted_script": self.pasted},
        ))
        prepared = prepare_workflow_for_job(job, self.workflow)
        script_nodes = [
            n for n in prepared["nodes"] if n["type"] == "script.input"
        ]
        story_nodes = [
            n for n in prepared["nodes"] if n["type"] == "story.generate"
        ]
        self.assertTrue(script_nodes)
        self.assertFalse(story_nodes)
        self.assertIn(self.pasted, script_nodes[0]["configuration"]["text"])
        self.assertFalse(prepared["extensions"]["script_provider_required"])
        self.assertEqual(prepared["extensions"]["source_mode"], "paste")

    def test_prepare_rewrites_story_generate_for_paste(self):
        # Graph with only story.generate must still run paste without a provider.
        from scriptase.engine.models import workflow_draft
        from scriptase.engine.registry import get_node_type as _gnt

        def _node(nid, type_key, **cfg):
            definition = _gnt(type_key)
            configuration = {
                field["name"]: field.get("default")
                for field in definition["config_schema"]
            }
            configuration.update(cfg)
            return {
                "id": nid,
                "type": type_key,
                "type_version": definition["type_version"],
                "name": definition["display_name"],
                "position": {"x": 0, "y": 0},
                "configuration": configuration,
                "disabled": False,
            }

        doc = workflow_draft(name="Story only")
        doc["nodes"] = [
            _node("n_trigger", "trigger.manual"),
            _node("n_story", "story.generate", idea=""),
            _node("n_out", "workflow.output", port_type="script", label="out"),
        ]
        doc["edges"] = [
            {
                "id": "e1",
                "source_node": "n_trigger",
                "source_port": "control",
                "target_node": "n_story",
                "target_port": "trigger",
                "edge_type": "control",
            },
            {
                "id": "e2",
                "source_node": "n_story",
                "source_port": "script",
                "target_node": "n_out",
                "target_port": "value",
                "edge_type": "data",
            },
        ]
        job = create_job(default_draft(
            channel_id=self.channel.id,
            source={"mode": "paste", "pasted_script": self.pasted},
        ))
        prepared = prepare_workflow_for_job(job, doc)
        types = [n["type"] for n in prepared["nodes"]]
        self.assertIn("script.input", types)
        self.assertNotIn("story.generate", types)
        script = next(n for n in prepared["nodes"] if n["type"] == "script.input")
        self.assertEqual(script["configuration"]["text"], self.pasted)

    def test_paste_job_runs_to_export_without_script_provider(self):
        # Prove the script provider domain is unreachable / unused.
        def _hub_get(domain, provider_id=None, **kwargs):
            if domain == "script":
                raise AssertionError(
                    "script provider hub must not be consulted for Paste Script"
                )
            return None

        with mock.patch.object(provider_hub, "get", side_effect=_hub_get):
            job = create_job(default_draft(
                channel_id=self.channel.id,
                execution_mode="automatic",
                workflow_id=self.workflow["workflow_id"],
                source={"mode": "paste", "pasted_script": self.pasted},
            ))
            # Channel snapshot has no script provider instance configured.
            provider_defaults = job.channel_snapshot.get("provider_defaults") or {}
            self.assertFalse(provider_defaults.get("script"))

            manager = ExecutionManager(
                output_dir=self.output_dir,
                executor_resolver=_deterministic_resolver(
                    self.output_dir,
                    forbidden_types={"story.generate"},
                ),
            )
            finished = start_job(
                job.id,
                manager=manager,
                project_id="pm_PASTE1",
                force=True,
                wait=True,
                timeout=20.0,
                workflow=self.workflow,
            )

        self.assertEqual(finished.status, "completed")
        self.assertIsNotNone(finished.execution_id)
        record = manager.active.get(finished.execution_id).scheduler.record.to_dict()
        self.assertEqual(record["status"], "succeeded")

        # Export artifact on disk.
        export_path = os.path.join(
            self.output_dir, "exports", "pm_PASTE1_final.mp4"
        )
        self.assertTrue(
            os.path.isfile(export_path) or finished.artifacts,
            "expected export artifact on disk or harvested on the Job",
        )

        # Prepared snapshot used script.input with the pasted text — no provider.
        snapshot = record.get("workflow_snapshot") or {}
        script_cfgs = [
            n for n in (snapshot.get("nodes") or [])
            if n.get("type") == "script.input"
        ]
        self.assertTrue(script_cfgs)
        self.assertEqual(script_cfgs[0]["configuration"]["text"], self.pasted)
        self.assertFalse(
            any(n.get("type") == "story.generate" for n in (snapshot.get("nodes") or []))
        )
        reloaded = get_job(job.id)
        self.assertEqual(reloaded.status, "completed")


if __name__ == "__main__":
    unittest.main()
