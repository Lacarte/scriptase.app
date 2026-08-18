"""Script-stage source modes (product §6 / contracts.md §6 / step 2.5).

Job creation (Step 0) and the Script stage share this catalog. Provider UI is
shown only in modes that need one; Paste and Manual require no script provider
at all.
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.jobs.models import EXECUTION_MODES, SOURCE_MODES

# Modes that call a script provider (story.generate / domain ``script``).
PROVIDER_REQUIRED_SOURCE_MODES: frozenset[str] = frozenset({
    "automatic",
    "topic",
    "idea",
})

# Modes that accept final narration text without AI generation.
DIRECT_TEXT_SOURCE_MODES: frozenset[str] = frozenset({"paste", "manual"})

# Human labels for the Production UI (never include ``-P``).
SOURCE_MODE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "mode": "automatic",
        "label": "Automatic",
        "description": (
            "Scriptase selects or derives a topic using Channel rules/history, "
            "then writes the script."
        ),
        "provider_required": True,
        "input_fields": ("topic", "idea"),
        "primary_field": None,
    },
    {
        "mode": "topic",
        "label": "Topic → Script",
        "description": "User supplies a topic; the script provider writes the narration.",
        "provider_required": True,
        "input_fields": ("topic",),
        "primary_field": "topic",
    },
    {
        "mode": "idea",
        "label": "Idea → Script",
        "description": (
            "User supplies a rough idea or premise; the provider expands it."
        ),
        "provider_required": True,
        "input_fields": ("idea",),
        "primary_field": "idea",
    },
    {
        "mode": "paste",
        "label": "Paste Script",
        "description": (
            "User supplies final text; the stage stores it without AI generation."
        ),
        "provider_required": False,
        "input_fields": ("pasted_script",),
        "primary_field": "pasted_script",
    },
    {
        "mode": "manual",
        "label": "Manual / Edit",
        "description": "User writes or edits the narration text directly.",
        "provider_required": False,
        "input_fields": ("pasted_script",),
        "primary_field": "pasted_script",
    },
)

SOURCE_MODE_BY_KEY: dict[str, dict[str, Any]] = {
    entry["mode"]: entry for entry in SOURCE_MODE_CATALOG
}

EXECUTION_MODE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "mode": "manual",
        "label": "Manual",
        "description": (
            "Operator runs or approves important stages. Default checkpoints "
            "pause after each primary stage (export excluded)."
        ),
    },
    {
        "mode": "assisted",
        "label": "Assisted",
        "description": (
            "Pipeline runs automatically and pauses only at configured "
            "human checkpoints (durable awaiting_approval)."
        ),
    },
    {
        "mode": "automatic",
        "label": "Automatic",
        "description": (
            "Unattended start-to-export under Channel policy: bounded retries, "
            "fallback, safe degradation; pause only on critical/unrecoverable issues."
        ),
    },
)

# script.input adapter enforces 1..10000; keep create-time floors aligned.
_MIN_DIRECT_SCRIPT = 1
_MAX_DIRECT_SCRIPT = 10_000
_MIN_SEED_TEXT = 1
_MAX_SEED_TEXT = 4_000


def source_mode_requires_provider(mode: str | None) -> bool:
    """True when the Script stage must call a script provider for *mode*."""
    text = str(mode or "").strip() or "topic"
    return text in PROVIDER_REQUIRED_SOURCE_MODES


def source_mode_label(mode: str | None) -> str:
    text = str(mode or "").strip() or "topic"
    entry = SOURCE_MODE_BY_KEY.get(text)
    return str(entry["label"]) if entry else text


def validate_job_source(source: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return structured problems for a Job ``source`` block (empty = valid).

    Paste / Manual require non-empty ``pasted_script``. Topic and Idea require
    their seed field. Automatic may carry optional seeds for later derivation.
    """
    if source is None:
        return [{
            "loc": ["source"],
            "msg": "source is required",
            "type": "value_error",
        }]
    if not isinstance(source, Mapping):
        return [{
            "loc": ["source"],
            "msg": "source must be an object",
            "type": "type_error",
        }]

    problems: list[dict[str, Any]] = []
    mode = str(source.get("mode") or "").strip() or "topic"
    if mode not in SOURCE_MODES:
        problems.append({
            "loc": ["source", "mode"],
            "msg": f"source.mode must be one of: {', '.join(SOURCE_MODES)}",
            "type": "value_error",
        })
        return problems

    topic = str(source.get("topic") or "").strip()
    idea = str(source.get("idea") or "").strip()
    pasted = str(source.get("pasted_script") or "").strip()

    if mode in DIRECT_TEXT_SOURCE_MODES:
        if not pasted:
            problems.append({
                "loc": ["source", "pasted_script"],
                "msg": (
                    "pasted_script is required for Paste Script and Manual/Edit modes"
                ),
                "type": "value_error",
            })
        elif len(pasted) > _MAX_DIRECT_SCRIPT:
            problems.append({
                "loc": ["source", "pasted_script"],
                "msg": f"pasted_script must be at most {_MAX_DIRECT_SCRIPT} characters",
                "type": "value_error",
            })
        elif len(pasted) < _MIN_DIRECT_SCRIPT:
            problems.append({
                "loc": ["source", "pasted_script"],
                "msg": "pasted_script must not be empty",
                "type": "value_error",
            })
    elif mode == "topic":
        if not topic:
            problems.append({
                "loc": ["source", "topic"],
                "msg": "topic is required for Topic → Script mode",
                "type": "value_error",
            })
        elif len(topic) > _MAX_SEED_TEXT:
            problems.append({
                "loc": ["source", "topic"],
                "msg": f"topic must be at most {_MAX_SEED_TEXT} characters",
                "type": "value_error",
            })
    elif mode == "idea":
        if not idea:
            problems.append({
                "loc": ["source", "idea"],
                "msg": "idea is required for Idea → Script mode",
                "type": "value_error",
            })
        elif len(idea) > _MAX_SEED_TEXT:
            problems.append({
                "loc": ["source", "idea"],
                "msg": f"idea must be at most {_MAX_SEED_TEXT} characters",
                "type": "value_error",
            })
    # automatic: optional seeds only

    return problems


def job_creation_catalog() -> dict[str, Any]:
    """Payload for ``GET /api/jobs/defaults`` — Step 0 form metadata."""
    return {
        "source_modes": [dict(entry) for entry in SOURCE_MODE_CATALOG],
        "execution_modes": [dict(entry) for entry in EXECUTION_MODE_CATALOG],
        "defaults": {
            "execution_mode": "manual",
            "source": {
                "mode": "paste",
                "topic": "",
                "idea": "",
                "pasted_script": "",
                "script_id": None,
                "references": [],
                "remove_silence": None,
                "speed": None,
            },
        },
    }


__all__ = [
    "DIRECT_TEXT_SOURCE_MODES",
    "EXECUTION_MODE_CATALOG",
    "EXECUTION_MODES",
    "PROVIDER_REQUIRED_SOURCE_MODES",
    "SOURCE_MODE_BY_KEY",
    "SOURCE_MODE_CATALOG",
    "SOURCE_MODES",
    "job_creation_catalog",
    "source_mode_label",
    "source_mode_requires_provider",
    "validate_job_source",
]
