from __future__ import annotations

import pytest

from scriptase.engine.expressions import (
    ExpressionError,
    parse_expression,
    resolve_configuration,
    validate_expressions,
)
from scriptase.engine.scheduler import SchedulerError, WorkflowScheduler
from scriptase.engine.validation import validate_workflow, validation_errors


def _node(node_id, value):
    return {
        "id": node_id, "type": "utility.set_value", "type_version": 1,
        "name": node_id, "position": {"x": 0, "y": 0},
        "configuration": {"value": value}, "disabled": False,
    }


def _workflow(target_value="{{ nodes.source.outputs.value }}"):
    return {
        "schema_version": 1, "workflow_id": "wf_ABC123", "name": "Expressions", "description": "",
        "nodes": [_node("source", {"typed": [1, True]}), _node("target", target_value)],
        "edges": [{
            "id": "e1", "source_node": "source", "source_port": "value",
            "target_node": "target", "target_port": "value", "edge_type": "data",
        }],
        "variables": {"nested": {"count": 3}},
        "viewport": {"x": 0, "y": 0, "zoom": 1}, "settings": {"on_error": "stop"},
        "created_at": "2026-08-04T12:00:00Z", "updated_at": "2026-08-04T12:00:00Z",
    }


def test_expression_config_executes_and_preserves_typed_output(tmp_path):
    result = WorkflowScheduler(
        _workflow(), project_id="pm_ABC123", lock_root=str(tmp_path / "locks"), output_dir=str(tmp_path)
    ).run()
    assert result.status == "succeeded"
    assert result.outputs["target"]["value"] == {"typed": [1, True]}


def test_workflow_and_nested_variable_references_preserve_values():
    resolved = resolve_configuration(
        {"project": "{{ workflow.project_id }}", "count": "{{ variables.nested.count }}"},
        node_outputs={}, variables={"nested": {"count": 3}}, project_id="pm_ABC123",
    )
    assert resolved == {"project": "pm_ABC123", "count": 3}


@pytest.mark.parametrize("source", [
    "{{ env.PATH }}",
    "{{ secrets.api_key }}",
    "{{ nodes.source.__class__ }}",
    "{{ nodes.source.outputs.value.__class__ }}",
    "{{ open.filesystem }}",
    "prefix {{ workflow.project_id }}",
    "{{ workflow.project_id + 'x' }}",
])
def test_sandbox_rejects_environment_secret_attribute_filesystem_and_code_access(source):
    with pytest.raises(ExpressionError) as raised:
        parse_expression(source)
    assert raised.value.code in {"EXPRESSION_INVALID", "EXPRESSION_FORBIDDEN"}


def test_static_validation_rejects_non_upstream_missing_ports_and_variables():
    workflow = _workflow("{{ nodes.target.outputs.value }}")
    problems = validation_errors(validate_workflow(workflow, require_complete=True))
    assert any(problem["code"] == "EXPRESSION_NOT_UPSTREAM" for problem in problems)

    workflow = _workflow("{{ nodes.source.outputs.missing }}")
    assert any(problem["code"] == "EXPRESSION_OUTPUT_MISSING" for problem in validate_expressions(workflow))

    workflow = _workflow("{{ variables.missing }}")
    assert any(problem["code"] == "EXPRESSION_VARIABLE_MISSING" for problem in validate_expressions(workflow))


def test_selected_scope_must_include_expression_source(tmp_path):
    with pytest.raises(SchedulerError) as raised:
        WorkflowScheduler(
            _workflow(), project_id="pm_ABC123", scope_node_ids=["target"],
            lock_root=str(tmp_path / "locks"), output_dir=str(tmp_path),
        )
    assert any(problem["code"] == "EXPRESSION_OUTSIDE_SCOPE" for problem in raised.value.details["problems"])
