"""Lab service — build and inspect script prompts without running a full job.

Everything here is read-only and side-effect-free: it composes the same prompts
`generate_story` would send (so the Lab shows exactly what the pipeline uses),
and scans saved stories for the prompt block persisted alongside each script.
No webhook is called and nothing is written.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from config import STORIES_DIR
from scriptase.modules.script.prompts import (
    build_story_system_prompt,
    build_story_user_prompt,
    choose_story_concept_family,
    compute_word_target,
)


def preview_prompt(inputs: Mapping[str, Any] | None) -> dict:
    """Compose the system + user prompt for a set of inputs, decomposed.

    Mirrors what `generate_story` builds, so the Lab shows the real thing. The
    user prompt varies per call (random angle, seed, sampled topics) — that is
    the diversity engine, and previewing it is how you see that variation.
    """
    data = dict(inputs or {})
    preset_style = str(data.get("preset_style") or "cinematic").strip() or "cinematic"
    story_category = str(data.get("story_category") or "").strip()
    story_tone = str(data.get("story_tone") or "").strip() or None
    language = str(data.get("language") or "english").strip() or "english"
    language_level = str(data.get("language_level") or "").strip() or None
    niche_preset = str(data.get("niche_preset") or "").strip() or None
    idea = str(data.get("idea") or "").strip() or None
    try:
        duration = int(data.get("duration") or 60)
    except (TypeError, ValueError):
        duration = 60

    concept_family = choose_story_concept_family(
        preset_style, story_category, language, niche_preset=niche_preset
    )
    system_prompt = build_story_system_prompt(
        preset_style,
        story_category,
        duration,
        language,
        story_tone=story_tone,
        language_level=language_level,
    )
    user_prompt = build_story_user_prompt(
        preset_style,
        story_category,
        duration,
        language,
        idea=idea,
        niche_preset=niche_preset,
        concept_family=concept_family,
    )
    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "word_target": compute_word_target(duration),
        "structure": ["hook", "build", "climax", "cta"],
        "decomposed": _decompose(user_prompt),
        "inputs": {
            "preset_style": preset_style,
            "story_category": story_category,
            "story_tone": story_tone or "",
            "language": language,
            "language_level": language_level or "",
            "duration": duration,
            "niche_preset": niche_preset or "",
            "idea": idea or "",
            "concept_family": concept_family,
        },
    }


# The labeled blocks the user prompt is built from (prompts.py). Splitting on
# them lets the Lab render each part as its own inspectable row.
_USER_PROMPT_LABELS = (
    "CREATIVE DIRECTION",
    "CONCEPT FAMILY FOR THIS RUN",
    "RECENT CONCEPT FAMILIES TO AVOID",
    "TOPIC COVERAGE",
    "GROUND IT IN SCENES",
    "AVOID THE USUAL ANGLE",
    "NARRATIVE LENS",
    "Build the story around this idea",
)


def _decompose(user_prompt: str) -> list[dict]:
    """Break the user prompt into its labeled parts for row-by-row inspection."""
    parts: list[dict] = []
    text = user_prompt or ""
    # The base instruction is everything before the first labeled block.
    first = len(text)
    for label in _USER_PROMPT_LABELS:
        idx = text.find(label)
        if idx != -1:
            first = min(first, idx)
    base = text[:first].strip()
    if base:
        parts.append({"label": "Base instruction", "text": base})
    for label in _USER_PROMPT_LABELS:
        idx = text.find(label)
        if idx == -1:
            continue
        end = len(text)
        for other in _USER_PROMPT_LABELS:
            oidx = text.find(other, idx + len(label))
            if oidx != -1:
                end = min(end, oidx)
        chunk = text[idx:end].strip()
        title, _, body = chunk.partition(":")
        parts.append({"label": title.strip(), "text": body.strip() or chunk})
    return parts


def list_recent_prompts(limit: int = 30) -> list[dict]:
    """Recent generated stories that carry a saved `prompt` block, newest first."""
    if not os.path.isdir(STORIES_DIR):
        return []

    records: list[dict] = []
    for name in os.listdir(STORIES_DIR):
        story_path = os.path.join(STORIES_DIR, name, "story.json")
        if not os.path.isfile(story_path):
            continue
        try:
            with open(story_path, encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        prompt = doc.get("prompt")
        if not isinstance(prompt, dict):
            continue
        meta = doc.get("metadata") or {}
        records.append({
            "project_id": doc.get("project_id") or name,
            "timestamp": meta.get("timestamp") or "",
            "story_category": meta.get("story_category") or "",
            "preset_style": meta.get("preset_style") or "",
            "concept_family": meta.get("concept_family") or "",
            "word_count": meta.get("word_count") or 0,
            "duration": meta.get("duration") or 0,
            "provider": meta.get("provider") or "",
            "prompt": {
                "system_prompt": prompt.get("system_prompt") or "",
                "user_prompt": prompt.get("user_prompt") or "",
                "word_target": prompt.get("word_target") or 0,
                "inputs": prompt.get("inputs") or {},
                "decomposed": _decompose(prompt.get("user_prompt") or ""),
            },
            "story_text": doc.get("story_text") or "",
        })

    records.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return records[: max(1, int(limit or 30))]


__all__ = ["preview_prompt", "list_recent_prompts"]
