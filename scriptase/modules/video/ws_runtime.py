"""Animator extension runtime — WebSocket bridge to the Chrome extension.

The STS backend sends image+prompt pairs to the Chrome extension via WebSocket.
The extension automates Grok's image-to-video generation and returns video URLs.

Provides:
  WS   /ws/animator-grok-video-grabber      — WebSocket endpoint (via flask-sock)

Step 14.4 moves the client pool, pending queue, prune, and broadcast onto the
shared ``ExtensionWebSocketHub``. The frozen route path is unchanged; domain
message handlers stay here.

This module is transport-free in the Flask sense: it owns no blueprint and must
never import ``scriptase.modules.video.routes``. The REST surface imports *from*
here, not the other way round (step 0.3).
"""

import json
import os
import threading
import time
from datetime import datetime

import requests as http_requests
from loguru import logger

from config import ANIMATOR_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.shared.security import sanitize_project_id
from scriptase.providers.transports.callbacks import default_callback_intake
from scriptase.providers.transports.extension import ExtensionWebSocketHub

PROVIDER_ID = "grok_automa"
DOMAIN = "animator"
WS_ROUTE = "/ws/animator-grok-video-grabber"

# ---------------------------------------------------------------------------
# WebSocket state (shared hub + legacy in-memory job map for older WS frames)
# ---------------------------------------------------------------------------
_jobs = {}
_jobs_lock = threading.Lock()


def _count_pending_jobs():
    with _jobs_lock:
        count = 0
        for job in _jobs.values():
            for s in job.get("scenes", {}).values():
                if s.get("status") in ("pending", "processing"):
                    count += 1
        return count


def _on_connect(ws):
    pending = _count_pending_jobs()
    try:
        ws.send(json.dumps({
            "type": "CONNECTED",
            "message": "STS Animator WebSocket connected",
            "pendingJobs": pending,
        }))
        logger.info("Grok WS → CONNECTED (pendingJobs: {})", pending)
    except Exception as e:
        logger.warning("Grok WS CONNECTED send failed: {}", e)


def _handle_ws_message(msg, ws=None):
    """Handle incoming domain messages from the Chrome extension."""
    msg_type = msg.get("type")

    if msg_type == "ANIMATE_RESULT":
        pid = msg.get("projectId", "?")
        scene = msg.get("sceneIndex", "?")
        ok = msg.get("success", False)
        logger.info("Grok ← ANIMATE_RESULT {} scene {} success={}", pid, scene, ok)
        _handle_result(msg)
    elif msg_type == "ANIMATE_PROGRESS":
        _handle_progress(msg)
    elif msg_type == "EXTENSION_READY":
        source = msg.get("source", "unknown")
        logger.success(
            "Grok extension HANDSHAKE ← source={}, clients={}, pending_grabber={}",
            source, hub.client_count(), hub.pending_count() > 0,
        )
        if ws is not None:
            hub.flush_pending(ws)
        elif hub.clients:
            hub.flush_pending(hub.clients[-1])
    elif msg_type == "JOB_RECEIVED":
        pid = msg.get("projectId", "?")
        scenes_count = msg.get("scenes", 0)
        had_pending = hub.drop_pending()
        logger.success(
            "Grok ← JOB_RECEIVED {} ({} scenes, cleared_pending={})",
            pid, scenes_count, bool(had_pending),
        )
    elif msg_type == "JOB_COMPLETE":
        pid = msg.get("projectId", "?")
        typed = msg.get("typed", 0)
        total = msg.get("total", 0)
        failed = msg.get("failed", 0)
        hub.drop_pending()
        logger.success("Grok ← JOB_COMPLETE {} ({}/{} typed, {} failed)", pid, typed, total, failed)
        if _accept_project(pid, source="JOB_COMPLETE"):
            _finalize_animator_job(pid, failed)
    elif msg_type == "ASSET_UPLOAD":
        pid = msg.get("projectId", "?")
        scene = msg.get("scene", "?")
        count = len(msg.get("images", []))
        logger.info("Grok ← ASSET_UPLOAD {} scene {} ({} files)", pid, scene, count)
        _handle_asset_upload_ws(msg)
    elif msg_type == "ASSET_UPLOADED":
        logger.info("Grok ← ASSET_UPLOADED {} scene {}", msg.get("projectId", "?"), msg.get("scene", "?"))
        _handle_asset_uploaded(msg)
    elif msg_type == "ASSET_RESULT":
        pid = msg.get("projectId", "?")
        scene = msg.get("scene", "?")
        urls = len(msg.get("urls", []))
        logger.info("Grok ← ASSET_RESULT {} scene {} ({} URLs)", pid, scene, urls)
        _handle_asset_result(msg)
    elif msg_type == "STATUS_UPDATE":
        pid = msg.get("projectId", "?")
        scene = msg.get("scene", "?")
        status = msg.get("status", "?")
        logger.info("Grok ← STATUS_UPDATE {} scene {} → {}", pid, scene, status)
    elif msg_type == "PONG":
        pass  # heartbeat response
    elif msg_type == "RATE_LIMITED":
        wait_ms = msg.get("waitMs", 0)
        retry_count = msg.get("retryCount", 0)
        mins = int(wait_ms / 60000)
        if retry_count:
            logger.warning("Grok rate limited — retry #{}, waiting {}m", retry_count, mins)
        else:
            logger.warning("Grok rate limited — waiting {}m", mins)
    elif msg_type == "RATE_LIMIT_CLEARED":
        logger.success("Grok rate limit cleared, resuming")
    else:
        logger.warning("Unknown animator WS message type: {}", msg_type)


hub = ExtensionWebSocketHub(
    "grok",
    WS_ROUTE,
    pending_mode="single",
    on_message=_handle_ws_message,
    on_connect=_on_connect,
)

# Compatibility aliases — health checks and tests still patch/read these names.
_ws_clients = hub.clients


def _accept_project(project_id: str, *, source: str) -> bool:
    """Refuse pushes that target a job owned by another animator provider (e.g. kie_ai)."""
    if not project_id or project_id == "?":
        return False
    from scriptase.modules.video import jobs as animator_jobs

    job = animator_jobs.read(project_id)
    disposition = default_callback_intake().accept_legacy_job(
        domain=DOMAIN,
        provider_id=PROVIDER_ID,
        project_id=project_id,
        job=job,
        source=source,
        aliases={"grok": PROVIDER_ID, "midjourney": PROVIDER_ID},
    )
    if not disposition.ok:
        logger.warning(
            "Grok {} dropped for {}: {}", source, project_id, disposition.message
        )
        return False
    return True


def is_extension_connected():
    """Check if at least one Grok extension client is connected."""
    return hub.is_connected()


def activate_tab():
    """Send ACTIVATE_TAB to all connected Grok extension clients."""
    return hub.broadcast({"type": "ACTIVATE_TAB"}, label="ACTIVATE_TAB", prune=True)


def focus_studio_tab():
    """Send FOCUS_STUDIO_TAB to all connected Grok extension clients."""
    return hub.broadcast({"type": "FOCUS_STUDIO_TAB"}, label="FOCUS_STUDIO_TAB")


def _send_to_extension(msg):
    """Send a message to the first connected extension client."""
    with hub._clients_lock:
        if not hub.clients:
            return False
        return hub.send(hub.clients[0], msg)


def add_job(project_id: str, scenes: list, grok_mode: str = "video", quality: str = "480p", duration: str = "6s"):
    """Add an animator job for the Grok extension.

    Args:
        project_id: Project identifier
        scenes: List of scene dicts with 'index', 'prompt'
        grok_mode: "video" or "image"
        quality: Video quality
        duration: Video duration
    """
    msg = {
        "type": "GRABBER_START",
        "projectId": project_id,
        "scenes": scenes,
        "grokMode": grok_mode,
        "grokQuality": quality,
        "grokDuration": duration,
    }
    queue_grabber_start(msg)
    logger.info("Added job to Grok animator queue: project={}, scenes={}", project_id, len(scenes))
    return msg


def queue_grabber_start(msg):
    """Queue a GRABBER_START message. Sends immediately AND keeps queued for late-connecting clients."""
    return hub.queue(msg, label="GRABBER_START")


def init_animator_ws(sock):
    """Register the /ws/animator-grok-video-grabber WebSocket route on the flask-sock instance."""
    hub.register(sock)


def _handle_result(msg):
    """Process a completed animation result from the extension."""
    job_id = msg.get("jobId")
    scene_key = str(msg.get("sceneIndex", ""))
    success = msg.get("success", False)
    video_url = msg.get("videoUrl")
    error = msg.get("error")

    if not job_id:
        return

    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return

        scene = job["scenes"].get(scene_key)
        if not scene:
            return

        if success and video_url:
            scene["status"] = "downloading"
            scene["video_url"] = video_url

            # Download in background
            project_id = job["project_id"]
            threading.Thread(
                target=_download_video,
                args=(project_id, job_id, scene_key, video_url),
                daemon=True,
            ).start()
        elif success and not video_url:
            scene["status"] = "ready"
        else:
            scene["status"] = "error"
            scene["error"] = error or "Unknown error"

        _update_job_status(job)
        _save_job_state(job)


def _handle_progress(msg):
    """Update progress for an in-flight animation."""
    job_id = msg.get("jobId")
    scene_key = str(msg.get("sceneIndex", ""))
    percentage = msg.get("percentage", 0)

    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        scene = job["scenes"].get(scene_key)
        if scene:
            scene["status"] = "processing"
            scene["percentage"] = percentage


def _finalize_animator_job(project_id, failed_count):
    """Sweep non-ready scenes to 'error' and mark the job done on JOB_COMPLETE."""
    from scriptase.modules.video.jobs import _get_job, _save_job, _mark_job_done
    job = _get_job(project_id)
    if not job:
        return
    swept = 0
    for key, scene in job.get("scene_statuses", {}).items():
        if scene.get("status") not in ("ready", "error", "downloaded"):
            scene["status"] = "error"
            scene["error"] = "Generation failed (reported by extension)"
            swept += 1
    _mark_job_done(job)
    _save_job(job)
    if swept:
        logger.warning("JOB_COMPLETE {}: swept {} non-ready scene(s) to error", project_id, swept)


def _handle_asset_upload_ws(msg):
    """Handle base64 asset data sent via WebSocket — save to disk.

    Message format:
        { type: "ASSET_UPLOAD", projectId, scene, images: [{data, source_url, ext, filename}] }
    """
    project_id = sanitize_project_id(msg.get("projectId", ""))
    scene_num = msg.get("scene")
    images = msg.get("images", [])

    if not project_id or scene_num is None or not images:
        logger.warning("ASSET_UPLOAD missing required fields")
        return
    if not _accept_project(project_id, source="ASSET_UPLOAD"):
        return

    scene_num = str(scene_num)
    total_kb = sum(len(img.get("data", "")) * 3 // 4 // 1024 for img in images)
    logger.info("ASSET_UPLOAD via WS: {} scene {} — {} file(s), ~{} KB",
                project_id, scene_num, len(images), total_kb)

    from config import ANIMATOR_DIR
    from scriptase.modules.video.organizer import save_base64_assets

    def _save():
        try:
            local_files = save_base64_assets(
                project_id=project_id,
                scene_num=scene_num,
                images=images,
                assets_dir=ANIMATOR_DIR,
            )
            logger.success("ASSET_UPLOAD: {} scene {} — {} files saved", project_id, scene_num, len(local_files))

            # Update grabber job status
            from scriptase.modules.video.jobs import _get_job, _save_job, _mark_job_done
            job = _get_job(project_id)
            if job and scene_num in job.get("scene_statuses", {}):
                job["scene_statuses"][scene_num]["status"] = "ready"
                job["scene_statuses"][scene_num]["local_files"] = local_files
                job["scene_statuses"][scene_num]["urls"] = [
                    img.get("source_url", "") for img in images
                ]
                job["updated_at"] = datetime.now().isoformat()
                all_done = all(
                    s.get("status") in ("ready", "error", "downloaded")
                    for s in job["scene_statuses"].values()
                )
                if all_done:
                    _mark_job_done(job)
                _save_job(job)
        except Exception as e:
            logger.error("ASSET_UPLOAD save failed for {} scene {}: {}", project_id, scene_num, e)

    threading.Thread(target=_save, daemon=True).start()


def _handle_asset_uploaded(msg):
    """Handle notification that Automa uploaded assets for a scene."""
    project_id = msg.get("projectId")
    scene = msg.get("scene")
    count = msg.get("count", 0)
    logger.info("Asset upload notification: {} scene {} ({} files)", project_id, scene, count)


def _handle_asset_result(msg):
    """Handle video/image URL results from Automa — download to assets folder.

    Message format:
        { type: "ASSET_RESULT", projectId, scene, urls: ["https://..."] }
    """
    project_id = sanitize_project_id(msg.get("projectId", ""))
    scene_num = msg.get("scene")
    urls = msg.get("urls", [])

    if not project_id or scene_num is None or not urls:
        logger.warning("ASSET_RESULT missing required fields: {}", msg)
        return

    scene_num = str(scene_num)

    # Grok CDN (assets.grok.com) requires auth — server-side download returns 403.
    # Log warning and skip; Automa should use ASSET_UPLOAD with base64 data instead.
    grok_urls = [u for u in urls if "assets.grok.com" in u]
    if grok_urls:
        logger.warning(
            "ASSET_RESULT: {} scene {} — {} Grok CDN URL(s) cannot be downloaded "
            "server-side (403). Client should use ASSET_UPLOAD with base64 data.",
            project_id, scene_num, len(grok_urls),
        )
        # Filter out Grok URLs, only download non-Grok URLs
        urls = [u for u in urls if "assets.grok.com" not in u]
        if not urls:
            return

    logger.info("ASSET_RESULT: downloading {} URL(s) for {} scene {}", len(urls), project_id, scene_num)

    from config import ANIMATOR_DIR
    from scriptase.modules.video.organizer import organize_grabber_assets

    def _download():
        try:
            local_files = organize_grabber_assets(
                project_id=project_id,
                scene_num=scene_num,
                urls=urls,
                assets_dir=ANIMATOR_DIR,
            )
            logger.success("ASSET_RESULT: {} scene {} — {} files saved", project_id, scene_num, len(local_files))

            # Update grabber job status if one exists
            from scriptase.modules.video.jobs import _get_job, _save_job, _mark_job_done
            job = _get_job(project_id)
            if job and scene_num in job.get("scene_statuses", {}):
                job["scene_statuses"][scene_num]["status"] = "ready"
                job["scene_statuses"][scene_num]["urls"] = urls
                job["scene_statuses"][scene_num]["local_files"] = local_files
                job["updated_at"] = datetime.now().isoformat()
                # Check if all scenes are now done
                all_done = all(
                    s.get("status") in ("ready", "error", "downloaded")
                    for s in job["scene_statuses"].values()
                )
                if all_done:
                    _mark_job_done(job)
                _save_job(job)
        except Exception as e:
            logger.error("ASSET_RESULT download failed for {} scene {}: {}", project_id, scene_num, e)

    threading.Thread(target=_download, daemon=True).start()


def _download_video(project_id, job_id, scene_key, video_url):
    """Download a video from the given URL to output/animator/{project_id}/{scene_key}/."""
    scene_dir = os.path.join(ANIMATOR_DIR, project_id, scene_key)
    os.makedirs(scene_dir, exist_ok=True)

    ext = "mp4"
    if ".webm" in video_url:
        ext = "webm"
    filename = f"{scene_key}.{ext}"
    filepath = os.path.join(scene_dir, filename)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    for attempt in range(3):
        try:
            resp = http_requests.get(video_url, headers=headers, timeout=120, stream=True)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            with _jobs_lock:
                job = _jobs.get(job_id)
                if job and scene_key in job["scenes"]:
                    job["scenes"][scene_key]["status"] = "ready"
                    job["scenes"][scene_key]["local_path"] = f"{scene_key}/{filename}"
                    _update_job_status(job)
                    _save_job_state(job)

            logger.info("Downloaded animator video: {}/{}", project_id, filename)
            return

        except Exception as e:
            logger.warning("Download attempt {}/3 failed for scene {}: {}", attempt + 1, scene_key, e)
            if attempt < 2:
                time.sleep(2 ** attempt)

    # All retries failed
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job and scene_key in job["scenes"]:
            job["scenes"][scene_key]["status"] = "error"
            job["scenes"][scene_key]["error"] = f"Download failed after 3 attempts"
            _update_job_status(job)
            _save_job_state(job)


def _update_job_status(job):
    """Recompute aggregate job status from scene statuses."""
    scenes = job["scenes"]
    statuses = [s["status"] for s in scenes.values()]

    if all(s == "ready" for s in statuses):
        job["status"] = "done"
        job["completed_at"] = datetime.now().isoformat()
    elif any(s in ("pending", "processing", "downloading") for s in statuses):
        job["status"] = "running"
    elif all(s in ("ready", "error") for s in statuses):
        job["status"] = "done"
        job["completed_at"] = datetime.now().isoformat()

    job["ready"] = sum(1 for s in statuses if s == "ready")
    job["errors"] = sum(1 for s in statuses if s == "error")


def _save_job_state(job):
    """Persist job state to disk."""
    project_dir = os.path.join(ANIMATOR_DIR, job["project_id"])
    os.makedirs(project_dir, exist_ok=True)
    safe_json_write(os.path.join(project_dir, "animator.json"), job)
