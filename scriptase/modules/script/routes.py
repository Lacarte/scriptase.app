"""Story Module — AI Story Generation Routes

Provides:
  POST /api/story/generate       — generate via the selected script provider
  POST /api/story/random         — pick a curated sample from random_template
  GET  /api/story/webhook-url    — return the configured story webhook URL
  GET  /api/story/history        — list generated stories
  GET  /api/story/<project_id>   — get a specific story
  GET  /api/story/categories     — list available story categories
"""

import json
import os
from datetime import datetime
from urllib.parse import urlparse, urlunparse

import requests as http_requests
from flask import Blueprint, jsonify, request
from loguru import logger

from config import (
    OUTPUT_DIR,
    STORIES_DIR,
    PROJECTS_DIR,
    SCENES_DIR,
    N8N_STORY_WEBHOOK_URL,
    N8N_CLASSIFY_WEBHOOK_URL,
    generate_project_id,
)
from scriptase.shared.io_utils import safe_json_read
from scriptase.shared.security import is_safe_webhook_url, sanitize_project_id
from scriptase.shared.validation import validate_json
from scriptase.modules.script.schemas import StoryGenerateRequest
from scriptase.modules.script.prompts import (
    STORY_CATEGORIES,
    WORDS_PER_SECOND,
)
from scriptase.modules.script.engine import parse_story_sections
from scriptase.modules.scene_director.templates import SCENE_STYLE_TEMPLATES
from scriptase.channels.presets import CATEGORIES as NICHE_CATEGORIES

story_bp = Blueprint("story", __name__)

# V2's `config.PIPELINE_DIR`. The classic pipeline package is not ported, so the
# constant no longer lives in `config`, but the managed `output/` layout stays
# V2-compatible (Phase 10 import) and `output/pipeline/<id>/pipeline.json` is
# still one of the recovery sources below.
PIPELINE_DIR = os.path.join(OUTPUT_DIR, "pipeline")


def _swap_webhook_suffix(webhook_url, source_suffix, target_suffix):
    """Swap the trailing webhook path segment when the host stays the same."""
    candidate = (webhook_url or "").strip()
    if not candidate:
        return ""

    parsed = urlparse(candidate)
    path = parsed.path or ""
    if not path.endswith(source_suffix):
        return candidate

    swapped = parsed._replace(path=path[: -len(source_suffix)] + target_suffix)
    return urlunparse(swapped)


def _resolve_classify_webhook_url(override_url=""):
    """Resolve the classifier webhook, deriving it from story config when needed."""
    if override_url:
        return _swap_webhook_suffix(
            override_url,
            "/webhook/story-generator",
            "/webhook/classify-style",
        )

    explicit_classify_url = os.environ.get("N8N_CLASSIFY_WEBHOOK_URL", "").strip()
    if explicit_classify_url:
        return explicit_classify_url

    derived_from_story = _swap_webhook_suffix(
        N8N_STORY_WEBHOOK_URL,
        "/webhook/story-generator",
        "/webhook/classify-style",
    )
    if derived_from_story:
        return derived_from_story

    return (N8N_CLASSIFY_WEBHOOK_URL or "").strip()


def _extract_story_text_from_payload(payload):
    """Best-effort recovery of story text from pipeline/editor/scenes payloads."""
    if not isinstance(payload, dict):
        return ""

    direct = str(payload.get("story_text") or payload.get("text") or "").strip()
    if direct:
        return direct

    scenes = payload.get("scenes") or []
    parts = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        text = (
            scene.get("script")
            or scene.get("segment_words")
            or scene.get("text")
            or scene.get("text_content")
            or ""
        )
        text = str(text).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def _recover_story_from_project(project_id):
    """Rebuild a story response from project artifacts when story.json is missing."""
    safe_id = sanitize_project_id(project_id)
    if not safe_id:
        return None

    candidates = [
        ("pipeline", os.path.join(PIPELINE_DIR, safe_id, "pipeline.json")),
        ("project_wip", os.path.join(PROJECTS_DIR, safe_id, "work@in@progress.json")),
        ("project_initial", os.path.join(PROJECTS_DIR, safe_id, "initial.json")),
        ("scenes", os.path.join(SCENES_DIR, safe_id, "scenes.json")),
    ]

    recovered_from = ""
    raw = {}
    story_text = ""

    for source_name, path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            raw = safe_json_read(path) or {}
        except (json.JSONDecodeError, OSError, FileNotFoundError) as error:
            logger.debug("Could not read fallback story source {}: {}", path, error)
            continue

        payload = raw.get("config") if source_name == "pipeline" and isinstance(raw.get("config"), dict) else raw
        story_text = _extract_story_text_from_payload(payload)
        if story_text:
            recovered_from = source_name
            break

    if not story_text:
        return None

    parsed = parse_story_sections(story_text)
    meta_source = raw.get("config") if isinstance(raw.get("config"), dict) else raw
    metadata = {
        "preset_style": meta_source.get("visual_style") or meta_source.get("style") or "",
        "story_category": meta_source.get("category") or meta_source.get("story_category") or "",
        "story_tone": meta_source.get("story_tone") or "",
        "duration": meta_source.get("duration") or raw.get("total_duration") or 0,
        "timestamp": raw.get("timestamp") or "",
        "recovered_from": recovered_from,
        "recovered": True,
    }

    return {
        "project_id": safe_id,
        "story_text": parsed["story_text"],
        "sections": parsed["sections"],
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@story_bp.route("/api/story/webhook-url")
def get_webhook_url():
    """Return the configured story webhook URL."""
    return jsonify({"url": N8N_STORY_WEBHOOK_URL})


@story_bp.route("/api/story/categories")
def get_categories():
    """Return available story categories."""
    return jsonify(list(dict.fromkeys([*STORY_CATEGORIES, *NICHE_CATEGORIES])))


@story_bp.route("/api/story/random", methods=["POST"])
def random_template_story():
    """Pick a curated sample narration from the `random_template` provider.

    Replaces the frontend-local `RANDOM_STORIES` catalog and anti-repeat rule
    (step 13.1). Body fields are optional:

      - category: template type label (e.g. "Anecdote"); empty = full catalog
      - seed: integer for deterministic tests (skips anti-repeat)

    Returns the same `{text, type, styles}` shape the UI badge/recommended-
    styles row already consumes, plus `word_count` and the catalog `index`.
    """
    body = request.get_json(silent=True) or {}
    if body and not isinstance(body, dict):
        return jsonify({"error": {"code": "INVALID_REQUEST", "message": "Expected JSON object"}}), 400

    seed = body.get("seed")
    if seed is not None and seed != "":
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            return jsonify({
                "error": {"code": "INVALID_REQUEST", "message": "seed must be an integer"}
            }), 400
    else:
        seed = None

    category = (body.get("category") or "").strip() or None

    try:
        from scriptase.providers.hub import hub

        provider = hub.create("script", "random_template")
        if provider is None:
            return jsonify({
                "error": {
                    "code": "PROVIDER_UNAVAILABLE",
                    "message": "The random_template script provider is not registered",
                }
            }), 503
        picked = provider.pick(category=category, seed=seed)
    except Exception:
        logger.exception("random_template pick failed")
        return jsonify({
            "error": {
                "code": "PROVIDER_FAILED",
                "message": "Failed to pick a random template",
            }
        }), 500

    return jsonify({
        "text": picked["text"],
        "type": picked.get("type") or "",
        "styles": list(picked.get("styles") or []),
        "word_count": picked.get("word_count") or len(str(picked["text"]).split()),
        "index": picked.get("index"),
        "seed": picked.get("seed"),
        "provider_id": "random_template",
    })


def _resolve_script_provider_id(requested: str | None) -> tuple[str, object | None, str | None]:
    """Resolve a request/default id to (canonical_id, provider_instance, error).

    Absent/empty values map to the historical AI default (`gemini`). The 12.3
    `builtin` bridge remains a permanent input alias of that provider.
    """
    from scriptase.providers.domains import DOMAINS
    from scriptase.providers.hub import hub
    from scriptase.providers.registry import ProviderConstructionError

    selected = (requested or "").strip() or DOMAINS["script"].default_provider
    try:
        instance = hub.create("script", selected)
    except ProviderConstructionError:
        return selected, None, "PROVIDER_UNAVAILABLE"
    if instance is None:
        return selected, None, "PROVIDER_UNAVAILABLE"
    meta = hub.get("script", selected)
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


@story_bp.route("/api/story/generate", methods=["POST"])
@validate_json(StoryGenerateRequest)
def generate_story(data: StoryGenerateRequest):
    """Generate a story via the selected `script` provider (step 13.3).

    Dispatches through the provider hub so the same node and this legacy route
    share one implementation. The top-level envelope is frozen (contracts.md
    §43); only the `provider` value changes from the hardcoded `"gemini"` to
    the resolved canonical id.

    Accepts JSON body:
      - preset_style, story_category, duration, language, language_level,
        story_tone, idea, webhook_url, project_name_id, niche_preset
      - provider_id: optional script provider (`gemini` default; `builtin`
        alias still accepted; `random_template` for the offline catalog)
    """
    import time

    from scriptase.providers.errors import ProviderError
    from scriptase.engine.adapters.common import provider_run_options

    project_id = sanitize_project_id(
        data.project_name_id or generate_project_id("ps")
    )
    if not project_id:
        project_id = generate_project_id("ps")

    canonical, provider, error = _resolve_script_provider_id(data.provider_id)
    if error or provider is None:
        return jsonify({
            "error": f"No script provider named '{data.provider_id or canonical}' is registered",
        }), 503

    # Same merge the Story Generator adapter uses: request body + portable
    # provider settings (request wins). Saved settings are never rewritten.
    configuration = data.model_dump(exclude_none=True)
    configuration["project_name_id"] = project_id
    configuration["provider_id"] = canonical
    configuration.update(provider_run_options("script", canonical, configuration))

    started = time.perf_counter()
    try:
        result = provider.generate(configuration, project_id=project_id)
    except ProviderError as exc:
        logger.error("Script provider {} failed: {} — {}", canonical, exc.code, exc.message)
        return jsonify({"error": exc.message}), _legacy_provider_http_status(exc.code)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Unexpected error in story generation")
        return jsonify({"error": f"Server error: {exc}"}), 500

    generation_time = round(time.perf_counter() - started, 3)
    meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    sections = result.get("sections") if isinstance(result.get("sections"), dict) else {}
    story_text = result.get("story_text") or ""
    word_count = meta.get("word_count") or len(str(story_text).split())
    estimated_duration = meta.get("estimated_duration")
    if estimated_duration is None:
        estimated_duration = round(word_count / WORDS_PER_SECOND)

    # Frozen legacy envelope (§43). `provider` is the resolved canonical id.
    response = {
        "success": True,
        "project_id": result.get("project_id") or project_id,
        "story_text": story_text,
        "sections": sections,
        "duration": data.duration,
        "estimated_duration": estimated_duration,
        "language": data.language,
        "story_category": data.story_category or meta.get("story_category") or "",
        "story_tone": data.story_tone or meta.get("story_tone") or "",
        "preset_style": data.preset_style or meta.get("preset_style") or "",
        "provider": meta.get("provider") or canonical,
        "word_count": word_count,
        "generation_time": meta.get("generation_time", generation_time),
        "timestamp": meta.get("timestamp") or datetime.now().isoformat(),
        "concept_family": meta.get("concept_family") or "",
    }

    logger.success(
        "Generated story via {} -> {} ({} words, {:.1f}s)",
        response["provider"],
        response["project_id"],
        word_count,
        generation_time,
    )
    return jsonify(response)


@story_bp.route("/api/story/history")
def list_stories():
    """List all generated stories."""
    items = []
    if not os.path.exists(STORIES_DIR):
        return jsonify(items)
    for entry in os.listdir(STORIES_DIR):
        json_path = os.path.join(STORIES_DIR, entry, "story.json")
        if os.path.isfile(json_path):
            try:
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("metadata", {})
                items.append({
                    "project_id": data.get("project_id", entry),
                    "story_category": meta.get("story_category", ""),
                    "language": meta.get("language", ""),
                    "preset_style": meta.get("preset_style", ""),
                    "duration": meta.get("duration", 0),
                    "word_count": meta.get("word_count", 0),
                    "timestamp": meta.get("timestamp", ""),
                    "preview": (data.get("story_text") or "")[:100],
                })
            except (json.JSONDecodeError, OSError) as error:
                logger.debug("Skipping unreadable story entry {}: {}", json_path, error)
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify(items)


@story_bp.route("/api/story/<project_id>")
def get_story(project_id):
    """Get full story data for a project."""
    project_id = sanitize_project_id(project_id)
    if not project_id:
        return jsonify({"error": "Invalid project id"}), 400
    json_path = os.path.join(STORIES_DIR, project_id, "story.json")
    if os.path.isfile(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                return jsonify(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            return jsonify({"error": f"Failed to read story data: {e}"}), 500

    recovered = _recover_story_from_project(project_id)
    if recovered:
        logger.info("Recovered story for {} from {}", project_id, recovered.get("metadata", {}).get("recovered_from", "project files"))
        return jsonify(recovered)

    return jsonify({"error": "Not found"}), 404


@story_bp.route("/api/story/classify-style", methods=["POST"])
def classify_style_route():
    """Classify pasted text into the best-matching visual style template via LLM."""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400

    # Build concise style list for the LLM
    style_options = [
        {"id": t["id"], "name": t["name"], "description": t["description"]}
        for t in SCENE_STYLE_TEMPLATES
    ]
    style_ids = [s["id"] for s in style_options]

    webhook_url = _resolve_classify_webhook_url(body.get("webhook_url", ""))
    if not webhook_url:
        return jsonify({"error": "N8N_CLASSIFY_WEBHOOK_URL not configured"}), 500
    allow_private = os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
    if not is_safe_webhook_url(webhook_url, allow_private=allow_private):
        return jsonify({"error": "Unsafe webhook URL"}), 400

    payload = {
        "text": text[:2000],  # limit to avoid huge payloads
        "styles": style_options,
        "system_prompt": (
            "You are a text style classifier. Given a story/script text and a list of visual styles, "
            "pick the single best-matching style for the text's genre, mood, and theme. "
            "Respond with ONLY a JSON object: {\"style_id\": \"<id>\", \"confidence\": <0.0-1.0>, \"reason\": \"<one sentence>\"} "
            "where style_id is one of the provided style IDs. No markdown, no extra text."
        ),
    }

    try:
        resp = http_requests.post(webhook_url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # n8n respondToWebhook returns an array — unwrap if needed
        if isinstance(data, list) and data:
            data = data[0]

        style_id = data.get("style_id", "")
        confidence = data.get("confidence", 0)
        reason = data.get("reason", "")

        # Validate the returned style_id
        if style_id not in style_ids:
            logger.warning("Classify webhook returned unknown style_id: {}", style_id)
            return jsonify({"error": f"Unknown style returned: {style_id}"}), 502

        return jsonify({
            "style_id": style_id,
            "confidence": confidence,
            "reason": reason,
        })
    except http_requests.Timeout:
        return jsonify({"error": "Classification timed out"}), 504
    except http_requests.RequestException as e:
        logger.error("Classify webhook error: {!r}", e)
        return jsonify({"error": f"Classify webhook error: {e}"}), 502
    except (ValueError, KeyError) as e:
        logger.error("Invalid classify response: {!r}", e)
        return jsonify({"error": "Invalid response from classifier"}), 502
