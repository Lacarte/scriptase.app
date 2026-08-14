"""Small, non-evaluating workflow expression parser and resolver."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .registry import get_node_type

_EXPRESSION_RE = re.compile(r"^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$")
_SEGMENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_VARIABLE_SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class ExpressionError(ValueError):
    def __init__(self, code: str, message: str, *, expression: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.expression = expression


@dataclass(frozen=True)
class Reference:
    kind: str
    path: tuple[str, ...]


def is_expression(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value


def parse_expression(value: str) -> Reference:
    """Parse one whole-value reference; never evaluate source text."""
    if not isinstance(value, str):
        raise ExpressionError("EXPRESSION_INVALID", "Expression must be a string")
    match = _EXPRESSION_RE.fullmatch(value)
    if not match:
        raise ExpressionError(
            "EXPRESSION_INVALID",
            "Expressions must occupy the whole value and use {{ reference }} syntax",
            expression=value,
        )
    parts = tuple(part.strip() for part in match.group(1).split("."))
    if parts == ("workflow", "project_id"):
        return Reference("workflow", ("project_id",))
    if len(parts) == 4 and parts[0] == "nodes" and parts[2] == "outputs":
        if not _SEGMENT_RE.fullmatch(parts[1]) or not _SEGMENT_RE.fullmatch(parts[3]):
            raise ExpressionError("EXPRESSION_INVALID", "Node and output IDs have an invalid format", expression=value)
        return Reference("node", (parts[1], parts[3]))
    if len(parts) >= 2 and parts[0] == "variables" and all(
        _VARIABLE_SEGMENT_RE.fullmatch(part) for part in parts[1:]
    ):
        return Reference("variable", parts[1:])
    raise ExpressionError(
        "EXPRESSION_FORBIDDEN",
        "Only nodes.<id>.outputs.<port>, workflow.project_id, and variables.<name> are allowed",
        expression=value,
    )


def _walk(value: Any, path: str):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")
    elif is_expression(value):
        yield path, value


def _ancestors(workflow: Mapping[str, Any]) -> dict[str, set[str]]:
    node_ids = {node.get("id") for node in workflow.get("nodes", []) if isinstance(node, Mapping)}
    incoming = {node_id: set() for node_id in node_ids}
    for edge in workflow.get("edges", []):
        if isinstance(edge, Mapping) and edge.get("target_node") in incoming:
            incoming[edge["target_node"]].add(edge.get("source_node"))
    result: dict[str, set[str]] = {}
    for node_id in node_ids:
        found: set[str] = set()
        pending = list(incoming[node_id])
        while pending:
            candidate = pending.pop()
            if candidate in found:
                continue
            found.add(candidate)
            pending.extend(incoming.get(candidate, ()))
        result[node_id] = found
    return result


def validate_expressions(
    workflow: Mapping[str, Any], *, scope_node_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    """Return structured static expression problems for a workflow snapshot."""
    nodes = {
        node.get("id"): node for node in workflow.get("nodes", [])
        if isinstance(node, Mapping) and isinstance(node.get("id"), str)
    }
    allowed_scope = set(scope_node_ids) if scope_node_ids is not None else set(nodes)
    variables = workflow.get("variables") if isinstance(workflow.get("variables"), Mapping) else {}
    ancestry = _ancestors(workflow)
    problems: list[dict[str, Any]] = []

    def problem(code: str, message: str, path: str) -> None:
        problems.append({"code": code, "message": message, "path": path, "severity": "error"})

    for node_id, node in nodes.items():
        if node_id not in allowed_scope:
            continue
        for path, source in _walk(node.get("configuration", {}), f"nodes.{node_id}.configuration"):
            try:
                reference = parse_expression(source)
            except ExpressionError as exc:
                problem(exc.code, exc.message, path)
                continue
            if reference.kind == "node":
                source_id, port_id = reference.path
                if source_id not in nodes:
                    problem("EXPRESSION_REFERENCE_MISSING", f"Expression node does not exist: {source_id}", path)
                    continue
                if source_id not in ancestry.get(node_id, set()):
                    problem("EXPRESSION_NOT_UPSTREAM", f"Expression may only reference an upstream node: {source_id}", path)
                    continue
                if source_id not in allowed_scope:
                    problem("EXPRESSION_OUTSIDE_SCOPE", f"Expression source is outside the selected run scope: {source_id}", path)
                    continue
                definition = get_node_type(nodes[source_id].get("type"))
                port = next((item for item in (definition or {}).get("outputs", []) if item.get("id") == port_id), None)
                if port is None or port.get("type") == "control":
                    problem("EXPRESSION_OUTPUT_MISSING", f"Expression output does not exist: {source_id}.{port_id}", path)
            elif reference.kind == "variable":
                current: Any = variables
                for segment in reference.path:
                    if not isinstance(current, Mapping) or segment not in current:
                        problem("EXPRESSION_VARIABLE_MISSING", f"Workflow variable does not exist: {'.'.join(reference.path)}", path)
                        break
                    current = current[segment]
    return problems


def resolve_configuration(
    value: Any, *, node_outputs: Mapping[str, Mapping[str, Any]], variables: Mapping[str, Any], project_id: str
) -> Any:
    """Recursively replace expressions with deep-copied, typed values."""
    if isinstance(value, dict):
        return {key: resolve_configuration(child, node_outputs=node_outputs, variables=variables, project_id=project_id) for key, child in value.items()}
    if isinstance(value, list):
        return [resolve_configuration(child, node_outputs=node_outputs, variables=variables, project_id=project_id) for child in value]
    if not is_expression(value):
        return deepcopy(value)
    reference = parse_expression(value)
    if reference.kind == "workflow":
        return project_id
    if reference.kind == "node":
        node_id, port_id = reference.path
        if node_id not in node_outputs or port_id not in node_outputs[node_id]:
            raise ExpressionError("EXPRESSION_VALUE_UNAVAILABLE", f"Upstream output is missing or stale: {node_id}.{port_id}", expression=value)
        return deepcopy(node_outputs[node_id][port_id])
    current: Any = variables
    for segment in reference.path:
        if not isinstance(current, Mapping) or segment not in current:
            raise ExpressionError("EXPRESSION_VARIABLE_MISSING", f"Workflow variable does not exist: {'.'.join(reference.path)}", expression=value)
        current = current[segment]
    return deepcopy(current)
