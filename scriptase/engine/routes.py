"""Flask blueprint for workflow registry and definition persistence."""

import io
import ipaddress
import json
import os
import shutil
import tempfile
import uuid

from flask import Blueprint, Response, jsonify, request, send_file, send_from_directory, stream_with_context
from werkzeug.exceptions import RequestEntityTooLarge

from config import BRANDING_DIR
from scriptase.shared.io_utils import now_iso
from scriptase.shared.security import is_loopback_remote, sanitize_folder_name
from .models import copy_draft
from .events import TERMINAL_STATUSES, sse_frame
from .execution import ExecutionRequestError, execution_manager
from .persistence import (
    WorkflowConflict,
    WorkflowNotFound,
    WorkflowReadOnlyError,
    WorkflowValidationError,
    create_workflow,
    delete_workflow,
    import_workflow,
    list_executions,
    load_execution,
    list_workflows,
    load_workflow,
    load_workflow_state,
    update_workflow,
)
from .options import OptionContextError, resolve_options
from .project_archive import (
    MAX_ARCHIVE_BYTES,
    ProjectArchiveError,
    create_archive,
    project_summaries,
    restore_archive,
)
from .notifications import list_notifications, mark_notifications_seen
from .registry import serialize_registry
from .sample_data import all_sample_payloads
from .scheduled_runs import schedule_details
from .templates import serialize_templates
from .validation import MAX_DOCUMENT_BYTES, validate_workflow
from .webhook_triggers import (
    MAX_WEBHOOK_PAYLOAD_BYTES,
    WebhookPayloadError,
    map_webhook_payload,
    token_matches,
    webhook_token,
)
from .dev_reload import dev_reload_enabled, dev_reloader, next_reload_event

BRANDING_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_BRANDING_BYTES = 5 * 1024 * 1024
# Whole-request cap for the multipart upload: the 5 MB file plus generous
# multipart framing overhead. Enforced by Werkzeug while the stream is read,
# so chunked transfer encoding cannot bypass it (step 6.3).
MAX_BRANDING_REQUEST_BYTES = MAX_BRANDING_BYTES + 1024 * 1024
MAX_BRANDING_ASSETS = 50

workflows_bp = Blueprint("workflows", __name__)


def _error(code, message, status, details=None):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


@workflows_bp.errorhandler(RequestEntityTooLarge)
def _request_entity_too_large(_exc):
    """Werkzeug raises this mid-read when max_content_length trips (including
    chunked requests with no Content-Length); answer with the envelope."""
    return _error("REQUEST_TOO_LARGE", "Request body exceeds the allowed size", 413)


def _require_loopback():
    if not is_loopback_remote(request.remote_addr):
        return _error("FORBIDDEN", "Workflow endpoints are local-only", 403)
    return None


def _json_body(*, allow_empty=False, max_bytes=MAX_DOCUMENT_BYTES, limit_message="Request exceeds the 2 MiB limit"):
    """Parse a bounded JSON object body.

    Reads at most MAX_DOCUMENT_BYTES + 1 bytes from the request stream, so the
    2 MiB limit holds even for chunked transfer encoding, where Content-Length
    is absent and header checks alone are bypassable (step 6.3).
    """
    declared = request.content_length
    if declared is not None and declared > max_bytes:
        return None, _error("REQUEST_TOO_LARGE", limit_message, 413)
    raw = request.stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return None, _error("REQUEST_TOO_LARGE", limit_message, 413)
    if not raw:
        if allow_empty:
            return {}, None
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    # Require a JSON content type like get_json did: cross-origin "simple"
    # requests cannot send application/json without a CORS preflight.
    if not request.is_json:
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    if not isinstance(body, dict):
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    return body, None


def _persistence_error(exc):
    if isinstance(exc, WorkflowNotFound):
        return _error("NOT_FOUND", "Workflow not found", 404)
    if isinstance(exc, WorkflowConflict):
        return _error("WORKFLOW_CONFLICT", "Workflow changed since it was opened", 409)
    if isinstance(exc, WorkflowReadOnlyError):
        return _error(
            "WORKFLOW_READ_ONLY",
            "Workflow contains node versions newer than this installation and is read-only",
            409,
        )
    if isinstance(exc, WorkflowValidationError):
        return _error(
            "WORKFLOW_INVALID",
            "Workflow has validation errors",
            422,
            {"problems": exc.problems},
        )
    if isinstance(exc, ValueError):
        return _error("BAD_REQUEST", str(exc), 400)
    raise exc


@workflows_bp.route("/api/workflow/node-types", methods=["GET"])
def node_types():
    denied = _require_loopback()
    if denied:
        return denied
    payload = serialize_registry()
    payload["dev_reload_enabled"] = dev_reload_enabled()
    # Default stub payloads per dynamic port type (step 2.5). Fixture-derived,
    # presentation-safe: fixture-relative refs only, no executor internals.
    payload["sample_payloads"] = all_sample_payloads()
    return jsonify(payload)


@workflows_bp.route("/api/workflow/dev-reload/events", methods=["GET"])
def workflow_dev_reload_events():
    """Dev-only SSE signal; normal runs do not expose or start a watcher."""
    denied = _require_loopback()
    if denied:
        return denied
    if not dev_reload_enabled():
        return _error("NOT_FOUND", "Not found", 404)

    reloader = dev_reloader()
    channel = reloader.subscribe()

    def stream():
        try:
            yield ": workflow dev reload connected\n\n"
            while True:
                event = next_reload_event(channel)
                if event is None:
                    yield ": keepalive\n\n"
                else:
                    yield f"event: registry-reload\ndata: {json.dumps(event)}\n\n"
        finally:
            reloader.unsubscribe(channel)

    return Response(stream_with_context(stream()), mimetype="text/event-stream")


@workflows_bp.route("/api/workflow/templates", methods=["GET"])
def workflow_templates():
    denied = _require_loopback()
    if denied:
        return denied
    return jsonify({"templates": serialize_templates()})


@workflows_bp.route("/api/workflow/options/<source>", methods=["GET"])
def workflow_options(source):
    """Resolve an allowlisted async option source (contracts §11, §23).

    Query parameters are a second allowlist: only the names the source declares
    are accepted, and each is validated before it reaches a resolver. The
    response echoes the **normalized** context so the client keys its cache on
    the server's interpretation rather than on its own query string (§23.2).
    """
    denied = _require_loopback()
    if denied:
        return denied
    try:
        options, context = resolve_options(source, request.args.to_dict())
    except OptionContextError as exc:
        return _error("OPTION_CONTEXT_INVALID", str(exc), 400)
    except RuntimeError as exc:
        return _error("PROVIDER_UNAVAILABLE", str(exc), 503)
    if options is None:
        return _error("NOT_FOUND", f"Unknown option source: {source[:80]}", 404)
    return jsonify({
        "source": source,
        "context": context,
        "options": options,
        "generated_at": now_iso(),
    })


def _branding_asset(filename):
    path = os.path.join(BRANDING_DIR, filename)
    return {
        "ref": f"branding/{filename}",
        "filename": filename,
        "size": os.path.getsize(path),
        "url": f"/output/branding/{filename}",
    }


@workflows_bp.route("/api/workflow/branding", methods=["GET"])
def branding_list():
    denied = _require_loopback()
    if denied:
        return denied
    os.makedirs(BRANDING_DIR, exist_ok=True)
    assets = []
    for name in sorted(os.listdir(BRANDING_DIR)):
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in BRANDING_EXTENSIONS:
            assets.append(_branding_asset(name))
    return jsonify({"assets": assets})


def _branding_asset_count():
    if not os.path.isdir(BRANDING_DIR):
        return 0
    count = 0
    for name in os.listdir(BRANDING_DIR):
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in BRANDING_EXTENSIONS:
            count += 1
    return count


@workflows_bp.route("/api/workflow/branding", methods=["POST"])
def branding_upload():
    """Managed logo upload (contracts §11): extension + MIME + size + decode
    validation into output/branding/ — never raw filesystem paths."""
    denied = _require_loopback()
    if denied:
        return denied
    # Transport cap before any multipart parsing: Werkzeug enforces
    # max_content_length while reading the stream, so a chunked request with
    # no Content-Length still stops at the limit (step 6.3).
    request.max_content_length = MAX_BRANDING_REQUEST_BYTES
    declared = request.content_length
    if declared is not None and declared > MAX_BRANDING_REQUEST_BYTES:
        return _error("REQUEST_TOO_LARGE", "Logo exceeds the 5 MB limit", 413)
    if _branding_asset_count() >= MAX_BRANDING_ASSETS:
        return _error(
            "LIMIT_EXCEEDED",
            f"Branding library is full ({MAX_BRANDING_ASSETS} logos) — delete unused logos first",
            409,
        )
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _error("BAD_REQUEST", "Multipart field 'file' is required", 400)

    original = upload.filename
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in BRANDING_EXTENSIONS:
        return _error("BAD_REQUEST", "Only png, jpg, jpeg, or webp logos are allowed", 400)
    if not (upload.mimetype or "").startswith("image/"):
        return _error("BAD_REQUEST", "Upload must be an image", 400)

    data = upload.read(MAX_BRANDING_BYTES + 1)
    if len(data) > MAX_BRANDING_BYTES:
        return _error("REQUEST_TOO_LARGE", "Logo exceeds the 5 MB limit", 413)
    if not data:
        return _error("BAD_REQUEST", "Uploaded file is empty", 400)

    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception:
        return _error("BAD_REQUEST", "File is not a decodable image", 400)

    stem = sanitize_folder_name(original.rsplit(".", 1)[0], max_len=40) or "logo"
    filename = f"{stem}_{uuid.uuid4().hex[:8]}.{ext}"
    os.makedirs(BRANDING_DIR, exist_ok=True)
    with open(os.path.join(BRANDING_DIR, filename), "wb") as handle:
        handle.write(data)
    return jsonify({"asset": _branding_asset(filename)}), 201


@workflows_bp.route("/output/branding/<path:filename>")
def serve_branding(filename):
    return send_from_directory(BRANDING_DIR, filename)


@workflows_bp.route("/api/workflow/validate", methods=["POST"])
def workflow_validate():
    """Structured validation for a draft document (contracts §6).

    Always 200 for a well-formed request — graph problems are data, not
    transport errors. `problems` = severity error, `warnings` = severity
    warning (e.g. required inputs still missing on an incomplete draft).
    """
    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body()
    if failure:
        return failure
    document = body.get("workflow")
    if not isinstance(document, dict):
        return _error("BAD_REQUEST", "workflow must be an object", 400)
    findings = validate_workflow(document, require_identity=False, require_complete=False)
    problems = [p for p in findings if p.get("severity") != "warning"]
    warnings = [p for p in findings if p.get("severity") == "warning"]
    return jsonify({"valid": not problems, "problems": problems, "warnings": warnings})


@workflows_bp.route("/api/workflows", methods=["GET"])
def workflows_list():
    denied = _require_loopback()
    if denied:
        return denied
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "limit must be an integer", 400)
    if not 1 <= limit <= 200:
        return _error("BAD_REQUEST", "limit must be between 1 and 200", 400)
    items, total = list_workflows(limit=limit)
    return jsonify({"workflows": items, "total": total})


@workflows_bp.route("/api/workflows", methods=["POST"])
def workflows_create():
    denied = _require_loopback()
    if denied:
        return denied
    body, error = _json_body()
    if error:
        return error
    if not isinstance(body.get("workflow"), dict):
        return _error("BAD_REQUEST", "workflow must be an object", 400)
    try:
        document = create_workflow(copy_draft(body["workflow"]))
    except (ValueError, WorkflowValidationError) as exc:
        return _persistence_error(exc)
    response = jsonify({"workflow": document})
    response.status_code = 201
    response.headers["Location"] = f"/api/workflows/{document['workflow_id']}"
    return response


@workflows_bp.route("/api/workflows/import", methods=["POST"])
def workflows_import():
    denied = _require_loopback()
    if denied:
        return denied
    body, error = _json_body()
    if error:
        return error
    if not isinstance(body.get("workflow"), dict):
        return _error("BAD_REQUEST", "workflow must be an object", 400)
    try:
        document, original_id = import_workflow(
            body["workflow"], on_conflict=body.get("on_conflict", "new_id")
        )
    except (ValueError, WorkflowConflict, WorkflowValidationError) as exc:
        return _persistence_error(exc)
    return jsonify({"workflow": document, "imported_from_id": original_id}), 201


@workflows_bp.route("/api/workflows/<workflow_id>", methods=["GET"])
def workflows_get(workflow_id):
    denied = _require_loopback()
    if denied:
        return denied
    try:
        state = load_workflow_state(workflow_id)
        return jsonify({
            "workflow": state.document,
            "migration_trail": state.trail,
            "read_only": state.read_only,
            "warnings": state.warnings,
        })
    except (ValueError, WorkflowNotFound, WorkflowValidationError) as exc:
        return _persistence_error(exc)


@workflows_bp.route("/api/workflows/<workflow_id>/schedules", methods=["GET"])
def workflow_schedules_get(workflow_id):
    denied = _require_loopback()
    if denied:
        return denied
    try:
        workflow = load_workflow(workflow_id)
        return jsonify({"schedules": schedule_details(workflow), "timezone": "UTC"})
    except (ValueError, WorkflowNotFound, WorkflowValidationError) as exc:
        return _persistence_error(exc)


@workflows_bp.route("/api/workflows/<workflow_id>/webhook", methods=["GET"])
def workflow_webhook_get(workflow_id):
    denied = _require_loopback()
    if denied:
        return denied
    try:
        workflow = load_workflow(workflow_id)
        token = webhook_token(workflow_id)
    except (ValueError, WorkflowNotFound, WorkflowValidationError) as exc:
        return _persistence_error(exc)
    settings = (workflow.get("settings") or {}).get("webhook") or {"enabled": False, "mappings": []}
    response = jsonify({
        "webhook": settings,
        "token": token,
        "path": f"/api/workflow/hooks/{workflow_id}/{token}",
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@workflows_bp.route("/api/workflows/<workflow_id>/webhook/regenerate", methods=["POST"])
def workflow_webhook_regenerate(workflow_id):
    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body(allow_empty=True)
    if failure:
        return failure
    if body:
        return _error("BAD_REQUEST", "Regenerate request body must be empty", 400)
    try:
        load_workflow(workflow_id)
        token = webhook_token(workflow_id, regenerate=True)
    except (ValueError, WorkflowNotFound, WorkflowValidationError) as exc:
        return _persistence_error(exc)
    response = jsonify({"token": token, "path": f"/api/workflow/hooks/{workflow_id}/{token}"})
    response.headers["Cache-Control"] = "no-store"
    return response


def _loopback_bind_enabled():
    bind_host = os.environ.get("STS_BIND_HOST", "127.0.0.1").strip().lower()
    if bind_host == "localhost":
        return True
    try:
        return ipaddress.ip_address(bind_host.strip("[]")).is_loopback
    except ValueError:
        return False


@workflows_bp.route("/api/workflow/hooks/<workflow_id>/<token>", methods=["POST"])
def workflow_hook(workflow_id, token):
    denied = _require_loopback()
    if denied:
        return denied
    if not _loopback_bind_enabled():
        return _error("FORBIDDEN", "Webhook triggers require a loopback-only server bind", 403)
    body, failure = _json_body(
        max_bytes=MAX_WEBHOOK_PAYLOAD_BYTES,
        limit_message="Webhook payload exceeds the 64 KiB limit",
    )
    if failure:
        return failure
    try:
        workflow = load_workflow(workflow_id)
    except (ValueError, WorkflowNotFound, WorkflowValidationError):
        return _error("WEBHOOK_NOT_FOUND", "Webhook not found", 404)
    settings = (workflow.get("settings") or {}).get("webhook") or {}
    if not settings.get("enabled") or not token_matches(workflow_id, token):
        return _error("WEBHOOK_NOT_FOUND", "Webhook not found", 404)
    try:
        overrides = map_webhook_payload(workflow, body)
        execution_id, project_id = execution_manager.start(
            workflow,
            run_mode="full",
            target_node_ids=[],
            source="webhook",
            input_overrides=overrides,
        )
    except WebhookPayloadError as exc:
        return _error("WEBHOOK_PAYLOAD_INVALID", str(exc), 422, exc.details)
    except ExecutionRequestError as exc:
        status = 422 if exc.code in {"WORKFLOW_INVALID", "MISSING_REQUIRED_INPUT"} else 400
        return _error(exc.code, str(exc), status, exc.details)
    return jsonify({"execution_id": execution_id, "project_id": project_id, "status": "queued"}), 202


@workflows_bp.route("/api/workflows/<workflow_id>", methods=["PUT"])
def workflows_update(workflow_id):
    denied = _require_loopback()
    if denied:
        return denied
    body, error = _json_body()
    if error:
        return error
    if not isinstance(body.get("workflow"), dict):
        return _error("BAD_REQUEST", "workflow must be an object", 400)
    try:
        document = update_workflow(
            workflow_id,
            body["workflow"],
            expected_updated_at=body.get("expected_updated_at", ""),
        )
    except (
        ValueError, WorkflowNotFound, WorkflowConflict,
        WorkflowValidationError, WorkflowReadOnlyError,
    ) as exc:
        return _persistence_error(exc)
    return jsonify({"workflow": document})


@workflows_bp.route("/api/workflows/<workflow_id>", methods=["DELETE"])
def workflows_delete(workflow_id):
    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body(allow_empty=True)
    if failure:
        return failure
    try:
        delete_workflow(workflow_id, expected_updated_at=body.get("expected_updated_at"))
    except (ValueError, WorkflowNotFound, WorkflowConflict, WorkflowValidationError) as exc:
        return _persistence_error(exc)
    return jsonify({"deleted": True, "workflow_id": workflow_id})


@workflows_bp.route("/api/workflows/<workflow_id>/export", methods=["GET"])
def workflows_export(workflow_id):
    denied = _require_loopback()
    if denied:
        return denied
    try:
        document = load_workflow(workflow_id)
    except (ValueError, WorkflowNotFound, WorkflowValidationError) as exc:
        return _persistence_error(exc)
    payload = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{workflow_id}.json"'},
    )


@workflows_bp.route("/api/workflows/<workflow_id>/projects", methods=["GET"])
def workflow_projects(workflow_id):
    """List the concrete project IDs created by a saved workflow."""
    denied = _require_loopback()
    if denied:
        return denied
    try:
        load_workflow(workflow_id)
        projects = project_summaries(workflow_id, output_dir=execution_manager.output_dir)
    except (ValueError, WorkflowNotFound, WorkflowValidationError) as exc:
        return _persistence_error(exc)
    except ProjectArchiveError as exc:
        return _error(exc.code, str(exc), 400)
    return jsonify({"projects": projects, "total": len(projects)})


@workflows_bp.route("/api/workflows/<workflow_id>/projects/<project_id>/archive", methods=["GET"])
def workflow_project_archive(workflow_id, project_id):
    """Download a portable ZIP containing one workflow project and its assets."""
    denied = _require_loopback()
    if denied:
        return denied
    output = tempfile.TemporaryFile(mode="w+b")
    try:
        create_archive(workflow_id, project_id, output, output_dir=execution_manager.output_dir)
        output.seek(0)
    except ProjectArchiveError as exc:
        output.close()
        status = 404 if exc.code in {"NOT_FOUND", "PROJECT_NOT_FOUND"} else 422
        return _error(exc.code, str(exc), status)
    return send_file(
        output,
        mimetype="application/vnd.scripttoscene.project+zip",
        as_attachment=True,
        download_name=f"{workflow_id}_{project_id}.sts-project.zip",
        conditional=False,
    )


@workflows_bp.route("/api/workflow/projects/restore", methods=["POST"])
def workflow_project_restore():
    """Restore an integrity-checked project archive under original or new IDs."""
    denied = _require_loopback()
    if denied:
        return denied
    request.max_content_length = MAX_ARCHIVE_BYTES + 1024 * 1024
    declared = request.content_length
    if declared is not None and declared > request.max_content_length:
        return _error("REQUEST_TOO_LARGE", "Project archive exceeds the 2 GiB limit", 413)
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _error("BAD_REQUEST", "Multipart field 'file' is required", 400)
    buffered = tempfile.TemporaryFile(mode="w+b")
    try:
        shutil.copyfileobj(upload.stream, buffered, length=1024 * 1024)
        buffered.seek(0)
        result = restore_archive(
            buffered, output_dir=execution_manager.output_dir,
            project_id_mode=request.form.get("project_id_mode", "new"),
            workflow_id_mode=request.form.get("workflow_id_mode", "new"),
        )
    except ProjectArchiveError as exc:
        status = 409 if exc.code == "RESTORE_CONFLICT" else 422
        if exc.code == "BAD_REQUEST":
            status = 400
        return _error(exc.code, str(exc), status)
    finally:
        buffered.close()
    return jsonify({
        "workflow": result.workflow,
        "project_id": result.project_id,
        "original_workflow_id": result.original_workflow_id,
        "original_project_id": result.original_project_id,
        "executions": result.executions,
        "files_restored": result.files_restored,
    }), 201


@workflows_bp.route("/api/workflow/run", methods=["POST"])
def workflow_run():
    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body()
    if failure:
        return failure
    has_id = "workflow_id" in body
    has_snapshot = "workflow" in body
    if has_id == has_snapshot:
        return _error("BAD_REQUEST", "Provide exactly one of workflow_id or workflow", 400)
    targets = body.get("target_node_ids", [])
    if not isinstance(targets, list) or any(not isinstance(item, str) for item in targets):
        return _error("BAD_REQUEST", "target_node_ids must be an array of node IDs", 400)
    if not isinstance(body.get("force", False), bool):
        return _error("BAD_REQUEST", "force must be a boolean", 400)
    try:
        if has_id:
            workflow = load_workflow(body.get("workflow_id"))
        elif isinstance(body.get("workflow"), dict):
            workflow = body["workflow"]
        else:
            return _error("BAD_REQUEST", "workflow must be an object", 400)
        execution_id, project_id = execution_manager.start(
            workflow,
            run_mode=body.get("run_mode", "full"),
            target_node_ids=targets,
            project_id=body.get("project_id"),
            force=body.get("force", False),
        )
    except WorkflowNotFound:
        return _error("NOT_FOUND", "Workflow not found", 404)
    except ExecutionRequestError as exc:
        status = 422 if exc.code in {"WORKFLOW_INVALID", "MISSING_REQUIRED_INPUT"} else 400
        return _error(exc.code, str(exc), status, exc.details)
    except ValueError as exc:
        return _error("BAD_REQUEST", str(exc), 400)
    return jsonify({
        "execution_id": execution_id,
        "project_id": project_id,
        "status": "queued",
    }), 202


@workflows_bp.route("/api/workflow/executions/<execution_id>/stop", methods=["POST"])
def workflow_execution_stop(execution_id):
    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body()
    if failure:
        return failure
    if body:
        return _error("BAD_REQUEST", "Stop request body must be empty", 400)
    try:
        status = execution_manager.stop(execution_id)
    except FileNotFoundError:
        return _error("NOT_FOUND", "Execution not found", 404)
    except ExecutionRequestError as exc:
        return _error(exc.code, str(exc), 409, exc.details)
    except ValueError as exc:
        return _error("BAD_REQUEST", str(exc), 400)
    return jsonify({"execution_id": execution_id, "status": status}), 202


@workflows_bp.route("/api/workflow/queue", methods=["GET"])
def workflow_queue_list():
    denied = _require_loopback()
    if denied:
        return denied
    workflow_id = request.args.get("workflow_id", "")
    try:
        limit = int(request.args.get("limit", 100))
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        items, total = execution_manager.list_queue(workflow_id, limit=limit)
    except ValueError as exc:
        return _error("BAD_REQUEST", str(exc), 400)
    return jsonify({"queue": items, "total": total})


@workflows_bp.route("/api/workflow/queue/<execution_id>/cancel", methods=["POST"])
def workflow_queue_cancel(execution_id):
    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body()
    if failure:
        return failure
    if body:
        return _error("BAD_REQUEST", "Cancel request body must be empty", 400)
    try:
        status = execution_manager.cancel_pending(execution_id)
    except FileNotFoundError:
        return _error("NOT_FOUND", "Execution not found", 404)
    except ExecutionRequestError as exc:
        return _error(exc.code, str(exc), 409, exc.details)
    except ValueError as exc:
        return _error("BAD_REQUEST", str(exc), 400)
    return jsonify({"execution_id": execution_id, "status": status}), 202


@workflows_bp.route("/api/workflow/notifications", methods=["GET"])
def workflow_notifications_list():
    denied = _require_loopback()
    if denied:
        return denied
    workflow_id = request.args.get("workflow_id", "")
    try:
        limit = int(request.args.get("limit", 100))
        items, total, unseen = list_notifications(
            workflow_id, output_dir=execution_manager.output_dir, limit=limit
        )
    except (TypeError, ValueError) as exc:
        return _error("BAD_REQUEST", str(exc), 400)
    return jsonify({"notifications": items, "total": total, "unseen": unseen})


@workflows_bp.route("/api/workflow/notifications/seen", methods=["POST"])
def workflow_notifications_seen():
    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body()
    if failure:
        return failure
    if set(body) != {"workflow_id"}:
        return _error("BAD_REQUEST", "Body must contain only workflow_id", 400)
    try:
        changed = mark_notifications_seen(
            body.get("workflow_id"), output_dir=execution_manager.output_dir
        )
    except ValueError as exc:
        return _error("BAD_REQUEST", str(exc), 400)
    return jsonify({"seen": True, "updated": changed})


@workflows_bp.route("/api/workflow/assets/orphans", methods=["GET"])
def workflow_asset_orphans():
    """Preview collectible assets. A preview never mutates the output tree."""
    from .asset_gc import collect_orphans

    denied = _require_loopback()
    if denied:
        return denied
    return jsonify(collect_orphans(output_dir=execution_manager.output_dir, dry_run=True))


@workflows_bp.route("/api/workflow/assets/gc", methods=["POST"])
def workflow_asset_gc():
    """Collect only caller-selected paths that remain orphaned on a fresh scan."""
    from .asset_gc import collect_orphans

    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body(allow_empty=True)
    if failure:
        return failure
    if set(body) - {"paths", "dry_run"}:
        return _error("BAD_REQUEST", "Body may contain only paths and dry_run", 400)
    dry_run = body.get("dry_run", True)
    paths = body.get("paths")
    if not isinstance(dry_run, bool):
        return _error("BAD_REQUEST", "dry_run must be a boolean", 400)
    if paths is not None and (
        not isinstance(paths, list)
        or any(not isinstance(path, str) for path in paths)
    ):
        return _error("BAD_REQUEST", "paths must be an array of strings", 400)
    try:
        report = collect_orphans(
            output_dir=execution_manager.output_dir, paths=paths, dry_run=dry_run
        )
    except ValueError as exc:
        return _error("ASSET_GC_STALE", str(exc), 409)
    status = 207 if report["failures"] else 200
    return jsonify(report), status


@workflows_bp.route("/api/workflow/executions/<execution_id>", methods=["GET"])
def workflow_execution_get(execution_id):
    denied = _require_loopback()
    if denied:
        return denied
    try:
        return jsonify({"execution": load_execution(execution_id)})
    except FileNotFoundError:
        return _error("NOT_FOUND", "Execution not found", 404)
    except ValueError as exc:
        return _error("BAD_REQUEST", str(exc), 400)


@workflows_bp.route("/api/workflow/executions", methods=["GET"])
def workflow_executions_list():
    denied = _require_loopback()
    if denied:
        return denied
    workflow_id = request.args.get("workflow_id", "")
    try:
        limit = int(request.args.get("limit", 100))
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        executions, total = list_executions(workflow_id, limit=limit)
    except ValueError as exc:
        return _error("BAD_REQUEST", str(exc), 400)
    return jsonify({"executions": executions, "total": total})


@workflows_bp.route("/api/workflow/executions/<execution_id>/events", methods=["GET"])
def workflow_execution_events(execution_id):
    denied = _require_loopback()
    if denied:
        return denied
    try:
        record = load_execution(execution_id)
    except FileNotFoundError:
        return _error("NOT_FOUND", "Execution not found", 404)
    except ValueError as exc:
        return _error("BAD_REQUEST", str(exc), 400)
    raw_last = request.headers.get("Last-Event-ID", "0")
    try:
        last_sequence = int(raw_last)
        if last_sequence < 0:
            raise ValueError
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "Last-Event-ID must be a non-negative integer", 400)

    stream = execution_manager.events.get(execution_id)
    if stream is None:
        stream = execution_manager.events.create(execution_id)
        if record.get("status") in TERMINAL_STATUSES:
            stream.emit({
                "type": "execution_snapshot",
                "node_id": None,
                "status": record["status"],
                "snapshot": record,
            })

    def generate():
        snapshot = lambda: load_execution(execution_id)
        for event in stream.subscribe(last_sequence, snapshot=snapshot):
            yield ": keep-alive\n\n" if event is None else sse_frame(event)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
