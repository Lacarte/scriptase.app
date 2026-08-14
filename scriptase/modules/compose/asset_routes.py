"""Overlay and font listings for the editor.

Transport only. Split out of V2 ``studio/editor/routes.py`` in step 0.3.
"""

import os

from flask import Blueprint, jsonify
from loguru import logger

from config import APP_ASSETS_DIR
from scriptase.shared.fonts import FONT_REGISTRY, get_font_url

compose_assets_bp = Blueprint("compose_assets", __name__)

OVERLAYS_DIR = os.path.join(APP_ASSETS_DIR, "overlays")


@compose_assets_bp.route("/api/editor/overlays", methods=["GET"])
def list_overlays():
    """List available overlay PNGs from assets/overlays/."""
    overlays = []
    if os.path.isdir(OVERLAYS_DIR):
        for f in sorted(os.listdir(OVERLAYS_DIR)):
            if f.lower().endswith(".png"):
                name = os.path.splitext(f)[0]
                overlays.append({"name": name, "file": f, "url": f"/assets/overlays/{f}"})
    return jsonify(overlays)


# ---------------------------------------------------------------------------
# Font API
# ---------------------------------------------------------------------------

SYSTEM_FONTS = [
    'Arial', 'Helvetica', 'Georgia', 'Times New Roman', 'Verdana',
    'Trebuchet MS', 'Impact', 'Comic Sans MS', 'Courier New',
]


@compose_assets_bp.route("/api/fonts", methods=["GET"])
def list_fonts():
    """Return combined list of custom + system fonts."""
    fonts = []

    # Custom fonts from registry
    for family, entry in sorted(FONT_REGISTRY.items()):
        variants = {}
        for variant, abs_path in entry['variants'].items():
            variants[variant] = get_font_url(abs_path)
        fonts.append({
            'family': family,
            'source': 'custom',
            'variants': variants,
        })

    # System fonts (no variant URLs — browser resolves them)
    for family in SYSTEM_FONTS:
        fonts.append({
            'family': family,
            'source': 'system',
            'variants': {},
        })

    logger.debug("Font API: {} custom + {} system fonts", len(FONT_REGISTRY), len(SYSTEM_FONTS))
    return jsonify(fonts)
