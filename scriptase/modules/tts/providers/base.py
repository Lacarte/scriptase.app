"""TTS provider base contract — Provider Contract v2 (step 15.1).

TTS is single-unit and synchronous for every provider, so unlike the two visual
domains it keeps a direct `synthesize()` rather than the async job shape. Two
entry points exist on purpose, mirroring `ScriptProvider`:

  * `synthesize(text, settings, voice, speed, on_progress)` — the domain method
    the legacy TTS routes and pipeline already call. Retained unchanged so
    `/api/tts/generate` and `_step_tts` keep working while 15.2 moves them onto
    generic dispatch;
  * `invoke(request, invocation)` — the v2 contract (contracts.md §30/§31).
    Returns a `ProviderResult` whose `payload` validates as `TTSResultPayload`.

The default `invoke()` bridges through `synthesize()`, so a provider that only
implements the domain method still participates in the standardized envelope:
one relative `audio_ref`, artifact refs the boundary can verify, and the
remaining `tts.json` keys carried as result `metadata` (§32.3).

`TTSResult` keeps its absolute `audio_path` because the legacy callers read it;
`invoke()` is the boundary that converts it to a managed relative ref, so an
absolute path never leaves the provider layer inside a `ProviderResult`.

Shipped providers: `inworld` (cloud API).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from scriptase.modules.tts.providers.contract import (  # noqa: F401  (re-exported)
    TTSRequest,
    TTSResultPayload,
)


@dataclass
class Voice:
    """A voice available for synthesis."""
    id: str
    name: str
    language: str
    gender: Optional[str] = None
    preview_url: Optional[str] = None


@dataclass
class TTSResult:
    """Result of a `synthesize()` call.

    `audio_path` is absolute — this is the in-process domain shape, not the
    envelope. `invoke()` normalizes it into `TTSResultPayload.audio_ref`.
    """
    audio_path: str
    duration_seconds: float
    format: str = "wav"
    sample_rate: int = 24000
    metadata: Optional[dict] = None


@dataclass
class TTSStreamChunk:
    """A chunk of streamed audio.

    `samples` carries the raw frames when the provider has them — that is what
    `/api/tts/stream` base64-encodes for the browser's AudioContext — and
    `data` the same audio already encoded. `sample_rate` travels with the chunk
    because the provider, not the route, knows what it produced (step 15.2).
    """
    data: bytes = b""
    samples: Any = None
    sample_rate: int = 24000
    is_final: bool = False


# Keys `TTSResultPayload` owns; everything else in a provider's metadata dict is
# carried through as result `metadata` so `tts.json` consumers keep their fields.
_PAYLOAD_KEYS = frozenset(
    {"audio_ref", "duration_seconds", "sample_rate", "format", "voice", "characters_billed"}
)


def job_dir(project_id: str) -> str:
    """The managed `tts/{project_id}` directory one invocation writes into.

    A project id that sanitizing would *alter* is rejected rather than quietly
    redirected: silently writing to a different folder than the caller named is
    how one project's audio ends up attributed to another.
    """
    import os

    from config import TTS_DIR
    from scriptase.providers.errors import (
        PROVIDER_REQUEST_INVALID,
        ProviderError,
    )
    from scriptase.shared.security import sanitize_project_id

    raw = str(project_id or "").strip()
    if not raw or sanitize_project_id(raw) != raw:
        raise ProviderError(
            PROVIDER_REQUEST_INVALID,
            "A TTS invocation needs a valid project id",
            domain="tts",
        )
    return os.path.join(TTS_DIR, raw)


class TTSProvider(ABC):
    """Base class for all TTS providers (contracts.md §32.3).

    Required:
      - `synthesize()`: generate audio from text
      - `list_voices()`: return available voices

    Optional:
      - `list_models()`, `download_model()`: behind the `model_download` capability
      - `stream()`: behind the `streaming` capability; never produces a
        `ProviderResult` (§32.3)
    """

    #: Filled by subclasses so error mapping and locks carry the right identity.
    provider_id: str = ""
    domain: str = "tts"

    @abstractmethod
    def synthesize(
        self,
        text: str,
        settings: dict,
        voice: Optional[str] = None,
        speed: float = 1.0,
        on_progress: Optional[Callable] = None,
    ) -> TTSResult:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize
            settings: Resolved provider settings (durable settings + run options)
            voice: Voice ID to use (overrides settings)
            speed: Playback speed multiplier
            on_progress: Optional callback for progress updates

        Returns:
            TTSResult with an absolute audio path and metadata
        """

    @abstractmethod
    def list_voices(self, settings: dict) -> list[Voice]:
        """Return the voices this provider can synthesize with."""

    def invoke(self, request: TTSRequest, invocation) -> Any:
        """v2 invocation (§30/§31). Bridges through `synthesize()` by default."""
        from scriptase.providers.concurrency import exclusive_execution
        from scriptase.providers.results import ProviderResult, normalize_ref

        if not isinstance(request, TTSRequest):
            request = TTSRequest.model_validate(request)

        provider_id = self.provider_id or invocation.provider_id
        settings = {
            **dict(invocation.settings or {}),
            **dict(invocation.options or {}),
            # §32.3 artifacts: `tts/{pid}/voice.wav` + `tts.json`. The provider
            # is told where to write rather than deciding, so every provider
            # lands in the same place and the refs are managed by construction.
            "output_dir": job_dir(invocation.project_id),
            "output_basename": request.output_basename,
            # Which sidecar the caller wants beside the audio. The provider used
            # to infer it from "was I given an output directory", which meant a
            # legacy caller could not ask for its historical `{basename}.json`
            # while still using the managed layout (step 15.2).
            "output_sidecar": request.sidecar_name,
        }
        if request.language:
            settings.setdefault("lang_override", request.language)

        invocation.cancel.raise_if_cancelled()
        # Serialization is declared by the manifest, never by this call site.
        with exclusive_execution(self.domain, provider_id):
            invocation.cancel.raise_if_cancelled()
            result = self.synthesize(
                request.text,
                settings,
                voice=request.voice or None,
                speed=request.speed,
                # `on_progress` is a positional-message callback; the reporter
                # takes keywords and owns redaction and rate limiting.
                on_progress=lambda text: invocation.progress(message=text),
            )

        metadata = dict(result.metadata or {})
        # Refs are relative to the *managed root*, never to the invocation's own
        # output directory (§31.2): `resolve_ref()` and the boundary's artifact
        # check both resolve against the root, so a job-dir-relative ref would
        # resolve to a path that does not exist.
        audio_ref = normalize_ref(result.audio_path)
        payload = TTSResultPayload(
            audio_ref=audio_ref,
            duration_seconds=result.duration_seconds,
            sample_rate=result.sample_rate,
            format=result.format,
            voice=metadata.get("voice") or request.voice,
            characters_billed=metadata.get("characters_billed"),
        ).model_dump()

        refs = [audio_ref]
        sidecar = metadata.pop("metadata_path", "")
        if sidecar:
            refs.append(normalize_ref(sidecar))

        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            payload=payload,
            artifact_refs=refs,
            metadata={
                key: value
                for key, value in metadata.items()
                if key not in _PAYLOAD_KEYS and key != "wav_path"
            },
        )

    def list_models(self, settings: dict) -> list[dict]:
        """Return the downloadable models. Optional; default is none."""
        return []

    def download_model(self, model_id: str, settings: dict) -> str:
        """Download a model locally and return its path. Optional."""
        raise NotImplementedError(
            f"download_model is not supported by {self.__class__.__name__}"
        )

    def stream(
        self,
        text: str,
        settings: dict,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> Iterator[TTSStreamChunk]:
        """Stream audio chunks. Optional; a transport capability, not an invocation."""
        raise NotImplementedError(
            f"stream is not supported by {self.__class__.__name__}"
        )

    def shutdown(self) -> None:
        """Release process-held resources. Idempotent; default is a no-op."""


__all__ = [
    "TTSProvider",
    "TTSRequest",
    "TTSResult",
    "TTSResultPayload",
    "TTSStreamChunk",
    "Voice",
]
