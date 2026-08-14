"""Kokoro TTS Settings Schema — Phase 4."""


def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "voice": {
                "type": "string",
                "label": "Default Voice",
                "description": "Default voice for synthesis",
                "default": "af_bella",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
                        "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
                        "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
                        "am_michael", "am_onyx", "am_puck",
                        "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
                        "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
                        "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
                        "zf_xiaobei", "zf_xiaoni", "zf_xiaoxuan", "zf_xiaoyi",
                        "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
                        "ef_dora", "em_alex", "em_santa",
                        "ff_siwis",
                        "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
                        "if_sara", "im_nicola",
                        "pf_dora", "pm_alex", "pm_santa",
                    ],
                },
            },
            "speed": {
                "type": "number",
                "label": "Speed",
                "description": "Speech speed multiplier (0.5-2.0)",
                "default": 1.0,
                "minimum": 0.5,
                "maximum": 2.0,
                "ui": {
                    "type": "slider",
                },
            },
            "lang": {
                "type": "string",
                "label": "Language",
                "description": "Language preset for voice selection",
                "default": "top-picks",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        "top-picks",
                        "en-us",
                        "en-gb",
                        "ja",
                        "cmn",
                        "es",
                        "fr-fr",
                        "hi",
                        "it",
                        "pt-br",
                    ],
                },
            },
            "blend": {
                "type": "boolean",
                "label": "Enable Voice Blending",
                "description": "Blend two voices together",
                "default": False,
                "ui": {
                    "type": "toggle",
                },
            },
            "blendA": {
                "type": "string",
                "label": "Voice A",
                "description": "First voice for blending",
                "default": "af_heart",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
                        "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
                    ],
                },
            },
            "blendB": {
                "type": "string",
                "label": "Voice B",
                "description": "Second voice for blending",
                "default": "am_adam",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
                        "am_michael", "am_onyx", "am_puck",
                    ],
                },
            },
            "blendRatio": {
                "type": "number",
                "label": "Blend Ratio",
                "description": "Ratio of Voice B (0-100)",
                "default": 50,
                "minimum": 0,
                "maximum": 100,
                "ui": {
                    "type": "slider",
                },
            },
            "blendMethod": {
                "type": "string",
                "label": "Blend Method",
                "description": "Method for voice blending",
                "default": "slerp",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        {"value": "slerp", "label": "SLERP (recommended)"},
                        {"value": "lerp", "label": "LERP (linear)"},
                    ],
                },
            },
            "genMode": {
                "type": "string",
                "label": "Generation Mode",
                "description": "Text processing mode",
                "default": "generate",
                "ui": {
                    "type": "dropdown",
                    "options": [
                        {"value": "generate", "label": "Generate (normalized)"},
                        {"value": "preserve", "label": "Preserve brackets"},
                    ],
                },
            },
        },
        "required": [],
    }
