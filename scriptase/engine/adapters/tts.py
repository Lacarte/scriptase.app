"""Workflow adapter for the Text to Speech node (`tts.generate`).

Dispatches generically through the `tts` provider hub (step 15.2). The adapter
resolves which provider the node runs on and hands the request to
`scriptase.modules.tts.dispatch` via `_step_tts`; it knows nothing about voices, models,
streaming, or audio formats, so a TTS provider that ships tomorrow runs on this
node with no edit here and none in the registry.

Step 15.3 retires the absolute `wav_path` / `path` keys that used to leave this
adapter on the audio and metadata ports (§36 L7). Port payloads carry relative
refs only — `artifact_refs` is authoritative and `wav_path` is the same relative
value sample fixtures already use. Consumers resolve through `resolve_ref`.
"""

from __future__ import annotations

import os

from scriptase.modules.tts.service import _step_tts
from scriptase.providers.errors import ProviderError

from .common import (
    artifact_ref,
    inherited_config,
    outputs,
    project_id,
    provider_id,
    provider_run_options,
    with_artifacts,
)

DOMAIN = "tts"

# Absolute path keys that must never reach a port payload, cache entry, or SSE
# frame after the 15.3 L7 retirement (contracts.md §30.2 / §36 / §44).
_ABSOLUTE_KEYS = frozenset({"wav_path", "path"})


def generate(inputs, config, context):
    pid = project_id(context, inputs)
    merged = inherited_config(config, inputs.get("settings"), {"tone": "story_tone", "style": "visual_style"})
    merged["text"] = inputs["script"]
    # `engine` became `provider_id` in v2 (contracts.md §41.3 M1). The legacy
    # request field the pipeline reads is unchanged, so a migrated workflow
    # produces the same call it made before the rename.
    selected = provider_id(DOMAIN, merged)
    merged["tts_provider_override"] = selected
    merged["tts_provider_options"] = provider_run_options(DOMAIN, selected, merged)
    try:
        result = _step_tts(merged, pid, context)
    except ProviderError as exc:
        raise exc.as_adapter_error() from exc

    wav_abs = result["wav_path"]
    sidecar_abs = os.path.join(os.path.dirname(wav_abs), "tts.json")
    # Relative managed ref — the only form that leaves this adapter.
    wav_ref = artifact_ref(wav_abs)

    # Drop absolute path keys from the service result, then re-emit wav_path as
    # the relative ref so sample fixtures and tts_metadata consumers keep a
    # stable shape without reintroducing L7.
    # native_word_timing / word_timings (step 5.3) ride through from dispatch
    # when the provider advertised them; Timing AUTO reads them off the audio
    # port (the only edge the default workflow draws from TTS → Timing).
    metadata_body = {key: value for key, value in result.items() if key not in _ABSOLUTE_KEYS}
    metadata_body["wav_path"] = wav_ref

    audio_body = {
        "project_id": pid,
        "filename": result["filename"],
        "folder": result.get("folder") or pid,
        "duration_seconds": result.get("duration_seconds"),
        "sample_rate": result.get("sample_rate"),
        "wav_path": wav_ref,
    }
    if result.get("native_word_timing"):
        audio_body["native_word_timing"] = True
    word_timings = result.get("word_timings")
    if isinstance(word_timings, list) and word_timings:
        audio_body["word_timings"] = word_timings

    metadata = with_artifacts(metadata_body, wav_abs, sidecar_abs)
    audio = with_artifacts(audio_body, wav_abs)
    return outputs(audio=audio, metadata=metadata)
