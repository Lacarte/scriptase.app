"""HTTP transport for Jobs and stage projection (steps 1.4–1.5, 2.2, 2.5).

Thin shell over store / orchestration / stage_projection. Business logic stays
out of this module (CLAUDE.md: no imports *from* a routes.py for behaviour).

Endpoints:

Job creation (Step 0 / step 2.5)
* ``GET    /api/jobs/defaults`` — source + execution mode catalog
* ``GET    /api/jobs`` — list (newest first)
* ``POST   /api/jobs`` — create from Channel + source + workflow + mode
* ``POST   /api/jobs/batch`` — create one queued Job per Studio script
* ``GET    /api/jobs/<job_id>`` — full document (snapshot is secret-free)
* ``GET    /api/jobs/<job_id>/cost`` — cost accounting report (9.3)
* ``GET    /api/jobs/<job_id>/repair-history`` — full repair sequence (8.4)
* ``POST   /api/jobs/<job_id>/start`` — run through the ported engine
* ``POST   /api/jobs/<job_id>/test-node`` — isolated Test Node run; never advances Job (4.2)
* ``POST   /api/jobs/<job_id>/approve`` — durable checkpoint approve + resume (2.6)
* ``POST   /api/jobs/<job_id>/reject`` — durable checkpoint reject (2.6)
* ``DELETE /api/jobs/<job_id>`` — soft-delete into TRASH

Stage projection (step 2.2)
* ``GET  /api/workflows/<workflow_id>/stages``
* ``POST /api/workflow/stages``
* ``GET  /api/workflow/executions/<execution_id>/stages``

Workflow routes that describe credentials stay loopback-only; Job and stage
payloads never include secrets or absolute filesystem paths.
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
from scriptase.jobs.models import JOB_ID_RE, JOB_STATUSES
from scriptase.jobs.orchestration import (
    JobOrchestrationError,
    approve_job,
    pause_job,
    reject_job,
    resume_job,
    start_job,
    sync_job_from_execution,
    run_node_test,
)
from scriptase.jobs.source_modes import job_creation_catalog
from scriptase.jobs.stage_projection import (
    StageProjectionError,
    project_stages,
    stage_projection_summary,
)
from scriptase.jobs.store import (
    JobNotFound,
    JobTerminal,
    JobValidationError,
    create_job,
    create_script_batch,
    delete_job,
    get_job,
    job_summary,
    list_jobs,
)
from scriptase.jobs.snapshot import assert_snapshot_has_no_credentials

# Draft bodies are workflow-sized; match the workflow document limit.
MAX_BODY_BYTES = 2 * 1024 * 1024

jobs_bp = Blueprint("jobs", __name__)


def _error(code: str, message: str, status: int, details=None):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def _json_body(*, allow_empty: bool = False):
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
        if allow_empty:
            return {}, None
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


def _store_error(exc: Exception):
    if isinstance(exc, JobNotFound):
        return _error("JOB_NOT_FOUND", "Job not found", 404)
    if isinstance(exc, JobTerminal):
        return _error(
            "JOB_TERMINAL",
            f"Job is terminal ({exc.status})",
            409,
            {"job_id": exc.job_id, "status": exc.status},
        )
    if isinstance(exc, JobValidationError):
        return _error(
            "JOB_INVALID",
            "Job document failed schema validation",
            422,
            {"problems": exc.problems},
        )
    if isinstance(exc, JobOrchestrationError):
        status = 409 if exc.code in {
            "JOB_ALREADY_RUNNING",
            "JOB_NOT_RUNNING",
            "JOB_NOT_PAUSED",
            "JOB_NOT_AWAITING",
            "EXECUTION_NOT_RUNNING",
            "EXECUTION_NOT_PAUSED",
            "EXECUTION_NOT_AWAITING",
            "CHECKPOINT_NOT_AWAITING",
            "APPROVAL_EXPIRED",
            "EXECUTION_TERMINAL",
        } else 422
        if exc.code in {"WORKFLOW_NOT_FOUND", "WORKFLOW_REQUIRED"}:
            status = 422
        return _error(exc.code, str(exc), status, exc.details)
    if isinstance(exc, ValueError):
        return _error("BAD_REQUEST", str(exc), 400)
    raise exc


def _job_public(document) -> dict:
    """Serialize a Job for the API. Snapshot is already secret-free; re-check."""
    payload = document.to_document()
    assert_snapshot_has_no_credentials(payload.get("channel_snapshot") or {})
    return payload


def _queue_view(execution_id: str | None) -> dict:
    """Place in the serial global pool for *execution_id* (step 13.1).

    Runtime state, never persisted onto the Job — a restart has no queue.
    ``queue_position`` is ``0`` while the run holds a pool slot, ``1..N``
    while it waits, and absent once the run is terminal.
    """
    if not execution_id:
        return {}
    from scriptase.engine.execution import execution_manager

    status = execution_manager.queue_status()
    position = status["positions"].get(execution_id)
    if position is None:
        return {}
    return {
        "queue_position": position,
        "queue_waiting": status["waiting"],
        "max_global_workers": status["max_global_workers"],
    }


def _draft_from_body(body: dict) -> dict:
    """Accept either a bare draft or ``{job: draft}``."""
    if isinstance(body.get("job"), dict):
        return body["job"]
    return {
        key: value
        for key, value in body.items()
        if key
        in {
            "channel_id",
            "workflow_id",
            "workflow_version",
            "execution_mode",
            "source",
        }
    }


def _owning_job_id(workflow) -> str | None:
    """The Job that stamped this snapshot, from ``extensions.job_id`` (2.5).

    Step 11.2: this is how a projection reaches the Job's ReviewIssues without
    a second lookup — ``prepare_workflow_for_job`` already writes the id into
    the snapshot the execution record carries.
    """
    extensions = workflow.get("extensions") if isinstance(workflow, dict) else None
    if not isinstance(extensions, dict):
        return None
    job_id = extensions.get("job_id")
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id.strip()):
        return None
    return job_id.strip()


def _project_or_error(workflow, *, execution=None):
    try:
        projection = project_stages(
            workflow, execution=execution, job_id=_owning_job_id(workflow)
        )
    except StageProjectionError as exc:
        return None, _error(
            exc.code,
            exc.message,
            422,
            exc.details,
        )
    return projection, None


# ---------------------------------------------------------------------------
# Job creation + lifecycle (step 2.5)
# ---------------------------------------------------------------------------


@jobs_bp.route("/api/jobs/defaults", methods=["GET"])
def jobs_defaults():
    """Step 0 form catalog: source modes, execution modes, blank draft."""
    return jsonify(job_creation_catalog())


@jobs_bp.route("/api/jobs", methods=["GET"])
def jobs_list():
    """List jobs newest-first.

    Query:
      channel_id  optional filter
      status      optional Job status filter
      limit       1–500 (default 200)
    """
    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "limit must be an integer", 400)
    if not 1 <= limit <= 500:
        return _error("BAD_REQUEST", "limit must be between 1 and 500", 400)

    channel_id = (request.args.get("channel_id") or "").strip() or None
    status = (request.args.get("status") or "").strip() or None
    if status is not None and status not in JOB_STATUSES:
        return _error(
            "BAD_REQUEST",
            f"status must be one of: {', '.join(JOB_STATUSES)}",
            400,
        )

    items = list_jobs(channel_id=channel_id, status=status, limit=limit)
    return jsonify({
        "jobs": [job_summary(item) for item in items],
        "total": len(items),
    })


@jobs_bp.route("/api/jobs", methods=["POST"])
def jobs_create():
    """Create a Job: Channel picker, source mode, workflow, execution mode.

    Body: bare draft or ``{job: draft}``. Snapshot is frozen from the Channel
    at create time and never holds credentials.
    """
    body, error = _json_body()
    if error:
        return error
    draft = _draft_from_body(body)
    if not draft.get("channel_id"):
        return _error("BAD_REQUEST", "channel_id is required", 400)
    try:
        document = create_job(draft)
    except (JobValidationError, ValueError) as exc:
        return _store_error(exc)
    response = jsonify({"job": _job_public(document)})
    response.status_code = 201
    response.headers["Location"] = f"/api/jobs/{document.id}"
    return response


@jobs_bp.route("/api/jobs/batch", methods=["POST"])
def jobs_batch_create():
    """Create one queued Job for every selected Script Studio document."""
    body, error = _json_body()
    if error:
        return error
    batch = body.get("batch") if isinstance(body.get("batch"), dict) else body
    channel_id = str(batch.get("channel_id") or "").strip()
    if not channel_id:
        return _error("BAD_REQUEST", "channel_id is required", 400)
    try:
        documents = create_script_batch(
            channel_id=channel_id,
            script_ids=batch.get("script_ids"),
            execution_mode=batch.get("execution_mode") or "manual",
            workflow_id=batch.get("workflow_id"),
            workflow_version=batch.get("workflow_version"),
        )
    except (JobValidationError, ValueError) as exc:
        return _store_error(exc)
    response = jsonify({
        "jobs": [_job_public(document) for document in documents],
        "total": len(documents),
    })
    response.status_code = 201
    return response


@jobs_bp.route("/api/jobs/<job_id>", methods=["GET"])
def jobs_get(job_id: str):
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    try:
        document = get_job(job_id)
        # Refresh status from the linked execution when present so the
        # Production view does not need a second polling loop for Job state.
        if document.execution_id and document.status not in {
            "completed", "failed", "cancelled",
        }:
            try:
                document = sync_job_from_execution(document.id)
            except Exception:
                pass
    except (JobNotFound, JobValidationError, ValueError) as exc:
        return _store_error(exc)
    return jsonify({
        "job": _job_public(document),
        **_queue_view(document.execution_id),
    })


@jobs_bp.route("/api/jobs/<job_id>/cost", methods=["GET"])
def jobs_cost_report(job_id: str):
    """Accumulated generation count and cost for a Job (step 9.3).

    Breaks spend down by Production stage and provider instance, and
    reconciles the sum with ``budget_spent`` / provenance cost records.
    Currency conversion (if any) is applied only in this report payload.
    """
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    try:
        document = get_job(job_id)
        # Refresh spend from the linked execution when present so the report
        # matches the latest provenance-backed node snapshots.
        if document.execution_id:
            try:
                document = sync_job_from_execution(document.id)
            except Exception:
                pass
    except (JobNotFound, JobValidationError, ValueError) as exc:
        return _store_error(exc)

    from scriptase.jobs.cost import build_cost_report

    execution = None
    if document.execution_id:
        try:
            execution = load_execution(document.execution_id)
        except Exception:
            execution = None

    report = build_cost_report(document, execution=execution)
    return jsonify({"cost": report})


@jobs_bp.route("/api/jobs/<job_id>/repair-history", methods=["GET"])
def jobs_repair_history(job_id: str):
    """Full repair sequence for a Job (step 8.4).

    Reconstructs every RepairHistoryEntry in attempt order, including
    superseded artifact versions and the reason each repair was attempted.
    """
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    try:
        get_job(job_id)
    except (JobNotFound, JobValidationError, ValueError) as exc:
        return _store_error(exc)

    from scriptase.review.history import (
        RepairHistoryError,
        reconstruct_job_repair_history,
    )

    try:
        history = reconstruct_job_repair_history(job_id)
    except RepairHistoryError as exc:
        return _error(exc.code, exc.message, 400, exc.details)
    return jsonify(history)


@jobs_bp.route("/api/jobs/<job_id>/start", methods=["POST"])
def jobs_start(job_id: str):
    """Start the Job's workflow through the ported execution manager.

    Body (optional):
      force   bool — re-run even when cache hits
      wait    bool — block until terminal (tests / short runs only)
      timeout float seconds when wait is true (default 120)
    """
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    body, error = _json_body(allow_empty=True)
    if error:
        return error
    force = bool(body.get("force", False)) if body else False
    wait = bool(body.get("wait", False)) if body else False
    try:
        timeout = float(body.get("timeout", 120.0)) if body else 120.0
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "timeout must be a number", 400)
    if timeout <= 0 or timeout > 3600:
        return _error("BAD_REQUEST", "timeout must be between 0 and 3600 seconds", 400)

    try:
        document = start_job(
            job_id,
            force=force,
            wait=wait,
            timeout=timeout,
        )
    except (
        JobNotFound,
        JobTerminal,
        JobValidationError,
        JobOrchestrationError,
        ValueError,
    ) as exc:
        return _store_error(exc)
    return jsonify({
        "job": _job_public(document),
        "execution_id": document.execution_id,
        "status": document.status,
        **_queue_view(document.execution_id),
    })


@jobs_bp.route("/api/jobs/<job_id>/test-node", methods=["POST"])
def jobs_test_node(job_id: str):
    """Test a single node in isolation without advancing the Job (step 4.2).

    Body:
      target_node_ids   list[str] — required; primary node to test
      input_bindings?   {node_id: {port_id: binding}} from the input picker
      input_overrides?  pre-resolved payloads (optional alternative)
      provider_instance_id? str — one-shot provider for this run only (13.2)
      force?            bool
      wait?             bool — block until terminal (tests / short runs)
      timeout?          float seconds when wait is true (default 120)

    The Job's status, current_stage, and artifact set are unchanged. Results
    keep the engine ``from_sample_data`` marker when sample bindings feed the
    node. The returned ``execution_id`` is exploratory and is **not** written
    onto the Job.

    ``provider_instance_id`` is resolved for this execution only and recorded
    in provenance as ``selection_reason: request``. The node's stored
    configuration is never touched.
    """
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    body, error = _json_body()
    if error:
        return error

    targets = body.get("target_node_ids")
    if not isinstance(targets, list) or not targets:
        return _error("BAD_REQUEST", "target_node_ids must be a non-empty list", 400)
    if not all(isinstance(item, str) and item for item in targets):
        return _error("BAD_REQUEST", "target_node_ids must be non-empty strings", 400)

    input_bindings = body.get("input_bindings")
    if input_bindings is not None and not isinstance(input_bindings, dict):
        return _error("BAD_REQUEST", "input_bindings must be an object", 400)
    input_overrides = body.get("input_overrides")
    if input_overrides is not None and not isinstance(input_overrides, dict):
        return _error("BAD_REQUEST", "input_overrides must be an object", 400)
    provider_instance_id = body.get("provider_instance_id")
    if provider_instance_id is not None and not isinstance(provider_instance_id, str):
        return _error("BAD_REQUEST", "provider_instance_id must be a string", 400)

    force = bool(body.get("force", False))
    wait = bool(body.get("wait", False))
    try:
        timeout = float(body.get("timeout", 120.0))
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "timeout must be a number", 400)
    if timeout <= 0 or timeout > 3600:
        return _error("BAD_REQUEST", "timeout must be between 0 and 3600 seconds", 400)

    try:
        result = run_node_test(
            job_id,
            target_node_ids=targets,
            input_bindings=input_bindings,
            input_overrides=input_overrides,
            provider_instance_id=provider_instance_id or "",
            force=force,
            wait=wait,
            timeout=timeout,
        )
    except (
        JobNotFound,
        JobValidationError,
        JobOrchestrationError,
        ValueError,
    ) as exc:
        return _store_error(exc)

    payload = {
        "job": _job_public(result["job"]),
        "execution_id": result["execution_id"],
        "project_id": result["project_id"],
        "status": result["status"],
        "run_mode": result["run_mode"],
        "target_node_ids": result["target_node_ids"],
        "provider_instance_id": result["provider_instance_id"],
    }
    if result.get("execution") is not None:
        payload["execution"] = result["execution"]
    response = jsonify(payload)
    response.status_code = 202
    return response


@jobs_bp.route("/api/jobs/<job_id>/pause", methods=["POST"])
def jobs_pause(job_id: str):
    """Durably pause the running Job at the next safe node boundary."""
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    body, error = _json_body(allow_empty=True)
    if error:
        return error
    try:
        timeout = float(body.get("timeout", 120.0)) if body else 120.0
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "timeout must be a number", 400)
    if timeout <= 0 or timeout > 3600:
        return _error("BAD_REQUEST", "timeout must be between 0 and 3600 seconds", 400)
    try:
        document = pause_job(job_id, timeout=timeout)
    except (
        JobNotFound, JobTerminal, JobValidationError, JobOrchestrationError, ValueError
    ) as exc:
        return _store_error(exc)
    return jsonify({
        "job": _job_public(document),
        "execution_id": document.execution_id,
        "status": document.status,
        **_queue_view(document.execution_id),
    })


@jobs_bp.route("/api/jobs/<job_id>/resume", methods=["POST"])
def jobs_resume(job_id: str):
    """Resume the same execution from a durable user pause."""
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    body, error = _json_body(allow_empty=True)
    if error:
        return error
    wait = bool(body.get("wait", False)) if body else False
    try:
        timeout = float(body.get("timeout", 120.0)) if body else 120.0
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "timeout must be a number", 400)
    if timeout <= 0 or timeout > 3600:
        return _error("BAD_REQUEST", "timeout must be between 0 and 3600 seconds", 400)
    try:
        document = resume_job(job_id, wait=wait, timeout=timeout)
    except (
        JobNotFound, JobTerminal, JobValidationError, JobOrchestrationError, ValueError
    ) as exc:
        return _store_error(exc)
    return jsonify({
        "job": _job_public(document),
        "execution_id": document.execution_id,
        "status": document.status,
        **_queue_view(document.execution_id),
    })


@jobs_bp.route("/api/jobs/<job_id>/approve", methods=["POST"])
def jobs_approve(job_id: str):
    """Approve a durable checkpoint and resume the Job (step 2.6).

    Body (optional):
      decided_by  actor label (never a credential)
      wait        bool — block until terminal or next pause
      timeout     float seconds when wait is true
    """
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    body, error = _json_body(allow_empty=True)
    if error:
        return error
    decided_by = None
    if body and body.get("decided_by") is not None:
        decided_by = str(body.get("decided_by") or "").strip() or None
    wait = bool(body.get("wait", False)) if body else False
    try:
        timeout = float(body.get("timeout", 120.0)) if body else 120.0
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "timeout must be a number", 400)
    if timeout <= 0 or timeout > 3600:
        return _error("BAD_REQUEST", "timeout must be between 0 and 3600 seconds", 400)
    try:
        document = approve_job(
            job_id,
            decided_by=decided_by,
            wait=wait,
            timeout=timeout,
        )
    except (
        JobNotFound,
        JobTerminal,
        JobValidationError,
        JobOrchestrationError,
        ValueError,
    ) as exc:
        return _store_error(exc)
    return jsonify({
        "job": _job_public(document),
        "execution_id": document.execution_id,
        "status": document.status,
        **_queue_view(document.execution_id),
    })


@jobs_bp.route("/api/jobs/<job_id>/reject", methods=["POST"])
def jobs_reject(job_id: str):
    """Reject a durable checkpoint and fail the Job (step 2.6)."""
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    body, error = _json_body(allow_empty=True)
    if error:
        return error
    decided_by = None
    if body and body.get("decided_by") is not None:
        decided_by = str(body.get("decided_by") or "").strip() or None
    try:
        document = reject_job(job_id, decided_by=decided_by)
    except (
        JobNotFound,
        JobTerminal,
        JobValidationError,
        JobOrchestrationError,
        ValueError,
    ) as exc:
        return _store_error(exc)
    return jsonify({
        "job": _job_public(document),
        "execution_id": document.execution_id,
        "status": document.status,
    })


@jobs_bp.route("/api/jobs/<job_id>", methods=["DELETE"])
def jobs_delete(job_id: str):
    if not JOB_ID_RE.fullmatch(job_id or ""):
        return _error("BAD_REQUEST", "job_id must match job_[A-Z0-9]{6}", 400)
    try:
        delete_job(job_id)
    except (JobNotFound, ValueError) as exc:
        return _store_error(exc)
    return jsonify({"deleted": True, "job_id": job_id})


# ---------------------------------------------------------------------------
# Stage projection (step 2.2)
# ---------------------------------------------------------------------------


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
        # Step 13.1: hydration value only — live movement arrives as
        # ``queue_position`` frames on the run's own SSE stream.
        **_queue_view(execution.get("execution_id") or execution_id),
    }
    return jsonify({"projection": projection})


__all__ = ["jobs_bp"]
