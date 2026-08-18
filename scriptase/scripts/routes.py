"""Thin CRUD transport for Script Studio documents."""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from scriptase.scripts.models import SCRIPT_ID_RE
from scriptase.scripts.store import (
    ScriptConflict,
    ScriptNotFound,
    ScriptValidationError,
    create_script,
    delete_script,
    get_script,
    list_scripts,
    resolve_narration_audio,
    script_summary,
    update_script,
)


MAX_SCRIPT_BODY_BYTES = 2 * 1024 * 1024
scripts_bp = Blueprint("studio_scripts", __name__)


def _error(code: str, message: str, status: int, details=None):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def _json_body():
    declared = request.content_length
    if declared is not None and declared > MAX_SCRIPT_BODY_BYTES:
        return None, _error("REQUEST_TOO_LARGE", "Request exceeds the 2 MiB limit", 413)
    raw = request.stream.read(MAX_SCRIPT_BODY_BYTES + 1)
    if len(raw) > MAX_SCRIPT_BODY_BYTES:
        return None, _error("REQUEST_TOO_LARGE", "Request exceeds the 2 MiB limit", 413)
    if not raw or not request.is_json:
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    if not isinstance(body, dict):
        return None, _error("BAD_REQUEST", "Request body must be a JSON object", 400)
    return body, None


def _draft(body: dict):
    source = body.get("script") if isinstance(body.get("script"), dict) else body
    return {
        key: value
        for key, value in source.items()
        if key not in {
            "id", "version", "schema_version", "created_at", "updated_at",
            "word_count", "estimated_duration_s", "expected_version",
        }
    }


def _store_error(exc: Exception):
    if isinstance(exc, ScriptNotFound):
        return _error("NOT_FOUND", "Script not found", 404)
    if isinstance(exc, ScriptConflict):
        return _error("SCRIPT_CONFLICT", "Script changed since it was opened", 409)
    if isinstance(exc, ScriptValidationError):
        return _error(
            "SCRIPT_INVALID",
            "Script document failed schema validation",
            422,
            {"problems": exc.problems},
        )
    if isinstance(exc, ValueError):
        return _error("BAD_REQUEST", str(exc), 400)
    raise exc


def _expected_version(body: dict) -> int | None:
    value = body.get("expected_version")
    if value is None and isinstance(body.get("script"), dict):
        value = body["script"].get("version")
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("expected_version must be an integer")
    parsed = int(value)
    if parsed < 1:
        raise ValueError("expected_version must be at least 1")
    return parsed


def _detail(document):
    payload = document.to_document()
    audio = resolve_narration_audio(document)
    return {
        "script": payload,
        "narration_audio": audio.to_document() if audio is not None else None,
    }


@scripts_bp.get("/api/scripts")
def scripts_list():
    try:
        limit = int(request.args.get("limit", 200))
        items = list_scripts(
            channel_id=request.args.get("channel_id") or None,
            origin=request.args.get("origin") or None,
            query=request.args.get("q") or None,
            limit=limit,
        )
    except (ScriptValidationError, ValueError) as exc:
        return _store_error(exc)
    return jsonify({"scripts": [script_summary(item) for item in items], "total": len(items)})


@scripts_bp.post("/api/scripts")
def scripts_create():
    body, error = _json_body()
    if error:
        return error
    try:
        document = create_script(_draft(body))
    except (ScriptValidationError, ValueError) as exc:
        return _store_error(exc)
    response = jsonify(_detail(document))
    response.status_code = 201
    response.headers["Location"] = f"/api/scripts/{document.id}"
    return response


@scripts_bp.get("/api/scripts/<script_id>")
def scripts_get(script_id: str):
    if not SCRIPT_ID_RE.fullmatch(script_id or ""):
        return _error("BAD_REQUEST", "script_id must match scr_[A-Z0-9]{6}", 400)
    try:
        return jsonify(_detail(get_script(script_id)))
    except (ScriptNotFound, ScriptValidationError, ValueError) as exc:
        return _store_error(exc)


@scripts_bp.put("/api/scripts/<script_id>")
def scripts_update(script_id: str):
    if not SCRIPT_ID_RE.fullmatch(script_id or ""):
        return _error("BAD_REQUEST", "script_id must match scr_[A-Z0-9]{6}", 400)
    body, error = _json_body()
    if error:
        return error
    try:
        document = update_script(
            script_id, _draft(body), expected_version=_expected_version(body)
        )
        return jsonify(_detail(document))
    except (ScriptNotFound, ScriptConflict, ScriptValidationError, ValueError) as exc:
        return _store_error(exc)


@scripts_bp.delete("/api/scripts/<script_id>")
def scripts_delete(script_id: str):
    if not SCRIPT_ID_RE.fullmatch(script_id or ""):
        return _error("BAD_REQUEST", "script_id must match scr_[A-Z0-9]{6}", 400)
    try:
        expected = request.args.get("expected_version")
        delete_script(
            script_id,
            expected_version=int(expected) if expected is not None else None,
        )
    except (ScriptNotFound, ScriptConflict, ScriptValidationError, ValueError) as exc:
        return _store_error(exc)
    return "", 204


__all__ = ["scripts_bp"]
