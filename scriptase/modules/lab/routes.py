"""Prompt Lab HTTP routes. Transport only — all logic lives in the services.

Every variant/experiment route is scoped by `lab_id` (query for GET, body for
mutations), defaulting to the script lab, so many labs share this surface.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from scriptase.modules.lab.experiment import (
    ExperimentError,
    build_prompt,
    list_runs,
    run_experiment,
    variant_leaderboard,
)
from scriptase.modules.lab.registry import get_lab, list_labs
from scriptase.modules.lab.service import list_recent_prompts, preview_prompt
from scriptase.modules.lab.variants import (
    create_variant,
    delete_variant,
    get_variant,
    list_variants,
    update_variant,
)

lab_bp = Blueprint("lab", __name__)

_DEFAULT_LAB = "script_prompt"


def _err(code: str, message: str, status: int):
    """The app-standard nested error shape the frontend api client parses."""
    return jsonify({"error": {"code": code, "message": message}}), status


def _body() -> dict | None:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _lab_id_from_query() -> str:
    return (request.args.get("lab") or _DEFAULT_LAB).strip() or _DEFAULT_LAB


def _lab_id_from_body(body: dict | None) -> str:
    return str((body or {}).get("lab_id") or _DEFAULT_LAB).strip() or _DEFAULT_LAB


# ── Lab catalog (self-describing framework) ─────────────────────────────────


@lab_bp.get("/api/lab/labs")
def labs():
    """Every registered lab's metadata: name, purpose, how-to, what it measures."""
    return jsonify({"labs": [lab.meta() for lab in list_labs()]})


# ── Prompt inspection (transparency) ────────────────────────────────────────


@lab_bp.post("/api/lab/prompt-preview")
def prompt_preview():
    """Compose the system + user prompt for a set of inputs (no generation)."""
    data = request.get_json(silent=True)
    if data is not None and not isinstance(data, dict):
        return _err("BAD_REQUEST", "Request body must be a JSON object", 400)
    return jsonify(preview_prompt(data or {}))


@lab_bp.get("/api/lab/prompts")
def recent_prompts():
    """Recent generated scripts that carry a saved prompt, newest first."""
    try:
        limit = int(request.args.get("limit", 30))
    except (TypeError, ValueError):
        limit = 30
    return jsonify({"prompts": list_recent_prompts(limit=limit)})


# ── Variants (config) ───────────────────────────────────────────────────────


@lab_bp.get("/api/lab/variants")
def variants():
    lab_id = _lab_id_from_query()
    if get_lab(lab_id) is None:
        return _err("UNKNOWN_LAB", "That lab does not exist", 404)
    return jsonify({"variants": list_variants(lab_id)})


@lab_bp.post("/api/lab/variants")
def variant_create():
    body = _body()
    lab_id = _lab_id_from_body(body)
    if get_lab(lab_id) is None:
        return _err("UNKNOWN_LAB", "That lab does not exist", 404)
    try:
        record = create_variant(body, lab_id)
    except ValueError as exc:
        return _err("INVALID_VARIANT", str(exc), 400)
    return jsonify({"variant": record}), 201


@lab_bp.put("/api/lab/variants/<variant_id>")
def variant_update(variant_id: str):
    body = _body()
    lab_id = _lab_id_from_body(body)
    try:
        record = update_variant(variant_id, body, lab_id)
    except ValueError as exc:
        return _err("INVALID_VARIANT", str(exc), 400)
    return jsonify({"variant": record})


@lab_bp.delete("/api/lab/variants/<variant_id>")
def variant_delete(variant_id: str):
    lab_id = _lab_id_from_query()
    if get_variant(variant_id, lab_id) is None:
        return _err("UNKNOWN_VARIANT", "That variant does not exist", 404)
    if not delete_variant(variant_id, lab_id):
        return _err("VARIANT_PROTECTED", "This variant cannot be deleted", 400)
    return jsonify({"deleted": variant_id})


# ── Experiments (test + measure) ────────────────────────────────────────────


@lab_bp.post("/api/lab/prompt-build")
def prompt_build():
    """Compose the prompt for a (channel, variant) without generating."""
    body = _body() or {}
    return jsonify(build_prompt(
        channel_id=body.get("channel_id") or None,
        variant_id=body.get("variant_id") or "builtin",
        overrides=body.get("overrides") or {},
        lab_id=_lab_id_from_body(body),
    ))


@lab_bp.post("/api/lab/run")
def experiment_run():
    """Generate one script for a (channel × variant × provider) and score it."""
    body = _body() or {}
    try:
        record = run_experiment(
            channel_id=body.get("channel_id") or None,
            variant_id=body.get("variant_id") or "builtin",
            provider_id=body.get("provider_id") or "script_n8n",
            overrides=body.get("overrides") or {},
            lab_id=_lab_id_from_body(body),
            # The LLM second opinion is opt-out per run (default on); it costs a
            # model call, so a caller can skip it.
            with_llm_judge=bool(body.get("with_llm_judge", True)),
        )
    except ExperimentError as exc:
        status = 404 if exc.code == "CHANNEL_NOT_FOUND" else 502
        return _err(exc.code, str(exc.args[0]), status)
    except Exception:  # noqa: BLE001 — never leak a bodyless 500 to the Lab UI
        return _err("RUN_FAILED", "The run failed unexpectedly. See the server log.", 500)
    return jsonify({"run": record})


@lab_bp.get("/api/lab/runs")
def runs():
    lab_id = _lab_id_from_query()
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    return jsonify({
        "runs": list_runs(limit=limit, lab_id=lab_id),
        "leaderboard": variant_leaderboard(lab_id),
    })
