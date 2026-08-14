"""Offline random-template script provider — step 13.1.

Moves the frontend's static `RANDOM_STORIES` catalog and its immediate-repeat
avoidance rule behind a backend provider so the random-story UI and the Story
Generator node share one source of truth.
"""

from __future__ import annotations

import json
import os
import random
import threading
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Mapping

from config import STORIES_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.modules.script.prompts import WORDS_PER_SECOND
from scriptase.modules.script.providers.base import ScriptProvider
from scriptase.modules.script.providers.contract import ScriptRequest, ScriptResultPayload


_TEMPLATES_PATH = os.path.join(os.path.dirname(__file__), "templates.json")

# Process-wide anti-repeat, matching the previous frontend `lastIdx` behaviour.
_last_index = -1
_last_lock = threading.Lock()


@lru_cache(maxsize=1)
def load_templates() -> tuple[dict, ...]:
    """The curated catalog, loaded once per process."""
    with open(_TEMPLATES_PATH, encoding="utf-8") as handle:
        raw = json.load(handle)
    entries: list[dict] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        styles = item.get("styles") or []
        if not isinstance(styles, list):
            styles = []
        entries.append({
            "text": text,
            "type": str(item.get("type") or "").strip(),
            "styles": [str(s) for s in styles if s],
        })
    if not entries:
        raise RuntimeError("random_template catalog is empty")
    return tuple(entries)


def template_types() -> list[str]:
    """Stable, unique type labels for settings and the random-pick API."""
    seen: list[str] = []
    for entry in load_templates():
        typ = entry["type"]
        if typ and typ not in seen:
            seen.append(typ)
    return seen


def _pool_for_category(category: str | None) -> list[tuple[int, dict]]:
    """`(catalog_index, entry)` pairs, optionally filtered by type label."""
    catalog = load_templates()
    needle = (category or "").strip().lower()
    if not needle:
        return list(enumerate(catalog))
    matched = [
        (idx, entry)
        for idx, entry in enumerate(catalog)
        if entry["type"].lower() == needle
    ]
    # An unknown category falls back to the full catalog rather than failing
    # the random-story button (legacy UI never filtered).
    return matched or list(enumerate(catalog))


def pick_template(
    *,
    category: str | None = None,
    seed: int | None = None,
    avoid_repeat: bool = True,
) -> dict:
    """Select one catalog entry.

    When `seed` is set the pick is fully deterministic and anti-repeat is
    skipped so tests stay reproducible. Otherwise the previous index is avoided
    when the pool has more than one entry (the old frontend rule).
    """
    global _last_index

    pool = _pool_for_category(category)
    if seed is not None:
        idx_in_pool = random.Random(int(seed)).randrange(len(pool))
        catalog_index, entry = pool[idx_in_pool]
        return {
            **entry,
            "index": catalog_index,
            "seed": int(seed),
        }

    with _last_lock:
        if len(pool) == 1:
            catalog_index, entry = pool[0]
        else:
            # Prefer avoiding the last *catalog* index so a category filter that
            # reshapes the pool still respects the global anti-repeat rule.
            candidates = [
                pair for pair in pool if not avoid_repeat or pair[0] != _last_index
            ] or pool
            catalog_index, entry = random.choice(candidates)
        _last_index = catalog_index

    return {**entry, "index": catalog_index, "seed": None}


def reset_anti_repeat() -> None:
    """Test helper: forget the last pick so cases do not share process state."""
    global _last_index
    with _last_lock:
        _last_index = -1


def _build_document(
    entry: Mapping[str, Any],
    *,
    project_id: str,
    request: ScriptRequest,
    settings: Mapping[str, Any] | None = None,
) -> tuple[dict, str]:
    """Write `stories/{project_id}/story.json` and return `(document, path)`."""
    settings = dict(settings or {})
    script_text = str(entry["text"])
    word_count = len(script_text.split())
    estimated = round(word_count / WORDS_PER_SECOND)
    language = (
        request.language
        or str(settings.get("language") or "english")
    )
    # Offline templates have no Hook/Build/Climax/CTA labels. Keep sections
    # empty so consumers that require structured_sections do not invent shape.
    sections: dict[str, str] = {}
    payload = ScriptResultPayload(
        script_text=script_text,
        sections=sections,
        word_count=word_count,
        estimated_duration_s=estimated,
        language=language,
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    story_data = {
        "project_id": project_id,
        "story_text": payload.script_text,
        "sections": dict(payload.sections),
        "metadata": {
            "preset_style": request.style or (entry.get("styles") or [""])[0],
            "language": payload.language,
            "story_category": request.category or entry.get("type") or "",
            "story_tone": request.tone or str(settings.get("tone") or ""),
            "duration": request.target_duration_s,
            "word_count": payload.word_count,
            "estimated_duration": payload.estimated_duration_s,
            # Resolved canonical id (P33 / step 13.3) — same key the AI path uses.
            "provider": "random_template",
            "template_type": entry.get("type") or "",
            # Flat scalar only — envelope metadata drops non-scalars (§31.1).
            "template_styles": ",".join(entry.get("styles") or []),
            "template_index": entry.get("index"),
            "seed": entry.get("seed"),
            "timestamp": generated_at,
        },
        "pipeline_ref": {"tts_project_id": None, "scenes_project_id": None},
    }
    path = os.path.join(STORIES_DIR, project_id, "story.json")
    safe_json_write(path, story_data, indent=2)
    return story_data, path


class RandomTemplateScriptProvider(ScriptProvider):
    """Local catalog pick with anti-repeat and optional deterministic seeding."""

    def generate(self, configuration: Mapping[str, Any], *, project_id: str) -> dict:
        request = ScriptRequest.from_configuration(configuration)
        settings = dict(configuration or {})
        category = (
            request.category
            or str(settings.get("default_category") or "")
            or None
        )
        entry = pick_template(category=category, seed=request.seed)
        document, path = _build_document(
            entry, project_id=project_id, request=request, settings=settings
        )
        return {**document, "path": path}

    def pick(
        self,
        *,
        category: str | None = None,
        seed: int | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> dict:
        """UI-facing pick: catalog fields only, no project artifact write."""
        settings = dict(settings or {})
        resolved_category = category or str(settings.get("default_category") or "") or None
        entry = pick_template(category=resolved_category, seed=seed)
        return {
            "text": entry["text"],
            "type": entry["type"],
            "styles": list(entry["styles"]),
            "index": entry["index"],
            "seed": entry["seed"],
            "word_count": len(entry["text"].split()),
        }


def create() -> RandomTemplateScriptProvider:
    return RandomTemplateScriptProvider()


def health_check(settings: dict) -> dict:
    try:
        count = len(load_templates())
    except Exception as exc:
        return {"status": "fail", "message": f"Catalog unavailable: {exc}"}
    return {
        "status": "ok",
        "latency_ms": 0,
        "message": f"Offline catalog ready ({count} templates)",
        "details": {"template_count": count, "types": template_types()},
    }


def validate_settings(settings: dict) -> list[dict]:
    issues: list[dict] = []
    category = str((settings or {}).get("default_category") or "").strip()
    if category and category not in template_types():
        issues.append({
            "field": "default_category",
            "severity": "warning",
            "message": f"Unknown template category '{category}'",
        })
    language = str((settings or {}).get("language") or "english").strip().lower()
    if language and language not in ("english", "french", "spanish"):
        issues.append({
            "field": "language",
            "severity": "warning",
            "message": f"Unsupported language '{language}'",
        })
    return issues
