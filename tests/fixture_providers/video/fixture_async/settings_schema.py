"""Settings the fixture animator provider claims to need."""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "endpoint_url": {
                "type": "string",
                "label": "Endpoint",
                "description": "A pretend renderer URL used only by tests",
                "default": "",
                "ui": {"type": "text"},
            },
        },
        "required": [],
    }
