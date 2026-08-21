"""Prompt Lab HTTP routes. Transport only — all logic lives in the services."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from scriptase.modules.lab.experiment import (
    ExperimentError,
    build_prompt,
    list_runs,
    run_experiment,
    variant_leaderboard,
)
from scriptase.modules.lab.service import list_recent_prompts, preview_prompt
from scriptase.modules.lab.variants import (
    create_variant,
    delete_variant,
    get_variant,
    list_variants,
    update_variant,
)

lab_bp = Blueprint("lab", __name__)


def _body() -> dict | None:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


# ── Prompt inspection (section 1) ───────────────────────────────────────────


@lab_bp.post("/api/lab/prompt-preview")
def prompt_preview():
    """Compose the system + user prompt for a set of inputs (no generation)."""
    data = request.get_json(silent=True)
    if data is not None and not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    return jsonify(preview_prompt(data or {}))


@lab_bp.get("/api/lab/prompts")
def recent_prompts():
    """List recent generated scripts that carry a saved prompt, newest first."""
    try:
        limit = int(request.args.get("limit", 30))
    except (TypeError, ValueError):
        limit = 30
    return jsonify({"prompts": list_recent_prompts(limit=limit)})


# ── Variants (config) ───────────────────────────────────────────────────────


@lab_bp.get("/api/lab/variants")
def variants():
    return jsonify({"variants": list_variants()})


@lab_bp.post("/api/lab/variants")
def variant_create():
    try:
        record = create_variant(_body())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"variant": record}), 201


@lab_bp.put("/api/lab/variants/<variant_id>")
def variant_update(variant_id: str):
    try:
        record = update_variant(variant_id, _body())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"variant": record})


@lab_bp.delete("/api/lab/variants/<variant_id>")
def variant_delete(variant_id: str):
    if get_variant(variant_id) is None:
        return jsonify({"error": "Unknown variant"}), 404
    if not delete_variant(variant_id):
        return jsonify({"error": "This variant cannot be deleted"}), 400
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
        )
    except ExperimentError as exc:
        status = 404 if exc.code == "CHANNEL_NOT_FOUND" else 502
        return jsonify({"error": exc.args[0], "code": exc.code}), status
    return jsonify({"run": record})


@lab_bp.get("/api/lab/runs")
def runs():
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    return jsonify({"runs": list_runs(limit=limit), "leaderboard": variant_leaderboard()})
