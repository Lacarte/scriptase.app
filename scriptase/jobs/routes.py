"""HTTP transport for stage projection (step 2.2).

Thin shell over ``scriptase.jobs.stage_projection``. Business logic stays out
of this module (CLAUDE.md: no imports *from* a routes.py for behaviour).

Endpoints:

* ``GET  /api/workflows/<workflow_id>/stages`` — project a saved workflow
* ``POST /api/workflow/stages`` — project a workflow document body (draft /
  template) without requiring persistence
* ``GET  /api/workflow/executions/<execution_id>/stages`` — project the
  snapshot used for a run, with live per-stage status from node records

Workflow routes that describe credentials stay loopback-only; stage projection
returns no secrets and is safe on any interface.
"""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from scriptase.engine.persistence import (
    WorkflowNotFound,
    WorkflowValidationError,
    load_execution,
    load_workflow,
)
from scriptase.engine.validation import WORKFLOW_ID_RE
from scriptase.jobs.stage_projection import (
    StageProjectionError,
    project_stages,
    stage_projection_summary,
)

# Draft bodies are workflow-sized; match the workflow document limit.
MAX_BODY_BYTES = 2 * 1024 * 1024

jobs_bp = Blueprint("jobs", __name__)


def _error(code: str, message: str, status: int, details=None):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def _json_body():
    declared = request.content_length
    if declared is not None and declared > MAX_BODY_BYTES:
        return None, _error(
            "REQUEST_TOO_LARGE", "Request exceeds the 2 MiB limit", 413
        )
    raw = request.stream.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        return None, _error(
            "REQUEST_TOO_LARGE", "Request exceeds the 2 MiB limit", 413
        )
    if not raw:
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    if not request.is_json:
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    if not isinstance(body, dict):
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    return body, None


def _project_or_error(workflow, *, execution=None):
    try:
        projection = project_stages(workflow, execution=execution)
    except StageProjectionError as exc:
        return None, _error(
            exc.code,
            exc.message,
            422,
            exc.details,
        )
    return projection, None


@jobs_bp.route("/api/workflows/<workflow_id>/stages", methods=["GET"])
def workflow_stages(workflow_id: str):
    """Project a saved workflow into the ordered Production stage list.

    Query:
      summary  when ``1``/``true``, return the compact listing form
    """
    if not WORKFLOW_ID_RE.fullmatch(workflow_id or ""):
        return _error("BAD_REQUEST", "workflow_id must match wf_XXXXXX", 400)
    try:
        workflow = load_workflow(workflow_id)
    except WorkflowNotFound:
        return _error("NOT_FOUND", "Workflow not found", 404)
    except WorkflowValidationError as exc:
        return _error(
            "WORKFLOW_INVALID",
            "Workflow document failed validation",
            422,
            {"problems": exc.problems},
        )

    projection, error = _project_or_error(workflow)
    if error:
        return error

    summary_flag = (request.args.get("summary", "") or "").strip().lower()
    if summary_flag in {"1", "true", "yes", "on"}:
        return jsonify({"projection": stage_projection_summary(projection)})
    return jsonify({"projection": projection})


@jobs_bp.route("/api/workflow/stages", methods=["POST"])
def project_workflow_body():
    """Project an inline workflow document (draft / template) into stages.

    Body accepts either a bare workflow object or ``{workflow: ...}``.
    """
    body, error = _json_body()
    if error:
        return error
    workflow = body.get("workflow") if isinstance(body.get("workflow"), dict) else body
    if not isinstance(workflow, dict) or "nodes" not in workflow:
        return _error(
            "BAD_REQUEST",
            "Body must be a workflow document (or {workflow: ...}) with nodes",
            400,
        )

    projection, error = _project_or_error(workflow)
    if error:
        return error
    return jsonify({"projection": projection})


@jobs_bp.route("/api/workflow/executions/<execution_id>/stages", methods=["GET"])
def execution_stages(execution_id: str):
    """Project the execution's workflow snapshot with live stage status.

    Status and artifacts are derived from member nodes' execution records —
    there is no separate stage status store (contracts.md §10).
    """
    from scriptase.engine.persistence import EXECUTION_ID_RE

    if not EXECUTION_ID_RE.fullmatch(execution_id or ""):
        return _error("BAD_REQUEST", "execution_id must match ex_XXXXXX", 400)
    try:
        execution = load_execution(execution_id)
    except FileNotFoundError:
        return _error("NOT_FOUND", "Execution not found", 404)

    snapshot = execution.get("workflow_snapshot") if isinstance(execution, dict) else None
    if not isinstance(snapshot, dict):
        return _error(
            "STAGE_PROJECTION_INVALID",
            "Execution has no workflow snapshot to project",
            422,
        )

    projection, error = _project_or_error(snapshot, execution=execution)
    if error:
        return error
    # Surface the execution identity so the Production view can bind SSE.
    projection = {
        **projection,
        "execution_id": execution.get("execution_id") or execution_id,
        "execution_status": execution.get("status"),
    }
    return jsonify({"projection": projection})
