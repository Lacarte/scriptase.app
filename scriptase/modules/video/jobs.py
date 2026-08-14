"""The animator job manifest — one owner for `grabber_job.json` (step 14.3).

Before this step the route, the Kie AI background thread, the Automa upload
handlers, and the workflow adapter each wrote the same file with different
rules, and Kie options were merged with inverted precedence. Providers now own
only remote/local generation mechanics and call `record_ready` / `record_error`
when a unit settles; the manifest shape, thumbnails, and status counters are
applied here, identically for every provider.

`grabber_job.json` stays authoritative and public (§17.1): the legacy status
route, the pipeline poller, and the Assets page all keep reading the same
document. While the process lives the in-memory store is preferred (Automa
callbacks land on the request thread while a worker may be writing), and the
file is the restart path — the same dual-write the route has always had.
"""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import datetime
from typing import Any, Mapping

from loguru import logger

from config import ANIMATOR_DIR, THUMBNAILS_DIR
from scriptase.shared.ffmpeg_utils import find_ffmpeg
from scriptase.shared.io_utils import JobStore, now_iso, safe_json_read, safe_json_write
from scriptase.providers.jobs import (
    RUNNING,
    JobStatus,
    status_from_scenes,
)

MANIFEST_NAME = "grabber_job.json"
VIDEO_EXTS = (".mp4", ".webm", ".mov")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# In-memory store is authoritative while the process lives; the file is the
# restart path. Both writers always go through this module.
_store = JobStore()
_lock = threading.RLock()

# Compatibility alias so `from scriptase.modules.video.animation_routes import grabber_jobs`
# and any external reader that already holds a reference keep resolving.
grabber_jobs = _store


# -- paths -------------------------------------------------------------------


def project_dir(project_id: str) -> str:
    return os.path.join(ANIMATOR_DIR, project_id)


def manifest_path(project_id: str) -> str:
    return os.path.join(project_dir(project_id), MANIFEST_NAME)


def scene_dir(project_id: str, index: Any) -> str:
    return os.path.join(project_dir(project_id), str(index))


def local_path(project_id: str, index: Any, filename: str) -> str:
    """The browser-facing `/output/...` path the manifest has always stored."""
    return f"/output/animator/{project_id}/{index}/{filename}"


def thumbnail_path(project_id: str, index: Any) -> str:
    return os.path.join(THUMBNAILS_DIR, project_id, "animator", f"{index}.jpg")


# -- store access ------------------------------------------------------------


def get(project_id: str) -> dict | None:
    """In-memory job, if the process still holds it."""
    job = _store.get(project_id)
    return dict(job) if isinstance(job, Mapping) else None


def set_job(project_id: str, job: Mapping[str, Any]) -> None:
    """Publish a job into the in-memory store (does not touch disk)."""
    _store.set(project_id, dict(job))


def read(project_id: str) -> dict | None:
    """Current job: memory first, then the on-disk manifest."""
    live = get(project_id)
    if live is not None:
        return live
    path = manifest_path(project_id)
    if not os.path.isfile(path):
        return None
    try:
        data = safe_json_read(path)
    except (OSError, ValueError):
        return None
    if not isinstance(data, Mapping):
        return None
    job = dict(data)
    # Rehydrate so subsequent writers and the status route see one copy.
    _store.set(project_id, job)
    return job


def save(project_id: str, job: Mapping[str, Any] | None = None) -> None:
    """Persist the job to disk and keep the in-memory copy in sync. Never raises."""
    with _lock:
        current = dict(job) if job is not None else get(project_id)
        if current is None:
            return
        current["updated_at"] = now_iso()
        try:
            safe_json_write(manifest_path(project_id), current, indent=2)
        except OSError as exc:
            logger.error("[animator] could not save {}: {}", MANIFEST_NAME, exc)
        _store.set(project_id, current)


# Compatibility wrappers — these lived in `animation_routes` until step 0.3,
# where the extension WebSocket runtime imported them out of a blueprint
# module. The names are kept exactly so existing callers keep resolving.


def _get_job(project_id):
    return get(project_id)


def _save_job(job):
    if not isinstance(job, dict):
        return
    save(job.get("project_id", ""), job)


# -- lifecycle ---------------------------------------------------------------


def seed(
    project_id: str,
    request,
    *,
    provider_id: str = "",
    payload: Mapping[str, Any] | None = None,
    grabber_id: str | None = None,
    status: str = "waiting",
    preserve_prior: bool = True,
) -> dict:
    """Create the manifest for a new job and publish it.

    `provider_id` is recorded so a reader can tell which provider produced an
    asset; it is metadata only and never drives dispatch. When `preserve_prior`
    is true (the default), already-ready scenes that are *not* being resent keep
    their status — the grabber start route has always done this so a partial
    re-run does not wipe completed work.
    """
    scene_list = list(request.legacy_scenes()) if hasattr(request, "legacy_scenes") else []
    prior = read(project_id) if preserve_prior else None
    scene_statuses: dict[str, Any] = {}
    if prior and isinstance(prior.get("scene_statuses"), Mapping):
        scene_statuses = {
            str(key): dict(value) if isinstance(value, Mapping) else value
            for key, value in prior["scene_statuses"].items()
        }
    for scene in scene_list:
        key = str(scene.get("scene", scene.get("index", 0)))
        scene_statuses[key] = {
            "status": "pending",
            "urls": [],
            "local_files": [],
        }

    body = dict(payload or {})
    if "projectId" not in body:
        body["projectId"] = project_id
    if "scenes" not in body:
        body["scenes"] = scene_list
    if "aspect_ratio" not in body:
        body["aspect_ratio"] = getattr(request, "aspect_ratio", "9:16")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job = {
        "grabber_id": grabber_id or f"grab_{stamp}_{project_id}",
        "project_id": project_id,
        "provider": provider_id,
        "arguments": "",
        "payload": body,
        "scene_statuses": scene_statuses,
        "status": status,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "total": len(scene_list),
        "ready": 0,
        "errors": 0,
    }
    # Drop stale completion fields so a re-run is not reported as already done.
    job.pop("completed_at", None)
    job.pop("generation_time", None)
    save(project_id, job)
    return job


def status(
    project_id: str, job_id: str | None = None, *, unit_count: int = 0
) -> JobStatus:
    """The `JobStatus` every animator provider's `poll` returns (§33.2)."""
    from scriptase.providers.media_jobs import (
        JOB_DONE_STATES,
        settled_state,
        units_from_legacy_scenes,
    )

    identity = job_id or project_id
    job = read(project_id)
    if job is None:
        return JobStatus(job_id=identity, state=RUNNING, total=unit_count)

    raw = job.get("scene_statuses")
    scenes = raw if isinstance(raw, Mapping) else {}
    derived = status_from_scenes(identity, scenes)
    produced = units_from_legacy_scenes(scenes)
    total = derived.total or int(job.get("total") or 0) or unit_count

    state = derived.state
    if not derived.terminal and str(job.get("status") or "") in JOB_DONE_STATES:
        state = settled_state(produced, total)

    return JobStatus(
        job_id=identity,
        state=state,
        ready=derived.ready,
        total=total,
        fraction=derived.fraction,
        units=produced,
        error=derived.error,
    )


# -- per-scene recording -----------------------------------------------------


def mark_scene(project_id: str, index: Any, state: str, **fields) -> None:
    """Set one scene's state and recount, atomically."""
    with _lock:
        job = read(project_id)
        if job is None:
            return
        scenes = dict(job.get("scene_statuses") or {})
        key = str(index)
        entry = dict(scenes.get(key) or {})
        entry["status"] = state
        for name, value in fields.items():
            entry[name] = value
        scenes[key] = entry
        job["scene_statuses"] = scenes
        _recount(job)
        save(project_id, job)


def record_ready(
    project_id: str,
    index: Any,
    local_files: list[str],
    *,
    urls: list[str] | None = None,
    kind: str = "image",
) -> dict:
    """Settle one unit as produced, with the same metadata for every provider.

    `local_files` are the browser-facing `/output/...` paths the organizer has
    always returned. Remote `urls` are kept on the job for redownload only and
    never cross into the workflow port (D38).
    """
    thumb = None
    duration_s = None
    if local_files:
        absolute = _absolute_local(local_files[0])
        if absolute and kind == "video":
            thumb = generate_video_thumbnail(absolute, project_id, index)
            duration_s = _probe_duration(absolute)
        elif absolute:
            thumb = generate_image_thumbnail(absolute, project_id, index)

    entry = {
        "status": "ready",
        "local_files": list(local_files or []),
        "urls": list(urls or []),
    }
    if thumb:
        entry["thumb_path"] = thumb
    if duration_s is not None:
        entry["duration_s"] = duration_s
    if kind:
        entry["kind"] = kind
    mark_scene(
        project_id, index, "ready",
        **{k: v for k, v in entry.items() if k != "status"},
    )
    return entry


def record_error(project_id: str, index: Any, message: str = "") -> None:
    """Settle one unit as failed with a caller-supplied, already-safe message."""
    fields: dict[str, Any] = {"local_files": [], "urls": []}
    if message:
        fields["error"] = str(message)
    mark_scene(project_id, index, "error", **fields)


def mark_done(project_id: str) -> None:
    """Close the job whatever the per-scene map says."""
    with _lock:
        job = read(project_id)
        if job is None:
            return
        _recount(job)
        job["status"] = "done"
        job["completed_at"] = now_iso()
        job["generation_time"] = _elapsed_seconds(job)
        save(project_id, job)
        logger.info(
            "[animator] job {} done ({}/{} ready)",
            project_id, job.get("ready", 0), job.get("total", 0),
        )


def mark_status(project_id: str, status_value: str) -> None:
    """Update the top-level job status string without touching scene entries."""
    with _lock:
        job = read(project_id)
        if job is None:
            return
        job["status"] = status_value
        save(project_id, job)


def clear_completion(project_id: str) -> None:
    """Clear stale completion fields before a redownload or retry begins."""
    with _lock:
        job = read(project_id)
        if job is None:
            return
        job.pop("completed_at", None)
        job.pop("generation_time", None)
        save(project_id, job)


def maybe_finish(project_id: str) -> bool:
    """Mark the job done when every scene is terminal. Returns True if closed."""
    with _lock:
        job = read(project_id)
        if job is None:
            return False
        scenes = job.get("scene_statuses") or {}
        if not scenes:
            return False
        all_done = all(
            isinstance(entry, Mapping) and entry.get("status") in ("ready", "error")
            for entry in scenes.values()
        )
        if not all_done:
            return False
        _recount(job)
        job["status"] = "done"
        job["completed_at"] = now_iso()
        job["generation_time"] = _elapsed_seconds(job)
        save(project_id, job)
        return True


def _recount(job: dict) -> None:
    """Recompute `ready`/`errors`/`total` from the scene map."""
    scenes = job.get("scene_statuses") or {}
    ready = sum(
        1 for entry in scenes.values()
        if isinstance(entry, Mapping) and entry.get("status") in ("ready", "done")
    )
    errors = sum(
        1 for entry in scenes.values()
        if isinstance(entry, Mapping) and entry.get("status") == "error"
    )
    job["ready"] = ready
    job["errors"] = errors
    job["total"] = max(int(job.get("total") or 0), len(scenes))
    if job["total"] and ready + errors >= job["total"]:
        if job.get("status") not in ("done", "error"):
            job["status"] = "done"
        if not job.get("completed_at"):
            job["completed_at"] = now_iso()
            job["generation_time"] = _elapsed_seconds(job)


# -- media helpers -----------------------------------------------------------


def requires_video(job: Mapping[str, Any] | None) -> bool:
    """True when the job is expected to produce videos only (Grok video mode)."""
    if not isinstance(job, Mapping):
        return False
    payload = job.get("payload") or {}
    if not isinstance(payload, Mapping):
        return False
    return str(payload.get("grok_mode") or payload.get("mode") or "").lower() == "video"


def looks_like_video(value: str) -> bool:
    clean = str(value or "").split("?", 1)[0].lower()
    return clean.endswith(VIDEO_EXTS) or "/generated_video" in clean


def filter_video_urls(urls) -> list:
    return [url for url in (urls or []) if looks_like_video(url)]


def filter_video_images(images) -> list:
    filtered = []
    for image in images or []:
        if not isinstance(image, Mapping):
            continue
        ext = str(image.get("ext", "")).lower()
        source_url = image.get("source_url", "")
        filename = image.get("filename", "")
        if ext in VIDEO_EXTS or looks_like_video(source_url) or looks_like_video(filename):
            filtered.append(image)
    return filtered


def generate_video_thumbnail(video_path: str, project_id: str, index: Any) -> str | None:
    """Extract a thumbnail jpg from a video file. Returns a URL or None."""
    # Prefer a co-located `_thumb.jpg` when the organizer already wrote one.
    sibling = video_path.rsplit(".", 1)[0] + "_thumb.jpg"
    destination = thumbnail_path(project_id, index)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        if os.path.isfile(sibling):
            return f"/api/thumbnails/{project_id}/animator/{index}.jpg"
        return None
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        target = destination if not os.path.isfile(sibling) else sibling
        if not os.path.isfile(target):
            subprocess.run(
                [ffmpeg, "-y", "-i", video_path, "-map", "0:v:0",
                 "-vframes", "1", "-ss", "0.1", "-q:v", "3", destination],
                capture_output=True, timeout=10,
            )
            target = destination
        if os.path.isfile(target) and target != destination:
            # Copy sibling into the managed thumbnails tree when present.
            import shutil
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(target, destination)
        if os.path.isfile(destination):
            return f"/api/thumbnails/{project_id}/animator/{index}.jpg"
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def generate_image_thumbnail(image_path: str, project_id: str, index: Any) -> str | None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    destination = thumbnail_path(project_id, index)
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        subprocess.run(
            [ffmpeg, "-y", "-i", image_path, "-vf", "scale=480:-1",
             "-q:v", "4", destination],
            capture_output=True, timeout=15,
        )
        if os.path.isfile(destination):
            return f"/api/thumbnails/{project_id}/animator/{index}.jpg"
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _absolute_local(browser_path: str) -> str | None:
    """Turn `/output/animator/...` into an absolute filesystem path."""
    text = str(browser_path or "").replace("\\", "/")
    if text.startswith("/output/animator/"):
        relative = text[len("/output/animator/"):]
        candidate = os.path.join(ANIMATOR_DIR, *relative.split("/"))
        return candidate if os.path.isfile(candidate) else None
    if os.path.isfile(text):
        return text
    return None


def _probe_duration(path: str) -> float | None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    import re
    match = re.search(rb"Duration:\s*(\d+):(\d+):(\d+\.\d+)", completed.stderr or b"")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _elapsed_seconds(job: Mapping[str, Any], *, include_running: bool = False) -> float:
    try:
        existing = float(job.get("generation_time", 0) or 0)
        if existing > 0:
            return round(existing, 3)
    except (TypeError, ValueError):
        pass

    start_dt = _parse_iso(job.get("created_at"))
    if not start_dt:
        return 0.0
    end_dt = _parse_iso(job.get("completed_at"))
    if end_dt is None and include_running:
        end_dt = datetime.now().astimezone()
    if end_dt is None:
        end_dt = _parse_iso(job.get("updated_at"))
    if end_dt is None:
        return 0.0
    if start_dt.tzinfo is not None:
        start_dt = start_dt.replace(tzinfo=None)
    if end_dt.tzinfo is not None:
        end_dt = end_dt.replace(tzinfo=None)
    return round(max((end_dt - start_dt).total_seconds(), 0.0), 3)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def elapsed_seconds(job: Mapping[str, Any], *, include_running: bool = False) -> float:
    """Public wrapper used by the status and history routes."""
    return _elapsed_seconds(job, include_running=include_running)


def load_from_disk() -> None:
    """Rehydrate the in-memory store from every on-disk grabber job."""
    if not os.path.isdir(ANIMATOR_DIR):
        return
    from scriptase.modules.video.organizer import reconcile_project

    for entry in os.scandir(ANIMATOR_DIR):
        if not entry.is_dir():
            continue
        pid = entry.name
        try:
            reconcile_project(ANIMATOR_DIR, pid)
        except Exception as exc:
            logger.debug("[animator] reconcile failed for {}: {}", pid, exc)
        path = os.path.join(entry.path, MANIFEST_NAME)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                import json
                job = json.load(handle)
            if isinstance(job, dict):
                _store.set(pid, job)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("[animator] skipped loading job from {}: {}", pid, exc)


__all__ = [
    "IMAGE_EXTS",
    "MANIFEST_NAME",
    "VIDEO_EXTS",
    "clear_completion",
    "elapsed_seconds",
    "filter_video_images",
    "filter_video_urls",
    "generate_image_thumbnail",
    "generate_video_thumbnail",
    "get",
    "grabber_jobs",
    "load_from_disk",
    "local_path",
    "looks_like_video",
    "manifest_path",
    "mark_done",
    "mark_scene",
    "mark_status",
    "maybe_finish",
    "project_dir",
    "read",
    "record_error",
    "record_ready",
    "requires_video",
    "save",
    "scene_dir",
    "seed",
    "set_job",
    "status",
    "thumbnail_path",
]
