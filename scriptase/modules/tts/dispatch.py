"""Generic TTS dispatch — step 15.2.

One path from "a caller wants narration" to "a `.wav` and a metadata dict
exist", shared by `/api/tts/generate`, the classic pipeline's `_step_tts`, and
the `tts.generate` workflow node. Before this module each of the three resolved
a provider itself and then compared its id against the two shipped ones —
`pipeline/services.py:91` and `:103`, `tts/routes.py:413`, `:525`, and `:798`.

Nothing here compares a provider id. What used to be a branch is now a question
answered by provider metadata:

  * **which voice** — the frontend sends both `voice` and `tts_voice`, and only
    one is valid for the resolved provider. `resolve_voice()` picks the
    candidate the provider's own settings schema accepts, then falls back to
    that schema's default. P5 closed without naming a provider;
  * **how it is serialized** — `exclusive_execution`, declared by the manifest
    (step 15.1);
  * **whether it streams** — the `streaming` capability, read by the route.

The result is one reconciled metadata dict and one `job_meta` block for every
provider, built from the platform-authored `Provenance` rather than assembled
twice with drifting keys.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone

import soundfile as sf
from loguru import logger

from config import TTS_CACHE_DIR, TTS_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.providers import boundary, settings_manager
from scriptase.providers.domains import DOMAINS
from scriptase.providers.errors import (
    PROVIDER_NOT_FOUND,
    ProviderError,
)
from scriptase.providers.hub import hub
from scriptase.providers.invocation import build_invocation
from scriptase.providers.results import resolve_ref
from scriptase.providers.settings_schema import properties
from scriptase.modules.tts.providers.contract import TTSRequest

DOMAIN = "tts"

# The historical sidecar next to the audio (§32.3). The standalone TTS page
# keeps `{basename}.json` instead; `synthesize()` takes the name.
SIDECAR_NAME = "tts.json"

# Voice candidates in precedence order. Both spellings survive as compatibility
# *inputs* — the caller may keep sending either, and dispatch decides which one
# the resolved provider can actually use.
VOICE_FIELDS = ("voice", "tts_voice")

# Keys of the reconciled metadata dict that never reach the sidecar file:
# `wav_path` is absolute (§36 L7) and is the caller's in-process handle.
_TRANSIENT_KEYS = frozenset({"wav_path"})


# ---------------------------------------------------------------------------
# Provider resolution (contracts.md §24.1)
# ---------------------------------------------------------------------------


def resolve_provider_id(config=None) -> tuple[str, str]:
    """`(instance_or_type_id, selection_reason)` for a TTS request.

    The §24.1 precedence chain, with the two historical override keys accepted
    as compatibility inputs so a caller that predates `provider_id` still
    selects what it always did. After step 3.2 the request value is typically
    an instance id; selection falls back to the domain's selected instance.
    """
    config = dict(config or {})
    for key, reason in (
        ("tts_provider_override", "request"),
        ("provider_id", "request"),
        ("tts_provider", "request"),
        ("provider", "request"),
    ):
        value = config.get(key)
        if isinstance(value, str) and value:
            return value, reason
    instance_id, type_id, _settings = settings_manager.resolve_instance(DOMAIN)
    if isinstance(instance_id, str) and instance_id:
        return instance_id, "selection"
    if isinstance(type_id, str) and type_id:
        return type_id, "selection"
    return DOMAINS[DOMAIN].default_provider, "default"


def resolve_provider(config=None):
    """The registered provider package this request runs on.

    Raises `PROVIDER_NOT_FOUND` — which the workflow layer reports as
    `PROVIDER_UNAVAILABLE` — rather than substituting another provider:
    silently synthesizing in a voice nobody asked for is worse than failing.

    Step 3.2: the selection may be an instance id; the package is the type.
    """
    selected, reason = resolve_provider_id(config)
    stored = settings_manager.get_instance_record(DOMAIN, selected)
    if stored is not None:
        type_id = stored.get("type") if isinstance(stored.get("type"), str) else selected
    else:
        type_id = selected
    instance = hub.get(DOMAIN, type_id)
    if instance is None:
        raise ProviderError(
            PROVIDER_NOT_FOUND,
            f"No TTS provider named '{selected}' is registered",
            domain=DOMAIN,
            provider_id=selected,
        )
    return instance, reason


# ---------------------------------------------------------------------------
# Voice resolution — the generic form of the `tts_voice` / `voice` split (P5)
# ---------------------------------------------------------------------------


def declared_voice_options(instance) -> list[tuple[str, str]]:
    """`(id, label)` pairs the provider's settings schema declares (§22.4).

    Metadata only: no provider is constructed and no network call is made, so
    resolving a voice never pays for a model load.
    """
    prop = properties(instance.settings_schema()).get("voice")
    if not isinstance(prop, dict):
        return []
    options = (prop.get("ui") or {}).get("options")
    if not isinstance(options, list):
        options = prop.get("enum")
    values = []
    for option in options or ():
        if isinstance(option, dict) and "value" in option:
            values.append((str(option["value"]), str(option.get("label") or option["value"])))
        elif isinstance(option, str):
            values.append((option, option))
    return values


def declared_voices(instance) -> list[str]:
    """Just the ids of `declared_voice_options`, for input validation."""
    return [voice_id for voice_id, _label in declared_voice_options(instance)]


def default_voice(instance) -> str:
    prop = properties(instance.settings_schema()).get("voice")
    default = prop.get("default") if isinstance(prop, dict) else None
    return str(default or "")


def list_voices(instance, settings=None) -> list[dict]:
    """The provider's voice catalog as `{id, label, language, gender}`.

    Live first, declared second. One helper so `/api/tts/voices` and the
    `tts_voices` option source can never disagree about what a provider offers
    — before 15.2 the route asked one provider's API directly while the option
    source read a settings schema, and the two answered differently.

    The live hook is advisory: a provider that cannot be built or reached falls
    back to what it declares rather than to nothing.
    """
    live = []
    try:
        hook = getattr(instance.create(), "list_voices", None)
        if callable(hook):
            live = hook(
                settings if settings is not None else resolved_settings(instance)
            )
    except Exception as exc:
        # A voice list is advisory: a provider that cannot be built or reached
        # falls back to what it declares rather than to nothing.
        logger.warning("[tts] list_voices failed for {}: {}", instance.id, exc)

    voices = [
        {
            "id": voice.id,
            "label": getattr(voice, "name", "") or voice.id,
            "language": getattr(voice, "language", "") or "",
            "gender": getattr(voice, "gender", "") or "",
        }
        for voice in live or ()
        if getattr(voice, "id", "")
    ]
    return voices or [
        {"id": voice_id, "label": label, "language": "", "gender": ""}
        for voice_id, label in declared_voice_options(instance)
    ]


def resolve_voice(instance, config=None, *, settings=None) -> str:
    """The voice this provider will actually accept.

    A caller that sends both spellings gets the one that belongs to the
    resolved provider; a caller that sends a voice from *another* provider's
    catalog gets that provider's own default instead of a remote 400. When a
    provider declares no voice list, the first supplied candidate is trusted —
    a provider with an open-ended catalog must not have its input filtered.
    """
    config = dict(config or {})
    allowed = set(declared_voices(instance))
    candidates = [config.get(field) for field in VOICE_FIELDS]
    candidates.append((settings or {}).get("voice"))
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        if not allowed or candidate in allowed:
            return candidate
    return default_voice(instance)


# ---------------------------------------------------------------------------
# Settings, options, and the preview cache
# ---------------------------------------------------------------------------


def resolved_settings(instance, options=None, *, instance_id: str | None = None) -> dict:
    """Durable settings with the env fallback applied, then the per-run patch.

    `instance_id` selects which configured binding's settings to read (step 3.2);
    defaults to the package id (the default instance of the type).
    """
    key = instance_id or instance.id
    saved = settings_manager.get_instance_settings(DOMAIN, key)
    return {
        **instance.resolve_settings(saved, instance_id=key),
        **dict(options or {}),
    }


def cache_key(text: str, voice: str, speed: float, provider_id: str = "") -> str:
    """Deterministic preview-cache key.

    `provider_id` is part of the key because the same `(text, voice, speed)`
    triple renders differently per provider — before 15.2 the key had no
    provider component only because the cache was reachable from one provider's
    branch alone.
    """
    import hashlib

    raw = f"{provider_id}|{text}|{voice}|{float(speed):.2f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def cache_path(key: str) -> str:
    return os.path.join(TTS_CACHE_DIR, f"{key}.wav")


def job_dir(project_id: str) -> str:
    return os.path.join(TTS_DIR, project_id)


# ---------------------------------------------------------------------------
# One invocation
# ---------------------------------------------------------------------------


def synthesize(
    config,
    *,
    project_id,
    output_dir="",
    basename="voice",
    sidecar_name=SIDECAR_NAME,
    context=None,
    use_cache=False,
    extra_metadata=None,
):
    """Run the selected provider and return the reconciled metadata dict.

    `config` carries the historical request keys (`text`, `voice`/`tts_voice`,
    `speed`, `tts_provider_options`, plus the project fields the sidecar
    records). The returned dict is the one shape every caller sees, whichever
    provider ran: the keys `_step_timing`, `tts.json` readers, and the TTS
    history page have always read, plus `job_meta`.
    """
    package, selection_reason = resolve_provider(config)
    selected_id, _ = resolve_provider_id(config)
    stored = settings_manager.get_instance_record(DOMAIN, selected_id)
    instance_id = selected_id if stored is not None else package.id
    options = dict((config or {}).get("tts_provider_options") or {})
    settings = resolved_settings(package, options, instance_id=instance_id)
    voice = resolve_voice(package, config, settings=settings)
    text = str((config or {}).get("text") or "")
    speed = float((config or {}).get("speed") or settings.get("speed") or 1.0)

    directory = output_dir or job_dir(project_id)
    os.makedirs(directory, exist_ok=True)

    request = TTSRequest(
        text=text,
        voice=voice,
        speed=speed,
        language=str((config or {}).get("language") or ""),
        output_basename=basename,
        output_sidecar=sidecar_name,
    )

    key = cache_key(text, voice, speed, instance_id)
    cached = _cache_hit(key, directory, basename) if use_cache else None
    if cached is not None:
        return _metadata(
            wav_path=cached,
            instance=package,
            request=request,
            settings=settings,
            options=options,
            provider_metadata={},
            config=config,
            project_id=project_id,
            directory=directory,
            sidecar_name=sidecar_name,
            selection_reason=selection_reason,
            inference_time=0.0,
            cache_hit=True,
            extra_metadata=extra_metadata,
        )

    invocation = build_invocation(
        context,
        domain=DOMAIN,
        provider_id=package.id,
        project_id=project_id,
        output_dir=directory,
        settings=settings,
        options=options,
        selection_reason=selection_reason,
        provider_instance_id=instance_id,
    )
    provider = package.create(instance_id=instance_id)
    result = boundary.invoke(
        lambda inv: provider.invoke(request, inv),
        invocation,
        provider_version=instance.version,
        contract_version=instance.contract_version,
        settings_version=settings_manager.load_settings().get("version", 1),
    )

    wav_path = resolve_ref(result.payload["audio_ref"])
    if use_cache:
        _cache_store(key, wav_path)

    return _metadata(
        wav_path=wav_path,
        instance=instance,
        request=request,
        settings=settings,
        options=options,
        provider_metadata=dict(result.metadata or {}),
        payload=dict(result.payload or {}),
        provenance=result.provenance,
        config=config,
        project_id=project_id,
        directory=directory,
        sidecar_name=sidecar_name,
        selection_reason=selection_reason,
        extra_metadata=extra_metadata,
    )


def _cache_hit(key: str, directory: str, basename: str):
    """Copy a usable cached preview into place and return its path, or `None`."""
    source = cache_path(key)
    if not os.path.isfile(source):
        return None
    try:
        if sf.info(source).duration < 0.5:
            return None
    except Exception:
        logger.opt(exception=True).debug("TTS cache read failed, regenerating")
        return None
    destination = os.path.join(directory, basename + ".wav")
    shutil.copy2(source, destination)
    from scriptase.modules.tts.audio import run_loudnorm

    run_loudnorm(destination)
    logger.success("TTS cache hit ({})", key)
    return destination


def _cache_store(key: str, wav_path: str) -> None:
    try:
        os.makedirs(TTS_CACHE_DIR, exist_ok=True)
        shutil.copy2(wav_path, cache_path(key))
    except OSError:
        logger.opt(exception=True).debug("TTS cache write failed")


# ---------------------------------------------------------------------------
# The one reconciled metadata / job_meta shape
# ---------------------------------------------------------------------------


def _audio_shape(wav_path, payload) -> tuple[float, int]:
    """`(duration_seconds, sample_rate)` from the payload, else from the file."""
    duration = float(payload.get("duration_seconds") or 0.0)
    sample_rate = int(payload.get("sample_rate") or 0)
    if duration <= 0 or sample_rate <= 0:
        info = sf.info(wav_path)
        duration = duration or float(info.duration)
        sample_rate = sample_rate or int(info.samplerate)
    return round(duration, 2), sample_rate


def _metadata(
    *,
    wav_path,
    instance,
    request,
    settings,
    options,
    provider_metadata,
    config,
    project_id,
    directory,
    sidecar_name,
    selection_reason,
    payload=None,
    provenance=None,
    inference_time=None,
    cache_hit=None,
    extra_metadata=None,
):
    """Build — and persist — the single metadata shape every provider produces.

    Before 15.2 this dict was assembled once per provider branch, which is how
    `characters_billed`, `rtf`, and `model` came and went depending on which
    branch ran. There is one builder now, so a key is either always present or
    always absent, and provider-specific extras arrive through the provider's
    own result metadata rather than through a branch.
    """
    config = dict(config or {})
    payload = dict(payload or {})
    # The provider already measured what it produced (§32.3), so the file is
    # only probed on the cache path where no provider ran. Probing it always
    # would make every provider's output pass through a decoder for no reason.
    duration, sample_rate = _audio_shape(wav_path, payload)
    elapsed = float(
        inference_time
        if inference_time is not None
        else provider_metadata.get("inference_time")
        or ((provenance.duration_ms / 1000.0) if provenance is not None else 0.0)
    )
    clean_prompt = re.sub(r"[\[\]]", "", request.text).strip()
    words = len(clean_prompt.split())

    metadata = {
        "filename": os.path.basename(wav_path),
        "folder": os.path.basename(directory),
        "prompt": clean_prompt,
        # The human-readable model name is the provider's to report; the id is
        # the platform's. Both keys have existed since before the migration.
        "model": str(provider_metadata.get("model") or instance.id),
        "model_id": instance.id,
        "provider": instance.id,
        # `voice_label` is the display name a provider composes when the id is
        # not the whole story — a blend, for instance. Optional by design.
        "voice": str(
            provider_metadata.get("voice_label")
            or provider_metadata.get("voice")
            or payload.get("voice")
            or request.voice
        ),
        "project_id": project_id,
        "visual_style": config.get("visual_style"),
        "story_tone": config.get("story_tone"),
        "category": config.get("category"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "inference_time": round(elapsed, 3),
        "rtf": round(elapsed / duration, 4) if duration > 0 else 0,
        "duration_seconds": duration,
        "sample_rate": sample_rate,
        "speed": request.speed,
        "words": words,
        "approx_tokens": int(words * 1.3),
        "cache_hit": bool(
            cache_hit
            if cache_hit is not None
            else (provenance.cache_hit if provenance is not None else False)
        ),
        "characters_billed": payload.get("characters_billed"),
        "wav_path": wav_path,
    }
    # A provider's own extras (`blend`, `chunked`, `num_chunks`, …) survive
    # without this module knowing any of them.
    for key, value in provider_metadata.items():
        metadata.setdefault(key, value)
    metadata.update(dict(extra_metadata or {}))
    metadata["job_meta"] = _job_meta(
        instance,
        settings=settings,
        options=options,
        provenance=provenance,
        selection_reason=selection_reason,
    )

    if sidecar_name:
        safe_json_write(
            os.path.join(directory, sidecar_name),
            {k: v for k, v in metadata.items() if k not in _TRANSIENT_KEYS},
            indent=2,
        )
    return metadata


def _job_meta(instance, *, settings, options, provenance, selection_reason) -> dict:
    """The `job_meta` block, from the platform-authored provenance (D39).

    The seven keys `legacy._provenance_from_job_meta` reads are preserved, so a
    recorded artifact still maps back onto a `Provenance`; `invocation_id`,
    `contract_version`, and `selection_reason` are added because provenance
    carries them and the two hand-built blocks never did.
    """
    return {
        "provider_id": instance.id,
        "provider_version": instance.version,
        "provider_kind": instance.kind,
        "contract_version": instance.contract_version,
        "resolved_settings_redacted": settings_manager.redact_settings(dict(settings)),
        "provider_options": dict(options),
        "selection_reason": selection_reason,
        "invocation_id": provenance.invocation_id if provenance is not None else "",
        "resolved_at": (
            provenance.finished_at
            if provenance is not None and provenance.finished_at
            else datetime.now(timezone.utc).isoformat()
        ),
        "settings_version": (
            provenance.settings_version
            if provenance is not None
            else settings_manager.load_settings().get("version", 1)
        ),
    }


__all__ = [
    "DOMAIN",
    "SIDECAR_NAME",
    "cache_key",
    "cache_path",
    "declared_voice_options",
    "declared_voices",
    "default_voice",
    "job_dir",
    "list_voices",
    "resolve_provider",
    "resolve_provider_id",
    "resolve_voice",
    "resolved_settings",
    "synthesize",
]
