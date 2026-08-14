"""SFX library listing.

Transport only. Split out of V2 ``studio/editor/routes.py`` in step 0.3.
"""

import json
import os
import re

from flask import Blueprint, jsonify

compose_sfx_bp = Blueprint("compose_sfx", __name__)


@compose_sfx_bp.route("/api/sfx/library")
def list_sfx():
    """List all sound effects from assets/sounds/sfx, grouped by folder category."""
    from config import APP_ASSETS_DIR
    from scriptase.shared.ffmpeg_utils import find_ffprobe
    sfx_dir = os.path.join(APP_ASSETS_DIR, "sounds", "sfx")
    ALLOWED = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}

    if not os.path.isdir(sfx_dir):
        return jsonify({"categories": []})

    ffprobe = find_ffprobe()

    def _probe_dur(fpath):
        if not ffprobe:
            return None
        try:
            import subprocess as sp
            r = sp.run([ffprobe, "-v", "quiet", "-print_format", "json",
                        "-show_format", fpath],
                       capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return round(float(json.loads(r.stdout).get("format", {}).get("duration", 0)), 2)
        except Exception:
            pass
        return None

    def _clean_label(fname):
        label = os.path.splitext(fname)[0].replace("-", " ").replace("_", " ")
        return re.sub(r'\s*\d{6,}$', '', label).strip()

    def _scan_folder(folder_path, url_prefix):
        items = []
        if not os.path.isdir(folder_path):
            return items
        for fname in sorted(os.listdir(folder_path)):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in ALLOWED or not os.path.isfile(os.path.join(folder_path, fname)):
                continue
            fpath = os.path.join(folder_path, fname)
            items.append({
                "filename": fname,
                "label": _clean_label(fname),
                "path": f"{url_prefix}/{fname}",
                "size_kb": round(os.path.getsize(fpath) / 1024, 1),
                "duration": _probe_dur(fpath),
            })
        return items

    categories = []

    # Root-level files → "General" category
    root_items = _scan_folder(sfx_dir, "/assets/sounds/sfx")
    if root_items:
        categories.append({"name": "General", "files": root_items})

    # Sub-folders → one category each
    for entry in sorted(os.listdir(sfx_dir)):
        sub = os.path.join(sfx_dir, entry)
        if not os.path.isdir(sub):
            continue
        items = _scan_folder(sub, f"/assets/sounds/sfx/{entry}")
        if items:
            cat_name = entry.replace("-", " ").replace("_", " ").title()
            categories.append({"name": cat_name, "files": items})

    return jsonify({"categories": categories})
