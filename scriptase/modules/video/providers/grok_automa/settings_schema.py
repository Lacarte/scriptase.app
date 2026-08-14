"""Grok Automa Settings Schema — Phase 7, extended by step 12.3.

`auto_type` arrives here from `animator.generate`'s config schema, where it was
gated by `display_options: {show: {provider: ["grok_automa"]}}` — a provider id
written into the node registry. `mode`, `quality`, and `duration` were already
declared here and are now the *single* declaration: contracts.md §41.3 M3 moves
the node's copies into per-run provider options, so the node no longer names a
provider at all.
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "label": "Mode",
                "description": "Generation mode",
                "default": "video",
                "ui": {
                    "type": "dropdown",
                    "options": ["video", "image"],
                },
            },
            "quality": {
                "type": "string",
                "label": "Quality",
                "description": "Video quality",
                "default": "480p",
                "ui": {
                    "type": "dropdown",
                    "options": ["480p", "720p", "1080p"],
                },
            },
            "duration": {
                "type": "string",
                "label": "Duration",
                "description": "Video duration",
                "default": "6s",
                "ui": {
                    "type": "dropdown",
                    "options": ["5s", "6s", "10s"],
                },
            },
            "auto_type": {
                "type": "boolean",
                "label": "Auto-type prompts",
                "description": "Let the extension type each prompt automatically",
                "default": True,
                "ui": {
                    "type": "toggle",
                },
            },
        },
    }