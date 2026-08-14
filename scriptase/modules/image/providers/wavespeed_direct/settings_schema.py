"""WaveSpeed Direct Settings Schema — Phase 6."""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "label": "WaveSpeed API Key",
                "description": "WaveSpeed API key for direct access",
                "default": "",
                "ui": {
                    "type": "password",
                },
            },
            "image_model": {
                "type": "string",
                "label": "Image Model",
                "description": "Model ID (e.g., 'flux-dev-lora', 'openai/gpt-image-1')",
                "default": "",
                "ui": {
                    "type": "text",
                },
            },
        },
        "required": [],
    }