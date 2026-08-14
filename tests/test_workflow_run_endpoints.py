"""Step 3.5: async runs, cooperative stop, sample provenance, and SSE replay."""

from __future__ import annotations

import json
import threading
import time

import pytest
from flask import Flask

import scriptase.engine.routes as workflow_routes
from scriptase.engine import workflows_bp
from scriptase.engine.events import ExecutionEventBuffer
from scriptase.engine.execution import ExecutionManager


def _node(node_id, node_type, configuration=None):
    return {
        "id": node_id,
        "type": node_type,
        "type_version": 1,
        "name": node_id,
        "position": {"x": 0, "y": 0},
        "configuration": configuration or {},
        "disabled": False,
    }


def _workflow(nodes, edges=None):
    return {
        "schema_version": 1,
        "name": "Execution test",
        "description": "",
        "nodes": nodes,
        "edges": edges or [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
    }


def _stub_workflow():
    return _workflow(
        [
            _node("sample", "stub.input", {"port_type": "generic_json", "payload": {"answer": 42}}),
            _node("viewer", "stub.output", {"port_type": "generic_json"}),
        ],
        [{
            "id": "edge_1",
            "source_node": "sample",
            "source_port": "value",
            "target_node": "viewer",
            "target_port": "value",
            "edge_type": "data",
        }],
    )


def _wait(manager, execution_id):
    handle = manager.active.get(execution_id)
    assert handle is not None
    handle.thread.join(timeout=5)
    assert not handle.thread.is_alive()


def test_isolated_stub_run_persists_sample_provenance(tmp_path):
    manager = ExecutionManager(output_dir=str(tmp_path))
    execution_id, _ = manager.start(
        _stub_workflow(), run_mode="node_isolated", target_node_ids=["viewer"]
    )
    _wait(manager, execution_id)
    record = manager.active.get(execution_id).scheduler.record.to_dict()
    assert record["status"] == "succeeded"
    assert record["scope_node_ids"] == ["sample", "viewer"]
    assert record["nodes"]["sample"]["from_sample_data"] is True
    assert record["nodes"]["viewer"]["from_sample_data"] is True
    events = manager.events.get(execution_id).replay(0).events
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["status"] == "succeeded"
    assert events[-1]["node_id"] is None
    viewer_events = [event for event in events if event.get("node_id") == "viewer"]
    assert viewer_events and all(event["from_sample_data"] for event in viewer_events)


def test_cooperative_stop_cannot_transition_back_to_success(tmp_path):
    started = threading.Event()

    def resolver(node):
        def execute(inputs, config, context):
            started.set()
            while not context.stop_requested():
                time.sleep(0.005)
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(output_dir=str(tmp_path), executor_resolver=resolver)
    execution_id, _ = manager.start(
        _workflow([_node("slow", "trigger.manual")]),
        run_mode="full",
        target_node_ids=[],
    )
    assert started.wait(timeout=2)
    assert manager.stop(execution_id) == "cancelling"
    _wait(manager, execution_id)
    record = manager.active.get(execution_id).scheduler.record.to_dict()
    assert record["status"] == "cancelled"
    statuses = [event["status"] for event in manager.events.get(execution_id).replay(0).events]
    assert statuses[-1] == "cancelled"
    assert "succeeded" not in statuses[statuses.index("cancelling") + 1:]


def test_event_buffer_replays_after_id_and_resets_stale_cursor():
    stream = ExecutionEventBuffer("ex_ABC123", max_events=3)
    for index in range(5):
        stream.emit({"node_id": "node", "status": "running", "summary": str(index)})
    stream.emit({"node_id": None, "status": "succeeded"})
    replay = stream.replay(1, snapshot=lambda: {"status": "running"}).events
    assert replay[0]["status"] == "reset"
    assert replay[0]["sequence"] == 3
    assert [event["sequence"] for event in replay[1:]] == [4, 5, 6]
    assert [event["sequence"] for event in stream.replay(4).events] == [5, 6]


@pytest.fixture
def client(tmp_path, monkeypatch):
    manager = ExecutionManager(output_dir=str(tmp_path))
    monkeypatch.setattr(workflow_routes, "execution_manager", manager)
    monkeypatch.setattr(
        workflow_routes,
        "load_execution",
        lambda execution_id: manager.active.get(execution_id).scheduler.record.to_dict(),
    )
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    return app.test_client(), manager


def test_run_events_and_terminal_stop_endpoint(client):
    http, manager = client
    response = http.post("/api/workflow/run", json={
        "workflow": _stub_workflow(),
        "run_mode": "node_isolated",
        "target_node_ids": ["viewer"],
    })
    assert response.status_code == 202
    execution_id = response.get_json()["execution_id"]
    _wait(manager, execution_id)

    response = http.get(f"/api/workflow/executions/{execution_id}/events")
    assert response.status_code == 200
    frames = [part for part in response.get_data(as_text=True).split("\n\n") if part]
    data = [json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: "))) for frame in frames]
    assert data[-1]["status"] == "succeeded"
    assert [event["sequence"] for event in data] == sorted({event["sequence"] for event in data})

    replay = http.get(
        f"/api/workflow/executions/{execution_id}/events",
        headers={"Last-Event-ID": str(data[-2]["sequence"])},
    )
    replay_frames = [part for part in replay.get_data(as_text=True).split("\n\n") if "data: " in part]
    replay_data = [
        json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
        for frame in replay_frames
    ]
    assert [event["sequence"] for event in replay_data] == [data[-1]["sequence"]]

    response = http.post(f"/api/workflow/executions/{execution_id}/stop", json={})
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "EXECUTION_TERMINAL"


def test_stop_endpoint_cancels_an_active_run(tmp_path, monkeypatch):
    started = threading.Event()

    def resolver(node):
        def execute(inputs, config, context):
            started.set()
            while not context.stop_requested():
                time.sleep(0.005)
            return {"control": {"ok": True}}
        return execute

    manager = ExecutionManager(output_dir=str(tmp_path), executor_resolver=resolver)
    monkeypatch.setattr(workflow_routes, "execution_manager", manager)
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    http = app.test_client()
    response = http.post("/api/workflow/run", json={
        "workflow": _workflow([_node("slow", "trigger.manual")]),
        "run_mode": "full",
        "target_node_ids": [],
    })
    execution_id = response.get_json()["execution_id"]
    assert started.wait(timeout=2)
    response = http.post(f"/api/workflow/executions/{execution_id}/stop", json={})
    assert response.status_code == 202
    assert response.get_json()["status"] == "cancelling"
    _wait(manager, execution_id)
    assert manager.active.get(execution_id).scheduler.record.status == "cancelled"
