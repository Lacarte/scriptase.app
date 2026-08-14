"""Deterministic echo node rebuilt with the node-author guide."""

from scriptase.engine.adapters.common import CONTROL


def execute(inputs, config, context):
    """Echo the connected source, falling back to the configured JSON value."""
    return {
        "control": CONTROL,
        "result": inputs.get("source", config.get("value", {})),
    }
