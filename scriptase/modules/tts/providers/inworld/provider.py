"""Inworld TTS provider — Provider Contract v2 (step 15.1).

Cloud synthesis through the Inworld Voice API. The provider keeps the payload
shape and the voice-dependent temperature/speaking-rate tuning; HTTP mechanics,
retry policy, and failure classification move to the shared direct-API transport
(step 14.4), which is what makes the errors this provider raises members of the
standard catalog with correct retryability.

The hand-rolled retry loop this replaces raised `requests.HTTPError` carrying
`resp.text[:200]`, and a `RuntimeError` embedding the 404 body — both of which
put a third-party response body, and the request URL, into an error that gets
persisted and displayed. `classify_http_error` never copies a body.
"""

from __future__ import annotations

import base64
import io
import os
import threading
import time
from datetime import datetime
from typing import Callable, Optional

import soundfile as sf
from loguru import logger

from config import INWORLD_API_KEY, INWORLD_TTS_BASE_URL, INWORLD_TTS_MODEL, TTS_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.providers.errors import (
    PROVIDER_NOT_CONFIGURED,
    PROVIDER_RESPONSE_MALFORMED,
    ProviderError,
)
from scriptase.providers.transports.direct_api import (
    DirectApiClient,
    classify_http_error,
)
from scriptase.modules.tts.providers.base import TTSProvider, TTSResult, Voice

_DOMAIN = "tts"
_PROVIDER_ID = "inworld"

DEFAULT_VOICE = "Ashley"

_voices_cache = None
_voices_cache_lock = threading.Lock()
_voices_cache_ts = 0
_VOICES_TTL = 600


def _auth_header(api_key: str) -> dict:
    return {"Authorization": f"Basic {api_key}"}


def _client(api_key: str, *, timeout: float = 30) -> DirectApiClient:
    return DirectApiClient(
        base_url=INWORLD_TTS_BASE_URL,
        default_headers={**_auth_header(api_key), "Content-Type": "application/json"},
        timeout=timeout,
        domain=_DOMAIN,
        provider_id=_PROVIDER_ID,
    )


def _require_api_key(settings: dict) -> str:
    api_key = (settings or {}).get("api_key") or INWORLD_API_KEY
    if not api_key:
        raise ProviderError(
            PROVIDER_NOT_CONFIGURED,
            "The Inworld API key is not configured",
            domain=_DOMAIN,
            provider_id=_PROVIDER_ID,
        )
    return api_key


class InworldTTSProvider(TTSProvider):
    """Cloud text-to-speech via the Inworld Voice API."""

    provider_id = _PROVIDER_ID

    def synthesize(
        self,
        text: str,
        settings: dict,
        voice: Optional[str] = None,
        speed: float = 1.0,
        on_progress: Optional[Callable] = None,
    ) -> TTSResult:
        settings = dict(settings or {})
        api_key = _require_api_key(settings)
        voice = voice or settings.get("voice") or DEFAULT_VOICE
        model_id = settings.get("model") or INWORLD_TTS_MODEL

        if on_progress:
            on_progress("Synthesizing via Inworld API...")

        # Bella is tuned differently from every other voice; a remote-model
        # quirk, preserved verbatim.
        is_bella = "bella" in voice.lower()
        temperature = 1.11 if is_bella else 1.1
        speaking_rate = 1.0 if is_bella else 1.15

        payload = {
            "text": text,
            "voiceId": voice,
            "modelId": model_id,
            "audioConfig": {
                "speakingRate": speaking_rate,
            },
            "temperature": temperature,
        }

        start = time.perf_counter()
        # A generation POST is never transport-retried (D40): a lost response
        # after the remote accepted the work would bill and render twice.
        data = _client(api_key).post_json("/voice", payload)
        elapsed = time.perf_counter() - start

        audio_b64 = data.get("audioContent") or ""
        if not audio_b64:
            raise ProviderError(
                PROVIDER_RESPONSE_MALFORMED,
                "The Inworld API returned no audio content",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
            )
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception as exc:
            raise classify_http_error(
                exc, domain=_DOMAIN, provider_id=_PROVIDER_ID
            ) from exc

        usage = data.get("usage") or {}
        characters = usage.get("processedCharactersCount", len(text))

        job_dir, basename, sidecar_name = _resolve_output(settings)
        os.makedirs(job_dir, exist_ok=True)
        wav_path = os.path.join(job_dir, basename + ".wav")

        audio, sr = sf.read(io.BytesIO(audio_bytes))
        sf.write(wav_path, audio, sr)
        # Loudness normalization used to sit in the two Inworld *call sites*
        # (`/api/tts/generate` and the pipeline branch), so a third caller got
        # audio several LU quieter than Kokoro's. It belongs to whoever produces
        # the audio (step 15.2).
        from scriptase.modules.tts.audio import run_loudnorm

        run_loudnorm(wav_path)

        info = sf.info(wav_path)
        duration = round(info.duration, 2)

        metadata = {
            "filename": basename + ".wav",
            "folder": os.path.basename(job_dir),
            "prompt": text,
            "model": model_id,
            "model_id": _PROVIDER_ID,
            "voice": voice,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "inference_time": round(elapsed, 3),
            "duration_seconds": duration,
            "sample_rate": info.samplerate,
            "characters_billed": characters,
        }

        sidecar = os.path.join(job_dir, sidecar_name)
        safe_json_write(sidecar, metadata, indent=2)
        metadata["metadata_path"] = sidecar

        return TTSResult(
            audio_path=wav_path,
            duration_seconds=duration,
            format="wav",
            sample_rate=info.samplerate,
            metadata=metadata,
        )

    def list_voices(self, settings: dict) -> list[Voice]:
        global _voices_cache, _voices_cache_ts

        api_key = (settings or {}).get("api_key") or INWORLD_API_KEY
        if not api_key:
            return []

        with _voices_cache_lock:
            if _voices_cache is not None and (time.time() - _voices_cache_ts) < _VOICES_TTL:
                return _as_voices(_voices_cache)

        try:
            data = _client(api_key, timeout=10).get_json("/voices")
            voices = data.get("voices") or []
        except ProviderError as exc:
            # Listing voices is advisory: a stale catalog beats an empty page.
            # Only the catalog code is logged — never the body or the URL.
            logger.error("Inworld list_voices failed: {}", exc.code)
            return _as_voices(_voices_cache or [])

        with _voices_cache_lock:
            _voices_cache = voices
            _voices_cache_ts = time.time()

        return _as_voices(voices)

    def list_models(self, settings: dict) -> list[dict]:
        model = (settings or {}).get("model") or INWORLD_TTS_MODEL
        return [{"id": model, "name": model, "downloaded": True}] if model else []


def _as_voices(raw) -> list[Voice]:
    return [
        Voice(
            id=item.get("voiceId", ""),
            name=item.get("displayName", ""),
            language="",
        )
        for item in raw or ()
        if isinstance(item, dict)
    ]


def _resolve_output(settings: dict) -> tuple[str, str, str]:
    """Where this synthesis writes: `(job_dir, basename, sidecar_name)`.

    A v2 invocation supplies `output_dir` (the project's `tts/{pid}` directory),
    `output_basename`, and the sidecar name the caller wants; a direct
    `synthesize()` call supplies none of them and keeps the historical
    timestamped folder.
    """
    output_dir = str(settings.get("output_dir") or "").strip()
    if output_dir:
        basename = str(settings.get("output_basename") or "voice").strip() or "voice"
        sidecar = str(settings.get("output_sidecar") or "").strip()
        return output_dir, basename, sidecar or f"{basename}.json"
    os.makedirs(TTS_DIR, exist_ok=True)
    basename = f"{_PROVIDER_ID}_{int(time.time() * 1000)}"
    return os.path.join(TTS_DIR, basename), basename, f"{basename}.json"


def validate_settings(settings: dict) -> list[dict]:
    issues = []
    api_key = (settings or {}).get("api_key") or INWORLD_API_KEY
    if not api_key:
        issues.append({
            "field": "api_key",
            "severity": "error",
            "message": "Inworld API key is required",
        })
    return issues


def create() -> InworldTTSProvider:
    """v2 factory (contracts.md §21.1). Memoized by the registry, never at import."""
    return InworldTTSProvider()


def health_check(settings: dict) -> dict:
    api_key = (settings or {}).get("api_key") or INWORLD_API_KEY
    if not api_key:
        return {"status": "warn", "message": "API key not configured"}

    start = time.perf_counter()
    try:
        _client(api_key, timeout=10).get_json("/voices", retries=0)
    except ProviderError as exc:
        # The catalog code, never the response body or the URL.
        return {"status": "fail", "message": f"Inworld request failed ({exc.code})"}
    return {
        "status": "ok",
        "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        "message": "Connected",
    }
