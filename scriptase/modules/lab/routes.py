"""Prompt Lab HTTP routes. Transport only — all logic lives in `service`."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from scriptase.modules.lab.service import list_recent_prompts, preview_prompt

lab_bp = Blueprint("lab", __name__)


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
