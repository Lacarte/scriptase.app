"""Step 7.4: loopback webhook triggers with typed payload mappings."""

from __future__ import annotations

from copy import deepcopy

import pytest
from flask import Flask

import scriptase.engine.routes as workflow_routes
import scriptase.engine.webhook_triggers as webhook_triggers
from scriptase.engine import workflows_bp
from scriptase.engine.validation import validate_workflow, validation_errors
from scriptase.engine.webhook_triggers import map_webhook_payload, webhook_token


def _workflow():
    return {
        "schema_version": 1,
        "workflow_id": "wf_ABC123",
        "name": "Webhook test",
        "description": "",
        "nodes": [{
            "id": "tts",
            "type": "tts.generate",
        "type_version": 4,
            "name": "Narration",
            "position": {"x": 0, "y": 0},
            "configuration": {},
            "disabled": False,
            "extensions": {},
        }],
        "edges": [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {
            "on_error": "stop",
            "webhook": {
                "enabled": True,
                "mappings": [{
                    "payload_path": "story.text",
                    "target_node_id": "tts",
                    "target_port": "script",
                    "required": True,
                }],
            },
        },
        "extensions": {},
        "created_at": "2026-08-05T12:00:00+00:00",
        "updated_at": "2026-08-05T12:00:00+00:00",
    }


class _Manager:
    def __init__(self):
        self.calls = []

    def start(self, workflow, **kwargs):
        self.calls.append((workflow, kwargs))
        return "ex_ABC123", "pm_ABC123"


@pytest.fixture
def client(tmp_path, monkeypatch):
    workflow = _workflow()
    manager = _Manager()
    monkeypatch.setattr(webhook_routes := workflow_routes, "load_workflow", lambda workflow_id: deepcopy(workflow))
    monkeypatch.setattr(webhook_routes, "execution_manager", manager)
    monkeypatch.setattr(webhook_triggers, "HOOK_TOKEN_DIR", str(tmp_path / "tokens"))
    monkeypatch.delenv("STS_BIND_HOST", raising=False)
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    return app.test_client(), manager, workflow


def test_valid_hook_maps_typed_payload_and_queues_webhook_source(client):
    http, manager, _workflow_document = client
    token = webhook_token("wf_ABC123")
    response = http.post(
        f"/api/workflow/hooks/wf_ABC123/{token}",
        json={"story": {"text": "A webhook supplied script."}},
    )

    assert response.status_code == 202
    assert response.get_json() == {
        "execution_id": "ex_ABC123", "project_id": "pm_ABC123", "status": "queued"
    }
    assert manager.calls[0][1]["source"] == "webhook"
    assert manager.calls[0][1]["input_overrides"] == {
        "tts": {"script": "A webhook supplied script."}
    }


def test_invalid_token_payload_and_oversize_use_standard_envelope(client):
    http, manager, _workflow_document = client
    token = webhook_token("wf_ABC123")

    invalid_token = http.post(
        "/api/workflow/hooks/wf_ABC123/not-a-real-token", json={"story": {"text": "valid"}}
    )
    assert invalid_token.status_code == 404
    assert invalid_token.get_json()["error"]["code"] == "WEBHOOK_NOT_FOUND"

    invalid_payload = http.post(f"/api/workflow/hooks/wf_ABC123/{token}", json={"story": {}})
    assert invalid_payload.status_code == 422
    assert invalid_payload.get_json()["error"]["code"] == "WEBHOOK_PAYLOAD_INVALID"

    oversized = http.post(
        f"/api/workflow/hooks/wf_ABC123/{token}",
        data=b'{"value":"' + (b"x" * (64 * 1024)) + b'"}',
        content_type="application/json",
    )
    assert oversized.status_code == 413
    assert oversized.get_json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert manager.calls == []


def test_hook_refuses_remote_clients_and_non_loopback_server_bind(client, monkeypatch):
    http, manager, _workflow_document = client
    token = webhook_token("wf_ABC123")

    remote = http.post(
        f"/api/workflow/hooks/wf_ABC123/{token}",
        json={"story": {"text": "valid"}},
        environ_base={"REMOTE_ADDR": "192.168.1.20"},
    )
    assert remote.status_code == 403
    assert remote.get_json()["error"]["code"] == "FORBIDDEN"

    monkeypatch.setenv("STS_BIND_HOST", "0.0.0.0")
    exposed = http.post(
        f"/api/workflow/hooks/wf_ABC123/{token}", json={"story": {"text": "valid"}}
    )
    assert exposed.status_code == 403
    assert exposed.get_json()["error"]["code"] == "FORBIDDEN"
    assert manager.calls == []


def test_webhook_settings_validate_declared_unique_data_ports():
    workflow = _workflow()
    assert validation_errors(validate_workflow(workflow, require_identity=True)) == []
    assert map_webhook_payload(workflow, {"story": {"text": "hello"}}) == {
        "tts": {"script": "hello"}
    }

    invalid = deepcopy(workflow)
    invalid["settings"]["webhook"]["mappings"][0]["target_port"] = "trigger"
    problems = validation_errors(validate_workflow(invalid, require_identity=True))
    assert any(item.get("path", "").endswith("target_port") for item in problems)


def test_token_endpoint_creates_and_regenerates_secret_outside_workflow(client):
    http, _manager, workflow = client
    first = http.get("/api/workflows/wf_ABC123/webhook")
    assert first.status_code == 200
    first_token = first.get_json()["token"]
    second = http.post("/api/workflows/wf_ABC123/webhook/regenerate", json={})
    assert second.status_code == 200
    assert second.get_json()["token"] != first_token
    assert "token" not in workflow["settings"]["webhook"]
