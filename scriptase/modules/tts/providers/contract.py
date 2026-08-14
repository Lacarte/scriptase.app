"""TTS domain request and result models (contracts.md §32.3).

Filled into `DomainSpec.request_model` / `result_model` by step 15.1 — the last
of the five domains to be filled (D30). Every TTS provider — the local Kokoro
model, the Inworld cloud API, and any future plugin — accepts and returns these
shapes.

Two deliberate decisions carried from §32.3:

  * **one** voice field. The `voice` / `tts_voice` split at
    `pipeline/services.py:88-94` (P5) exists only because dispatch branches on
    the provider id; the caller resolves one voice for the resolved provider and
    the provider receives exactly that. 15.2 removes the branch that produces
    the split;
  * streaming is **not** here. `stream()` / `TTSStreamChunk` are a transport
    capability used by `/api/tts/stream` and never produce a `ProviderResult`.

`model`, `blend*`, and `genMode` are provider *settings* (§26), not request
fields, so the request never freezes a value that is also a durable setting.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from pydantic import BaseModel, Field, field_validator


DEFAULT_BASENAME = "voice"
# §32.3 names the sidecar written beside the audio. The standalone TTS page asks
# for `{basename}.json` instead, which is what its history has always read, so
# the name is a request field rather than something a provider infers.
DEFAULT_SIDECAR = "tts.json"
MIN_SPEED = 0.5
MAX_SPEED = 2.0

# The basename becomes a filename inside the managed output directory, so it may
# carry neither separators nor a leading dot — `.` and `..` are traversal, and a
# dotfile stem is not a name any consumer expects.
_BASENAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$")


class TTSRequest(BaseModel):
    """Frozen §32.3 request. Unknown keys are rejected, not silently ignored."""

    text: str = Field(min_length=1)
    voice: str = ""
    speed: float = Field(default=1.0, ge=MIN_SPEED, le=MAX_SPEED)
    language: str = ""
    output_basename: str = DEFAULT_BASENAME
    # `""` means "beside the audio, named `{output_basename}.json`".
    output_sidecar: str = DEFAULT_SIDECAR

    model_config = {"extra": "forbid"}

    @field_validator("text", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("voice", "language", mode="before")
    @classmethod
    def _strip_optional(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("speed", mode="before")
    @classmethod
    def _default_speed(cls, value: Any) -> float:
        if value in (None, ""):
            return 1.0
        return value

    @field_validator("output_basename", mode="before")
    @classmethod
    def _safe_basename(cls, value: Any) -> str:
        basename = str(value or "").strip() or DEFAULT_BASENAME
        if not _BASENAME_RE.match(basename):
            raise ValueError("output_basename must be a bare, safe file stem")
        return basename

    @field_validator("output_sidecar", mode="before")
    @classmethod
    def _safe_sidecar(cls, value: Any) -> str:
        name = str(value if value is not None else DEFAULT_SIDECAR).strip()
        if not name:
            return ""
        if not _BASENAME_RE.match(name):
            raise ValueError("output_sidecar must be a bare, safe file name")
        return name

    @property
    def sidecar_name(self) -> str:
        """The sidecar file name, with the empty request meaning `{stem}.json`."""
        return self.output_sidecar or f"{self.output_basename}.json"

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "TTSRequest":
        """Build a request from the historical pipeline/node configuration keys.

        Accepts `text`, and either spelling of the voice — the pre-15.2 frontend
        sends `voice` for Kokoro and `tts_voice` for Inworld, and only one of them
        is right for the resolved provider. Explicit `voice` wins; `tts_voice` is
        the fallback so an Inworld-configured request still resolves.
        """
        data = dict(config or {})
        voice = data.get("voice") or data.get("tts_voice") or ""
        return cls(
            text=data.get("text", ""),
            voice=voice,
            speed=data.get("speed", 1.0),
            language=data.get("language", "") or data.get("lang", "") or "",
            output_basename=data.get("output_basename", DEFAULT_BASENAME),
            output_sidecar=data.get("output_sidecar", DEFAULT_SIDECAR),
        )


class TTSResultPayload(BaseModel):
    """Frozen §32.3 result payload — the only shape a TTS provider returns.

    `audio_ref` is a *relative* managed ref, replacing the absolute `audio_path`
    of the ABC `TTSResult` it supersedes. Everything else today's `tts.json`
    carries (`prompt`, `words`, `rtf`, `inference_time`, `model`, …) moves to
    result `metadata`/`provenance`, and the file keeps them, so `tts.json`
    consumers are unaffected.
    """

    audio_ref: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    sample_rate: int = Field(gt=0)
    format: str = "wav"
    voice: str = ""
    characters_billed: int | None = None

    model_config = {"extra": "forbid"}

    @field_validator("audio_ref", mode="before")
    @classmethod
    def _posix_ref(cls, value: Any) -> str:
        return str(value or "").replace("\\", "/").strip()

    @field_validator("characters_billed", mode="before")
    @classmethod
    def _optional_characters(cls, value: Any) -> Any:
        if value in (None, ""):
            return None
        return value

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TTSResultPayload":
        payload = dict(data or {})
        return cls(
            audio_ref=payload.get("audio_ref") or "",
            duration_seconds=payload.get("duration_seconds") or 0,
            sample_rate=payload.get("sample_rate") or 0,
            format=payload.get("format") or "wav",
            voice=payload.get("voice") or "",
            characters_billed=payload.get("characters_billed"),
        )


__all__ = [
    "DEFAULT_BASENAME",
    "DEFAULT_SIDECAR",
    "MAX_SPEED",
    "MIN_SPEED",
    "TTSRequest",
    "TTSResultPayload",
]
