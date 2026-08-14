"""Per-preset story history — prevents Gemini from repeating itself.

Mirrors the pattern in scriptase/music/selector.py: a small JSON file per
preset combination tracking the last N generated stories. Before each
generation, the recent hooks/themes are injected into the user prompt as
explicit "do not repeat" examples.

History files live at:
    output/story_history/{preset_style}__{category}__{language}.json

Each preset combo has its own independent memory — Stickman Glow Philosophy
does not interfere with Crimson Silhouette Psychology.
"""

from __future__ import annotations

import json
import os
import re

from loguru import logger

from config import OUTPUT_DIR

_HISTORY_DIR = os.path.join(OUTPUT_DIR, "story_history")
_HISTORY_LIMIT = 10  # remember last 10 stories per preset combo


def _safe_segment(value: str) -> str:
    """Sanitize a string for use in a filename."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", (value or "").strip().lower())
    return cleaned.strip("_") or "default"


def _history_path(preset_style: str, category: str, language: str) -> str:
    """Return the history file path for a preset combination."""
    fname = f"{_safe_segment(preset_style)}__{_safe_segment(category)}__{_safe_segment(language)}.json"
    return os.path.join(_HISTORY_DIR, fname)


def load_history(preset_style: str, category: str, language: str) -> list[dict]:
    """Load recent story summaries for a preset combo. Returns list (oldest first)."""
    path = _history_path(preset_style, category, language)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def append_history(
    preset_style: str,
    category: str,
    language: str,
    hook: str,
    opening: str,
    timestamp: str,
    concept_family: str = "",
) -> None:
    """Append one story summary to the preset's history file (trims to last N).

    Deduplicates against the most recent entry: if the incoming hook matches
    the last recorded hook (case-insensitive, whitespace-trimmed), the call
    is a no-op. This protects against the common double-record case where the
    user generates a story via /story/generate (which records once) and then
    runs the pipeline with that same text (which would record again).
    """
    new_hook = (hook or "").strip()
    path = _history_path(preset_style, category, language)
    history = load_history(preset_style, category, language)

    if history and new_hook:
        last_hook = (history[-1].get("hook") or "").strip()
        if last_hook.lower() == new_hook.lower():
            return  # already recorded — pipeline re-run of an existing story

    history.append({
        "hook": new_hook[:300],
        "opening": (opening or "").strip()[:300],
        "timestamp": timestamp,
        "concept_family": (concept_family or "").strip()[:160],
    })
    history = history[-_HISTORY_LIMIT:]
    try:
        os.makedirs(_HISTORY_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.debug("Could not save story history at {}: {}", path, e)


def format_history_for_prompt(preset_style: str, category: str, language: str) -> str:
    """Format the recent history as a 'do not repeat' block for the user prompt.

    Returns an empty string if there is no history yet (first run for this preset).
    """
    history = load_history(preset_style, category, language)
    if not history:
        return ""

    lines = [
        "RECENT STORIES FOR THIS PRESET — DO NOT REPEAT THEIR HOOKS, OPENINGS, OR CORE THEMES.",
        "Pick a genuinely different angle, subject, and metaphor. The viewer has already seen these:",
    ]
    for i, entry in enumerate(history, 1):
        concept_family = entry.get("concept_family", "").strip()
        hook = entry.get("hook", "").strip()
        opening = entry.get("opening", "").strip()
        if concept_family:
            lines.append(f"{i}. Concept: {concept_family}")
        if hook:
            lines.append(f"   Hook: {hook}" if concept_family else f"{i}. Hook: {hook}")
        if opening and opening != hook:
            lines.append(f"   Opening: {opening}")
    lines.append(
        "Treat the above as forbidden territory — your new story must stand clearly apart "
        "in subject matter, opening line, central metaphor, and emotional arc."
    )
    return "\n".join(lines)
