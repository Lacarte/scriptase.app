"""Music Module — Browse and manage background music tracks.

Two music sources, two URL formats:
  • Built-in library  → resources/sounds/music/<folder>/<file>
                      → /assets/sounds/music/<folder>/<file>
  • User uploads      → output/musics/<file>
                      → /output/musics/<file>

Both are returned in one unified list by /api/music/library so the editor's
music picker shows them together.
"""
import json
import os
import subprocess

from flask import Blueprint, jsonify, request, send_from_directory
from loguru import logger
from werkzeug.utils import secure_filename

from config import MUSIC_DIR, MUSIC_LIBRARY_DIR
from scriptase.shared.ffmpeg_utils import find_ffprobe

music_bp = Blueprint("music", __name__)

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}


def _get_duration(filepath):
    """Try to get audio duration using ffprobe (optional)."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", filepath],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return round(float(data.get("format", {}).get("duration", 0)), 2)
    except Exception:
        pass
    return None


@music_bp.route("/api/music/library")
def list_music():
    """List all music files — built-in library + user uploads.

    Each entry carries the URL format that matches its physical location:
      • Built-in (resources/sounds/music/<folder>/<file>)
        →  /assets/sounds/music/<folder>/<file>
      • User uploads (output/musics/<file>)
        →  /output/musics/<file>
    """
    files = []

    # ── Built-in music (one level deep, grouped by folder/category) ──
    if os.path.isdir(MUSIC_LIBRARY_DIR):
        for entry in sorted(os.listdir(MUSIC_LIBRARY_DIR)):
            folder = os.path.join(MUSIC_LIBRARY_DIR, entry)
            if not os.path.isdir(folder):
                continue
            for fname in sorted(os.listdir(folder)):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in ALLOWED_EXTENSIONS:
                    continue
                fpath = os.path.join(folder, fname)
                if not os.path.isfile(fpath):
                    continue
                size_mb = round(os.path.getsize(fpath) / (1024 * 1024), 1)
                files.append({
                    "filename": fname,
                    "path": f"/assets/sounds/music/{entry}/{fname}",
                    "category": entry,
                    "source": "builtin",
                    "size_mb": size_mb,
                    "duration": _get_duration(fpath),
                })

    # ── User uploads (flat directory) ──
    if os.path.isdir(MUSIC_DIR):
        for fname in sorted(os.listdir(MUSIC_DIR)):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            fpath = os.path.join(MUSIC_DIR, fname)
            if not os.path.isfile(fpath):
                continue
            size_mb = round(os.path.getsize(fpath) / (1024 * 1024), 1)
            files.append({
                "filename": fname,
                "path": f"/output/musics/{fname}",
                "category": "uploads",
                "source": "user",
                "size_mb": size_mb,
                "duration": _get_duration(fpath),
            })

    return jsonify(files)


@music_bp.route("/api/music/upload", methods=["POST"])
def upload_music():
    """Upload a music file to output/musics/ (the user-upload bucket)."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No filename"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported format: {ext}"}), 400

    fname = secure_filename(f.filename)
    os.makedirs(MUSIC_DIR, exist_ok=True)
    dest = os.path.join(MUSIC_DIR, fname)
    f.save(dest)
    logger.info("Music uploaded: {}", fname)

    size_mb = round(os.path.getsize(dest) / (1024 * 1024), 1)
    duration = _get_duration(dest)
    return jsonify({
        "filename": fname,
        "path": f"/output/musics/{fname}",
        "category": "uploads",
        "source": "user",
        "size_mb": size_mb,
        "duration": duration,
    })


@music_bp.route("/api/music/auto-select")
def auto_select_music():
    """Pick a random music track from the BUILT-IN library only.

    With a `tone` query param: tone-aware folder selection (e.g. suspenseful
    → dark/ambient/chill). Without a tone: fully random across every built-in
    folder. In both cases the pick comes from resources/sounds/music/ — never
    from user uploads in output/musics/.
    """
    story_tone = request.args.get("tone", "").strip()
    project_id = request.args.get("project_id", "").strip()

    from scriptase.modules.music.selector import (
        load_project_audio_history,
        persist_project_audio_history,
        select_music,
        select_random_music,
    )
    project_audio_history = load_project_audio_history(project_id) if project_id else {
        "music_history": [],
    }
    music_history = list(project_audio_history.get("music_history") or [])
    if story_tone:
        result = select_music(story_tone, history=music_history)
        if not result:
            # Tone had no matching folders — fall back to fully random
            # rather than failing the call.
            result = select_random_music(history=music_history)
    else:
        result = select_random_music(history=music_history)

    if not result:
        return jsonify({"error": "No built-in music available"}), 404

    if project_id:
        persist_project_audio_history(project_id, music_history=result.get("history"))

    # Convert absolute path to a servable /assets/... URL
    abs_path = result["path"]
    from config import APP_ASSETS_DIR
    if abs_path.startswith(APP_ASSETS_DIR):
        rel = abs_path[len(APP_ASSETS_DIR):].replace("\\", "/").lstrip("/")
        result["path"] = f"/assets/{rel}"
    result.pop("history", None)
    result["filename"] = os.path.basename(abs_path)
    return jsonify(result)


@music_bp.route("/output/musics/<path:filename>")
def serve_music(filename):
    """Serve user-uploaded music files for playback."""
    return send_from_directory(MUSIC_DIR, filename)
