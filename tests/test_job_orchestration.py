"""Step 1.5 — Job orchestration over the ported engine.

Done when: a Job created from a Channel runs the default workflow through to
export, and its artifacts match a direct workflow run of the same graph
byte-for-byte.

Also locks: Job is not a node; status derives from the execution record;
channel defaults use inherited_config precedence (explicit wins; empty is not
explicit).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from copy import deepcopy

from scriptase.artifacts import store as artifact_store
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.adapters.common import inherited_config
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import create_workflow
from scriptase.engine.registry import get_node_type
from scriptase.engine.templates import full_video_template
from scriptase.jobs import store as job_store
from scriptase.jobs.channel_settings import (
    channel_settings_from_snapshot,
    merge_node_config_with_channel,
    script_text_from_source,
)
from scriptase.jobs.orchestration import (
    JobOrchestrationError,
    assert_job_is_not_a_node,
    collect_execution_artifact_refs,
    derive_job_status,
    kind_for_artifact_ref,
    prepare_workflow_for_job,
    start_job,
    sync_job_from_execution,
)
from scriptase.jobs.store import create_job, default_draft, get_job


# ---------------------------------------------------------------------------
# Deterministic full-video stub executor
# ---------------------------------------------------------------------------

_PORT_DEFAULTS = {
    "control": {"ok": True},
    "settings": {"channel_name": "stub", "tone": "calm", "style": "cinematic"},
    "script": "Deterministic narration for the Job orchestration test.",
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


def _deterministic_resolver(output_dir: str, seen_configs: list | None = None):
    """Return fixed outputs and write stable artifact bytes per node type."""

    def resolve(node):
        node_type = node.get("type")
        node_id = node.get("id")

        def execute(inputs, config, context):
            if seen_configs is not None:
                seen_configs.append({
                    "node_id": node_id,
                    "type": node_type,
                    "config": dict(config or {}),
                    "settings": (
                        dict(inputs.get("settings"))
                        if isinstance(inputs.get("settings"), dict)
                        else inputs.get("settings")
                    ),
                })
            definition = get_node_type(node_type) or {}
            result = {}
            project_id = getattr(context, "project_id", None) or "pm_TEST0"
            for port in definition.get("outputs", []):
                port_id = port["id"]
                if port_id == "settings":
                    # Echo configuration as settings (project.setup behaviour).
                    result[port_id] = dict(config or {})
                    continue
                if port_id == "script" and node_type == "script.input":
                    result[port_id] = str((config or {}).get("text") or _PORT_DEFAULTS["script"])
                    continue
                if port_id in {"audio", "metadata"} and node_type == "tts.generate":
                    rel = f"tts/{project_id}/voice.wav"
                    _write_blob(output_dir, rel, b"VOICE-BYTES-DETERMINISTIC")
                    payload = {
                        "filename": "voice.wav",
                        "artifact_refs": [rel],
                    }
                    result[port_id] = payload if port_id == "audio" else {"duration": 1.0}
                    continue
                if port_id == "video" and node_type == "export.video":
                    rel = f"exports/{project_id}_final.mp4"
                    _write_blob(output_dir, rel, b"EXPORT-BYTES-DETERMINISTIC")
                    result[port_id] = {
                        "filename": f"{project_id}_final.mp4",
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "value" and node_type == "workflow.output":
                    # Pass through upstream video payload when present.
                    upstream = inputs.get("value") if isinstance(inputs, dict) else None
                    if isinstance(upstream, dict):
                        result[port_id] = upstream
                    else:
                        result[port_id] = dict(_PORT_DEFAULTS["value"])
                    continue
                if port_id == "project" and node_type in {"assemble.project", "timeline.project"}:
                    rel = f"projects/{project_id}/work@in@progress.json"
                    _write_blob(output_dir, rel, b'{"scenes":[{"id":1,"duration":1}]}')
                    result[port_id] = {
                        "assembled_data": {"scenes": [{"id": 1, "duration": 1}]},
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "images" and node_type == "storyboard.generate":
                    rel = f"storyboard/{project_id}/scene_01.png"
                    _write_blob(output_dir, rel, b"IMAGE-BYTES-DETERMINISTIC")
                    result[port_id] = {"ready": 1, "total": 1, "artifact_refs": [rel]}
                    continue
                if port_id == "assets" and node_type == "animator.generate":
                    rel = f"animator/{project_id}/scene_01.mp4"
                    _write_blob(output_dir, rel, b"VIDEO-BYTES-DETERMINISTIC")
                    result[port_id] = {"ready": 1, "total": 1, "artifact_refs": [rel]}
                    continue
                if port_id == "alignment" and node_type == "timing.align":
                    rel = f"alignments/{project_id}/alignment.json"
                    _write_blob(output_dir, rel, b'{"words":[]}')
                    result[port_id] = {"words": [], "artifact_refs": [rel]}
                    continue
                if port_id == "segments" and node_type == "segment.run":
                    rel = f"segmenters/{project_id}/segments.json"
                    _write_blob(output_dir, rel, b'{"segments":[]}')
                    result[port_id] = {"segments": [], "artifact_refs": [rel]}
                    continue
                if port_id == "scenes" and node_type == "scenes.blueprint":
                    rel = f"scenes/{project_id}/scenes.json"
                    _write_blob(output_dir, rel, b'{"scenes":[{"id":"s1"}]}')
                    result[port_id] = {
                        "scenes": [{"id": "s1", "image_prompt": "p"}],
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "captions" and node_type == "captions.generate":
                    rel = f"captions/{project_id}/captions.json"
                    _write_blob(output_dir, rel, b'{"cues":[]}')
                    result[port_id] = {"cues": [], "artifact_refs": [rel]}
                    continue
                if port_id == "track" and node_type == "music.select":
                    rel = f"musics/{project_id}/track.wav"
                    _write_blob(output_dir, rel, b"MUSIC-BYTES-DETERMINISTIC")
                    result[port_id] = {"title": "ambient", "artifact_refs": [rel]}
                    continue
                result[port_id] = deepcopy(_PORT_DEFAULTS.get(port_id, {}))
            return result

        return execute

    return resolve


def _artifact_payloads(execution: dict, output_dir: str) -> dict[str, bytes]:
    """Map each artifact ref (project-id stripped) to its file bytes."""
    payloads: dict[str, bytes] = {}
    for ref in collect_execution_artifact_refs(execution):
        abs_path = os.path.join(output_dir, ref.replace("/", os.sep))
        with open(abs_path, "rb") as handle:
            content = handle.read()
        # Normalize path so two project ids still compare content by role.
        logical = ref
        for token in ref.split("/"):
            if token.startswith("pm_") or token.startswith("pp_"):
                logical = logical.replace(token, "{project}")
        # Also strip project id embedded in export filenames.
        parts = logical.split("/")
        if parts and parts[0] == "exports" and len(parts) > 1:
            name = parts[-1]
            if "_final.mp4" in name:
                logical = "exports/{project}_final.mp4"
        payloads[logical] = content
    return payloads


def _wait(manager: ExecutionManager, execution_id: str, timeout: float = 10.0) -> None:
    handle = manager.active.get(execution_id)
    assert handle is not None
    handle.thread.join(timeout=timeout)
    assert not handle.thread.is_alive(), f"execution {execution_id} still running"


def _full_video_draft(*, script_text: str = "") -> dict:
    draft = full_video_template()
    draft.pop("template_id", None)
    for node in draft["nodes"]:
        if node["type"] == "script.input":
            node["configuration"] = {
                **(node.get("configuration") or {}),
                "text": script_text or "Placeholder script for validation only.",
            }
    return draft


# ---------------------------------------------------------------------------
# Test base
# ---------------------------------------------------------------------------


class JobOrchestrationTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_job_orch_")
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

        # Workflow persistence under the same managed output root.
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

        # Persist the default workflow first so the Channel can reference it.
        self.workflow = create_workflow(_full_video_draft())
        self.channel = create_channel(
            self._channel_draft(default_workflow_id=self.workflow["workflow_id"])
        )

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

    def _channel_draft(self, **overrides):
        draft = channel_default_draft(name="Philosophy Daily")
        draft["content"] = {
            "niche": "stoicism",
            "language": "en",
            "tone": "educational",
            "duration_target": 60,
        }
        draft["visual_direction"] = {
            "style": "cinematic",
            "pattern": [
                {"narrative_role": "hook", "shot": "extreme close-up"},
            ],
            "palette": "dark blue + amber",
        }
        draft["audio_defaults"] = {
            "tts_provider_instance_id": "inst_tts_1",
            "voice": "af_heart",
            "speed": 0.95,
        }
        draft["provider_defaults"] = {
            "script": "inst_script_1",
            "tts": "inst_tts_1",
            "image": "inst_image_1",
        }
        draft["export_defaults"] = {"aspect_ratio": "9:16", "fps": 30}
        draft.update(overrides)
        return draft

    def _job_draft(self, **overrides):
        draft = default_draft(
            channel_id=self.channel.id,
            execution_mode="automatic",
            source={
                "mode": "paste",
                "pasted_script": (
                    "What Marcus Aurelius teaches about control of the mind."
                ),
            },
            workflow_id=self.workflow["workflow_id"],
        )
        draft.update(overrides)
        return draft


# ---------------------------------------------------------------------------
# Unit: status derivation, inheritance, not-a-node
# ---------------------------------------------------------------------------


class DeriveStatusTests(unittest.TestCase):
    def test_execution_status_maps_to_job_status(self):
        self.assertEqual(derive_job_status("queued"), "queued")
        self.assertEqual(derive_job_status("running"), "running")
        self.assertEqual(derive_job_status("cancelling"), "running")
        self.assertEqual(derive_job_status("awaiting_approval"), "awaiting_approval")
        self.assertEqual(derive_job_status("succeeded"), "completed")
        self.assertEqual(derive_job_status("partial"), "completed")
        self.assertEqual(derive_job_status("failed"), "failed")
        self.assertEqual(derive_job_status("cancelled"), "cancelled")
        self.assertEqual(derive_job_status(None), "queued")
        self.assertEqual(derive_job_status("unknown"), "queued")


class InheritedConfigChannelTests(unittest.TestCase):
    def test_explicit_node_config_beats_channel_and_empty_is_not_explicit(self):
        channel = {
            "tone": "from-channel",
            "style": "cinematic",
            "voice": "af_heart",
        }
        # Explicit non-empty wins.
        merged = merge_node_config_with_channel(
            {"tone": "from-node", "style": ""},
            channel,
        )
        self.assertEqual(merged["tone"], "from-node")
        # Empty string is not explicit — channel style fills in.
        self.assertEqual(merged["style"], "cinematic")
        # Key only on channel is inherited.
        self.assertEqual(merged["voice"], "af_heart")

        # Same rules as the ported helper (identity check).
        self.assertEqual(merged, inherited_config({"tone": "from-node", "style": ""}, channel))

    def test_channel_settings_from_snapshot_are_flat_and_secret_free(self):
        snapshot = {
            "name": "Philosophy Daily",
            "content": {"tone": "educational"},
            "visual_direction": {"style": "cinematic"},
            "audio_defaults": {"voice": "af_heart", "speed": 0.95},
            "export_defaults": {"aspect_ratio": "9:16"},
            "branding": {"enabled": False},
            "provider_defaults": {"tts": "inst_tts_1"},
            "api_key": "should-not-map",  # not allowlisted into settings
        }
        settings = channel_settings_from_snapshot(snapshot)
        self.assertEqual(settings["channel_name"], "Philosophy Daily")
        self.assertEqual(settings["tone"], "educational")
        self.assertEqual(settings["style"], "cinematic")
        self.assertEqual(settings["aspect_ratio"], "9:16")
        self.assertEqual(settings["voice"], "af_heart")
        self.assertNotIn("api_key", settings)

    def test_script_text_from_source_modes(self):
        self.assertEqual(
            script_text_from_source({"mode": "paste", "pasted_script": "A", "idea": "B"}),
            "A",
        )
        self.assertEqual(
            script_text_from_source({"mode": "idea", "idea": "B", "topic": "C"}),
            "B",
        )
        self.assertEqual(
            script_text_from_source({"mode": "topic", "topic": "C"}),
            "C",
        )


class JobIsNotANodeTests(unittest.TestCase):
    def test_job_is_not_in_node_registry(self):
        assert_job_is_not_a_node()
        for key in ("job", "job.run", "jobs.orchestrate"):
            self.assertIsNone(get_node_type(key))


class KindForRefTests(unittest.TestCase):
    def test_kind_for_artifact_ref(self):
        self.assertEqual(kind_for_artifact_ref("exports/pm_X_final.mp4"), "export")
        self.assertEqual(kind_for_artifact_ref("tts/pm_X/voice.wav"), "audio")
        self.assertEqual(kind_for_artifact_ref("storyboard/pm_X/s.png"), "image")
        self.assertIsNone(kind_for_artifact_ref("tmp/scratch.bin"))


# ---------------------------------------------------------------------------
# Integration: prepare + run
# ---------------------------------------------------------------------------


class PrepareWorkflowTests(JobOrchestrationTestBase):
    def test_prepare_merges_channel_into_setup_and_script_from_source(self):
        job = create_job(self._job_draft())
        # Explicit style on setup must win; empty tone must take channel tone.
        workflow = deepcopy(self.workflow)
        for node in workflow["nodes"]:
            if node["type"] == "project.setup":
                node["configuration"]["style"] = "explicit-style"
                node["configuration"]["tone"] = ""
            if node["type"] == "script.input":
                node["configuration"]["text"] = ""

        prepared = prepare_workflow_for_job(job, workflow)
        setup = next(n for n in prepared["nodes"] if n["type"] == "project.setup")
        script = next(n for n in prepared["nodes"] if n["type"] == "script.input")

        self.assertEqual(setup["configuration"]["style"], "explicit-style")
        self.assertEqual(setup["configuration"]["tone"], "educational")
        self.assertEqual(setup["configuration"]["channel_name"], "Philosophy Daily")
        self.assertEqual(setup["configuration"]["aspect_ratio"], "9:16")
        self.assertIn(
            "Marcus Aurelius",
            script["configuration"]["text"],
        )
        self.assertEqual(prepared["extensions"]["job_id"], job.id)
        self.assertEqual(prepared["extensions"]["channel_id"], job.channel_id)


class JobRunParityTests(JobOrchestrationTestBase):
    """Done-when: Job run artifacts match a direct run of the same graph."""

    def test_job_run_matches_direct_workflow_run_byte_for_byte(self):
        job = create_job(self._job_draft())
        prepared = prepare_workflow_for_job(job, self.workflow)

        # --- Direct engine run of the prepared graph ---
        direct_dir = os.path.join(self.output_dir, "direct")
        os.makedirs(direct_dir, exist_ok=True)
        direct_manager = ExecutionManager(
            output_dir=direct_dir,
            executor_resolver=_deterministic_resolver(direct_dir),
        )
        direct_ex, direct_project = direct_manager.start(
            deepcopy(prepared),
            run_mode="full",
            target_node_ids=[],
            project_id="pm_DIRCT1",
            force=True,
        )
        _wait(direct_manager, direct_ex)
        direct_record = direct_manager.active.get(direct_ex).scheduler.record.to_dict()
        self.assertEqual(direct_record["status"], "succeeded")
        # Must have reached export.
        export_nodes = [
            nid for nid, rec in direct_record["nodes"].items()
            if "export" in nid or rec.get("artifact_refs")
        ]
        self.assertTrue(export_nodes)
        export_refs = [
            ref for ref in collect_execution_artifact_refs(direct_record)
            if ref.startswith("exports/")
        ]
        self.assertTrue(export_refs, "direct run produced no export artifact")
        direct_payloads = _artifact_payloads(direct_record, direct_dir)

        # --- Job-orchestrated run of the same graph ---
        job_dir = os.path.join(self.output_dir, "jobrun")
        os.makedirs(job_dir, exist_ok=True)
        # Rebind artifact store output for registration under job_dir.
        artifact_store._output_dir = job_dir
        artifact_store._artifacts_dir = os.path.join(job_dir, "artifacts")
        os.makedirs(artifact_store._artifacts_dir, exist_ok=True)

        job_manager = ExecutionManager(
            output_dir=job_dir,
            executor_resolver=_deterministic_resolver(job_dir),
        )
        finished = start_job(
            job.id,
            manager=job_manager,
            project_id="pm_JOBRN1",
            force=True,
            wait=True,
            timeout=15.0,
            workflow=self.workflow,
        )
        self.assertEqual(finished.status, "completed")
        self.assertEqual(
            finished.status,
            derive_job_status("succeeded"),
        )
        self.assertIsNotNone(finished.execution_id)
        self.assertIsNotNone(finished.completed_at)
        self.assertTrue(finished.artifacts, "Job should harvest typed artifact ids")

        job_record = job_manager.active.get(finished.execution_id).scheduler.record.to_dict()
        self.assertEqual(job_record["status"], "succeeded")
        job_payloads = _artifact_payloads(job_record, job_dir)

        # Byte-for-byte: every logical artifact content matches.
        self.assertEqual(set(direct_payloads), set(job_payloads))
        for key in direct_payloads:
            self.assertEqual(
                direct_payloads[key],
                job_payloads[key],
                f"artifact content mismatch for {key}",
            )
            self.assertEqual(
                hashlib.sha256(direct_payloads[key]).hexdigest(),
                hashlib.sha256(job_payloads[key]).hexdigest(),
            )

        # Status was derived, not independently tracked to a divergent value.
        reloaded = sync_job_from_execution(job.id, manager=job_manager)
        self.assertEqual(reloaded.status, "completed")
        self.assertEqual(reloaded.execution_id, finished.execution_id)

    def test_job_status_tracks_execution_failure(self):
        job = create_job(self._job_draft())

        def failing_resolver(node):
            def execute(inputs, config, context):
                if node.get("type") == "export.video":
                    raise RuntimeError("export boom")
                definition = get_node_type(node.get("type")) or {}
                return {
                    port["id"]: deepcopy(_PORT_DEFAULTS.get(port["id"], {"ok": True}))
                    for port in definition.get("outputs", [])
                }
            return execute

        manager = ExecutionManager(
            output_dir=self.output_dir,
            executor_resolver=failing_resolver,
        )
        finished = start_job(
            job.id,
            manager=manager,
            project_id="pm_FAIL01",
            force=True,
            wait=True,
            timeout=15.0,
            workflow=self.workflow,
        )
        self.assertEqual(finished.status, "failed")
        record = manager.active.get(finished.execution_id).scheduler.record.to_dict()
        self.assertEqual(finished.status, derive_job_status(record["status"]))

    def test_start_job_requires_workflow(self):
        # Channel with no default workflow → Job has no workflow_id.
        bare = create_channel(self._channel_draft(default_workflow_id=None, name="Bare"))
        orphan = create_job(
            default_draft(
                channel_id=bare.id,
                source={"mode": "paste", "pasted_script": "x" * 20},
            )
        )
        self.assertIsNone(orphan.workflow_id)
        with self.assertRaises(JobOrchestrationError) as ctx:
            start_job(orphan.id, manager=ExecutionManager(output_dir=self.output_dir))
        self.assertEqual(ctx.exception.code, "WORKFLOW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
