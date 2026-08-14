"""Semantic reviewer settings schema.

Rendered by the generic provider settings UI — do not hardcode fields in Vue.
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "min_text_words": {
                "type": "integer",
                "label": "Minimum text words",
                "description": (
                    "Text shorter than this word count raises a structured "
                    "script_defect issue."
                ),
                "default": 8,
                "minimum": 1,
                "maximum": 500,
                "ui": {"type": "number"},
            },
            "duration_tolerance_s": {
                "type": "number",
                "label": "Duration tolerance (seconds)",
                "description": (
                    "Video duration may differ from the expected duration by "
                    "this many seconds before a timing_drift issue is raised."
                ),
                "default": 1.5,
                "minimum": 0.0,
                "maximum": 60.0,
                "ui": {"type": "number"},
            },
            "confidence": {
                "type": "number",
                "label": "Default confidence",
                "description": "Confidence stamped on heuristic findings (0–1).",
                "default": 0.85,
                "minimum": 0.0,
                "maximum": 1.0,
                "ui": {"type": "number"},
            },
        },
        "required": [],
    }
