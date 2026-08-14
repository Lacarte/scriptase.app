"""Importable scene-blueprint generation service shared by non-HTTP callers.

Extracted from `scriptase.modules.pipeline.services._step_scenes` and the
`POST /api/scenes/generate` route body so the registered `n8n` provider, the
legacy pipeline step, and the legacy HTTP route share one implementation
(step 13.4).
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Callable, Mapping

from loguru import logger

from config import N8N_WEBHOOK_URL, SCENES_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.shared.security import is_safe_webhook_url
from scriptase.shared.webhooks import call_webhook


class SceneServiceError(RuntimeError):
    """Structured scene-generation failure mapped by the provider layer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def generate_scenes(
    segment_result: Mapping[str, Any],
    configuration: Mapping[str, Any],
    *,
    project_id: str,
    provider_id: str = "n8n",
    webhook_caller: Callable[..., Mapping[str, Any]] | None = None,
    progress_cb: Callable[[str], None] | None = None,
    parent_id: str | None = None,
    source_folder: str | None = None,
) -> dict[str, Any]:
    """Generate, annotate, and persist a scenes document without Flask state.

    `webhook_caller` defaults to the shared `call_webhook` so tests can inject a
    fixture without fighting a frozen default-argument binding.

    `provider_id` is the resolved canonical scene-blueprint provider identity
    stamped onto the artifact (P33 / step 13.4).
    """
    from scriptase.modules.scene_director.chapters import should_use_chapters
    from scriptase.modules.scene_director.planner import (
        build_scene_blueprints,
        build_visual_bible,
        summarize_blueprints,
    )
    from scriptase.modules.scene_director.prompts import build_scene_system_prompt
    from scriptase.modules.scene_director.routes import (
        _apply_segmenter_timing,
        _normalize_webhook_response,
        generate_with_chapters_chunked,
    )
    from scriptase.modules.scene_director.style_compiler import resolve_template_bundle
    from scriptase.modules.scene_director.templates import TEMPLATES_BY_ID
    from scriptase.modules.scene_director.validators import (
        ensure_analysis_payload,
        finalize_scene_result,
    )
    from scriptase.modules.niches.presets import resolve_niche as _resolve_niche
    from scriptase.modules.pipeline.services import _assign_hook_animations

    config = dict(configuration or {})
    all_segments = list((segment_result or {}).get("segments") or [])
    segments = [
        {"index": i, "words": s["words"]}
        for i, s in enumerate(s for s in all_segments if not s.get("is_filler"))
    ]
    if not segments:
        raise SceneServiceError(
            "SCENES_SEGMENTS_EMPTY",
            "No non-filler segments to generate scenes for",
        )

    webhook_url = (config.get("webhook_url") or N8N_WEBHOOK_URL or "").strip()
    allow_private = os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
    if not is_safe_webhook_url(webhook_url, allow_private=allow_private):
        raise SceneServiceError("SCENES_WEBHOOK_UNSAFE", "Unsafe scene webhook URL")

    script = config.get("text") or config.get("script") or ""
    custom_style_notes = (
        config.get("style_prompt") or config.get("custom_style_notes") or ""
    )
    resolved = _resolve_niche(config)
    style_id = resolved["visual_style"]
    bundle = resolve_template_bundle(style_id, TEMPLATES_BY_ID, custom_style_notes)
    planning_segments = [
        {**s, "index": i}
        for i, s in enumerate(s for s in all_segments if not s.get("is_filler"))
    ]
    visual_bible = build_visual_bible(script, planning_segments, bundle["style_spec"])
    scene_blueprints = build_scene_blueprints(
        planning_segments,
        visual_bible,
        bundle["style_spec"],
    )
    plan_summary = summarize_blueprints(scene_blueprints)

    caller = webhook_caller or call_webhook
    started = time.perf_counter()

    try:
        if should_use_chapters(all_segments):
            result = generate_with_chapters_chunked(
                script=script,
                style_id=style_id,
                style_spec=bundle["style_spec"],
                style_prompt=bundle["style_prompt"],
                visual_bible=visual_bible,
                scene_blueprints=scene_blueprints,
                plan_summary=plan_summary,
                full_segments=all_segments,
                webhook_url=webhook_url,
                progress_cb=progress_cb,
                custom_style_notes=custom_style_notes,
                webhook_caller=caller,
            )
        else:
            system_prompt = build_scene_system_prompt(
                bundle["style_spec"],
                visual_bible,
                scene_blueprints,
                plan_summary=plan_summary,
                custom_style_notes=custom_style_notes,
            )
            payload = {
                "script": script,
                "style": style_id,
                "style_prompt": bundle["style_prompt"],
                "system_prompt": system_prompt,
                "segments": segments,
                "style_spec": bundle["style_spec"],
                "visual_bible": visual_bible,
                "scene_blueprints": scene_blueprints,
                "plan_summary": plan_summary,
            }
            result = caller(webhook_url, payload, timeout=180, label="Scene webhook")
    except SceneServiceError:
        raise
    except RuntimeError as exc:
        # Chapter index / count mismatches and exhausted webhook retries.
        message = str(exc).lower()
        if "mismatch" in message or "scene count" in message:
            raise SceneServiceError(
                "SCENES_RESPONSE_MALFORMED",
                "The scene webhook returned an incomplete or mismatched scene set",
            ) from exc
        raise

    result = _normalize_webhook_response(result)
    if not isinstance(result, dict):
        raise SceneServiceError(
            "SCENES_RESPONSE_MALFORMED",
            "The scene webhook returned a non-object payload",
        )
    if not result.get("scenes"):
        raise SceneServiceError(
            "SCENES_RESPONSE_MALFORMED",
            "The scene webhook returned no scenes",
        )

    speech_segments = [
        {**s, "index": i}
        for i, s in enumerate(s for s in all_segments if not s.get("is_filler"))
    ]
    try:
        _apply_segmenter_timing(result, speech_segments, all_segments)
    except RuntimeError as exc:
        raise SceneServiceError(
            "SCENES_RESPONSE_MALFORMED",
            "The scene webhook returned scenes that do not match the segments",
        ) from exc

    ensure_analysis_payload(result, visual_bible, bundle["style_spec"], bundle["template"])
    result["style_spec"] = bundle["style_spec"]
    result["style_prompt"] = bundle["style_prompt"]
    result["scene_blueprints"] = scene_blueprints
    result["visual_bible"] = visual_bible
    if custom_style_notes:
        result["custom_style_notes"] = custom_style_notes
    finalize_scene_result(result, scene_blueprints, visual_bible)

    story_tone = config.get("story_tone") or config.get("tone") or ""
    _assign_hook_animations(result, story_tone)

    resolved_provider = (provider_id or "n8n").strip() or "n8n"
    meta = (segment_result or {}).get("metadata") or {}
    folder = source_folder if source_folder is not None else meta.get("source_folder", "")
    result["project_id"] = project_id
    result["timestamp"] = datetime.now().isoformat()
    result["generation_time"] = round(time.perf_counter() - started, 3)
    result["source_folder"] = folder or ""
    result["style"] = style_id
    result["provider"] = resolved_provider
    if parent_id:
        result["parent_id"] = parent_id

    path = os.path.join(SCENES_DIR, project_id, "scenes.json")
    safe_json_write(path, result, indent=2)
    logger.success("Generated {} scenes -> {}", len(result.get("scenes", [])), project_id)
    return {**result, "path": path}
