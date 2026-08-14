"""Step 7.5: persisted run notifications and optional delivery channels."""

from __future__ import annotations

from copy import deepcopy

from flask import Flask

import scriptase.engine.notifications as notification_service
import scriptase.engine.routes as workflow_routes
from scriptase.engine import workflows_bp
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.notifications import dispatch_run_notification, list_notifications
from scriptase.engine.validation import validate_workflow, validation_errors


def _workflow(*, on_completion=True, on_failure=True):
    return {
        "schema_version": 1,
        "name": "Notify test",
        "description": "",
        "nodes": [{
            "id": "work", "type": "trigger.manual", "type_version": 1,
            "name": "work", "position": {"x": 0, "y": 0},
            "configuration": {}, "disabled": False,
        }],
        "edges": [], "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {
            "on_error": "stop",
            "notifications": {
                "on_completion": on_completion,
                "on_failure": on_failure,
                "windows_toast": False,
                "webhook": {"enabled": False, "url": ""},
            },
        },
        "extensions": {},
    }


def _finish(manager, execution_id):
    manager.active.get(execution_id).thread.join(timeout=5)
    assert not manager.active.get(execution_id).thread.is_alive()


def test_successful_and_failed_runs_create_configured_records(tmp_path):
    success = ExecutionManager(output_dir=str(tmp_path))
    success_id, _ = success.start(_workflow(), run_mode="full", target_node_ids=[])
    _finish(success, success_id)
    workflow_id = success.active.get(success_id).scheduler.workflow["workflow_id"]

    def failing_resolver(_node):
        def execute(_inputs, _config, _context):
            raise RuntimeError("expected failure")
        return execute

    failed = ExecutionManager(output_dir=str(tmp_path), executor_resolver=failing_resolver)
    failure_workflow = _workflow()
    failure_workflow["workflow_id"] = workflow_id
    failure_id, _ = failed.start(failure_workflow, run_mode="full", target_node_ids=[])
    _finish(failed, failure_id)

    records, total, unseen = list_notifications(workflow_id, output_dir=str(tmp_path))
    assert total == unseen == 2
    assert {item["outcome"] for item in records} == {"success", "failure"}
    assert {item["execution_id"] for item in records} == {success_id, failure_id}


def test_delivery_is_idempotent_and_webhook_receives_bounded_payload(tmp_path, monkeypatch):
    calls = []

    class Response:
        status_code = 204
        def raise_for_status(self):
            return None

    monkeypatch.setattr(notification_service.requests, "post", lambda url, **kwargs: calls.append((url, kwargs)) or Response())
    monkeypatch.setattr(notification_service, "_windows_toast", lambda title, message: calls.append((title, message)))
    workflow = _workflow()
    workflow["workflow_id"] = "wf_ABC123"
    workflow["settings"]["notifications"].update({
        "windows_toast": True,
        "webhook": {"enabled": True, "url": "https://example.com/run-events"},
    })
    execution = {
        "execution_id": "ex_ABC123", "workflow_id": "wf_ABC123",
        "project_id": "pm_ABC123", "status": "succeeded", "finished_at": "2026-08-05T12:00:00+00:00",
    }
    first = dispatch_run_notification(workflow, execution, output_dir=str(tmp_path))
    second = dispatch_run_notification(workflow, execution, output_dir=str(tmp_path))

    assert first == second
    assert len(calls) == 2
    url, request = calls[1]
    assert url == "https://example.com/run-events"
    assert request["timeout"] == 5
    assert "seen" not in request["json"] and "deliveries" not in request["json"]
    assert first["deliveries"]["webhook"] == {"status": "sent", "http_status": 204}


def test_notification_api_surfaces_and_clears_unseen_state(tmp_path, monkeypatch):
    workflow = _workflow()
    workflow["workflow_id"] = "wf_ABC123"
    dispatch_run_notification(workflow, {
        "execution_id": "ex_ABC123", "project_id": "pm_ABC123",
        "status": "failed", "finished_at": "2026-08-05T12:00:00+00:00",
    }, output_dir=str(tmp_path))
    manager = ExecutionManager(output_dir=str(tmp_path))
    monkeypatch.setattr(workflow_routes, "execution_manager", manager)
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    http = app.test_client()

    response = http.get("/api/workflow/notifications?workflow_id=wf_ABC123")
    assert response.status_code == 200
    assert response.get_json()["unseen"] == 1
    response = http.post("/api/workflow/notifications/seen", json={"workflow_id": "wf_ABC123"})
    assert response.status_code == 200 and response.get_json()["updated"] == 1
    assert http.get("/api/workflow/notifications?workflow_id=wf_ABC123").get_json()["unseen"] == 0


def test_notification_settings_validate_webhook_and_unknown_fields():
    workflow = _workflow()
    workflow["settings"]["notifications"]["webhook"] = {"enabled": True, "url": "file:///tmp/event"}
    problems = validation_errors(validate_workflow(workflow))
    assert any(item["path"] == "settings.notifications.webhook.url" for item in problems)
    invalid = deepcopy(workflow)
    invalid["settings"]["notifications"]["surprise"] = True
    problems = validation_errors(validate_workflow(invalid))
    assert any(item["path"] == "settings.notifications.surprise" for item in problems)
