"""Gemini image generator — WebSocket bridge for the storyboard extension.

Provides:
  WS  /ws/storyboard-gemini-image-grabber  — endpoint for the Gemini extension

Protocol (Extension → Server):
  { type: "EXTENSION_READY", source: "sts-gemini-ext" }
  { type: "IMAGE_UPLOAD", projectId, scene, image: { data, source_url } }
  { type: "STATUS_UPDATE", projectId, scene, status }
  { type: "JOB_RECEIVED", projectId, scenes }
  { type: "JOB_COMPLETE", projectId }

Protocol (Server → Extension):
  { type: "IMAGE_JOB", projectId, scenes: [...], aspectRatio, autoType }
  { type: "PONG" }

Step 14.2 reduced this module to transport + domain handlers. Step 14.4 moves
the client pool, pending queue, prune, and broadcast onto the shared
``ExtensionWebSocketHub``; this file keeps only Gemini message handling and the
``auto_animate`` hand-off. The frozen route path is unchanged.
"""

from __future__ import annotations

import base64
import os
import threading

from loguru import logger

from scriptase.providers.transports.callbacks import (
    default_callback_intake,
    job_matches_provider,
)
from scriptase.providers.transports.extension import ExtensionWebSocketHub
from scriptase.modules.image import jobs

PROVIDER_ID = "gemini_ws"
DOMAIN = "storyboard"
WS_ROUTE = "/ws/storyboard-gemini-image-grabber"


def _handle_message(msg, ws):
    """Process a domain message from the Gemini extension."""
    msg_type = msg.get("type", "")

    if msg_type == "EXTENSION_READY":
        logger.success(
            "Gemini extension HANDSHAKE ← source={}, pending_jobs={}",
            msg.get("source", "unknown"), hub.pending_count(),
        )
        hub.flush_pending(ws)

    elif msg_type == "IMAGE_UPLOAD":
        logger.info(
            "Gemini ← IMAGE_UPLOAD {} scene {}",
            msg.get("projectId", "?"), msg.get("scene", "?"),
        )
        _handle_image_upload(msg)

    elif msg_type == "STATUS_UPDATE":
        project_id = msg.get("projectId", "")
        scene = msg.get("scene")
        status = msg.get("status", "")
        logger.info("Gemini ← STATUS_UPDATE {} scene {} → {}", project_id or "?", scene, status)
        if project_id and _accept_project(project_id, source="STATUS_UPDATE"):
            jobs.mark_scene(project_id, scene, status)

    elif msg_type == "JOB_RECEIVED":
        project_id = msg.get("projectId", "")
        removed = hub.drop_pending(project_id)
        logger.success(
            "Gemini ← JOB_RECEIVED {} ({} scenes, cleared {} pending)",
            project_id, msg.get("scenes", 0), removed,
        )

    elif msg_type == "JOB_COMPLETE":
        project_id = msg.get("projectId", "")
        hub.drop_pending(project_id)
        logger.success("Gemini ← JOB_COMPLETE {}", project_id)
        if _accept_project(project_id, source="JOB_COMPLETE"):
            _mark_job_done(project_id)

    # PING / DIAGNOSE* are handled by the shared hub.


hub = ExtensionWebSocketHub(
    "gemini",
    WS_ROUTE,
    pending_mode="list",
    on_message=_handle_message,
)

# Compatibility aliases — health checks and tests still patch/read these names.
_ws_clients = hub.clients


def register_runtime(app, sock=None):
    """Register the /ws/storyboard-gemini-image-grabber WebSocket route."""
    hub.register(sock)


def _capability(name: str, default: bool = False) -> bool:
    """Read one declared capability of this provider (§20.4).

    Falls back to `default` when the registry has not been discovered, which is
    the case in unit tests that exercise the transport in isolation.
    """
    from scriptase.providers.hub import hub as provider_hub

    instance = provider_hub.get("storyboard", PROVIDER_ID)
    if instance is None:
        return default
    return bool(instance.capabilities.get(name, default))


def is_extension_connected():
    """Check if at least one Gemini extension client is connected."""
    return hub.is_connected()


def queue_image_job(msg):
    """Queue an IMAGE_JOB message. Sends immediately to connected clients."""
    return hub.queue(msg, label="IMAGE_JOB")


def _accept_project(project_id: str, *, source: str) -> bool:
    """Refuse pushes that target a job owned by another storyboard provider."""
    if not project_id:
        return False
    job = jobs.read(project_id)
    disposition = default_callback_intake().accept_legacy_job(
        domain=DOMAIN,
        provider_id=PROVIDER_ID,
        project_id=project_id,
        job=job,
        source=source,
    )
    if not disposition.ok:
        logger.warning(
            "Gemini {} dropped for {}: {}", source, project_id, disposition.message
        )
        return False
    return True


def _handle_image_upload(msg):
    """Save a base64 frame from the extension through the shared job store."""
    project_id = msg.get("projectId", "")
    scene_num = msg.get("scene")
    image = msg.get("image", {})
    image_data = image.get("data", "") if isinstance(image, dict) else ""

    if not project_id or scene_num is None or not image_data:
        logger.warning("IMAGE_UPLOAD missing fields")
        return

    if not _accept_project(project_id, source="IMAGE_UPLOAD"):
        return

    # Bound the base64 payload so a runaway extension cannot fill the disk.
    from scriptase.providers.transports.callbacks import (
        MAX_MEDIA_CALLBACK_BYTES,
        measure_body,
    )

    if measure_body(image_data) > MAX_MEDIA_CALLBACK_BYTES:
        logger.warning(
            "IMAGE_UPLOAD rejected oversized frame for {} scene {}",
            project_id, scene_num,
        )
        jobs.record_error(project_id, scene_num, "The uploaded frame was too large")
        return

    logger.info(
        "IMAGE_UPLOAD: {} scene {} (~{} KB)",
        project_id, scene_num, len(image_data) * 3 // 4 // 1024,
    )

    try:
        if "," in image_data:
            header, encoded = image_data.split(",", 1)
            ext = jobs.extension_for(header, default=".png")
            if "jpeg" in header or "jpg" in header:
                ext = ".jpeg"
            elif "webp" in header:
                ext = ".webp"
            elif "png" in header:
                ext = ".png"
        else:
            encoded, ext = image_data, ".jpeg"

        destination = jobs.prepare_scene_file(project_id, scene_num, ext)
        with open(destination, "wb") as handle:
            handle.write(base64.b64decode(encoded))
        logger.success("Saved: {} ({:.0f} KB)", destination, os.path.getsize(destination) / 1024)
    except (OSError, ValueError) as exc:
        logger.error("IMAGE_UPLOAD save failed: {}", exc)
        jobs.record_error(project_id, scene_num, "The uploaded frame could not be saved")
        return

    # Watermark removal and thumbnail generation are both applied by the job
    # store, so an extension frame carries the same per-scene metadata as a
    # downloaded one. Off the WebSocket thread: the remover loads a CV stack
    # and the extension is waiting to send the next frame.
    threading.Thread(
        target=jobs.record_ready,
        args=(project_id, scene_num, destination),
        kwargs={"remove_watermark": _capability("watermark_removal", True)},
        name=f"storyboard-frame-{project_id}-{scene_num}",
        daemon=True,
    ).start()


def activate_tab():
    """Send ACTIVATE_TAB to all connected Gemini extension clients."""
    return hub.broadcast({"type": "ACTIVATE_TAB"}, label="ACTIVATE_TAB", prune=True)


def focus_studio_tab():
    """Send FOCUS_STUDIO_TAB to all connected Gemini extension clients."""
    return hub.broadcast({"type": "FOCUS_STUDIO_TAB"}, label="FOCUS_STUDIO_TAB")


def _mark_job_done(project_id):
    """Close the job, then run the provider's declared completion behaviour."""
    jobs.mark_done(project_id)

    if _capability("watermark_removal", True):
        _sweep_watermarks(project_id)
    if _capability("auto_animate", True):
        threading.Thread(
            target=_push_to_grok, args=(project_id,),
            name=f"storyboard-handoff-{project_id}", daemon=True,
        ).start()


def _sweep_watermarks(project_id):
    """Re-run watermark removal across a project's frames."""
    return jobs.sweep_watermarks(project_id)


def _push_to_grok(project_id):
    """Hand the finished frames and their prompts to the animator extension.

    Declared as the `auto_animate` capability. The transport is the shared
    animator ``ExtensionWebSocketHub``; the hand-off payload is domain data.
    """
    from scriptase.shared.io_utils import safe_json_read

    prompts_path = jobs.scene_prompts_path(project_id)
    if not os.path.isfile(prompts_path):
        logger.warning("No scene prompts for {} — cannot hand off to the animator", project_id)
        return

    try:
        scenes = safe_json_read(prompts_path)
    except (OSError, ValueError) as exc:
        logger.error("Failed to read scene prompts: {}", exc)
        return
    if not isinstance(scenes, list):
        return

    handoff = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        index = scene.get("scene")
        prompt = scene.get("prompt", "")
        if index is None or not prompt:
            continue
        entry = {"scene": index, "prompt": prompt}
        frame = jobs.current_image(project_id, index)
        if frame:
            encoded = _encode_frame(frame)
            if encoded:
                entry["image"] = encoded
        handoff.append(entry)

    if not handoff:
        logger.warning("No scenes to hand off to the animator for {}", project_id)
        return

    try:
        from scriptase.modules.video.routes import activate_tab as animator_activate, queue_grabber_start

        animator_activate()
        queue_grabber_start({
            "type": "GRABBER_START",
            "projectId": project_id,
            "scenes": handoff,
            "aspectRatio": "9:16",
            "grokMode": "video",
            "grokDuration": "6s",
            "autoType": True,
        })
        logger.success("Handed {} scenes to the animator for {}", len(handoff), project_id)
    except Exception as exc:
        logger.error("Animator hand-off failed: {}", exc)


def _encode_frame(path: str) -> str | None:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
    return f"data:image/{mime};base64,{base64.b64encode(raw).decode()}"


# Re-export for rare callers that checked provider ownership directly.
__all__ = [
    "PROVIDER_ID",
    "WS_ROUTE",
    "activate_tab",
    "focus_studio_tab",
    "hub",
    "is_extension_connected",
    "job_matches_provider",
    "queue_image_job",
    "register_runtime",
]
