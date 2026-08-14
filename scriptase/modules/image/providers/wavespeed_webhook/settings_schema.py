"""WaveSpeed Webhook Settings Schema — Phase 6."""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "webhook_url": {
                "type": "string",
                "label": "n8n Webhook URL",
                "description": "n8n webhook URL for WaveSpeed image generation",
                "default": "",
                "ui": {
                    "type": "text",
                },
            },
            "image_model": {
                "type": "string",
                "label": "Image Model",
                "description": "Optional model override (leave empty for default)",
                "default": "",
                # The list, with its prices, was fetched and rendered by the
                # Storyboard page itself until step 12.4. §22.4 puts it here,
                # with the provider that consumes the value.
                "ui": {
                    "type": "dropdown",
                    "options_source": "image_models",
                },
            },
        },
        "required": ["webhook_url"],
    }