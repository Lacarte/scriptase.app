"""Step 1.7 — project.setup reads the Job's channel snapshot.

Done when: a saved V2-era workflow containing project.setup runs inside a Job
and takes channel values wherever its own configuration is empty.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy

from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.adapters import project
from scriptase.engine.adapters.common import AdapterContext
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import create_workflow
from scriptase.engine.registry import get_node_type
from scriptase.engine.templates import full_video_template
from scriptase.jobs import store as job_store
from scriptase.jobs.channel_settings import (
    channel_settings_from_snapshot,
    merge_setup_config_with_channel,
    resolve_channel_settings,
)
from scriptase.jobs.orchestration import prepare_workflow_for_job
from scriptase.jobs.store import create_job, default_draft


def _v2_setup_config(**overrides) -> dict:
    """Schema-default configuration as a saved V2 full-video workflow carries."""
    definition = get_node_type("project.setup")
    config = {
        field["name"]: field.get("default")
        for field in definition["config_schema"]
    }
    config.update(overrides)
    return config


class ChannelSettingsLogoMappingTests(unittest.TestCase):
    def test_branding_maps_to_setup_logo_block(self):
        snapshot = {
            "name": "Philosophy Daily",
            "content": {"tone": "educational"},
            "visual_direction": {"style": "noir"},
            "export_defaults": {"aspect_ratio": "16:9"},
            "branding": {
                "enabled": True,
                "logo_asset_id": "branding/logo_deadbeef.png",
                "position": "bottom-right",
                "size": 0.12,
                "opacity": 0.85,
                "margin": 0.04,
            },
        }
        settings = channel_settings_from_snapshot(snapshot)
        self.assertEqual(settings["channel_name"], "Philosophy Daily")
        self.assertEqual(settings["tone"], "educational")
        self.assertEqual(settings["style"], "noir")
        self.assertEqual(settings["aspect_ratio"], "16:9")
        self.assertTrue(settings["logo_enabled"])
        self.assertEqual(settings["logo"]["ref"], "branding/logo_deadbeef.png")
        self.assertEqual(settings["logo_position"], "bottom_right")
        self.assertEqual(settings["logo_size"], 12)
        self.assertEqual(settings["logo_opacity"], 0.85)
        self.assertEqual(settings["logo_margin"], round(0.04 * 1080))

    def test_logo_asset_id_without_branding_prefix_is_normalized(self):
        settings = channel_settings_from_snapshot({
            "name": "X",
            "branding": {
                "enabled": True,
                "logo_asset_id": "logo_only.png",
            },
        })
        self.assertEqual(settings["logo"]["ref"], "branding/logo_only.png")

    def test_absolute_logo_path_is_rejected(self):
        settings = channel_settings_from_snapshot({
            "name": "X",
            "branding": {
                "enabled": True,
                "logo_asset_id": "C:/secrets/logo.png",
            },
        })
        self.assertNotIn("logo", settings)


class MergeSetupConfigTests(unittest.TestCase):
    def test_empty_fields_take_channel_values(self):
        channel = channel_settings_from_snapshot({
            "name": "Philosophy Daily",
            "content": {"tone": "educational"},
            "visual_direction": {"style": "noir"},
            "export_defaults": {"aspect_ratio": "16:9"},
            "branding": {"enabled": False},
        })
        # V2 defaults: empty channel_name/tone; non-empty style/aspect stay.
        merged = merge_setup_config_with_channel(_v2_setup_config(), channel)
        self.assertEqual(merged["channel_name"], "Philosophy Daily")
        self.assertEqual(merged["tone"], "educational")
        # Schema default style is non-empty → explicit beats channel.
        self.assertEqual(merged["style"], "cinematic")
        self.assertEqual(merged["aspect_ratio"], "9:16")

    def test_explicit_override_beats_channel(self):
        channel = channel_settings_from_snapshot({
            "name": "Channel",
            "content": {"tone": "from-channel"},
            "visual_direction": {"style": "from-channel"},
        })
        merged = merge_setup_config_with_channel(
            _v2_setup_config(
                channel_name="Workflow Override",
                tone="from-workflow",
                style="",  # empty → channel
            ),
            channel,
        )
        self.assertEqual(merged["channel_name"], "Workflow Override")
        self.assertEqual(merged["tone"], "from-workflow")
        self.assertEqual(merged["style"], "from-channel")

    def test_logo_package_inherited_when_node_has_no_asset(self):
        channel = channel_settings_from_snapshot({
            "name": "Branded",
            "branding": {
                "enabled": True,
                "logo_asset_id": "branding/logo.png",
                "position": "top-left",
                "size": 0.1,
                "opacity": 0.9,
                "margin": 0.03,
            },
        })
        # V2 default: logo_enabled False, logo None.
        merged = merge_setup_config_with_channel(_v2_setup_config(), channel)
        self.assertTrue(merged["logo_enabled"])
        self.assertEqual(merged["logo"]["ref"], "branding/logo.png")
        self.assertEqual(merged["logo_position"], "top_left")

    def test_node_logo_asset_keeps_node_branding(self):
        channel = channel_settings_from_snapshot({
            "name": "Branded",
            "branding": {
                "enabled": True,
                "logo_asset_id": "branding/channel.png",
                "position": "top-left",
            },
        })
        merged = merge_setup_config_with_channel(
            _v2_setup_config(
                logo_enabled=True,
                logo={"ref": "branding/workflow.png"},
                logo_position="bottom_right",
            ),
            channel,
        )
        self.assertEqual(merged["logo"]["ref"], "branding/workflow.png")
        self.assertEqual(merged["logo_position"], "bottom_right")


class ProjectSetupAdapterReadsChannelTests(unittest.TestCase):
    def test_setup_reads_channel_settings_from_context(self, tmp_path_factory=None):
        # No logo file needed — logo disabled after merge.
        result = project.setup(
            {},
            _v2_setup_config(tone="", channel_name="", style=""),
            AdapterContext(
                project_id="pm_ABC123",
                channel_settings={
                    "channel_name": "From Context",
                    "tone": "calm",
                    "style": "documentary",
                    "aspect_ratio": "1:1",
                    "logo_enabled": False,
                },
            ),
        )
        settings = result["settings"]
        self.assertEqual(settings["channel_name"], "From Context")
        self.assertEqual(settings["tone"], "calm")
        self.assertEqual(settings["style"], "documentary")
        # Non-empty schema aspect_ratio stays.
        self.assertEqual(settings["aspect_ratio"], "9:16")

    def test_setup_inherits_channel_logo_and_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            logo_path = os.path.join(tmp, "logo.png")
            with open(logo_path, "wb") as handle:
                handle.write(b"png")
            old_branding = project.BRANDING_DIR
            project.BRANDING_DIR = tmp
            try:
                result = project.setup(
                    {},
                    _v2_setup_config(),
                    AdapterContext(
                        project_id="pm_ABC123",
                        channel_settings={
                            "channel_name": "Logo Channel",
                            "logo_enabled": True,
                            "logo": {"ref": "branding/logo.png"},
                            "logo_position": "bottom_left",
                        },
                    ),
                )
            finally:
                project.BRANDING_DIR = old_branding
            settings = result["settings"]
            self.assertTrue(settings["logo_enabled"])
            self.assertEqual(settings["logo"]["ref"], "branding/logo.png")
            self.assertEqual(settings["artifact_refs"], ["branding/logo.png"])

    def test_standalone_without_channel_keeps_v2_config(self):
        result = project.setup(
            {},
            _v2_setup_config(channel_name="Local Only", tone="dramatic"),
            AdapterContext(project_id="pm_ABC123"),
        )
        settings = result["settings"]
        self.assertEqual(settings["channel_name"], "Local Only")
        self.assertEqual(settings["tone"], "dramatic")
        self.assertFalse(settings["logo_enabled"])

    def test_resolve_channel_settings_from_mapping_extensions(self):
        resolved = resolve_channel_settings({
            "workflow_extensions": {
                "channel_settings": {"tone": "via-extensions"},
            },
        })
        self.assertEqual(resolved["tone"], "via-extensions")


class JobRunV2SetupChannelTests(unittest.TestCase):
    """Done-when: V2-era project.setup inside a Job takes empty fields from channel."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_setup_1_7_")
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
        workflow_persistence.EXECUTIONS_DIR = os.path.join(
            self.workflows_dir, "executions"
        )
        os.makedirs(workflow_persistence.EXECUTIONS_DIR, exist_ok=True)

        # Persist a V2-shaped full-video workflow (schema defaults on setup).
        draft = full_video_template()
        draft.pop("template_id", None)
        for node in draft["nodes"]:
            if node["type"] == "script.input":
                node["configuration"]["text"] = "Narration for channel snapshot test."
            if node["type"] == "project.setup":
                # Explicit empty identity fields — the V2 "unset" state.
                # style/aspect_ratio keep schema defaults (non-empty options);
                # empty strings on those widgets fail option validation at save.
                node["configuration"]["channel_name"] = ""
                node["configuration"]["tone"] = ""
        self.workflow = create_workflow(draft)

        channel_draft = channel_default_draft(name="Stoic Broadcast")
        channel_draft["content"] = {"tone": "reflective", "language": "en"}
        channel_draft["visual_direction"] = {
            "style": "documentary",
            "pattern": [{"narrative_role": "hook", "shot": "wide"}],
        }
        channel_draft["export_defaults"] = {"aspect_ratio": "16:9"}
        channel_draft["branding"] = {
            "enabled": False,
            "logo_asset_id": None,
            "position": "bottom-right",
            "size": 0.12,
            "opacity": 1.0,
            "margin": 0.04,
        }
        channel_draft["default_workflow_id"] = self.workflow["workflow_id"]
        self.channel = create_channel(channel_draft)

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        self._wf_mod.WORKFLOWS_DIR = self.old_workflows_dir
        self._wf_mod.EXECUTIONS_DIR = self.old_executions_dir
        self.temp.cleanup()

    def test_prepare_fills_empty_setup_from_channel_snapshot(self):
        job = create_job(default_draft(
            channel_id=self.channel.id,
            workflow_id=self.workflow["workflow_id"],
            source={"mode": "paste", "pasted_script": "Hello from the Job."},
        ))
        prepared = prepare_workflow_for_job(job, self.workflow)
        setup = next(n for n in prepared["nodes"] if n["type"] == "project.setup")
        self.assertEqual(setup["configuration"]["channel_name"], "Stoic Broadcast")
        self.assertEqual(setup["configuration"]["tone"], "reflective")
        # Non-empty schema defaults stay (empty-only rule).
        self.assertEqual(setup["configuration"]["style"], "cinematic")
        self.assertEqual(setup["configuration"]["aspect_ratio"], "9:16")
        self.assertEqual(
            prepared["extensions"]["channel_settings"]["channel_name"],
            "Stoic Broadcast",
        )

    def test_job_run_setup_emits_channel_values_for_empty_fields(self):
        job = create_job(default_draft(
            channel_id=self.channel.id,
            workflow_id=self.workflow["workflow_id"],
            source={"mode": "paste", "pasted_script": "Hello from the Job."},
        ))
        prepared = prepare_workflow_for_job(job, self.workflow)

        seen = []

        def resolver(node):
            node_type = node.get("type")
            node_id = node.get("id")

            def execute(inputs, config, context):
                if node_type == "project.setup":
                    # Use the real adapter so runtime channel read is exercised.
                    result = project.setup(inputs, config, context)
                    seen.append(result["settings"])
                    return result
                definition = get_node_type(node_type) or {}
                out = {}
                for port in definition.get("outputs", []):
                    pid = port["id"]
                    if pid == "control":
                        continue
                    if pid == "script":
                        out[pid] = str((config or {}).get("text") or "script")
                    elif pid == "settings":
                        out[pid] = dict(config or {})
                    else:
                        out[pid] = {"ok": True}
                from scriptase.engine.adapters.common import outputs as make_outputs
                return make_outputs(**out)

            return execute

        # Minimal graph: only trigger + setup, to keep the run focused.
        # Keep document metadata so start() validation accepts the snapshot.
        keep_types = {"trigger.manual", "project.setup"}
        keep_ids = {
            n["id"] for n in prepared["nodes"] if n["type"] in keep_types
        }
        slim = deepcopy(prepared)
        slim["name"] = "setup-only"
        slim["nodes"] = [
            n for n in slim["nodes"] if n["id"] in keep_ids
        ]
        slim["edges"] = [
            e for e in slim.get("edges", [])
            if e.get("source_node") in keep_ids and e.get("target_node") in keep_ids
        ]
        # Reset identity fields to empty so runtime channel read is the only
        # path filling them. style/aspect keep valid schema defaults so the
        # document still validates at start.
        for node in slim["nodes"]:
            if node["type"] == "project.setup":
                node["configuration"] = _v2_setup_config(
                    channel_name="",
                    tone="",
                )

        manager = ExecutionManager(
            output_dir=self.output_dir,
            executor_resolver=resolver,
        )
        execution_id, _ = manager.start(
            slim,
            run_mode="full",
            target_node_ids=[],
            project_id="pm_SETP17",
            force=True,
        )
        handle = manager.active.get(execution_id)
        handle.thread.join(timeout=10)
        record = handle.scheduler.record.to_dict()
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(len(seen), 1)
        emitted = seen[0]
        self.assertEqual(emitted["channel_name"], "Stoic Broadcast")
        self.assertEqual(emitted["tone"], "reflective")
        # Schema default style is non-empty → not overwritten by channel.
        self.assertEqual(emitted["style"], "cinematic")

    def test_explicit_setup_fields_survive_job_prepare(self):
        workflow = deepcopy(self.workflow)
        for node in workflow["nodes"]:
            if node["type"] == "project.setup":
                node["configuration"]["channel_name"] = "Workflow Name"
                node["configuration"]["tone"] = "from-workflow"
                # Keep a valid style option; empty tone/name are the overrides.
        job = create_job(default_draft(
            channel_id=self.channel.id,
            workflow_id=self.workflow["workflow_id"],
            source={"mode": "paste", "pasted_script": "x"},
        ))
        prepared = prepare_workflow_for_job(job, workflow)
        setup = next(n for n in prepared["nodes"] if n["type"] == "project.setup")
        self.assertEqual(setup["configuration"]["channel_name"], "Workflow Name")
        self.assertEqual(setup["configuration"]["tone"], "from-workflow")
        # Non-empty style on the node stays (channel documentary does not win).
        self.assertEqual(setup["configuration"]["style"], "cinematic")


if __name__ == "__main__":
    unittest.main()
