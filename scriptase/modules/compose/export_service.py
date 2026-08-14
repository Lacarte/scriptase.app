"""Export execution and export-payload normalisation.

The job registry, ``_process_video`` and their helpers come verbatim from V2
``studio/editor/routes.py``; the payload normalisers from V2
``studio/pipeline/services.py`` (lines 476-707).

Service layer: no Flask import belongs in this module.

``_builtin_audio_abs_to_url`` below is the *pipeline* one — it takes a
``bucket`` and accepts any file under ``APP_ASSETS_DIR``. The editor's
same-named helper takes a ``track_type`` and additionally requires the file
to sit under ``sounds/<bucket>/``; it lives in ``compose/audio_service.py``.
The two are genuinely different, so both survive in their own module.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import traceback

from loguru import logger

from config import APP_ASSETS_DIR, APP_CONFIG_PATH, EXPORT_DIR, PROJECTS_DIR, SCENES_DIR
from scriptase.shared.ffmpeg_utils import find_ffprobe
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.shared.security import sanitize_project_id

# ---------------------------------------------------------------------------
# Export job storage & output directory
# ---------------------------------------------------------------------------
_export_jobs = {}
_export_jobs_lock = threading.Lock()
EXPORT_DIR_ABS = os.path.abspath(EXPORT_DIR)
EXPORT_MAX_JOB_AGE = 3600  # evict finished jobs after 1 hour

logger.info("Export output directory: {}", EXPORT_DIR)


def _auto_sync_after_export(filename, output_path):
    """Auto-sync exported video to sync folder if enabled in settings."""
    if not filename or not output_path or not os.path.isfile(output_path):
        return

    cfg = safe_json_read(APP_CONFIG_PATH) or {}
    defaults = cfg.get("defaults", {})
    user = cfg.get("user", {})

    if not (user.get("sts-auto-sync", defaults.get("sts-auto-sync", False))):
        return

    sync_folder = (user.get("sts-sync-folder") or defaults.get("sts-sync-folder") or "").strip()
    if not sync_folder:
        return

    sync_folder = os.path.normpath(sync_folder)
    if not os.path.isdir(sync_folder):
        return

    dest_dir = os.path.join(sync_folder, "exports")
    os.makedirs(dest_dir, exist_ok=True)

    dest_path = os.path.join(dest_dir, filename)
    if os.path.isfile(dest_path) and os.path.getsize(dest_path) == os.path.getsize(output_path):
        logger.info("Auto-sync: {} already up to date", filename)
        return

    shutil.copy2(output_path, dest_path)
    logger.success("Auto-synced: {} → {}", filename, dest_dir)


class ExportCancelled(Exception):
    """Raised when an export job is cancelled while processing."""


def _safe_project_id(project_id: str) -> str:
    return sanitize_project_id(project_id)


def _resolve_export_relpath(rel_path: str) -> str:
    """Resolve a path under EXPORT_DIR, rejecting traversal."""
    normalized = (rel_path or "").replace("\\", "/").lstrip("/")
    normalized = os.path.normpath(normalized).replace("\\", "/")
    if normalized.startswith("../") or normalized == "..":
        raise ValueError("Invalid path")
    abs_path = os.path.abspath(os.path.join(EXPORT_DIR_ABS, normalized))
    if os.path.commonpath([EXPORT_DIR_ABS, abs_path]) != EXPORT_DIR_ABS:
        raise ValueError("Invalid path")
    return abs_path


_ffprobe_bin = find_ffprobe()


def _ffprobe_video(abs_path: str) -> dict:
    """Return {duration, width, height} via ffprobe, or empty dict on failure."""
    if not _ffprobe_bin:
        return {}
    try:
        r = subprocess.run(
            [_ffprobe_bin, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", abs_path],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return {}
        data = json.loads(r.stdout)
        dur = float((data.get("format") or {}).get("duration", 0))
        # Find video stream for dimensions
        w, h = 0, 0
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                w = int(s.get("width", 0))
                h = int(s.get("height", 0))
                break
        return {"duration": round(dur, 2), "width": w, "height": h}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as error:
        logger.debug("ffprobe probe failed for {}: {}", abs_path, error)
        return {}


def _cleanup_old_export_jobs():
    """Evict completed/failed jobs older than EXPORT_MAX_JOB_AGE."""
    now = time.time()
    with _export_jobs_lock:
        expired = [
            jid for jid, job in _export_jobs.items()
            if job["status"] in ("completed", "failed", "cancelled")
            and now - job.get("created_at", 0) > EXPORT_MAX_JOB_AGE
        ]
        for jid in expired:
            del _export_jobs[jid]
    if expired:
        logger.debug("Evicted {} old export job(s)", len(expired))


def _cleanup_orphaned_temp_dirs():
    """Remove leftover video_export_* temp dirs older than 2 hours."""
    tmp_root = tempfile.gettempdir()
    cutoff = time.time() - 7200
    cleaned = 0
    try:
        for entry in os.listdir(tmp_root):
            if not entry.startswith("video_export_"):
                continue
            path = os.path.join(tmp_root, entry)
            if not os.path.isdir(path):
                continue
            try:
                mtime = os.path.getmtime(path)
                if mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    cleaned += 1
            except OSError as error:
                logger.debug("Skipping temp dir cleanup for {}: {}", path, error)
    except OSError as error:
        logger.debug("Could not scan temp root {}: {}", tmp_root, error)
    if cleaned:
        logger.info("Cleaned up {} orphaned video_export temp dir(s)", cleaned)


# Run orphan cleanup on module load (server start)
_cleanup_orphaned_temp_dirs()


def _process_video(job_id, export_data, output_path):
    """Process video in background thread with step-level error tracking."""
    short_id = job_id[:8]
    with _export_jobs_lock:
        job = _export_jobs.get(job_id)
    if job is None:
        logger.warning("[{}] Export job disappeared before processing started", short_id)
        return

    def _set_step(step, message):
        job["step"] = step
        job["message"] = message
        logger.debug("[{}] Step: {} — {}", short_id, step, message)

    def _metadata_path():
        base, _ext = os.path.splitext(output_path)
        return base + ".json"

    try:
        # Import here to avoid circular imports at module load
        from scriptase.modules.compose.video_processor import VideoProcessor

        logger.info("[{}] Processing started", short_id)
        job["status"] = "processing"
        _set_step("init", "Starting video processing")

        def update_progress(progress, message):
            if job.get("status") == "cancelled":
                raise ExportCancelled("Export cancelled by user")
            job["progress"] = progress
            job["message"] = message
            # Infer step from progress ranges set by VideoProcessor
            if progress < 80:
                job["step"] = "scenes"
            elif progress < 85:
                job["step"] = "concat"
            elif progress < 90:
                job["step"] = "overlay"
            elif progress < 100:
                job["step"] = "captions"
            logger.debug("[{}] Progress: {}% — {}", short_id, progress, message)

        processor = VideoProcessor(
            export_data=export_data,
            progress_callback=update_progress,
        )
        processor.process(output_path)

        if job.get("status") == "cancelled":
            raise ExportCancelled("Export cancelled by user")

        # Verify output was actually created
        if not os.path.exists(output_path):
            raise RuntimeError("Export finished but output file is missing")

        file_size = os.path.getsize(output_path)
        if file_size == 0:
            os.remove(output_path)
            raise RuntimeError("Export produced an empty file")

        logger.success("[{}] Export completed — {} ({:.1f} MB)",
                       short_id, output_path, file_size / (1024 * 1024))

        # Derive aspect ratio from resolution
        _res = (export_data.get("output") or {}).get("resolution") or {}
        _w, _h = _res.get("width", 0), _res.get("height", 0)
        _ratio = f"{_w}:{_h}" if _w and _h else ""

        # Try to read style from the scenes project
        _style = ""
        project_id = export_data.get("project_id", "")
        if project_id:
            _scenes_json = os.path.join(SCENES_DIR, project_id, "scenes.json")
            try:
                if os.path.isfile(_scenes_json):
                    _sdata = safe_json_read(_scenes_json)
                    _style = _sdata.get("style", "")
            except Exception as error:
                logger.debug("Could not read style metadata from {}: {}", _scenes_json, error)

        # Probe exported video for duration and dimensions
        _probe = _ffprobe_video(output_path)
        scene_count = len(export_data.get("scenes", []))

        export_audio_summary = {
            "narration": export_data.get("audio") if isinstance(export_data.get("audio"), dict) else None,
            "bg_music": export_data.get("bgMusic") if isinstance(export_data.get("bgMusic"), dict) else None,
            "sfx": export_data.get("sfx") if isinstance(export_data.get("sfx"), dict) else None,
        }

        safe_json_write(os.path.splitext(output_path)[0] + ".json", {
            "job_id": job_id,
            "project_id": job.get("project_id", ""),
            "output_filename": job.get("output_filename", ""),
            "completed_at": time.time(),
            "scene_count": scene_count,
            "style": _style,
            "ratio": _ratio,
            "duration": _probe.get("duration", 0),
            "width": _probe.get("width", 0),
            "height": _probe.get("height", 0),
            "export_audio": export_audio_summary,
        }, indent=2)

        safe_json_write(_metadata_path(), {
            "job_id": job_id,
            "project_id": job.get("project_id", ""),
            "output_filename": job.get("output_filename", ""),
            "completed_at": time.time(),
        }, indent=2)

        job["status"] = "completed"
        job["progress"] = 100
        job["step"] = "done"
        job["message"] = "Export completed successfully"
        job["completed_at"] = time.time()

        # Auto-sync to folder if enabled
        try:
            _auto_sync_after_export(job.get("output_filename", ""), output_path)
        except Exception as sync_err:
            logger.warning("[{}] Auto-sync failed: {}", short_id, sync_err)

    except ExportCancelled as e:
        logger.info("[{}] Export cancelled", short_id)

        if os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.debug("[{}] Removed cancelled output: {}", short_id, output_path)
            except OSError as rm_err:
                logger.warning("[{}] Could not remove cancelled output: {}", short_id, rm_err)
        meta_path = _metadata_path()
        if os.path.exists(meta_path):
            try:
                os.remove(meta_path)
            except OSError as error:
                logger.debug("Could not remove cancelled metadata {}: {}", meta_path, error)

        job["status"] = "cancelled"
        job["error"] = None
        job["message"] = str(e)
        job["completed_at"] = time.time()

    except Exception as e:
        logger.error("[{}] Export FAILED at step '{}': {}", short_id, job.get("step"), e)
        logger.debug("[{}] Traceback:\n{}", short_id, traceback.format_exc())

        # Clean up partial output file
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
                logger.debug("[{}] Removed partial output: {}", short_id, output_path)
            except OSError as rm_err:
                logger.warning("[{}] Could not remove partial output: {}", short_id, rm_err)
        meta_path = _metadata_path()
        if os.path.exists(meta_path):
            try:
                os.remove(meta_path)
            except OSError as error:
                logger.debug("Could not remove failed metadata {}: {}", meta_path, error)

        failed_step = job.get("step") or "unknown"
        job["status"] = "failed"
        job["error"] = str(e)
        job["step"] = failed_step
        job["message"] = f"Export failed during {failed_step}: {e}"
        job["completed_at"] = time.time()


def _normalize_export_audio(assembled):
    """Normalize assembled editor audio data into export audio config."""
    audio = assembled.get("audio")
    if isinstance(audio, dict):
        audio_path = audio.get("path") or audio.get("url") or ""
        if audio_path:
            normalized = dict(audio)
            normalized["path"] = audio_path
            return normalized

    disabled_tracks = set(assembled.get("disabled_tracks") or [])
    usable_tracks = []
    for track in assembled.get("audio_tracks") or []:
        if not isinstance(track, dict):
            continue
        if track.get("muted"):
            continue
        track_id = track.get("id")
        if track_id and track_id in disabled_tracks:
            continue

        track_path = track.get("path") or track.get("url") or ""
        if not track_path:
            continue

        usable_tracks.append(track)

    for track in usable_tracks:
        if (track.get("type") or "").lower() != "voice":
            continue
        return {
            "path": track.get("path") or track.get("url") or "",
            "volume": track.get("volume", 1.0),
            "start_offset": track.get("startOffset", track.get("start_offset", 0)),
            "timeline_offset": track.get("timelineOffset", track.get("timeline_offset", 0)),
            "trimmed_duration": track.get("trimmedDuration", track.get("trimmed_duration")),
            "fade_in": track.get("fadeIn", track.get("fade_in", 0)),
            "fade_out": track.get("fadeOut", track.get("fade_out", 0.5)),
        }

    for track in usable_tracks:
        return {
            "path": track.get("path") or track.get("url") or "",
            "volume": track.get("volume", 1.0),
            "start_offset": track.get("startOffset", track.get("start_offset", 0)),
            "timeline_offset": track.get("timelineOffset", track.get("timeline_offset", 0)),
            "trimmed_duration": track.get("trimmedDuration", track.get("trimmed_duration")),
            "fade_in": track.get("fadeIn", track.get("fade_in", 0)),
            "fade_out": track.get("fadeOut", track.get("fade_out", 0.5)),
        }

    return None


def _extract_music_track(assembled):
    """Pull the first non-muted/non-disabled music track out of audio_tracks."""
    if not isinstance(assembled, dict):
        return None
    disabled_tracks = set(assembled.get("disabled_tracks") or [])
    for track in assembled.get("audio_tracks") or []:
        if not isinstance(track, dict):
            continue
        if (track.get("type") or "").lower() != "music":
            continue
        if track.get("muted"):
            continue
        if track.get("id") and track.get("id") in disabled_tracks:
            continue
        track_path = track.get("path") or track.get("url") or ""
        if not track_path:
            continue
        return {
            "path": track_path,
            "volume": track.get("volume", 0.15),
            "fade_in": track.get("fadeIn", track.get("fade_in", 2.0)),
            "fade_out": track.get("fadeOut", track.get("fade_out", 3.0)),
            "loop": track.get("loop", True),
            "ducking_enabled": track.get("duckingEnabled", track.get("ducking_enabled", True)),
            "ducking_level": track.get("duckingLevel", track.get("ducking_level", 0.20)),
        }
    return None


def _extract_sfx_track(assembled):
    """Pull the first non-muted/non-disabled SFX track out of audio_tracks.

    Returns a dict shaped like a bgMusic entry (path/volume/loop/fades/ducking)
    so the renderer can mix it as a second auxiliary audio layer. Returns
    None when no usable SFX track exists.
    """
    if not isinstance(assembled, dict):
        return None
    disabled_tracks = set(assembled.get("disabled_tracks") or [])
    for track in assembled.get("audio_tracks") or []:
        if not isinstance(track, dict):
            continue
        if (track.get("type") or "").lower() != "sfx":
            continue
        if track.get("muted"):
            continue
        if track.get("id") and track.get("id") in disabled_tracks:
            continue
        track_path = track.get("path") or track.get("url") or ""
        if not track_path:
            continue
        return {
            "path": track_path,
            "volume": track.get("volume", 0.10),
            "fade_in": track.get("fadeIn", track.get("fade_in", 1.5)),
            "fade_out": track.get("fadeOut", track.get("fade_out", 2.0)),
            "loop": track.get("loop", True),
            "ducking_enabled": track.get("duckingEnabled", track.get("ducking_enabled", True)),
            "ducking_level": track.get("duckingLevel", track.get("ducking_level", 0.20)),
        }
    return None


def _builtin_audio_abs_to_url(bucket: str, abs_path: str) -> str | None:
    """Convert a built-in audio file under APP_ASSETS_DIR into a /assets URL."""
    if bucket not in {"music", "sfx"} or not abs_path:
        return None
    try:
        normalized = os.path.normpath(abs_path)
        assets_root = os.path.normpath(APP_ASSETS_DIR)
        if os.path.commonpath([normalized, assets_root]) != assets_root:
            return None
    except ValueError:
        return None
    rel = os.path.relpath(normalized, assets_root).replace("\\", "/")
    return f"/assets/{rel}"


def _persist_auto_selected_export_audio(project_id: str, *, bg_music=None, sfx=None) -> None:
    """Persist fallback export picks into project JSON so editor/export stay aligned."""
    if not project_id:
        return

    track_specs = []
    if isinstance(bg_music, dict) and bg_music.get("path"):
        music_path = bg_music.get("path")
        music_url = _builtin_audio_abs_to_url("music", music_path)
        if music_path and music_url:
            track_specs.append({
                "id": "at_music_export",
                "label": "Music",
                "type": "music",
                "file": os.path.basename(music_path),
                "path": music_url,
                "duration": 0,
                "timelineOffset": 0,
                "startOffset": 0,
                "trimmedDuration": None,
                "volume": bg_music.get("volume", 0.15),
                "loop": bg_music.get("loop", True),
                "muted": False,
                "duckingEnabled": bg_music.get("ducking_enabled", True),
                "duckingLevel": bg_music.get("ducking_level", 0.20),
                "fadeIn": bg_music.get("fade_in", 2.0),
                "fadeOut": bg_music.get("fade_out", 3.0),
            })

    if isinstance(sfx, dict) and sfx.get("path"):
        sfx_path = sfx.get("path")
        sfx_url = _builtin_audio_abs_to_url("sfx", sfx_path)
        if sfx_path and sfx_url:
            track_specs.append({
                "id": "at_sfx_export",
                "label": "SFX",
                "type": "sfx",
                "file": os.path.basename(sfx_path),
                "path": sfx_url,
                "duration": 0,
                "timelineOffset": 0,
                "startOffset": 0,
                "trimmedDuration": None,
                "volume": sfx.get("volume", 0.10),
                "loop": sfx.get("loop", True),
                "muted": False,
                "duckingEnabled": sfx.get("ducking_enabled", True),
                "duckingLevel": sfx.get("ducking_level", 0.20),
                "fadeIn": sfx.get("fade_in", 1.5),
                "fadeOut": sfx.get("fade_out", 2.0),
            })

    if not track_specs:
        return

    for filename in ("initial.json", "work@in@progress.json"):
        project_path = os.path.join(PROJECTS_DIR, project_id, filename)
        if not os.path.isfile(project_path):
            continue
        try:
            data = safe_json_read(project_path) or {}
        except Exception as error:
            logger.debug("Could not read {} for export audio persist: {}", project_path, error)
            continue
        if not isinstance(data, dict):
            continue

        existing_tracks = data.get("audio_tracks")
        if not isinstance(existing_tracks, list):
            existing_tracks = []

        kept_tracks = []
        for track in existing_tracks:
            if not isinstance(track, dict):
                kept_tracks.append(track)
                continue
            track_type = str(track.get("type") or "").lower()
            if track_type in {"music", "sfx"}:
                continue
            kept_tracks.append(track)

        data["audio_tracks"] = kept_tracks + [dict(spec) for spec in track_specs]
        safe_json_write(project_path, data, indent=2)


def _normalize_export_captions(assembled):
    """Normalize editor caption payload into export caption payload."""
    captions = assembled.get("captions")
    if not isinstance(captions, dict):
        return None

    entries = captions.get("entries")
    if not isinstance(entries, list):
        entries = captions.get("captions")
    if not isinstance(entries, list) or not entries:
        return None

    normalized = dict(captions)
    normalized["entries"] = entries
    return normalized
