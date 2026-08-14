"""Settings for the async multi-asset fixture (contracts.md §22).

`image_model` reads its list from `ui.options_source` rather than a literal
list — the §22.4 mechanism the shipped webhook provider also uses. A provider
declaring an allowlisted source is the supported way to get a *dynamic*
dropdown without an edit to the option resolver.
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "endpoint_url": {
                "type": "string",
                "label": "Endpoint URL",
                "description": "Where the renderer submits jobs.",
                "default": "",
            },
            "image_model": {
                "type": "string",
                "label": "Image model",
                "default": "",
                "ui": {"type": "dropdown", "options_source": "image_models"},
            },
            "unit_count": {
                "type": "integer",
                "label": "Units per job",
                "default": 3,
                "minimum": 1,
                "maximum": 12,
                "ui": {"type": "number"},
            },
            "fail_last_unit": {
                "type": "boolean",
                "label": "Fail the last unit",
                "description": "Exercises the partial-result path (§31.5).",
                "default": False,
                "ui": {"type": "toggle"},
            },
        },
        "required": ["endpoint_url"],
    }
