"""HTTP transport for V2 import (step 10.1).

Loopback-only: import rewrites settings and workflows and may write secrets
into the machine-local secret store. Never expose on a non-loopback bind.
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from scriptase.migration.v2 import (
    V2ImportError,
    export_project,
    import_project_from_zip,
    import_settings,
    import_v2_root,
    import_workflow,
    migrate_settings_document,
    migrate_workflow_document,
    validate_migrated_workflow,
)
from scriptase.shared.security import is_loopback_remote

migration_bp = Blueprint("migration", __name__)


def _require_loopback():
    if not is_loopback_remote(request.remote_addr):
        return jsonify({
            "error": {
                "code": "FORBIDDEN",
                "message": "Migration endpoints are loopback-only",
            }
        }), 403
    return None


def _error(code: str, message: str, status: int = 400):
    return jsonify({"error": {"code": code, "message": message}}), status


@migration_bp.route("/api/migration/v2/preview/settings", methods=["POST"])
def preview_settings():
    """Rewrite a settings document in memory; do not write."""
    denied = _require_loopback()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    document = body.get("settings")
    if not isinstance(document, dict):
        return _error("BAD_REQUEST", "settings must be an object")
    try:
        migrated, changed = migrate_settings_document(document, body.get("legacy_user"))
    except V2ImportError as exc:
        return _error(exc.code, str(exc))
    return jsonify({
        "settings": migrated,
        "changed": changed,
        "version": migrated.get("version"),
    })


@migration_bp.route("/api/migration/v2/preview/workflow", methods=["POST"])
def preview_workflow():
    """Migrate + validate a workflow in memory; do not write."""
    denied = _require_loopback()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    document = body.get("workflow")
    if not isinstance(document, dict):
        return _error("BAD_REQUEST", "workflow must be an object")
    try:
        state = migrate_workflow_document(document)
    except V2ImportError as exc:
        return _error(exc.code, str(exc))
    errors = validate_migrated_workflow(state.document)
    return jsonify({
        "workflow": state.document,
        "migration_trail": state.trail,
        "read_only": state.read_only,
        "validation_errors": errors,
        "valid": not errors and not state.read_only,
    })


@migration_bp.route("/api/migration/v2/workflows", methods=["POST"])
def import_workflow_route():
    """Migrate, validate, and persist one workflow."""
    denied = _require_loopback()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    document = body.get("workflow")
    if not isinstance(document, dict):
        return _error("BAD_REQUEST", "workflow must be an object")
    try:
        saved, original_id, trail = import_workflow(
            document, on_conflict=body.get("on_conflict", "new_id")
        )
    except V2ImportError as exc:
        return _error(exc.code, str(exc))
    return jsonify({
        "workflow": saved,
        "imported_from_id": original_id,
        "migration_trail": trail,
    }), 201


@migration_bp.route("/api/migration/v2/settings", methods=["POST"])
def import_settings_route():
    """Migrate and write settings.json (optional body; else no-op without path)."""
    denied = _require_loopback()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    document = body.get("settings")
    if not isinstance(document, dict):
        return _error("BAD_REQUEST", "settings must be an object")
    try:
        migrated, changed = import_settings(
            document,
            legacy_user=body.get("legacy_user") if isinstance(body.get("legacy_user"), dict) else None,
            write=True,
        )
    except V2ImportError as exc:
        return _error(exc.code, str(exc))
    return jsonify({"settings_version": migrated.get("version"), "changed": changed})


@migration_bp.route("/api/migration/v2/project-zip", methods=["POST"])
def import_project_zip_route():
    """Import an editor project ZIP through the V2 import surface."""
    denied = _require_loopback()
    if denied:
        return denied
    if "file" not in request.files:
        return _error("BAD_REQUEST", "No file uploaded")
    zfile = request.files["file"]
    if not zfile.filename or not zfile.filename.lower().endswith(".zip"):
        return _error("BAD_REQUEST", "File must be a .zip")
    try:
        result = import_project_from_zip(zfile.read())
    except V2ImportError as exc:
        return _error(exc.code, str(exc))
    payload = {
        "project_id": result.project_id,
        "imported_files": result.imported_files,
        "source_folder": result.source_folder,
    }
    if result.renamed_from:
        payload["renamed_from"] = result.renamed_from
    return jsonify(payload), 201


@migration_bp.route("/api/migration/v2/projects/<project_id>/export", methods=["GET"])
def export_project_route(project_id):
    """Re-export an imported project as a ZIP (no manual edits)."""
    denied = _require_loopback()
    if denied:
        return denied
    try:
        data = export_project(project_id)
    except V2ImportError as exc:
        status = 404 if exc.code == "PROJECT_NOT_FOUND" else 400
        return _error(exc.code, str(exc), status)
    from flask import send_file
    import io

    return send_file(
        io.BytesIO(data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{project_id}.zip",
    )


@migration_bp.route("/api/migration/v2/root", methods=["POST"])
def import_root_route():
    """Import a local V2 installation root (loopback path only).

    Body: ``{ "path": "<absolute path to V2 root>", "project_ids"?: [...] }``.
    Path must exist on this machine; browser-supplied paths are not trusted
    beyond the loopback gate.
    """
    denied = _require_loopback()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        return _error("BAD_REQUEST", "path must be a non-empty string")
    path = os.path.abspath(path.strip())
    if not os.path.isdir(path):
        return _error("SOURCE_NOT_FOUND", f"V2 root not found: {path}", 404)
    project_ids = body.get("project_ids")
    if project_ids is not None and not (
        isinstance(project_ids, list) and all(isinstance(x, str) for x in project_ids)
    ):
        return _error("BAD_REQUEST", "project_ids must be a list of strings")
    try:
        report = import_v2_root(
            path,
            project_ids=project_ids,
            import_settings_file=bool(body.get("import_settings", True)),
            import_workflows=bool(body.get("import_workflows", True)),
            import_projects=bool(body.get("import_projects", True)),
            seed_channels=bool(body.get("seed_channels", True)),
        )
    except V2ImportError as exc:
        return _error(exc.code, str(exc))
    return jsonify(report.as_dict()), 201
