"""Scenes Module — AI Scene Script Generation Routes"""

import json
import os

from flask import Blueprint, jsonify
from loguru import logger

from config import SCENES_DIR, ALIGN_DIR, N8N_WEBHOOK_URL, generate_project_id
from scriptase.shared.validation import validate_json
from scriptase.modules.scene_director.schemas import SceneGenerateRequest
from scriptase.modules.scene_director.templates import SCENE_STYLE_TEMPLATES, TEMPLATES_BY_ID
from scriptase.modules.scene_director.style_compiler import public_template_payload, resolve_template_bundle
from scriptase.modules.scene_director.planner import (
    build_scene_blueprints,
    build_visual_bible,
    summarize_blueprints,
)
from scriptase.modules.scene_director.service import generate_with_chapters_chunked
from scriptase.shared.security import sanitize_folder_name, sanitize_project_id

scenes_bp = Blueprint("scenes", __name__)


# ---------------------------------------------------------------------------
# Segment normalization
# ---------------------------------------------------------------------------

def _normalize_segments(segments):
    """Normalize segments from mixed formats to [{index, words, ...}] dicts.

    Accepts:
      - Plain strings: ["text1", "text2"] -> [{index:0, words:"text1"}, ...]
      - SegmentItem objects: preserved with model_dump()
      - Dicts: passed through
    """
    result = []
    for i, seg in enumerate(segments):
        if isinstance(seg, str):
            result.append({"index": i, "words": seg})
        elif hasattr(seg, "model_dump"):
            result.append(seg.model_dump())
        elif isinstance(seg, dict):
            result.append(seg)
        else:
            result.append({"index": i, "words": str(seg)})
    return result


def _planning_segments(segments, full_segments=None):
    if full_segments:
        speech = [dict(seg) for seg in full_segments if not seg.get("is_filler")]
        if speech:
            return speech
    return [dict(seg) for seg in segments]


def _build_generation_context(script, style_id, segments, full_segments=None, custom_style_notes=""):
    planning_segments = _planning_segments(segments, full_segments)
    bundle = resolve_template_bundle(style_id, TEMPLATES_BY_ID, custom_style_notes)
    visual_bible = build_visual_bible(script, planning_segments, bundle["style_spec"])
    scene_blueprints = build_scene_blueprints(planning_segments, visual_bible, bundle["style_spec"])
    plan_summary = summarize_blueprints(scene_blueprints)
    return bundle, visual_bible, scene_blueprints, plan_summary


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@scenes_bp.route("/api/scenes/templates")
def get_templates():
    """Return all available scene style templates."""
    return jsonify([public_template_payload(template) for template in SCENE_STYLE_TEMPLATES])


@scenes_bp.route("/api/scenes/webhook-url")
def get_webhook_url():
    """Return the current scene webhook URL."""
    return jsonify({"url": N8N_WEBHOOK_URL})


def _resolve_scene_provider_id(requested: str | None) -> tuple[str, object | None, str | None]:
    """Resolve a request/default id to (canonical_id, provider_instance, error).

    Absent/empty values map to the historical AI default (`n8n`). The 12.3
    `builtin` bridge remains a permanent input alias of that provider.
    """
    from scriptase.providers.domains import DOMAINS
    from scriptase.providers.hub import hub
    from scriptase.providers.registry import ProviderConstructionError

    selected = (requested or "").strip() or DOMAINS["scene_director"].default_provider
    try:
        instance = hub.create("scene_director", selected)
    except ProviderConstructionError:
        return selected, None, "PROVIDER_UNAVAILABLE"
    if instance is None:
        return selected, None, "PROVIDER_UNAVAILABLE"
    meta = hub.get("scene_director", selected)
    canonical = meta.id if meta is not None else selected
    return canonical, instance, None


def _legacy_provider_http_status(code: str) -> int:
    """Map a ProviderError code onto the legacy flat-error HTTP statuses."""
    if code in {"PROVIDER_REQUEST_INVALID", "PROVIDER_NOT_CONFIGURED"}:
        return 400
    if code == "PROVIDER_TIMEOUT":
        return 504
    if code in {
        "PROVIDER_TRANSPORT_FAILED",
        "PROVIDER_RESPONSE_MALFORMED",
        "PROVIDER_FAILED",
    }:
        return 502
    if code in {"PROVIDER_UNAVAILABLE", "PROVIDER_NOT_FOUND"}:
        return 503
    return 500


@scenes_bp.route("/api/scenes/generate", methods=["POST"])
@validate_json(SceneGenerateRequest)
def generate_scenes(data: SceneGenerateRequest):
    """Generate scenes via the selected `scene_blueprint` provider (step 13.4).

    Dispatches through the provider hub so the Scene Blueprint node and this
    legacy route share one implementation. The top-level envelope is frozen
    (contracts.md §43); only the additive `provider` key is new.

    Accepts JSON body:
      - script: full transcript text
      - style: visual style preset
      - segments: array of {index, words} (non-filler segments only)
      - full_segments: optional full segment list (with fillers) for chapter mode
      - source_folder, aspect_ratio: optional metadata
      - webhook_url: optional override for the webhook URL
      - provider_id: optional scene_blueprint provider (`n8n` default; `builtin`
        alias still accepted)
    """
    from scriptase.providers.errors import ProviderError

    project_id_raw = data.project_id or generate_project_id("pm")
    project_id = sanitize_project_id(project_id_raw)
    if not project_id:
        return jsonify({"error": "Invalid project id"}), 400

    requested = getattr(data, "provider_id", None)
    canonical, provider, error = _resolve_scene_provider_id(requested)
    if error or provider is None:
        return jsonify({"error": f"Scene blueprint provider '{requested or canonical}' is unavailable"}), 503

    # Prefer full_segments (with fillers) when present so chaptering matches
    # the pre-migration route behaviour.
    segments_raw = _normalize_segments(data.segments)
    full_segments_raw = data.full_segments or []
    if full_segments_raw:
        segment_list = list(full_segments_raw)
    else:
        segment_list = list(segments_raw)

    custom_style_notes = getattr(data, "custom_style_notes", None) or data.style_prompt or ""
    configuration = {
        "text": data.script,
        "script": data.script,
        "style": data.style,
        "style_prompt": custom_style_notes,
        "webhook_url": data.webhook_url or "",
        "aspect_ratio": data.aspect_ratio or "9:16",
        "story_tone": getattr(data, "story_tone", None) or "",
        "provider_id": canonical,
    }
    # Merge portable saved settings for the resolved provider (request wins).
    try:
        from scriptase.providers import settings_manager

        saved = settings_manager.portable_provider_settings("scene_director", canonical)
        for key, value in (saved or {}).items():
            if configuration.get(key) in (None, ""):
                configuration[key] = value
    except Exception:
        pass

    segment_result = {
        "segments": segment_list,
        "metadata": {
            "source_folder": sanitize_folder_name(data.source_folder or ""),
        },
    }

    try:
        result = provider.generate(
            segment_result,
            configuration,
            project_id=project_id,
            parent_id=data.parent_id,
            source_folder=sanitize_folder_name(data.source_folder or ""),
        )
    except ProviderError as exc:
        status = _legacy_provider_http_status(exc.code)
        # Flat legacy error string — key set frozen (§43); do not leak details.
        return jsonify({"error": exc.message}), status
    except Exception as e:
        logger.exception("Unexpected error in scene generation")
        return jsonify({"error": "Server error during scene generation"}), 500

    result.pop("path", None)
    if not result.get("provider"):
        result["provider"] = canonical
    return jsonify(result)


# ---------------------------------------------------------------------------
# Chapter-based generation
# ---------------------------------------------------------------------------

def _generate_with_chapters(script, style_id, style_spec, style_prompt,
                            visual_bible, scene_blueprints, plan_summary,
                            full_segments, webhook_url,
                            custom_style_notes=""):
    """Backward-compatible wrapper used by /api/scenes/generate."""
    return generate_with_chapters_chunked(
        script,
        style_id,
        style_spec,
        style_prompt,
        visual_bible,
        scene_blueprints,
        plan_summary,
        full_segments,
        webhook_url,
        custom_style_notes=custom_style_notes,
    )


# ---------------------------------------------------------------------------
# Other routes
# ---------------------------------------------------------------------------

@scenes_bp.route("/api/scenes/history")
def list_scenes():
    """List all generated scene projects."""
    items = []
    if not os.path.exists(SCENES_DIR):
        return jsonify(items)
    for entry in os.listdir(SCENES_DIR):
        json_path = os.path.join(SCENES_DIR, entry, "scenes.json")
        if os.path.isfile(json_path):
            try:
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                item = {
                    "project_id": data.get("project_id", entry),
                    "scene_count": len(data.get("scenes", [])),
                    "timestamp": data.get("timestamp", ""),
                    "source_folder": data.get("source_folder", ""),
                    "style": data.get("style", ""),
                    "generation_time": (
                        data.get("generation_time")
                        or (data.get("pipeline_timing", {}) or {}).get("scenes", 0)
                    ),
                }
                if data.get("parent_id"):
                    item["parent_id"] = data["parent_id"]
                items.append(item)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
                logger.debug("Skipping unreadable scenes history entry {}: {}", json_path, error)
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify(items)


@scenes_bp.route("/api/scenes/<project_id>")
def get_scenes(project_id):
    """Get full scene data for a project."""
    project_id = os.path.basename(project_id)
    json_path = os.path.join(SCENES_DIR, project_id, "scenes.json")
    if not os.path.isfile(json_path):
        return jsonify({"error": "Not found"}), 404
    try:
        with open(json_path, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return jsonify({"error": f"Failed to read scene data: {e}"}), 500


@scenes_bp.route("/api/scenes/audio/<source_folder>")
def get_scene_audio(source_folder):
    """Resolve audio file URL for a source folder."""
    source_folder = os.path.basename(source_folder)
    folder_path = os.path.join(ALIGN_DIR, source_folder)
    if not os.path.isdir(folder_path):
        return jsonify({"error": "Not found"}), 404
    for f in os.listdir(folder_path):
        if f.endswith((".wav", ".mp3")):
            return jsonify({"url": f"/output/alignments/{source_folder}/{f}"})
    return jsonify({"error": "No audio file found"}), 404
