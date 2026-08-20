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
            # `speed` scales the voice's baseline `audioConfig.speakingRate`,
            # clamped to the remote API's [0.5, 1.5] range. An unset speed (1.0)
            # keeps the historical per-voice rate.
            "speed_control": True,
        },
        contract_version=2,
        description="Cloud text-to-speech with named voices and selectable models.",
        # Read-time fallback only — a value is never copied into settings.json.
        environment={"api_key": "INWORLD_API_KEY", "model": "INWORLD_TTS_MODEL"},
    )
