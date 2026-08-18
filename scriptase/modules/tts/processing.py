"""Resolve narration-processing parameters at the TTS-stage boundary.

Script values are nullable overrides. A missing value inherits the Channel;
the node configuration is only a fallback for runs that have no Channel.
Keeping this resolution here gives orchestration, TTS, and Schema one shape.
"""

from __future__ import annotations

from typing import Any, Mapping

DEFAULT_REMOVE_SILENCE = True
DEFAULT_SPEED = 1.0


def resolve_narration_processing(
    channel: Mapping[str, Any] | None = None,
    script: Mapping[str, Any] | None = None,
    node: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    channel = channel if isinstance(channel, Mapping) else {}
    script = script if isinstance(script, Mapping) else {}
    node = node if isinstance(node, Mapping) else {}

    remove_silence, silence_source = _resolve_bool(
        script.get("remove_silence"),
        channel.get("remove_silence"),
        node.get("remove_silence"),
        DEFAULT_REMOVE_SILENCE,
    )
    speed, speed_source = _resolve_speed(
        script.get("speed"),
        channel.get("speed"),
        node.get("speed"),
        DEFAULT_SPEED,
    )
    return {
        "remove_silence": remove_silence,
        "speed": speed,
        "remove_silence_source": silence_source,
        "speed_source": speed_source,
        "inherited": silence_source != "script" and speed_source != "script",
    }


def _resolve_bool(script: Any, channel: Any, node: Any, default: bool):
    for value, source in ((script, "script"), (channel, "channel"), (node, "node")):
        if isinstance(value, bool):
            return value, source
    return default, "default"


def _resolve_speed(script: Any, channel: Any, node: Any, default: float):
    for value, source in ((script, "script"), (channel, "channel"), (node, "node")):
        if value is None or isinstance(value, bool):
            continue
        try:
            speed = float(value)
        except (TypeError, ValueError):
            continue
        if 0.25 <= speed <= 4.0:
            return speed, source
    return default, "default"


__all__ = ["resolve_narration_processing"]
