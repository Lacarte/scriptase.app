"""Importable scene-blueprint generation service shared by non-HTTP callers.

Extracted from V2's `studio/pipeline/services.py::_step_scenes` and the
`POST /api/scenes/generate` route body so the registered `n8n` provider and the
HTTP route share one implementation (step 13.4). Step 0.3 pulled the last three
helpers this module used to import back out of `routes.py`, so the dependency
now runs one way only: transport imports service, never the reverse.
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
from scriptase.modules.scene_director.chapters import (
    group_into_chapters, build_chapter_system_prompt, merge_chapter_results,
    chunk_segments, build_script_window, validate_scene_indexes,
)
from scriptase.modules.scene_director.continuity import build_progress_state
from scriptase.modules.scene_director.planner import slice_scene_blueprints


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
    from scriptase.modules.scene_director.style_compiler import resolve_template_bundle
    from scriptase.modules.scene_director.templates import TEMPLATES_BY_ID
    from scriptase.modules.scene_director.validators import (
        ensure_analysis_payload,
        finalize_scene_result,
    )
    from scriptase.channels.presets import resolve_niche as _resolve_niche
    from scriptase.modules.scene_director.hooks import _assign_hook_animations

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

    # Step 5.1: stamp stable scene ids + narration onto SceneSpec rows, and
    # re-emit each scene through the frozen §8 shape so scenes.json and the
    # provider envelope share one contract.
    from scriptase.modules.scene_director.providers.contract import (
        stamp_scene_specs_from_segments,
    )

    stamped = stamp_scene_specs_from_segments(
        result.get("scenes") or [],
        speech_segments,
    )
    result["scenes"] = [spec.to_port_dict() for spec in stamped]

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


def _normalize_webhook_response(result):
    """Normalize webhook response to expected {scenes: [...]} format.

    Handles both:
      - Current format: {analysis, scenes: [{index, image_prompt, type_of_scene, ...}]}
      - Simplified format: {analysis, segments: [{index, prompt, type, ...}]}
    """
    if not isinstance(result, dict):
        return result

    if "segments" in result and "scenes" not in result:
        scenes = []
        for seg in result["segments"]:
            scene = {
                "index": seg.get("index"),
                "image_prompt": seg.get("prompt", seg.get("image_prompt", "")),
                "type_of_scene": seg.get("type", seg.get("type_of_scene", "video")),
                "title": seg.get("title", ""),
                "narrative_role": seg.get("narrative_role", "buildup"),
                "text_content": seg.get("text_content"),
            }
            scenes.append(scene)
        result["scenes"] = scenes
        del result["segments"]

    return result


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _coerce_float(value):
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _build_timed_segment_refs(segments, full_segments=None):
    """Return speech segments with stable timing, ordered by time."""
    merged_by_index = {}

    for seg in full_segments or []:
        if seg.get("is_filler"):
            continue
        try:
            idx = int(seg.get("index"))
        except (TypeError, ValueError):
            continue
        merged_by_index[idx] = dict(seg)

    ordered = []
    seen = set()
    for seg in segments or []:
        try:
            idx = int(seg.get("index"))
        except (TypeError, ValueError):
            continue
        base = dict(merged_by_index.get(idx, {}))
        base.update(seg)
        start = _coerce_float(base.get("start"))
        end = _coerce_float(base.get("end"))
        if start is None or end is None or end < start:
            continue
        base["index"] = idx
        base["start"] = start
        base["end"] = end
        base["duration"] = round(end - start, 3)
        merged_by_index[idx] = base
        if idx not in seen:
            ordered.append(base)
            seen.add(idx)

    if not ordered:
        for idx, seg in merged_by_index.items():
            start = _coerce_float(seg.get("start"))
            end = _coerce_float(seg.get("end"))
            if start is None or end is None or end < start:
                continue
            seg["index"] = idx
            seg["start"] = start
            seg["end"] = end
            seg["duration"] = round(end - start, 3)
            ordered.append(seg)

    ordered.sort(key=lambda seg: (seg["start"], seg["index"]))

    total_end = 0.0
    for seg in full_segments or []:
        end = _coerce_float(seg.get("end"))
        if end is not None:
            total_end = max(total_end, end)
    if total_end <= 0 and ordered:
        total_end = ordered[-1]["end"]

    return ordered, round(total_end, 3)


def _apply_segmenter_timing(result, segments, full_segments=None):
    """Make segmenter timing the source of truth for saved scene placement."""
    scenes = result.get("scenes", []) if isinstance(result, dict) else []
    if not scenes:
        return

    timed_segments, total_end = _build_timed_segment_refs(segments, full_segments)
    if not timed_segments:
        return

    missing, unexpected = validate_scene_indexes(result, timed_segments)
    if missing or unexpected:
        raise RuntimeError(
            f"scene index mismatch (missing={missing}, unexpected={unexpected})"
        )

    scene_by_index = {}
    for scene in scenes:
        try:
            idx = int(scene.get("index"))
        except (TypeError, ValueError, AttributeError):
            continue
        scene_by_index[idx] = scene

    ordered_scenes = []
    for pos, seg in enumerate(timed_segments):
        scene = scene_by_index[seg["index"]]
        timeline_start = 0.0 if pos == 0 else seg["start"]
        next_start = timed_segments[pos + 1]["start"] if pos + 1 < len(timed_segments) else total_end
        timeline_end = max(next_start, timeline_start)
        visual_duration = round(timeline_end - timeline_start, 3)
        speech_duration = round(seg["end"] - seg["start"], 3)

        # Cap trailing silence — don't let a scene extend more than 1.5s
        # beyond its speech end (prevents TTS paragraph pauses from bloating scenes)
        MAX_TRAILING_SILENCE = 1.5
        trailing = timeline_end - seg["end"]
        if trailing > MAX_TRAILING_SILENCE and speech_duration > 0:
            timeline_end = round(seg["end"] + MAX_TRAILING_SILENCE, 3)
            visual_duration = round(timeline_end - timeline_start, 3)

        # Enforce minimum scene duration (too-short scenes produce unusable video)
        MIN_SCENE_DURATION = 1.5
        if visual_duration < MIN_SCENE_DURATION:
            visual_duration = MIN_SCENE_DURATION
            timeline_end = timeline_start + visual_duration

        original_duration = scene.get("duration")
        if original_duration is not None:
            scene["model_duration"] = original_duration

        scene["timestamp"] = timeline_start
        scene["timeline_start"] = timeline_start
        scene["timeline_end"] = timeline_end
        scene["duration"] = visual_duration
        scene["segment_start"] = seg["start"]
        scene["segment_end"] = seg["end"]
        scene["segment_duration"] = speech_duration
        scene["segment_words"] = seg.get("words", "")
        ordered_scenes.append(scene)

    result["scenes"] = ordered_scenes
    final_end = max(
        (_coerce_float(scene.get("timeline_end")) or 0.0)
        for scene in ordered_scenes
    )
    result["total_duration"] = round(max(total_end, final_end), 3)


# ---------------------------------------------------------------------------
# Chapter-based generation
# ---------------------------------------------------------------------------

def generate_with_chapters_chunked(script, style_id, style_spec, style_prompt,
                                   visual_bible, scene_blueprints, plan_summary,
                                   full_segments, webhook_url, progress_cb=None,
                                   custom_style_notes="", webhook_caller=None):
    """Generate scenes in chapter mode with digestible payload chunks.

    Each chapter is split into small segment batches and validated to ensure
    all expected indexes are returned, preventing silent scene drops.
    `webhook_caller` defaults to the module-level `_call_webhook` so tests and
    the registered provider can inject a fixture without patching imports.
    """
    caller = webhook_caller or _call_webhook
    chapters = group_into_chapters(full_segments)
    total = len(chapters)
    expected_total = sum(len(c["segments"]) for c in chapters)
    logger.info("Chapter mode: {} chapters from {} segments",
                total, expected_total)

    chapter_results = []
    analysis = None
    failed_chapters = []
    generated_scenes = []

    for i, ch in enumerate(chapters):
        chapter_no = i + 1
        script_window = build_script_window(chapters, i)
        chunk_size = 8
        chapter_done = False

        while not chapter_done:
            seg_chunks = chunk_segments(ch["segments"], chunk_size=chunk_size)
            chunk_results = []
            logger.info("Generating Chapter {}/{}: {} segments as {} chunk(s) of <= {}",
                        chapter_no, total, len(ch["segments"]), len(seg_chunks), chunk_size)
            if progress_cb:
                progress_cb(
                    f"Chapter {chapter_no}/{total}: {len(ch['segments'])} segments "
                    f"in {len(seg_chunks)} chunk(s)"
                )

            try:
                for chunk_idx, seg_chunk in enumerate(seg_chunks, start=1):
                    chunk_blueprints = slice_scene_blueprints(scene_blueprints, seg_chunk)
                    continuation_state = build_progress_state(
                        generated_scenes,
                        visual_bible,
                        plan_summary,
                    ) if generated_scenes else None
                    prompt = build_chapter_system_prompt(
                        style_spec,
                        visual_bible,
                        chunk_blueprints,
                        analysis,
                        i,
                        total,
                        chapters,
                        plan_summary=plan_summary,
                        continuation_state=continuation_state,
                        custom_style_notes=custom_style_notes,
                    )
                    payload = {
                        "script": script_window,
                        "style": style_id,
                        "style_prompt": style_prompt,
                        "system_prompt": prompt,
                        "segments": seg_chunk,
                        "style_spec": style_spec,
                        "visual_bible": visual_bible,
                        "scene_blueprints": chunk_blueprints,
                        "plan_summary": plan_summary,
                        "continuation_state": continuation_state or {},
                        "chapter": chapter_no,
                        "total_chapters": total,
                        "chapter_chunk": chunk_idx,
                        "chapter_chunk_total": len(seg_chunks),
                    }

                    if progress_cb:
                        progress_cb(
                            f"Chapter {chapter_no}/{total}, chunk {chunk_idx}/{len(seg_chunks)}: "
                            f"{len(seg_chunk)} segments"
                        )
                    result = _normalize_webhook_response(
                        caller(webhook_url, payload, timeout=300, label="Scene chapter webhook")
                    )
                    missing, unexpected = validate_scene_indexes(result, seg_chunk)
                    if missing or unexpected:
                        raise RuntimeError(
                            f"chapter {chapter_no} chunk {chunk_idx} mismatch "
                            f"(missing={missing}, unexpected={unexpected})"
                        )
                    chunk_results.append(result)
                    generated_scenes.extend(result.get("scenes", []))

                    if analysis is None and result.get("analysis"):
                        analysis = result["analysis"]

                chapter_results.append(merge_chapter_results(chunk_results))
                chapter_done = True

            except Exception as e:
                logger.error("Chapter {}/{} failed at chunk_size {}: {}",
                             chapter_no, total, chunk_size, e)
                if chunk_size <= 3:
                    failed_chapters.append(chapter_no)
                    if chapter_no == 1:
                        raise
                    break
                chunk_size = max(3, chunk_size // 2)
                logger.warning("Retrying chapter {}/{} with smaller chunk_size={}",
                               chapter_no, total, chunk_size)

    merged = merge_chapter_results(chapter_results)
    scene_count = len(merged.get("scenes", []))
    if failed_chapters:
        merged.setdefault("warnings", []).append(
            f"Chapters {failed_chapters} failed and were skipped — "
            f"{len(chapter_results)}/{total} chapters completed"
        )
    if scene_count != expected_total:
        raise RuntimeError(
            f"Scene count mismatch after chunked generation: got {scene_count}, "
            f"expected {expected_total}"
        )
    return merged


# ---------------------------------------------------------------------------
# Webhook helpers — delegate to shared module
# ---------------------------------------------------------------------------

from scriptase.shared.webhooks import call_webhook as _call_webhook  # noqa: E402
