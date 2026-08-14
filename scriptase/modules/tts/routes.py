"""TTS Module — text-to-speech routes

Text-to-speech generation, streaming, model management, voice blending, and
generation history for the standalone TTS page.

Step 15.2 removed the three provider-id comparisons this module used to make
(`voices`, `generate`, and `stream_audio` each branched on
`provider == "inworld"`). Generation goes through `scriptase.modules.tts.dispatch`, voice
and model lists come from the selected provider's own hooks, and streaming is
gated on the `streaming` capability. The multi-voice and chunked jobs below
still drive the Kokoro engine directly: they are page features built on voice
blending and internal chunking, and they are 16.1's to generalize.
"""

import base64
import gc
import json
import os
import re
import subprocess
import sys
import time
import threading
import uuid
from datetime import datetime
from queue import Queue

import numpy as np
import soundfile as sf
import urllib.request
from flask import Blueprint, Response, jsonify, request, send_from_directory
from loguru import logger
from pydantic import ValidationError

from config import TTS_DIR, TTS_CACHE_DIR, TRASH_DIR, MODELS_DIR, BIN_DIR, generate_project_id
from scriptase.shared.io_utils import move_to_unique_path, safe_json_write
from scriptase.providers.concurrency import exclusive_execution, exclusive_lock
from scriptase.providers.errors import (
    PROVIDER_NOT_CONFIGURED,
    PROVIDER_NOT_FOUND,
    PROVIDER_REQUEST_INVALID,
    ProviderError,
)
from scriptase.shared.security import safe_join, sanitize_project_id
from scriptase.shared.validation import validate_json
from scriptase.shared.ffmpeg_utils import find_ffmpeg
from scriptase.modules.tts import dispatch
from .schemas import BlendConfig, TtsGenerateRequest, TtsMultivoiceRequest
from .normalize import (
    normalize_for_tts, clean_for_tts,
    format_breathing_blocks, validate_brackets,
    _protect_kokoro, _restore_kokoro,
)
from .audio import pad_audio, concatenate_chunks, run_loudnorm

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

tts_bp = Blueprint("tts", __name__)


def _selected_provider(provider_id=None):
    """`(ProviderInstance, provider object)` for a request, or `ProviderError`.

    An empty `provider_id` follows the domain selection (§24.1), which is what
    lets every route below answer for whichever provider the operator picked
    without naming one.
    """
    instance, _reason = dispatch.resolve_provider({"provider": provider_id or ""})
    return instance, instance.create()


# Provider error codes the legacy page reports as something other than a 500.
_ERROR_STATUS = {
    PROVIDER_NOT_CONFIGURED: 503,
    PROVIDER_REQUEST_INVALID: 400,
    PROVIDER_NOT_FOUND: 404,
}


def _status_for(exc: ProviderError) -> int:
    return _ERROR_STATUS.get(exc.code, 502)

# ---------------------------------------------------------------------------
# Kokoro engine — owned by the provider package (contracts.md B5 / K1)
#
# This module used to declare its own `kokoro_instance`, `kokoro_lock`,
# `generation_inference_lock`, misaki handle, model table, and voice catalog,
# while `providers/kokoro/provider.py` declared a second, never-populated copy
# of all of them. Two model caches were reachable and the two inference locks
# guarded nothing in common. The provider package is now the single owner and
# everything below delegates to it, so these routes and the workflow/pipeline
# paths share one ONNX session, one G2P engine, and one exclusivity lock.
#
# `_voices()` and `_models()` are functions rather than constants on purpose:
# `load_model()` replaces the voice catalog with the model's own list, and a
# module-level copy taken at import time would freeze the shipped defaults.
# ---------------------------------------------------------------------------

_ENGINE_ATTRS = frozenset({
    "MODELS", "VOICES", "VOICE_LANG_MAP",
    "kokoro_instance", "kokoro_lock",
})


def _engine():
    from scriptase.modules.tts.providers import kokoro_engine

    return kokoro_engine()


def __getattr__(name):
    """Re-export the engine's state so `from scriptase.modules.tts.routes import VOICES` works.

    Resolved on access, never at import: touching the registry while this module
    is still being imported would run discovery before the app has booted.
    """
    if name in _ENGINE_ATTRS:
        return getattr(_engine(), name)
    if name == "generation_inference_lock":
        return exclusive_lock("tts", "kokoro")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _voices() -> list:
    return _engine().VOICES


def _models() -> dict:
    return _engine().MODELS


def _voice_to_lang(voice_name: str) -> str:
    return _engine()._voice_to_lang(voice_name)


def _blend_voices(kokoro_inst, voice_a: str, voice_b: str,
                  ratio: float, method: str = "slerp") -> np.ndarray:
    return _engine()._blend_voices(kokoro_inst, voice_a, voice_b, ratio, method)


def _phonemize_with_misaki(text: str, lang: str = "en-us") -> tuple[str | None, bool]:
    return _engine()._phonemize_with_misaki(text, lang)


def _model_files_present() -> bool:
    return _engine()._model_files_present()


def load_model():
    return _engine().load_model()


def _inference_lock():
    """Serialize Kokoro inference iff the manifest declares it (§20.4).

    The route no longer knows *that* Kokoro is exclusive — it asks, and the
    capability answers. A provider without the capability pays nothing.
    """
    return exclusive_execution("tts", "kokoro")


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

generation_jobs = {}
generation_jobs_lock = threading.Lock()

_stream_active = threading.Event()

_metadata_locks = {}
_metadata_locks_lock = threading.Lock()


def _get_metadata_lock(basename):
    with _metadata_locks_lock:
        if basename not in _metadata_locks:
            _metadata_locks[basename] = threading.Lock()
        return _metadata_locks[basename]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tts_job_dir(basename):
    return os.path.join(TTS_DIR, basename)


def _safe_job_dir_from_filename(filename: str, require_wav: bool = False) -> tuple[str, str, str]:
    safe_file = os.path.basename(filename or "")
    if not safe_file:
        raise ValueError("Missing filename")
    if require_wav and not safe_file.endswith(".wav"):
        raise ValueError("Only .wav files are supported")
    folder = _folder_for_file(safe_file)
    safe_folder = sanitize_project_id(folder)
    if not safe_folder:
        raise ValueError("Invalid filename")
    return safe_join(TTS_DIR, safe_folder), safe_file, safe_folder


def _folder_for_file(filename):
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    changed = True
    while changed:
        changed = False
        for suffix in ("_cleaned", "_enhanced"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                changed = True
    return base


def _update_metadata(basename, updates):
    lock = _get_metadata_lock(basename)
    json_path = os.path.join(_tts_job_dir(basename), basename + ".json")
    with lock:
        with open(json_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        metadata.update(updates)
        safe_json_write(json_path, metadata, indent=2)
    return metadata


def _read_metadata(basename):
    lock = _get_metadata_lock(basename)
    json_path = os.path.join(_tts_job_dir(basename), basename + ".json")
    with lock:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)


def generate_filename(prompt: str) -> str:
    """Generate a unique pm_ project ID for manual TTS generations."""
    return generate_project_id("pm")


# ---------------------------------------------------------------------------
# Model management
# ---------------------------------------------------------------------------

def _download_file_with_progress(url: str, dest_path: str, queue: Queue, label: str):
    tmp_path = dest_path + ".tmp"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ScriptToScene-Studio/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 256 * 1024
            start_time = time.time()

            with open(tmp_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = time.time() - start_time
                    speed = downloaded / max(elapsed, 0.001)
                    progress = int((downloaded / total) * 100) if total else 0

                    if speed >= 1_000_000:
                        speed_str = f"{speed / 1_000_000:.1f}MB/s"
                    elif speed >= 1_000:
                        speed_str = f"{speed / 1_000:.1f}KB/s"
                    else:
                        speed_str = f"{speed:.0f}B/s"

                    queue.put({
                        "phase": "downloading",
                        "file": label,
                        "progress": progress,
                        "downloaded_mb": round(downloaded / 1_000_000, 2),
                        "total_mb": round(total / 1_000_000, 2),
                        "size": f"{total / 1_000_000:.1f}MB",
                        "speed": speed_str,
                    })

        os.replace(tmp_path, dest_path)
    except Exception:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        raise


def _cleanup_old_jobs(max_age_s=300):
    now = time.time()
    with generation_jobs_lock:
        expired = [jid for jid, job in generation_jobs.items()
                   if now - job.get("created", 0) > max_age_s]
        for jid in expired:
            del generation_jobs[jid]


# ===================================================================
# Routes
# ===================================================================

# --- Normalize text ---
@tts_bp.route("/api/tts/normalize", methods=["POST"])
def normalize_text():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    text = data.get("text", "")
    if not isinstance(text, str):
        return jsonify({"error": "Text must be a string"}), 400
    if not text.strip():
        return jsonify({"error": "No text provided"}), 400

    # Protect Kokoro links so their brackets don't affect validation/extraction
    text_safe, kokoro_saved = _protect_kokoro(text)
    validity = validate_brackets(text_safe)
    if validity == "well_formed":
        blocks = re.findall(r'\[([^\[\]]+)\]', text_safe)
        blocks = [_restore_kokoro(b, kokoro_saved) for b in blocks]
        normalized_blocks = [normalize_for_tts(b) for b in blocks if b.strip()]
        if len(normalized_blocks) <= 1:
            formatted = normalized_blocks[0] if normalized_blocks else text.strip()
        else:
            formatted = "\n\n".join(f"[{b}]" for b in normalized_blocks)
    else:
        stripped = re.sub(r'[\[\]]', '', text_safe)
        stripped = _restore_kokoro(stripped, kokoro_saved)
        normalized = normalize_for_tts(stripped)
        formatted = format_breathing_blocks(normalized)

    return jsonify({"original": text, "normalized": formatted})


# --- Models ---
@tts_bp.route("/api/tts/models")
def models():
    """The selected provider's own model list, via its optional hook (§22.4)."""
    try:
        instance, provider = _selected_provider()
    except ProviderError as exc:
        return jsonify({"error": exc.message}), _status_for(exc)
    models_hook = getattr(provider, "list_models", None)
    if not callable(models_hook):
        return jsonify([])
    settings = dispatch.resolved_settings(instance)
    return jsonify([
        {"id": m.get("id"), "name": m.get("name") or m.get("id"), "size": m.get("size", "")}
        for m in models_hook(settings) or ()
        if isinstance(m, dict) and m.get("id")
    ])


# --- Voices ---
@tts_bp.route("/api/tts/voices")
def voices():
    """One reconciled voice list for whichever provider is asked for.

    Answered by `dispatch.list_voices` — the provider's own hook, falling back
    to what it declares — so a provider that ships tomorrow populates this list
    without an edit here, and the canvas dropdown resolves the same catalog.
    """
    try:
        instance, _provider = _selected_provider(request.args.get("provider"))
    except ProviderError as exc:
        return jsonify({"error": exc.message}), _status_for(exc)
    return jsonify(dispatch.list_voices(instance))


# --- Model status ---
@tts_bp.route("/api/tts/model-status/<model_id>")
def model_status(model_id):
    if model_id not in _models():
        return jsonify({"error": "Unknown model"}), 404
    cached = _model_files_present()
    return jsonify({"model_id": model_id, "cached": cached})


# --- Download model with SSE progress ---
@tts_bp.route("/api/tts/download-model/<model_id>")
def download_model(model_id):
    if model_id not in _models():
        return jsonify({"error": "Unknown model"}), 404

    model_cfg = _models()[model_id]

    def _stream_download(url, dest, q, label):
        result = {}

        def _run():
            try:
                _download_file_with_progress(url, dest, q, label)
            except Exception as e:
                logger.error("Download failed for {}: {}", label, e)
                result["error"] = e

        t = threading.Thread(target=_run)
        t.start()
        while t.is_alive():
            t.join(timeout=0.15)
            while not q.empty():
                yield f"data: {json.dumps(q.get())}\n\n"
        while not q.empty():
            yield f"data: {json.dumps(q.get())}\n\n"
        if "error" in result:
            raise result["error"]

    def stream():
        q = Queue()
        yield f"data: {json.dumps({'phase': 'checking', 'model': model_id})}\n\n"

        try:
            onnx_path = os.path.join(MODELS_DIR, model_cfg["onnx_file"])
            voices_path = os.path.join(MODELS_DIR, model_cfg["voices_file"])

            if not os.path.isfile(onnx_path):
                for event in _stream_download(model_cfg["onnx_url"], onnx_path, q, model_cfg["onnx_file"]):
                    yield event

            if not os.path.isfile(voices_path):
                for event in _stream_download(model_cfg["voices_url"], voices_path, q, model_cfg["voices_file"]):
                    yield event

            yield f"data: {json.dumps({'phase': 'loading', 'message': 'Loading model...'})}\n\n"
            load_result = {}

            def _load():
                try:
                    load_model()
                except Exception as e:
                    load_result["error"] = e

            t = threading.Thread(target=_load)
            t.start()
            while t.is_alive():
                t.join(timeout=1.0)
                yield f"data: {json.dumps({'phase': 'loading', 'message': 'Loading model...'})}\n\n"
            if "error" in load_result:
                raise load_result["error"]

            yield f"data: {json.dumps({'phase': 'ready', 'message': 'Model ready'})}\n\n"

        except Exception as e:
            logger.exception("Model download/load failed")
            yield f"data: {json.dumps({'phase': 'error', 'message': str(e)})}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# --- Generate audio ---
@tts_bp.route("/api/tts/generate", methods=["POST"])
@validate_json(TtsGenerateRequest)
def generate(data: TtsGenerateRequest):
    """Synthesize one standalone generation through the selected provider.

    One path for every provider. The Kokoro/Inworld fork this replaces also
    produced two different metadata dicts; the reconciled one comes from
    `scriptase.modules.tts.dispatch`, so a history entry has the same keys whichever
    provider wrote it.
    """
    if _stream_active.is_set():
        return jsonify({"error": "A stream is already in progress. Please wait."}), 429
    with generation_jobs_lock:
        for job in generation_jobs.values():
            if job.get("status") == "running":
                return jsonify({"error": "A generation is already in progress. Please wait or abort."}), 429

    prompt = data.prompt
    tts_prompt = prompt.strip() if data.skip_clean else clean_for_tts(prompt)
    basename = generate_filename(prompt)

    config = {
        "text": tts_prompt,
        "provider": data.provider,
        "voice": data.voice,
        "tts_voice": getattr(data, "tts_voice", "") or "",
        "speed": data.speed,
        "tts_provider_options": _blend_options(data.blend),
    }

    logger.info("Generate  \033[1mTTS\033[0m | {} | {} chars", data.voice, len(prompt))
    try:
        metadata = dispatch.synthesize(
            config,
            project_id=basename,
            basename=basename,
            # The history page reads `{folder}/{folder}.json`, so the standalone
            # layout keeps its own sidecar name rather than the managed one.
            sidecar_name=f"{basename}.json",
            extra_metadata={"max_silence_ms": data.max_silence_ms},
        )
    except ProviderError as exc:
        return jsonify({"error": exc.message}), _status_for(exc)

    return jsonify({k: v for k, v in metadata.items() if k != "wav_path"})


def _blend_options(blend) -> dict:
    """The route's blend request as the per-run options a provider declares.

    Named settings, not a special case: a provider that declares no blending
    receives keys it ignores, and `provider_run_options`-style validation is
    the same one every other per-run option goes through.
    """
    if blend is None:
        return {}
    method = blend.method if blend.method in ("slerp", "lerp") else "slerp"
    return {
        "blend": True,
        "blendA": blend.voice_a,
        "blendB": blend.voice_b,
        "blendRatio": round(float(blend.ratio) * 100, 4),
        "blendMethod": method,
    }


# --- Chunked generation SSE progress ---
@tts_bp.route("/api/tts/generate-progress/<job_id>")
def generate_progress(job_id):
    with generation_jobs_lock:
        job = generation_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job ID"}), 404

    def stream():
        status = job.get("status")
        if status == "done":
            yield f"data: {json.dumps({'phase': 'done', 'metadata': job.get('metadata')})}\n\n"
            return
        if status in ("error", "aborted"):
            yield f"data: {json.dumps({'phase': status})}\n\n"
            return

        q = job["queue"]
        while True:
            try:
                event = q.get(timeout=10)
            except Exception:
                with generation_jobs_lock:
                    cur_status = job.get("status")
                if cur_status == "done":
                    yield f"data: {json.dumps({'phase': 'done', 'metadata': job.get('metadata')})}\n\n"
                    break
                if cur_status in ("error", "aborted"):
                    yield f"data: {json.dumps({'phase': cur_status})}\n\n"
                    break
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("phase") in ("done", "error", "aborted"):
                break

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# --- Abort generation ---
@tts_bp.route("/api/tts/generate-abort/<job_id>", methods=["POST"])
def abort_generation(job_id):
    with generation_jobs_lock:
        job = generation_jobs.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job ID"}), 404
        job["abort"] = True
    return jsonify({"status": "aborting"})


# --- TTS preview cache ---
# The key lives in `scriptase.modules.tts.dispatch` and carries the provider id, so the
# same (text, voice, speed) triple no longer collides across providers.
_cache_path = dispatch.cache_path


def _preview_key(text: str, voice: str, speed: float, provider: str = "") -> str:
    instance, _reason = dispatch.resolve_provider({"provider": provider})
    return dispatch.cache_key(text, voice, speed, instance.id)


@tts_bp.route("/api/tts/cache/check", methods=["POST"])
def cache_check():
    """Check if a cached preview WAV exists for (text, voice, speed)."""
    data = request.get_json(silent=True) or {}
    text = (data.get("prompt") or "").strip()
    voice = data.get("voice", "")
    try:
        speed = round(max(0.5, min(2.0, float(data.get("speed", 1.0)))), 2)
    except (TypeError, ValueError):
        speed = 1.0
    if not text:
        return jsonify({"cached": False})
    try:
        key = _preview_key(text, voice, speed, data.get("provider", ""))
    except ProviderError:
        return jsonify({"cached": False})
    if os.path.isfile(_cache_path(key)):
        return jsonify({"cached": True, "key": key})
    return jsonify({"cached": False})


@tts_bp.route("/api/tts/cache/<key>")
def cache_serve(key):
    """Serve a cached preview WAV file."""
    key = re.sub(r'[^a-f0-9]', '', key)[:16]
    path = _cache_path(key)
    if not os.path.isfile(path):
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(TTS_CACHE_DIR, f"{key}.wav", mimetype="audio/wav")


# --- Stream audio (listen-only, no save) ---
@tts_bp.route("/api/tts/stream", methods=["POST"])
def stream_audio():
    """Stream audio from a provider that declares the `streaming` capability.

    The route used to reject Inworld by name and then drive the Kokoro engine
    directly. It asks the manifest instead and calls `provider.stream()`, so a
    second streaming provider works here with no edit — and a non-streaming one
    is refused for a reason the catalog can explain (step 15.2).
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400

    prompt = data.get("prompt", "")
    if not isinstance(prompt, str):
        return jsonify({"error": "Prompt must be a string"}), 400
    if not prompt.strip():
        return jsonify({"error": "Prompt is required"}), 400
    try:
        speed = max(0.5, min(2.0, float(data.get("speed", 1.0))))
    except (TypeError, ValueError):
        return jsonify({"error": "Speed must be a number between 0.5 and 2.0"}), 400

    blend = data.get("blend")
    if blend is not None and not isinstance(blend, dict):
        return jsonify({"error": "Blend must be an object"}), 400
    try:
        options = _blend_options(BlendConfig(**blend) if blend else None)
    except ValidationError:
        return jsonify({"error": "Blend ratio must be between 0.0 and 1.0"}), 400

    try:
        instance, provider = _selected_provider(data.get("provider"))
    except ProviderError as exc:
        return jsonify({"error": exc.message}), _status_for(exc)
    if not instance.capabilities.get("streaming"):
        return jsonify({
            "error": f"{instance.label} does not support streaming. "
                     "Use /api/tts/generate instead."
        }), 400

    if _stream_active.is_set():
        return jsonify({"error": "A stream is already in progress."}), 429
    with generation_jobs_lock:
        for job in generation_jobs.values():
            if job.get("status") == "running":
                return jsonify({"error": "A generation is already in progress. Please wait or abort."}), 429

    settings = dispatch.resolved_settings(instance, options)
    voice = dispatch.resolve_voice(instance, data, settings=settings)
    tts_prompt = prompt.strip() if data.get("skip_clean") else clean_for_tts(prompt)

    cache_k = dispatch.cache_key(prompt, voice, speed, instance.id)
    cache_p = _cache_path(cache_k)

    logger.info("Stream  \033[1m{}\033[0m | {} | {} chars", instance.id, voice, len(prompt))

    q = Queue()

    def _run_stream():
        _stream_active.set()
        all_samples = []
        final_sr = 24000
        try:
            for chunk in provider.stream(tts_prompt, settings, voice=voice, speed=speed):
                if chunk.is_final:
                    break
                final_sr = chunk.sample_rate
                all_samples.append(chunk.samples)
                q.put(("audio", chunk.samples, chunk.sample_rate))
            q.put(("done", None, None))

            # Save to cache as WAV
            if all_samples:
                try:
                    os.makedirs(TTS_CACHE_DIR, exist_ok=True)
                    combined = np.concatenate(all_samples)
                    sf.write(cache_p, combined, final_sr, format="WAV")
                    logger.debug("Cached preview → {}", cache_k)
                except Exception:
                    logger.opt(exception=True).debug("Cache write failed")
        except ProviderError as exc:
            logger.error("Stream failed for {}: {}", instance.id, exc.code)
            q.put(("error", exc.message, None))
        except Exception as e:
            logger.exception("Stream generation failed")
            q.put(("error", str(e), None))
        finally:
            _stream_active.clear()

    t = threading.Thread(target=_run_stream, daemon=True)
    t.start()

    def _sse():
        chunk_num = 0
        while True:
            try:
                kind, payload, sr = q.get(timeout=60)
            except Exception:
                yield f"data: {json.dumps({'phase': 'error', 'message': 'Stream timed out'})}\n\n"
                break
            if kind == "audio":
                chunk_num += 1
                pcm_bytes = payload.astype(np.float32).tobytes()
                b64 = base64.b64encode(pcm_bytes).decode("ascii")
                yield f"data: {json.dumps({'phase': 'audio', 'chunk': chunk_num, 'samples': b64, 'sample_rate': sr})}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'phase': 'done', 'total_chunks': chunk_num})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'phase': 'error', 'message': payload})}\n\n"
                break

    return Response(
        _sse(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# --- List generations ---
@tts_bp.route("/api/tts/generation")
def list_audio():
    files = []
    if not os.path.exists(TTS_DIR):
        return jsonify(files)
    for entry in os.listdir(TTS_DIR):
        entry_path = os.path.join(TTS_DIR, entry)
        if not os.path.isdir(entry_path) or entry == "TRASH":
            continue
        json_path = os.path.join(entry_path, entry + ".json")
        if not os.path.isfile(json_path):
            json_path = os.path.join(entry_path, "tts.json")
        if os.path.isfile(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    files.append(json.load(f))
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Skipping corrupt/partial metadata {}: {}", entry, e)
    files.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify(files)


# --- Delete generation (move to TRASH) ---
@tts_bp.route("/api/tts/generation/<filename>", methods=["DELETE"])
def delete_audio(filename):
    try:
        job_dir, _safe_file, basename = _safe_job_dir_from_filename(filename)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if os.path.isdir(job_dir):
        tts_trash = os.path.join(TRASH_DIR, "tts")
        move_to_unique_path(job_dir, tts_trash, basename)
        return jsonify({"status": "deleted", "filename": _safe_file})
    return jsonify({"error": "File not found"}), 404


# --- Delete all generations ---
@tts_bp.route("/api/tts/generation", methods=["DELETE"])
def delete_all_audio():
    count = 0
    tts_trash = os.path.join(TRASH_DIR, "tts")
    for entry in os.listdir(TTS_DIR):
        entry_path = os.path.join(TTS_DIR, entry)
        if os.path.isdir(entry_path):
            move_to_unique_path(entry_path, tts_trash, entry)
            count += 1
    return jsonify({"status": "deleted", "count": count})


# --- Open generation folder ---
@tts_bp.route("/api/tts/open-generation-folder", methods=["POST"])
def open_audio_folder():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "")
    filename = os.path.basename(filename) if filename else ""
    basename = filename.rsplit(".", 1)[0] if filename else ""
    job_dir = os.path.abspath(_tts_job_dir(basename)) if basename else ""
    file_path = os.path.join(job_dir, filename) if job_dir and filename else ""
    folder = os.path.abspath(TTS_DIR)
    try:
        if sys.platform == "win32":
            if file_path and os.path.exists(file_path):
                subprocess.Popen(["explorer", "/select,", file_path])
            else:
                os.startfile(folder)
        elif sys.platform == "darwin":
            if file_path and os.path.exists(file_path):
                subprocess.Popen(["open", "-R", file_path])
            else:
                subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error("Failed to open folder: {}", e)
        return jsonify({"error": str(e)}), 500


# --- MP3 check ---
@tts_bp.route("/api/tts/generation/<filename>/mp3-check")
def check_mp3(filename):
    try:
        job_dir, safe_file, _ = _safe_job_dir_from_filename(filename, require_wav=True)
    except ValueError:
        return jsonify({"exists": False})
    mp3_name = safe_file.rsplit(".", 1)[0] + ".mp3"
    mp3_path = os.path.join(job_dir, mp3_name)
    return jsonify({"exists": os.path.exists(mp3_path)})


# --- Serve cached MP3 ---
@tts_bp.route("/api/tts/generation/<filename>/mp3")
def serve_mp3(filename):
    try:
        job_dir, safe_file, _ = _safe_job_dir_from_filename(filename, require_wav=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    mp3_name = safe_file.rsplit(".", 1)[0] + ".mp3"
    mp3_path = os.path.join(job_dir, mp3_name)
    if not os.path.exists(mp3_path):
        return jsonify({"error": "MP3 not found - convert first"}), 404
    return send_from_directory(job_dir, mp3_name, as_attachment=True)


# --- Convert WAV to MP3 with SSE progress ---
@tts_bp.route("/api/tts/generation/<filename>/mp3-convert")
def convert_to_mp3(filename):
    try:
        job_dir, safe_file, _ = _safe_job_dir_from_filename(filename, require_wav=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    wav_path = os.path.join(job_dir, safe_file)
    if not os.path.exists(wav_path):
        return jsonify({"error": "File not found"}), 404

    mp3_name = safe_file.rsplit(".", 1)[0] + ".mp3"
    mp3_path = os.path.join(job_dir, mp3_name)

    if os.path.exists(mp3_path):
        def _done():
            yield f"data: {json.dumps({'phase': 'done', 'progress': 100})}\n\n"
        return Response(
            _done(), mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return jsonify({"error": "ffmpeg not found. Place ffmpeg in bin/ or install it system-wide."}), 501

    total_duration = 0.0
    json_path = wav_path.rsplit(".", 1)[0] + ".json"
    if os.path.exists(json_path):
        with open(json_path) as f:
            total_duration = json.load(f).get("duration_seconds", 0.0)
    if total_duration <= 0:
        try:
            info = sf.info(wav_path)
            total_duration = info.duration
        except Exception:
            pass

    def stream():
        yield f"data: {json.dumps({'phase': 'converting', 'progress': 0})}\n\n"

        proc = subprocess.Popen(
            [ffmpeg, "-i", wav_path, "-codec:a", "libmp3lame", "-qscale:a", "2",
             "-progress", "pipe:1", "-nostats", "-y", mp3_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )

        try:
            last_pct = 0
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        if total_duration > 0:
                            pct = min(99, int((us / 1_000_000) / total_duration * 100))
                            if pct > last_pct:
                                last_pct = pct
                                yield f"data: {json.dumps({'phase': 'converting', 'progress': pct})}\n\n"
                    except (ValueError, ZeroDivisionError):
                        pass
                elif line == "progress=end":
                    break

            proc.wait(timeout=30)

            if proc.returncode == 0:
                yield f"data: {json.dumps({'phase': 'done', 'progress': 100})}\n\n"
            else:
                err = proc.stderr.read()[:200] if proc.stderr else "Unknown error"
                yield f"data: {json.dumps({'phase': 'error', 'message': err})}\n\n"
        except GeneratorExit:
            proc.kill()
            proc.wait(timeout=5)
        finally:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

    return Response(
        stream(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# --- Multi-voice generation ---

def _background_multivoice_generate(job_id, segments, speed, gap_ms, prompt, basename):
    """Generate audio with different voices per segment, then concatenate."""
    with generation_jobs_lock:
        job = generation_jobs[job_id]
    q = job["queue"]
    try:
        kokoro = load_model()
        audio_chunks = []
        total = len(segments)
        total_inference = 0.0
        voices_used = set()

        for i, seg in enumerate(segments):
            if job.get("abort"):
                q.put({"phase": "aborted"})
                with generation_jobs_lock:
                    job["status"] = "aborted"
                return

            seg_text = seg.get("text", "").strip()
            seg_voice = seg.get("voice", "af_heart")
            seg_speed = max(0.5, min(2.0, float(seg.get("speed", speed))))
            seg_blend = seg.get("blend")

            if not seg_text:
                continue

            voices_used.add(seg_voice)
            q.put({"phase": "generating", "chunk": i + 1, "total": total,
                    "sentence": seg_text[:60], "voice": seg_voice})

            # Resolve voice param (blend or single)
            voice_param = seg_voice
            if seg_blend:
                va = seg_blend.get("voice_a", "")
                vb = seg_blend.get("voice_b", "")
                ratio = max(0.0, min(1.0, float(seg_blend.get("ratio", 0.5))))
                method = seg_blend.get("method", "slerp")
                if va in _voices() and vb in _voices():
                    voice_param = _blend_voices(kokoro, va, vb, ratio, method)

            lang = _voice_to_lang(seg_voice)
            phonemes, is_ph = _phonemize_with_misaki(seg_text, lang)
            start = time.perf_counter()
            with _inference_lock():
                chunk_audio, _sr = kokoro.create(
                    text=phonemes, voice=voice_param, speed=seg_speed,
                    lang=lang, is_phonemes=is_ph,
                )
            elapsed = time.perf_counter() - start
            total_inference += elapsed
            audio_chunks.append(chunk_audio)

        if not audio_chunks:
            q.put({"phase": "error", "message": "No audio generated"})
            with generation_jobs_lock:
                job["status"] = "error"
            return

        q.put({"phase": "concatenating"})
        audio = concatenate_chunks(audio_chunks, sample_rate=24000, gap_ms=gap_ms, crossfade_ms=20)
        del audio_chunks
        audio = pad_audio(audio, sample_rate=24000)

        job_dir = _tts_job_dir(basename)
        os.makedirs(job_dir, exist_ok=True)
        wav_path = os.path.join(job_dir, basename + ".wav")
        sf.write(wav_path, audio, 24000)
        del audio
        gc.collect()

        q.put({"phase": "normalizing"})
        run_loudnorm(wav_path)

        info = sf.info(wav_path)
        duration_generated = info.duration
        rtf = total_inference / duration_generated if duration_generated > 0 else 0
        logger.success("Multi-voice  {:.1f}s audio in {:.2f}s | RTF {:.2f} | {} segments",
                       duration_generated, total_inference, rtf, total)

        clean_prompt = re.sub(r'[\[\]]', '', prompt).strip()
        metadata = {
            "filename": basename + ".wav",
            "folder": basename,
            "prompt": clean_prompt,
            "model": "kokoro-v1.0",
            "model_id": "kokoro",
            "voice": f"multi-voice ({len(voices_used)} voices)",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "inference_time": round(total_inference, 3),
            "rtf": round(rtf, 4),
            "duration_seconds": round(duration_generated, 2),
            "sample_rate": 24000,
            "speed": speed,
            "max_silence_ms": gap_ms,
            "words": len(clean_prompt.split()),
            "approx_tokens": int(len(clean_prompt.split()) * 1.3),
            "chunked": True,
            "num_chunks": total,
            "multi_voice": True,
            "voices_used": sorted(voices_used),
            "segments": [{"voice": s.get("voice"), "text": s.get("text", "")[:50]} for s in segments],
        }

        safe_json_write(os.path.join(job_dir, basename + ".json"), metadata, indent=2)

        q.put({"phase": "done", "metadata": metadata})
        with generation_jobs_lock:
            job["status"] = "done"
            job["metadata"] = metadata

    except Exception as e:
        logger.exception("Multi-voice generation failed")
        q.put({"phase": "error", "message": str(e)})
        with generation_jobs_lock:
            job["status"] = "error"


@tts_bp.route("/api/tts/generate-multivoice", methods=["POST"])
@validate_json(TtsMultivoiceRequest)
def generate_multivoice(data: TtsMultivoiceRequest):
    """Generate audio with different voices per segment.

    Accepts: {
        segments: [{text, voice, speed?, blend?}, ...],
        gap_ms: int (default 80),
        prompt: str (original full text for metadata)
    }
    Returns: {job_id, status: "chunking", total_chunks} (202)
    Progress via /api/tts/generate-progress/<job_id>
    """
    segments = [s.model_dump() for s in data.segments]
    gap_ms = data.gap_ms
    prompt = data.prompt
    speed = data.speed

    # Validate voices
    for i, seg in enumerate(segments):
        v = seg.get("voice", "")
        if v and v not in _voices():
            return jsonify({"error": f"Unknown voice in segment {i + 1}: {v}"}), 400

    if _stream_active.is_set():
        return jsonify({"error": "A stream is already in progress."}), 429
    with generation_jobs_lock:
        for job in generation_jobs.values():
            if job.get("status") == "running":
                return jsonify({"error": "A generation is already in progress."}), 429

    if not _model_files_present():
        return jsonify({"error": "Model not downloaded. Download it first."}), 400

    _cleanup_old_jobs()
    job_id = uuid.uuid4().hex[:12]
    basename = generate_filename(prompt or "multivoice")

    with generation_jobs_lock:
        generation_jobs[job_id] = {
            "queue": Queue(),
            "status": "running",
            "metadata": None,
            "created": time.time(),
            "abort": False,
        }

    t = threading.Thread(
        target=_background_multivoice_generate,
        args=(job_id, segments, speed, gap_ms, prompt, basename),
        daemon=True,
    )
    t.start()

    return jsonify({
        "job_id": job_id,
        "status": "chunking",
        "total_chunks": len(segments),
    }), 202


# --- Serve TTS audio files ---
@tts_bp.route("/output/tts/<path:filename>")
def serve_audio(filename):
    return send_from_directory(TTS_DIR, filename)
