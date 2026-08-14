"""Animator Module — Grabber-based Video/Image Generation & Management Routes.

Step 14.3 removed every provider-ID branch from this module. The generating
route resolves a provider through the registry and calls `submit`; the
transport, mode/quality/duration handling, Kie batch loop, and Automa
WebSocket push all belong to the provider that declares them. What did not
change is the wire contract: the same fields are accepted, the same envelopes
are returned, and `grabber_job.json` keeps the shape the status route and the
Assets page read.

Selection order: `provider_override` → legacy `provider` → saved selection →
domain default. Legacy spellings (`grok` / `midjourney` / `kie-ai`) resolve
through the registry's aliases. The direct import of
`providers.kie_ai.generate_image` is gone (B8).
"""

import json
import os
import platform
import subprocess
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request
from loguru import logger
from pydantic import ValidationError

from config import ANIMATOR_DIR, PROJECTS_DIR, SCENES_DIR, THUMBNAILS_DIR
from scriptase.shared.ffmpeg_utils import find_ffmpeg
from scriptase.shared.security import is_loopback_remote, sanitize_project_id
from scriptase.providers import settings_manager
from scriptase.providers.boundary import wrap_exception
from scriptase.providers.domains import DOMAINS
from scriptase.providers.errors import ProviderError
from scriptase.providers.hub import hub
from scriptase.providers.invocation import build_invocation
from scriptase.providers.registry import ProviderConstructionError
from scriptase.shared.validation import validate_json
from scriptase.modules.video import jobs
from scriptase.modules.video.organizer import (
    organize_grabber_assets,
    save_base64_assets,
    reconcile_project,
)
from scriptase.modules.video.providers.contract import AnimatorRequest
from .schemas import GrabberStartRequest

animation_bp = Blueprint("animation", __name__)

DOMAIN = "animator"
VIDEO_EXTS = jobs.VIDEO_EXTS

# Compatibility re-exports so external code and tests that imported these from
# the route module keep resolving.
grabber_jobs = jobs.grabber_jobs


def _get_job(project_id):
    return jobs.get(project_id)


def _set_job(project_id, job):
    jobs.set_job(project_id, job)


def _save_job(job):
    if not isinstance(job, dict):
        return
    jobs.save(job.get("project_id", ""), job)


def _job_elapsed_seconds(job, *, include_running=False):
    return jobs.elapsed_seconds(job, include_running=include_running)


def _video_thumbnail(video_path):
    """Extract a co-located thumbnail jpg from a video file."""
    thumb_path = video_path.rsplit(".", 1)[0] + "_thumb.jpg"
    if os.path.isfile(thumb_path):
        return thumb_path
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", video_path, "-map", "0:v:0",
             "-vframes", "1", "-ss", "0.1", "-q:v", "3", thumb_path],
            capture_output=True, timeout=10,
        )
        if os.path.isfile(thumb_path):
            return thumb_path
    except Exception:
        pass
    return None


# Load existing jobs on module import
jobs.load_from_disk()


# ---------------------------------------------------------------------------
# Generic provider dispatch
# ---------------------------------------------------------------------------


def resolve_provider(*candidates):
    """The first candidate the registry resolves, by ID or by alias.

    Order at the call sites is `provider_override` → the legacy `provider`
    field → the saved selection → the domain default. Alias resolution is the
    registry's (`grok`/`midjourney` → `grok_automa`, `kie-ai` → `kie_ai`).
    """
    for candidate in candidates:
        if not candidate:
            continue
        instance = hub.get(DOMAIN, str(candidate))
        if instance is not None:
            return instance
    return None


def _selected_provider() -> str:
    return settings_manager.get_domain_settings(DOMAIN).get("selected_provider") or ""


def _invocation(instance, project_id: str, options: dict):
    """Build the provider invocation for a legacy route call (§30.6)."""
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


def _submit(instance, anim_request: AnimatorRequest, project_id: str, options: dict):
    """Construct and run the provider. Raises `ProviderError` on failure."""
    try:
        provider = hub.create(DOMAIN, instance.id)
    except ProviderConstructionError as exc:
        raise ProviderError(
            "PROVIDER_UNAVAILABLE",
            f"The animator provider '{instance.id}' could not be started",
            domain=DOMAIN,
            provider_id=instance.id,
        ) from exc
    invocation = _invocation(instance, project_id, options)
    try:
        return provider.submit(anim_request, invocation)
    except ProviderError:
        raise
    except BaseException as exc:
        raise wrap_exception(
            exc, domain=DOMAIN, provider_id=instance.id, log=invocation.log
        ) from None


def _request_from(scenes, *, aspect_ratio, mode) -> AnimatorRequest:
    try:
        return AnimatorRequest.from_scenes(
            scenes, aspect_ratio=aspect_ratio, mode=mode
        )
    except ValidationError as exc:
        raise ProviderError(
            "PROVIDER_REQUEST_INVALID",
            "No scenes with a usable prompt were supplied",
            domain=DOMAIN,
        ) from exc


def _http_status(exc: ProviderError) -> int:
    return 400 if exc.code == "PROVIDER_REQUEST_INVALID" else 502


def _consistency_prefix(consistency) -> str:
    if not consistency:
        return ""
    parts = []
    for key in ("character", "setting", "mood"):
        value = consistency.get(key)
        if value:
            parts.append(value)
    if not parts:
        return ""
    return ", ".join(parts) + ". "


def _run_options(data: GrabberStartRequest) -> dict:
    """Per-run values a request may override on the selected provider.

    Flat Grok keys (`grok_mode` / `grok_quality` / `grok_duration` / `auto_type`)
    still win over `provider_options` so an un-migrated client is unaffected
    (§40.2 O1). Top-level Kie fields (`model` / `resolution` / `output_format`)
    lift the same way. Request options always beat stored settings once they
    reach the provider (§40.2 O4).
    """
    options = dict(data.provider_options or {})
    body = request.get_json(silent=True) or {}

    flat_map = (
        ("grok_mode", "mode"),
        ("grok_quality", "quality"),
        ("grok_duration", "duration"),
        ("auto_type", "auto_type"),
    )
    for flat, key in flat_map:
        if flat in body and body[flat] is not None:
            options[key] = body[flat]

    for name in ("model", "resolution", "output_format"):
        value = getattr(data, name, None)
        if value is not None and value != "":
            options.setdefault(name, value)

    if data.aspect_ratio:
        options.setdefault("aspect_ratio", data.aspect_ratio)

    return options


# ---------------------------------------------------------------------------
# Grabber Routes
# ---------------------------------------------------------------------------


@animation_bp.route("/api/animator/grabber/start", methods=["POST"])
@validate_json(GrabberStartRequest)
def grabber_start(data: GrabberStartRequest):
    """Initialize a grabber job — prepares prompts for Automa / cloud providers."""
    project_id = sanitize_project_id(data.project_id)
    if not project_id:
        return jsonify({"error": "Invalid project id"}), 400

    instance = resolve_provider(
        data.provider_override,
        data.provider,
        _selected_provider(),
        DOMAINS[DOMAIN].default_provider,
    )
    if instance is None:
        return jsonify({"error": "No animator provider is registered"}), 503

    prefix = _consistency_prefix(data.consistency)
    scenes = [
        {
            "scene": scene.scene,
            "prompt": prefix + scene.prompt if prefix else scene.prompt,
        }
        for scene in data.scenes
        if scene.prompt
    ]
    options = _run_options(data)
    mode = options.get("mode") or "video"

    try:
        anim_request = _request_from(
            scenes,
            aspect_ratio=data.aspect_ratio or options.get("aspect_ratio") or "9:16",
            mode=mode,
        )
        _submit(instance, anim_request, project_id, options)
    except ProviderError as exc:
        logger.error("[{}] animator submit failed: {}", project_id, exc.code)
        return jsonify({"error": exc.message, "provider": instance.id}), _http_status(exc)

    job = jobs.read(project_id) or {}
    grabber_id = job.get("grabber_id", "")
    scene_count = len(anim_request.scenes)
    logger.info(
        "Grabber job created: {} ({} scenes, provider={})",
        grabber_id, scene_count, instance.id,
    )
    return jsonify({
        "grabber_id": grabber_id,
        "project_id": project_id,
        "scene_count": scene_count,
        "provider": instance.id,
    })


@animation_bp.route("/api/animator/grabber/pending")
def grabber_pending():
    """Return the most recent pending grabber payload for Automa to consume."""
    if not is_loopback_remote(request.remote_addr):
        return jsonify({"error": "Forbidden"}), 403

    latest = None
    for job in grabber_jobs.values():
        if job.get("status") == "waiting":
            if not latest or job.get("created_at", "") > latest.get("created_at", ""):
                latest = job

    if not latest:
        return jsonify({"error": "No pending grabber jobs"}), 404

    jobs.mark_status(latest["project_id"], "grabbing")
    return jsonify(latest["payload"])


def _extension_callback_scope():
    """Identity + aliases for the extension Automa transport (step 14.4).

    Resolved from the extension runtime module and its manifest so this route
    never embeds a concrete provider id (the 14.3 source-level scan).
    """
    from scriptase.modules.video import routes as ext_runtime
    from scriptase.providers.hub import hub as provider_hub

    provider_id = ext_runtime.PROVIDER_ID
    aliases: dict[str, str] = {}
    instance = provider_hub.get("animator", provider_id)
    if instance is not None:
        for alias in instance.manifest.aliases or []:
            aliases[str(alias)] = provider_id
    return provider_id, aliases


@animation_bp.route("/api/animator/grabber/results", methods=["POST"])
def grabber_results():
    """Receive scraped image URLs from Automa and download them.

    Compatibility facade for the existing Automa callback URL (step 14.4).
    Correlation is scoped to the extension provider so a push cannot
    contaminate a direct-API job for the same project.
    """
    if not is_loopback_remote(request.remote_addr):
        return jsonify({"error": "Forbidden"}), 403

    raw = request.get_data(cache=True, as_text=False) or b""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400

    from scriptase.providers.transports.callbacks import (
        MAX_MEDIA_CALLBACK_BYTES,
        default_callback_intake,
    )

    results = data if isinstance(data, list) else [data]
    intake = default_callback_intake()
    provider_id, aliases = _extension_callback_scope()

    for project in results:
        project_id = sanitize_project_id(project.get("projectId", ""))
        if not project_id:
            continue
        job = jobs.read(project_id)
        disposition = intake.accept_legacy_job(
            domain="animator",
            provider_id=provider_id,
            project_id=project_id,
            job=job,
            body=raw,
            max_body_bytes=MAX_MEDIA_CALLBACK_BYTES,
            aliases=aliases,
            source="grabber_results",
        )
        if not disposition.ok:
            logger.warning(
                "Grabber results rejected for {}: {}", project_id, disposition.message
            )
            continue

        jobs.clear_completion(project_id)
        jobs.mark_status(project_id, "downloading")
        scenes = project.get("scenes", [])
        logger.info("Received results for {}: {} scenes", project_id, len(scenes))

        def _download_all(pid, scene_list):
            job_ref = jobs.read(pid) or {}
            for scene_entry in scene_list:
                scene_num = str(scene_entry.get("scene", ""))
                raw_urls = scene_entry.get("url", []) or scene_entry.get("urls", [])
                urls = (
                    jobs.filter_video_urls(raw_urls)
                    if jobs.requires_video(job_ref)
                    else raw_urls
                )
                if not urls:
                    if jobs.requires_video(job_ref) and raw_urls:
                        logger.error(
                            "Scene {} rejected non-video asset URLs for video job: {}",
                            scene_num, raw_urls,
                        )
                        jobs.record_error(pid, scene_num)
                    else:
                        logger.warning("Scene {} has no URLs, skipping", scene_num)
                    continue

                if len(urls) != len(raw_urls):
                    logger.warning(
                        "Scene {} filtered {} non-video URL(s) from grabber payload",
                        scene_num, len(raw_urls) - len(urls),
                    )

                jobs.mark_scene(pid, scene_num, "downloading", urls=urls, local_files=[])
                logger.info("Downloading scene {} ({} URLs)...", scene_num, len(urls))

                try:
                    local_files = organize_grabber_assets(
                        project_id=pid,
                        scene_num=scene_num,
                        urls=urls,
                        assets_dir=ANIMATOR_DIR,
                    )
                    kind = "video" if jobs.requires_video(job_ref) else "image"
                    jobs.record_ready(
                        pid, scene_num, local_files, urls=urls, kind=kind
                    )
                    logger.success(
                        "Scene {} ready: {} files downloaded", scene_num, len(local_files)
                    )
                except Exception as exc:
                    logger.error("Download failed for scene {}: {}", scene_num, exc)
                    jobs.record_error(pid, scene_num)

            if jobs.maybe_finish(pid):
                logger.success("Grabber job complete for {}", pid)

        threading.Thread(
            target=_download_all,
            args=(project_id, scenes),
            daemon=True,
        ).start()

    return jsonify({"status": "downloading", "projects": len(results)})


@animation_bp.route("/api/animator/grabber/upload", methods=["POST"])
def grabber_upload():
    """Receive base64 image/video data from Automa (for CDN URLs that require auth).

    Compatibility facade for the existing Automa callback URL (step 14.4).
    Oversized or cross-provider payloads are rejected without writing assets.
    """
    if not is_loopback_remote(request.remote_addr):
        return jsonify({"error": "Forbidden"}), 403

    raw = request.get_data(cache=True, as_text=False) or b""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400

    project_id = sanitize_project_id(data.get("projectId", ""))
    scenes = data.get("scenes", [])
    if not project_id or not scenes:
        return jsonify({"error": "Missing projectId or scenes"}), 400

    from scriptase.providers.transports.callbacks import (
        MAX_MEDIA_CALLBACK_BYTES,
        REJECTED_OVERSIZED,
        default_callback_intake,
    )

    job = jobs.read(project_id)
    provider_id, aliases = _extension_callback_scope()
    disposition = default_callback_intake().accept_legacy_job(
        domain="animator",
        provider_id=provider_id,
        project_id=project_id,
        job=job,
        body=raw,
        max_body_bytes=MAX_MEDIA_CALLBACK_BYTES,
        aliases=aliases,
        source="grabber_upload",
    )
    if disposition.outcome == REJECTED_OVERSIZED:
        return jsonify({"error": "Payload too large"}), 413
    # Unknown project is still accepted for Automa's "upload then seed" race;
    # only a live job owned by another provider is a hard reject.
    if disposition.outcome == "dropped_mismatch":
        logger.warning(
            "Grabber upload rejected for {}: {}", project_id, disposition.message
        )
        return jsonify({"error": disposition.message or "Callback rejected"}), 409

    if job:
        jobs.clear_completion(project_id)
        jobs.mark_status(project_id, "downloading")

    logger.info("Upload received for {}: {} scenes", project_id, len(scenes))

    def _save_all(pid, scene_list):
        job_ref = jobs.read(pid)
        for scene_entry in scene_list:
            scene_num = str(scene_entry.get("scene", ""))
            raw_images = scene_entry.get("images", [])
            images = (
                jobs.filter_video_images(raw_images)
                if jobs.requires_video(job_ref)
                else raw_images
            )
            if not images:
                if jobs.requires_video(job_ref) and raw_images:
                    logger.error(
                        "Scene {} rejected non-video upload(s) for video job", scene_num
                    )
                    jobs.record_error(pid, scene_num)
                continue

            if len(images) != len(raw_images):
                logger.warning(
                    "Scene {} filtered {} non-video upload(s) from Automa",
                    scene_num, len(raw_images) - len(images),
                )

            jobs.mark_scene(pid, scene_num, "downloading")
            logger.info("Saving scene {} ({} images)...", scene_num, len(images))
            try:
                local_files = save_base64_assets(
                    project_id=pid,
                    scene_num=scene_num,
                    images=images,
                    assets_dir=ANIMATOR_DIR,
                )
                kind = "video" if jobs.requires_video(job_ref) else "image"
                jobs.record_ready(
                    pid, scene_num, local_files,
                    urls=[img.get("source_url", "") for img in images],
                    kind=kind,
                )
                logger.success("Scene {} saved: {} files", scene_num, len(local_files))
            except Exception as exc:
                logger.error("Save failed for scene {}: {}", scene_num, exc)
                jobs.record_error(pid, scene_num)

        if jobs.maybe_finish(pid):
            logger.success("Upload job complete for {}", pid)

    threading.Thread(
        target=_save_all,
        args=(project_id, scenes),
        daemon=True,
    ).start()

    return jsonify({"status": "saving", "scenes": len(scenes)})


@animation_bp.route("/api/animator/grabber/status/<project_id>")
def grabber_status(project_id):
    """Poll grabber job status — frontend calls this every 5s."""
    project_id = sanitize_project_id(project_id)
    if not project_id:
        return jsonify({"error": "Invalid project id"}), 400
    job = jobs.read(project_id)
    if not job:
        return jsonify({"error": "No grabber job found"}), 404

    return jsonify({
        "grabber_id": job["grabber_id"],
        "project_id": project_id,
        "status": job["status"],
        "generation_time": jobs.elapsed_seconds(
            job, include_running=job.get("status") not in ("done", "error")
        ),
        "scene_statuses": job["scene_statuses"],
    })


# ---------------------------------------------------------------------------
# Re-download — retry downloading assets for scenes that failed or are pending
# ---------------------------------------------------------------------------


@animation_bp.route("/api/animator/redownload/<project_id>", methods=["POST"])
def redownload_assets(project_id):
    """Re-attempt downloads for scenes with URLs but no local files."""
    project_id = sanitize_project_id(project_id)
    if not project_id:
        return jsonify({"error": "Invalid project id"}), 400
    job = jobs.read(project_id)
    if not job:
        return jsonify({"error": "No grabber job found"}), 404

    meta_path = os.path.join(ANIMATOR_DIR, project_id, "metadata.json")
    meta = {}
    if os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    scenes_to_retry = []
    for scene_num, ss in job["scene_statuses"].items():
        has_local = ss.get("local_files") and len(ss["local_files"]) > 0
        scene_directory = os.path.join(ANIMATOR_DIR, project_id, str(scene_num))
        has_files = os.path.isdir(scene_directory) and any(
            f.is_file() for f in Path(scene_directory).iterdir()
        )
        if has_local and has_files:
            continue

        urls = ss.get("urls", [])
        if not urls:
            scene_meta = meta.get("scenes", {}).get(str(scene_num), {})
            urls = scene_meta.get("source_urls", [])
        if urls:
            scenes_to_retry.append({"scene": scene_num, "url": urls})

    if not scenes_to_retry:
        return jsonify({
            "status": "nothing_to_retry",
            "message": "All scenes already downloaded",
        })

    jobs.clear_completion(project_id)
    jobs.mark_status(project_id, "downloading")

    def _retry_downloads(pid, scene_list):
        job_ref = jobs.read(pid)
        for entry in scene_list:
            sn = str(entry["scene"])
            urls = entry["url"]
            jobs.mark_scene(pid, sn, "downloading")
            logger.info("Re-downloading scene {} ({} URLs)", sn, len(urls))

            try:
                local_files = organize_grabber_assets(
                    project_id=pid, scene_num=sn,
                    urls=urls, assets_dir=ANIMATOR_DIR,
                )
                kind = "video" if jobs.requires_video(job_ref) else "image"
                jobs.record_ready(pid, sn, local_files, urls=urls, kind=kind)
                logger.success(
                    "Re-download scene {} done: {} files", sn, len(local_files)
                )
            except Exception as exc:
                logger.error("Re-download failed for scene {}: {}", sn, exc)
                jobs.record_error(pid, sn)

        if jobs.maybe_finish(pid):
            logger.success("Redownload complete for {}", pid)

    threading.Thread(
        target=_retry_downloads,
        args=(project_id, scenes_to_retry),
        daemon=True,
    ).start()

    return jsonify({
        "status": "retrying",
        "scenes_retrying": len(scenes_to_retry),
    })


# ---------------------------------------------------------------------------
# History — list all asset projects
# ---------------------------------------------------------------------------


@animation_bp.route("/api/animator/history")
def assets_history():
    """List all asset projects with metadata summary."""
    projects = []
    if not os.path.isdir(ANIMATOR_DIR):
        return jsonify(projects)

    try:
        entries = sorted(
            os.scandir(ANIMATOR_DIR), key=lambda e: e.stat().st_mtime, reverse=True
        )
    except OSError:
        return jsonify(projects)

    from datetime import datetime

    for entry in entries:
        if not entry.is_dir():
            continue

        project_id = entry.name
        project_info = {
            "project_id": project_id,
            "timestamp": datetime.fromtimestamp(entry.stat().st_mtime).isoformat(),
        }

        job_path = os.path.join(entry.path, "grabber_job.json")
        if os.path.isfile(job_path):
            try:
                with open(job_path, "r", encoding="utf-8") as f:
                    job = json.load(f)
                project_info["grabber_id"] = job.get("grabber_id", "")
                project_info["provider"] = job.get("provider", "")
                project_info["status"] = job.get("status", "unknown")
                project_info["created_at"] = job.get("created_at", "")
                project_info["updated_at"] = job.get("updated_at", "")
                project_info["completed_at"] = job.get("completed_at", "")
                project_info["generation_time"] = jobs.elapsed_seconds(
                    job, include_running=job.get("status") not in ("done", "error")
                )
                project_info["scene_count"] = len(job.get("scene_statuses", {}))
                statuses = [
                    s["status"] for s in job.get("scene_statuses", {}).values()
                ]
                project_info["ready_count"] = statuses.count("ready")
                project_info["error_count"] = statuses.count("error")
                project_info["pending_count"] = statuses.count("pending")
            except (json.JSONDecodeError, OSError, TypeError, ValueError, KeyError):
                pass

        meta_path = os.path.join(entry.path, "metadata.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                total_files = sum(
                    len(s.get("local_files", []))
                    for s in meta.get("scenes", {}).values()
                )
                project_info["total_files"] = total_files
            except (json.JSONDecodeError, OSError):
                pass

        total_disk_files = 0
        try:
            for sub in Path(entry.path).iterdir():
                if sub.is_dir() and sub.name not in (".", ".."):
                    try:
                        total_disk_files += sum(
                            1 for f in sub.iterdir() if f.is_file()
                        )
                    except OSError:
                        pass
        except OSError:
            pass
        project_info["disk_files"] = total_disk_files

        scenes_json = os.path.join(SCENES_DIR, project_id, "scenes.json")
        if os.path.isfile(scenes_json):
            try:
                with open(scenes_json, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                project_info["style"] = sdata.get("style", "")
            except Exception:
                pass

        project_info["preview"] = None
        thumb_base = os.path.join(THUMBNAILS_DIR, project_id)
        editor_cover = os.path.join(thumb_base, "editor", "cover.jpg")
        assets_thumb_0 = os.path.join(thumb_base, "assets", "0.jpg")
        if os.path.isfile(editor_cover):
            project_info["preview"] = f"/api/thumbnails/{project_id}/editor/cover.jpg"
        elif os.path.isfile(assets_thumb_0):
            project_info["preview"] = f"/api/thumbnails/{project_id}/assets/0.jpg"
        else:
            try:
                scene_dirs = sorted(os.listdir(entry.path))
            except OSError:
                scene_dirs = []
            for scene_num in scene_dirs:
                scene_path = os.path.join(entry.path, scene_num)
                if not os.path.isdir(scene_path) or scene_num in (".", ".."):
                    continue
                try:
                    scene_files = sorted(os.listdir(scene_path))
                except OSError:
                    continue
                for fname in scene_files:
                    fpath = os.path.join(scene_path, fname)
                    if not os.path.isfile(fpath):
                        continue
                    lower = fname.lower()
                    if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                        project_info["preview"] = (
                            f"/output/animator/{project_id}/{scene_num}/{fname}"
                        )
                        break
                    if lower.endswith(VIDEO_EXTS):
                        thumb = _video_thumbnail(fpath)
                        if thumb:
                            thumb_name = os.path.basename(thumb)
                            project_info["preview"] = (
                                f"/output/animator/{project_id}/{scene_num}/{thumb_name}"
                            )
                        break
                if project_info["preview"]:
                    break

        proj_dir = os.path.join(PROJECTS_DIR, project_id)
        project_info["has_build"] = os.path.isfile(
            os.path.join(proj_dir, "initial.json")
        )
        projects.append(project_info)

    return jsonify(projects)


@animation_bp.route("/api/animator/reconcile/<project_id>", methods=["POST"])
def reconcile_assets(project_id):
    """Force reconcile disk files with metadata.json + grabber_job.json."""
    project_id = sanitize_project_id(project_id)
    if not project_id:
        return jsonify({"error": "Invalid project id"}), 400
    project_directory = os.path.join(ANIMATOR_DIR, project_id)
    if not os.path.isdir(project_directory):
        return jsonify({"error": "Project not found"}), 404
    updated = reconcile_project(ANIMATOR_DIR, project_id)
    if updated > 0:
        job_path = os.path.join(project_directory, "grabber_job.json")
        if os.path.isfile(job_path):
            with open(job_path, "r", encoding="utf-8") as f:
                jobs.set_job(project_id, json.load(f))
    return jsonify({"updated": updated})


@animation_bp.route("/api/animator/project/<project_id>")
def get_asset_project(project_id):
    """Get full asset project details — all scenes with local files."""
    project_id = sanitize_project_id(project_id)
    if not project_id:
        return jsonify({"error": "Invalid project id"}), 400
    project_directory = os.path.join(ANIMATOR_DIR, project_id)
    if not os.path.isdir(project_directory):
        return jsonify({"error": "Project not found"}), 404

    reconcile_project(ANIMATOR_DIR, project_id)

    result = {
        "project_id": project_id,
        "scenes": {},
    }

    meta_path = os.path.join(project_directory, "metadata.json")
    if os.path.isfile(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        result["scenes"] = meta.get("scenes", {})

    job = jobs.read(project_id)
    if job:
        result["grabber_id"] = job.get("grabber_id", "")
        result["provider"] = job.get("provider", "")
        result["status"] = job.get("status", "unknown")
        result["created_at"] = job.get("created_at", "")
        result["updated_at"] = job.get("updated_at", "")
        result["completed_at"] = job.get("completed_at", "")
        result["generation_time"] = jobs.elapsed_seconds(
            job, include_running=job.get("status") not in ("done", "error")
        )
        result["scene_statuses"] = job.get("scene_statuses", {})
        result["prompts"] = {
            str(s["scene"]): s["prompt"]
            for s in job.get("payload", {}).get("scenes", [])
        }

    for scene_num_dir in sorted(os.listdir(project_directory)):
        scene_path = os.path.join(project_directory, scene_num_dir)
        if not os.path.isdir(scene_path):
            continue
        try:
            int(scene_num_dir)
        except ValueError:
            continue

        files_on_disk = []
        for fname in sorted(os.listdir(scene_path)):
            fpath = os.path.join(scene_path, fname)
            if os.path.isfile(fpath):
                files_on_disk.append({
                    "url": f"/output/animator/{project_id}/{scene_num_dir}/{fname}",
                    "filename": fname,
                    "size": os.path.getsize(fpath),
                })

        if scene_num_dir not in result["scenes"]:
            result["scenes"][scene_num_dir] = {}
        result["scenes"][scene_num_dir]["files_on_disk"] = files_on_disk

    return jsonify(result)


# ---------------------------------------------------------------------------
# Asset serving
# ---------------------------------------------------------------------------


@animation_bp.route(
    "/api/animator/open-folder/<project_id>/<int:scene_index>", methods=["POST"]
)
def open_asset_scene_folder(project_id, scene_index):
    """Open a specific scene's asset folder in the OS file explorer."""
    if not is_loopback_remote(request.remote_addr):
        return jsonify({"error": "Forbidden"}), 403

    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))
    folder = os.path.join(ANIMATOR_DIR, safe_id, str(scene_index))
    if not os.path.isdir(folder):
        return jsonify({"error": "Folder not found"}), 404
    folder = os.path.abspath(folder)
    try:
        if platform.system() == "Windows":
            subprocess.run(["explorer", folder], check=False)
        elif platform.system() == "Darwin":
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error("Failed to open asset folder: {}", e)
        return jsonify({"error": str(e)}), 500


@animation_bp.route("/api/animator/thumbnails/<project_id>", methods=["POST"])
def generate_video_thumbnails(project_id):
    """Generate _thumb.jpg for all video files in a project that lack one."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))
    project_directory = os.path.join(ANIMATOR_DIR, safe_id)
    if not os.path.isdir(project_directory):
        return jsonify({"error": "Project not found"}), 404

    generated = []
    for scene_dir in sorted(os.listdir(project_directory)):
        scene_path = os.path.join(project_directory, scene_dir)
        if not os.path.isdir(scene_path):
            continue
        for fname in os.listdir(scene_path):
            lower = fname.lower()
            if not lower.endswith(VIDEO_EXTS):
                continue
            fpath = os.path.join(scene_path, fname)
            thumb = _video_thumbnail(fpath)
            if thumb:
                thumb_name = os.path.basename(thumb)
                generated.append({
                    "scene": scene_dir,
                    "thumb_url": f"/output/animator/{safe_id}/{scene_dir}/{thumb_name}",
                    "video_url": f"/output/animator/{safe_id}/{scene_dir}/{fname}",
                })

    return jsonify({"project_id": safe_id, "thumbnails": generated})


# Static file serving for /output/animator/ is handled by routes.py (serve_animator_file)
