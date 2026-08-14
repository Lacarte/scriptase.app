"""Step 9.1 — Execution modes (Manual, Assisted, Automatic).

Done when: an Automatic Job runs start-to-export with no human input, and the
same Job in Assisted mode pauses at exactly its configured checkpoints and
nowhere else.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest

import pytest

from scriptase.artifacts import store as artifact_store
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.approval import ApprovalRequired
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import load_execution
from scriptase.engine.registry import get_node_type
from scriptase.engine.templates import full_video_template
from scriptase.jobs.execution_modes import (
    AUTOMATIC_MAX_REPAIRS_PER_SCENE,
    AUTOMATIC_SAFE_DEGRADATION_DEFAULTS,
    MANUAL_DEFAULT_CHECKPOINT_STAGES,
    configured_checkpoint_refs,
    resolve_checkpoint_node_ids,
    resolve_execution_policy,
    should_pause_for_escalation,
)
from scriptase.jobs.orchestration import (
    approve_job,
    prepare_workflow_for_job,
    start_job,
)
from scriptase.jobs import store as job_store
from scriptase.jobs.store import create_job, default_draft, get_job
from scriptase.review.repair import (
    LOW_CONFIDENCE,
    REPAIR_LIMIT_REACHED,
    SAFE_DEGRADATION,
    decide_issue_repair,
    resolve_repair_policy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _node(nid, type_key, **cfg):
    definition = get_node_type(type_key)
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


def _edge(eid, src, sport, tgt, tport, etype="data"):
    return {
        "id": eid,
        "source_node": src,
        "source_port": sport,
        "target_node": tgt,
        "target_port": tport,
        "edge_type": etype,
    }


def _workflow(nodes, edges, *, extensions=None, workflow_id="wf_MODE01"):
    return {
        "workflow_id": workflow_id,
        "name": "Execution mode test",
        "schema_version": 1,
        "nodes": nodes,
        "edges": edges,
        "extensions": dict(extensions or {}),
    }


def _linear_stub_workflow(*, checkpoint_on=None, workflow_id="wf_MODE01"):
    """sample → mid → viewer. Optional graph-authored approval_checkpoints."""
    extensions = {}
    if checkpoint_on:
        extensions["approval_checkpoints"] = list(checkpoint_on)
    return _workflow(
        [
            _node("sample", "stub.input", port_type="generic_json", payload={"v": 1}),
            _node("mid", "utility.set_value", value={"approved": True}),
            _node("viewer", "stub.output", port_type="generic_json"),
        ],
        [
            _edge("e1", "sample", "value", "mid", "value", "data"),
            _edge("e2", "mid", "value", "viewer", "value", "data"),
        ],
        extensions=extensions,
        workflow_id=workflow_id,
    )


def _script_spine_workflow(*, workflow_id="wf_SPINE1"):
    """trigger → script.input → workflow.output (maps to Production script stage)."""
    return _workflow(
        [
            _node("n_trigger", "trigger.manual"),
            _node("n_script", "script.input", text="Hello from mode test."),
            _node("n_out", "workflow.output", port_type="script", label="out"),
        ],
        [
            _edge("e1", "n_trigger", "control", "n_script", "trigger", "control"),
            _edge("e2", "n_script", "script", "n_out", "value", "data"),
        ],
        workflow_id=workflow_id,
    )


def _deterministic_full_resolver(output_dir: str):
    """Stable outputs for a full_video-style graph (no real providers)."""

    port_defaults = {
        "control": {"ok": True},
        "settings": {"channel_name": "stub", "tone": "calm", "style": "cinematic"},
        "script": "Automatic mode narration for end-to-end export.",
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

    def _write(relative: str, content: bytes) -> str:
        abs_path = os.path.join(output_dir, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(content)
        return relative.replace("\\", "/")

    def resolve(node):
        node_type = node.get("type")
        node_id = node.get("id")

        def execute(inputs, config, context):
            definition = get_node_type(node_type) or {}
            result = {}
            project_id = getattr(context, "project_id", None) or "pm_AUTO01"
            for port in definition.get("outputs", []):
                port_id = port["id"]
                if port_id in port_defaults:
                    result[port_id] = port_defaults[port_id]
                else:
                    result[port_id] = {"ok": True, "from": node_id}
            # Write a few managed artifact blobs so export path exists.
            if node_type == "export.video":
                rel = _write(
                    f"exports/{project_id}_final.mp4",
                    b"fake-mp4-bytes",
                )
                result["video"] = {"filename": os.path.basename(rel), "path": rel}
                result["value"] = result["video"]
            if node_type == "script.input":
                text = (config or {}).get("text") or port_defaults["script"]
                result["script"] = text
            return result

        return execute

    return resolve


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    channels = tmp_path / "channels"
    jobs = tmp_path / "jobs"
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "output"
    channels.mkdir()
    jobs.mkdir()
    artifacts.mkdir()
    output.mkdir()
    # Module-level roots (not config.JOBS_DIR) are what the stores read.
    monkeypatch.setattr(channel_store, "_channels_dir", str(channels))
    monkeypatch.setattr(channel_store, "_trash_dir", str(channels / "trash"))
    monkeypatch.setattr(job_store, "_jobs_dir", str(jobs))
    monkeypatch.setattr(job_store, "_trash_dir", str(jobs / "trash"))
    monkeypatch.setattr(artifact_store, "_artifacts_dir", str(artifacts))
    monkeypatch.setattr(artifact_store, "_output_dir", str(output))
    yield tmp_path


# ---------------------------------------------------------------------------
# Pure policy unit tests
# ---------------------------------------------------------------------------


class ConfiguredCheckpointRefsTests(unittest.TestCase):
    def test_automatic_never_configures_checkpoints(self):
        self.assertEqual(
            configured_checkpoint_refs(
                "automatic",
                human_checkpoints=["script", "review"],
                workflow_checkpoints=["mid"],
            ),
            [],
        )

    def test_assisted_uses_channel_list_only(self):
        self.assertEqual(
            configured_checkpoint_refs(
                "assisted",
                human_checkpoints=["script"],
                workflow_checkpoints=["mid"],
            ),
            ["script"],
        )

    def test_assisted_falls_back_to_workflow_authored(self):
        self.assertEqual(
            configured_checkpoint_refs(
                "assisted",
                human_checkpoints=[],
                workflow_checkpoints=["mid"],
            ),
            ["mid"],
        )

    def test_manual_defaults_when_channel_empty(self):
        refs = configured_checkpoint_refs("manual", human_checkpoints=[])
        self.assertEqual(refs, list(MANUAL_DEFAULT_CHECKPOINT_STAGES))
        self.assertNotIn("export", refs)


class ResolveCheckpointNodeIdsTests(unittest.TestCase):
    def test_stage_key_maps_to_primary_node(self):
        workflow = _script_spine_workflow()
        ids = resolve_checkpoint_node_ids(workflow, ["script"])
        self.assertEqual(ids, ["n_script"])

    def test_raw_node_id_passes_through(self):
        workflow = _linear_stub_workflow()
        ids = resolve_checkpoint_node_ids(workflow, ["mid"])
        self.assertEqual(ids, ["mid"])

    def test_unknown_ref_skipped(self):
        workflow = _script_spine_workflow()
        ids = resolve_checkpoint_node_ids(workflow, ["not_a_stage", "n_script"])
        self.assertEqual(ids, ["n_script"])

    def test_alias_script_approval(self):
        workflow = _script_spine_workflow()
        ids = resolve_checkpoint_node_ids(workflow, ["script_approval"])
        self.assertEqual(ids, ["n_script"])


class PauseForEscalationTests(unittest.TestCase):
    def test_manual_always_pauses(self):
        self.assertTrue(
            should_pause_for_escalation(
                execution_mode="manual", severity="low", code=LOW_CONFIDENCE
            )
        )

    def test_automatic_pauses_only_on_critical(self):
        self.assertTrue(
            should_pause_for_escalation(
                execution_mode="automatic", severity="critical", code=LOW_CONFIDENCE
            )
        )
        self.assertFalse(
            should_pause_for_escalation(
                execution_mode="automatic", severity="medium", code=LOW_CONFIDENCE
            )
        )

    def test_automatic_pauses_on_unrecoverable_codes(self):
        self.assertTrue(
            should_pause_for_escalation(
                execution_mode="automatic",
                severity="low",
                code=REPAIR_LIMIT_REACHED,
            )
        )


# ---------------------------------------------------------------------------
# prepare_workflow_for_job integration
# ---------------------------------------------------------------------------


class PrepareWorkflowModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = self.temp.name
        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        self.old_jobs = job_store._jobs_dir
        self.old_job_trash = job_store._trash_dir
        channel_store._channels_dir = os.path.join(root, "channels")
        channel_store._trash_dir = os.path.join(root, "channels", "trash")
        job_store._jobs_dir = os.path.join(root, "jobs")
        job_store._trash_dir = os.path.join(root, "jobs", "trash")
        os.makedirs(channel_store._channels_dir, exist_ok=True)
        os.makedirs(job_store._jobs_dir, exist_ok=True)

        draft = channel_default_draft(name="Mode channel")
        draft["review_policy"] = {
            "thresholds": {},
            "max_repairs": 3,
            "escalation": "",
            "human_checkpoints": ["script"],
        }
        self.channel = create_channel(draft)
        self.spine = _script_spine_workflow()

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        self.temp.cleanup()

    def test_automatic_clears_checkpoints_despite_channel_list(self):
        job = create_job(default_draft(
            channel_id=self.channel.id,
            execution_mode="automatic",
            source={"mode": "paste", "pasted_script": "hello"},
            workflow_id="wf_SPINE1",
        ))
        prepared = prepare_workflow_for_job(job, self.spine)
        self.assertEqual(prepared["extensions"]["approval_checkpoints"], [])
        self.assertEqual(prepared["extensions"]["execution_mode"], "automatic")
        policy = prepared["extensions"]["execution_policy"]
        self.assertTrue(policy["pause_only_on_critical_semantic"])
        self.assertEqual(
            policy["max_repairs_per_scene"], AUTOMATIC_MAX_REPAIRS_PER_SCENE
        )
        self.assertEqual(
            policy["safe_degradation"]["video"],
            AUTOMATIC_SAFE_DEGRADATION_DEFAULTS["video"],
        )

    def test_assisted_pauses_at_channel_checkpoint_only(self):
        job = create_job(default_draft(
            channel_id=self.channel.id,
            execution_mode="assisted",
            source={"mode": "paste", "pasted_script": "hello"},
            workflow_id="wf_SPINE1",
        ))
        # Author-time list must not add extra pauses when Channel configures one.
        authored = dict(self.spine)
        authored["extensions"] = {"approval_checkpoints": ["n_out"]}
        prepared = prepare_workflow_for_job(job, authored)
        self.assertEqual(prepared["extensions"]["approval_checkpoints"], ["n_script"])
        self.assertEqual(
            prepared["extensions"]["execution_policy"]["checkpoint_refs"],
            ["script"],
        )

    def test_manual_defaults_to_primary_stages_present(self):
        # Channel without human_checkpoints → manual defaults.
        bare = create_channel(channel_default_draft(name="Bare"))
        job = create_job(default_draft(
            channel_id=bare.id,
            execution_mode="manual",
            source={"mode": "paste", "pasted_script": "hello"},
            workflow_id="wf_SPINE1",
        ))
        prepared = prepare_workflow_for_job(job, self.spine)
        # Only script stage exists in this graph.
        self.assertEqual(prepared["extensions"]["approval_checkpoints"], ["n_script"])


# ---------------------------------------------------------------------------
# Done-when: Automatic end-to-end vs Assisted checkpoint pause
# ---------------------------------------------------------------------------


def test_automatic_job_runs_start_to_export_with_no_human_input(
    isolated_stores, tmp_path
):
    channel = create_channel(channel_default_draft(name="Auto channel"))
    # Even with human_checkpoints configured, Automatic must ignore them.
    # Re-create channel with checkpoints via update of draft before create.
    draft = channel_default_draft(name="Auto with checkpoints")
    draft["review_policy"] = {
        "thresholds": {},
        "max_repairs": 3,
        "escalation": "",
        "human_checkpoints": ["script", "review", "composer"],
    }
    channel = create_channel(draft)

    workflow = full_video_template()
    workflow["workflow_id"] = "wf_AUTO01"
    job = create_job(default_draft(
        channel_id=channel.id,
        execution_mode="automatic",
        workflow_id="wf_AUTO01",
        source={
            "mode": "paste",
            "pasted_script": "Automatic mode must reach export unattended.",
        },
    ))

    engine_dir = str(tmp_path / "engine")
    manager = ExecutionManager(
        output_dir=engine_dir,
        executor_resolver=_deterministic_full_resolver(engine_dir),
    )
    finished = start_job(
        job.id,
        manager=manager,
        workflow=workflow,
        project_id="pm_AUTO01",
        force=True,
        wait=True,
        timeout=30.0,
    )
    assert finished.status == "completed", (
        f"Automatic Job should complete without human input; got "
        f"status={finished.status} reason={finished.status_reason}"
    )
    assert finished.status_reason is None
    record = load_execution(finished.execution_id, root=manager.execution_root)
    assert record["status"] in {"succeeded", "partial"}
    # Never paused for approval mid-run.
    assert record["status"] != "awaiting_approval"
    for node in (record.get("nodes") or {}).values():
        assert node.get("status") != "awaiting_approval"


def test_assisted_job_pauses_only_at_configured_checkpoint(isolated_stores, tmp_path):
    draft = channel_default_draft(name="Assisted channel")
    draft["review_policy"] = {
        "thresholds": {},
        "max_repairs": 3,
        "escalation": "",
        # Pause only after the script stage primary node.
        "human_checkpoints": ["script"],
    }
    channel = create_channel(draft)
    workflow = _script_spine_workflow(workflow_id="wf_ASST01")
    job = create_job(default_draft(
        channel_id=channel.id,
        execution_mode="assisted",
        workflow_id="wf_ASST01",
        source={"mode": "paste", "pasted_script": "Need human eyes on the script."},
    ))

    manager = ExecutionManager(output_dir=str(tmp_path / "engine"))
    paused = start_job(
        job.id,
        manager=manager,
        workflow=workflow,
        wait=True,
        timeout=10.0,
    )
    assert paused.status == "awaiting_approval"
    assert paused.status_reason in {"script_approval", "policy", "approval"}
    record = load_execution(paused.execution_id, root=manager.execution_root)
    assert record["status"] == "awaiting_approval"
    assert record["nodes"]["n_script"]["status"] == "awaiting_approval"
    # Downstream must not have run.
    assert record["nodes"]["n_out"]["status"] in {"idle", "queued", "waiting", "skipped"} or (
        record["nodes"]["n_out"]["status"] != "succeeded"
    )

    # Worker released.
    handle = manager.active.get(paused.execution_id)
    if handle is not None and handle.thread is not None:
        assert not handle.thread.is_alive()

    resumed = approve_job(
        job.id, manager=manager, decided_by="tester", wait=True, timeout=10.0
    )
    assert resumed.status == "completed"
    final = load_execution(paused.execution_id, root=manager.execution_root)
    assert final["status"] == "succeeded"
    assert final["nodes"]["n_out"]["status"] == "succeeded"


def test_assisted_with_same_graph_as_automatic_differs_only_at_checkpoints(
    isolated_stores, tmp_path
):
    """Same Channel+graph: Automatic finishes; Assisted pauses at mid."""
    draft = channel_default_draft(name="Compare modes")
    draft["review_policy"] = {
        "thresholds": {},
        "max_repairs": 3,
        "escalation": "",
        "human_checkpoints": ["mid"],
    }
    channel = create_channel(draft)
    workflow = _linear_stub_workflow(workflow_id="wf_CMP001")

    # --- Automatic: ignore human_checkpoints, finish ---
    auto_job = create_job(default_draft(
        channel_id=channel.id,
        execution_mode="automatic",
        workflow_id="wf_CMP001",
        source={"mode": "paste", "pasted_script": "x"},
    ))
    mgr_auto = ExecutionManager(output_dir=str(tmp_path / "engine-auto"))
    auto_done = start_job(
        auto_job.id, manager=mgr_auto, workflow=workflow, wait=True, timeout=10.0
    )
    assert auto_done.status == "completed"

    # --- Assisted: pause exactly at mid, nowhere else ---
    asst_job = create_job(default_draft(
        channel_id=channel.id,
        execution_mode="assisted",
        workflow_id="wf_CMP001",
        source={"mode": "paste", "pasted_script": "x"},
    ))
    mgr_asst = ExecutionManager(output_dir=str(tmp_path / "engine-asst"))
    asst_paused = start_job(
        asst_job.id, manager=mgr_asst, workflow=workflow, wait=True, timeout=10.0
    )
    assert asst_paused.status == "awaiting_approval"
    rec = load_execution(asst_paused.execution_id, root=mgr_asst.execution_root)
    assert rec["nodes"]["mid"]["status"] == "awaiting_approval"
    assert rec["nodes"]["viewer"]["status"] != "succeeded"
    # Only one node awaiting — nowhere else.
    awaiting = [
        nid
        for nid, node in rec["nodes"].items()
        if node.get("status") == "awaiting_approval"
    ]
    assert awaiting == ["mid"]


def test_automatic_strips_workflow_authored_checkpoints(isolated_stores, tmp_path):
    channel = create_channel(channel_default_draft(name="Strip authored"))
    workflow = _linear_stub_workflow(checkpoint_on=["mid"], workflow_id="wf_STRIP1")
    job = create_job(default_draft(
        channel_id=channel.id,
        execution_mode="automatic",
        workflow_id="wf_STRIP1",
        source={"mode": "paste", "pasted_script": "x"},
    ))
    manager = ExecutionManager(output_dir=str(tmp_path / "engine"))
    done = start_job(
        job.id, manager=manager, workflow=workflow, wait=True, timeout=10.0
    )
    assert done.status == "completed"
    rec = load_execution(done.execution_id, root=manager.execution_root)
    assert rec["nodes"]["mid"]["status"] == "succeeded"
    assert rec["nodes"]["viewer"]["status"] == "succeeded"


# ---------------------------------------------------------------------------
# Automatic repair policy defaults + pause-only-on-critical
# ---------------------------------------------------------------------------


def _issue_doc(**overrides):
    base = {
        "id": "iss_TEST1",
        "schema_version": 2,
        "job_id": "job_TEST1",
        "scene_id": "sc_1",
        "target_node_id": "n_anim",
        "target_artifact_id": "art_TEST1",
        "issue_type": "motion_defect",
        "severity": "medium",
        "confidence": 0.9,
        "status": "open",
        "suggested_action": "regenerate",
        "attempt_count": 0,
        "reason": "jitter",
        "repair_instruction": "Stabilize motion",
        "check_id": None,
        "observed": {},
        "expected": {},
        "created_at": "2026-01-01T00:00:00Z",
        "resolved_at": None,
    }
    base.update(overrides)
    return base


def _job_map(*, mode="automatic", max_repairs=3, thresholds=None):
    return {
        "id": "job_TEST1",
        "execution_mode": mode,
        "workflow_id": "wf_REP01",
        "channel_snapshot": {
            "review_policy": {
                "max_repairs": max_repairs,
                "thresholds": thresholds or {},
                "escalation": "",
                "human_checkpoints": [],
            },
            "budget": {},
        },
        "budget_spent": {"generations": 0, "cost": 0.0},
    }


def _workflow_with_video():
    return {
        "workflow_id": "wf_REP01",
        "nodes": [
            {
                "id": "n_anim",
                "type": "animator.generate",
                "type_version": 1,
                "name": "Video",
                "position": {"x": 0, "y": 0},
                "configuration": {},
                "disabled": False,
            }
        ],
        "edges": [],
    }


class AutomaticRepairPolicyTests(unittest.TestCase):
    def test_automatic_defaults_max_repairs_per_scene_and_safe_degradation(self):
        policy = resolve_repair_policy(_job_map(mode="automatic"))
        self.assertEqual(policy.max_repairs_per_scene, AUTOMATIC_MAX_REPAIRS_PER_SCENE)
        self.assertEqual(
            policy.safe_degradation.get("video"),
            AUTOMATIC_SAFE_DEGRADATION_DEFAULTS["video"],
        )
        self.assertFalse(policy.escalate_on_low_confidence)

    def test_manual_does_not_inject_automatic_defaults(self):
        policy = resolve_repair_policy(_job_map(mode="manual"))
        self.assertIsNone(policy.max_repairs_per_scene)
        self.assertEqual(dict(policy.safe_degradation), {})
        self.assertTrue(policy.escalate_on_low_confidence)

    def test_automatic_non_critical_suggested_escalate_soft_handles(self):
        job = _job_map(mode="automatic")
        decision = decide_issue_repair(
            _issue_doc(suggested_action="escalate", severity="medium"),
            job,
            workflow=_workflow_with_video(),
        )
        # Safe degradation for video/motion is on by default in Automatic.
        self.assertIn(decision.action, {"degrade", "accept"})
        self.assertNotEqual(decision.action, "escalate")

    def test_automatic_critical_still_escalates(self):
        job = _job_map(mode="automatic")
        decision = decide_issue_repair(
            _issue_doc(suggested_action="escalate", severity="critical"),
            job,
            workflow=_workflow_with_video(),
        )
        self.assertEqual(decision.action, "escalate")

    def test_assisted_escalates_on_low_confidence(self):
        job = _job_map(mode="assisted")
        decision = decide_issue_repair(
            _issue_doc(confidence=0.1, severity="medium"),
            job,
            workflow=_workflow_with_video(),
        )
        self.assertEqual(decision.action, "escalate")
        self.assertEqual(decision.code, LOW_CONFIDENCE)

    def test_automatic_repair_limit_degrades_video(self):
        job = _job_map(mode="automatic", max_repairs=2)
        decision = decide_issue_repair(
            _issue_doc(attempt_count=2, severity="medium"),
            job,
            workflow=_workflow_with_video(),
        )
        self.assertEqual(decision.action, "degrade")
        self.assertEqual(decision.code, SAFE_DEGRADATION)


class ResolveExecutionPolicyTests(unittest.TestCase):
    def test_policy_dict_shape(self):
        job = {
            "execution_mode": "automatic",
            "channel_snapshot": {
                "review_policy": {
                    "human_checkpoints": ["script"],
                    "thresholds": {},
                    "max_repairs": 3,
                }
            },
        }
        policy = resolve_execution_policy(job, _script_spine_workflow())
        self.assertEqual(policy.mode, "automatic")
        self.assertEqual(policy.checkpoint_node_ids, ())
        self.assertTrue(policy.pause_only_on_critical_semantic)
        self.assertTrue(policy.auto_export_when_gates_pass)
        payload = policy.to_dict()
        self.assertIn("provider_retries", payload)
        self.assertIn("safe_degradation", payload)
