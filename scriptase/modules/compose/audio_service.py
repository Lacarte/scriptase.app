"""SFX placement and audio-track assembly.

Moved verbatim out of V2 ``studio/editor/routes.py`` in step 0.3.
Service layer: no Flask import belongs in this module.
"""

import json
import os

from loguru import logger

from config import APP_ASSETS_DIR
from scriptase.shared.io_utils import safe_json_read
from scriptase.modules.compose.project_service import (
    _append_audio_history,
    _initial_path,
    _normalize_audio_history,
)


def _list_sfx_files_in_folder(folder: str) -> list[str]:
    """List all audio files in resources/sounds/sfx/<folder>/. Returns absolute paths."""
    sfx_dir = os.path.join(APP_ASSETS_DIR, "sounds", "sfx", folder)
    if not os.path.isdir(sfx_dir):
        return []
    audio_exts = (".mp3", ".wav", ".ogg", ".m4a", ".flac")
    return [
        os.path.join(sfx_dir, f)
        for f in sorted(os.listdir(sfx_dir))
        if f.lower().endswith(audio_exts)
        and os.path.isfile(os.path.join(sfx_dir, f))
    ]


def _pick_sfx_file_for_hint(entry: dict, history: list[str]) -> str | None:
    """Pick a real file matching a vocabulary entry, with history-deduped randomization.

    Looks at `folder` first, narrowed by `filename_match` regex if present.
    Falls back to `fallback_folder` (also narrowed by the same regex) if the
    primary folder produces nothing.

    Returns the absolute file path, or None if no candidates exist.
    """
    import random
    import re

    folder = entry.get("folder")
    if not folder:
        return None  # silence hint or unmapped entry

    pattern = entry.get("filename_match")
    regex = re.compile(pattern, re.IGNORECASE) if pattern else None

    def _candidates(in_folder: str) -> list[str]:
        all_files = _list_sfx_files_in_folder(in_folder)
        if not regex:
            return all_files
        return [p for p in all_files if regex.search(os.path.basename(p))]

    candidates = _candidates(folder)
    if not candidates:
        fallback = entry.get("fallback_folder")
        if fallback:
            candidates = _candidates(fallback)

    if not candidates:
        return None

    # Prefer files NOT in recent history
    fresh = [p for p in candidates if p not in history]
    pool = fresh if fresh else candidates
    return random.choice(pool)


def _build_per_scene_sfx_tracks(
    editor_scenes: list[dict],
    raw_scenes: list[dict],
    sfx_history: list[str],
) -> tuple[list[dict], list[str]]:
    """Build per-scene SFX tracks from validated sfx_hint fields.

    For each scene that carries a non-null `sfx_hint`, look up the vocabulary
    entry, pick a real file, compute the timeline offset based on the entry's
    placement mode, and produce an audio_tracks-shaped dict.

    Returns (tracks_to_append, updated_sfx_history). The history is grown by
    each successful pick so the next pick within the same project doesn't
    re-roll the same file.

    Placement modes:
      - scene_start    : timelineOffset = scene start time (one-shot, fires on cut into scene)
      - scene_duration : timelineOffset = scene start, trimmedDuration = scene length (looped texture)
      - lead_in        : timelineOffset = scene start - lead_in_seconds (one-shot fires before cut)

    Skipped silently when:
      - sfx_hint is null/empty
      - hint key is not in the loaded vocabulary
      - the entry's folder (and fallback) contain no matching files
      - the hint is `silence` (intentional no-op — the bed track will be ducked)
    """
    from scriptase.modules.scene_director.sfx_validator import load_sfx_vocabulary

    vocab = load_sfx_vocabulary()
    hints_by_id = vocab.get("hints") or {}
    if not hints_by_id:
        return [], sfx_history

    history = list(sfx_history or [])
    tracks: list[dict] = []
    seq = 0  # for unique track ids

    # Build a fast index from scene index/id to its computed timestamp + duration.
    # editor_scenes already has timestamps computed at the cumulative-position step.
    scene_by_id = {es["id"]: es for es in editor_scenes}

    for raw in raw_scenes:
        # Try several keys to find the matching editor scene — raw scenes
        # use `index`, editor scenes use `id` (which is the array position).
        # The assemble loop builds editor_scenes in raw_scenes order, so the
        # raw_scenes index in the loop is the editor scene id.
        try:
            raw_index = int(raw.get("index", -1))
        except (TypeError, ValueError):
            raw_index = -1

        # The editor scene id is the array position from the assemble loop.
        # raw_scenes and editor_scenes are 1:1 ordered, so we use the loop
        # position. But we don't have the loop position here — instead use
        # the raw_index which is what was set as `id` in the loop above.
        # Defensively, fall back to scanning by raw index.
        editor_scene = scene_by_id.get(raw_index)
        if editor_scene is None:
            continue

        hint_id = raw.get("sfx_hint")
        if not hint_id:
            continue

        entry = hints_by_id.get(hint_id)
        if not entry:
            continue  # validator should have caught this, defense in depth

        if hint_id == "silence":
            # Explicit no-op. The audio bed will keep playing — silence is a
            # creative choice to NOT add an accent here, not a request to
            # mute the existing layers.
            continue

        chosen_path = _pick_sfx_file_for_hint(entry, history)
        if not chosen_path:
            logger.debug("SFX hint '{}' has no available files (folder={}, fallback={})",
                         hint_id, entry.get("folder"), entry.get("fallback_folder"))
            continue

        history.append(chosen_path)

        # Compute timeline offset based on placement mode
        scene_start = float(editor_scene.get("timestamp", 0) or 0)
        scene_duration = float(editor_scene.get("duration", 0) or 0)
        placement = entry.get("placement", "scene_start")

        if placement == "lead_in":
            lead = float(entry.get("lead_in_seconds", 0.5) or 0.5)
            timeline_offset = max(0.0, scene_start - lead)
            trimmed_duration = None
        elif placement == "scene_duration":
            timeline_offset = scene_start
            trimmed_duration = scene_duration
        else:  # scene_start (default)
            timeline_offset = scene_start
            trimmed_duration = None

        # Build the asset URL the editor's audio system uses.
        # Files live under resources/sounds/sfx/<folder>/<file>; the editor
        # serves them via /assets/sounds/sfx/<folder>/<file>.
        sfx_file = os.path.basename(chosen_path)
        sfx_folder = os.path.basename(os.path.dirname(chosen_path))
        sfx_url = f"/assets/sounds/sfx/{sfx_folder}/{sfx_file}"

        seq += 1
        tracks.append({
            "id": f"at_sfx_scene{raw_index}_{hint_id}_{seq}",
            "label": entry.get("label", hint_id.upper()),
            "type": "sfx",
            "file": sfx_file,
            "path": sfx_url,
            "duration": 0,
            "timelineOffset": round(timeline_offset, 3),
            "startOffset": 0,
            "trimmedDuration": round(trimmed_duration, 3) if trimmed_duration is not None else None,
            "volume": float(entry.get("volume", 0.15)),
            "loop": bool(entry.get("loop", False)),
            "muted": False,
            "duckingEnabled": True,
            "duckingLevel": 0.20,
            "fadeIn": float(entry.get("fade_in", 0.0)),
            "fadeOut": float(entry.get("fade_out", 0.3)),
            # Provenance — useful for debugging when a hint fires the wrong file
            "sfx_hint": hint_id,
            "scene_index": raw_index,
        })

        logger.info("Per-scene SFX: scene {} -> {} ({}) @ {:.2f}s [{}]",
                    raw_index, hint_id, sfx_file, timeline_offset, placement)

    return tracks, history


def _builtin_audio_url_to_abs(track_type: str, path: str | None) -> str | None:
    """Convert a built-in /assets/sounds/{music|sfx}/... URL back to an absolute path."""
    if not isinstance(path, str) or not path.strip():
        return None
    bucket = "music" if track_type == "music" else "sfx" if track_type == "sfx" else ""
    if not bucket:
        return None
    prefix = f"/assets/sounds/{bucket}/"
    if not path.startswith(prefix):
        return None
    rel = path[len("/assets/"):].replace("/", os.sep)
    return os.path.join(APP_ASSETS_DIR, rel)


def _builtin_audio_abs_to_url(track_type: str, abs_path: str | None) -> str | None:
    """Convert a built-in music/SFX absolute path to the matching /assets/... URL."""
    if not isinstance(abs_path, str) or not abs_path.strip():
        return None
    normalized = os.path.abspath(abs_path)
    try:
        if os.path.commonpath([os.path.abspath(APP_ASSETS_DIR), normalized]) != os.path.abspath(APP_ASSETS_DIR):
            return None
    except ValueError:
        return None
    bucket = "music" if track_type == "music" else "sfx" if track_type == "sfx" else ""
    if not bucket:
        return None
    expected_root = os.path.join(APP_ASSETS_DIR, "sounds", bucket)
    try:
        if os.path.commonpath([os.path.abspath(expected_root), normalized]) != os.path.abspath(expected_root):
            return None
    except ValueError:
        return None
    rel = os.path.relpath(normalized, APP_ASSETS_DIR).replace("\\", "/")
    return f"/assets/{rel}"


def _materialize_history_audio_tracks(data: dict) -> None:
    """Backfill missing music/SFX tracks from persisted history for older projects."""
    if not isinstance(data, dict):
        return

    tracks = data.get("audio_tracks")
    if not isinstance(tracks, list):
        tracks = []
        data["audio_tracks"] = tracks

    existing_types = {
        str(track.get("type") or "").lower()
        for track in tracks
        if isinstance(track, dict)
    }
    music_history = _normalize_audio_history(data.get("music_history"))
    sfx_history = _normalize_audio_history(data.get("sfx_history"))

    from scriptase.modules.music.selector import recall_last_music, recall_last_sfx

    if "music" not in existing_types:
        restored_music = recall_last_music(music_history)
        if restored_music:
            music_url = _builtin_audio_abs_to_url("music", restored_music.get("path"))
            music_path = restored_music.get("path") or ""
            if music_url and music_path:
                tracks.append({
                    "id": "at_music_history",
                    "label": "Music",
                    "type": "music",
                    "file": os.path.basename(music_path),
                    "path": music_url,
                    "duration": 0,
                    "timelineOffset": 0,
                    "startOffset": 0,
                    "trimmedDuration": None,
                    "volume": restored_music.get("volume", 0.15),
                    "loop": restored_music.get("loop", True),
                    "muted": False,
                    "duckingEnabled": restored_music.get("ducking_enabled", True),
                    "duckingLevel": restored_music.get("ducking_level", 0.20),
                    "fadeIn": restored_music.get("fade_in", 2.0),
                    "fadeOut": restored_music.get("fade_out", 3.0),
                })
                existing_types.add("music")

    if "sfx" not in existing_types:
        restored_sfx = recall_last_sfx(sfx_history)
        if restored_sfx:
            sfx_url = _builtin_audio_abs_to_url("sfx", restored_sfx.get("path"))
            sfx_path = restored_sfx.get("path") or ""
            if sfx_url and sfx_path:
                tracks.append({
                    "id": "at_sfx_history",
                    "label": "SFX",
                    "type": "sfx",
                    "file": os.path.basename(sfx_path),
                    "path": sfx_url,
                    "duration": 0,
                    "timelineOffset": 0,
                    "startOffset": 0,
                    "trimmedDuration": None,
                    "volume": restored_sfx.get("volume", 0.10),
                    "loop": restored_sfx.get("loop", True),
                    "muted": False,
                    "duckingEnabled": restored_sfx.get("ducking_enabled", True),
                    "duckingLevel": restored_sfx.get("ducking_level", 0.20),
                    "fadeIn": restored_sfx.get("fade_in", 1.5),
                    "fadeOut": restored_sfx.get("fade_out", 2.0),
                })


def _merge_project_audio_history(save_data: dict, project_id: str):
    """Keep initial/WIP payloads in sync with current music/SFX history."""
    initial = _initial_path(project_id)
    existing_initial = {}
    if os.path.isfile(initial):
        try:
            existing_initial = safe_json_read(initial)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            logger.debug("Could not read existing initial.json for {}: {}", project_id, e)
            existing_initial = {}
    if not isinstance(existing_initial, dict):
        existing_initial = {}

    music_history = _normalize_audio_history(
        save_data.get("music_history") if "music_history" in save_data else existing_initial.get("music_history")
    )
    sfx_history = _normalize_audio_history(
        save_data.get("sfx_history") if "sfx_history" in save_data else existing_initial.get("sfx_history")
    )

    for track in save_data.get("audio_tracks", []):
        if not isinstance(track, dict):
            continue
        track_type = str(track.get("type") or "").lower()
        abs_path = _builtin_audio_url_to_abs(track_type, track.get("path"))
        if track_type == "music":
            music_history = _append_audio_history(music_history, abs_path)
        elif track_type == "sfx":
            sfx_history = _append_audio_history(sfx_history, abs_path)

    save_data["music_history"] = music_history
    save_data["sfx_history"] = sfx_history
