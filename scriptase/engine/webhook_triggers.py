"""Loopback-only webhook trigger configuration, tokens, and payload mapping."""

from __future__ import annotations

import hmac
import math
import os
import re
import secrets
import threading
from typing import Any, Mapping

from config import OUTPUT_DIR
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

from .registry import get_node_type
from .sample_data import validate_stub_payload


HOOK_TOKEN_DIR = os.path.join(OUTPUT_DIR, "workflows", "hook-tokens")
MAX_WEBHOOK_PAYLOAD_BYTES = 64 * 1024
MAX_WEBHOOK_MAPPINGS = 32
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
PAYLOAD_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]{0,63}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,63}){0,7}$"
)
_TOKEN_LOCK = threading.RLock()


class WebhookPayloadError(ValueError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details = dict(details or {})


def _token_path(workflow_id: str, root: str | None = None) -> str:
    return safe_join(root or HOOK_TOKEN_DIR, f"{workflow_id}.json")


def generate_token() -> str:
    """Return a cryptographically random, URL-safe webhook credential."""
    return secrets.token_urlsafe(32)


def webhook_token(workflow_id: str, *, regenerate: bool = False, root: str | None = None) -> str:
    """Load a workflow token, creating or replacing it atomically as requested."""
    with _TOKEN_LOCK:
        path = _token_path(workflow_id, root)
        if not regenerate:
            try:
                record = safe_json_read(path)
                token = record.get("token") if isinstance(record, dict) else None
                if isinstance(token, str) and TOKEN_RE.fullmatch(token):
                    return token
            except (FileNotFoundError, OSError, ValueError):
                pass
        token = generate_token()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        safe_json_write(path, {"workflow_id": workflow_id, "token": token}, indent=2)
        return token


def token_matches(workflow_id: str, supplied: str, *, root: str | None = None) -> bool:
    if not isinstance(supplied, str) or not TOKEN_RE.fullmatch(supplied):
        return False
    try:
        expected = webhook_token(workflow_id, root=root)
    except (OSError, ValueError):
        return False
    return hmac.compare_digest(expected, supplied)


def _port_type(node: Mapping, port: Mapping) -> str:
    if port.get("type") != "dynamic":
        return str(port.get("type", ""))
    return str((node.get("configuration") or {}).get("port_type", ""))


def validate_webhook_settings(value: Any, node_map: Mapping, problems: list[dict]) -> None:
    """Append workflow-validation problems for ``settings.webhook``."""
    if value is None:
        return
    path = "settings.webhook"
    if not isinstance(value, dict):
        problems.append({"code": "WORKFLOW_INVALID", "message": "settings.webhook must be an object", "path": path, "severity": "error"})
        return
    for unknown in sorted(set(value) - {"enabled", "mappings", "channel_id"}):
        problems.append({"code": "WORKFLOW_INVALID", "message": f"Unknown webhook field: {unknown}", "path": f"{path}.{unknown}", "severity": "error"})
    if not isinstance(value.get("enabled"), bool):
        problems.append({"code": "WORKFLOW_INVALID", "message": "Webhook enabled must be a boolean", "path": f"{path}.enabled", "severity": "error"})
    channel_id = value.get("channel_id")
    if channel_id is not None and channel_id != "":
        if not isinstance(channel_id, str) or not re.fullmatch(r"ch_[A-Z0-9]{6}", channel_id):
            problems.append({
                "code": "WORKFLOW_INVALID",
                "message": "Webhook channel_id must match ch_[A-Z0-9]{6}",
                "path": f"{path}.channel_id",
                "severity": "error",
            })
    mappings = value.get("mappings")
    if not isinstance(mappings, list):
        problems.append({"code": "WORKFLOW_INVALID", "message": "Webhook mappings must be an array", "path": f"{path}.mappings", "severity": "error"})
        return
    if len(mappings) > MAX_WEBHOOK_MAPPINGS:
        problems.append({"code": "WORKFLOW_INVALID", "message": f"A webhook can have at most {MAX_WEBHOOK_MAPPINGS} mappings", "path": f"{path}.mappings", "severity": "error"})
    if value.get("enabled") and not mappings:
        problems.append({"code": "WORKFLOW_INVALID", "message": "An enabled webhook needs at least one input mapping", "path": f"{path}.mappings", "severity": "error"})
    seen_targets = set()
    for index, mapping in enumerate(mappings):
        item_path = f"{path}.mappings.{index}"
        if not isinstance(mapping, dict):
            problems.append({"code": "WORKFLOW_INVALID", "message": "Webhook mapping must be an object", "path": item_path, "severity": "error"})
            continue
        for unknown in sorted(set(mapping) - {"payload_path", "target_node_id", "target_port", "required"}):
            problems.append({"code": "WORKFLOW_INVALID", "message": f"Unknown webhook mapping field: {unknown}", "path": f"{item_path}.{unknown}", "severity": "error"})
        payload_path = mapping.get("payload_path")
        if not isinstance(payload_path, str) or not PAYLOAD_PATH_RE.fullmatch(payload_path):
            problems.append({"code": "WORKFLOW_INVALID", "message": "Payload path must be a dotted JSON field path", "path": f"{item_path}.payload_path", "severity": "error"})
        if not isinstance(mapping.get("required"), bool):
            problems.append({"code": "WORKFLOW_INVALID", "message": "Webhook mapping required must be a boolean", "path": f"{item_path}.required", "severity": "error"})
        node_id, port_id = mapping.get("target_node_id"), mapping.get("target_port")
        if not isinstance(node_id, str) or not isinstance(port_id, str):
            problems.append({"code": "WORKFLOW_INVALID", "message": "Webhook target must name a node and input port", "path": item_path, "severity": "error"})
            continue
        target = (node_id, port_id)
        if target in seen_targets:
            problems.append({"code": "WORKFLOW_INVALID", "message": "Webhook target ports must be unique", "path": item_path, "severity": "error"})
        seen_targets.add(target)
        pair = node_map.get(node_id)
        if not pair or pair[0].get("disabled"):
            problems.append({"code": "WORKFLOW_INVALID", "message": "Webhook target node is unavailable", "path": f"{item_path}.target_node_id", "severity": "error"})
            continue
        node, definition = pair
        port = next((entry for entry in definition.get("inputs", []) if entry.get("id") == port_id), None)
        if port is None or _port_type(node, port) in {"", "control"}:
            problems.append({"code": "WORKFLOW_INVALID", "message": "Webhook target must be a declared data input port", "path": f"{item_path}.target_port", "severity": "error"})


_MISSING = object()


def _lookup(payload: Mapping, path: str) -> Any:
    value: Any = payload
    for segment in path.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            return _MISSING
        value = value[segment]
    return value


def _valid_json_shape(value: Any) -> bool:
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 20:
            return False
        if item is None or isinstance(item, (str, bool)):
            continue
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if isinstance(item, float) and not math.isfinite(item):
                return False
            continue
        if isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, dict) and all(isinstance(key, str) for key in item):
            stack.extend((child, depth + 1) for child in item.values())
        else:
            return False
    return True


def map_webhook_payload(workflow: Mapping, payload: Mapping) -> dict[str, dict[str, Any]]:
    """Validate declared mappings and produce scheduler input overrides."""
    if not isinstance(payload, Mapping) or not _valid_json_shape(payload):
        raise WebhookPayloadError("Webhook payload must be a finite JSON object")
    settings = (workflow.get("settings") or {}).get("webhook") or {}
    nodes = {node.get("id"): node for node in workflow.get("nodes", []) if isinstance(node, Mapping)}
    overrides: dict[str, dict[str, Any]] = {}
    for mapping in settings.get("mappings", []):
        path = mapping["payload_path"]
        value = _lookup(payload, path)
        if value is _MISSING:
            if mapping.get("required"):
                raise WebhookPayloadError(
                    f"Required webhook field is missing: {path}", details={"payload_path": path}
                )
            continue
        node = nodes[mapping["target_node_id"]]
        definition = get_node_type(node["type"]) or {}
        port = next(item for item in definition.get("inputs", []) if item.get("id") == mapping["target_port"])
        port_type = _port_type(node, port)
        typed_problems = validate_stub_payload(port_type, value)
        if typed_problems:
            raise WebhookPayloadError(
                f"Webhook field {path} is not valid {port_type}",
                details={"payload_path": path, "port_type": port_type, "problems": typed_problems},
            )
        overrides.setdefault(mapping["target_node_id"], {})[mapping["target_port"]] = value
    return overrides
