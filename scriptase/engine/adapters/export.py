"""Workflow adapter for the Export node (`export.video`).

Step 0.3 retires the absolute `path` key this adapter used to emit on the video
port (§36 L7), matching what step 15.3 already did for `tts.generate`. The
rendered file is addressed the way every other managed artifact is: `filename`
plus the relative `artifact_refs` entry `with_artifacts` derives. `VideoProcessor`
still receives an absolute path — it writes the file — but that path does not
leave the adapter.
"""

from __future__ import annotations

import os
import uuid

from config import EXPORT_DIR
from scriptase.modules.compose.video_processor import VideoProcessor
from scriptase.modules.compose.export_service import _normalize_export_audio, _normalize_export_captions, _extract_music_track, _extract_sfx_track
from .common import AdapterError, inherited_config, outputs, project_id, with_artifacts

PROFILES = {
    "yt_shorts": (1080, 1920, "9:16"), "tiktok": (1080, 1920, "9:16"),
    "reels": (1080, 1920, "9:16"), "yt_landscape": (1920, 1080, "16:9"),
    "square": (1080, 1080, "1:1"),
}


def _logo_config(settings):
    if not settings.get("logo_enabled"):
        return None
    logo = settings.get("logo") or {}
    path = logo.get("url") or logo.get("ref") or logo.get("path")
    if not path:
        raise AdapterError("LOGO_REQUIRED", "Logo is enabled but no logo asset is configured")
    path = str(path).replace("\\", "/")
    if path.startswith("branding/"):
        path = "/output/" + path
    elif not path.startswith("/output/branding/"):
        raise AdapterError("ARTIFACT_UNMANAGED", "Logo must be a managed branding asset")
    return {
        "enabled": True, "path": path,
        "position": settings.get("logo_position", "top_right"),
        "size": settings.get("logo_size", 10),
        "opacity": settings.get("logo_opacity", 0.9),
        "margin": settings.get("logo_margin", 32),
    }


def _payload(project, config, settings):
    profile = config.get("profile", "yt_shorts")
    width, height, ratio = PROFILES.get(profile, PROFILES["yt_shorts"])
    assembled = project.get("assembled_data", project)
    scenes = []
    for scene in assembled.get("scenes", []):
        media_path = scene.get("mediaUrl") or scene.get("image_url") or ""
        scenes.append({
            "id": scene.get("id", scene.get("scene_id", 0)),
            "duration": scene.get("duration", 3),
            "media": {"path": media_path, "type": "video" if scene.get("isVideo") or media_path.lower().endswith((".mp4", ".webm", ".mov")) else "image"},
            "effect": scene.get("effect", {"type": "none"}),
            "transition": scene.get("transition", {"type": "none", "duration": 0}),
        })
    if not scenes:
        raise AdapterError("EDITOR_PROJECT_INVALID", "Editor project has no scenes to export")
    return {
        "project_id": assembled.get("project_id"), "scenes": scenes,
        "output": {"resolution": {"width": width, "height": height}, "fps": 30, "quality": "high"},
        "timeline": {"total_duration": assembled.get("total_duration") or sum(float(s["duration"]) for s in scenes)},
        "captions": _normalize_export_captions(assembled) if config.get("captions", True) else None,
        "audio": _normalize_export_audio(assembled), "bgMusic": _extract_music_track(assembled),
        "sfx": _extract_sfx_track(assembled),
        "grain_overlay": {"enabled": True, "opacity": 0.16} if config.get("grain", False) else None,
        "logo_overlay": _logo_config(settings), "profile": profile, "aspect_ratio": ratio,
    }


def video(inputs, config, context):
    pid = project_id(context, inputs)
    settings = inputs.get("settings") if isinstance(inputs.get("settings"), dict) else {}
    merged = inherited_config(config, settings)
    payload = _payload(inputs["project"], merged, settings)
    payload["project_id"] = pid
    filename = f"{pid}_{uuid.uuid4().hex[:8]}.mp4"
    path = os.path.join(EXPORT_DIR, filename)
    progress = context.get("progress") if isinstance(context, dict) else getattr(context, "progress", None)
    VideoProcessor(payload, progress_callback=(lambda percent, message: progress(message) if progress else None)).process(path)
    result = with_artifacts({"project_id": pid, "filename": filename, "profile": payload["profile"], "resolution": f"{payload['output']['resolution']['width']}x{payload['output']['resolution']['height']}"}, path)
    return outputs(video=result)
