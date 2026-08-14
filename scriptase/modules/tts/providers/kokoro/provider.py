"""Kokoro TTS provider — Provider Contract v2 (step 15.1).

Local Kokoro ONNX synthesis with voice blending, misaki pronunciation, and
language inference from the voice prefix.

**This module is the single owner of the Kokoro engine** (contracts.md B5 / K1).
Until 15.1 the same four pieces of process state were declared twice — here and
in `scriptase/modules/tts/routes.py` — and only the route's copy was ever populated, so a
caller reaching the provider could have loaded a second 373 MB ONNX session and
serialized on a lock nobody else held. `routes.py` and `pipeline/services.py` now
delegate here through `scriptase.modules.tts.providers.kokoro_engine()`; nothing else
defines `kokoro_instance`, the G2P engine, the voice catalog, or the model table.

The engine is reached through the registry rather than imported (B8): this folder
has no `__init__.py` and is loadable only through discovery, so the module object
callers get is guaranteed to be the one the registry serves — which is what makes
"single owner" true rather than merely intended.

Exclusive execution is **declared**, not hardcoded: the manifest carries
`exclusive_execution` and `providers_common.concurrency` derives the process-wide
lock from it, so the serialization that protects the one ONNX session no longer
depends on every caller remembering to import the right lock object.
"""

from __future__ import annotations

import gc
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

import numpy as np
import soundfile as sf
from loguru import logger

from config import MODELS_DIR, TTS_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.providers.concurrency import exclusive_execution
from scriptase.providers.errors import (
    PROVIDER_FAILED,
    PROVIDER_NOT_CONFIGURED,
    PROVIDER_REQUEST_INVALID,
    ProviderError,
)
from scriptase.modules.tts.providers.base import TTSProvider, TTSResult, TTSStreamChunk, Voice

_DOMAIN = "tts"
_PROVIDER_ID = "kokoro"

SAMPLE_RATE = 24000
DEFAULT_VOICE = "af_bella"

MODELS = {
    "kokoro": {
        "name": "Kokoro v1.0",
        "size": "~373MB",
        "onnx_file": "kokoro-v1.0.onnx",
        "voices_file": "voices-v1.0.bin",
        "onnx_url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
        "voices_url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
    },
}

VOICE_LANG_MAP = {
    "af": "en-us", "am": "en-us",
    "bf": "en-gb", "bm": "en-gb",
    "jf": "ja",    "jm": "ja",
    "zf": "cmn",   "zm": "cmn",
    "ef": "es",    "em": "es",
    "ff": "fr-fr",
    "hf": "hi",    "hm": "hi",
    "if": "it",    "im": "it",
    "pf": "pt-br", "pm": "pt-br",
}

# The shipped catalog. `load_model()` replaces it with the model's own voice list
# once the ONNX session reports one, so this is a starting point, not a constant.
VOICES = [
    # American Female
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
    "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    # American Male
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx", "am_puck",
    # British Female
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    # British Male
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    # Japanese
    "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
    # Chinese
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxuan", "zf_xiaoyi",
    "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
    # Spanish
    "ef_dora", "em_alex", "em_santa",
    # French
    "ff_siwis",
    # Hindi
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    # Italian
    "if_sara", "im_nicola",
    # Portuguese
    "pf_dora", "pm_alex", "pm_santa",
]


# ---------------------------------------------------------------------------
# Engine state — the one copy in the process (B5 / K1)
# ---------------------------------------------------------------------------

kokoro_instance = None
kokoro_lock = threading.Lock()

_misaki_g2p = None
_misaki_lock = threading.Lock()


def _voice_to_lang(voice_name: str) -> str:
    prefix = voice_name.split("_")[0] if "_" in voice_name else voice_name[:2]
    return VOICE_LANG_MAP.get(prefix, "en-us")


def _model_files_present() -> bool:
    cfg = MODELS["kokoro"]
    onnx_path = os.path.join(MODELS_DIR, cfg["onnx_file"])
    voices_path = os.path.join(MODELS_DIR, cfg["voices_file"])
    return os.path.isfile(onnx_path) and os.path.isfile(voices_path)


def load_model():
    """Load the ONNX session once per process and return it."""
    global kokoro_instance, VOICES
    if kokoro_instance is not None:
        return kokoro_instance

    from kokoro_onnx import Kokoro

    cfg = MODELS["kokoro"]
    onnx_path = os.path.join(MODELS_DIR, cfg["onnx_file"])
    voices_path = os.path.join(MODELS_DIR, cfg["voices_file"])

    with kokoro_lock:
        if kokoro_instance is None:
            logger.info("Loading Kokoro model ...")
            kokoro_instance = Kokoro(onnx_path, voices_path)
            try:
                available = kokoro_instance.get_voices()
                if available:
                    VOICES = sorted(available)
            except Exception:
                pass
            logger.success("Kokoro model ready")
    return kokoro_instance


# ---------------------------------------------------------------------------
# Voice blending (SLERP / LERP)
# ---------------------------------------------------------------------------

def _slerp(v0: np.ndarray, v1: np.ndarray, t: float) -> np.ndarray:
    v0 = v0.astype(np.float64)
    v1 = v1.astype(np.float64)
    if v0.ndim == 1:
        n0, n1 = np.linalg.norm(v0), np.linalg.norm(v1)
        dot = np.clip(np.dot(v0, v1) / (n0 * n1 + 1e-10), -1.0, 1.0)
        omega = np.arccos(dot)
        if abs(omega) < 1e-6:
            return ((1.0 - t) * v0 + t * v1).astype(np.float32)
        so = np.sin(omega)
        return ((np.sin((1.0 - t) * omega) / so) * v0
                + (np.sin(t * omega) / so) * v1).astype(np.float32)
    result = np.empty_like(v0)
    for i in range(v0.shape[0]):
        result[i] = _slerp(v0[i], v1[i], t)
    return result.astype(np.float32)


def _lerp(v0: np.ndarray, v1: np.ndarray, t: float) -> np.ndarray:
    return ((1.0 - t) * v0 + t * v1).astype(np.float32)


def _blend_voices(kokoro_inst, voice_a: str, voice_b: str,
                  ratio: float, method: str = "slerp") -> np.ndarray:
    embed_a = kokoro_inst.get_voice_style(voice_a)
    embed_b = kokoro_inst.get_voice_style(voice_b)
    if method == "slerp":
        return _slerp(embed_a, embed_b, ratio)
    return _lerp(embed_a, embed_b, ratio)


# ---------------------------------------------------------------------------
# Misaki G2P (pre-phonemizer for Kokoro pronunciation links)
# ---------------------------------------------------------------------------

def _get_misaki_g2p(british=False):
    """Lazy-load the misaki G2P engine (supports [word](+1) stress syntax)."""
    global _misaki_g2p
    with _misaki_lock:
        if _misaki_g2p is None:
            try:
                from misaki import en
                _misaki_g2p = en.G2P(trf=False, british=british)
                logger.success("Misaki G2P loaded (british={})", british)
            except ImportError:
                logger.warning("misaki not installed — Kokoro pronunciation links will not work")
                return None
            except Exception:
                logger.exception("Failed to load misaki G2P")
                return None
        return _misaki_g2p


def _phonemize_with_misaki(text: str, lang: str = "en-us") -> tuple[str | None, bool]:
    """Convert text to phonemes using misaki G2P.

    Returns (phonemes, success). If misaki is unavailable or fails, returns
    (original_text, False) so the caller falls back to espeak via kokoro-onnx's
    default pipeline.
    """
    # Only use misaki for English — other languages use kokoro's built-in G2P.
    if not lang.startswith("en"):
        return text, False

    british = lang == "en-gb"
    g2p = _get_misaki_g2p(british=british)
    if g2p is None:
        return text, False

    try:
        phonemes, _tokens = g2p(text)
        if phonemes and phonemes.strip():
            return phonemes, True
    except Exception:
        logger.exception("Misaki G2P failed, falling back to espeak")
    return text, False


def _tts_job_dir(basename):
    return os.path.join(TTS_DIR, basename)


def _fail(code: str, message: str, exc: BaseException | None = None) -> ProviderError:
    """A `ProviderError` that never copies `str(exc)` into its message (§34.4)."""
    return ProviderError(
        code,
        message,
        domain=_DOMAIN,
        provider_id=_PROVIDER_ID,
        cause_type=type(exc).__name__ if exc is not None else None,
    )


class KokoroTTSProvider(TTSProvider):
    """Local Kokoro ONNX text-to-speech."""

    provider_id = _PROVIDER_ID

    def _prepare(self, text: str, settings: dict, voice: Optional[str], speed: float):
        """Resolve everything one `kokoro.create*()` call needs.

        Shared by `synthesize()` and `stream()` so the two entry points cannot
        disagree about the voice, the blend recipe, the inferred language, or
        the phonemization — before 15.2 the streaming half of that logic lived
        in `tts/routes.py` and had already drifted.
        """
        settings = dict(settings or {})
        voice = voice or settings.get("voice") or DEFAULT_VOICE
        speed = float(settings.get("speed", speed) or 1.0)

        kokoro = self._load()
        lang = settings.get("lang_override") or _voice_to_lang(voice)

        blend_meta = None
        voice_param: Any = voice

        if settings.get("blend", False):
            voice_a = settings.get("blendA", "af_heart")
            voice_b = settings.get("blendB", "am_adam")
            blend_ratio = float(settings.get("blendRatio", 50)) / 100.0
            blend_method = settings.get("blendMethod", "slerp")
            if blend_method not in ("slerp", "lerp"):
                blend_method = "slerp"
            blend_meta = {
                "voiceA": voice_a,
                "voiceB": voice_b,
                "ratio": blend_ratio,
                "method": blend_method,
            }
            try:
                blended_embed = _blend_voices(
                    kokoro, voice_a, voice_b, blend_ratio, blend_method
                )
            except (KeyError, ValueError) as exc:
                raise _fail(
                    PROVIDER_REQUEST_INVALID,
                    "One of the voices to blend is not available",
                    exc,
                ) from exc
            voice_param = (blended_embed, voice_a, voice_b)

        phonemes, is_ph = _phonemize_with_misaki(text, lang)
        return kokoro, voice, voice_param, speed, lang, phonemes, is_ph, blend_meta

    def synthesize(
        self,
        text: str,
        settings: dict,
        voice: Optional[str] = None,
        speed: float = 1.0,
        on_progress: Optional[Callable] = None,
    ) -> TTSResult:
        settings = dict(settings or {})
        (
            kokoro, voice, voice_param, speed, lang, phonemes, is_ph, blend_meta
        ) = self._prepare(text, settings, voice, speed)

        if on_progress:
            on_progress("Synthesizing...")

        start = time.perf_counter()
        # Declared by the manifest, applied by the platform: one ONNX session
        # cannot serve two concurrent `create()` calls.
        with exclusive_execution(_DOMAIN, _PROVIDER_ID):
            try:
                audio, _sr = kokoro.create(
                    text=phonemes,
                    voice=voice_param,
                    speed=speed,
                    lang=lang,
                    is_phonemes=is_ph,
                )
            except (KeyError, ValueError) as exc:
                raise _fail(
                    PROVIDER_REQUEST_INVALID,
                    f"The model rejected voice '{voice}' or the requested language",
                    exc,
                ) from exc
            except Exception as exc:
                raise _fail(PROVIDER_FAILED, "Kokoro synthesis failed", exc) from exc
        inference_time = time.perf_counter() - start

        job_dir, basename, sidecar_name = _resolve_output(settings)
        os.makedirs(job_dir, exist_ok=True)
        wav_path = os.path.join(job_dir, basename + ".wav")

        from scriptase.modules.tts.audio import pad_audio, run_loudnorm
        audio = pad_audio(audio, sample_rate=SAMPLE_RATE)
        sf.write(wav_path, audio, SAMPLE_RATE)
        run_loudnorm(wav_path)
        del audio
        gc.collect()

        info = sf.info(wav_path)
        duration = info.duration
        rtf = inference_time / duration if duration > 0 else 0

        metadata = {
            "filename": basename + ".wav",
            "folder": os.path.basename(job_dir),
            "prompt": text,
            "model": "kokoro-v1.0",
            "model_id": _PROVIDER_ID,
            "voice": voice,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "inference_time": round(inference_time, 3),
            "rtf": round(rtf, 4),
            "duration_seconds": round(duration, 2),
            "sample_rate": SAMPLE_RATE,
            "speed": speed,
        }
        if blend_meta:
            metadata["blend"] = blend_meta
            # The human-readable name of a blend is the blender's to compose;
            # the caller only knows there may be a `voice_label` (step 15.2).
            pct = int(round(blend_meta["ratio"] * 100))
            metadata["voice_label"] = (
                f"{blend_meta['voiceA']} + {blend_meta['voiceB']} "
                f"({pct}% {blend_meta['method'].upper()})"
            )

        sidecar = os.path.join(job_dir, sidecar_name)
        safe_json_write(sidecar, metadata, indent=2)
        metadata["metadata_path"] = sidecar

        return TTSResult(
            audio_path=wav_path,
            duration_seconds=duration,
            format="wav",
            sample_rate=SAMPLE_RATE,
            metadata=metadata,
        )

    def stream(
        self,
        text: str,
        settings: dict,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ):
        """Yield audio chunks as the model produces them (`streaming` capability).

        A transport capability, not an invocation: it produces no
        `ProviderResult` and writes no artifact (§32.3). The async generator
        `kokoro-onnx` returns is driven one chunk at a time rather than
        collected, so `/api/tts/stream` stays progressive.
        """
        import asyncio

        (
            kokoro, _voice, voice_param, speed, lang, phonemes, is_ph, _blend
        ) = self._prepare(text, settings, voice, speed)

        loop = asyncio.new_event_loop()
        try:
            with exclusive_execution(_DOMAIN, _PROVIDER_ID):
                producer = kokoro.create_stream(
                    text=phonemes, voice=voice_param, speed=speed,
                    lang=lang, is_phonemes=is_ph,
                )
                while True:
                    try:
                        samples, rate = loop.run_until_complete(
                            producer.__anext__()
                        )
                    except StopAsyncIteration:
                        break
                    except Exception as exc:
                        raise _fail(PROVIDER_FAILED, "Kokoro streaming failed", exc) from exc
                    yield TTSStreamChunk(samples=samples, sample_rate=int(rate))
            yield TTSStreamChunk(sample_rate=SAMPLE_RATE, is_final=True)
        finally:
            loop.close()

    def list_voices(self, settings: dict) -> list[Voice]:
        return [
            Voice(id=v, name=v, language=_voice_to_lang(v), gender=None)
            for v in VOICES
        ]

    def list_models(self, settings: dict) -> list[dict]:
        return [
            {
                "id": model_id,
                "name": cfg["name"],
                "size": cfg["size"],
                "downloaded": _model_files_present(),
            }
            for model_id, cfg in MODELS.items()
        ]

    def shutdown(self) -> None:
        global kokoro_instance
        with kokoro_lock:
            kokoro_instance = None

    @staticmethod
    def _load():
        if not _model_files_present():
            raise _fail(
                PROVIDER_NOT_CONFIGURED,
                "The Kokoro model files have not been downloaded",
            )
        try:
            return load_model()
        except ImportError as exc:
            raise _fail(
                PROVIDER_NOT_CONFIGURED, "kokoro-onnx is not installed", exc
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise _fail(PROVIDER_FAILED, "The Kokoro model failed to load", exc) from exc


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
    return _tts_job_dir(basename), basename, f"{basename}.json"


def validate_settings(settings: dict) -> list[dict]:
    issues = []
    voice = settings.get("voice", DEFAULT_VOICE)
    if voice not in VOICES:
        issues.append({
            "field": "voice",
            "severity": "warning",
            "message": f"Voice '{voice}' may not be available. Check model download.",
        })
    return issues


def create() -> KokoroTTSProvider:
    """v2 factory (contracts.md §21.1). Memoized by the registry, never at import."""
    return KokoroTTSProvider()


def health_check(settings: dict) -> dict:
    if not _model_files_present():
        return {"status": "warn", "message": "Model files not downloaded", "details": {"model_present": False}}
    try:
        load_model()
        return {"status": "ok", "latency_ms": 0, "message": "Kokoro model loaded"}
    except Exception as e:
        return {"status": "fail", "message": str(e)}
