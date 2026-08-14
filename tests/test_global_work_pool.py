"""Step 3.5: bounded global work pool with per-project FIFO ordering.

Done when: N concurrent Jobs never exceed the configured global worker ceiling
while preserving per-project ordering.
"""

from __future__ import annotations

import threading
import time

from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import load_execution, load_queue_record


def _workflow(name: str = "Pool test"):
    return {
        "schema_version": 1,
        "name": name,
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


def _wait_for(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def _wait_done(manager: ExecutionManager, execution_id: str, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            record = load_execution(execution_id, root=manager.execution_root)
        except FileNotFoundError:
            time.sleep(0.01)
            continue
        if record.get("status") in {"succeeded", "failed", "cancelled", "partial"}:
            return record
        handle = manager.active.get(execution_id)
        if handle is not None and handle.thread is not None and handle.thread.is_alive():
            handle.thread.join(timeout=0.05)
            continue
        time.sleep(0.01)
    raise AssertionError(f"execution {execution_id} did not finish within {timeout}s")


def test_global_ceiling_caps_concurrent_projects(tmp_path):
    """More ready projects than max_global_workers never overruns the ceiling."""
    release = threading.Event()
    state_lock = threading.Lock()
    active = {"n": 0}
    peak = {"n": 0}
    started = []

    def resolver(_node):
        def execute(_inputs, _config, context):
            with state_lock:
                active["n"] += 1
                peak["n"] = max(peak["n"], active["n"])
                started.append(context.project_id)
            release.wait(timeout=4)
            with state_lock:
                active["n"] -= 1
            return {"control": {"ok": True}}
        return execute

    ceiling = 2
    manager = ExecutionManager(
        output_dir=str(tmp_path),
        executor_resolver=resolver,
        max_global_workers=ceiling,
    )
    projects = [f"pm_POOL{i:02d}" for i in range(5)]
    execution_ids = [
        manager.start(
            _workflow(), run_mode="full", target_node_ids=[], project_id=project
        )[0]
        for project in projects
    ]

    _wait_for(lambda: len(started) == ceiling)
    time.sleep(0.05)
    assert peak["n"] <= ceiling
    assert manager.running_count <= ceiling
    # The remaining three stay pending until a slot frees.
    pending_statuses = [
        load_queue_record(eid, root=manager.queue_root)["status"]
        for eid in execution_ids
    ]
    assert pending_statuses.count("running") == ceiling
    assert pending_statuses.count("pending") == len(projects) - ceiling

    release.set()
    for eid in execution_ids:
        _wait_done(manager, eid)
    assert peak["n"] == ceiling
    assert set(started) == set(projects)
    assert manager.running_count == 0


def test_per_project_fifo_preserved_under_global_pool(tmp_path):
    """Same-project runs stay serial (FIFO) even when the pool has free slots."""
    release = threading.Event()
    state_lock = threading.Lock()
    order = []
    active_for_project = {"n": 0}
    peak_for_project = {"n": 0}

    def resolver(_node):
        def execute(_inputs, _config, context):
            with state_lock:
                active_for_project["n"] += 1
                peak_for_project["n"] = max(
                    peak_for_project["n"], active_for_project["n"]
                )
                order.append(context.execution_id)
            release.wait(timeout=4)
            with state_lock:
                active_for_project["n"] -= 1
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(
        output_dir=str(tmp_path),
        executor_resolver=resolver,
        max_global_workers=4,
    )
    project = "pm_FIFO01"
    first, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id=project
    )
    second, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id=project
    )
    third, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id=project
    )

    _wait_for(lambda: order == [first])
    assert load_queue_record(second, root=manager.queue_root)["status"] == "pending"
    assert load_queue_record(third, root=manager.queue_root)["status"] == "pending"
    assert peak_for_project["n"] == 1

    release.set()
    for eid in (first, second, third):
        _wait_done(manager, eid)

    assert order == [first, second, third]
    assert peak_for_project["n"] == 1


def test_different_projects_run_concurrently_up_to_ceiling(tmp_path):
    """Two different projects may run at once when the ceiling allows it."""
    barrier = threading.Barrier(2)

    def resolver(_node):
        def execute(_inputs, _config, context):
            barrier.wait(timeout=3)
            return {"control": {"ok": True, "project_id": context.project_id}}
        return execute

    manager = ExecutionManager(
        output_dir=str(tmp_path),
        executor_resolver=resolver,
        max_global_workers=2,
    )
    a, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_AAA001"
    )
    b, _ = manager.start(
        _workflow(), run_mode="full", target_node_ids=[], project_id="pm_BBB001"
    )
    for eid in (a, b):
        record = _wait_done(manager, eid)
        assert record["status"] == "succeeded"
