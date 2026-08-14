"""Validation for persisted workflow definitions (Phase 1).

The canvas performs the same fast checks for UX, but this module is the
authoritative trust boundary for anything saved or imported.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime
from typing import Any

from .expressions import is_expression, validate_expressions
from .options import allowed_option_values, config_option_context, configured_provider
from .registry import DYNAMIC_PORT_TYPES, get_node_type, is_supported
from .sample_data import validate_stub_payload

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_NODES = 200
MAX_EDGES = 500
MAX_NESTING_DEPTH = 20
MAX_VARIABLES_BYTES = 64 * 1024
MAX_EXTENSIONS_BYTES = 64 * 1024

WORKFLOW_ID_RE = re.compile(r"^wf_[A-Z0-9]{6}$")
ELEMENT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

_TOP_FIELDS = {
    "schema_version", "workflow_id", "name", "description", "nodes", "edges",
    "variables", "viewport", "settings", "created_at", "updated_at", "extensions",
}
_NODE_FIELDS = {
    "id", "type", "type_version", "name", "position", "configuration", "disabled",
    "on_error", "extensions",
}

_ERROR_POLICIES = {"stop", "retry", "continue_error", "skip_optional"}
_EDGE_FIELDS = {
    "id", "source_node", "source_port", "target_node", "target_port", "edge_type",
    "extensions",
}


def _problem(code: str, message: str, path: str = "", *, severity: str = "error") -> dict:
    item = {"code": code, "message": message, "severity": severity}
    if path:
        item["path"] = path
    return item


def _json_size(value: Any) -> int:
    return len(json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8"))


def _json_shape_error(value: Any) -> str | None:
    """Return the first transport-independent JSON shape violation."""
    stack = [(value, 1)]
    seen: set[int] = set()
    while stack:
        item, depth = stack.pop()
        if isinstance(item, bool) or item is None or isinstance(item, str):
            continue
        if isinstance(item, (int, float)):
            if isinstance(item, float) and not math.isfinite(item):
                return "JSON numbers must be finite"
            continue
        if not isinstance(item, (dict, list)):
            return "Workflow contains a value that is not valid JSON"
        if depth > MAX_NESTING_DEPTH:
            return f"JSON nesting depth exceeds {MAX_NESTING_DEPTH}"
        identity = id(item)
        if identity in seen:
            return "Workflow contains a recursive JSON value"
        seen.add(identity)
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                return "JSON object keys must be strings"
            stack.extend((child, depth + 1) for child in item.values())
        else:
            stack.extend((child, depth + 1) for child in item)
    return None


def _valid_server_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not RFC3339_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _validate_extensions(value: Any, path: str, problems: list[dict]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        problems.append(_problem("WORKFLOW_INVALID", "extensions must be an object", path))
    elif _json_size(value) > MAX_EXTENSIONS_BYTES:
        problems.append(_problem("WORKFLOW_INVALID", "extensions exceeds 64 KiB", path))


def _validate_schedules(value: Any, problems: list[dict]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        problems.append(_problem("WORKFLOW_INVALID", "settings.schedules must be an array", "settings.schedules"))
        return
    if len(value) > 16:
        problems.append(_problem("WORKFLOW_INVALID", "A workflow can have at most 16 schedules", "settings.schedules"))
    seen = set()
    from .scheduled_runs import CronExpression, CronExpressionError
    for index, schedule in enumerate(value):
        path = f"settings.schedules.{index}"
        if not isinstance(schedule, dict):
            problems.append(_problem("WORKFLOW_INVALID", "Schedule must be an object", path))
            continue
        for unknown in sorted(set(schedule) - {"id", "cron", "enabled"}):
            problems.append(_problem("WORKFLOW_INVALID", f"Unknown schedule field: {unknown}", f"{path}.{unknown}"))
        schedule_id = schedule.get("id")
        if not isinstance(schedule_id, str) or not re.fullmatch(r"sch_[A-Za-z0-9_-]{1,32}", schedule_id):
            problems.append(_problem("WORKFLOW_INVALID", "Schedule id must match sch_<1-32 characters>", f"{path}.id"))
        elif schedule_id in seen:
            problems.append(_problem("WORKFLOW_INVALID", "Schedule ids must be unique", f"{path}.id"))
        seen.add(schedule_id)
        if not isinstance(schedule.get("enabled"), bool):
            problems.append(_problem("WORKFLOW_INVALID", "Schedule enabled must be a boolean", f"{path}.enabled"))
        try:
            CronExpression(schedule.get("cron"))
        except CronExpressionError as exc:
            problems.append(_problem("WORKFLOW_INVALID", str(exc), f"{path}.cron"))


def _validate_watch_folder(value: Any, node_map: dict, problems: list[dict]) -> None:
    if value is None:
        return
    path = "settings.watch_folder"
    if not isinstance(value, dict):
        problems.append(_problem("WORKFLOW_INVALID", "settings.watch_folder must be an object", path))
        return
    allowed = {"enabled", "folder", "pattern", "target_node_id", "target_port"}
    for unknown in sorted(set(value) - allowed):
        problems.append(_problem("WORKFLOW_INVALID", f"Unknown watch-folder field: {unknown}", f"{path}.{unknown}"))
    if not isinstance(value.get("enabled"), bool):
        problems.append(_problem("WORKFLOW_INVALID", "Watch-folder enabled must be a boolean", f"{path}.enabled"))
    folder = value.get("folder")
    if not isinstance(folder, str) or not folder.strip() or len(folder) > 1024 or not os.path.isabs(folder):
        problems.append(_problem("WORKFLOW_INVALID", "Watch folder must be an absolute path", f"{path}.folder"))
    pattern = value.get("pattern")
    if not isinstance(pattern, str) or not pattern or len(pattern) > 120 or "/" in pattern or "\\" in pattern:
        problems.append(_problem("WORKFLOW_INVALID", "Watch pattern must be a filename glob", f"{path}.pattern"))

    node_id = value.get("target_node_id", "")
    port_id = value.get("target_port", "")
    if not isinstance(node_id, str) or len(node_id) > 64:
        problems.append(_problem("WORKFLOW_INVALID", "Watch target_node_id must be a node ID", f"{path}.target_node_id"))
        return
    if not isinstance(port_id, str) or len(port_id) > 64:
        problems.append(_problem("WORKFLOW_INVALID", "Watch target_port must be a port ID", f"{path}.target_port"))
        return
    if bool(node_id) != bool(port_id):
        problems.append(_problem("WORKFLOW_INVALID", "Watch target node and port must be configured together", path))
        return
    if node_id:
        pair = node_map.get(node_id)
        if not pair:
            problems.append(_problem("WORKFLOW_INVALID", "Watch target node does not exist", f"{path}.target_node_id"))
            return
        node, definition = pair
        port = next((item for item in definition.get("inputs", []) if item.get("id") == port_id), None)
        if not port or _port_type(node, port) not in {"text", "script"}:
            problems.append(_problem("WORKFLOW_INVALID", "Watch target must be a text or script input port", f"{path}.target_port"))
    elif value.get("enabled") and not any(
        node.get("type") == "script.input" and not node.get("disabled")
        for node, _ in node_map.values()
    ):
        problems.append(_problem("WORKFLOW_INVALID", "An enabled watch folder needs a Script Input node or configured target port", path))


def _validate_webhook(value: Any, node_map: dict, problems: list[dict]) -> None:
    # Kept behind this small adapter to avoid importing trigger persistence and
    # token machinery unless a workflow actually declares webhook settings.
    from .webhook_triggers import validate_webhook_settings
    validate_webhook_settings(value, node_map, problems)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _port_type(node: dict, port: dict) -> str:
    if port.get("type") != "dynamic":
        return port.get("type", "")
    return (node.get("configuration") or {}).get("port_type", "")


def _field_is_visible(field: dict, configuration: dict) -> bool:
    display = field.get("display_options") or {}
    for reference, values in (display.get("show") or {}).items():
        if configuration.get(reference) not in values:
            return False
    for reference, values in (display.get("hide") or {}).items():
        if configuration.get(reference) in values:
            return False
    return True


def _validate_provider_options(
    field: dict,
    fields: dict,
    config: dict,
    value: Any,
    field_path: str,
    problems: list[dict],
) -> None:
    """Validate a per-run options patch against the *selected* provider's schema.

    The provider is resolved authoritatively — from the node's own `provider`
    field, never from the global selection — and its own `settings_schema()` is
    the contract the patch is checked against, so a provider gets node-level
    validation without a line of code here (step 12.3, contracts.md §22.5).

    Two documented ways this fails open, both because a workflow must stay
    saveable and inspectable on a machine where a provider is not installed
    (§23.3): an unresolvable provider skips schema validation entirely, and a
    provider with no `settings_schema.py` validates nothing.

    Required-but-absent is *not* an error here. This is a patch over saved
    provider settings, so an omitted key means "use the saved value", and only
    the keys actually present are checked.
    """
    if not isinstance(value, dict):
        problems.append(_problem("WORKFLOW_INVALID", "must be an object", field_path))
        return
    try:
        _json_size(value)
    except (TypeError, ValueError):
        problems.append(_problem("WORKFLOW_INVALID", "must be JSON-serializable", field_path))
        return

    from scriptase.providers.settings_schema import (
        is_secret_field,
        properties,
        validate_against_schema,
    )

    domain = field.get("provider_domain")
    _resolved_domain, provider_id = configured_provider(config, fields)

    # A credential in a node configuration would be written to the workflow
    # JSON, its exports, and its archives. That is never recoverable by failing
    # open, so it is an error regardless of whether the provider resolves.
    schema = None
    if domain and provider_id:
        from scriptase.providers.hub import hub

        provider = hub.get(domain, provider_id)
        schema = provider.settings_schema() if provider is not None else None
    props = properties(schema)
    for key in sorted(value):
        if is_secret_field(key, props.get(key)):
            problems.append(_problem(
                "WORKFLOW_INVALID",
                f"'{key}' is a credential and must be set in provider settings, "
                "not in a workflow",
                f"{field_path}.{key}",
            ))

    if schema is None:
        return
    # `required` is dropped: an omitted key inherits the saved provider setting.
    patch_schema = {**schema, "required": []}
    for issue in validate_against_schema(patch_schema, value):
        problems.append(_problem(
            "WORKFLOW_INVALID",
            issue["message"],
            f"{field_path}.{issue['field']}",
            severity="error" if issue["severity"] == "error" else "warning",
        ))


def _validate_config(
    node: dict,
    definition: dict,
    path: str,
    problems: list[dict],
    *,
    require_complete: bool,
) -> None:
    config = node.get("configuration")
    if not isinstance(config, dict):
        problems.append(_problem("WORKFLOW_INVALID", "configuration must be an object", f"{path}.configuration"))
        return
    if _json_size(config) > 256 * 1024:
        problems.append(_problem("WORKFLOW_INVALID", "configuration exceeds 256 KiB", f"{path}.configuration"))
        return

    fields = {field["name"]: field for field in definition.get("config_schema", [])}
    for unknown in sorted(set(config) - set(fields)):
        problems.append(_problem("WORKFLOW_INVALID", f"Unknown configuration field: {unknown}", f"{path}.configuration.{unknown}"))

    for name, field in fields.items():
        value = config.get(name, field.get("default"))
        field_path = f"{path}.configuration.{name}"
        if field.get("required") and _field_is_visible(field, config) and (
            value is None or value == ""
        ):
            problems.append(_problem(
                "WORKFLOW_INVALID",
                f"{field.get('label', name)} is required",
                field_path,
                severity="error" if require_complete else "warning",
            ))
            continue
        if value is None:
            continue
        # Expressions are checked against the completed graph below and are
        # type-checked after typed resolution immediately before execution.
        if is_expression(value):
            continue
        widget = field.get("type")
        if widget in {"string", "textarea"}:
            if not isinstance(value, str):
                problems.append(_problem("WORKFLOW_INVALID", "must be a string", field_path))
                continue
            if len(value) < field.get("min_length", 0) or len(value) > field.get("max_length", 100000):
                problems.append(_problem("WORKFLOW_INVALID", "string length is outside allowed limits", field_path))
            pattern = field.get("pattern")
            if pattern and value and not re.fullmatch(pattern, value):
                problems.append(_problem("WORKFLOW_INVALID", "value has an invalid format", field_path))
        elif widget == "number":
            if not _finite_number(value):
                problems.append(_problem("WORKFLOW_INVALID", "must be a finite number", field_path))
            elif value < field.get("min", -math.inf) or value > field.get("max", math.inf):
                problems.append(_problem("WORKFLOW_INVALID", "number is outside allowed limits", field_path))
            elif field.get("integer") and not float(value).is_integer():
                problems.append(_problem("WORKFLOW_INVALID", "must be an integer", field_path))
        elif widget == "boolean" and not isinstance(value, bool):
            problems.append(_problem("WORKFLOW_INVALID", "must be a boolean", field_path))
        elif widget in ("options", "provider"):
            # `provider` is an options field whose list is always the domain's
            # registered providers, so it validates through the same allowlisted
            # source and fails open the same way when the catalog cannot answer.
            options = field.get("options")
            source = field.get("options_source")
            if options:
                if value not in options:
                    problems.append(_problem("WORKFLOW_INVALID", "value is not an allowed option", field_path))
            elif source:
                # Async sources resolve through the backend allowlist only
                # (step 6.3). A context-sensitive source is resolved against the
                # provider saved in *this* node, never a union across providers
                # (§23.3). None = source unavailable right now: fail open so a
                # missing provider never blocks saving.
                allowed = allowed_option_values(
                    source, config_option_context(source, config, fields)
                )
                if allowed is not None and (not isinstance(value, str) or value not in allowed):
                    problems.append(_problem("WORKFLOW_INVALID", "value is not an allowed option", field_path))
        elif widget == "json":
            try:
                _json_size(value)
            except (TypeError, ValueError):
                problems.append(_problem("WORKFLOW_INVALID", "must be JSON-serializable", field_path))
        elif widget == "provider_options":
            _validate_provider_options(field, fields, config, value, field_path, problems)
        elif widget == "media_asset" and value is not None and not isinstance(value, dict):
            problems.append(_problem("WORKFLOW_INVALID", "must be a managed media reference", field_path))

    # Sample Input payloads are typed data, not free-form JSON: enforce the
    # per-port-type stub contract, including fixture-only file references
    # (contracts.md §2 "Utility/testing nodes", step 2.5).
    if node.get("type") == "stub.input" or (
        node.get("type") == "stub.output" and config.get("pinned") is True
    ):
        port_type = config.get("port_type", "generic_json")
        if port_type in DYNAMIC_PORT_TYPES:
            payload = config.get("payload", fields.get("payload", {}).get("default"))
            for stub_problem in validate_stub_payload(port_type, payload):
                problems.append(_problem(
                    stub_problem["code"],
                    stub_problem["message"],
                    f"{path}.configuration.payload",
                ))


def validate_resolved_configuration(node: dict, configuration: dict) -> list[dict]:
    """Validate the typed value produced after expression resolution."""
    definition = get_node_type(node.get("type"))
    if definition is None:
        return [_problem("WORKFLOW_INVALID", "Unknown node type", f"nodes.{node.get('id')}.type")]
    resolved_node = dict(node)
    resolved_node["configuration"] = configuration
    problems: list[dict] = []
    _validate_config(
        resolved_node,
        definition,
        f"nodes.{node.get('id')}",
        problems,
        require_complete=True,
    )
    return problems


def _validate_error_policy(node: dict, definition: dict, path: str, problems: list[dict]) -> None:
    policy = node.get("on_error")
    if policy is None:
        return
    policy_path = f"{path}.on_error"
    if not isinstance(policy, dict):
        problems.append(_problem("WORKFLOW_INVALID", "on_error must be an object", policy_path))
        return
    allowed = {"policy", "max_attempts", "delay_ms", "backoff_multiplier"}
    for unknown in sorted(set(policy) - allowed):
        problems.append(_problem(
            "WORKFLOW_INVALID", f"Unknown on_error field: {unknown}", f"{policy_path}.{unknown}"
        ))
    name = policy.get("policy", "stop")
    if name not in _ERROR_POLICIES:
        problems.append(_problem(
            "WORKFLOW_INVALID", f"Unsupported error policy: {name}", f"{policy_path}.policy"
        ))
        return
    capabilities = definition.get("capabilities", {})
    capability = {"retry": "retry", "continue_error": "error_output", "skip_optional": "skip_optional"}.get(name)
    if capability and not capabilities.get(capability, False):
        problems.append(_problem(
            "WORKFLOW_INVALID", f"{name} is not supported by this node type", f"{policy_path}.policy"
        ))

    max_attempts = policy.get("max_attempts", 3)
    delay_ms = policy.get("delay_ms", 1000)
    multiplier = policy.get("backoff_multiplier", 2.0)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10:
        problems.append(_problem(
            "WORKFLOW_INVALID", "max_attempts must be an integer from 1 to 10",
            f"{policy_path}.max_attempts",
        ))
    if isinstance(delay_ms, bool) or not isinstance(delay_ms, int) or not 0 <= delay_ms <= 60_000:
        problems.append(_problem(
            "WORKFLOW_INVALID", "delay_ms must be an integer from 0 to 60000",
            f"{policy_path}.delay_ms",
        ))
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or not 1 <= multiplier <= 10:
        problems.append(_problem(
            "WORKFLOW_INVALID", "backoff_multiplier must be a number from 1 to 10",
            f"{policy_path}.backoff_multiplier",
        ))


def validate_workflow(
    document: Any,
    *,
    require_identity: bool = True,
    require_complete: bool = False,
    provided_inputs: set[tuple[str, str]] | None = None,
    allow_future_versions: bool = False,
) -> list[dict]:
    """Return structured errors/warnings for a workflow document."""
    problems: list[dict] = []
    if not isinstance(document, dict):
        return [_problem("WORKFLOW_INVALID", "Workflow must be a JSON object")]
    shape_error = _json_shape_error(document)
    if shape_error:
        return [_problem("WORKFLOW_INVALID", shape_error)]
    try:
        if _json_size(document) > MAX_DOCUMENT_BYTES:
            return [_problem("WORKFLOW_INVALID", "Workflow exceeds the 2 MiB limit")]
    except (TypeError, ValueError):
        return [_problem("WORKFLOW_INVALID", "Workflow is not valid JSON data")]

    for unknown in sorted(set(document) - _TOP_FIELDS):
        problems.append(_problem("WORKFLOW_INVALID", f"Unknown workflow field: {unknown}", unknown))
    if document.get("schema_version") != 1:
        problems.append(_problem("WORKFLOW_INVALID", "schema_version must be 1", "schema_version"))
    workflow_id = document.get("workflow_id")
    if (require_identity or workflow_id is not None) and (
        not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.fullmatch(workflow_id)
    ):
        problems.append(_problem("WORKFLOW_INVALID", "workflow_id must match wf_XXXXXX", "workflow_id"))
    for field in ("created_at", "updated_at"):
        value = document.get(field)
        if (require_identity or value is not None) and not _valid_server_timestamp(value):
            problems.append(_problem("WORKFLOW_INVALID", f"{field} must be an RFC 3339 timestamp", field))
    name = document.get("name")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 120):
        problems.append(_problem("WORKFLOW_INVALID", "name must contain 1–120 characters", "name"))
    description = document.get("description", "")
    if not isinstance(description, str) or len(description) > 2000:
        problems.append(_problem("WORKFLOW_INVALID", "description must be at most 2,000 characters", "description"))

    nodes = document.get("nodes")
    edges = document.get("edges")
    if not isinstance(nodes, list):
        problems.append(_problem("WORKFLOW_INVALID", "nodes must be an array", "nodes"))
        nodes = []
    elif len(nodes) > MAX_NODES:
        problems.append(_problem("WORKFLOW_INVALID", f"nodes exceeds the {MAX_NODES} item limit", "nodes"))
    if not isinstance(edges, list):
        problems.append(_problem("WORKFLOW_INVALID", "edges must be an array", "edges"))
        edges = []
    elif len(edges) > MAX_EDGES:
        problems.append(_problem("WORKFLOW_INVALID", f"edges exceeds the {MAX_EDGES} item limit", "edges"))

    node_map: dict[str, tuple[dict, dict]] = {}
    future_node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        path = f"nodes[{index}]"
        if not isinstance(node, dict):
            problems.append(_problem("WORKFLOW_INVALID", "node must be an object", path))
            continue
        for unknown in sorted(set(node) - _NODE_FIELDS):
            problems.append(_problem("WORKFLOW_INVALID", f"Unknown node field: {unknown}", f"{path}.{unknown}"))
        node_id = node.get("id")
        if not isinstance(node_id, str) or not ELEMENT_ID_RE.fullmatch(node_id):
            problems.append(_problem("WORKFLOW_INVALID", "node id has an invalid format", f"{path}.id"))
            continue
        if node_id in node_map:
            problems.append(_problem("WORKFLOW_INVALID", f"Duplicate node id: {node_id}", f"{path}.id"))
            continue
        type_key = node.get("type")
        definition = get_node_type(type_key) if isinstance(type_key, str) else None
        if not definition:
            problems.append(_problem("UNKNOWN_NODE_TYPE", f"Unknown node type: {type_key}", f"{path}.type"))
            continue
        type_version = node.get("type_version")
        is_future = (
            allow_future_versions
            and isinstance(type_version, int)
            and not isinstance(type_version, bool)
            and type_version > definition["type_version"]
        )
        if not is_supported(type_key, type_version):
            problems.append(_problem(
                "FUTURE_NODE_VERSION" if is_future else "UNSUPPORTED_NODE_VERSION",
                (f"Future version {type_version} for {type_key}; current version is {definition['type_version']}"
                 if is_future else f"Unsupported version for {type_key}"),
                f"{path}.type_version",
                severity="warning" if is_future else "error",
            ))
        if is_future:
            future_node_ids.add(node_id)
        node_name = node.get("name")
        if not isinstance(node_name, str) or not (1 <= len(node_name.strip()) <= 120):
            problems.append(_problem("WORKFLOW_INVALID", "node name must contain 1–120 characters", f"{path}.name"))
        position = node.get("position")
        if not isinstance(position, dict) or set(position) != {"x", "y"} or not all(
            _finite_number(position.get(axis)) and -1_000_000 <= position[axis] <= 1_000_000 for axis in ("x", "y")
        ):
            problems.append(_problem("WORKFLOW_INVALID", "position must contain finite x/y coordinates", f"{path}.position"))
        if not isinstance(node.get("disabled"), bool):
            problems.append(_problem("WORKFLOW_INVALID", "disabled must be a boolean", f"{path}.disabled"))
        _validate_extensions(node.get("extensions"), f"{path}.extensions", problems)
        if not is_future:
            _validate_config(node, definition, path, problems, require_complete=require_complete)
            _validate_error_policy(node, definition, path, problems)
        node_map[node_id] = (node, definition)

    edge_ids: set[str] = set()
    connections: set[tuple[str, str, str, str]] = set()
    occupied: set[tuple[str, str]] = set()
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_map}
    connected_inputs: set[tuple[str, str]] = set(provided_inputs or ())
    for index, edge in enumerate(edges):
        path = f"edges[{index}]"
        if not isinstance(edge, dict):
            problems.append(_problem("WORKFLOW_INVALID", "edge must be an object", path))
            continue
        for unknown in sorted(set(edge) - _EDGE_FIELDS):
            problems.append(_problem("WORKFLOW_INVALID", f"Unknown edge field: {unknown}", f"{path}.{unknown}"))
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not ELEMENT_ID_RE.fullmatch(edge_id):
            problems.append(_problem("WORKFLOW_INVALID", "edge id has an invalid format", f"{path}.id"))
        elif edge_id in edge_ids:
            problems.append(_problem("WORKFLOW_INVALID", f"Duplicate edge id: {edge_id}", f"{path}.id"))
        else:
            edge_ids.add(edge_id)
        _validate_extensions(edge.get("extensions"), f"{path}.extensions", problems)
        source_id, target_id = edge.get("source_node"), edge.get("target_node")
        if source_id not in node_map or target_id not in node_map:
            problems.append(_problem("WORKFLOW_INVALID", "edge endpoint does not exist", path))
            continue
        source_node, source_def = node_map[source_id]
        target_node, target_def = node_map[target_id]
        if source_id in future_node_ids or target_id in future_node_ids:
            # A newer node contract may have changed its ports. Preserve the
            # edge verbatim for view-only display instead of interpreting it
            # through the older local registry.
            adjacency[source_id].append(target_id)
            continue
        source_port = next((p for p in source_def["outputs"] if p["id"] == edge.get("source_port")), None)
        target_port = next((p for p in target_def["inputs"] if p["id"] == edge.get("target_port")), None)
        if not source_port or not target_port:
            problems.append(_problem("WORKFLOW_INVALID", "edge references an unknown port", path))
            continue
        source_type = _port_type(source_node, source_port)
        target_type = _port_type(target_node, target_port)
        if source_type not in DYNAMIC_PORT_TYPES + ["control"] or target_type not in DYNAMIC_PORT_TYPES + ["control"]:
            problems.append(_problem("PORT_TYPE_MISMATCH", "dynamic port_type is invalid", path))
            continue
        expected_edge_type = "control" if source_type == "control" else "data"
        if source_type != target_type or edge.get("edge_type") != expected_edge_type:
            problems.append(_problem("PORT_TYPE_MISMATCH", f"Cannot connect {source_type} to {target_type}", path))
            continue
        key = (source_id, source_port["id"], target_id, target_port["id"])
        if key in connections:
            problems.append(_problem("WORKFLOW_INVALID", "duplicate connection", path))
            continue
        connections.add(key)
        target_key = (target_id, target_port["id"])
        if not target_port.get("multiple") and target_key in occupied:
            problems.append(_problem("WORKFLOW_INVALID", "single-value input has multiple connections", path))
            continue
        occupied.add(target_key)
        connected_inputs.add(target_key)
        adjacency[source_id].append(target_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(target) for target in adjacency.get(node_id, [])):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    if any(visit(node_id) for node_id in node_map if node_id not in visited):
        problems.append(_problem("CYCLE_DETECTED", "Workflow connections must form a DAG", "edges"))

    for node_id, (_, definition) in node_map.items():
        if node_id in future_node_ids:
            continue
        for port in definition.get("inputs", []):
            if port.get("required") and (node_id, port["id"]) not in connected_inputs:
                problems.append(_problem(
                    "MISSING_REQUIRED_INPUT",
                    f"{node_id}.{port['id']} is not connected",
                    f"nodes.{node_id}.inputs.{port['id']}",
                    severity="error" if require_complete else "warning",
                ))

    viewport = document.get("viewport", {"x": 0, "y": 0, "zoom": 1})
    if not isinstance(viewport, dict) or not all(_finite_number(viewport.get(k)) for k in ("x", "y", "zoom")) or not 0.1 <= viewport.get("zoom", 0) <= 1.5:
        problems.append(_problem("WORKFLOW_INVALID", "viewport is invalid", "viewport"))
    variables = document.get("variables", {})
    if not isinstance(variables, dict):
        problems.append(_problem("WORKFLOW_INVALID", "variables must be an object", "variables"))
    else:
        try:
            variables_size = _json_size(variables)
        except (TypeError, ValueError):
            problems.append(_problem("WORKFLOW_INVALID", "variables must contain finite JSON data", "variables"))
        else:
            if variables_size > MAX_VARIABLES_BYTES:
                problems.append(_problem("WORKFLOW_INVALID", "variables exceeds 64 KiB", "variables"))
    _validate_extensions(document.get("extensions"), "extensions", problems)
    settings = document.get("settings", {"on_error": "stop"})
    if not isinstance(settings, dict):
        problems.append(_problem("WORKFLOW_INVALID", "settings must be an object", "settings"))
    else:
        for unknown in sorted(set(settings) - {"on_error", "auto_attach_stubs", "schedules", "watch_folder", "webhook", "notifications"}):
            problems.append(_problem("WORKFLOW_INVALID", f"Unknown settings field: {unknown}", f"settings.{unknown}"))
        if settings.get("on_error", "stop") != "stop":
            problems.append(_problem("WORKFLOW_INVALID", "settings.on_error must be stop in Phase 1", "settings.on_error"))
        if not isinstance(settings.get("auto_attach_stubs", True), bool):
            problems.append(_problem("WORKFLOW_INVALID", "settings.auto_attach_stubs must be a boolean", "settings.auto_attach_stubs"))
        _validate_schedules(settings.get("schedules"), problems)
        _validate_watch_folder(settings.get("watch_folder"), node_map, problems)
        _validate_webhook(settings.get("webhook"), node_map, problems)
        from .notifications import validate_notification_settings
        validate_notification_settings(settings.get("notifications"), problems)
    problems.extend(validate_expressions(document))
    return problems


def validation_errors(problems: list[dict]) -> list[dict]:
    return [problem for problem in problems if problem.get("severity") == "error"]
