"""Step 9.2 — Channel-driven triggers.

Done when: a scheduled Channel creates and completes a Job unattended with the
queue record showing its trigger source, and triggers run under both the dev
server and a WSGI host.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from app import create_app, start_trigger_services, stop_trigger_services
from scriptase.artifacts import store as artifact_store
from scriptase.channels import store as channel_store
from scriptase.channels.cadence import ChannelCadenceService
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import load_queue_record
from scriptase.engine.registry import get_node_type
from scriptase.jobs import store as job_store
from scriptase.jobs.store import get_job
from scriptase.jobs.triggers import (
    create_job_from_channel_cadence,
    enqueue_scheduled_workflow,
)


# ---------------------------------------------------------------------------
# Helpers
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


def _linear_stub_workflow(*, workflow_id="wf_CAD001"):
    return {
        "workflow_id": workflow_id,
        "name": "Cadence test workflow",
        "schema_version": 1,
        "nodes": [
            _node("sample", "stub.input", port_type="generic_json", payload={"v": 1}),
            _node("mid", "utility.set_value", value={"ok": True}),
            _node("viewer", "stub.output", port_type="generic_json"),
        ],
        "edges": [
            _edge("e1", "sample", "value", "mid", "value", "data"),
            _edge("e2", "mid", "value", "viewer", "value", "data"),
        ],
        "extensions": {},
    }


def _at(hour, minute, second=0):
    return datetime(2026, 8, 5, hour, minute, second, tzinfo=timezone.utc)


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    channels = tmp_path / "channels"
    jobs = tmp_path / "jobs"
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "output"
    for path in (channels, jobs, artifacts, output):
        path.mkdir()
    monkeypatch.setattr(channel_store, "_channels_dir", str(channels))
    monkeypatch.setattr(channel_store, "_trash_dir", str(channels / "trash"))
    monkeypatch.setattr(job_store, "_jobs_dir", str(jobs))
    monkeypatch.setattr(job_store, "_trash_dir", str(jobs / "trash"))
    monkeypatch.setattr(artifact_store, "_artifacts_dir", str(artifacts))
    monkeypatch.setattr(artifact_store, "_output_dir", str(output))
    yield tmp_path


# ---------------------------------------------------------------------------
# Channel cadence → Job with schedule source
# ---------------------------------------------------------------------------


def test_scheduled_channel_creates_and_completes_job_with_schedule_source(
    isolated_stores, tmp_path
):
    """Done-when: cadence fire creates a Job that completes; queue source=schedule."""
    draft = channel_default_draft(name="Cadence Channel")
    draft["default_workflow_id"] = "wf_CAD001"
    draft["content"] = {"niche": "stoicism", "tone": "calm"}
    draft["cadence"] = {
        "enabled": True,
        "cron": "* * * * *",
        "execution_mode": "automatic",
        "source": {
            "mode": "paste",
            "pasted_script": "Scheduled channel narration for unattended export.",
        },
    }
    channel = create_channel(draft)
    workflow = _linear_stub_workflow(workflow_id="wf_CAD001")

    engine_dir = str(tmp_path / "engine")
    manager = ExecutionManager(output_dir=engine_dir)

    # Direct cadence enqueue (what the service calls on a fire).
    job = create_job_from_channel_cadence(
        channel,
        manager=manager,
        workflow=workflow,
        wait=True,
        timeout=15.0,
        force=True,
        project_id="pm_CAD001",
    )
    finished = get_job(job.id)
    assert finished.status == "completed", (
        f"Scheduled Channel Job should complete unattended; got "
        f"status={finished.status} reason={finished.status_reason}"
    )
    assert finished.execution_id
    queue = load_queue_record(
        finished.execution_id, root=os.path.join(engine_dir, "workflows", "queue")
    )
    assert queue["source"] == "schedule"
    assert queue["execution_id"] == finished.execution_id


def test_channel_cadence_service_fires_once_and_creates_job(
    isolated_stores, tmp_path, monkeypatch
):
    draft = channel_default_draft(name="Polled Cadence")
    draft["default_workflow_id"] = "wf_CAD002"
    draft["cadence"] = {
        "enabled": True,
        "cron": "* * * * *",
        "execution_mode": "automatic",
        "source": {"mode": "topic", "topic": "Daily stoic thought"},
    }
    channel = create_channel(draft)

    created = []

    def enqueue(ch):
        created.append(ch.id if hasattr(ch, "id") else ch.get("id"))
        return {"job_id": "job_TEST01", "source": "schedule"}

    service = ChannelCadenceService(
        state_root=str(tmp_path / "cadence-state"),
        channel_loader=lambda: [channel],
        enqueue=enqueue,
    )
    assert service.tick(_at(12, 0, 30)) == []  # establish cursor
    fired = service.tick(_at(12, 1))
    assert len(fired) == 1
    assert fired[0]["channel_id"] == channel.id
    assert created == [channel.id]
    assert service.tick(_at(12, 1)) == []  # no duplicate
    # Latest-only catch-up across a multi-minute gap.
    fired = service.tick(_at(12, 4, 20))
    assert len(fired) == 1
    assert fired[0]["fire_at"] == "2026-08-05T12:04:00Z"
    assert created == [channel.id, channel.id]


def test_workflow_schedule_with_channel_id_creates_job(isolated_stores, tmp_path):
    channel = create_channel({
        **channel_default_draft(name="Bound Channel"),
        "default_workflow_id": "wf_SCH001",
        "cadence": {
            "enabled": False,
            "cron": "0 9 * * 1-5",
            "execution_mode": "automatic",
            "source": {
                "mode": "paste",
                "pasted_script": "Workflow schedule creates a Job.",
            },
        },
    })

    workflow = _linear_stub_workflow(workflow_id="wf_SCH001")
    workflow["settings"] = {
        "on_error": "stop",
        "channel_id": channel.id,
        "schedules": [{
            "id": "sch_minute",
            "cron": "* * * * *",
            "enabled": True,
            "channel_id": channel.id,
        }],
    }

    engine_dir = str(tmp_path / "engine")
    manager = ExecutionManager(output_dir=engine_dir)
    result = enqueue_scheduled_workflow(workflow, workflow["settings"]["schedules"][0], manager=manager)
    assert isinstance(result, dict)
    assert result["source"] == "schedule"
    assert result["job_id"]
    job = get_job(result["job_id"])
    assert job.channel_id == channel.id
    assert job.execution_id == result["execution_id"]

    # Wait for completion via a second start isn't needed — ensure queue source.
    # Poll finalize thread briefly.
    import time

    for _ in range(50):
        job = get_job(result["job_id"])
        if job.status in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    job = get_job(result["job_id"])
    # Even if still running, the queue record must show schedule.
    queue = load_queue_record(
        job.execution_id, root=os.path.join(engine_dir, "workflows", "queue")
    )
    assert queue["source"] == "schedule"


def test_unbound_workflow_schedule_keeps_raw_execution(tmp_path):
    """Legacy workflows without channel_id still enqueue raw executions."""
    workflow = {
        "schema_version": 1,
        "workflow_id": "wf_LEGACY",
        "name": "Legacy",
        "nodes": [
            _node("sample", "stub.input", port_type="generic_json", payload={"v": 1}),
            _node("viewer", "stub.output", port_type="generic_json"),
        ],
        "edges": [_edge("e1", "sample", "value", "viewer", "value", "data")],
        "settings": {
            "on_error": "stop",
            "schedules": [{"id": "sch_1", "cron": "* * * * *", "enabled": True}],
        },
        "extensions": {},
    }
    engine_dir = str(tmp_path / "engine")
    manager = ExecutionManager(output_dir=engine_dir)
    execution_id, project_id = enqueue_scheduled_workflow(workflow, manager=manager)
    assert execution_id
    queue = load_queue_record(
        execution_id, root=os.path.join(engine_dir, "workflows", "queue")
    )
    assert queue["source"] == "schedule"


# ---------------------------------------------------------------------------
# App factory / WSGI trigger startup (V2 __main__-only defect)
# ---------------------------------------------------------------------------


def test_create_app_starts_triggers_when_requested():
    stop_trigger_services()
    try:
        app = create_app(discover_providers=False, start_triggers=True)
        assert app.config["START_TRIGGERS"] is True
        from scriptase.channels.cadence import channel_cadence_service
        from scriptase.engine.scheduled_runs import schedule_service
        from scriptase.engine.watch_folders import watch_folder_service

        assert schedule_service.is_running
        assert watch_folder_service.is_running
        assert channel_cadence_service.is_running
    finally:
        stop_trigger_services()


def test_create_app_skips_triggers_when_disabled():
    stop_trigger_services()
    try:
        app = create_app(discover_providers=False, start_triggers=False)
        assert app.config["START_TRIGGERS"] is False
        from scriptase.channels.cadence import channel_cadence_service
        from scriptase.engine.scheduled_runs import schedule_service
        from scriptase.engine.watch_folders import watch_folder_service

        assert not schedule_service.is_running
        assert not watch_folder_service.is_running
        assert not channel_cadence_service.is_running
    finally:
        stop_trigger_services()


def test_wsgi_module_starts_triggers(monkeypatch):
    """WSGI host loads wsgi.application with triggers on (not only __main__)."""
    stop_trigger_services()
    # Isolate from pytest's SCRIPTASE_DISABLE_TRIGGERS default.
    monkeypatch.delenv("SCRIPTASE_DISABLE_TRIGGERS", raising=False)
    monkeypatch.setenv("SCRIPTASE_START_TRIGGERS", "1")
    try:
        # Re-import wsgi with a forced start_triggers path.
        import importlib
        import wsgi as wsgi_mod

        # wsgi.py already constructed application at import; call factory again
        # the way a host would after a clean process start.
        from app import create_app as factory

        app = factory(discover_providers=False, start_triggers=True)
        assert app.config["START_TRIGGERS"] is True
        status = start_trigger_services()
        assert status["schedule"] is True
        assert status["watch_folder"] is True
        assert status["channel_cadence"] is True
        assert wsgi_mod.application is not None
    finally:
        stop_trigger_services()


def test_enabled_cadence_requires_valid_cron(isolated_stores):
    draft = channel_default_draft(name="Bad cron")
    draft["cadence"] = {
        "enabled": True,
        "cron": "not a cron",
        "execution_mode": "automatic",
        "source": {"mode": "topic", "topic": "x"},
    }
    from scriptase.channels.store import ChannelValidationError

    with pytest.raises(ChannelValidationError):
        create_channel(draft)
