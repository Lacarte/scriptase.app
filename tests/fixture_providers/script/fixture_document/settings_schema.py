"""Settings for the sync-document fixture (contracts.md §22).

Written to exercise the parts of the frozen vocabulary a *node* has to render:
a secret, a static dropdown, a conditional field, and a bounded number. The
inspector's `provider_options` sub-form is built from exactly this, so if a
widget renders here it renders for any provider that declares it (§26).
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "label": "API key",
                "description": "Never leaves the settings store.",
                "ui": {"type": "password"},
            },
            "voice_of": {
                "type": "string",
                "label": "Narrative voice",
                "default": "narrator",
                "enum": ["narrator", "protagonist", "chorus"],
                "ui": {"type": "dropdown"},
            },
            "chaptered": {
                "type": "boolean",
                "label": "Split into chapters",
                "default": False,
                "ui": {"type": "toggle"},
            },
            "chapter_count": {
                "type": "integer",
                "label": "Chapters",
                "default": 3,
                "minimum": 2,
                "maximum": 9,
                # §22.3: hidden unless `chaptered` is on. Hidden fields keep
                # their value, are exempt from `required`, and are dropped
                # before the provider is invoked.
                "ui": {"type": "number", "show_if": {"chaptered": True}},
            },
            "epigraph": {
                "type": "string",
                "label": "Epigraph",
                "default": "",
                "ui": {"type": "textarea"},
            },
        },
        "required": ["api_key"],
    }
