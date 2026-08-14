"""Project ZIP export / import and the OS folder opener.

Transport only. Business logic lives in ``project_zip_service`` (step 10.1
extracted the ZIP path so V2 import can share it without importing routes).
"""

import io
import os
import platform
import subprocess

from flask import Blueprint, jsonify, request, send_file
from loguru import logger

from config import ANIMATOR_DIR, SCENES_DIR
from scriptase.modules.compose.project_zip_service import (
    ProjectZipError,
    export_project_zip as export_project_zip_bytes,
    import_project_zip as import_project_zip_bytes,
)

compose_archive_bp = Blueprint("compose_archive", __name__)


@compose_archive_bp.route("/api/editor/export-zip/<project_id>", methods=["GET"])
def export_project_zip(project_id):
    """Bundle a complete project into a downloadable ZIP file."""
    try:
        result = export_project_zip_bytes(project_id)
    except ProjectZipError as exc:
        status = 404 if exc.code == "PROJECT_NOT_FOUND" else 400
        return jsonify({"error": str(exc)}), status

    return send_file(
        io.BytesIO(result.data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=result.filename,
    )


@compose_archive_bp.route("/api/editor/import-zip", methods=["POST"])
def import_project_zip():
    """Import a project from an uploaded ZIP file."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    zfile = request.files["file"]
    if not zfile.filename or not zfile.filename.lower().endswith(".zip"):
        return jsonify({"error": "File must be a .zip"}), 400

    try:
        result = import_project_zip_bytes(zfile.read())
    except ProjectZipError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error("ZIP import failed: {}", exc)
        return jsonify({"error": str(exc)}), 500

    payload = {
        "project_id": result.project_id,
        "imported_files": result.imported_files,
        "source_folder": result.source_folder,
    }
    if result.renamed_from:
        payload["renamed_from"] = result.renamed_from
    return jsonify(payload)


@compose_archive_bp.route("/api/editor/open-folder/<project_id>", methods=["POST"])
def open_project_folder(project_id):
    """Open the project's assets folder in the OS file explorer."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))

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
