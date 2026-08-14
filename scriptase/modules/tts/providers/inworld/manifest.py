"""Inworld TTS provider manifest — Provider Contract v2 (step 15.1)."""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="inworld",
        label="Inworld",
        domain="tts",
        kind="cloud",
        version="1.0.0",
        requires=["api_key"],
        capabilities={
            "test_connection": True,
            "streaming": False,
            "model_download": False,
            "single_scene": True,
            "batch": True,
            "voice_list": True,
            # The remote API applies its own speaking rate; `speed` is not a
            # request field this provider honors (§32.3), and saying so keeps a
            # caller from believing it took effect.
            "speed_control": False,
        },
        contract_version=2,
        description="Cloud text-to-speech with named voices and selectable models.",
        # Read-time fallback only — a value is never copied into settings.json.
        environment={"api_key": "INWORLD_API_KEY", "model": "INWORLD_TTS_MODEL"},
    )
