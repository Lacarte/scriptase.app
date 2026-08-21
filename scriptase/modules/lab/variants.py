"""Prompt variants — named, versioned bundles of prompt-tuning knobs.

A variant is *data*, not code: it parameterizes the inputs to the (tested,
in-code) prompt engine so you can A/B a change without a deploy. It never
carries prompt *machinery* — only the levers that change the output:

  * ``angle_pool``       — restrict/replace which opening angles the engine may
                           pick (empty = the built-in pool)
  * ``extra_directives`` — free-text lines appended to the user prompt
  * ``tone_override``    — force a story tone
  * ``language_level``   — beginner | intermediate | advanced | native
  * ``temperature``      — LLM sampling temperature sent to the webhook
  * ``word_target_ratio``— scale the duration-derived word target

The assembly (anti-repetition, structure enforcement, sampling) stays in
``scriptase.modules.script.prompts``. Variants only decide what goes in.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Mapping

from config import OUTPUT_DIR
from scriptase.shared.io_utils import safe_json_write

LAB_DIR = os.path.join(OUTPUT_DIR, "lab")
VARIANTS_DIR = os.path.join(LAB_DIR, "variants")
DEFAULT_LAB = "script_prompt"

_ID_RE = re.compile(r"^var_[a-z0-9]{8}$")


def _variants_dir(lab_id: str | None) -> str:
    """Per-lab variants directory, so labs never collide."""
    return os.path.join(VARIANTS_DIR, lab_id or DEFAULT_LAB)
_LANGUAGE_LEVELS = ("", "beginner", "intermediate", "advanced", "native")

# The built-in control is always present and represents "the engine's defaults"
# — the baseline of any experiment. Its knob values are the lab's real defaults,
# shown pre-filled so a user can see and clone them. Not stored on disk.
def builtin_variant(lab_id: str | None = None) -> dict:
    from scriptase.modules.lab.registry import get_lab

    lab = get_lab(lab_id or DEFAULT_LAB)
    defaults = dict(lab.default_variant) if lab else {}
    return {
        "id": "builtin",
        "name": "Default (built-in)",
        "description": "The engine's own logic with no overrides — the control.",
        "builtin": True,
        "version": 1,
        **defaults,
    }


def _new_id() -> str:
    # Time-derived, lowercased base36-ish; unique enough for a local store.
    stamp = format(int(time.time() * 1000) & 0xFFFFFFFFFF, "x").rjust(8, "0")[-8:]
    return f"var_{stamp}"


def _coerce(data: Mapping[str, Any] | None) -> dict:
    """Validate + normalize a variant payload into the stored shape."""
    d = dict(data or {})
    name = str(d.get("name") or "").strip()
    if not name:
        raise ValueError("A variant needs a name")

    angle_pool = [str(a).strip() for a in (d.get("angle_pool") or []) if str(a).strip()]
    directives = [str(x).strip() for x in (d.get("extra_directives") or []) if str(x).strip()]

    level = str(d.get("language_level") or "").strip().lower()
    if level not in _LANGUAGE_LEVELS:
        raise ValueError("language_level must be beginner, intermediate, advanced, or native")

    temperature = d.get("temperature")
    if temperature in (None, ""):
        temperature = None
    else:
        temperature = float(temperature)
        if not 0.0 < temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")

    try:
        ratio = float(d.get("word_target_ratio") or 1.0)
    except (TypeError, ValueError):
        ratio = 1.0
    ratio = max(0.5, min(2.0, ratio))

    return {
        "name": name[:80],
        "description": str(d.get("description") or "").strip()[:400],
        "angle_pool": angle_pool[:40],
        "extra_directives": directives[:20],
        "tone_override": str(d.get("tone_override") or "").strip()[:80],
        "language_level": level,
        "temperature": temperature,
        "word_target_ratio": ratio,
    }


def list_variants(lab_id: str | None = None) -> list[dict]:
    """Every stored variant for a lab, newest first, control first."""
    directory = _variants_dir(lab_id)
    stored: list[dict] = []
    if os.path.isdir(directory):
        for name in os.listdir(directory):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(directory, name), encoding="utf-8") as fh:
                    stored.append(json.load(fh))
            except (OSError, json.JSONDecodeError):
                continue
    stored.sort(key=lambda v: v.get("updated_at") or "", reverse=True)
    return [builtin_variant(lab_id), *stored]


def get_variant(variant_id: str, lab_id: str | None = None) -> dict | None:
    if variant_id == "builtin":
        return builtin_variant(lab_id)
    if not _ID_RE.fullmatch(variant_id or ""):
        return None
    path = os.path.join(_variants_dir(lab_id), f"{variant_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def create_variant(data: Mapping[str, Any] | None, lab_id: str | None = None) -> dict:
    record = _coerce(data)
    now = _now_iso()
    record.update({
        "id": _new_id(),
        "lab_id": lab_id or DEFAULT_LAB,
        "builtin": False,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })
    safe_json_write(os.path.join(_variants_dir(lab_id), f"{record['id']}.json"), record, indent=2)
    return record


def update_variant(variant_id: str, data: Mapping[str, Any] | None, lab_id: str | None = None) -> dict:
    existing = get_variant(variant_id, lab_id)
    if existing is None or existing.get("builtin"):
        raise ValueError("Unknown or read-only variant")
    record = _coerce({**existing, **dict(data or {})})
    record.update({
        "id": variant_id,
        "lab_id": lab_id or DEFAULT_LAB,
        "builtin": False,
        "version": int(existing.get("version") or 1) + 1,
        "created_at": existing.get("created_at") or _now_iso(),
        "updated_at": _now_iso(),
    })
    safe_json_write(os.path.join(_variants_dir(lab_id), f"{variant_id}.json"), record, indent=2)
    return record


def delete_variant(variant_id: str, lab_id: str | None = None) -> bool:
    if variant_id == "builtin" or not _ID_RE.fullmatch(variant_id or ""):
        return False
    path = os.path.join(_variants_dir(lab_id), f"{variant_id}.json")
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


__all__ = [
    "DEFAULT_LAB",
    "LAB_DIR",
    "VARIANTS_DIR",
    "builtin_variant",
    "create_variant",
    "delete_variant",
    "get_variant",
    "list_variants",
    "update_variant",
]
