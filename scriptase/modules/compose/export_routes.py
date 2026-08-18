"""Export execution API and the export library.

Transport only. Split out of V2 ``studio/editor/routes.py`` in step 0.3.
"""

import json
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import uuid

from flask import Blueprint, jsonify, request, send_file
from loguru import logger

from config import EXPORT_DIR, SCENES_DIR, STORYBOARD_DIR, TRASH_DIR
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.shared.validation import validate_json
from scriptase.modules.compose.export_service import (
    _cleanup_old_export_jobs,
    _export_jobs,
    _export_jobs_lock,
    _ffprobe_video,
    _process_video,
    _resolve_export_relpath,
    _safe_project_id,
)
from scriptase.modules.compose.project_service import _initial_path
from scriptase.modules.compose.schemas import ExportRequest
from scriptase.modules.compose.settings_service import _read_app_config

compose_export_bp = Blueprint("compose_export", __name__)


# ---------------------------------------------------------------------------
# Export API
# ---------------------------------------------------------------------------

@compose_export_bp.route("/api/export", methods=["POST"])
@validate_json(ExportRequest)
def start_export(data: ExportRequest):
    """Start a video export job."""
    try:
        export_data = data.model_dump(exclude_none=True)

        job_id = str(uuid.uuid4())
        project_id = data.project_id
        scene_count = len(data.scenes)
        output_filename = f"{project_id}_{job_id[:8]}.mp4"
        output_path = os.path.join(EXPORT_DIR, output_filename)

        logger.info("Export started — job={} project={} scenes={} output={}",
                     job_id[:8], project_id, scene_count, output_filename)

        # Log export settings
        output_cfg = export_data.get("output", {})
        res = output_cfg.get("resolution", {}) if isinstance(output_cfg, dict) else {}
        logger.debug("Export settings: {}x{} {}fps crf={} codec={}",
                      res.get("width", "?"), res.get("height", "?"),
                      output_cfg.get("fps", "?"), output_cfg.get("crf", "?"),
                      output_cfg.get("codec", "?"))

        audio_cfg = export_data.get("audio")
        if audio_cfg and audio_cfg.get("path"):
            logger.debug("Audio: path={} vol={}",
                          audio_cfg.get("path"), audio_cfg.get("volume", 1.0))
        else:
            logger.debug("Audio: none")

        bg_music = export_data.get("bgMusic")
        if bg_music:
            logger.debug("BgMusic: path={} vol={} loop={} ducking={}",
                          bg_music.get("path"), bg_music.get("volume"),
                          bg_music.get("loop"), bg_music.get("ducking_enabled"))

        captions = export_data.get("captions", {})
        cap_entries = captions.get("entries", []) if isinstance(captions, dict) else []
        if cap_entries:
            logger.debug("Captions: {} entries", len(cap_entries))

        # Log scene summary
        for i, sc in enumerate(export_data.get("scenes", [])):
            media = sc.get("media", {}) if isinstance(sc, dict) else {}
            effect = sc.get("effect", {}) if isinstance(sc, dict) else {}
            logger.debug("  Scene {}: type={} dur={}s effect={} path={}",
                          i + 1, media.get("type", "?"), sc.get("duration", "?") if isinstance(sc, dict) else "?",
                          effect.get("type", "static"),
                          (media.get("path") or "n/a")[:60])

        _cleanup_old_export_jobs()

        with _export_jobs_lock:
            _export_jobs[job_id] = {
                "status": "queued",
                "progress": 0,
                "message": "Job queued",
                "step": None,
                "output_path": output_path,
                "output_filename": output_filename,
                "project_id": project_id,
                "scene_count": scene_count,
                "error": None,
                "created_at": time.time(),
                "completed_at": None,
            }

        thread = threading.Thread(
            target=_process_video,
            args=(job_id, export_data, output_path),
            daemon=True,
        )
        thread.start()

        return jsonify({"job_id": job_id, "status": "queued", "message": "Export job started"})

    except Exception as e:
        logger.exception("Export start error")
        return jsonify({"error": str(e)}), 500


@compose_export_bp.route("/api/export/<job_id>/status", methods=["GET"])
def get_export_status(job_id):
    """Get status of an export job."""
    with _export_jobs_lock:
        job = _export_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "step": job.get("step"),
        "error": job["error"],
    })


@compose_export_bp.route("/api/export/<job_id>/download", methods=["GET"])
def download_export(job_id):
    """Download completed export."""
    with _export_jobs_lock:
        job = _export_jobs.get(job_id)
    if not job:
        logger.warning("Download request for unknown job: {}", job_id[:8])
        return jsonify({"error": "Job not found"}), 404

    if job["status"] != "completed":
        logger.warning("Download attempt on non-completed job: {} (status={})", job_id[:8], job["status"])
        return jsonify({"error": "Export not completed yet"}), 400
    if not os.path.exists(job["output_path"]):
        logger.error("Download file missing: {}", job["output_path"])
        return jsonify({"error": "Output file not found"}), 404

    logger.info("Serving download: {}", job["output_filename"])
    return send_file(
        job["output_path"],
        mimetype="video/mp4",
        as_attachment=True,
        download_name=job["output_filename"],
    )


@compose_export_bp.route("/api/export/<job_id>/preview", methods=["GET"])
def preview_export(job_id):
    """Preview completed export in browser."""
    with _export_jobs_lock:
        job = _export_jobs.get(job_id)
    if not job:
        logger.warning("Preview request for unknown job: {}", job_id[:8])
        return jsonify({"error": "Job not found"}), 404

    if job["status"] != "completed":
        logger.warning("Preview attempt on non-completed job: {} (status={})", job_id[:8], job["status"])
        return jsonify({"error": "Export not completed yet"}), 400
    if not os.path.exists(job["output_path"]):
        logger.error("Preview file missing: {}", job["output_path"])
        return jsonify({"error": "Output file not found"}), 404

    logger.info("Serving preview: {}", job["output_filename"])
    return send_file(
        job["output_path"],
        mimetype="video/mp4",
        as_attachment=False,
    )


@compose_export_bp.route("/api/export/library", methods=["GET"])
def export_library_list():
    """List exported videos from output/exports recursively."""
    if not os.path.isdir(EXPORT_DIR):
        return jsonify({"items": []})

    from datetime import datetime, timezone
    from urllib.parse import quote

    video_exts = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    items = []

    # Production uses its Job id as the project id by default. Joining that
    # compact, secret-free metadata here keeps the gallery filterable without
    # making the browser issue one request per video.
    jobs_by_project = {}
    try:
        from scriptase.jobs.store import list_jobs

        for production_job in list_jobs(limit=1000):
            jobs_by_project[production_job.id] = {
                "job_id": production_job.id,
                "channel_id": production_job.channel_id,
                "channel_name": str(production_job.channel_snapshot.get("name") or ""),
            }
    except Exception as error:
        logger.debug("Could not enrich export library with Job metadata: {}", error)

    def _normalize_completed_at(value):
        """Normalize export completion stamps to ISO strings."""
        if value in (None, ""):
            return ""
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        if isinstance(value, str):
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
            except (TypeError, ValueError):
                return value
        return ""

    for root, _dirs, files in os.walk(EXPORT_DIR):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in video_exts:
                continue

            abs_video = os.path.join(root, fname)
            rel_video = os.path.relpath(abs_video, EXPORT_DIR).replace("\\", "/")
            rel_folder = os.path.relpath(root, EXPORT_DIR).replace("\\", "/")
            base = os.path.splitext(fname)[0]
            folder_project_id = _safe_project_id(os.path.basename(root))
            meta_path = os.path.splitext(abs_video)[0] + ".json"
            project_id = ""
            meta_style = ""
            meta_ratio = ""
            meta_scene_count = 0
            meta_duration = 0
            meta_width = 0
            meta_height = 0
            meta_completed_at = ""
            meta_channel_id = ""
            meta_channel_name = ""
            meta_dirty = False  # whether sidecar needs update
            if os.path.isfile(meta_path):
                try:
                    meta = safe_json_read(meta_path)
                    project_id = _safe_project_id(meta.get("project_id", ""))
                    meta_style = meta.get("style", "")
                    meta_ratio = meta.get("ratio", "")
                    meta_scene_count = meta.get("scene_count", 0)
                    meta_duration = meta.get("duration", 0)
                    meta_width = meta.get("width", 0)
                    meta_height = meta.get("height", 0)
                    meta_completed_at = _normalize_completed_at(meta.get("completed_at"))
                    meta_channel_id = str(meta.get("channel_id") or "")
                    meta_channel_name = str(meta.get("channel_name") or "")
                except Exception as error:
                    logger.debug("Could not read export metadata {}: {}", meta_path, error)
                    project_id = ""

            # Probe video if duration/dimensions are missing
            if not meta_duration or not meta_width:
                probe = _ffprobe_video(abs_video)
                if probe:
                    if not meta_duration and probe.get("duration"):
                        meta_duration = probe["duration"]
                        meta_dirty = True
                    if not meta_width and probe.get("width"):
                        meta_width = probe["width"]
                        meta_height = probe.get("height", 0)
                        meta_dirty = True

            # Build video_ratio from actual dimensions
            video_ratio = ""
            if meta_width and meta_height:
                video_ratio = f"{meta_width}:{meta_height}"

            # Cache probe results into sidecar
            if meta_dirty and meta_path:
                try:
                    existing = safe_json_read(meta_path) if os.path.isfile(meta_path) else {}
                    existing["duration"] = meta_duration
                    existing["width"] = meta_width
                    existing["height"] = meta_height
                    safe_json_write(meta_path, existing, indent=2)
                except Exception as error:
                    logger.debug("Could not update export metadata {}: {}", meta_path, error)
            if not project_id:
                match = re.match(r"^(?P<project>.+)_[0-9a-fA-F]{8}$", base)
                if match:
                    project_id = _safe_project_id(match.group("project"))
            if not project_id:
                project_id = folder_project_id or _safe_project_id(base)

            # Pair ZIP by same filename in the same folder, fallback to generated project ZIP.
            zip_name = f"{base}.zip"
            abs_zip = os.path.join(root, zip_name)
            zip_exists = os.path.isfile(abs_zip)
            zip_rel = os.path.relpath(abs_zip, EXPORT_DIR).replace("\\", "/") if zip_exists else ""

            mtime = os.path.getmtime(abs_video)
            mtime_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            video_q = quote(rel_video, safe="/")
            zip_q = quote(zip_rel, safe="/") if zip_exists else ""

            # Read scenes.json for style, scene count, and pipeline timing
            pid = project_id or base
            pipeline_timing = {}
            source_folder = ""
            if not meta_style or not pipeline_timing:
                try:
                    _sp = os.path.join(SCENES_DIR, pid, "scenes.json")
                    if os.path.isfile(_sp):
                        _sd = safe_json_read(_sp)
                        if not meta_style:
                            meta_style = _sd.get("style", "")
                        if not meta_scene_count:
                            meta_scene_count = len(_sd.get("scenes", []))
                        source_folder = _sd.get("source_folder", "")
                        pipeline_timing = _sd.get("pipeline_timing", {})
                except Exception as error:
                    logger.debug("Could not read scene metadata: {}", error)

            project_name = ""
            project_total_duration = 0
            audio_track_count = 0
            caption_count = 0
            has_captions = False
            media_counts = {"video": 0, "image": 0, "text": 0}
            try:
                _project_json = _initial_path(pid)
                if os.path.isfile(_project_json):
                    _pdata = safe_json_read(_project_json)
                    project_name = _pdata.get("project_name", "")
                    source_folder = source_folder or _pdata.get("source_folder", "")
                    project_total_duration = _pdata.get("total_duration", 0)
                    audio_track_count = len(_pdata.get("audio_tracks") or [])

                    _captions = _pdata.get("captions") or {}
                    _caption_entries = []
                    if isinstance(_captions, dict):
                        _caption_entries = _captions.get("entries")
                        if not isinstance(_caption_entries, list):
                            _caption_entries = _captions.get("captions", [])
                    caption_count = len(_caption_entries or [])
                    has_captions = bool(_pdata.get("captionsEnabled") or caption_count)

                    for scene in _pdata.get("scenes") or []:
                        if not isinstance(scene, dict):
                            continue
                        scene_type = str(scene.get("type", "")).lower()
                        if scene_type in media_counts:
                            media_counts[scene_type] += 1
                            continue
                        if scene.get("isVideo"):
                            media_counts["video"] += 1
                        else:
                            media_counts["image"] += 1
            except Exception as error:
                logger.debug("Could not read project metadata: {}", error)

            completed_at = meta_completed_at or mtime_iso
            resolution_label = f"{meta_width}x{meta_height}" if meta_width and meta_height else ""
            job_metadata = jobs_by_project.get(pid, {})

            items.append({
                "project_id": pid,
                "project_name": project_name or pid,
                "job_id": job_metadata.get("job_id", ""),
                "channel_id": meta_channel_id or job_metadata.get("channel_id", ""),
                "channel_name": meta_channel_name or job_metadata.get("channel_name", ""),
                "video_name": fname,
                "video_relpath": rel_video,
                "folder_relpath": rel_folder if rel_folder != "." else "",
                "size_bytes": os.path.getsize(abs_video),
                "modified_at": mtime_iso,
                "completed_at": completed_at,
                "preview_url": f"/api/export/library/preview/{video_q}",
                "video_download_url": f"/api/export/library/download/{video_q}",
                "zip_download_url": (f"/api/export/library/download/{zip_q}" if zip_exists else (f"/api/editor/export-zip/{pid}" if pid else "")),
                "zip_source": ("file" if zip_exists else "generated"),
                "style": meta_style,
                "ratio": meta_ratio,
                "video_ratio": video_ratio,
                "duration": meta_duration,
                "project_total_duration": project_total_duration or meta_duration,
                "scene_count": meta_scene_count,
                "source_folder": source_folder,
                "width": meta_width,
                "height": meta_height,
                "resolution_label": resolution_label,
                "media_counts": media_counts,
                "audio_track_count": audio_track_count,
                "caption_count": caption_count,
                "has_captions": has_captions,
                "pipeline_timing": pipeline_timing,
            })

    items.sort(key=lambda it: it.get("modified_at", ""), reverse=True)
    return jsonify({"items": items, "count": len(items)})


@compose_export_bp.route("/api/export/library/prompts/<project_id>", methods=["GET"])
def export_library_prompts(project_id):
    """Return scene-level prompt details for analytics / prompt inspection."""
    from scriptase.shared.security import sanitize_project_id
    pid = sanitize_project_id(project_id)

    result = {"project_id": pid, "style": "", "style_name": "", "style_description": "", "style_prompt": "", "style_color": "", "scenes": []}

    # Read scenes.json
    scenes_path = os.path.join(SCENES_DIR, pid, "scenes.json")
    if os.path.isfile(scenes_path):
        sd = safe_json_read(scenes_path)
        result["style"] = sd.get("style", "")

    # Read initial.json for full scene data
    initial_path = _initial_path(pid)
    if os.path.isfile(initial_path):
        pd = safe_json_read(initial_path)
        result["style"] = result["style"] or pd.get("style", "")
        for i, s in enumerate(pd.get("scenes") or []):
            if not isinstance(s, dict):
                continue
            result["scenes"].append({
                "index": i,
                "script": s.get("script", ""),
                "image_prompt": s.get("image_prompt", s.get("prompt", "")),
                "narrative_role": s.get("narrative_role", ""),
                "duration": s.get("duration", 0),
                "visual_fx": s.get("visual_fx", ""),
                "scene_type": s.get("type", ""),
                "isVideo": s.get("isVideo", False),
            })

    # Resolve style template details
    if result["style"]:
        try:
            from scriptase.modules.scene_director.templates import TEMPLATES_BY_ID
            tmpl = TEMPLATES_BY_ID.get(result["style"])
            if tmpl:
                result["style_name"] = tmpl.get("name", "")
                result["style_description"] = tmpl.get("description", "")
                result["style_color"] = tmpl.get("color", "")
                from scriptase.modules.scene_director.style_compiler import normalize_template, compile_style_prompt
                normalized = normalize_template(tmpl)
                style_spec = normalized.get("style_spec", {})
                result["style_prompt"] = compile_style_prompt(style_spec, "")
        except Exception:
            pass

    # Read storyboard prompts if available
    storyboard_prompts_path = os.path.join(STORYBOARD_DIR, pid, "scene_prompts.json")
    if os.path.isfile(storyboard_prompts_path):
        try:
            sp = safe_json_read(storyboard_prompts_path)
            if isinstance(sp, list):
                for entry in sp:
                    idx = entry.get("scene", -1)
                    if 0 <= idx < len(result["scenes"]):
                        result["scenes"][idx]["storyboard_prompt"] = entry.get("prompt", "")
        except Exception:
            pass

    return jsonify(result)


@compose_export_bp.route("/api/export/library/trash", methods=["POST"])
def export_library_trash():
    """Move an exported video (and its sidecar .json / .zip) to output/TRASH."""
    data = request.get_json(silent=True) or {}
    rel_path = (data.get("video_relpath") or "").replace("\\", "/").strip("/")
    if not rel_path:
        return jsonify({"error": "Missing video_relpath"}), 400

    try:
        abs_video = _resolve_export_relpath(rel_path)
    except ValueError:
        return jsonify({"error": "Invalid path"}), 400

    if not os.path.isfile(abs_video):
        return jsonify({"error": "File not found"}), 404

    # Collect related files (sidecar .json and .zip with same base name)
    base_no_ext = os.path.splitext(abs_video)[0]
    files_to_move = [abs_video]
    for ext in (".json", ".zip"):
        sidecar = base_no_ext + ext
        if os.path.isfile(sidecar):
            files_to_move.append(sidecar)

    moved = []
    for fpath in files_to_move:
        fname = os.path.basename(fpath)
        dest = os.path.join(TRASH_DIR, fname)
        # Avoid overwriting: append timestamp if name collision
        if os.path.exists(dest):
            name, ext = os.path.splitext(fname)
            dest = os.path.join(TRASH_DIR, f"{name}_{int(time.time())}{ext}")
        shutil.move(fpath, dest)
        moved.append(os.path.basename(dest))
        logger.info("Trashed export file: {} → {}", fpath, dest)

    return jsonify({"status": "trashed", "moved": moved})


@compose_export_bp.route("/api/export/library/sync", methods=["GET"])
def export_library_sync():
    """SSE stream: copy exported videos to sync folder with per-file progress."""
    from flask import Response

    VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

    cfg = _read_app_config()
    defaults = cfg.get("defaults", {})
    user_settings = cfg.get("user", {})
    sync_folder = (user_settings.get("sts-sync-folder") or defaults.get("sts-sync-folder") or "").strip()

    def _sse_error(msg):
        return Response(
            f"data: {json.dumps({'phase': 'error', 'message': msg})}\n\n",
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if not sync_folder:
        return _sse_error("No sync folder configured. Set it in Settings.")

    sync_folder = os.path.normpath(sync_folder)
    dest_dir = os.path.join(sync_folder, "exports")

    if not os.path.isdir(sync_folder):
        return _sse_error(f"Sync folder does not exist: {sync_folder}")

    os.makedirs(dest_dir, exist_ok=True)

    # Collect video files first
    video_files = []
    if os.path.isdir(EXPORT_DIR):
        for root, _dirs, files in os.walk(EXPORT_DIR):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in VIDEO_EXTS:
                    video_files.append((os.path.join(root, fname), fname))

    def _sse():
        total = len(video_files)
        copied = 0
        skipped = 0

        for idx, (src_path, fname) in enumerate(video_files):
            dest_path = os.path.join(dest_dir, fname)
            src_size = os.path.getsize(src_path)

            # Skip duplicate (same name + size)
            if os.path.isfile(dest_path) and os.path.getsize(dest_path) == src_size:
                skipped += 1
                yield f"data: {json.dumps({'phase': 'skip', 'file': fname, 'index': idx + 1, 'total': total})}\n\n"
                continue

            # Emit start event
            yield f"data: {json.dumps({'phase': 'copying', 'file': fname, 'size': src_size, 'index': idx + 1, 'total': total})}\n\n"

            shutil.copy2(src_path, dest_path)
            copied += 1
            logger.info("Synced export: {} → {}", fname, dest_dir)

            yield f"data: {json.dumps({'phase': 'copied', 'file': fname, 'index': idx + 1, 'total': total})}\n\n"

        yield f"data: {json.dumps({'phase': 'done', 'copied': copied, 'skipped': skipped, 'total': total})}\n\n"

    return Response(_sse(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@compose_export_bp.route("/api/export/library/preview/<path:rel_path>", methods=["GET"])
def export_library_preview(rel_path):
    """Preview an exported video from output/exports."""
    try:
        abs_path = _resolve_export_relpath(rel_path)
    except ValueError:
        return jsonify({"error": "Invalid path"}), 400

    if not os.path.isfile(abs_path):
        return jsonify({"error": "File not found"}), 404

    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
        return jsonify({"error": "Unsupported preview format"}), 400

    mime = mimetypes.guess_type(abs_path)[0] or "video/mp4"
    return send_file(abs_path, mimetype=mime, as_attachment=False)


@compose_export_bp.route("/api/export/library/download/<path:rel_path>", methods=["GET"])
def export_library_download(rel_path):
    """Download a file from output/exports."""
    try:
        abs_path = _resolve_export_relpath(rel_path)
    except ValueError:
        return jsonify({"error": "Invalid path"}), 400

    if not os.path.isfile(abs_path):
        return jsonify({"error": "File not found"}), 404

    mime = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
    return send_file(abs_path, mimetype=mime, as_attachment=True, download_name=os.path.basename(abs_path))


@compose_export_bp.route("/api/export/<job_id>", methods=["DELETE"])
def cancel_export(job_id):
    """Cancel/cleanup an export job."""
    with _export_jobs_lock:
        job = _export_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    meta_path = os.path.splitext(job["output_path"])[0] + ".json"
    logger.info("Cancelling export job: {} (status={})", job_id[:8], job["status"])
    if job["status"] in ("queued", "processing"):
        job["status"] = "cancelled"
        job["message"] = "Cancellation requested"
        job["completed_at"] = time.time()
        if os.path.exists(job["output_path"]):
            try:
                os.remove(job["output_path"])
                logger.debug("Removed partial export file: {}", job["output_path"])
            except OSError as e:
                logger.warning("Could not remove partial export file: {}", e)
        if os.path.exists(meta_path):
            try:
                os.remove(meta_path)
            except OSError:
                pass
        return jsonify({"message": "Cancellation requested", "status": "cancelled"}), 202

    if os.path.exists(job["output_path"]):
        try:
            os.remove(job["output_path"])
            logger.debug("Removed export file: {}", job["output_path"])
        except OSError as e:
            logger.warning("Could not remove export file: {}", e)
    if os.path.exists(meta_path):
        try:
            os.remove(meta_path)
        except OSError:
            pass

    with _export_jobs_lock:
        _export_jobs.pop(job_id, None)
    return jsonify({"message": "Job cancelled and cleaned up"})


@compose_export_bp.route("/api/export/<job_id>/open-folder", methods=["POST"])
def open_export_folder(job_id):
    """Open the folder containing the exported video and select it."""
    with _export_jobs_lock:
        job = _export_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    output_path = os.path.abspath(job.get("output_path", ""))

    if not os.path.exists(output_path):
        output_path = EXPORT_DIR
        if not os.path.isdir(output_path):
            return jsonify({"error": "Output file not found"}), 404

    try:
        if platform.system() == "Windows":
            if os.path.isfile(output_path):
                subprocess.run(["explorer", "/select,", output_path], check=False)
            else:
                subprocess.run(["explorer", output_path], check=False)
        elif platform.system() == "Darwin":
            if os.path.isfile(output_path):
                subprocess.run(["open", "-R", output_path], check=False)
            else:
                subprocess.run(["open", output_path], check=False)
        else:
            folder = os.path.dirname(output_path) if os.path.isfile(output_path) else output_path
            subprocess.run(["xdg-open", folder], check=False)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error("Failed to open export folder: {}", e)
        return jsonify({"error": str(e)}), 500


@compose_export_bp.route("/api/export/jobs", methods=["GET"])
def list_export_jobs():
    """List all export jobs with their current status."""
    jobs = []
    with _export_jobs_lock:
        for jid, job in _export_jobs.items():
            jobs.append({
                "job_id": jid,
                "status": job["status"],
                "progress": job["progress"],
                "message": job["message"],
                "step": job.get("step"),
                "error": job["error"],
                "project_id": job.get("project_id"),
                "scene_count": job.get("scene_count"),
                "output_filename": job.get("output_filename"),
                "created_at": job.get("created_at"),
                "completed_at": job.get("completed_at"),
            })
    jobs.sort(key=lambda j: j.get("created_at") or 0, reverse=True)
    return jsonify(jobs)
