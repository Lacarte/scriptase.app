"""Storyboard module — reference image generation, dispatched generically.

Provides:
  POST /api/storyboard/generate                    — start storyboard generation
  POST /api/storyboard/grab                        — generate a single scene
  GET  /api/storyboard/status/<project_id>          — poll per-scene status
  GET  /api/storyboard/images/<project_id>          — list generated images
  GET  /api/storyboard/images/<project_id>/<file>   — serve an individual image
  POST /api/storyboard/remove-watermarks/<pid>      — re-run the watermark sweep
  GET  /api/storyboard/image-models                 — image-model catalog
  GET  /api/storyboard/webhook-url                  — configured webhook URL

Step 14.2 removed every provider-ID branch from this module. Both generating
routes resolve a provider through the registry and call `submit`; the transport,
the aspect-ratio handling, the prompt prefix, and the watermark pass all belong
to the provider that declares them. What did not change is the wire contract:
the same fields are accepted, the same 202 envelopes are returned, and
`storyboard.json` keeps the shape the status route and the Storyboard page read.

The one repaired defect is the selection itself. `provider` was a read-only
property on the request model, so the value old callers posted was discarded and
only `provider_override` could choose a provider. Both are honoured now, and
legacy spellings resolve through the registry's aliases.
"""

import os
import re
import threading

from flask import Blueprint, jsonify, send_from_directory
from loguru import logger
from pydantic import ValidationError

from config import N8N_STORYBOARD_WEBHOOK_URL, STORYBOARD_DIR
from scriptase.shared.security import sanitize_project_id
from scriptase.providers import settings_manager
from scriptase.providers.boundary import wrap_exception
from scriptase.providers.domains import DOMAINS
from scriptase.providers.errors import ProviderError
from scriptase.providers.hub import hub
from scriptase.providers.invocation import build_invocation
from scriptase.providers.registry import ProviderConstructionError
from scriptase.shared.validation import validate_json
from scriptase.modules.image import jobs
from scriptase.modules.image.providers.contract import StoryboardRequest
from .schemas import StoryboardGenerateRequest, StoryboardGrabOneRequest

storyboard_bp = Blueprint("storyboard", __name__)

DOMAIN = "storyboard"


# ---------------------------------------------------------------------------
# Generic provider dispatch
# ---------------------------------------------------------------------------


def resolve_provider(*candidates):
    """The first candidate the registry resolves, by ID or by alias.

    Order at the call sites is `provider_override` → the legacy `provider`
    field → the saved selection → the domain default. Alias resolution is the
    registry's (`gemini` → `gemini_ws`, `webhook` → `wavespeed_webhook`,
    `direct` → `wavespeed_direct`), so no translation table lives here.
    """
    for candidate in candidates:
        if not candidate:
            continue
        instance = hub.get(DOMAIN, str(candidate))
        if instance is not None:
            return instance
    return None


def _selected_provider() -> str:
    _iid, type_id, _settings = settings_manager.resolve_instance(DOMAIN)
    return type_id or ""


def _invocation(instance, project_id: str, options: dict):
    """Build the provider invocation for a legacy route call (§30.6).

    `context=None`: there is no scheduler here, so cancellation and progress are
    the no-op collaborators, which is exactly what these fire-and-poll routes
    have always had.
    """
    saved = settings_manager.get_provider_settings(DOMAIN, instance.id)
    return build_invocation(
        None,
        domain=DOMAIN,
        provider_id=instance.id,
        project_id=project_id,
        output_dir=jobs.project_dir(project_id),
        settings=instance.resolve_settings(saved),
        options={key: value for key, value in options.items() if value is not None},
        selection_reason="request",
    )


def _submit(instance, request: StoryboardRequest, project_id: str, options: dict):
    """Construct and run the provider. Raises `ProviderError` on failure.

    Everything a provider can throw is mapped onto the shared catalog, so a
    misbehaving package answers 502 with a safe message rather than a 500 with
    a traceback (§34.4).
    """
    try:
        provider = hub.create(DOMAIN, instance.id)
    except ProviderConstructionError as exc:
        raise ProviderError(
            "PROVIDER_UNAVAILABLE",
            f"The storyboard provider '{instance.id}' could not be started",
            domain=DOMAIN,
            provider_id=instance.id,
        ) from exc
    invocation = _invocation(instance, project_id, options)
    try:
        return provider.submit(request, invocation)
    except ProviderError:
        raise
    except BaseException as exc:
        raise wrap_exception(
            exc, domain=DOMAIN, provider_id=instance.id, log=invocation.log
        ) from None


def _request_from(scenes, *, aspect_ratio, style) -> StoryboardRequest:
    """Build the §32.4 request, or fail as a bad request rather than a 500."""
    try:
        return StoryboardRequest.from_scenes(
            scenes, aspect_ratio=aspect_ratio, style=style
        )
    except ValidationError as exc:
        raise ProviderError(
            "PROVIDER_REQUEST_INVALID",
            "No scenes with a usable prompt were supplied",
            domain=DOMAIN,
        ) from exc


def _http_status(exc: ProviderError) -> int:
    """A caller's mistake is 4xx; anything upstream is 502."""
    return 400 if exc.code == "PROVIDER_REQUEST_INVALID" else 502


def _run_options(data) -> dict:
    """Per-run values a request may override on the selected provider."""
    options = dict(getattr(data, "provider_options", None) or {})
    for name in ("webhook_url", "image_model", "auto_type"):
        value = getattr(data, name, None)
        if value is not None and value != "":
            options.setdefault(name, value)
    return options


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@storyboard_bp.route("/api/storyboard/image-models")
def list_image_models():
    """Return the image-models.json config for frontend use."""
    from .wavespeed import _load_image_models

    return jsonify(_load_image_models())


@storyboard_bp.route("/api/storyboard/generate", methods=["POST"])
@validate_json(StoryboardGenerateRequest)
def generate(data: StoryboardGenerateRequest):
    """Start storyboard image generation for a project."""
    project_id = sanitize_project_id(data.project_id)
    instance = resolve_provider(
        data.provider_override,
        data.provider,
        _selected_provider(),
        DOMAINS[DOMAIN].default_provider,
    )
    if instance is None:
        return jsonify({"error": "No storyboard provider is registered"}), 503

    try:
        request = _request_from(
            [{"index": scene.scene, "prompt": scene.prompt} for scene in data.scenes],
            aspect_ratio=data.aspect_ratio,
            style=data.style,
        )
        _submit(instance, request, project_id, _run_options(data))
    except ProviderError as exc:
        logger.error("[{}] storyboard submit failed: {}", project_id, exc.code)
        return jsonify({"error": exc.message, "provider": instance.id}), _http_status(exc)

    logger.info(
        "[{}] Storyboard generation started via {} — {} scenes",
        project_id, instance.id, request.unit_count,
    )
    return jsonify({
        "status": "running",
        "project_id": project_id,
        "total": request.unit_count,
        "provider": instance.id,
    }), 202


@storyboard_bp.route("/api/storyboard/grab", methods=["POST"])
@validate_json(StoryboardGrabOneRequest)
def grab_one(data: StoryboardGrabOneRequest):
    """Generate a single scene's storyboard image.

    The same generic dispatch as the bulk route with a one-scene request, so a
    provider needs no separate single-image entry point. The manifest is merged
    rather than replaced: regenerating one frame must not discard the rest.
    """
    project_id = sanitize_project_id(data.project_id)
    instance = resolve_provider(
        data.provider_override,
        data.provider,
        _selected_provider(),
        DOMAINS[DOMAIN].default_provider,
    )
    if instance is None:
        return jsonify({"error": "No storyboard provider is registered"}), 503

    existing = jobs.read(project_id)
    try:
        request = _request_from(
            [{"index": data.scene, "prompt": data.prompt}],
            aspect_ratio=data.aspect_ratio,
            style=data.style,
        )
        _submit(instance, request, project_id, _run_options(data))
    except ProviderError as exc:
        logger.error("[{}] storyboard grab failed: {}", project_id, exc.code)
        return jsonify({"error": exc.message, "provider": instance.id}), _http_status(exc)

    jobs.merge_prior_scenes(project_id, (existing or {}).get("scene_statuses"), data.scene)

    logger.info("[{}] Storyboard grab started via {} — scene {}",
                project_id, instance.id, data.scene)
    return jsonify({
        "status": "generating",
        "project_id": project_id,
        "scene": data.scene,
        "provider": instance.id,
    }), 202


@storyboard_bp.route("/api/storyboard/status/<project_id>")
def status(project_id):
    """Poll storyboard generation status."""
    project_id = sanitize_project_id(project_id)

    job = jobs.read(project_id)
    if not job:
        return jsonify({"error": "No storyboard job found for this project"}), 404

    scene_statuses = job.get("scene_statuses", {})
    total = job.get("total", 0) or sum(1 for key in scene_statuses if key != "-1")
    ready = sum(
        1 for key, entry in scene_statuses.items()
        if key != "-1" and entry.get("status") in ("ready", "done")
    )
    errors = sum(
        1 for key, entry in scene_statuses.items()
        if key != "-1" and entry.get("status") == "error"
    )

    done = ready >= total and total > 0

    return jsonify({
        "project_id": project_id,
        "status": "done" if done else job.get("status", "unknown"),
        "total": total,
        "ready": ready,
        "errors": errors,
        "scene_statuses": scene_statuses,
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
    })


@storyboard_bp.route("/api/storyboard/images/<project_id>")
def list_images(project_id):
    """List generated storyboard images for a project."""
    project_id = sanitize_project_id(project_id)
    project_dir = jobs.project_dir(project_id)

    if not os.path.isdir(project_dir):
        return jsonify({"error": "No storyboard found for this project"}), 404

    images = []
    for entry in sorted(os.scandir(project_dir), key=lambda e: e.name):
        # Current structure: {project_id}/{scene}/image.jpeg + image_v1.jpeg …
        if entry.is_dir() and entry.name.isdigit():
            scene_num = int(entry.name)
            thumb_file = jobs.thumbnail_path(project_id, scene_num)
            thumb_url = (
                f"/api/thumbnails/{project_id}/storyboard/{entry.name}.jpg"
                if os.path.isfile(thumb_file) else None
            )
            versions = []
            for file in sorted(os.scandir(entry.path), key=lambda e: e.name):
                if not file.is_file() or file.name == "thumb.jpg":
                    continue
                if not file.name.lower().endswith(jobs.IMAGE_EXTENSIONS):
                    continue
                match = re.match(r"image_v(\d+)", file.name)
                version = int(match.group(1)) if match else None
                versions.append({
                    "filename": file.name,
                    "path": f"/output/storyboard/{project_id}/{entry.name}/{file.name}",
                    "version": version,
                    "is_current": version is None and file.name.startswith("image."),
                    "size_bytes": file.stat().st_size,
                })
            # Sort: versions ascending, current frame last (newest).
            versions.sort(key=lambda v: v["version"] if v["version"] is not None else 9999)
            images.append({
                "scene": scene_num,
                "path": next(
                    (v["path"] for v in versions if v["is_current"]),
                    versions[-1]["path"] if versions else None,
                ),
                "thumb_path": thumb_url,
                "versions": versions,
                "version_count": len(versions),
            })
        # Legacy flat structure: {project_id}/{scene}.jpg
        elif entry.is_file() and entry.name.lower().endswith(jobs.IMAGE_EXTENSIONS):
            base = os.path.splitext(entry.name)[0]
            path = f"/output/storyboard/{project_id}/{entry.name}"
            images.append({
                "scene": int(base) if base.isdigit() else None,
                "path": path,
                "thumb_path": None,
                "versions": [{
                    "filename": entry.name, "path": path, "version": None,
                    "is_current": True, "size_bytes": entry.stat().st_size,
                }],
                "version_count": 1,
            })

    images.sort(key=lambda item: item.get("scene") if item.get("scene") is not None else 0)
    return jsonify({"project_id": project_id, "images": images, "count": len(images)})


@storyboard_bp.route("/api/storyboard/images/<project_id>/<path:filename>")
def serve_image(project_id, filename):
    """Serve an individual storyboard image file."""
    project_id = sanitize_project_id(project_id)
    project_dir = jobs.project_dir(project_id)

    if not os.path.isfile(os.path.join(project_dir, filename)):
        return jsonify({"error": "Image not found"}), 404

    return send_from_directory(project_dir, filename)


@storyboard_bp.route("/api/storyboard/remove-watermarks/<project_id>", methods=["POST"])
def remove_watermarks(project_id):
    """Sweep a project's frames and remove any watermarks."""
    project_id = sanitize_project_id(project_id)
    threading.Thread(
        target=jobs.sweep_watermarks, args=(project_id,),
        name=f"storyboard-sweep-{project_id}", daemon=True,
    ).start()
    return jsonify({"status": "started", "project_id": project_id}), 202


@storyboard_bp.route("/api/storyboard/webhook-url")
def get_webhook_url():
    """Return the configured storyboard webhook URL (image-generator)."""
    return jsonify({"url": N8N_STORYBOARD_WEBHOOK_URL})


@storyboard_bp.route("/output/storyboard/<path:filename>")
def serve_output(filename):
    """Serve storyboard files via /output/storyboard/ (consistent with other modules)."""
    return send_from_directory(STORYBOARD_DIR, filename)
