"""Settings schema for the reference v2 provider (contracts.md §22.1)."""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "title": "API key",
                "ui": {"type": "password"},
            },
            "mode": {
                "type": "string",
                "title": "Mode",
                "default": "sync",
                "enum": ["sync", "async", "batch"],
                "ui": {"type": "select"},
            },
            "unit_count": {
                "type": "integer",
                "title": "Units per request",
                "default": 3,
                "ui": {"type": "number", "show_if": {"mode": ["async", "batch"]}},
            },
        },
        "required": ["api_key"],
    }
