"""Settings schema for the AI `n8n` scene-blueprint provider.

Webhook configuration that used to live only on env vars and ad-hoc request
fields is owned by this provider's metadata so the shared settings UI and
per-run `provider_options` can surface it without a hardcoded frontend form.
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "webhook_url": {
                "type": "string",
                "label": "Scene webhook URL",
                "description": (
                    "n8n webhook that runs the scene-blueprint workflow. "
                    "Leave empty to use the N8N_WEBHOOK_URL environment default."
                ),
                "default": "",
                "ui": {"type": "text"},
            },
        },
        "required": [],
    }
