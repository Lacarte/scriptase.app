"""Captions Module — Load caption presets and project data."""

import json
import os

from flask import Blueprint, jsonify

from config import CAPTIONS_DIR
from .presets import CAPTION_PRESETS

captions_bp = Blueprint("captions", __name__)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@captions_bp.route("/api/captions/presets")
def get_presets():
    """Return all available caption style presets."""
    return jsonify(list(CAPTION_PRESETS.values()))


@captions_bp.route("/api/captions/<project_id>")
def get_captions(project_id):
    """Get full caption data for a project."""
    project_id = os.path.basename(project_id)
    json_path = os.path.join(CAPTIONS_DIR, project_id, "captions.json")
    if os.path.isfile(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                return jsonify(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            return jsonify({"error": f"Failed to read caption data: {e}"}), 500

    # Fallback: build captions from alignment data
    from config import ALIGN_DIR
    align_path = os.path.join(ALIGN_DIR, project_id, "alignment.json")
    if os.path.isfile(align_path):
        try:
            with open(align_path, encoding="utf-8") as f:
                align = json.load(f)
            words = align.get("alignment", [])
            if words:
                return jsonify({
                    "project_id": project_id,
                    "source_folder": project_id,
                    "words": [
                        {"word": w["word"], "start": w.get("begin", 0), "end": w.get("end", 0)}
                        for w in words
                    ],
                    "transcript": align.get("transcript", ""),
                    "from_alignment": True,
                })
        except Exception:
            pass

    return jsonify({"error": "Not found"}), 404
