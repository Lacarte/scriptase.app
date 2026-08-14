"""Project ZIP export / import and the OS folder opener.

Transport only. Split out of V2 ``studio/editor/routes.py`` in step 0.3.
"""

import io
import json
import os
import platform
import subprocess
import zipfile

from flask import Blueprint, jsonify, request, send_file
from loguru import logger

from config import ALIGN_DIR, ANIMATOR_DIR, SCENES_DIR, TTS_DIR
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.shared.security import safe_join, sanitize_folder_name, sanitize_project_id
from scriptase.modules.compose.project_service import (
    _get_source_folder,
    _initial_path,
    _project_dir,
    _wip_path,
)
from scriptase.modules.compose.schemas import EditorSaveRequest

compose_archive_bp = Blueprint("compose_archive", __name__)


# ---------------------------------------------------------------------------
# Project ZIP export
# ---------------------------------------------------------------------------

@compose_archive_bp.route("/api/editor/export-zip/<project_id>", methods=["GET"])
def export_project_zip(project_id):
    """Bundle a complete project into a downloadable ZIP file."""
    from datetime import datetime, timezone

    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))


    # Prefer WIP file, then initial state, then scenes.json
    wip_file = _wip_path(safe_id)
    initial_file = _initial_path(safe_id)
    editor_path = wip_file if os.path.isfile(wip_file) else initial_file
    scenes_path = os.path.join(SCENES_DIR, safe_id, "scenes.json")
    if not os.path.isfile(editor_path) and not os.path.isfile(scenes_path):
        return jsonify({"error": "Project not found"}), 404

    source_folder = _get_source_folder(safe_id)
    manifest = {
        "project_id": safe_id,
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_folder": source_folder or "",
        "files": [],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        prefix = f"{safe_id}/"

        # 1) Editor save JSON
        if os.path.isfile(editor_path):
            zf.write(editor_path, f"{prefix}project.json")
            manifest["files"].append("project.json")

        # 2) Scenes JSON
        if os.path.isfile(scenes_path):
            zf.write(scenes_path, f"{prefix}scenes.json")
            manifest["files"].append("scenes.json")

        # 3) Assets — all media files under output/animator/{project_id}/
        assets_dir = os.path.join(ANIMATOR_DIR, safe_id)
        if os.path.isdir(assets_dir):
            for root, _dirs, files in os.walk(assets_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, assets_dir).replace("\\", "/")
                    arc_name = f"{prefix}assets/{rel}"
                    zf.write(fpath, arc_name)
                    manifest["files"].append(f"assets/{rel}")

        # 4) Audio — alignment files
        if source_folder:
            align_dir = os.path.join(ALIGN_DIR, source_folder)
            if os.path.isdir(align_dir):
                try:
                    for fname in os.listdir(align_dir):
                        fpath = os.path.join(align_dir, fname)
                        if os.path.isfile(fpath):
                            zf.write(fpath, f"{prefix}audio/{fname}")
                            manifest["files"].append(f"audio/{fname}")
                except OSError:
                    pass

            # 5) TTS files
            tts_dir = os.path.join(TTS_DIR, source_folder)
            if os.path.isdir(tts_dir):
                try:
                    for fname in os.listdir(tts_dir):
                        fpath = os.path.join(tts_dir, fname)
                        if os.path.isfile(fpath):
                            zf.write(fpath, f"{prefix}tts/{fname}")
                            manifest["files"].append(f"tts/{fname}")
                except OSError:
                    pass

        # 6) Manifest
        zf.writestr(f"{prefix}manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    logger.info("Project ZIP exported: {} ({} files, {:.1f} MB)",
                safe_id, len(manifest["files"]), buf.getbuffer().nbytes / 1024 / 1024)

    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{safe_id}.zip",
    )


def _coerce_imported_editor_project(raw_bytes: bytes, project_id: str, renamed_from: str | None = None) -> dict:
    """Validate and normalize imported editor project payload before saving."""
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid project.json payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid project.json payload: expected JSON object")

    payload["project_id"] = project_id
    project_name = str(payload.get("project_name", "") or "").strip()
    if not project_name or (renamed_from and project_name == renamed_from):
        payload["project_name"] = project_id

    EditorSaveRequest.model_validate(payload)
    return payload


@compose_archive_bp.route("/api/editor/import-zip", methods=["POST"])
def import_project_zip():
    """Import a project from an uploaded ZIP file."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    zfile = request.files["file"]
    if not zfile.filename or not zfile.filename.lower().endswith(".zip"):
        return jsonify({"error": "File must be a .zip"}), 400

    try:
        data = zfile.read()
        zio = io.BytesIO(data)
        with zipfile.ZipFile(zio, "r") as zf:
            names = zf.namelist()
            if not names:
                return jsonify({"error": "ZIP is empty"}), 400

            # Detect project_id from manifest or top-level folder
            project_id = None
            manifest = None
            for n in names:
                if n.endswith("manifest.json"):
                    manifest = json.loads(zf.read(n))
                    project_id = manifest.get("project_id")
                    break
            if not project_id:
                # Infer from first path component
                project_id = names[0].split("/")[0]

            safe_id = sanitize_project_id(project_id)
            if not safe_id:
                return jsonify({"error": "Cannot determine project ID from ZIP"}), 400

            # Validate: ZIP must contain at least scenes.json or project.json
            has_scenes = any(n.endswith("scenes.json") for n in names)
            has_project = any(n.endswith("project.json") for n in names)
            if not has_scenes and not has_project:
                return jsonify({"error": "Invalid project ZIP: missing scenes.json and project.json"}), 400

            # Handle duplicate project IDs — append -2, -3, etc.
            original_id = safe_id
            renamed_from = None
            scenes_dir_check = os.path.join(SCENES_DIR, safe_id)
            editor_dir_check = _project_dir(safe_id)
            if os.path.exists(scenes_dir_check) or os.path.isdir(editor_dir_check):
                suffix = 2
                while True:
                    candidate = f"{original_id}-{suffix}"
                    if not os.path.exists(os.path.join(SCENES_DIR, candidate)) and \
                       not os.path.isdir(_project_dir(candidate)):
                        renamed_from = safe_id
                        safe_id = candidate
                        break
                    suffix += 1
                logger.info("Project {} already exists, renamed to {}", original_id, safe_id)

            source_folder = sanitize_folder_name(manifest.get("source_folder", "") if manifest else "")
            prefix = f"{original_id}/"

            # Extract each file to its correct output location
            imported = []
            for name in names:
                if name.endswith("/"):
                    continue  # skip directories

                # Strip the project prefix to get relative path
                rel = name[len(prefix):] if name.startswith(prefix) else name
                raw = zf.read(name)

                if rel == "project.json":
                    proj_dir = _project_dir(safe_id)
                    os.makedirs(proj_dir, exist_ok=True)
                    try:
                        project_payload = _coerce_imported_editor_project(
                            raw,
                            safe_id,
                            renamed_from=renamed_from,
                        )
                    except ValueError as exc:
                        return jsonify({"error": str(exc)}), 400
                    dest = _initial_path(safe_id)
                    safe_json_write(dest, project_payload, indent=2)
                    imported.append(rel)

                elif rel == "scenes.json":
                    dest_dir = os.path.join(SCENES_DIR, safe_id)
                    os.makedirs(dest_dir, exist_ok=True)
                    with open(os.path.join(dest_dir, "scenes.json"), "wb") as f:
                        f.write(raw)
                    imported.append(rel)

                elif rel.startswith("assets/"):
                    sub = rel[len("assets/"):]
                    try:
                        dest = safe_join(os.path.join(ANIMATOR_DIR, safe_id), sub)
                    except ValueError:
                        return jsonify({"error": "Invalid ZIP path in assets"}), 400
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(raw)
                    imported.append(rel)

                elif rel.startswith("audio/") and source_folder:
                    sub = rel[len("audio/"):]
                    try:
                        dest = safe_join(os.path.join(ALIGN_DIR, source_folder), sub)
                    except ValueError:
                        return jsonify({"error": "Invalid ZIP path in audio"}), 400
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(raw)
                    imported.append(rel)

                elif rel.startswith("tts/") and source_folder:
                    sub = rel[len("tts/"):]
                    try:
                        dest = safe_join(os.path.join(TTS_DIR, source_folder), sub)
                    except ValueError:
                        return jsonify({"error": "Invalid ZIP path in tts"}), 400
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(raw)
                    imported.append(rel)

            # If renamed, update project_id inside scenes.json and project.json
            if renamed_from:
                scenes_json_path = os.path.join(SCENES_DIR, safe_id, "scenes.json")
                if os.path.exists(scenes_json_path):
                    try:
                        sdata = safe_json_read(scenes_json_path)
                        sdata["project_id"] = safe_id
                        safe_json_write(scenes_json_path, sdata, indent=2)
                    except Exception as error:
                        logger.debug("Could not update imported scenes.json {}: {}", scenes_json_path, error)
                editor_json_path = _initial_path(safe_id)
                if os.path.exists(editor_json_path):
                    try:
                        edata = safe_json_read(editor_json_path)
                        edata["project_id"] = safe_id
                        project_name = str(edata.get("project_name", "") or "").strip()
                        if not project_name or project_name == renamed_from:
                            edata["project_name"] = safe_id
                        EditorSaveRequest.model_validate(edata)
                        safe_json_write(editor_json_path, edata, indent=2)
                    except Exception as error:
                        logger.debug("Could not update imported editor manifest {}: {}", editor_json_path, error)

            logger.info("Project ZIP imported: {} ({} files){}", safe_id, len(imported),
                        f" (renamed from {renamed_from})" if renamed_from else "")
            result = {
                "project_id": safe_id,
                "imported_files": len(imported),
                "source_folder": source_folder,
            }
            if renamed_from:
                result["renamed_from"] = renamed_from
            return jsonify(result)

    except zipfile.BadZipFile:
        return jsonify({"error": "Invalid ZIP file"}), 400
    except Exception as e:
        logger.error("ZIP import failed: {}", e)
        return jsonify({"error": str(e)}), 500


@compose_archive_bp.route("/api/editor/open-folder/<project_id>", methods=["POST"])
def open_project_folder(project_id):
    """Open the project's assets folder in the OS file explorer."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))

    # Try assets dir first, then editor save dir
    folder = os.path.join(ANIMATOR_DIR, safe_id)
    if not os.path.isdir(folder):
        folder = os.path.join(SCENES_DIR, safe_id)
    if not os.path.isdir(folder):
        return jsonify({"error": "Project folder not found"}), 404

    folder = os.path.abspath(folder)
    try:
        if platform.system() == "Windows":
            subprocess.run(["explorer", folder], check=False)
        elif platform.system() == "Darwin":
            subprocess.run(["open", folder], check=False)
        else:
            subprocess.run(["xdg-open", folder], check=False)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error("Failed to open project folder: {}", e)
        return jsonify({"error": str(e)}), 500
