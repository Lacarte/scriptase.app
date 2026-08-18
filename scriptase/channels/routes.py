"""Channel CRUD routes — step 1.3.

Thin transport over ``scriptase.channels.store`` and the niche-preset seeder.
Business logic stays out of this module (CLAUDE.md: no imports *from* a
routes.py for behaviour).

Logo upload is **not** here: the managed branding endpoint at
``POST /api/workflow/branding`` already owns type/size validation into
``output/branding/``. The Channel document stores only the managed ref
(``branding/{filename}``) in ``branding.logo_asset_id``.
"""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from scriptase.channels.models import CHANNEL_ID_RE
from scriptase.channels.presets import (
    get_presets,
    list_starter_mappings,
    seed_starter_channels,
)
from scriptase.channels.store import (
    ChannelConflict,
    ChannelNotFound,
    ChannelValidationError,
    channel_summary,
    create_channel,
    default_draft,
    delete_channel,
    get_channel,
    list_channels,
    update_channel,
)

# 2 MiB JSON body cap — Channel drafts are small; match workflow document limit.
MAX_CHANNEL_BODY_BYTES = 2 * 1024 * 1024

channels_bp = Blueprint("channels", __name__)


def _error(code: str, message: str, status: int, details=None):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def _json_body(*, allow_empty: bool = False):
    """Parse a bounded JSON object body (chunked-transfer safe)."""
    declared = request.content_length
    if declared is not None and declared > MAX_CHANNEL_BODY_BYTES:
        return None, _error(
            "REQUEST_TOO_LARGE", "Request exceeds the 2 MiB limit", 413
        )
    raw = request.stream.read(MAX_CHANNEL_BODY_BYTES + 1)
    if len(raw) > MAX_CHANNEL_BODY_BYTES:
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
    if isinstance(exc, ChannelNotFound):
        return _error("NOT_FOUND", "Channel not found", 404)
    if isinstance(exc, ChannelConflict):
        return _error(
            "CHANNEL_CONFLICT",
            "Channel changed since it was opened",
            409,
        )
    if isinstance(exc, ChannelValidationError):
        return _error(
            "CHANNEL_INVALID",
            "Channel document failed schema validation",
            422,
            {"problems": exc.problems},
        )
    if isinstance(exc, ValueError):
        return _error("BAD_REQUEST", str(exc), 400)
    raise exc


def _draft_from_body(body: dict):
    """Accept either a bare draft or ``{channel: draft}``."""
    if isinstance(body.get("channel"), dict):
        return body["channel"]
    # Drop envelope keys if the client sent them at the top level.
    return {
        key: value
        for key, value in body.items()
        if key not in {"expected_version", "channel"}
    }


@channels_bp.route("/api/channels/prompt-preview", methods=["POST"])
def channels_prompt_preview():
    """Render the editor's live example with the production composer."""
    body, error = _json_body()
    if error:
        return error
    from scriptase.prompts.visual import compose_visual_prompt

    subject = body.get("scene_subject") or "A lone traveler finds a glowing door in the rain"
    return jsonify({
        "prompt": compose_visual_prompt(
            subject,
            body.get("visual_style"),
            body.get("mood"),
            body.get("aspect_ratio"),
        )
    })


@channels_bp.route("/api/channels", methods=["GET"])
def channels_list():
    """List channels (newest first). Auto-seeds starter Channels once.

    Query:
      limit          1–500 (default 200)
      seed           when ``1``/``true`` (default), run the idempotent seeder
      starters_only  when ``1``/``true``, return only seeded starters
    """
    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        return _error("BAD_REQUEST", "limit must be an integer", 400)
    if not 1 <= limit <= 500:
        return _error("BAD_REQUEST", "limit must be between 1 and 500", 400)

    seed_flag = (request.args.get("seed", "1") or "1").strip().lower()
    seed_result = None
    if seed_flag not in {"0", "false", "no", "off"}:
        seed_result = seed_starter_channels()

    items = list_channels(limit=limit)
    starters_only = (request.args.get("starters_only", "") or "").strip().lower()
    mappings = list_starter_mappings()
    starter_ids = set(mappings.values())
    if starters_only in {"1", "true", "yes", "on"}:
        items = [item for item in items if item.id in starter_ids]

    payload = {
        "channels": [channel_summary(item) for item in items],
        "total": len(items),
        "starter_mappings": mappings,
    }
    if seed_result is not None:
        payload["seed"] = {
            "created": seed_result["created"],
            "skipped": seed_result["skipped"],
            "total_presets": seed_result["total_presets"],
        }
    return jsonify(payload)


@channels_bp.route("/api/channels", methods=["POST"])
def channels_create():
    """Create a Channel from a draft body."""
    body, error = _json_body()
    if error:
        return error
    draft = _draft_from_body(body)
    if not draft:
        # Blank create: use the structured default pattern.
        draft = default_draft(name=(body.get("name") or "New Channel"))
    try:
        document = create_channel(draft)
    except (ChannelValidationError, ValueError) as exc:
        return _store_error(exc)
    response = jsonify({"channel": document.to_document()})
    response.status_code = 201
    response.headers["Location"] = f"/api/channels/{document.id}"
    return response


@channels_bp.route("/api/channels/seed", methods=["POST"])
def channels_seed():
    """Idempotent: materialise every niche preset as a starter Channel."""
    body, error = _json_body(allow_empty=True)
    if error:
        return error
    force = bool(body.get("force", False)) if body else False
    result = seed_starter_channels(force=force)
    return jsonify({
        "created": result["created"],
        "skipped": result["skipped"],
        "total_presets": result["total_presets"],
        "channel_ids": result["channel_ids"],
        "presets": len(get_presets()),
    })


@channels_bp.route("/api/channels/defaults", methods=["GET"])
def channels_defaults():
    """Return a blank draft + the niche-preset catalog for the editor."""
    return jsonify({
        "draft": default_draft(),
        "presets": get_presets(),
        "starter_mappings": list_starter_mappings(),
    })


@channels_bp.route("/api/channels/<channel_id>", methods=["GET"])
def channels_get(channel_id: str):
    if not CHANNEL_ID_RE.fullmatch(channel_id or ""):
        return _error("BAD_REQUEST", "channel_id must match ch_[A-Z0-9]{6}", 400)
    try:
        document = get_channel(channel_id)
    except (ChannelNotFound, ChannelValidationError, ValueError) as exc:
        return _store_error(exc)
    return jsonify({"channel": document.to_document()})


@channels_bp.route("/api/channels/<channel_id>/cost", methods=["GET"])
def channels_cost_report(channel_id: str):
    """Channel-level cost rollup across its Jobs (step 9.3)."""
    if not CHANNEL_ID_RE.fullmatch(channel_id or ""):
        return _error("BAD_REQUEST", "channel_id must match ch_[A-Z0-9]{6}", 400)
    try:
        get_channel(channel_id)
    except (ChannelNotFound, ChannelValidationError, ValueError) as exc:
        return _store_error(exc)

    from scriptase.jobs.cost import build_channel_cost_report
    from scriptase.jobs.store import list_jobs

    jobs = list_jobs(channel_id=channel_id, limit=500)
    report = build_channel_cost_report(channel_id, jobs)
    return jsonify({"cost": report})


@channels_bp.route("/api/channels/<channel_id>", methods=["PUT"])
def channels_update(channel_id: str):
    if not CHANNEL_ID_RE.fullmatch(channel_id or ""):
        return _error("BAD_REQUEST", "channel_id must match ch_[A-Z0-9]{6}", 400)
    body, error = _json_body()
    if error:
        return error
    draft = _draft_from_body(body)
    expected = body.get("expected_version")
    if expected is None and isinstance(body.get("channel"), dict):
        expected = body["channel"].get("version")
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            return _error("BAD_REQUEST", "expected_version must be an integer", 400)
    try:
        document = update_channel(
            channel_id, draft, expected_version=expected
        )
    except (
        ChannelNotFound,
        ChannelConflict,
        ChannelValidationError,
        ValueError,
    ) as exc:
        return _store_error(exc)
    return jsonify({"channel": document.to_document()})


@channels_bp.route("/api/channels/<channel_id>", methods=["DELETE"])
def channels_delete(channel_id: str):
    if not CHANNEL_ID_RE.fullmatch(channel_id or ""):
        return _error("BAD_REQUEST", "channel_id must match ch_[A-Z0-9]{6}", 400)
    expected = request.args.get("expected_version")
    expected_version = None
    if expected is not None and expected != "":
        try:
            expected_version = int(expected)
        except (TypeError, ValueError):
            return _error("BAD_REQUEST", "expected_version must be an integer", 400)
    try:
        delete_channel(channel_id, expected_version=expected_version)
    except (ChannelNotFound, ChannelConflict, ValueError) as exc:
        return _store_error(exc)
    return jsonify({"deleted": True, "channel_id": channel_id})


__all__ = ["channels_bp"]
