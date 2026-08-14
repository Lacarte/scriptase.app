"""Step 10.4 — Observability: trigger loops and notification dispatch log failures.

Done when: blanket silent exception handlers in the watch-folder loop, schedule
loop, channel cadence loop, and notification delivery no longer swallow errors
without a log line.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from loguru import logger

import scriptase.engine.notifications as notification_service
from scriptase.channels.cadence import ChannelCadenceService
from scriptase.engine.notifications import dispatch_run_notification
from scriptase.engine.scheduled_runs import ScheduleService
from scriptase.engine.watch_folders import WatchFolderService


@pytest.fixture
def captured_logs():
    """Capture loguru sink messages for the duration of one test."""
    messages: list[str] = []

    def _sink(message) -> None:
        # ``message`` is a loguru Message; str() yields the formatted line.
        messages.append(str(message))

    handler_id = logger.add(_sink, format="{level}|{message}", level="DEBUG")
    try:
        yield messages
    finally:
        try:
            logger.remove(handler_id)
        except ValueError:
            pass


def _workflow(*, enabled=True, cron="* * * * *"):
    return {
        "schema_version": 1,
        "workflow_id": "wf_OBS001",
        "name": "Observability schedule",
        "description": "",
        "nodes": [],
        "edges": [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {
            "on_error": "stop",
            "schedules": [{"id": "sch_minute", "cron": cron, "enabled": enabled}],
        },
        "extensions": {},
        "created_at": "2026-08-05T12:00:00+00:00",
        "updated_at": "2026-08-05T12:00:00+00:00",
    }


def _watch_workflow(folder):
    return {
        "schema_version": 1,
        "workflow_id": "wf_OBS002",
        "name": "Observability watch",
        "description": "",
        "nodes": [{
            "id": "script",
            "type": "script.input",
            "type_version": 1,
            "name": "Script Input",
            "position": {"x": 0, "y": 0},
            "configuration": {"text": "fallback"},
            "disabled": False,
            "extensions": {},
        }],
        "edges": [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {
            "on_error": "stop",
            "watch_folder": {
                "enabled": True,
                "folder": str(folder),
                "pattern": "*.txt",
                "target_node_id": "",
                "target_port": "",
            },
        },
        "extensions": {},
        "created_at": "2026-08-05T12:00:00+00:00",
        "updated_at": "2026-08-05T12:00:00+00:00",
    }


def _at(hour, minute, second=0):
    return datetime(2026, 8, 5, hour, minute, second, tzinfo=timezone.utc)


def _joined(messages: list[str]) -> str:
    return "\n".join(str(m) for m in messages)


def test_schedule_enqueue_failure_is_logged(tmp_path, captured_logs):
    workflow = _workflow()
    service = ScheduleService(
        state_root=str(tmp_path / "state"),
        workflow_loader=lambda: [workflow],
        enqueue=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("schedule boom")),
    )
    # Establish cursor, then fire.
    service.tick(_at(12, 0, 30))
    service.tick(_at(12, 1))

    text = _joined(captured_logs)
    assert "[schedules] enqueue failed" in text
    assert "schedule boom" in text
    assert "wf_OBS001" in text


def test_schedule_tick_loop_logs_instead_of_swallowing(tmp_path, captured_logs):
    """The daemon `_run` loop must log tick failures (step 10.4)."""
    import time

    service = ScheduleService(
        state_root=str(tmp_path / "state"),
        workflow_loader=lambda: (_ for _ in ()).throw(RuntimeError("loader broken")),
        enqueue=lambda *_a, **_k: None,
        poll_seconds=0.05,
    )
    service.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if any("[schedules] tick failed" in str(m) for m in captured_logs):
                break
            time.sleep(0.05)
    finally:
        service.stop()

    text = _joined(captured_logs)
    assert "[schedules] tick failed" in text
    assert "loader broken" in text


def test_watch_folder_enqueue_failure_is_logged_and_retried(tmp_path, captured_logs):
    watched = tmp_path / "incoming"
    watched.mkdir()
    workflow = _watch_workflow(watched)
    now = [0.0]
    attempts: list[str] = []

    def enqueue(document, content, settings):
        attempts.append(content)
        raise RuntimeError("watch boom api_key=sk-secret")

    service = WatchFolderService(
        workflow_loader=lambda: [workflow],
        enqueue=enqueue,
        clock=lambda: now[0],
        stable_seconds=0.0,
    )
    incoming = watched / "story.txt"
    incoming.write_text("narration body", encoding="utf-8")
    # First tick observes; second tick (stable window elapsed) enqueues.
    service.tick()
    now[0] = 1.0
    service.tick()

    text = _joined(captured_logs)
    assert "[watch-folder] enqueue failed" in text
    assert "watch boom" in text
    # Secrets in exception text must be scrubbed before they reach the log.
    assert "sk-secret" not in text
    # Claim rolled back so a later tick can retry.
    assert incoming.exists()
    assert len(attempts) == 1


def test_channel_cadence_enqueue_failure_is_logged(tmp_path, captured_logs):
    channel = {
        "id": "ch_OBS001",
        "name": "Obs Channel",
        "cadence": {"enabled": True, "cron": "* * * * *"},
    }
    service = ChannelCadenceService(
        state_root=str(tmp_path / "cadence"),
        channel_loader=lambda: [channel],
        enqueue=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cadence boom")),
    )
    service.tick(_at(12, 0, 30))  # cursor
    service.tick(_at(12, 1))  # fire + fail

    text = _joined(captured_logs)
    assert "[channel-cadence] enqueue failed" in text
    assert "ch_OBS001" in text
    assert "cadence boom" in text


def test_notification_webhook_failure_is_logged(tmp_path, monkeypatch, captured_logs):
    class BoomResponse:
        status_code = 500

        def raise_for_status(self):
            raise RuntimeError("webhook 500")

    monkeypatch.setattr(
        notification_service.requests,
        "post",
        lambda *a, **k: BoomResponse(),
    )
    workflow = {
        "workflow_id": "wf_OBS003",
        "name": "Notify",
        "settings": {
            "notifications": {
                "on_completion": True,
                "on_failure": False,
                "windows_toast": False,
                "webhook": {"enabled": True, "url": "https://example.com/hook"},
            }
        },
    }
    execution = {
        "execution_id": "ex_OBS003",
        "workflow_id": "wf_OBS003",
        "project_id": "pm_OBS003",
        "status": "succeeded",
        "finished_at": "2026-08-05T12:00:00+00:00",
    }
    record = dispatch_run_notification(workflow, execution, output_dir=str(tmp_path))
    assert record["deliveries"]["webhook"]["status"] == "failed"

    text = _joined(captured_logs)
    assert "[notifications] webhook delivery failed" in text
    assert "ex_OBS003" in text
    assert "webhook 500" in text


def test_notification_toast_failure_is_logged(tmp_path, monkeypatch, captured_logs):
    def boom_toast(title, message):
        raise RuntimeError("toast unavailable")

    monkeypatch.setattr(notification_service, "_windows_toast", boom_toast)
    workflow = {
        "workflow_id": "wf_OBS004",
        "name": "Toast",
        "settings": {
            "notifications": {
                "on_completion": True,
                "on_failure": False,
                "windows_toast": True,
                "webhook": {"enabled": False, "url": ""},
            }
        },
    }
    execution = {
        "execution_id": "ex_OBS004",
        "workflow_id": "wf_OBS004",
        "project_id": "pm_OBS004",
        "status": "succeeded",
        "finished_at": "2026-08-05T12:00:00+00:00",
    }
    record = dispatch_run_notification(workflow, execution, output_dir=str(tmp_path))
    assert record["deliveries"]["windows_toast"]["status"] == "failed"
    text = _joined(captured_logs)
    assert "[notifications] windows_toast delivery failed" in text
    assert "toast unavailable" in text
