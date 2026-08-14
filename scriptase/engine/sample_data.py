"""Sample-data fixtures for stub nodes (step 2.5, contracts.md §10).

The bundled fixtures under ``scriptase/engine/fixtures/`` are the ONLY files
stub payloads may reference — never browser-supplied paths. This module:

- serves the default sample payload per dynamic port type (consumed by the
  frontend through GET /api/workflow/node-types),
- validates arbitrary user-edited ``stub.input`` payloads per port type
  (STUB_PAYLOAD_INVALID / SAMPLE_FIXTURE_MISSING), and
- validates the committed fixture set against the manifest and the
  type-specific fixture contract (exercised by pytest and the generator).

Fixtures are deterministic, sanitized, and independent of live providers;
they are regenerated with ``scriptase/engine/fixtures/generate.py``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import wave
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from .registry import DYNAMIC_PORT_TYPES

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_SCHEMA_VERSION = 1

# Canonical sample identity — matches the strict project-ID shape without
# ever colliding with a generated ``pm_`` project.
SAMPLE_PROJECT_ID = "pm_SAMPLE"
CANONICAL_AUDIO_SECONDS = 8.0

_PROJECT_ID_RE = re.compile(r"^p[pm]_[A-Za-z0-9]{6}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

# port type -> fixture file holding its payload verbatim (contracts.md §10).
_PAYLOAD_FILES = {
    "script": "script.json",
    "audio_file": "audio_file.json",
    "tts_metadata": "tts.json",
    "alignment": "alignment.json",
    "segments": "segmented.json",
    "scenes": "scenes.json",
    "image_prompts": "image_prompts.json",
    "storyboard_images": "storyboard.json",
    "animation_assets": "metadata.json",
    "captions": "captions.json",
    "music_track": "music_track.json",
    "editor_project": "initial.json",
    "project_settings": "project_settings.json",
    "video_file": "video_file.json",
}


def _problem(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _invalid(message: str) -> dict:
    return _problem("STUB_PAYLOAD_INVALID", message)


def _load_fixture_json(name: str) -> Any:
    with open(FIXTURES_DIR / name, encoding="utf-8") as handle:
        return json.load(handle)


def sample_payload(port_type: str) -> Any:
    """Default stub payload for a dynamic port type (deep copy)."""
    if port_type == "text":
        return _load_fixture_json("script.json").get("text", "")
    if port_type == "script":
        return _load_fixture_json("script.json").get("text", "")
    if port_type == "project_id":
        return SAMPLE_PROJECT_ID
    if port_type == "export_profile":
        return "yt_shorts"
    if port_type == "generic_json":
        return {"sample": True, "project_id": SAMPLE_PROJECT_ID}
    name = _PAYLOAD_FILES.get(port_type)
    if name is None:
        raise KeyError(f"No sample payload for port type: {port_type}")
    return _load_fixture_json(name)


def all_sample_payloads() -> dict:
    """Payloads for every dynamic port type, keyed by type."""
    return {port_type: sample_payload(port_type) for port_type in DYNAMIC_PORT_TYPES}


# ---------------------------------------------------------------------------
# File-reference containment: fixture-relative paths only.
# ---------------------------------------------------------------------------

def _check_ref(ref: Any, problems: list[dict], label: str) -> None:
    if not isinstance(ref, str) or not ref.strip():
        problems.append(_invalid(f"{label} must be a non-empty fixture-relative path"))
        return
    normalized = ref.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if (
        normalized.startswith("/")
        or _DRIVE_RE.match(normalized)
        or normalized.startswith("~")
        or ".." in parts
        or not parts
    ):
        problems.append(_invalid(
            f"{label} must stay inside the bundled sample fixtures (got: {ref})"
        ))
        return
    if not (FIXTURES_DIR / Path(*parts)).is_file():
        problems.append(_problem(
            "SAMPLE_FIXTURE_MISSING",
            f"{label} references a missing sample fixture: {ref}",
        ))


def _check_artifact_refs(payload: dict, problems: list[dict]) -> None:
    refs = payload.get("artifact_refs")
    if refs is None:
        return
    if not isinstance(refs, list):
        problems.append(_invalid("artifact_refs must be a list of fixture-relative paths"))
        return
    for index, ref in enumerate(refs):
        _check_ref(ref, problems, f"artifact_refs[{index}]")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require_object(payload: Any, problems: list[dict], type_name: str) -> bool:
    if not isinstance(payload, dict):
        problems.append(_invalid(f"A {type_name} payload must be a JSON object"))
        return False
    return True


# ---------------------------------------------------------------------------
# Per-port-type structural validators (mirrored client-side in
# frontend/src/features/workflow/stubPayloads.js).
# ---------------------------------------------------------------------------

def _validate_string(payload, problems, *, label, max_length=10000):
    if not isinstance(payload, str) or not payload.strip():
        problems.append(_invalid(f"A {label} payload must be a non-empty string"))
    elif len(payload) > max_length:
        problems.append(_invalid(f"A {label} payload must stay under {max_length} characters"))


def _validate_project_id(payload, problems):
    if not isinstance(payload, str) or not _PROJECT_ID_RE.fullmatch(payload):
        problems.append(_invalid("A project_id payload must match pp_XXXXXX or pm_XXXXXX"))


def _validate_audio_file(payload, problems):
    if not _require_object(payload, problems, "audio_file"):
        return
    _check_ref(payload.get("wav_path"), problems, "wav_path")
    if not _finite(payload.get("duration_seconds")) or payload.get("duration_seconds") <= 0:
        problems.append(_invalid("duration_seconds must be a positive number"))


def _validate_tts_metadata(payload, problems):
    if not _require_object(payload, problems, "tts_metadata"):
        return
    for key in ("folder", "filename"):
        if not isinstance(payload.get(key), str) or not payload.get(key):
            problems.append(_invalid(f"{key} must be a non-empty string"))
    _check_ref(payload.get("wav_path"), problems, "wav_path")
    if not _finite(payload.get("duration_seconds")) or payload.get("duration_seconds") <= 0:
        problems.append(_invalid("duration_seconds must be a positive number"))
    words = payload.get("words")
    if not isinstance(words, int) or isinstance(words, bool) or words <= 0:
        problems.append(_invalid("words must be a positive integer"))


def _validate_alignment(payload, problems):
    if not _require_object(payload, problems, "alignment"):
        return
    if not isinstance(payload.get("transcript"), str) or not payload.get("transcript").strip():
        problems.append(_invalid("transcript must be a non-empty string"))
    words = payload.get("alignment")
    if not isinstance(words, list) or not words:
        problems.append(_invalid("alignment must be a non-empty list of timed words"))
        return
    previous_begin = -math.inf
    for index, word in enumerate(words):
        if not isinstance(word, dict) or not isinstance(word.get("word"), str):
            problems.append(_invalid(f"alignment[{index}] must be {{word, begin, end}}"))
            return
        begin, end = word.get("begin"), word.get("end")
        if not _finite(begin) or not _finite(end) or begin < 0 or end < begin:
            problems.append(_invalid(f"alignment[{index}] has invalid word timings"))
            return
        if begin < previous_begin:
            problems.append(_invalid("alignment words must be ordered by start time"))
            return
        previous_begin = begin


def _validate_segments(payload, problems):
    if not _require_object(payload, problems, "segments"):
        return
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        problems.append(_invalid("segments must be a non-empty list"))
        return
    previous_end = -math.inf
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            problems.append(_invalid(f"segments[{index}] must be an object"))
            return
        start, end = segment.get("start"), segment.get("end")
        if not _finite(start) or not _finite(end) or start < 0 or end < start:
            problems.append(_invalid(f"segments[{index}] has invalid start/end times"))
            return
        if start < previous_end - 1e-6:
            problems.append(_invalid("segments must be ordered and non-overlapping"))
            return
        if not isinstance(segment.get("words"), str):
            problems.append(_invalid(f"segments[{index}].words must be a string"))
            return
        previous_end = end


def _validate_scenes(payload, problems):
    if not _require_object(payload, problems, "scenes"):
        return
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        problems.append(_invalid("scenes must be a non-empty list"))
        return
    seen: set[int] = set()
    for position, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            problems.append(_invalid(f"scenes[{position}] must be an object"))
            return
        index = scene.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index in seen:
            problems.append(_invalid("every scene needs a stable unique integer index"))
            return
        seen.add(index)
        prompt = scene.get("image_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            problems.append(_invalid(f"scenes[{position}].image_prompt must be a non-empty string"))
            return


def _validate_image_prompts(payload, problems):
    if not _require_object(payload, problems, "image_prompts"):
        return
    prompts = payload.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        problems.append(_invalid("prompts must be a non-empty list"))
        return
    for position, item in enumerate(prompts):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("index"), int)
            or isinstance(item.get("index"), bool)
            or not isinstance(item.get("image_prompt"), str)
            or not item["image_prompt"].strip()
        ):
            problems.append(_invalid(f"prompts[{position}] must be {{index, image_prompt}}"))
            return


def _counts(payload, problems, type_name):
    values = []
    for key in ("total", "ready", "errors"):
        value = payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            problems.append(_invalid(f"{type_name}.{key} must be a non-negative integer"))
            return None
        values.append(value)
    total, ready, errors = values
    if ready + errors > total:
        problems.append(_invalid(f"{type_name} ready+errors cannot exceed total"))
        return None
    return total, ready, errors


def _validate_storyboard_images(payload, problems):
    if not _require_object(payload, problems, "storyboard_images"):
        return
    counts = _counts(payload, problems, "storyboard_images")
    statuses = payload.get("scene_statuses")
    if not isinstance(statuses, dict):
        problems.append(_invalid("scene_statuses must be an object keyed by scene"))
        return
    ready_seen = 0
    error_seen = 0
    for key, status in statuses.items():
        if not isinstance(status, dict) or not isinstance(status.get("status"), str):
            problems.append(_invalid(f"scene_statuses[{key}] must carry a status string"))
            return
        if status["status"] == "ready":
            ready_seen += 1
            if "local_path" in status:
                _check_ref(status.get("local_path"), problems, f"scene_statuses[{key}].local_path")
        elif status["status"] == "error":
            error_seen += 1
    if counts is not None:
        total, ready, errors = counts
        if len(statuses) != total or ready_seen != ready or error_seen != errors:
            problems.append(_invalid("storyboard counts must match the listed scene statuses"))


def _validate_animation_assets(payload, problems):
    if not _require_object(payload, problems, "animation_assets"):
        return
    counts = _counts(payload, problems, "animation_assets")
    scenes = payload.get("scenes")
    if not isinstance(scenes, dict) or not scenes:
        problems.append(_invalid("scenes must be a non-empty object keyed by scene"))
        return
    ready_seen = 0
    for key, scene in scenes.items():
        if not isinstance(scene, dict) or not isinstance(scene.get("local_files"), list):
            problems.append(_invalid(f"scenes[{key}] must carry a local_files list"))
            return
        if scene["local_files"]:
            ready_seen += 1
        for index, ref in enumerate(scene["local_files"]):
            _check_ref(ref, problems, f"scenes[{key}].local_files[{index}]")
    if counts is not None:
        total, ready, _errors = counts
        if len(scenes) != total or ready_seen != ready:
            problems.append(_invalid("animation asset counts must match the listed scenes"))


def _validate_captions(payload, problems):
    if not _require_object(payload, problems, "captions"):
        return
    captions = payload.get("captions")
    if not isinstance(captions, list) or not captions:
        problems.append(_invalid("captions must be a non-empty list"))
        return
    previous_start = -math.inf
    for index, caption in enumerate(captions):
        if not isinstance(caption, dict) or not isinstance(caption.get("text"), str):
            problems.append(_invalid(f"captions[{index}] must carry a text string"))
            return
        start, end = caption.get("start"), caption.get("end")
        if not _finite(start) or not _finite(end) or start < 0 or end < start:
            problems.append(_invalid(f"captions[{index}] has invalid timings"))
            return
        if start < previous_start:
            problems.append(_invalid("captions must be ordered by start time"))
            return
        previous_start = start


def _validate_music_track(payload, problems):
    if not _require_object(payload, problems, "music_track"):
        return
    _check_ref(payload.get("track_ref"), problems, "track_ref")
    volume = payload.get("volume")
    if not _finite(volume) or not 0 <= volume <= 1:
        problems.append(_invalid("volume must be a number between 0 and 1"))


def _validate_editor_project(payload, problems):
    if not _require_object(payload, problems, "editor_project"):
        return
    if not isinstance(payload.get("project_id"), str) or not payload.get("project_id"):
        problems.append(_invalid("project_id must be a non-empty string"))
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        problems.append(_invalid("scenes must be a non-empty list"))
        return
    if payload.get("scene_count") != len(scenes):
        problems.append(_invalid("scene_count must match the scenes list"))
    if not _finite(payload.get("total_duration")) or payload.get("total_duration") <= 0:
        problems.append(_invalid("total_duration must be a positive number"))
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            problems.append(_invalid(f"scenes[{index}] must be an object"))
            return
        if scene.get("mediaUrl"):
            _check_ref(scene.get("mediaUrl"), problems, f"scenes[{index}].mediaUrl")
    for index, track in enumerate(payload.get("audio_tracks") or []):
        if isinstance(track, dict) and track.get("path"):
            _check_ref(track.get("path"), problems, f"audio_tracks[{index}].path")


def _validate_project_settings(payload, problems):
    if not _require_object(payload, problems, "project_settings"):
        return
    logo = payload.get("logo")
    if logo is not None:
        if not isinstance(logo, dict):
            problems.append(_invalid("logo must be an object reference"))
        elif logo.get("path"):
            _check_ref(logo.get("path"), problems, "logo.path")


def _validate_video_file(payload, problems):
    if not _require_object(payload, problems, "video_file"):
        return
    _check_ref(payload.get("path"), problems, "path")


def _validate_generic_json(payload, problems):
    if payload is None:
        problems.append(_invalid("A generic_json payload cannot be null"))


_VALIDATORS = {
    "text": lambda payload, problems: _validate_string(payload, problems, label="text"),
    "script": lambda payload, problems: _validate_string(payload, problems, label="script"),
    "project_id": _validate_project_id,
    "project_settings": _validate_project_settings,
    "audio_file": _validate_audio_file,
    "tts_metadata": _validate_tts_metadata,
    "alignment": _validate_alignment,
    "segments": _validate_segments,
    "scenes": _validate_scenes,
    "image_prompts": _validate_image_prompts,
    "storyboard_images": _validate_storyboard_images,
    "animation_assets": _validate_animation_assets,
    "captions": _validate_captions,
    "music_track": _validate_music_track,
    "editor_project": _validate_editor_project,
    "export_profile": lambda payload, problems: _validate_string(
        payload, problems, label="export_profile", max_length=80),
    "video_file": _validate_video_file,
    "generic_json": _validate_generic_json,
}


def validate_stub_payload(port_type: str, payload: Any) -> list[dict]:
    """Structured problems for a user-edited stub.input payload.

    Returns ``[{code, message}]`` with codes STUB_PAYLOAD_INVALID or
    SAMPLE_FIXTURE_MISSING; empty list means the payload is acceptable.
    """
    validator = _VALIDATORS.get(port_type)
    if validator is None:
        return [_invalid(f"Unsupported sample data type: {port_type}")]
    problems: list[dict] = []
    validator(payload, problems)
    if isinstance(payload, dict):
        _check_artifact_refs(payload, problems)
    return problems


# ---------------------------------------------------------------------------
# Fixture-set validation (manifest + cross-file contract, contracts.md §10).
# ---------------------------------------------------------------------------

def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
    if rate <= 0 or frames <= 0:
        raise ValueError(f"{path.name} is not a playable WAV file")
    return frames / rate


def validate_fixtures() -> list[str]:
    """Validate the committed fixture set. Empty list == frozen contract holds."""
    problems: list[str] = []
    if not FIXTURES_DIR.is_dir():
        return ["scriptase/engine/fixtures/ does not exist — run fixtures/generate.py"]
    manifest_path = FIXTURES_DIR / "manifest.json"
    if not manifest_path.is_file():
        return ["fixtures/manifest.json is missing — run fixtures/generate.py"]
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("fixture_schema_version") != FIXTURE_SCHEMA_VERSION:
        problems.append("manifest fixture_schema_version mismatch")

    listed = manifest.get("files") or {}
    on_disk = {
        path.relative_to(FIXTURES_DIR).as_posix()
        for path in FIXTURES_DIR.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "generate.py"}
        and "__pycache__" not in path.parts
    }
    for missing in sorted(set(listed) - on_disk):
        problems.append(f"manifest lists a missing fixture: {missing}")
    for unlisted in sorted(on_disk - set(listed)):
        problems.append(f"fixture file not recorded in the manifest: {unlisted}")

    for relpath, entry in sorted(listed.items()):
        path = FIXTURES_DIR / relpath
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) != entry.get("bytes"):
            problems.append(f"{relpath}: byte size differs from the manifest")
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{relpath}: SHA-256 differs from the manifest")

    if problems:
        return problems

    # Every dynamic port type must have a sample payload that passes its own
    # stub-payload validation (including fixture-ref containment/existence).
    for port_type in DYNAMIC_PORT_TYPES:
        try:
            payload = sample_payload(port_type)
        except (KeyError, OSError, json.JSONDecodeError) as exc:
            problems.append(f"{port_type}: sample payload unavailable ({exc})")
            continue
        for item in validate_stub_payload(port_type, payload):
            problems.append(f"{port_type}: {item['message']}")

    if problems:
        return problems

    # Cross-file coherence against the canonical audio.
    script_text = _load_fixture_json("script.json").get("text", "")
    if not script_text or len(script_text) > 10000:
        problems.append("script.json text must be non-empty and bounded")

    duration = _wav_duration(FIXTURES_DIR / "media" / "voice.wav")
    tts = _load_fixture_json("tts.json")
    if abs(duration - CANONICAL_AUDIO_SECONDS) > 0.05:
        problems.append(f"voice.wav duration {duration:.2f}s != canonical {CANONICAL_AUDIO_SECONDS}s")
    if abs(tts.get("duration_seconds", 0) - duration) > 0.05:
        problems.append("tts.json duration_seconds disagrees with voice.wav")

    alignment = _load_fixture_json("alignment.json")
    words = alignment.get("alignment") or []
    if alignment.get("transcript") != script_text:
        problems.append("alignment transcript differs from the canonical script")
    if words and words[-1]["end"] > duration + 1e-6:
        problems.append("alignment words exceed the canonical audio duration")

    segmented = _load_fixture_json("segmented.json")
    segments = segmented.get("segments") or []
    if segmented.get("metadata", {}).get("transcript") != script_text:
        problems.append("segmented transcript differs from the canonical script")
    if segments and segments[-1]["end"] > duration + 1e-6:
        problems.append("segments exceed the canonical audio duration")
    non_filler = [seg for seg in segments if not seg.get("is_filler")]

    scenes = _load_fixture_json("scenes.json").get("scenes") or []
    if len(scenes) != len(non_filler):
        problems.append("scenes must map 1:1 onto non-filler segments")
    if [scene.get("index") for scene in scenes] != list(range(len(scenes))):
        problems.append("scene indices must be stable and sequential")

    captions = _load_fixture_json("captions.json").get("captions") or []
    if captions and captions[-1]["end"] > duration + 1e-6:
        problems.append("captions exceed the canonical audio duration")

    project = _load_fixture_json("initial.json")
    if abs(project.get("total_duration", 0) - duration) > 0.05:
        problems.append("initial.json total_duration disagrees with voice.wav")

    music = _load_fixture_json("music_track.json")
    music_duration = _wav_duration(FIXTURES_DIR / "media" / "music.wav")
    if abs(music.get("duration_seconds", 0) - music_duration) > 0.05:
        problems.append("music_track duration_seconds disagrees with music.wav")

    return problems


def fixture_manifest() -> dict:
    return deepcopy(_load_fixture_json("manifest.json"))
