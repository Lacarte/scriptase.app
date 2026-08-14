"""Settings schema for the `random_template` script provider.

Category/language/tone options are owned by this provider's metadata so the
generic settings renderer can surface them without a hardcoded frontend catalog.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache


_TEMPLATES_PATH = os.path.join(os.path.dirname(__file__), "templates.json")


@lru_cache(maxsize=1)
def _template_types() -> tuple[str, ...]:
    with open(_TEMPLATES_PATH, encoding="utf-8") as handle:
        entries = json.load(handle)
    seen: list[str] = []
    for entry in entries:
        typ = str((entry or {}).get("type") or "").strip()
        if typ and typ not in seen:
            seen.append(typ)
    return tuple(seen)


def settings_schema() -> dict:
    types = list(_template_types())
    return {
        "type": "object",
        "properties": {
            "default_category": {
                "type": "string",
                "label": "Default category",
                "description": (
                    "When set, random picks prefer templates of this type. "
                    "Leave empty to draw from the full catalog."
                ),
                "default": "",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        {"value": "", "label": "Any category"},
                        *[{"value": t, "label": t} for t in types],
                    ],
                },
            },
            "language": {
                "type": "string",
                "label": "Language tag",
                "description": "Recorded on the result metadata (catalog is English text).",
                "default": "english",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        {"value": "english", "label": "English"},
                        {"value": "french", "label": "French"},
                        {"value": "spanish", "label": "Spanish"},
                    ],
                },
            },
            "tone": {
                "type": "string",
                "label": "Tone label",
                "description": "Optional tone tag stored in result metadata.",
                "default": "",
                "ui": {"type": "text"},
            },
        },
        "required": [],
    }
