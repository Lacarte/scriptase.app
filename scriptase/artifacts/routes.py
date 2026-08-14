"""Artifact library, input-picker, and attempt-history routes (steps 4.1 / 4.3).

Thin transport over the artifact index, ``input_sources`` resolver, and
``history`` comparison helpers. Business logic stays out of this module.

Endpoints:

* ``GET  /api/artifacts`` — browse the library (filter by job/kind/scene)
* ``GET  /api/artifacts/<id>`` — one index record
* ``GET  /api/artifacts/<id>/payload`` — materialize as a port payload
* ``GET  /api/artifacts/<id>/history`` — version chain + side-by-side pair
* ``GET  /api/artifacts/history`` — chain by job/kind/scene
* ``GET  /api/artifacts/compare`` — explicit left/right comparison
* ``POST /api/artifacts/upload`` — managed media/JSON upload → index entry
* ``POST /api/artifacts/resolve-inputs`` — dry-run input bindings → overrides

Uploads are written under ``output/library/`` (or a Job-owned path when
``job_id`` is supplied) and registered as Artifacts. Browser-supplied
filesystem paths are never accepted.
"""

from __future__ import annotations

import json
import os
import uuid

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from scriptase.artifacts.history import (
    HistoryError,
    compare_attempts,
    history_for_artifact,
    history_for_chain,
)
from scriptase.artifacts.input_sources import (
    INPUT_SOURCES,
    KIND_TO_PORT_TYPE,
    LIBRARY_JOB_ID,
    PORT_TYPE_TO_KIND,
    InputSourceError,
    artifact_summary,
    materialize_artifact,
    port_types_for_workflow,
    resolve_input_bindings,
)
from scriptase.artifacts.models import ARTIFACT_ID_RE, ARTIFACT_KINDS
from scriptase.artifacts.store import (
    ArtifactNotFound,
    ArtifactSuperseded,
    ArtifactValidationError,
    get_artifact,
    list_artifacts,
    register_artifact,
)
from scriptase.shared.security import is_loopback_remote, sanitize_folder_name

artifacts_bp = Blueprint("artifacts", __name__)

# 25 MiB cap for a single library upload (scene JSON / still / short clip).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024
MAX_JSON_BODY_BYTES = 2 * 1024 * 1024

# Extension → kind defaults when the client omits ``kind``.
_EXT_KIND: dict[str, str] = {
    "json": "scene_spec",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "webp": "image",
    "gif": "image",
    "wav": "audio",
    "mp3": "audio",
    "m4a": "audio",
    "ogg": "audio",
    "mp4": "video",
    "webm": "video",
    "mov": "video",
    "srt": "captions",
    "vtt": "captions",
}

_ALLOWED_EXTENSIONS = frozenset(_EXT_KIND)


def _error(code: str, message: str, status: int, details=None):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


@artifacts_bp.errorhandler(RequestEntityTooLarge)
def _request_entity_too_large(_exc):
    return _error("REQUEST_TOO_LARGE", "Request body exceeds the allowed size", 413)


def _require_loopback():
    if not is_loopback_remote(request.remote_addr):
        return _error("FORBIDDEN", "Artifact routes are loopback-only", 403)
    return None


def _json_body(*, allow_empty: bool = False):
    declared = request.content_length
    if declared is not None and declared > MAX_JSON_BODY_BYTES:
        return None, _error(
            "REQUEST_TOO_LARGE", "Request exceeds the 2 MiB limit", 413
        )
    raw = request.stream.read(MAX_JSON_BODY_BYTES + 1)
    if len(raw) > MAX_JSON_BODY_BYTES:
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


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@artifacts_bp.route("/api/artifacts", methods=["GET"])
def artifacts_list():
    """Browse the artifact library / index.

    Query:
      job_id              filter by owning job (use ``library`` for uploads)
      scene_id            filter by scene
      kind                filter by kind vocabulary
      include_superseded  default true
      limit               1–500 (default 100)
    """
    denied = _require_loopback()
    if denied:
        return denied
    try:
        limit = int(request.args.get("limit") or 100)
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "limit must be an integer", 400)
    limit = max(1, min(limit, 500))

    job_id = (request.args.get("job_id") or "").strip() or None
    scene_id = (request.args.get("scene_id") or "").strip() or None
    kind = (request.args.get("kind") or "").strip() or None
    if kind is not None and kind not in ARTIFACT_KINDS:
        return _error(
            "BAD_REQUEST",
            f"kind must be one of: {', '.join(ARTIFACT_KINDS)}",
            400,
        )
    include_superseded = _truthy(
        request.args.get("include_superseded"), default=True
    )

    items = list_artifacts(
        job_id=job_id,
        scene_id=scene_id,
        kind=kind,
        include_superseded=include_superseded,
        limit=limit,
    )
    return jsonify({
        "artifacts": [artifact_summary(item) for item in items],
        "total": len(items),
        "sources": list(INPUT_SOURCES),
        "kinds": list(ARTIFACT_KINDS),
        "port_kind_map": dict(PORT_TYPE_TO_KIND),
        "kind_port_map": dict(KIND_TO_PORT_TYPE),
        "library_job_id": LIBRARY_JOB_ID,
    })


def _history_error(exc: HistoryError):
    status = 400
    if exc.code == "ARTIFACT_NOT_FOUND":
        status = 404
    elif exc.code == "ARTIFACT_INVALID":
        status = 422
    return _error(exc.code, exc.message, status, exc.details)


# Static path segments registered before ``/<artifact_id>`` so they are never
# captured as an id (Flask ranks static higher, but keep the order obvious).
@artifacts_bp.route("/api/artifacts/history", methods=["GET"])
def artifacts_history_by_chain():
    """Attempt history for an explicit (job_id, kind, scene_id?) chain."""
    denied = _require_loopback()
    if denied:
        return denied
    job_id = (request.args.get("job_id") or "").strip()
    kind = (request.args.get("kind") or "").strip()
    scene_id = (request.args.get("scene_id") or "").strip() or None
    if not job_id:
        return _error("BAD_REQUEST", "job_id is required", 400)
    if not kind:
        return _error("BAD_REQUEST", "kind is required", 400)
    try:
        payload = history_for_chain(job_id=job_id, kind=kind, scene_id=scene_id)
    except HistoryError as exc:
        return _history_error(exc)
    return jsonify(payload)


@artifacts_bp.route("/api/artifacts/compare", methods=["GET"])
def artifacts_compare():
    """Side-by-side comparison of two artifact versions.

    Query: ``left`` / ``right`` (or ``a`` / ``b``) artifact ids.
    """
    denied = _require_loopback()
    if denied:
        return denied
    left = (
        (request.args.get("left") or request.args.get("a") or "").strip()
    )
    right = (
        (request.args.get("right") or request.args.get("b") or "").strip()
    )
    if not ARTIFACT_ID_RE.fullmatch(left or ""):
        return _error("BAD_REQUEST", "left must match art_[A-Z0-9]{6}", 400)
    if not ARTIFACT_ID_RE.fullmatch(right or ""):
        return _error("BAD_REQUEST", "right must match art_[A-Z0-9]{6}", 400)
    try:
        payload = compare_attempts(left, right)
    except HistoryError as exc:
        return _history_error(exc)
    return jsonify(payload)


@artifacts_bp.route("/api/artifacts/<artifact_id>", methods=["GET"])
def artifacts_get(artifact_id: str):
    denied = _require_loopback()
    if denied:
        return denied
    if not ARTIFACT_ID_RE.fullmatch(artifact_id or ""):
        return _error("BAD_REQUEST", "artifact_id must match art_[A-Z0-9]{6}", 400)
    try:
        artifact = get_artifact(artifact_id)
    except ArtifactNotFound:
        return _error("ARTIFACT_NOT_FOUND", "Artifact not found", 404)
    except ArtifactValidationError as exc:
        return _error(
            "ARTIFACT_INVALID",
            "Artifact document failed validation",
            422,
            {"problems": exc.problems},
        )
    return jsonify({"artifact": artifact_summary(artifact)})


@artifacts_bp.route("/api/artifacts/<artifact_id>/payload", methods=["GET"])
def artifacts_payload(artifact_id: str):
    """Materialize an artifact as a port payload for the input picker."""
    denied = _require_loopback()
    if denied:
        return denied
    if not ARTIFACT_ID_RE.fullmatch(artifact_id or ""):
        return _error("BAD_REQUEST", "artifact_id must match art_[A-Z0-9]{6}", 400)
    port_type = (request.args.get("port_type") or "").strip() or None
    try:
        artifact = get_artifact(artifact_id)
        payload = materialize_artifact(artifact, port_type=port_type)
    except ArtifactNotFound:
        return _error("ARTIFACT_NOT_FOUND", "Artifact not found", 404)
    except InputSourceError as exc:
        status = 404 if exc.code in {"ARTIFACT_NOT_FOUND", "ARTIFACT_MISSING"} else 400
        if exc.code == "ARTIFACT_SUPERSEDED":
            status = 409
        if exc.code == "ARTIFACT_INVALID":
            status = 422
        return _error(exc.code, exc.message, status, exc.details or None)
    except ArtifactValidationError as exc:
        return _error(
            "ARTIFACT_INVALID",
            "Artifact document failed validation",
            422,
            {"problems": exc.problems},
        )
    return jsonify({
        "artifact_id": artifact_id,
        "port_type": port_type or KIND_TO_PORT_TYPE.get(artifact.kind),
        "payload": payload,
        "source_artifact_ids": [artifact_id],
    })


@artifacts_bp.route("/api/artifacts/<artifact_id>/history", methods=["GET"])
def artifacts_history(artifact_id: str):
    """Version chain + default side-by-side pair for the artifact's chain.

    Surfaces 1.2 immutable versions with provider instance, seed, and prompt
    revision for each attempt (step 4.3).
    """
    denied = _require_loopback()
    if denied:
        return denied
    if not ARTIFACT_ID_RE.fullmatch(artifact_id or ""):
        return _error("BAD_REQUEST", "artifact_id must match art_[A-Z0-9]{6}", 400)
    try:
        payload = history_for_artifact(artifact_id)
    except HistoryError as exc:
        return _history_error(exc)
    return jsonify(payload)


@artifacts_bp.route("/api/artifacts/upload", methods=["POST"])
def artifacts_upload():
    """Managed upload into the artifact library (or a Job's chain).

    Multipart fields:
      file       required
      kind       optional (inferred from extension)
      job_id     optional (default ``library``)
      scene_id   optional
    """
    denied = _require_loopback()
    if denied:
        return denied
    request.max_content_length = MAX_UPLOAD_REQUEST_BYTES
    declared = request.content_length
    if declared is not None and declared > MAX_UPLOAD_REQUEST_BYTES:
        return _error("REQUEST_TOO_LARGE", "Upload exceeds the 25 MB limit", 413)

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return _error("BAD_REQUEST", "Multipart field 'file' is required", 400)

    original = upload.filename
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in _ALLOWED_EXTENSIONS:
        return _error(
            "BAD_REQUEST",
            f"Unsupported file type; allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
            400,
        )

    kind = (request.form.get("kind") or "").strip() or _EXT_KIND.get(ext, "")
    if kind not in ARTIFACT_KINDS:
        return _error(
            "BAD_REQUEST",
            f"kind must be one of: {', '.join(ARTIFACT_KINDS)}",
            400,
        )

    job_id = (request.form.get("job_id") or "").strip() or LIBRARY_JOB_ID
    scene_id = (request.form.get("scene_id") or "").strip() or None

    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return _error("REQUEST_TOO_LARGE", "Upload exceeds the 25 MB limit", 413)
    if not data:
        return _error("BAD_REQUEST", "Uploaded file is empty", 400)

    stem = sanitize_folder_name(original.rsplit(".", 1)[0], max_len=40) or "upload"
    filename = f"{stem}_{uuid.uuid4().hex[:8]}.{ext}"
    # Library uploads land under output/library/; Job-owned under output/library/{job_id}/.
    if job_id == LIBRARY_JOB_ID:
        rel_dir = "library"
    else:
        safe_job = sanitize_folder_name(job_id, max_len=40) or "job"
        rel_dir = f"library/{safe_job}"
    rel_path = f"{rel_dir}/{filename}"
    # Resolve the managed root at request time so tests can rebind the store.
    from scriptase.artifacts import store as artifact_store

    output_root = artifact_store._output_dir
    abs_dir = os.path.join(output_root, *rel_dir.split("/"))
    os.makedirs(abs_dir, exist_ok=True)
    abs_path = os.path.join(abs_dir, filename)
    with open(abs_path, "wb") as handle:
        handle.write(data)

    try:
        artifact = register_artifact(
            job_id=job_id,
            kind=kind,
            path=rel_path,
            scene_id=scene_id,
            provenance_ref="upload",
            from_sample_data=False,
        )
    except ArtifactValidationError as exc:
        try:
            os.remove(abs_path)
        except OSError:
            pass
        return _error(
            "ARTIFACT_INVALID",
            "Could not register uploaded artifact",
            422,
            {"problems": exc.problems},
        )
    except Exception as exc:
        try:
            os.remove(abs_path)
        except OSError:
            pass
        return _error("BAD_REQUEST", str(exc), 400)

    return jsonify({"artifact": artifact_summary(artifact)}), 201


@artifacts_bp.route("/api/artifacts/resolve-inputs", methods=["POST"])
def artifacts_resolve_inputs():
    """Dry-run: turn input_bindings into input_overrides + source ids.

    Body:
      input_bindings   {node_id: {port_id: binding}}
      current_job_id?  context for current_job sources
      workflow?        optional; used to infer port types from the registry
    """
    denied = _require_loopback()
    if denied:
        return denied
    body, failure = _json_body()
    if failure:
        return failure

    bindings = body.get("input_bindings")
    if not isinstance(bindings, dict):
        return _error("BAD_REQUEST", "input_bindings must be an object", 400)
    current_job_id = body.get("current_job_id")
    if current_job_id is not None and not isinstance(current_job_id, str):
        return _error("BAD_REQUEST", "current_job_id must be a string", 400)

    port_types = None
    workflow = body.get("workflow")
    if isinstance(workflow, dict):
        port_types = port_types_for_workflow(workflow)

    try:
        overrides, sources, sample_fed = resolve_input_bindings(
            bindings,
            current_job_id=current_job_id,
            port_types=port_types,
        )
    except InputSourceError as exc:
        status = 400
        if exc.code in {"ARTIFACT_NOT_FOUND", "ARTIFACT_MISSING"}:
            status = 404
        elif exc.code == "ARTIFACT_SUPERSEDED":
            status = 409
        elif exc.code == "RUN_DEPS":
            status = 422
        return _error(exc.code, exc.message, status, exc.details or None)

    return jsonify({
        "input_overrides": overrides,
        "sample_fed_node_ids": sample_fed,
        "source_artifact_ids": sources,
    })


__all__ = ["artifacts_bp"]
