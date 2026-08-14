from __future__ import annotations

from unittest.mock import Mock

import pytest

from scriptase.modules.script import service as story_service
from scriptase.engine.adapters import AdapterContext, AdapterError
from scriptase.engine.adapters import script, utilities
from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.engine.validation import validate_workflow, validation_errors


CTX = AdapterContext(project_id="pm_ABC123")


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


def _edge(edge_id, source, source_port, target, target_port):
    return {
        "id": edge_id,
        "source_node": source,
        "source_port": source_port,
        "target_node": target,
        "target_port": target_port,
        "edge_type": "data",
    }


def _workflow(condition_value):
    return {
        "schema_version": 1,
        "workflow_id": "wf_ABC123",
        "name": "Conditional merge",
        "description": "",
        "nodes": [
            _node("source", "utility.set_value", {"value": condition_value}),
            _node("branch", "utility.condition", {"operator": "truthy", "compare_to": None}),
            _node("yes", "utility.wait", {"delay_ms": 0}),
            _node("no", "utility.set_value", {"value": "fallback"}),
            _node("join", "utility.merge", {"mode": "array"}),
        ],
        "edges": [
            _edge("e1", "source", "value", "branch", "value"),
            _edge("e2", "branch", "true", "yes", "value"),
            _edge("e3", "branch", "false", "no", "value"),
            _edge("e4", "yes", "value", "join", "values"),
            _edge("e5", "no", "value", "join", "values"),
        ],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "created_at": "2026-08-04T12:00:00Z",
        "updated_at": "2026-08-04T12:00:00Z",
    }


@pytest.mark.parametrize(
    ("condition_value", "skipped_node", "expected"),
    [(5, "no", [5]), (0, "yes", ["fallback"])],
)
def test_condition_branches_rejoin_merge_with_skip_propagation(tmp_path, condition_value, skipped_node, expected):
    result = WorkflowScheduler(
        _workflow(condition_value),
        project_id="pm_ABC123",
        lock_root=str(tmp_path / "locks"),
        output_dir=str(tmp_path),
    ).run()

    assert result.status == "succeeded"
    assert result.node_statuses[skipped_node] == "skipped"
    assert result.node_statuses["join"] == "succeeded"
    assert result.outputs["join"]["value"] == expected


def test_condition_emits_only_selected_port_and_preserves_null():
    assert utilities.condition({"value": None}, {"operator": "equals", "compare_to": None}, CTX) == {"true": None}
    assert utilities.condition({"value": "hello"}, {"operator": "contains", "compare_to": "ell"}, CTX) == {"true": "hello"}


def test_set_value_replaces_input_and_object_merge_is_left_to_right():
    assert utilities.set_value({"value": "old"}, {"value": {"new": True}}, CTX)["value"] == {"new": True}
    merged = utilities.merge({"values": [{"a": 1, "same": 1}, {"b": 2, "same": 2}]}, {"mode": "object"}, CTX)
    assert merged["value"] == {"a": 1, "b": 2, "same": 2}
    with pytest.raises(AdapterError) as raised:
        utilities.merge({"values": [{"a": 1}, "bad"]}, {"mode": "object"}, CTX)
    assert raised.value.code == "MERGE_OBJECT_REQUIRED"


def test_wait_uses_bounded_intervals_and_honors_cancellation(monkeypatch):
    sleeps = []
    monkeypatch.setattr(utilities.time, "sleep", sleeps.append)
    assert utilities.wait({"value": 3}, {"delay_ms": 120}, CTX)["value"] == 3
    assert sleeps == pytest.approx([0.05, 0.05, 0.02])

    cancelled = AdapterContext(project_id="pm_ABC123", stop_requested=lambda: True)
    with pytest.raises(AdapterError) as raised:
        utilities.wait({}, {"delay_ms": 1}, cancelled)
    assert raised.value.code == "CANCELLED"


def test_wait_delay_requires_integer_milliseconds():
    workflow = _workflow(True)
    workflow["nodes"][2]["configuration"]["delay_ms"] = 1.5
    problems = validation_errors(validate_workflow(workflow, require_complete=True))
    assert any(problem.get("path", "").endswith("delay_ms") and "integer" in problem["message"] for problem in problems)


def test_story_adapter_dispatches_to_script_provider_and_emits_script(monkeypatch, tmp_path):
    """Adapter talks only to the script provider seam (step 13.2) — not the
    concrete AI service module.
    """
    artifact = tmp_path / "story.json"
    artifact.write_text("{}", encoding="utf-8")
    provider = Mock()
    provider.generate = Mock(return_value={
        "story_text": "Hook: Test",
        "sections": {"hook": "Test"},
        "metadata": {},
        "path": str(artifact),
    })
    monkeypatch.setattr(script, "resolve_provider", lambda domain, selected: provider)
    monkeypatch.setattr(script, "with_artifacts", lambda payload, *paths: {**payload, "artifact_refs": list(paths)})
    result = script.generate(
        {"settings": {"style": "cinematic", "tone": "dramatic"}},
        {"story_category": "motivation", "duration": 45, "language": "english"},
        CTX,
    )
    assert result["script"] == "Hook: Test"
    assert result["story"]["artifact_refs"] == [str(artifact)]
    assert provider.generate.call_args.kwargs["project_id"] == "pm_ABC123"
    # Default provider after 13.2 is the AI gemini path (builtin remains an alias).
    assert provider.generate.call_count == 1


def test_story_service_reuses_story_pipeline_and_persists_artifact(monkeypatch, tmp_path):
    seen = {}

    def webhook(url, payload, **kwargs):
        seen.update(url=url, payload=payload, kwargs=kwargs)
        return {"story_text": "Hook: Begin.\n\nBuild: Continue.\n\nCTA: Act."}

    monkeypatch.setattr(story_service, "STORIES_DIR", str(tmp_path))
    monkeypatch.setattr(story_service, "append_history", lambda **kwargs: None)
    result = story_service.generate_story(
        {
            "preset_style": "cinematic",
            "story_category": "motivation",
            "duration": 45,
            "language": "english",
            "webhook_url": "https://example.com/webhook/story-generator",
        },
        project_id="pm_ABC123",
        webhook_caller=webhook,
    )

    assert result["story_text"].startswith("Hook: Begin")
    assert seen["payload"]["word_target"] > 0
    assert seen["kwargs"]["timeout"] == 120
    assert (tmp_path / "pm_ABC123" / "story.json").is_file()
