"""Step 13.1: Jobs run strictly in queue, each showing its place in line.

Done when: three Jobs started together execute strictly one after another,
each showing its queue position, and raising the override restores concurrency.
"""

from __future__ import annotations

import importlib
import threading
import time

import config
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import load_queue_record


def _workflow(name: str = "Serial queue test"):
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


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def _drain(manager: ExecutionManager, execution_ids, timeout: float = 6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        statuses = [
            load_queue_record(eid, root=manager.queue_root)["status"]
            for eid in execution_ids
        ]
        if all(status in {"done", "failed", "cancelled"} for status in statuses):
            _wait_for(lambda: manager.running_count == 0)
            return
        time.sleep(0.01)
    raise AssertionError("queue did not drain")


def test_default_global_workers_is_one():
    """The shipped default runs Jobs strictly in submission order."""
    assert config.GLOBAL_WORK_POOL_SIZE == 1
    assert ExecutionManager(output_dir="ignored").max_global_workers == 1


def test_env_override_still_sets_the_ceiling(monkeypatch):
    """SCRIPTASE_GLOBAL_WORKERS remains the escape hatch out of serial mode."""
    monkeypatch.setenv("SCRIPTASE_GLOBAL_WORKERS", "4")
    try:
        assert importlib.reload(config).GLOBAL_WORK_POOL_SIZE == 4
    finally:
        monkeypatch.delenv("SCRIPTASE_GLOBAL_WORKERS", raising=False)
        importlib.reload(config)
    assert config.GLOBAL_WORK_POOL_SIZE == 1


def test_three_jobs_run_strictly_one_after_another(tmp_path):
    """Three runs submitted together never overlap and keep submission order."""
    release = threading.Event()
    state_lock = threading.Lock()
    active = {"n": 0}
    peak = {"n": 0}
    order = []

    def resolver(_node):
        def execute(_inputs, _config, context):
            with state_lock:
                active["n"] += 1
                peak["n"] = max(peak["n"], active["n"])
                order.append(context.execution_id)
            release.wait(timeout=5)
            with state_lock:
                active["n"] -= 1
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(
        output_dir=str(tmp_path), executor_resolver=resolver, max_global_workers=1
    )
    # Three *different* projects: without the serial ceiling these would run
    # concurrently, so this proves the ceiling and not the per-project FIFO.
    execution_ids = [
        manager.start(
            _workflow(), run_mode="full", target_node_ids=[], project_id=f"pm_SER{i:03d}"
        )[0]
        for i in range(3)
    ]

    _wait_for(lambda: len(order) == 1)
    time.sleep(0.05)
    assert peak["n"] == 1

    # Each waiting run knows its place: 1 and 2 behind the one holding the pool.
    status = manager.queue_status()
    assert status["max_global_workers"] == 1
    assert status["waiting"] == 2
    assert status["positions"][execution_ids[0]] == 0
    assert status["positions"][execution_ids[1]] == 1
    assert status["positions"][execution_ids[2]] == 2

    release.set()
    _drain(manager, execution_ids)
    assert order == execution_ids
    assert peak["n"] == 1


def test_waiting_runs_are_told_when_their_place_moves(tmp_path):
    """Queue position is pushed down each waiting run's own SSE stream."""
    gates = [threading.Event() for _ in range(3)]
    started = []
    state_lock = threading.Lock()

    def resolver(_node):
        def execute(_inputs, _config, context):
            with state_lock:
                index = len(started)
                started.append(context.execution_id)
            gates[index].wait(timeout=5)
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(
        output_dir=str(tmp_path), executor_resolver=resolver, max_global_workers=1
    )
    execution_ids = [
        manager.start(
            _workflow(), run_mode="full", target_node_ids=[], project_id=f"pm_SSE{i:03d}"
        )[0]
        for i in range(3)
    ]
    _wait_for(lambda: len(started) == 1)

    def positions_for(execution_id):
        """(queue_position, queue_waiting) from this run's own SSE frames."""
        buffer = manager.events.get(execution_id)
        return [
            (event["queue_position"], event["queue_waiting"])
            for event in buffer.replay(0).events
            if event.get("type") == "queue_position"
        ]

    assert positions_for(execution_ids[0]) == []             # never waited
    # The second run was alone in line until the third joined behind it.
    assert positions_for(execution_ids[1]) == [(1, 1), (1, 2)]
    assert positions_for(execution_ids[2]) == [(2, 2)]

    # First run finishes: the last run moves up without doing anything itself.
    gates[0].set()
    _wait_for(lambda: positions_for(execution_ids[2]) == [(2, 2), (1, 1)])
    assert positions_for(execution_ids[1]) == [(1, 1), (1, 2)]

    for gate in gates:
        gate.set()
    _drain(manager, execution_ids)


def test_cancelling_a_waiting_run_moves_the_rest_up(tmp_path):
    """Cancelling out of the middle of the line re-numbers what is behind it."""
    release = threading.Event()
    started = []

    def resolver(_node):
        def execute(_inputs, _config, context):
            started.append(context.execution_id)
            release.wait(timeout=5)
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(
        output_dir=str(tmp_path), executor_resolver=resolver, max_global_workers=1
    )
    execution_ids = [
        manager.start(
            _workflow(), run_mode="full", target_node_ids=[], project_id=f"pm_CAN{i:03d}"
        )[0]
        for i in range(3)
    ]
    _wait_for(lambda: len(started) == 1)
    assert manager.queue_position(execution_ids[2]) == 2

    manager.cancel_pending(execution_ids[1])
    assert manager.queue_position(execution_ids[1]) is None
    assert manager.queue_position(execution_ids[2]) == 1

    release.set()
    _drain(manager, [execution_ids[0], execution_ids[2]])


def test_raising_the_ceiling_restores_concurrency(tmp_path):
    """The same three runs overlap once the override lifts the ceiling."""
    barrier = threading.Barrier(3)

    def resolver(_node):
        def execute(_inputs, _config, _context):
            barrier.wait(timeout=5)
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(
        output_dir=str(tmp_path), executor_resolver=resolver, max_global_workers=3
    )
    execution_ids = [
        manager.start(
            _workflow(), run_mode="full", target_node_ids=[], project_id=f"pm_CON{i:03d}"
        )[0]
        for i in range(3)
    ]
    # The barrier only clears if all three hold a pool slot at the same time.
    _drain(manager, execution_ids)
    for execution_id in execution_ids:
        assert load_queue_record(execution_id, root=manager.queue_root)["status"] == "done"
