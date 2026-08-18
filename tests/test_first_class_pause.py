"""Step 4.2: serial drain with a first-class, restart-safe user pause."""

from __future__ import annotations

import threading
import time

from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import load_execution, load_queue_record


def _workflow(workflow_id: str = "wf_PAU001") -> dict:
    nodes = []
    for index in (1, 2):
        nodes.append({
            "id": f"work{index}",
            "type": "trigger.manual",
            "type_version": 1,
            "name": f"work{index}",
            "position": {"x": index * 100, "y": 0},
            "configuration": {},
            "disabled": False,
        })
    return {
        "schema_version": 1,
        "workflow_id": workflow_id,
        "name": "Pause test",
        "description": "",
        "nodes": nodes,
        "edges": [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
    }


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def test_pause_holds_serial_slot_and_resume_keeps_completed_work(tmp_path):
    release_first = threading.Event()
    calls: list[tuple[str, str]] = []
    first_execution = {"id": ""}

    def resolver(node):
        def execute(_inputs, _config, context):
            calls.append((context.execution_id, node["id"]))
            if context.execution_id == first_execution["id"] and node["id"] == "work1":
                release_first.wait(timeout=5)
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(
        output_dir=str(tmp_path), executor_resolver=resolver, max_global_workers=1
    )
    first_execution["id"] = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_PAUSE1"
    )[0]
    _wait_for(lambda: (first_execution["id"], "work1") in calls)
    second = manager.start(
        _workflow("wf_PAU002"),
        run_mode="full",
        target_node_ids=[],
        project_id="pm_PAUSE2",
    )[0]

    assert manager.pause(first_execution["id"]) == "pausing"
    release_first.set()
    _wait_for(
        lambda: load_execution(first_execution["id"], root=manager.execution_root)["status"]
        == "paused"
    )
    _wait_for(
        lambda: load_queue_record(first_execution["id"], root=manager.queue_root)["status"]
        == "paused"
    )
    assert load_queue_record(first_execution["id"], root=manager.queue_root)["status"] == "paused"
    assert load_queue_record(second, root=manager.queue_root)["status"] == "pending"
    assert manager.running_count == 1
    assert manager.queue_position(first_execution["id"]) == 0
    assert manager.queue_position(second) == 1

    assert manager.resume(first_execution["id"]) == "resuming"
    _wait_for(
        lambda: load_execution(first_execution["id"], root=manager.execution_root)["status"]
        == "succeeded"
    )
    _wait_for(lambda: load_execution(second, root=manager.execution_root)["status"] == "succeeded")
    assert calls.count((first_execution["id"], "work1")) == 1
    assert calls.count((first_execution["id"], "work2")) == 1


def test_paused_slot_and_resume_state_survive_manager_restart(tmp_path):
    release_first = threading.Event()
    calls: list[tuple[str, str]] = []
    paused_id = {"value": ""}

    def resolver(node):
        def execute(_inputs, _config, context):
            calls.append((context.execution_id, node["id"]))
            if context.execution_id == paused_id["value"] and node["id"] == "work1":
                release_first.wait(timeout=5)
            return {"control": {"ok": True}}
        return execute

    manager1 = ExecutionManager(
        output_dir=str(tmp_path), executor_resolver=resolver, max_global_workers=1
    )
    paused_id["value"] = manager1.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_REST01"
    )[0]
    _wait_for(lambda: (paused_id["value"], "work1") in calls)
    manager1.pause(paused_id["value"])
    release_first.set()
    _wait_for(
        lambda: load_execution(paused_id["value"], root=manager1.execution_root)["status"]
        == "paused"
    )

    manager2 = ExecutionManager(
        output_dir=str(tmp_path), executor_resolver=resolver, max_global_workers=1
    )
    assert manager2.running_count == 1
    waiting = manager2.start(
        _workflow("wf_PAU003"),
        run_mode="full",
        target_node_ids=[],
        project_id="pm_REST02",
    )[0]
    time.sleep(0.05)
    assert load_queue_record(waiting, root=manager2.queue_root)["status"] == "pending"

    manager2.resume(paused_id["value"])
    _wait_for(
        lambda: load_execution(paused_id["value"], root=manager2.execution_root)["status"]
        == "succeeded"
    )
    _wait_for(lambda: load_execution(waiting, root=manager2.execution_root)["status"] == "succeeded")
    assert calls.count((paused_id["value"], "work1")) == 1
