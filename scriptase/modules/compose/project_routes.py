"""Editor project save / load / list / reset and project discovery.

Transport only. Split out of V2 ``studio/editor/routes.py`` in step 0.3.
"""

import json
import os

from flask import Blueprint, jsonify
from loguru import logger

from config import PROJECTS_DIR, THUMBNAILS_DIR
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.shared.validation import validate_json
from scriptase.modules.compose.audio_service import (
    _materialize_history_audio_tracks,
    _merge_project_audio_history,
)
from scriptase.modules.compose.project_service import (
    INITIAL_FILENAME,
    WIP_FILENAME,
    _discover_projects,
    _get_source_folder,
    _get_story_tone,
    _initial_path,
    _project_dir,
    _resolve_project_audio,
    _resolve_project_captions,
    _wip_path,
)
from scriptase.modules.compose.schemas import EditorSaveRequest

compose_projects_bp = Blueprint("compose_projects", __name__)


# ---------------------------------------------------------------------------
# Editor project save / load
# ---------------------------------------------------------------------------

@compose_projects_bp.route("/api/editor/save", methods=["POST"])
@validate_json(EditorSaveRequest)
def editor_save_project(data: EditorSaveRequest):
    """Save editor project edits to both the work-in-progress and initial files."""
    safe_id = data.project_id  # already validated: alphanumeric + _ and -

    from datetime import datetime, timezone
    save_data = data.model_dump(exclude_none=True)
    source_folder = _get_source_folder(safe_id)
    if source_folder:
        save_data["source_folder"] = source_folder
        captions = save_data.get("captions")
        if isinstance(captions, dict) and not captions.get("source_folder"):
            captions["source_folder"] = source_folder
    _resolve_project_audio(save_data, safe_id)
    _resolve_project_captions(save_data, safe_id)
    _merge_project_audio_history(save_data, safe_id)
    save_data["saved_at"] = datetime.now(timezone.utc).isoformat()

    os.makedirs(_project_dir(safe_id), exist_ok=True)

    # Always write to the WIP file — initial state stays untouched
    # Mirror the latest saved editor state into both project files.
    initial = _initial_path(safe_id)
    wip = _wip_path(safe_id)
    try:
        safe_json_write(initial, save_data)
        safe_json_write(wip, save_data)
    except OSError as e:
        logger.error("Failed to save editor state for {}: {}", safe_id, e)
        return jsonify({"error": f"Failed to save: {e}"}), 500

    logger.info("Editor state saved to initial + WIP: {} ({} scenes)", safe_id, save_data.get("scene_count", "?"))
    return jsonify({"ok": True, "saved_at": save_data["saved_at"], "wip": True, "initial": True})


@compose_projects_bp.route("/api/editor/load/<project_id>", methods=["GET"])
def editor_load_project(project_id):
    """Load a saved editor project.

    Prefers the work-in-progress file if it exists, otherwise falls back to
    the initial project file.  The response includes a ``source``
    field (``"wip"`` or ``"initial"``) so the frontend knows which was loaded.
    """
    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))

    # Try WIP first, then initial
    wip = _wip_path(safe_id)
    initial = _initial_path(safe_id)
    source = "initial"

    if os.path.isfile(wip):
        path = wip
        source = "wip"
    elif os.path.isfile(initial):
        path = initial
    else:
        return jsonify({"error": "not found"}), 404

    try:
        data = safe_json_read(path)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load editor project {}: {}", safe_id, e)
        return jsonify({"error": f"Corrupted project file: {e}"}), 500

    data["_source"] = source

    # Inject source_folder so the frontend can scope captions/audio
    source_folder = _get_source_folder(safe_id)
    if source_folder:
        data["source_folder"] = source_folder

    # Inject story_tone from pipeline so the editor can auto-select animations
    story_tone = _get_story_tone(safe_id)
    if story_tone:
        data["story_tone"] = story_tone

    # Resolve correct audio from scenes.json source_folder to prevent
    # cross-project audio bleed (saved voice track may belong to another project).
    _resolve_project_audio(data, safe_id)
    _materialize_history_audio_tracks(data)

    # Resolve correct captions from the alignment folder
    _resolve_project_captions(data, safe_id)
    if data.get("captions"):
        if source == "initial":
            data["captionsEnabled"] = True
        elif data.get("captionsEnabled") is False and not data.get("edit_history"):
            data["captionsEnabled"] = True

    return jsonify(data)


@compose_projects_bp.route("/api/editor/projects", methods=["GET"])
def editor_list_projects():
    """List all saved editor projects from per-project subdirectories."""
    seen_ids = set()
    projects = []

    def _collect_from_dir(proj_dir, pid):
        """Read project metadata from an editor subdirectory."""
        if pid in seen_ids:
            return
        wip = os.path.join(proj_dir, WIP_FILENAME)
        initial = os.path.join(proj_dir, INITIAL_FILENAME)
        has_wip = os.path.isfile(wip)
        fpath = wip if has_wip else initial
        if not os.path.isfile(fpath):
            return
        try:
            data = safe_json_read(fpath)
            seen_ids.add(pid)
            # Look up thumbnail preview
            preview = None
            thumb_base = os.path.join(THUMBNAILS_DIR, pid)
            editor_cover = os.path.join(thumb_base, "editor", "cover.jpg")
            assets_thumb_0 = os.path.join(thumb_base, "assets", "0.jpg")
            if os.path.isfile(editor_cover):
                preview = f"/api/thumbnails/{pid}/editor/cover.jpg"
            elif os.path.isfile(assets_thumb_0):
                preview = f"/api/thumbnails/{pid}/assets/0.jpg"
            projects.append({
                "project_id": data.get("project_id", pid),
                "project_name": data.get("project_name", ""),
                "saved_at": data.get("saved_at", ""),
                "scene_count": data.get("scene_count", 0),
                "total_duration": data.get("total_duration", 0),
                "has_wip": has_wip,
                "preview": preview,
            })
        except Exception as error:
            logger.debug("Skipping project manifest {}: {}", fpath, error)

    if os.path.isdir(PROJECTS_DIR):
        for entry in os.listdir(PROJECTS_DIR):
            proj_dir = os.path.join(PROJECTS_DIR, entry)
            if os.path.isdir(proj_dir):
                _collect_from_dir(proj_dir, entry)

    projects.sort(key=lambda p: p.get("saved_at", ""), reverse=True)
    return jsonify(projects)


@compose_projects_bp.route("/api/projects", methods=["GET"])
def list_all_projects():
    """Discover and list all projects across output directories."""
    projects = _discover_projects()
    return jsonify(projects)


@compose_projects_bp.route("/api/editor/reset/<project_id>", methods=["POST"])
def editor_reset_to_initial(project_id):
    """Delete the WIP file and fall back to the mirrored initial project file."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))


    initial = _initial_path(safe_id)
    if not os.path.isfile(initial):
        return jsonify({"error": "No initial state found"}), 404

    wip = _wip_path(safe_id)
    deleted = False
    if os.path.isfile(wip):
        os.remove(wip)
        deleted = True
        logger.info("WIP file deleted for project {}", safe_id)

    return jsonify({"ok": True, "deleted_wip": deleted})
