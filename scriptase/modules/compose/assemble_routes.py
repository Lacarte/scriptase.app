"""Assemble a project into editor-ready form.

Transport only: a thin wrapper over
``scriptase.modules.compose.service.assemble_project_for_editor``. V2 had
the route function *be* the service; step 0.3 separates them.
"""

from flask import Blueprint, jsonify, request

from scriptase.modules.compose.service import assemble_project_for_editor

compose_assemble_bp = Blueprint("compose_assemble", __name__)


@compose_assemble_bp.route("/api/projects/<project_id>/assemble", methods=["POST"])
def assemble_project(project_id):
    """Assemble a project from scenes + assets into editor-ready format."""
    force = request.args.get("force", "0") == "1"
    result = assemble_project_for_editor(project_id, force=force)
    if isinstance(result, tuple):
        payload, status = result
        return jsonify(payload), status
    return jsonify(result)
