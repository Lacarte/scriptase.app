"""Kie AI Settings Schema — Phase 7."""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "label": "Kie AI API Key",
                "description": "Kie AI API key",
                "default": "",
                "ui": {
                    "type": "password",
                },
            },
            "model": {
                "type": "string",
                "label": "Model",
                "description": "Model ID (e.g., 'google/nano-banana')",
                "default": "google/nano-banana",
                # The option list was a hand-written `<select>` on the Assets
                # page until step 12.4. Declaring it here is what lets that page
                # offer the same three choices without naming this provider.
                "ui": {
                    "type": "dropdown",
                    "options": [
                        {"value": "google/nano-banana", "label": "Nano Banana — $0.02"},
                        {"value": "nano-banana-2", "label": "Nano Banana 2 — $0.04"},
                        {"value": "nano-banana-pro", "label": "Nano Banana Pro — $0.09"},
                    ],
                },
            },
            "resolution": {
                "type": "string",
                "label": "Resolution",
                "description": "Resolution setting",
                "default": "1",
                "ui": {
                    "type": "dropdown",
                    "options": ["1", "2", "3", "4"],
                },
            },
            # Declared here by step 12.4. It was only ever a hand-written widget
            # on the Assets page, so the provider that consumes it could not
            # describe it; `png` is the default that page shipped.
            "output_format": {
                "type": "string",
                "label": "Output format",
                "description": "Image file format returned by the API",
                "default": "png",
                "ui": {
                    "type": "dropdown",
                    "options": ["png", "jpg"],
                },
            },
        },
        "required": [],
    }