"""Inworld TTS Settings Schema — Phase 4."""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "label": "API Key",
                "description": "Inworld API key",
                "default": "",
                "ui": {
                    "type": "password",
                },
            },
            "voice": {
                "type": "string",
                "label": "Default Voice",
                "description": "Default Inworld voice ID",
                "default": "Ashley",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        "Ashley", "Carter", "Dennis", "Diana", "Freya",
                        "Giovanni", "Grace", "Jennifer", "Jonathan", "Katherine",
                        "Mark", "Mary", "Michael", "Patrick", "Robert", "Sara",
                    ],
                },
            },
            "model": {
                "type": "string",
                "label": "Model",
                "description": "Inworld TTS model",
                "default": "inworld-tts-1.5-max",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        "inworld-tts-1.5-max",
                        "inworld-tts-1",
                        "inworld-tts-1-hd",
                    ],
                },
            },
            "speed": {
                "type": "number",
                "label": "Speed",
                "description": (
                    "Speech speed multiplier on the voice's natural rate. "
                    "The result is clamped to Inworld's supported [0.5, 1.5] "
                    "speaking-rate range; stay near 1.0 for best quality."
                ),
                "default": 1.0,
                "minimum": 0.5,
                "maximum": 2.0,
                "ui": {
                    "type": "slider",
                },
            },
        },
        "required": ["api_key"],
    }
