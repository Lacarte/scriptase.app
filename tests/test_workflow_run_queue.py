"""Step 7.1: persisted, per-project workflow run queue."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from flask import Flask

import scriptase.engine.routes as workflow_routes
from scriptase.engine import workflows_bp
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import list_executions, load_execution, load_queue_record


def _workflow():
    return {
        "schema_version": 1,
        "name": "Queue test",
        "description": "",
        "nodes": [{
            "id": "work",
            "type": "trigger.manual",
            "type_version": 1,
            "name": "work",
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


def _wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def _join_handle(manager, execution_id, timeout=5):
    """Wait until the pool assigns a worker (if needed), then join it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        handle = manager.active.get(execution_id)
        if handle is None:
            return
        # Terminal records mean the worker already finished and may have been
        # reaped; treat as done.
        try:
            status = load_queue_record(execution_id, root=manager.queue_root)["status"]
        except Exception:
            status = None
        if status in {"done", "failed", "cancelled"}:
            if handle.thread is not None and handle.thread.is_alive():
                handle.thread.join(timeout=max(0.0, deadline - time.monotonic()))
            return
        if handle.thread is not None:
            handle.thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if not handle.thread.is_alive():
                return
            continue
        time.sleep(0.005)
    raise AssertionError(f"execution {execution_id} did not finish within {timeout}s")


def test_same_project_serializes_while_different_projects_run_concurrently(tmp_path):
    release = threading.Event()
    state_lock = threading.Lock()
    active_by_project = {}
    maximum_by_project = {}
    started_by_project = {}

    def resolver(_node):
        def execute(_inputs, _config, context):
            with state_lock:
                project = context.project_id
                active_by_project[project] = active_by_project.get(project, 0) + 1
                maximum_by_project[project] = max(
                    maximum_by_project.get(project, 0), active_by_project[project]
                )
                started_by_project[project] = started_by_project.get(project, 0) + 1
            release.wait(timeout=3)
            with state_lock:
                active_by_project[project] -= 1
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(output_dir=str(tmp_path), executor_resolver=resolver)
    first, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_ABC123"
    )
    second, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_ABC123"
    )
    other, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_DEF456"
    )

    _wait_for(lambda: started_by_project.get("pm_ABC123") == 1)
    _wait_for(lambda: started_by_project.get("pm_DEF456") == 1)
    assert load_queue_record(second, root=manager.queue_root)["status"] == "pending"
    assert load_queue_record(first, root=manager.queue_root)["status"] == "running"
    assert load_queue_record(other, root=manager.queue_root)["status"] == "running"

    release.set()
    _join_handle(manager, second)
    _join_handle(manager, other)
    assert maximum_by_project == {"pm_ABC123": 1, "pm_DEF456": 1}
    assert started_by_project == {"pm_ABC123": 2, "pm_DEF456": 1}
    assert load_queue_record(second, root=manager.queue_root)["status"] == "done"


def test_concurrent_projects_isolate_events_records_history_and_artifacts(tmp_path):
    workflow = _workflow()
    workflow["workflow_id"] = "wf_CONCUR"
    rendezvous = threading.Barrier(2)

    def resolver(_node):
        def execute(_inputs, _config, context):
            # Neither run can pass this point unless both project workers are
            # executing at the same time.
            rendezvous.wait(timeout=2)
            artifact_ref = (
                f"projects/{context.project_id}/"
                f"concurrent-{context.execution_id}.txt"
            )
            staged = context.stage_artifact(artifact_ref)
            Path(staged).write_text(
                f"{context.project_id}:{context.execution_id}", encoding="utf-8"
            )
            return {"control": {
                "ok": True,
                "project_id": context.project_id,
                "execution_id": context.execution_id,
                "artifact_refs": [artifact_ref],
            }}
        return execute

    manager = ExecutionManager(output_dir=str(tmp_path), executor_resolver=resolver)
    projects = ("pm_ABC123", "pm_DEF456")
    execution_ids = [
        manager.start(
            workflow, run_mode="full", target_node_ids=[], project_id=project_id
        )[0]
        for project_id in projects
    ]

    for execution_id in execution_ids:
        _join_handle(manager, execution_id)
        handle = manager.active.get(execution_id)
        if handle is not None and handle.thread is not None:
            assert not handle.thread.is_alive()

    records = {
        execution_id: load_execution(execution_id, root=manager.execution_root)
        for execution_id in execution_ids
    }
    for execution_id, project_id in zip(execution_ids, projects):
        record = records[execution_id]
        expected_ref = f"projects/{project_id}/concurrent-{execution_id}.txt"
        assert record["execution_id"] == execution_id
        assert record["project_id"] == project_id
        assert record["status"] == "succeeded"
        assert record["nodes"]["work"]["artifact_refs"] == [expected_ref]
        assert (tmp_path / expected_ref).read_text(encoding="utf-8") == (
            f"{project_id}:{execution_id}"
        )

        replay = manager.events.get(execution_id).replay(0)
        assert replay.terminal is True
        assert [event["sequence"] for event in replay.events] == list(
            range(1, len(replay.events) + 1)
        )
        assert {event["execution_id"] for event in replay.events} == {execution_id}

    history, total = list_executions(
        "wf_CONCUR", root=manager.execution_root
    )
    assert total == 2
    assert {
        (item["execution_id"], item["project_id"], item["status"])
        for item in history
    } == {
        (execution_ids[0], projects[0], "succeeded"),
        (execution_ids[1], projects[1], "succeeded"),
    }


def test_pending_run_can_be_cancelled_and_never_executes(tmp_path):
    first_started = threading.Event()
    release = threading.Event()
    calls = []

    def resolver(_node):
        def execute(_inputs, _config, context):
            calls.append(context.execution_id)
            first_started.set()
            release.wait(timeout=3)
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(output_dir=str(tmp_path), executor_resolver=resolver)
    first, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_ABC123"
    )
    assert first_started.wait(timeout=2)
    pending, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_ABC123"
    )

    assert manager.cancel_pending(pending) == "cancelled"
    assert load_queue_record(pending, root=manager.queue_root)["status"] == "cancelled"
    assert load_execution(pending, root=manager.execution_root)["status"] == "cancelled"
    release.set()
    _join_handle(manager, first)
    assert calls == [first]


def test_queue_record_persists_source_and_requested_mode(tmp_path):
    manager = ExecutionManager(output_dir=str(tmp_path))
    execution_id, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], source="webhook"
    )
    _join_handle(manager, execution_id)
    item = load_queue_record(execution_id, root=manager.queue_root)
    assert item["source"] == "webhook"
    assert item["requested_run_mode"] == "full"
    assert item["status"] == "done"
    assert item["requested_at"]
    assert item["started_at"]
    assert item["finished_at"]


def test_queue_endpoints_list_and_cancel_pending(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def resolver(_node):
        def execute(_inputs, _config, _context):
            started.set()
            release.wait(timeout=3)
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(output_dir=str(tmp_path), executor_resolver=resolver)
    monkeypatch.setattr(workflow_routes, "execution_manager", manager)
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    http = app.test_client()

    first, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_ABC123"
    )
    assert started.wait(timeout=2)
    pending, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_ABC123"
    )
    workflow_id = manager.active.get(pending).queue_record.workflow_id

    response = http.get("/api/workflow/queue", query_string={"workflow_id": workflow_id})
    assert response.status_code == 200
    assert response.get_json()["queue"][0]["status"] == "pending"
    response = http.post(f"/api/workflow/queue/{pending}/cancel", json={})
    assert response.status_code == 202
    assert response.get_json()["status"] == "cancelled"

    release.set()
    _join_handle(manager, first)
