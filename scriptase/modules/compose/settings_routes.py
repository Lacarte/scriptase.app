"""App settings, the native folder picker, and the frontend log relay.

Transport only. Split out of V2 ``studio/editor/routes.py`` in step 0.3.
"""

import os

from flask import Blueprint, jsonify, request
from loguru import logger

from scriptase.modules.compose.settings_service import _read_app_config, _write_app_config

compose_settings_bp = Blueprint("compose_settings", __name__)


@compose_settings_bp.route("/api/settings", methods=["GET"])
def get_settings():
    """Return user settings from app-config.json['user'].

    Step 16.1: the three retired provider-selection keys never leave this
    endpoint — ``settings.json`` is the only selection store.
    """
    from scriptase.providers.compatibility import strip_legacy_selection_keys

    cfg = _read_app_config()
    return jsonify(strip_legacy_selection_keys(cfg.get("user", {})))


@compose_settings_bp.route("/api/settings", methods=["PUT"])
def put_settings():
    """Replace all user settings in app-config.json['user']."""
    from scriptase.providers.compatibility import strip_legacy_selection_keys

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected JSON object"}), 400
    cfg = _read_app_config()
    cfg["user"] = strip_legacy_selection_keys(data)
    _write_app_config(cfg)
    return jsonify({"ok": True})


@compose_settings_bp.route("/api/settings", methods=["PATCH"])
def patch_settings():
    """Merge partial updates into app-config.json['user']."""
    from scriptase.providers.compatibility import (
        LEGACY_SELECTION_KEYS,
        strip_legacy_selection_keys,
    )

    patch = request.get_json(silent=True)
    if not isinstance(patch, dict):
        return jsonify({"error": "Expected JSON object"}), 400
    # Silently drop attempts to write the retired selection keys so a stale
    # mirror or an old client cannot reintroduce them.
    patch = {k: v for k, v in patch.items() if k not in LEGACY_SELECTION_KEYS}
    cfg = _read_app_config()
    user = dict(cfg.get("user", {}) or {})
    user.update(patch)
    cfg["user"] = strip_legacy_selection_keys(user)
    _write_app_config(cfg)
    return jsonify({"ok": True})


@compose_settings_bp.route("/api/settings", methods=["DELETE"])
def delete_settings():
    """Reset user settings in app-config.json."""
    cfg = _read_app_config()
    cfg["user"] = {}
    _write_app_config(cfg)
    return jsonify({"ok": True})


# `/api/settings/v2` and the whole `/api/providers/*` surface moved to the
# provider blueprint (`scriptase/providers/routes.py`) in step 11.5. The URLs did
# not change — only the owning module — so no consumer needed an edit.


@compose_settings_bp.route("/api/settings/browse-folder", methods=["POST"])
def browse_folder():
    """Open a native folder picker dialog and return the selected path."""
    import tkinter as tk
    from tkinter import filedialog

    data = request.get_json(silent=True) or {}
    initial_dir = data.get("initial", "")

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    folder = filedialog.askdirectory(
        title="Select Sync Folder",
        initialdir=initial_dir if initial_dir and os.path.isdir(initial_dir) else None,
    )
    root.destroy()

    if not folder:
        return jsonify({"cancelled": True})
    return jsonify({"path": folder.replace("\\", "/")})


# ---------------------------------------------------------------------------
# Frontend log relay — POST /api/log
# ---------------------------------------------------------------------------

@compose_settings_bp.route("/api/log", methods=["POST"])
def frontend_log():
    """Receive log messages from the frontend and emit via loguru."""
    data = request.get_json(silent=True) or {}
    level = (data.get("level") or "info").upper()
    msg = data.get("message", "")
    ctx = data.get("context", "")
    source = data.get("source", "frontend")

    tag = f"[{source}]"
    full = f"{tag} {msg}" + (f" | {ctx}" if ctx else "")

    if level == "ERROR":
        logger.error(full)
    elif level == "WARNING" or level == "WARN":
        logger.warning(full)
    elif level == "DEBUG":
        logger.debug(full)
    else:
        logger.info(full)

    return jsonify({"ok": True})
