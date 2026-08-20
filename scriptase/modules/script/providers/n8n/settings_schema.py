"""Settings schema for the `n8n` script provider.

The webhook URL is the only durable setting; it is owned by provider metadata
so the shared settings UI and per-run `provider_options` can surface it without
a hardcoded frontend form. An empty value falls back to N8N_STORY_WEBHOOK_URL.
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "webhook_url": {
                "type": "string",
                "label": "Script webhook URL",
                "description": (
                    "n8n webhook that runs your script-generation workflow. "
                    "Leave empty to use the N8N_STORY_WEBHOOK_URL environment "
                    "default."
                ),
                "default": "",
                "ui": {"type": "text"},
            },
        },
        "required": [],
    }
