"""Importable story generation service shared by non-HTTP callers."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Callable, Mapping

from config import N8N_STORY_WEBHOOK_URL, STORIES_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.shared.security import is_safe_webhook_url
from scriptase.shared.webhooks import call_webhook

from .engine import parse_story_sections
from .history import append_history
from .prompts import (
    WORDS_PER_SECOND,
    build_story_system_prompt,
    build_story_user_prompt,
    choose_story_concept_family,
    compute_word_target,
)
from .schemas import StoryGenerateRequest


class StoryServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def generate_story(
    configuration: Mapping[str, Any],
    *,
    project_id: str,
    provider_id: str = "script_n8n",
    webhook_caller: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate, parse, and persist a story without Flask request state.

    `webhook_caller` defaults to the module-level `call_webhook` so tests can
    patch `scriptase.modules.script.service.call_webhook` (or inject a caller) without
    fighting a frozen default-argument binding.

    `provider_id` is the resolved canonical script-provider identity stamped
    into artifact metadata (P33 / step 13.3). Callers that wrap this service
    as a registered provider pass their own id; the historical default is the
    app-prompt `script_n8n` path (formerly `gemini`).
    """
    data = StoryGenerateRequest.model_validate(dict(configuration or {}))
    webhook_url = data.webhook_url or N8N_STORY_WEBHOOK_URL
    allow_private = os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
    if not is_safe_webhook_url(webhook_url, allow_private=allow_private):
        raise StoryServiceError("STORY_WEBHOOK_UNSAFE", "Unsafe story webhook URL")

    resolved_provider = (provider_id or "script_n8n").strip() or "script_n8n"
    concept_family = choose_story_concept_family(
        data.preset_style,
        data.story_category,
        data.language,
        niche_preset=data.niche_preset,
    )
    payload = {
        "system_prompt": build_story_system_prompt(
            data.preset_style,
            data.story_category,
            data.duration,
            data.language,
            story_tone=data.story_tone,
            language_level=data.language_level,
        ),
        "user_prompt": build_story_user_prompt(
            data.preset_style,
            data.story_category,
            data.duration,
            data.language,
            idea=data.idea,
            niche_preset=data.niche_preset,
            concept_family=concept_family,
        ),
        "preset_style": data.preset_style,
        "story_category": data.story_category,
        "story_tone": data.story_tone,
        "duration": data.duration,
        "language": data.language,
        "word_target": compute_word_target(data.duration),
        "structure": ["hook", "build", "climax", "cta"],
    }
    started = time.perf_counter()
    caller = webhook_caller or call_webhook
    result = caller(webhook_url, payload, timeout=120, label="Story webhook")
    raw_text = result.get("story_text", "")
    if not raw_text:
        raw_text = next((result.get(key, "") for key in ("output", "text", "response") if result.get(key)), "")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise StoryServiceError("STORY_TEXT_MISSING", "Story webhook returned no story text")

    parsed = parse_story_sections(raw_text)
    generated_at = datetime.now().astimezone().isoformat()
    generation_time = round(time.perf_counter() - started, 3)
    estimated_duration = round(parsed["word_count"] / WORDS_PER_SECOND)
    story_data = {
        "project_id": project_id,
        "story_text": parsed["story_text"],
        "sections": parsed["sections"],
        "metadata": {
            "preset_style": data.preset_style,
            "language": data.language,
            "story_category": data.story_category,
            "story_tone": data.story_tone,
            "duration": data.duration,
            "word_count": parsed["word_count"],
            "estimated_duration": estimated_duration,
            "provider": resolved_provider,
            "generation_time": generation_time,
            "timestamp": generated_at,
            "concept_family": concept_family,
        },
        "pipeline_ref": {"tts_project_id": None, "scenes_project_id": None},
    }
    path = os.path.join(STORIES_DIR, project_id, "story.json")
    safe_json_write(path, story_data, indent=2)

    try:
        append_history(
            preset_style=data.preset_style,
            category=data.story_category,
            language=data.language,
            hook=parsed["sections"].get("hook", ""),
            opening=(parsed["sections"].get("build", "") or "").split(".")[0],
            timestamp=generated_at,
            concept_family=concept_family,
        )
    except Exception:
        # History improves prompt diversity but is not part of the node result.
        pass

    return {**story_data, "path": path}
