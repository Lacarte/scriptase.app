"""Settings schema for the LLM virality judge provider.

The only per-instance setting is the webhook URL; leaving it empty falls back to
the N8N_VIRALITY_WEBHOOK_URL environment default (read-time only, never stored).
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "webhook_url": {
                "type": "string",
                "label": "Virality webhook URL",
                "description": (
                    "n8n webhook that runs the LLM virality-judge workflow. "
                    "Leave empty to use the N8N_VIRALITY_WEBHOOK_URL environment default."
                ),
                "default": "",
                "ui": {"type": "text"},
            },
        },
        "required": [],
    }
