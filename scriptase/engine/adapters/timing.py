"""Timing adapter (`timing.align`) — strategy AUTO (step 5.3).

User-facing node name is **Timing** (V2: Force Alignment). Resolves the managed
wav through `resolve_ref` from `artifact_refs` (authoritative) or a relative
`wav_path` / `path` (sample fixtures), then hands the absolute path only to the
in-process `_step_timing` service.

When the upstream audio port carries `native_word_timing` plus `word_timings`,
the service normalises those; otherwise it force-aligns. The alignment port
always emits the same canonical schema either way.
"""

from __future__ import annotations

import os

from config import ALIGN_DIR
from scriptase.modules.timing.service import _step_timing
from scriptase.providers.errors import ProviderError
from scriptase.providers.results import resolve_ref

from .common import AdapterError, outputs, project_id, with_artifacts

_AUDIO_SUFFIXES = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac")


def _resolve_audio_path(audio) -> str:
    """Absolute path of the managed TTS wav for `_step_timing`.

    Resolution order (contracts.md §30.2 / §44):
      1. `artifact_refs` — authoritative after 15.3
      2. relative `wav_path` / `path` — sample fixtures and relative leftovers
    Absolute path keys are rejected so a stale cache entry cannot reintroduce
    the L7 leak onto the next node's inputs.
    """
    if not isinstance(audio, dict):
        raise AdapterError("ARTIFACT_MISSING", "TTS audio payload is missing")

    candidates: list[str] = []
    refs = audio.get("artifact_refs")
    if isinstance(refs, list):
        audio_refs = [
            ref for ref in refs
            if isinstance(ref, str) and ref.lower().endswith(_AUDIO_SUFFIXES)
        ]
        other_refs = [
            ref for ref in refs
            if isinstance(ref, str) and ref and ref not in audio_refs
        ]
        candidates.extend(audio_refs or other_refs)
    for key in ("wav_path", "path"):
        value = audio.get(key)
        if isinstance(value, str) and value and value not in candidates:
            candidates.append(value)

    last_error: ProviderError | None = None
    for candidate in candidates:
        try:
            return resolve_ref(candidate)
        except ProviderError as exc:
            last_error = exc
            continue

    message = "TTS audio has no managed relative artifact reference"
    if last_error is not None:
        message = f"{message}: {last_error.message}"
    raise AdapterError("ARTIFACT_MISSING", message)


def align(inputs, config, context):
    pid = project_id(context, inputs)
    audio = inputs["audio"]
    wav_path = _resolve_audio_path(audio)
    # Absolute only for the in-process timing service — never re-emitted on
    # the alignment port (with_artifacts writes relative refs from the JSON path).
    metadata = {
        "wav_path": wav_path,
        "folder": audio.get("folder") or audio.get("source_folder") or pid,
        "filename": audio.get("filename") or os.path.basename(wav_path),
    }
    # Forward native timing advertisement + payload for strategy AUTO.
    if audio.get("native_word_timing"):
        metadata["native_word_timing"] = True
    for key in ("word_timings", "alignment", "word_alignment"):
        value = audio.get(key)
        if isinstance(value, list) and value:
            metadata[key] = value
            break
    try:
        result = _step_timing(metadata, {"text": inputs["script"]}, pid)
    except RuntimeError as exc:
        raise AdapterError("ALIGNMENT_EMPTY", str(exc)) from exc
    path = os.path.join(ALIGN_DIR, result["folder"], "alignment.json")
    return outputs(alignment=with_artifacts(result, path))