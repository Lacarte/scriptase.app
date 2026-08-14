"""Step 2.6 — Durable approval state in the engine.

Done when: a Job pauses at a checkpoint holding no worker thread, survives a
full process restart, and resumes from exactly where it paused on approval.
"""

from __future__ import annotations

import os
import threading
import time
from copy import deepcopy

import pytest

from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.approval import (
    ApprovalRequired,
    approvals_root,
    find_awaiting_for_execution,
    is_expired,
    load_checkpoint,
    load_resume_state,
    resume_root,
)
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import load_execution, save_execution
from scriptase.engine.registry import get_node_type
from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.jobs.orchestration import (
    approve_job,
    derive_job_status,
    prepare_workflow_for_job,
    reject_job,
    start_job,
    sync_job_from_execution,
)
from scriptase.jobs.store import create_job, default_draft, get_job
from scriptase.channels import store as channel_store
from scriptase.jobs import store as job_store
from scriptase.artifacts import store as artifact_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(node_id, node_type="trigger.manual", *, config=None, disabled=False):
    defn = get_node_type(node_type)
    ver = defn["type_version"] if defn else 1
    return {
        "id": node_id,
        "type": node_type,
        "type_version": ver,
        "name": node_id,
        "position": {"x": 0, "y": 0},
        "configuration": config or {},
        "disabled": disabled,
    }


def _edge(edge_id, source, source_port, target, target_port, edge_type="control"):
    return {
        "id": edge_id,
        "source_node": source,
        "source_port": source_port,
        "target_node": target,
        "target_port": target_port,
        "edge_type": edge_type,
    }


def _workflow(nodes, edges, *, extensions=None, workflow_id="wf_APR001"):
    return {
        "schema_version": 1,
        "workflow_id": workflow_id,
        "name": "Approval test",
        "description": "",
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": extensions or {},
        "created_at": "2026-08-14T12:00:00Z",
        "updated_at": "2026-08-14T12:00:00Z",
    }


def _linear_stub_workflow(*, checkpoint_on=None, workflow_id="wf_APR001"):
    """sample → mid (set_value) → viewer. Optionally pause after mid.

    Uses utility.set_value as the checkpoint node so pause-after-success is
    exercised on a real executable with control+value ports.
    """
    extensions = {}
    if checkpoint_on:
        extensions["approval_checkpoints"] = list(checkpoint_on)
    return _workflow(
        [
            _node("sample", "stub.input", config={
                "port_type": "generic_json",
                "payload": {"v": 1},
            }),
            _node("mid", "utility.set_value", config={"value": {"approved": True}}),
            _node("viewer", "stub.output", config={"port_type": "generic_json"}),
        ],
        [
            _edge("e1", "sample", "value", "mid", "value", "data"),
            _edge("e2", "mid", "value", "viewer", "value", "data"),
        ],
        extensions=extensions,
        workflow_id=workflow_id,
    )


def _resolver(calls, behavior=None, raise_approval_on=None):
    behavior = behavior or {}
    raise_approval_on = set(raise_approval_on or [])

    def resolve(node):
        def execute(inputs, config, context):
            calls.append(node["id"])
            if node["id"] in raise_approval_on:
                raise ApprovalRequired("script_approval", stage_key="script")
            defaults = {
                port["id"]: ({"ok": True} if port["id"] == "control" else {"echo": node["id"]})
                for port in get_node_type(node["type"])["outputs"]
            }
            return behavior.get(node["id"], defaults)
        return execute

    return resolve


def _wait_settled(manager, execution_id, *, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        handle = manager.active.get(execution_id)
        if handle is not None and handle.thread is not None and handle.thread.is_alive():
            handle.thread.join(timeout=0.1)
            continue
        try:
            record = load_execution(execution_id, root=manager.execution_root)
        except FileNotFoundError:
            time.sleep(0.05)
            continue
        status = record.get("status")
        if status in {
            "succeeded", "failed", "cancelled", "partial", "awaiting_approval",
        }:
            return record
        time.sleep(0.05)
    raise AssertionError(f"execution {execution_id} did not settle within {timeout}s")


def _active_worker_count():
    return sum(
        1
        for thread in threading.enumerate()
        if thread.is_alive()
        and (
            (thread.name or "").startswith("workflow-queue-")
            or (thread.name or "").startswith("workflow-")
        )
    )


# ---------------------------------------------------------------------------
# Scheduler-level unit tests
# ---------------------------------------------------------------------------


def test_scheduler_pauses_after_configured_checkpoint(tmp_path):
    calls = []
    workflow = _linear_stub_workflow(checkpoint_on=["mid"])
    result = WorkflowScheduler(
        workflow,
        project_id="pm_APR001",
        lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path),
        executor_resolver=_resolver(calls),
        checkpoint_after_node_ids=["mid"],
    ).run()

    assert result.status == "awaiting_approval"
    assert result.node_statuses["sample"] == "succeeded"
    assert result.node_statuses["mid"] == "awaiting_approval"
    assert result.node_statuses["viewer"] == "idle"
    assert "viewer" not in calls
    assert "mid" in calls
    assert result.execution_record is not None
    assert result.execution_record["status"] == "awaiting_approval"
    assert result.execution_record["finished_at"] is None
    assert result.execution_record["approval"]["node_id"] == "mid"


def test_scheduler_pauses_on_approval_required_exception(tmp_path):
    calls = []
    workflow = _linear_stub_workflow()
    result = WorkflowScheduler(
        workflow,
        project_id="pm_APR002",
        lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path),
        executor_resolver=_resolver(calls, raise_approval_on=["mid"]),
    ).run()

    assert result.status == "awaiting_approval"
    assert result.node_statuses["mid"] == "awaiting_approval"
    assert "viewer" not in calls
    checkpoint = find_awaiting_for_execution(
        result.execution_record["execution_id"],
        root=approvals_root(str(tmp_path)),
    )
    assert checkpoint is not None
    assert checkpoint.reason == "script_approval"
    assert checkpoint.has_outputs is False


def test_scheduler_resume_continues_from_pause_point(tmp_path):
    calls = []
    workflow = _linear_stub_workflow(checkpoint_on=["mid"])
    first = WorkflowScheduler(
        workflow,
        project_id="pm_APR003",
        lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path),
        executor_resolver=_resolver(calls),
        checkpoint_after_node_ids=["mid"],
        execution_id="ex_APR003",
    ).run()
    assert first.status == "awaiting_approval"

    resume = load_resume_state("ex_APR003", root=resume_root(str(tmp_path)))
    assert resume.checkpoint_node_id == "mid"
    assert "mid" in resume.node_outputs

    # Simulate approval decision at the store layer; scheduler only resumes.
    from scriptase.engine.approval import decide_checkpoint, APPROVED_STATUS
    from scriptase.engine.models import ExecutionRecord, NodeExecutionRecord

    decide_checkpoint(
        resume.checkpoint_id,
        decision=APPROVED_STATUS,
        decided_by="tester",
        root=approvals_root(str(tmp_path)),
    )

    record_doc = first.execution_record
    nodes = {}
    for node_id, raw in record_doc["nodes"].items():
        nodes[node_id] = NodeExecutionRecord(
            status=raw.get("status", "idle"),
            attempts=int(raw.get("attempts") or 0),
            duration_ms=raw.get("duration_ms"),
            outputs_summary=dict(raw.get("outputs_summary") or {}),
            artifact_refs=list(raw.get("artifact_refs") or []),
            logs=list(raw.get("logs") or []),
        )
    existing = ExecutionRecord(
        execution_id="ex_APR003",
        workflow_id=record_doc["workflow_id"],
        workflow_snapshot=record_doc["workflow_snapshot"],
        project_id="pm_APR003",
        run_mode="full",
        scope_node_ids=list(record_doc["scope_node_ids"]),
        status="awaiting_approval",
        started_at=record_doc["started_at"],
        nodes=nodes,
    )

    calls_after = []
    second = WorkflowScheduler(
        workflow,
        project_id="pm_APR003",
        lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path),
        executor_resolver=_resolver(calls_after),
        execution_id="ex_APR003",
        resume_state=resume,
        existing_record=existing,
        # Approved node must not re-trigger.
        checkpoint_after_node_ids=[],
    ).run()

    assert second.status == "succeeded"
    assert second.node_statuses["mid"] == "succeeded"
    assert second.node_statuses["viewer"] == "succeeded"
    # mid was restored from resume outputs — not re-executed.
    assert "mid" not in calls_after
    assert "viewer" in calls_after


# ---------------------------------------------------------------------------
# ExecutionManager + process restart
# ---------------------------------------------------------------------------


def test_execution_manager_releases_worker_on_checkpoint(tmp_path):
    manager = ExecutionManager(output_dir=str(tmp_path))
    workflow = _linear_stub_workflow(checkpoint_on=["mid"])
    before = _active_worker_count()
    execution_id, _ = manager.start(
        workflow,
        run_mode="full",
        target_node_ids=[],
        checkpoint_after_node_ids=["mid"],
    )
    record = _wait_settled(manager, execution_id)
    assert record["status"] == "awaiting_approval"
    assert record["finished_at"] is None

    # Worker that was draining this project must have exited.
    handle = manager.active.get(execution_id)
    if handle is not None and handle.thread is not None:
        assert not handle.thread.is_alive()

    # Drain thread released; no stuck worker held for the human.
    time.sleep(0.05)
    after = _active_worker_count()
    assert after <= before


def test_approval_survives_process_restart_and_resumes(tmp_path):
    """Simulate a full process restart: new manager, same disk, then approve."""
    output_dir = str(tmp_path)
    workflow = _linear_stub_workflow(checkpoint_on=["mid"], workflow_id="wf_RST001")

    manager1 = ExecutionManager(output_dir=output_dir)
    execution_id, project_id = manager1.start(
        workflow,
        run_mode="full",
        target_node_ids=[],
        checkpoint_after_node_ids=["mid"],
    )
    paused = _wait_settled(manager1, execution_id)
    assert paused["status"] == "awaiting_approval"
    checkpoint_id = paused["approval"]["checkpoint_id"]

    # Drop all in-memory state — new process.
    del manager1
    manager2 = ExecutionManager(output_dir=output_dir)

    # Disk still has the pause + resume point.
    disk = load_execution(execution_id, root=manager2.execution_root)
    assert disk["status"] == "awaiting_approval"
    resume = load_resume_state(execution_id, root=resume_root(output_dir))
    assert resume.checkpoint_node_id == "mid"
    assert resume.checkpoint_id == checkpoint_id

    status = manager2.approve(execution_id, decided_by="restart-test")
    assert status == "resuming"
    finished = _wait_settled(manager2, execution_id)
    assert finished["status"] == "succeeded"
    assert finished["nodes"]["mid"]["status"] == "succeeded"
    assert finished["nodes"]["viewer"]["status"] == "succeeded"
    assert finished["finished_at"] is not None


def test_reject_fails_execution(tmp_path):
    manager = ExecutionManager(output_dir=str(tmp_path))
    workflow = _linear_stub_workflow(checkpoint_on=["mid"])
    execution_id, _ = manager.start(
        workflow,
        run_mode="full",
        target_node_ids=[],
        checkpoint_after_node_ids=["mid"],
    )
    _wait_settled(manager, execution_id)
    status = manager.reject(execution_id, decided_by="tester")
    assert status == "failed"
    record = load_execution(execution_id, root=manager.execution_root)
    assert record["status"] == "failed"
    assert record["approval"]["status"] == "rejected"


def test_expired_checkpoint_refuses_approve(tmp_path):
    from scriptase.engine.approval import save_checkpoint

    manager = ExecutionManager(output_dir=str(tmp_path))
    workflow = _linear_stub_workflow(checkpoint_on=["mid"])
    execution_id, _ = manager.start(
        workflow,
        run_mode="full",
        target_node_ids=[],
        checkpoint_after_node_ids=["mid"],
    )
    record = _wait_settled(manager, execution_id)
    checkpoint_id = record["approval"]["checkpoint_id"]
    checkpoint = load_checkpoint(checkpoint_id, root=approvals_root(str(tmp_path)))
    checkpoint.expires_at = "2000-01-01T00:00:00+00:00"
    save_checkpoint(checkpoint, root=approvals_root(str(tmp_path)))

    with pytest.raises(Exception) as exc_info:
        manager.approve(execution_id, decided_by="late")
    assert getattr(exc_info.value, "code", None) == "APPROVAL_EXPIRED"
    failed = load_execution(execution_id, root=manager.execution_root)
    assert failed["status"] == "failed"


# ---------------------------------------------------------------------------
# Job orchestration
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    jobs_root = tmp_path / "jobs"
    channels_root = tmp_path / "channels"
    artifacts_root = tmp_path / "artifacts"
    jobs_root.mkdir()
    channels_root.mkdir()
    artifacts_root.mkdir()
    monkeypatch.setattr(job_store, "JOBS_DIR", str(jobs_root))
    monkeypatch.setattr(channel_store, "CHANNELS_DIR", str(channels_root))
    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", str(artifacts_root))
    return tmp_path


def test_derive_job_status_maps_awaiting_approval():
    assert derive_job_status("awaiting_approval") == "awaiting_approval"


def test_job_pauses_with_no_worker_survives_restart_and_resumes(isolated_stores, tmp_path):
    channel = create_channel(channel_default_draft(name="Approval channel"))
    workflow = _linear_stub_workflow(checkpoint_on=["mid"], workflow_id="wf_JOB001")
    # Inject graph via start_job(workflow=) so we do not need a saved workflow file.
    draft = default_draft(
        channel_id=channel.id,
        workflow_id="wf_JOB001",
        execution_mode="assisted",
        source={"mode": "paste", "pasted_script": "hello"},
    )
    job = create_job(draft)

    manager1 = ExecutionManager(output_dir=str(tmp_path / "engine"))
    started = start_job(
        job.id,
        manager=manager1,
        workflow=workflow,
        wait=True,
        timeout=10.0,
    )
    assert started.status == "awaiting_approval"
    assert started.status_reason in {"policy", "approval"}
    assert started.execution_id

    # Worker released.
    handle = manager1.active.get(started.execution_id)
    if handle is not None and handle.thread is not None:
        assert not handle.thread.is_alive()

    execution_id = started.execution_id

    # Process restart.
    del manager1
    manager2 = ExecutionManager(output_dir=str(tmp_path / "engine"))
    disk_job = get_job(job.id)
    # Job store still shows awaiting (synced before restart).
    assert disk_job.status == "awaiting_approval"
    disk_exec = load_execution(execution_id, root=manager2.execution_root)
    assert disk_exec["status"] == "awaiting_approval"

    resumed = approve_job(
        job.id,
        manager=manager2,
        decided_by="tester",
        wait=True,
        timeout=10.0,
    )
    assert resumed.status == "completed"
    final_exec = load_execution(execution_id, root=manager2.execution_root)
    assert final_exec["status"] == "succeeded"
    assert final_exec["nodes"]["viewer"]["status"] == "succeeded"
    assert final_exec["nodes"]["mid"]["status"] == "succeeded"


def test_reject_job_marks_failed(isolated_stores, tmp_path):
    channel = create_channel(channel_default_draft(name="Reject channel"))
    workflow = _linear_stub_workflow(checkpoint_on=["mid"], workflow_id="wf_REJ001")
    job = create_job(default_draft(
        channel_id=channel.id,
        workflow_id="wf_REJ001",
        execution_mode="assisted",
        source={"mode": "paste", "pasted_script": "x"},
    ))
    manager = ExecutionManager(output_dir=str(tmp_path / "engine"))
    start_job(job.id, manager=manager, workflow=workflow, wait=True, timeout=10.0)
    rejected = reject_job(job.id, manager=manager, decided_by="tester")
    assert rejected.status == "failed"
