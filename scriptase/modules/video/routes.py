"""Animator Module — REST surface for the Chrome-extension animation bridge.

Provides:
  POST /api/animator/submit                 — submit animation jobs
  POST /api/animator/submit-storyboard      — submit using storyboard stills
  GET  /api/animator/status/<project_id>    — poll job status
  GET  /api/animator/videos/<project_id>    — list generated videos
  GET  /api/animator/videos/<project_id>/<f> — serve individual video
  GET  /output/animator/<path:filepath>     — serve animator output files

The WebSocket endpoint, the extension message handlers, and the in-memory job
map live in ``ws_runtime`` (step 0.3). This module is transport only: it
imports the runtime, never the other way round.
"""

import os
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, send_from_directory
from loguru import logger

import base64 as b64_mod

from config import OUTPUT_DIR, STORYBOARD_DIR, SCENES_DIR, ANIMATOR_DIR
from scriptase.shared.io_utils import safe_json_read
from scriptase.shared.security import sanitize_project_id
from scriptase.modules.video.ws_runtime import (
    _jobs,
    _jobs_lock,
    _save_job_state,
    _send_to_extension,
    _ws_clients,
)

animator_bp = Blueprint("animator", __name__)


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@animator_bp.route("/api/animator/submit", methods=["POST"])
def submit_jobs():
    """Submit animation jobs — sends image+prompt pairs to the extension."""
    data = request.get_json(silent=True) or {}
    project_id = sanitize_project_id(data.get("project_id", ""))
    scenes = data.get("scenes", [])
    mode = data.get("mode", "imageToVideo")
    duration = data.get("duration", "6s")
    aspect_ratio = data.get("aspect_ratio", "9:16")

    if not project_id or not scenes:
        return jsonify({"error": "project_id and scenes are required"}), 400

    # Check extension is connected
    with _ws_lock:
        if not _ws_clients:
            return jsonify({"error": "No Chrome extension connected"}), 503

    job_id = str(uuid.uuid4())[:8]

    # Build job
    job = {
        "job_id": job_id,
        "project_id": project_id,
        "status": "running",
        "total": len(scenes),
        "ready": 0,
        "errors": 0,
        "mode": mode,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "scenes": {},
    }

    for i, scene in enumerate(scenes):
        key = str(i)
        job["scenes"][key] = {
            "status": "pending",
            "prompt": scene.get("prompt", ""),
            "image_path": scene.get("image_path", ""),
            "image_base64": scene.get("image_base64", ""),
            "video_url": None,
            "local_path": None,
            "error": None,
            "percentage": 0,
        }

    with _jobs_lock:
        _jobs[job_id] = job

    _save_job_state(job)

    # Send jobs to extension
    payloads = []
    for i, scene in enumerate(scenes):
        payload = {
            "type": "ANIMATE_JOB",
            "jobId": job_id,
            "projectId": project_id,
            "sceneIndex": i,
            "prompt": scene.get("prompt", ""),
            "mode": mode,
            "duration": duration,
            "aspectRatio": aspect_ratio,
        }

        # Resolve image: prefer base64, fall back to reading file
        if scene.get("image_base64"):
            payload["image"] = scene["image_base64"]
        elif scene.get("image_path"):
            img_path = scene["image_path"]
            if os.path.isfile(img_path):
                import base64
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                ext = os.path.splitext(img_path)[1].lstrip(".")
                mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
                payload["image"] = f"data:image/{mime};base64,{b64}"

        payloads.append(payload)

    # Send all jobs to extension
    for payload in payloads:
        _send_to_extension(payload)

    logger.info("Submitted {} animator jobs for project {}", len(scenes), project_id)
    return jsonify({"job_id": job_id, "total": len(scenes), "status": "running"})


@animator_bp.route("/api/animator/submit-storyboard", methods=["POST"])
def submit_storyboard():
    """Submit animation jobs using storyboard images as references.

    Reads storyboard images from output/storyboard/{project_id}/{scene}/image.*
    and scene prompts from output/scenes/{project_id}/scenes.json.
    Sends each scene as imageToVideo to the Chrome extension.
    """
    data = request.get_json(silent=True) or {}
    project_id = sanitize_project_id(data.get("project_id", ""))
    mode = data.get("mode", "imageToVideo")
    duration = data.get("duration", "6s")
    aspect_ratio = data.get("aspect_ratio", "9:16")

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    with _ws_lock:
        if not _ws_clients:
            return jsonify({"error": "No Chrome extension connected"}), 503

    # Load scene prompts
    scenes_json = os.path.join(SCENES_DIR, project_id, "scenes.json")
    if not os.path.isfile(scenes_json):
        return jsonify({"error": f"No scenes.json found for {project_id}"}), 404

    scenes_data = safe_json_read(scenes_json)
    scene_list = scenes_data.get("scenes", [])
    if not scene_list:
        return jsonify({"error": "No scenes in scenes.json"}), 400

    # Find storyboard images
    sb_dir = os.path.join(STORYBOARD_DIR, project_id)
    image_exts = (".jpeg", ".jpg", ".png", ".webp")

    scenes_payload = []
    for scene in scene_list:
        idx = scene.get("index", 0)
        prompt = scene.get("image_prompt", "")
        scene_img_dir = os.path.join(sb_dir, str(idx))

        # Find image file
        image_path = None
        if os.path.isdir(scene_img_dir):
            for fname in os.listdir(scene_img_dir):
                if fname.startswith("image") and fname.lower().endswith(image_exts) and "_v" not in fname:
                    image_path = os.path.join(scene_img_dir, fname)
                    break

        if not image_path or not os.path.isfile(image_path):
            logger.warning("[{}] No storyboard image for scene {}, skipping", project_id, idx)
            continue

        # Read and encode image
        with open(image_path, "rb") as f:
            raw = f.read()
        ext = os.path.splitext(image_path)[1].lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
        image_b64 = f"data:image/{mime};base64,{b64_mod.b64encode(raw).decode()}"

        scenes_payload.append({
            "prompt": prompt,
            "image_base64": image_b64,
            "scene_index": idx,
        })

    if not scenes_payload:
        return jsonify({"error": "No storyboard images found for any scene"}), 404

    # Build job
    job_id = str(uuid.uuid4())[:8]
    job = {
        "job_id": job_id,
        "project_id": project_id,
        "status": "running",
        "total": len(scenes_payload),
        "ready": 0,
        "errors": 0,
        "mode": mode,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "scenes": {},
    }

    for i, sp in enumerate(scenes_payload):
        key = str(sp["scene_index"])
        job["scenes"][key] = {
            "status": "pending",
            "prompt": sp["prompt"],
            "image_path": "",
            "image_base64": "(storyboard)",
            "video_url": None,
            "local_path": None,
            "error": None,
            "percentage": 0,
        }

    with _jobs_lock:
        _jobs[job_id] = job
    _save_job_state(job)

    # Send jobs to extension
    for sp in scenes_payload:
        _send_to_extension({
            "type": "ANIMATE_JOB",
            "jobId": job_id,
            "projectId": project_id,
            "sceneIndex": sp["scene_index"],
            "prompt": sp["prompt"],
            "image": sp["image_base64"],
            "mode": mode,
            "duration": duration,
            "aspectRatio": aspect_ratio,
        })

    logger.info("Submitted {} storyboard animator jobs for {}", len(scenes_payload), project_id)
    return jsonify({"job_id": job_id, "total": len(scenes_payload), "status": "running"})


@animator_bp.route("/api/animator/status/<project_id>")
def animator_status(project_id):
    """Get animator job status for a project."""
    project_id = sanitize_project_id(project_id)

    # Check in-memory first
    with _jobs_lock:
        for job in _jobs.values():
            if job["project_id"] == project_id:
                return jsonify(job)

    # Fall back to disk
    state_path = os.path.join(ANIMATOR_DIR, project_id, "animator.json")
    if os.path.isfile(state_path):
        return jsonify(safe_json_read(state_path))

    return jsonify({"error": "Not found"}), 404


@animator_bp.route("/api/animator/videos/<project_id>")
def list_videos(project_id):
    """List generated videos for a project."""
    project_id = sanitize_project_id(project_id)
    project_dir = os.path.join(ANIMATOR_DIR, project_id)
    if not os.path.isdir(project_dir):
        return jsonify({"videos": []})

    videos = []
    for scene_name in sorted(os.listdir(project_dir)):
        scene_path = os.path.join(project_dir, scene_name)
        if os.path.isdir(scene_path):
            for f in sorted(os.listdir(scene_path)):
                if f.endswith((".mp4", ".webm")):
                    videos.append(f"{scene_name}/{f}")
    return jsonify({"videos": videos, "project_id": project_id})


@animator_bp.route("/api/animator/videos/<project_id>/<scene>/<filename>")
def serve_video(project_id, scene, filename):
    """Serve an individual generated video."""
    project_id = sanitize_project_id(project_id)
    scene_dir = os.path.join(ANIMATOR_DIR, project_id, scene)
    return send_from_directory(scene_dir, filename)


@animator_bp.route("/output/animator/<path:filepath>")
def serve_animator_file(filepath):
    """Serve animator output files (videos) for the editor/export pipeline."""
    resp = send_from_directory(ANIMATOR_DIR, filepath)
    resp.headers.setdefault("Accept-Ranges", "bytes")
    return resp
