"""Step 7.2: persisted cron schedules and latest-only catch-up."""

from copy import deepcopy
from datetime import datetime, timezone

from scriptase.engine.scheduled_runs import CronExpression, ScheduleService, schedule_details
from scriptase.engine.validation import validate_workflow, validation_errors


def _workflow(*, enabled=True, cron="* * * * *"):
    return {
        "schema_version": 1,
        "workflow_id": "wf_ABC123",
        "name": "Scheduled test",
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


def _at(hour, minute, second=0):
    return datetime(2026, 8, 5, hour, minute, second, tzinfo=timezone.utc)


def test_accelerated_clock_enqueues_once_at_fire_and_catches_up_latest_only(tmp_path):
    workflow = _workflow()
    queued = []
    service = ScheduleService(
        state_root=str(tmp_path / "state"),
        workflow_loader=lambda: [workflow],
        enqueue=lambda document: queued.append(document["workflow_id"]),
    )

    assert service.tick(_at(12, 0, 30)) == []  # New schedule establishes its cursor.
    assert service.tick(_at(12, 0, 59)) == []

    fired = service.tick(_at(12, 1))
    assert queued == ["wf_ABC123"]
    assert [item["fire_at"] for item in fired] == ["2026-08-05T12:01:00Z"]
    assert service.tick(_at(12, 1)) == []  # Repeating a tick cannot duplicate it.

    # Three missed minute boundaries become one queued run for the latest one.
    fired = service.tick(_at(12, 4, 20))
    assert len(fired) == 1
    assert fired[0]["fire_at"] == "2026-08-05T12:04:00Z"
    assert queued == ["wf_ABC123", "wf_ABC123"]


def test_disabled_schedule_never_fires_and_advances_cursor(tmp_path):
    workflow = _workflow(enabled=False)
    queued = []
    service = ScheduleService(
        state_root=str(tmp_path / "state"),
        workflow_loader=lambda: [workflow],
        enqueue=lambda document: queued.append(document),
    )
    service.tick(_at(12, 0))
    service.tick(_at(13, 0))
    workflow["settings"]["schedules"][0]["enabled"] = True
    assert service.tick(_at(13, 0, 30)) == []
    assert queued == []
    assert len(service.tick(_at(13, 1))) == 1


def test_cron_validation_and_next_fire_metadata():
    assert CronExpression("0 9 * * 1-5").next_after(_at(8, 59)).isoformat() == "2026-08-05T09:00:00+00:00"
    details = schedule_details(_workflow(cron="0 9 * * 1-5"), now=_at(8, 59))
    assert details[0]["next_fire_at"] == "2026-08-05T09:00:00Z"
    assert details[0]["timezone"] == "UTC"

    invalid = deepcopy(_workflow(cron="not cron"))
    problems = validation_errors(validate_workflow(invalid, require_identity=True))
    assert any(problem.get("path") == "settings.schedules.0.cron" for problem in problems)

