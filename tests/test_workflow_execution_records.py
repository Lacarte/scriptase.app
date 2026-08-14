from __future__ import annotations

import json

from scriptase.engine.persistence import load_execution
from scriptase.engine.redaction import REDACTED, Redactor, redact
from scriptase.engine.scheduler import WorkflowScheduler


def _workflow(secret: str) -> dict:
    return {
        "schema_version": 1,
        "workflow_id": "wf_ABC123",
        "name": "Redaction",
        "description": "",
        "nodes": [{
            "id": "n_secret",
            "type": "stub.input",
            "type_version": 1,
            "name": "Secret source",
            "position": {"x": 0, "y": 0},
            "configuration": {
                "port_type": "generic_json",
                "payload": {"api_key": secret, "ordinary": "safe"},
            },
            "disabled": False,
        }],
        "edges": [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
        "created_at": "2026-08-04T12:00:00Z",
        "updated_at": "2026-08-04T12:00:00Z",
    }


def test_complete_execution_record_is_persisted(tmp_path):
    workflow = _workflow("unit-test-secret-value")

    def resolver(node):
        def execute(inputs, config, context):
            return {"value": {"artifact_refs": ["fixtures/result.json"], "ok": True}}
        return execute

    result = WorkflowScheduler(
        workflow,
        project_id="pm_ABC123",
        execution_id="ex_REC001",
        output_dir=str(tmp_path),
        lock_root=str(tmp_path / "locks"),
        executor_resolver=resolver,
    ).run()
    record = load_execution("ex_REC001", root=str(tmp_path / "workflows" / "executions"))

    assert result.execution_record == record
    assert record["status"] == "succeeded"
    assert record["finished_at"]
    assert record["workflow_snapshot"]["nodes"][0]["configuration"]["payload"]["api_key"] == REDACTED
    node = record["nodes"]["n_secret"]
    assert node["status"] == "succeeded"
    assert node["attempts"] == 1
    assert node["duration_ms"] >= 0
    assert node["artifact_refs"] == ["fixtures/result.json"]


def test_secret_never_reaches_persisted_or_emitted_bytes(tmp_path):
    secret = "fake-api-key-for-redaction-12345"
    workflow = _workflow(secret)
    events = []

    def resolver(node):
        def execute(inputs, config, context):
            raise RuntimeError(f"provider rejected api_key={secret}")
        return execute

    WorkflowScheduler(
        workflow,
        project_id="pm_ABC123",
        execution_id="ex_SEC001",
        output_dir=str(tmp_path),
        lock_root=str(tmp_path / "locks"),
        executor_resolver=resolver,
        on_event=events.append,
    ).run()

    persisted = (tmp_path / "workflows" / "executions" / "ex_SEC001.json").read_bytes()
    emitted = json.dumps(events).encode("utf-8")
    assert secret.encode() not in persisted
    assert secret.encode() not in emitted
    assert REDACTED.encode() in persisted
    assert any(event["type"] == "node_error" for event in events)


def test_recursive_redaction_covers_sensitive_keys_inline_tokens_and_copies():
    source = {"password": "hunter2-value", "nested": ["Bearer abcdefghijklmnop"]}
    cleaned = redact(source)
    assert cleaned == {"password": REDACTED, "nested": [f"Bearer {REDACTED}"]}
    assert source["password"] == "hunter2-value"

    redactor = Redactor({"api_key": "remember-this-secret"})
    assert redactor("log contains remember-this-secret") == f"log contains {REDACTED}"
