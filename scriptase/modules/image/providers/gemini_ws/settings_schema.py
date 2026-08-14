"""Gemini WS Settings Schema — Phase 6, extended by step 12.3.

`prompt_prefix` arrives here from `storyboard.generate`'s config schema, where it
was gated by `display_options: {show: {provider: ["gemini_ws"]}}` — a provider id
written into the node registry. Contracts.md §41.3 M2 moves it (and `auto_type`,
which this schema already declared) into the provider that owns it, so the node
no longer names a provider at all.
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "auto_type": {
                "type": "boolean",
                "label": "Auto-type images",
                "description": "Automatically type images as they arrive from extension",
                "default": False,
                "ui": {
                    "type": "toggle",
                },
            },
            "prompt_prefix": {
                "type": "string",
                "label": "Prompt prefix",
                "description": "Text prepended to every prompt sent to the extension",
                "default": "",
                "ui": {
                    "type": "text",
                },
            },
        },
    }