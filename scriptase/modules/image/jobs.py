"""The storyboard job manifest — one owner for `storyboard.json` (step 14.2).

Before this step four places wrote the same file with four different rules:
`routes.generate` and `adapters/storyboard._step_storyboard` each seeded it,
`routes._generate_storyboard` recorded downloaded scenes with a thumbnail, and
`gemini_ws._handle_image_upload` recorded uploaded scenes *without* one — so a
frame's per-scene metadata depended on which provider produced it. Three of the
four also used bare `open().write()` rather than `safe_json_write`.

This module is the single writer. Providers own remote/local generation
mechanics and call `record_ready` / `record_error` when a unit settles; the
manifest shape, the thumbnail, the versioned rotation, and the optional
watermark pass are applied here, identically for every provider.

`storyboard.json` stays authoritative and public (§17.1): the legacy status
route, the pipeline poller, and the Storyboard page all keep reading the same
`{total, ready, errors, scene_statuses}` document with the same values.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from typing import Any, Mapping

from loguru import logger

from config import STORYBOARD_DIR, THUMBNAILS_DIR
from scriptase.shared.ffmpeg_utils import find_ffmpeg
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.providers.jobs import (
    RUNNING,
    SCENE_SENTINEL_KEY,
    JobStatus,
    status_from_scenes,
)

MANIFEST_NAME = "storyboard.json"
SCENE_PROMPTS_NAME = "scene_prompts.json"
IMAGE_EXTENSIONS = (".jpeg", ".jpg", ".png", ".webp")

THUMB_SIZE = "480:-1"
THUMB_QUALITY = "4"

# Serializes the read-modify-write cycle. The extension pushes one message per
# frame on the WebSocket thread while a download loop writes from its own
# thread, so per-scene updates would otherwise clobber each other.
#
# There is deliberately no in-memory mirror. The legacy store kept one and the
# status route had to bypass it ("Gemini WS handler writes to disk, not
# in-memory"), because a cached copy goes stale the moment any writer skips it.
# `safe_json_write` is atomic, so the file is both authoritative and cheap.
_lock = threading.RLock()


# -- paths -------------------------------------------------------------------


def project_dir(project_id: str) -> str:
    return os.path.join(STORYBOARD_DIR, project_id)


def manifest_path(project_id: str) -> str:
    return os.path.join(project_dir(project_id), MANIFEST_NAME)


def scene_dir(project_id: str, index: Any) -> str:
    return os.path.join(project_dir(project_id), str(index))


def scene_prompts_path(project_id: str) -> str:
    return os.path.join(project_dir(project_id), SCENE_PROMPTS_NAME)


def thumbnail_path(project_id: str, index: Any) -> str:
    return os.path.join(THUMBNAILS_DIR, project_id, "storyboard", f"{index}.jpg")


def local_path(project_id: str, index: Any, filename: str) -> str:
    """The browser-facing `/output/...` path the manifest has always stored."""
    return f"/output/storyboard/{project_id}/{index}/{filename}"


# -- manifest lifecycle ------------------------------------------------------


def seed(project_id: str, request, *, provider_id: str = "") -> dict:
    """Create the manifest for a new job and publish it.

    `provider_id` is recorded so a reader can tell which provider produced a
    frame; it is metadata only and never drives dispatch.
    """
    job = {
        "project_id": project_id,
        "status": "running",
        "total": request.unit_count,
        "ready": 0,
        "errors": 0,
        "aspect_ratio": request.aspect_ratio,
        "provider": provider_id,
        "created_at": now_iso(),
        "completed_at": None,
        "scene_statuses": {
            str(scene.index): {"status": "pending", "image_url": None, "local_path": None}
            for scene in request.scenes
        },
    }
    save(project_id, job)
    save_scene_prompts(project_id, request.legacy_scenes())
    return job


def read(project_id: str) -> dict | None:
    """The current manifest, or `None` when the job has not been seeded."""
    path = manifest_path(project_id)
    if not os.path.isfile(path):
        return None
    try:
        data = safe_json_read(path)
    except (OSError, ValueError):
        return None
    return dict(data) if isinstance(data, Mapping) else None


def save(project_id: str, job: Mapping[str, Any]) -> None:
    """Publish a manifest atomically. Never raises."""
    try:
        safe_json_write(manifest_path(project_id), dict(job), indent=2)
    except OSError as exc:
        logger.error("[storyboard] could not save {}: {}", MANIFEST_NAME, exc)


def save_scene_prompts(project_id: str, scenes: list[Mapping[str, Any]]) -> None:
    """Persist the requested prompts beside the manifest.

    Written for every provider, not just the extension: it is what lets a
    downstream consumer recover the prompt a frame was generated from.
    """
    try:
        safe_json_write(scene_prompts_path(project_id), list(scenes), indent=2)
    except OSError as exc:
        logger.debug("[storyboard] could not save scene prompts: {}", exc)


def status(
    project_id: str, job_id: str | None = None, *, unit_count: int = 0
) -> JobStatus:
    """The `JobStatus` every storyboard provider's `poll` returns (§33.2).

    One definition, so the three providers cannot disagree about what "done"
    means. Per-unit results ride along in `units`, which is what lets the shared
    service report a partial outcome and reuse produced frames on retry.
    """
    from scriptase.providers.media_jobs import (
        JOB_DONE_STATES,
        settled_state,
        units_from_legacy_scenes,
    )

    identity = job_id or project_id
    job = read(project_id)
    if job is None:
        # The job has not been seeded yet — not an error, just nothing to see.
        return JobStatus(job_id=identity, state=RUNNING, total=unit_count)

    raw = job.get("scene_statuses")
    scenes = raw if isinstance(raw, Mapping) else {}
    derived = status_from_scenes(identity, scenes)
    produced = units_from_legacy_scenes(scenes)
    total = derived.total or unit_count

    state = derived.state
    if not derived.terminal and str(job.get("status") or "") in JOB_DONE_STATES:
        # The extension declares the job finished whatever the per-scene map
        # says; units still pending at that point never arrive.
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


def merge_prior_scenes(project_id: str, prior: Any, keep: Any) -> None:
    """Re-attach the scenes a single-scene submit reset to pending.

    A provider seeds the manifest for the request it was given, so regenerating
    one frame would otherwise drop every other frame from the status route.
    Runs under the same lock as `mark_scene`, because the provider's worker may
    already be recording the frame being regenerated.
    """
    if not isinstance(prior, Mapping):
        return
    with _lock:
        job = read(project_id)
        if job is None:
            return
        scenes = dict(job.get("scene_statuses") or {})
        for key, entry in prior.items():
            if str(key) == str(keep) or not isinstance(entry, Mapping):
                continue
            scenes.setdefault(str(key), dict(entry))
        job["scene_statuses"] = scenes
        job["total"] = max(
            int(job.get("total") or 0),
            sum(1 for key in scenes if str(key) != SCENE_SENTINEL_KEY),
        )
        # Reopened first; `_recount` closes it again if every scene is terminal.
        job["status"] = "running"
        job["completed_at"] = None
        _recount(job)
        save(project_id, job)


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
    file_path: str,
    *,
    image_url: str | None = None,
    remove_watermark: bool = False,
) -> dict:
    """Settle one unit as produced, with the same metadata for every provider.

    Applies the optional watermark pass first (so the thumbnail is generated
    from the cleaned frame, which the extension path never guaranteed), then
    the thumbnail, then the manifest entry.
    """
    if remove_watermark:
        _remove_watermark(file_path)
    thumb = generate_thumbnail(file_path, project_id, index)
    entry = {
        "status": "ready",
        "image_url": image_url,
        "local_path": local_path(project_id, index, os.path.basename(file_path)),
        "thumb_path": thumb,
    }
    dimensions = _dimensions(file_path)
    if dimensions:
        entry["width"], entry["height"] = dimensions
    mark_scene(project_id, index, "ready", **{k: v for k, v in entry.items() if k != "status"})
    return entry


def record_error(project_id: str, index: Any, message: str, *, image_url: str | None = None) -> None:
    """Settle one unit as failed with a caller-supplied, already-safe message."""
    mark_scene(
        project_id, index, "error",
        image_url=image_url, local_path=None, error=str(message),
    )


def mark_done(project_id: str) -> None:
    """Close the job whatever the per-scene map says.

    The extension reports job completion out of band, and units still pending
    at that point never arrive. Counters are recomputed from the scene map so
    an earlier race cannot leave `ready` overstated.
    """
    with _lock:
        job = read(project_id)
        if job is None:
            return
        scenes = dict(job.get("scene_statuses") or {})
        job["scene_statuses"] = scenes
        _recount(job)
        job["status"] = "done"
        job["completed_at"] = now_iso()
        # The job-level marker the extension protocol has always written. It is
        # not a unit; every counter here and in `status_from_scenes` skips it.
        scenes[SCENE_SENTINEL_KEY] = {**dict(scenes.get(SCENE_SENTINEL_KEY) or {}), "status": "done"}
        save(project_id, job)
        logger.info(
            "[storyboard] job {} done ({}/{} ready)",
            project_id, job.get("ready", 0), job.get("total", 0),
        )


def _recount(job: dict) -> None:
    """Recompute `ready`/`errors` and auto-close a fully produced job."""
    scenes = job.get("scene_statuses") or {}
    ready = sum(
        1 for key, entry in scenes.items()
        if str(key) != SCENE_SENTINEL_KEY
        and isinstance(entry, Mapping)
        and entry.get("status") in ("ready", "done")
    )
    errors = sum(
        1 for key, entry in scenes.items()
        if str(key) != SCENE_SENTINEL_KEY
        and isinstance(entry, Mapping)
        and entry.get("status") == "error"
    )
    job["ready"] = ready
    job["errors"] = errors
    total = int(job.get("total") or 0)
    if total and ready + errors >= total:
        job["status"] = "done"
        if not job.get("completed_at"):
            job["completed_at"] = now_iso()


# -- image files -------------------------------------------------------------


def extension_for(url_or_name: str, default: str = ".jpeg") -> str:
    lowered = str(url_or_name or "").lower()
    for candidate in (".png", ".webp", ".jpeg", ".jpg"):
        if lowered.endswith(candidate):
            return candidate
    return default


def version_existing_image(directory: str) -> None:
    """Rotate `image.*` to `image_v{N}.*` so regenerating keeps the history."""
    import glob

    for ext in IMAGE_EXTENSIONS:
        current = os.path.join(directory, f"image{ext}")
        if not os.path.isfile(current):
            continue
        existing = glob.glob(os.path.join(directory, f"image_v*{ext}"))
        versioned = os.path.join(directory, f"image_v{len(existing) + 1}{ext}")
        os.rename(current, versioned)
        logger.info("[storyboard] versioned {} → {}", current, versioned)


def prepare_scene_file(project_id: str, index: Any, ext: str) -> str:
    """Make the scene directory, rotate any previous frame, return the target."""
    directory = scene_dir(project_id, index)
    os.makedirs(directory, exist_ok=True)
    version_existing_image(directory)
    return os.path.join(directory, f"image{ext}")


def current_image(project_id: str, index: Any) -> str | None:
    """The non-versioned frame for a scene, if one exists."""
    directory = scene_dir(project_id, index)
    if not os.path.isdir(directory):
        return None
    for ext in IMAGE_EXTENSIONS:
        candidate = os.path.join(directory, f"image{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None


def generate_thumbnail(source: str, project_id: str, index: Any) -> str | None:
    """Write a JPEG thumbnail and return its URL, or `None` when unavailable."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.warning("[storyboard] ffmpeg not found — no thumbnail for {}", source)
        return None
    destination = thumbnail_path(project_id, index)
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        subprocess.run(
            [ffmpeg, "-y", "-i", source, "-vf", f"scale={THUMB_SIZE}",
             "-q:v", THUMB_QUALITY, destination],
            capture_output=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("[storyboard] thumbnail failed for {}: {}", source, exc)
        return None
    if not os.path.isfile(destination):
        return None
    return f"/api/thumbnails/{project_id}/storyboard/{index}.jpg"


def _dimensions(path: str) -> tuple[int, int] | None:
    """Frame size for the unit metadata (§32.4). Best effort, never raises."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path], capture_output=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(rb"\s(\d{2,5})x(\d{2,5})[,\s]", completed.stderr or b"")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _remove_watermark(path: str) -> None:
    """Run the watermark remover. Non-critical: a failure never fails a unit."""
    try:
        from scriptase.modules.image.watermark import remove_watermark
    except ImportError as exc:
        logger.warning("[storyboard] watermark remover unavailable: {}", exc)
        return
    try:
        remove_watermark(path)
    except Exception as exc:  # third-party CV stack; must not fail the unit
        logger.debug("[storyboard] watermark removal failed for {}: {}", path, exc)


def sweep_watermarks(project_id: str) -> int:
    """Re-run watermark removal over every frame of a project."""
    directory = project_dir(project_id)
    if not os.path.isdir(directory):
        return 0
    cleaned = 0
    for entry in os.listdir(directory):
        child = os.path.join(directory, entry)
        if not os.path.isdir(child):
            continue
        for name in os.listdir(child):
            if name.startswith("image") and name.lower().endswith(IMAGE_EXTENSIONS):
                _remove_watermark(os.path.join(child, name))
                cleaned += 1
    logger.info("[storyboard] watermark sweep for {} — {} frames", project_id, cleaned)
    return cleaned


__all__ = [
    "IMAGE_EXTENSIONS",
    "MANIFEST_NAME",
    "SCENE_PROMPTS_NAME",
    "current_image",
    "extension_for",
    "generate_thumbnail",
    "local_path",
    "manifest_path",
    "mark_done",
    "mark_scene",
    "merge_prior_scenes",
    "prepare_scene_file",
    "project_dir",
    "read",
    "record_error",
    "record_ready",
    "save",
    "save_scene_prompts",
    "scene_dir",
    "scene_prompts_path",
    "seed",
    "status",
    "sweep_watermarks",
    "thumbnail_path",
    "version_existing_image",
]
