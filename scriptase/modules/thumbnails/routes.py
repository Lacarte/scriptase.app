"""Thumbnails Module — Generate and serve per-project thumbnails.

Structure:
  output/thumbnails/{project_id}/
    ├── assets/       (one thumb per scene asset video/image)
    ├── exports/      (one thumb per exported video)
    └── editor/       (cover thumb from first editor scene)

Routes:
  POST /api/thumbnails/<project_id>/generate  — generate all thumbnails for a project
  GET  /api/thumbnails/<project_id>           — list available thumbnails
  GET  /api/thumbnails/<project_id>/<module>/<filename> — serve a thumbnail file
"""

import os
import re
import subprocess

from flask import Blueprint, jsonify, request, send_file
from loguru import logger

from config import THUMBNAILS_DIR, ANIMATOR_DIR, EXPORT_DIR, PROJECTS_DIR
from scriptase.shared.ffmpeg_utils import find_ffmpeg
from scriptase.shared.io_utils import safe_json_read
thumbnails_bp = Blueprint("thumbnails", __name__)

THUMB_SIZE = "480:-1"  # width 480, auto height
THUMB_QUALITY = "4"    # ffmpeg jpeg quality (2=best, 31=worst)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_id(project_id: str) -> str:
    return "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))


def _extract_thumb(src_path: str, dest_path: str, ffmpeg: str) -> bool:
    """Extract a single thumbnail from a video or copy/resize an image."""
    if not os.path.isfile(src_path):
        return False

    ext = os.path.splitext(src_path)[1].lower()
    video_exts = (".mp4", ".webm", ".mov", ".mkv", ".m4v")
    image_exts = (".jpg", ".jpeg", ".png", ".webp")

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    try:
        if ext in video_exts:
            subprocess.run(
                [ffmpeg, "-y", "-i", src_path, "-map", "0:v:0",
                 "-vframes", "1", "-ss", "0.1",
                 "-vf", f"scale={THUMB_SIZE}",
                 "-q:v", THUMB_QUALITY, dest_path],
                capture_output=True, timeout=15,
            )
        elif ext in image_exts:
            subprocess.run(
                [ffmpeg, "-y", "-i", src_path,
                 "-vf", f"scale={THUMB_SIZE}",
                 "-q:v", THUMB_QUALITY, dest_path],
                capture_output=True, timeout=15,
            )
        else:
            return False

        return os.path.isfile(dest_path)
    except Exception as e:
        logger.debug("Thumbnail extraction failed for {}: {}", src_path, e)
        return False


def _project_thumb_dir(project_id: str, module: str) -> str:
    return os.path.join(THUMBNAILS_DIR, project_id, module)


# ---------------------------------------------------------------------------
# Generators per module
# ---------------------------------------------------------------------------

def _generate_assets_thumbs(project_id: str, ffmpeg: str, force: bool = False) -> dict:
    """Generate thumbnails from scene assets (output/animator/{project_id}/{scene}/)."""
    asset_root = os.path.join(ANIMATOR_DIR, project_id)
    thumb_dir = _project_thumb_dir(project_id, "assets")
    video_exts = (".mp4", ".webm", ".mov", ".mkv", ".m4v")
    media_exts = video_exts + (".jpg", ".jpeg", ".png", ".webp")
    results = {"generated": 0, "skipped": 0, "errors": 0}

    if not os.path.isdir(asset_root):
        return results

    for scene_name in sorted(os.listdir(asset_root)):
        scene_dir = os.path.join(asset_root, scene_name)
        if not os.path.isdir(scene_dir) or not scene_name.isdigit():
            continue

        dest = os.path.join(thumb_dir, f"{scene_name}.jpg")
        if not force and os.path.isfile(dest):
            results["skipped"] += 1
            continue

        # Pick best source: prefer video over image, newest first
        files = []
        for fname in os.listdir(scene_dir):
            fpath = os.path.join(scene_dir, fname)
            if os.path.isfile(fpath) and fname.lower().endswith(media_exts):
                files.append((os.path.getmtime(fpath), fname, fpath))

        if not files:
            continue

        video_files = [(t, n, p) for t, n, p in files if n.lower().endswith(video_exts)]
        pick = max(video_files) if video_files else max(files)
        _, _, src_path = pick

        if _extract_thumb(src_path, dest, ffmpeg):
            results["generated"] += 1
        else:
            results["errors"] += 1

    return results


def _generate_exports_thumbs(project_id: str, ffmpeg: str, force: bool = False) -> dict:
    """Generate thumbnails from exported videos matching this project."""
    thumb_dir = _project_thumb_dir(project_id, "exports")
    video_exts = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    results = {"generated": 0, "skipped": 0, "errors": 0}

    if not os.path.isdir(EXPORT_DIR):
        return results

    for root, _dirs, files in os.walk(EXPORT_DIR):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in video_exts:
                continue

            # Check if this export belongs to this project
            base = os.path.splitext(fname)[0]
            match = re.match(r"^(?P<project>.+?)_[0-9a-fA-F]{8}$", base)
            file_pid = match.group("project") if match else base
            if file_pid != project_id:
                continue

            dest = os.path.join(thumb_dir, f"{base}.jpg")
            if not force and os.path.isfile(dest):
                results["skipped"] += 1
                continue

            src_path = os.path.join(root, fname)
            if _extract_thumb(src_path, dest, ffmpeg):
                results["generated"] += 1
            else:
                results["errors"] += 1

    return results


def _generate_editor_thumb(project_id: str, ffmpeg: str, force: bool = False) -> dict:
    """Generate a cover thumbnail from the first editor scene."""
    thumb_dir = _project_thumb_dir(project_id, "editor")
    dest = os.path.join(thumb_dir, "cover.jpg")
    results = {"generated": 0, "skipped": 0, "errors": 0}

    if not force and os.path.isfile(dest):
        results["skipped"] = 1
        return results

    # Try WIP first, then initial
    wip = os.path.join(PROJECTS_DIR, project_id, "work@in@progress.json")
    initial = os.path.join(PROJECTS_DIR, project_id, "initial.json")
    project_file = wip if os.path.isfile(wip) else initial

    if not os.path.isfile(project_file):
        return results

    try:
        data = safe_json_read(project_file)
    except Exception:
        return results

    scenes = data.get("scenes", [])
    if not scenes:
        return results

    # Find first scene with a media URL
    for scene in scenes:
        media_url = scene.get("mediaUrl") or scene.get("image_url") or ""
        if not media_url:
            continue

        # Resolve URL to absolute path
        # URLs like /output/animator/pp_XXX/0/file.mp4
        if media_url.startswith("/output/"):
            from config import OUTPUT_DIR
            src_path = os.path.join(OUTPUT_DIR, media_url[len("/output/"):].replace("/", os.sep))
        elif media_url.startswith("working-assets/"):
            from config import ROOT_DIR
            src_path = os.path.join(ROOT_DIR, media_url.replace("/", os.sep))
        else:
            continue

        if _extract_thumb(src_path, dest, ffmpeg):
            results["generated"] = 1
            return results

    results["errors"] = 1
    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@thumbnails_bp.route("/api/thumbnails/<project_id>/generate", methods=["POST"])
def generate_thumbnails(project_id):
    """Generate thumbnails for a project across all modules.

    Query params:
      ?modules=assets,exports,editor  (comma-separated, default all)
      ?force=1                        (regenerate existing thumbnails)
    """
    safe_id = _safe_id(project_id)
    if not safe_id:
        return jsonify({"error": "Invalid project ID"}), 400

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return jsonify({"error": "ffmpeg not found"}), 500

    force = request.args.get("force", "0") == "1"
    modules_param = request.args.get("modules", "assets,exports,editor")
    modules = [m.strip() for m in modules_param.split(",") if m.strip()]

    report = {}
    generators = {
        "assets": _generate_assets_thumbs,
        "exports": _generate_exports_thumbs,
        "editor": _generate_editor_thumb,
    }

    for mod in modules:
        gen = generators.get(mod)
        if gen:
            report[mod] = gen(safe_id, ffmpeg, force=force)

    total_gen = sum(r.get("generated", 0) for r in report.values())
    total_skip = sum(r.get("skipped", 0) for r in report.values())
    total_err = sum(r.get("errors", 0) for r in report.values())

    logger.info("Thumbnails for {}: {} generated, {} skipped, {} errors",
                safe_id, total_gen, total_skip, total_err)

    return jsonify({
        "project_id": safe_id,
        "modules": report,
        "total_generated": total_gen,
        "total_skipped": total_skip,
        "total_errors": total_err,
    })


@thumbnails_bp.route("/api/thumbnails/<project_id>", methods=["GET"])
def list_thumbnails(project_id):
    """List all generated thumbnails for a project."""
    safe_id = _safe_id(project_id)
    proj_dir = os.path.join(THUMBNAILS_DIR, safe_id)

    if not os.path.isdir(proj_dir):
        return jsonify({"project_id": safe_id, "modules": {}})

    modules = {}
    for mod_name in sorted(os.listdir(proj_dir)):
        mod_dir = os.path.join(proj_dir, mod_name)
        if not os.path.isdir(mod_dir):
            continue
        thumbs = []
        for fname in sorted(os.listdir(mod_dir)):
            fpath = os.path.join(mod_dir, fname)
            if os.path.isfile(fpath) and fname.lower().endswith((".jpg", ".jpeg", ".png")):
                thumbs.append({
                    "filename": fname,
                    "url": f"/api/thumbnails/{safe_id}/{mod_name}/{fname}",
                    "size_bytes": os.path.getsize(fpath),
                })
        if thumbs:
            modules[mod_name] = thumbs

    return jsonify({"project_id": safe_id, "modules": modules})


@thumbnails_bp.route("/api/thumbnails/<project_id>/<module>/<filename>", methods=["GET"])
def serve_thumbnail(project_id, module, filename):
    """Serve a specific thumbnail file."""
    safe_id = _safe_id(project_id)
    safe_mod = "".join(c for c in module if c.isalnum() or c in ("_", "-"))
    safe_name = os.path.basename(filename)

    thumb_path = os.path.join(THUMBNAILS_DIR, safe_id, safe_mod, safe_name)
    if not os.path.isfile(thumb_path):
        return jsonify({"error": "Thumbnail not found"}), 404

    return send_file(thumb_path, mimetype="image/jpeg")

