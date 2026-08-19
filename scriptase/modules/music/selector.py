"""Auto-select background music and SFX based on story tone."""

import json
import os
import random

from loguru import logger

from config import APP_ASSETS_DIR, MUSIC_DIR, PROJECTS_DIR
from scriptase.shared.io_utils import safe_json_read, safe_json_write

_MUSIC_ROOT = os.path.join(APP_ASSETS_DIR, "sounds", "music")
# V2 import location: tracks land here flat, not organised by tone.
_MUSIC_IMPORT_ROOT = MUSIC_DIR
_SFX_ROOT = os.path.join(APP_ASSETS_DIR, "sounds", "sfx")
_INITIAL_FILENAME = "initial.json"
_HISTORY_LIMIT = 10

_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}

# story_tone -> ordered list of music sub-folders (primary first, fallbacks after)
TONE_MUSIC_MAP = {
    "suspenseful": ["dark", "psychology", "sad", "cinematic", "ambient", "chill"],
    "dramatic": ["cinematic", "dark", "sad", "historic", "philosophy", "ambient"],
    "religious": ["religion", "philosophy", "cinematic", "sad", "ambient", "dark"],
    "educational": ["philosophy", "psychology", "ambient", "historic", "chill", "cinematic"],
    "inspirational": ["joy", "cinematic", "chill", "ambient", "romantic"],
    "comedic": ["joy", "chill", "ambient", "romantic"],
    "wholesome": ["romantic", "joy", "chill", "ambient"],
}

# story_tone -> ordered list of SFX sub-folders to draw a single ambience-style
# sound from. The pick is layered onto the timeline as a low-volume looping
# accent (rain for suspense, ambient pad for educational, etc.).
TONE_SFX_MAP = {
    "suspenseful": ["heartbeat", "clock", "ambient", "viscous"],
    "dramatic": ["bass-drops", "cinematic", "ambient"],
    "religious": ["ambient", "magic"],
    "educational": ["ambient", "thinking", "clicks"],
    "inspirational": ["ambient", "whoosh", "magic"],
    "comedic": ["cartoon", "notification", "clicks"],
    "wholesome": ["ambient", "magic", "notification"],
}


def _list_tracks(folder):
    """Return audio file paths in a folder."""
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if os.path.splitext(name)[1].lower() in _AUDIO_EXTS
        and os.path.isfile(os.path.join(folder, name))
    ]


def _normalize_history(history):
    """Normalize history payloads to the expected bounded list."""
    if not isinstance(history, list):
        return []
    return list(history)[-_HISTORY_LIMIT:]


def _project_initial_path(project_id):
    """Return output/projects/{project_id}/initial.json for a safe id."""
    safe_id = "".join(c for c in str(project_id or "") if c.isalnum() or c in ("_", "-"))
    if not safe_id:
        return ""
    return os.path.join(PROJECTS_DIR, safe_id, _INITIAL_FILENAME)


def load_project_audio_history(project_id):
    """Load persisted music/SFX history arrays from a project's initial.json."""
    path = _project_initial_path(project_id)
    if not path or not os.path.isfile(path):
        return {"music_history": [], "sfx_history": []}
    try:
        data = safe_json_read(path)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.debug("Could not read audio history from {}: {}", path, exc)
        return {"music_history": [], "sfx_history": []}
    if not isinstance(data, dict):
        return {"music_history": [], "sfx_history": []}
    return {
        "music_history": _normalize_history(data.get("music_history")),
        "sfx_history": _normalize_history(data.get("sfx_history")),
    }


def persist_project_audio_history(project_id, *, music_history=None, sfx_history=None):
    """Persist history arrays into an existing project's initial.json."""
    path = _project_initial_path(project_id)
    if not path or not os.path.isfile(path):
        return False
    try:
        data = safe_json_read(path)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.debug("Could not load {} before persisting history: {}", path, exc)
        data = {}
    if not isinstance(data, dict):
        data = {}
    if music_history is not None:
        data["music_history"] = _normalize_history(music_history)
    if sfx_history is not None:
        data["sfx_history"] = _normalize_history(sfx_history)
    try:
        safe_json_write(path, data, indent=2)
        return True
    except OSError as exc:
        logger.debug("Could not persist audio history into {}: {}", path, exc)
        return False


def _pick_with_history(tracks, history):
    """Pick a random track preferring those not in recent history."""
    if not tracks:
        return None
    fresh = [track for track in tracks if track not in history]
    if fresh:
        return random.choice(fresh)
    return random.choice(tracks)


def _last_valid_history_track(history, root):
    """Return the newest valid history path that still exists under the given root."""
    root_abs = os.path.abspath(root)
    for candidate in reversed(_normalize_history(history)):
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        candidate_abs = os.path.abspath(candidate)
        try:
            if os.path.commonpath([root_abs, candidate_abs]) != root_abs:
                continue
        except ValueError:
            continue
        if not os.path.isfile(candidate_abs):
            continue
        if os.path.splitext(candidate_abs)[1].lower() not in _AUDIO_EXTS:
            continue
        return candidate_abs
    return None


def select_music(story_tone, history=None):
    """Pick a random music track matching the story tone.

    Searches tone-organised folders under the built-in library first.  When
    none of them contain tracks the V2 import location (``output/musics/``) is
    checked as a flat fallback — the import puts every bed there regardless of
    tone.
    """
    folders = TONE_MUSIC_MAP.get(story_tone)
    if not folders:
        logger.debug("No music mapping for story_tone '{}', skipping auto-music", story_tone)
        return None

    history = _normalize_history(history)

    for folder_name in folders:
        tracks = _list_tracks(os.path.join(_MUSIC_ROOT, folder_name))
        if not tracks:
            continue
        chosen = _pick_with_history(tracks, history)
        if not chosen:
            continue
        next_history = _normalize_history(history + [chosen])
        logger.info(
            "Auto-music: tone='{}' -> folder='{}' -> '{}'",
            story_tone,
            folder_name,
            os.path.basename(chosen),
        )
        return {
            "path": chosen,
            "history": next_history,
            "volume": 0.15,
            "fade_in": 2.0,
            "fade_out": 3.0,
            "loop": True,
            "ducking_enabled": True,
            "ducking_level": 0.20,
        }

    # Fallback: the V2 import stores tracks flat in output/musics/ without
    # tone sub-folders.  Pick any track from there rather than failing.
    import_tracks = _list_tracks(_MUSIC_IMPORT_ROOT)
    if import_tracks:
        chosen = _pick_with_history(import_tracks, history)
        if chosen:
            next_history = _normalize_history(history + [chosen])
            logger.info(
                "Auto-music: tone='{}' -> import fallback -> '{}'",
                story_tone,
                os.path.basename(chosen),
            )
            return {
                "path": chosen,
                "history": next_history,
                "volume": 0.15,
                "fade_in": 2.0,
                "fade_out": 3.0,
                "loop": True,
                "ducking_enabled": True,
                "ducking_level": 0.20,
            }

    logger.warning("Auto-music: no tracks found for tone '{}' in folders {}", story_tone, folders)
    return None


def recall_last_music(history=None):
    """Reuse the most recent valid built-in music file from history, if available."""
    chosen = _last_valid_history_track(history, _MUSIC_ROOT)
    if not chosen:
        return None
    logger.info("Auto-music: reusing history pick '{}'", os.path.basename(chosen))
    return {
        "path": chosen,
        "volume": 0.15,
        "fade_in": 2.0,
        "fade_out": 3.0,
        "loop": True,
        "ducking_enabled": True,
        "ducking_level": 0.20,
    }


def select_random_music(history=None):
    """Pick a random track from any folder under the built-in music library."""
    if not os.path.isdir(_MUSIC_ROOT):
        return None

    all_tracks = []
    for entry in os.listdir(_MUSIC_ROOT):
        folder = os.path.join(_MUSIC_ROOT, entry)
        if not os.path.isdir(folder):
            continue
        all_tracks.extend(_list_tracks(folder))

    if not all_tracks:
        logger.warning("Auto-music: no tracks found in {}", _MUSIC_ROOT)
        return None

    history = _normalize_history(history)
    chosen = _pick_with_history(all_tracks, history)
    if not chosen:
        return None
    next_history = _normalize_history(history + [chosen])
    logger.info("Auto-music: random pick -> '{}'", os.path.basename(chosen))
    return {
        "path": chosen,
        "history": next_history,
        "volume": 0.15,
        "fade_in": 2.0,
        "fade_out": 3.0,
        "loop": True,
        "ducking_enabled": True,
        "ducking_level": 0.20,
    }


def select_sfx(story_tone, history=None):
    """Pick a random SFX track matching the story tone."""
    folders = TONE_SFX_MAP.get(story_tone)
    if not folders:
        logger.debug("No SFX mapping for story_tone '{}', skipping auto-sfx", story_tone)
        return None

    history = _normalize_history(history)

    for folder_name in folders:
        tracks = _list_tracks(os.path.join(_SFX_ROOT, folder_name))
        if not tracks:
            continue
        chosen = _pick_with_history(tracks, history)
        if not chosen:
            continue
        next_history = _normalize_history(history + [chosen])
        logger.info(
            "Auto-sfx: tone='{}' -> folder='{}' -> '{}'",
            story_tone,
            folder_name,
            os.path.basename(chosen),
        )
        return {
            "path": chosen,
            "history": next_history,
            "folder": folder_name,
            "volume": 0.10,
            "fade_in": 1.5,
            "fade_out": 2.0,
            "loop": True,
            "ducking_enabled": True,
            "ducking_level": 0.20,
        }

    logger.warning("Auto-sfx: no tracks found for tone '{}' in folders {}", story_tone, folders)
    return None


def recall_last_sfx(history=None):
    """Reuse the most recent valid built-in SFX file from history, if available."""
    chosen = _last_valid_history_track(history, _SFX_ROOT)
    if not chosen:
        return None
    folder_name = os.path.basename(os.path.dirname(chosen))
    logger.info("Auto-sfx: reusing history pick '{}'", os.path.basename(chosen))
    return {
        "path": chosen,
        "folder": folder_name,
        "volume": 0.10,
        "fade_in": 1.5,
        "fade_out": 2.0,
        "loop": True,
        "ducking_enabled": True,
        "ducking_level": 0.20,
    }
