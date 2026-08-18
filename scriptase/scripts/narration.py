"""Narration generation for first-class Studio scripts.

Every take goes through the generic TTS dispatch and the shared immutable
artifact store.  Regeneration therefore advances the script's audio artifact
chain instead of overwriting the previous take.
"""

from __future__ import annotations

import os
from typing import Any

from config import OUTPUT_DIR, TTS_DIR
from scriptase.artifacts.store import active_artifact, register_artifact
from scriptase.channels.store import get_channel
from scriptase.modules.tts import dispatch
from scriptase.scripts.store import ScriptConflict, get_script, update_script


_tts_dir = TTS_DIR
_output_dir = OUTPUT_DIR


def _draft(document, narration: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": document.title,
        "body": document.body,
        "channel_id": document.channel_id,
        "origin": document.origin,
        "narration": narration,
    }


def effective_processing(document, channel) -> dict[str, Any]:
    """Resolve nullable per-script overrides against Channel defaults."""
    narration = document.narration
    audio = channel.audio_defaults
    return {
        "remove_silence": (
            narration.remove_silence
            if narration.remove_silence is not None
            else audio.remove_silence
        ),
        "speed": narration.speed if narration.speed is not None else audio.speed,
    }


def generate_narration(
    script_id: str,
    *,
    voice: str | None = None,
    remove_silence: bool | None = None,
    speed: float | None = None,
    expected_version: int | None = None,
):
    """Generate one take and return ``(updated_script, artifact)``.

    ``None`` processing values mean inherit. They remain nullable in the
    document even though concrete values are passed to TTS.
    """
    current = get_script(script_id)
    if expected_version is not None and current.version != expected_version:
        raise ScriptConflict(script_id)
    if not current.body.strip():
        raise ValueError("Script body is required before generating narration")

    channel = get_channel(current.channel_id)
    requested_voice = (voice or "").strip() or channel.audio_defaults.voice
    overrides = {
        "remove_silence": remove_silence,
        "speed": speed,
    }
    generating = update_script(
        script_id,
        _draft(current, {
            **current.narration.model_dump(mode="json"),
            "state": "generating",
            "voice": requested_voice,
            **overrides,
        }),
        expected_version=current.version,
    )
    processing = effective_processing(generating, channel)
    prior = active_artifact(script_id, "audio")
    take = (prior.version + 1) if prior is not None else 1
    basename = f"narration_v{take}"
    output_dir = os.path.join(_tts_dir, script_id)
    provider_instance = (
        channel.audio_defaults.tts_provider_instance_id
        or channel.provider_defaults.tts
        or ""
    )

    try:
        result = dispatch.synthesize(
            {
                "text": generating.body,
                "voice": requested_voice,
                "speed": processing["speed"],
                "remove_silence": processing["remove_silence"],
                "language": channel.content.language,
                "tts_provider_override": provider_instance,
            },
            project_id=script_id,
            output_dir=output_dir,
            basename=basename,
            sidecar_name=f"{basename}.json",
            use_cache=True,
        )
        relative = os.path.relpath(result["wav_path"], _output_dir).replace("\\", "/")
        artifact = register_artifact(
            job_id=script_id,
            kind="audio",
            path=relative,
            provenance_ref=(result.get("job_meta") or {}).get("invocation_id") or None,
        )
        ready = update_script(
            script_id,
            _draft(generating, {
                "state": "ready",
                "voice": result.get("voice") or requested_voice,
                "remove_silence": remove_silence,
                "speed": speed,
                "duration_s": result.get("duration_seconds"),
                "audio_artifact_id": artifact.id,
            }),
            expected_version=generating.version,
        )
        return ready, artifact
    except Exception:
        # A failed attempt must not strand the document in "generating" or
        # discard the last playable take.
        try:
            update_script(
                script_id,
                _draft(generating, current.narration.model_dump(mode="json")),
                expected_version=generating.version,
            )
        except Exception:
            pass
        raise


__all__ = ["effective_processing", "generate_narration"]
