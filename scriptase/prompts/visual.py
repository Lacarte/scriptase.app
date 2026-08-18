"""Canonical per-scene visual prompt composition.

The scene planner owns the subject (what is in frame).  A Channel owns the
visual treatment, while mood and delivery aspect complete the provider-ready
prompt.  Keeping this small function provider-neutral lets Scene Director,
image providers, and the Channel preview share one exact composition rule.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip().strip(" ,.;")


def compose_visual_prompt(
    scene_subject: Any,
    visual_style: Any = "",
    mood: Any = "",
    aspect_ratio: Any = "",
) -> str:
    """Compose subject + Channel style + mood + aspect in that exact order."""
    subject = _text(scene_subject)
    if not subject:
        return ""

    parts = [subject]
    style = _text(visual_style)
    if style:
        parts.append(style)
    mood_text = _text(mood)
    if mood_text:
        parts.append(f"Mood: {mood_text}")
    aspect = _text(aspect_ratio)
    if aspect:
        parts.append(f"Aspect ratio: {aspect}")
    return ". ".join(parts) + "."


__all__ = ["compose_visual_prompt"]
