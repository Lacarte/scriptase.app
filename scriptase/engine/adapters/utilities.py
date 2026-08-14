"""Side-effect-free utility node adapters with explicit branch semantics."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from .common import AdapterError, CONTROL, context_value


def set_value(inputs, config, context):
    return {"control": CONTROL, "value": (config or {}).get("value")}


def _contains(value: Any, expected: Any) -> bool:
    if isinstance(value, str):
        return isinstance(expected, str) and expected in value
    if isinstance(value, list):
        return expected in value
    if isinstance(value, Mapping):
        return expected in value
    return False


def condition(inputs, config, context):
    value = inputs["value"]
    configuration = config or {}
    operator = configuration.get("operator", "truthy")
    expected = configuration.get("compare_to")
    matches = {
        "truthy": lambda: bool(value),
        "falsy": lambda: not bool(value),
        "equals": lambda: value == expected,
        "not_equals": lambda: value != expected,
        "contains": lambda: _contains(value, expected),
    }
    predicate = matches.get(operator)
    if predicate is None:
        raise AdapterError("CONDITION_OPERATOR_INVALID", f"Unsupported condition operator: {operator}")
    # The missing port is the scheduler-level inactive-branch signal.  Do not
    # emit it with None: JSON null is a legitimate branch value.
    return {"true" if predicate() else "false": value}


def merge(inputs, config, context):
    values = list(inputs.get("values") or [])
    if not values:
        raise AdapterError("MERGE_INPUT_EMPTY", "Merge requires at least one active input")
    mode = (config or {}).get("mode", "array")
    if mode == "array":
        value = values
    elif mode == "first":
        value = values[0]
    elif mode == "object":
        value = {}
        for item in values:
            if not isinstance(item, Mapping):
                raise AdapterError("MERGE_OBJECT_REQUIRED", "Object merge requires every active input to be an object")
            value.update(item)
    else:
        raise AdapterError("MERGE_MODE_INVALID", f"Unsupported merge mode: {mode}")
    return {"control": CONTROL, "value": value}


def wait(inputs, config, context):
    delay_ms = (config or {}).get("delay_ms", 1000)
    remaining = float(delay_ms) / 1000.0
    stop_requested = context_value(context, "stop_requested", None) or (lambda: False)
    while remaining > 0:
        if stop_requested():
            raise AdapterError("CANCELLED", "Execution was cancelled")
        interval = min(0.05, remaining)
        time.sleep(interval)
        remaining -= interval
    if stop_requested():
        raise AdapterError("CANCELLED", "Execution was cancelled")
    return {"control": CONTROL, "value": inputs.get("value")}
