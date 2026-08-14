def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "label_prefix": {
                "type": "string",
                "label": "Scene title prefix",
                "default": "Fixture",
                "ui": {"type": "text"},
            },
        },
        "required": [],
    }
