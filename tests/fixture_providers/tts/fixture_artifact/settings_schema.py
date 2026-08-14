"""Settings for the sync-artifact fixture (contracts.md §22).

`voice.ui.options` is the mechanism step 12.2 chose for per-provider voices:
the `tts_voices` option source reads this list rather than constructing the
provider, so declaring it here is the whole of "make my voices selectable".
"""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "voice": {
                "type": "string",
                "label": "Voice",
                "default": "fx_calm",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        {"value": "fx_calm", "label": "Calm"},
                        {"value": "fx_bright", "label": "Bright"},
                    ],
                },
            },
            "speed": {
                "type": "number",
                "label": "Speed",
                "default": 1.0,
                "minimum": 0.5,
                "maximum": 2.0,
                "ui": {"type": "slider"},
            },
            "sample_rate": {
                "type": "integer",
                "label": "Sample rate",
                "default": 24000,
                "enum": [16000, 24000, 48000],
                "ui": {"type": "dropdown"},
            },
        },
        "required": [],
    }
