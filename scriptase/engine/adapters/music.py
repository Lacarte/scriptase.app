from __future__ import annotations

import os

from config import MUSIC_DIR, MUSIC_LIBRARY_DIR
from scriptase.modules.music.selector import load_project_audio_history, select_music, select_random_music
from .common import AdapterError, inherited_config, outputs, project_id

# Two valid roots: the read-only built-in library and the writable V2 import
# location.  A track from either is accepted as managed.
_MANAGED_ROOTS: tuple[tuple[str, str], ...] = (
    (os.path.abspath(MUSIC_LIBRARY_DIR), "/assets/sounds/music/"),
    (os.path.abspath(MUSIC_DIR), "musics/"),
)


def _resolve_mode(config, merged) -> str:
    """The selection mode, honoring the Channel's random/specific intent.

    A node whose `mode` was explicitly set to something other than the schema
    default (`tone`) wins — an author who dialed in a mode on the node means it.
    Otherwise the Channel decides: `music_random` picks `random`, a curated
    `music_profile` with random off picks `specific`, and everything else falls
    back to tone-based selection.
    """
    node_mode = str((config or {}).get("mode") or "").strip()
    if node_mode and node_mode != "tone":
        return node_mode
    if _truthy(merged.get("music_random")):
        return "random"
    if str(merged.get("music_profile") or "").strip():
        return "specific"
    return node_mode or "tone"


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _managed_track(path: str) -> str:
    absolute = os.path.abspath(path)
    for root, prefix in _MANAGED_ROOTS:
        try:
            if os.path.commonpath([root, absolute]) != root:
                continue
        except ValueError:
            continue
        if not os.path.isfile(absolute):
            raise AdapterError("ARTIFACT_MISSING", "The selected music track does not exist")
        rel = os.path.relpath(absolute, root).replace("\\", "/")
        return f"{prefix}{rel}"
    raise AdapterError("ARTIFACT_UNMANAGED", "Music must come from the managed music library")


def select(inputs, config, context):
    merged = inherited_config(config, inputs.get("settings"), {"tone": "story_tone"})
    pid = project_id(context, inputs)
    history = load_project_audio_history(pid).get("music_history", [])
    mode = _resolve_mode(config, merged)
    if mode == "specific":
        ref = str(merged.get("track_ref") or merged.get("music_profile") or "")
        if ref.startswith("/assets/sounds/music/"):
            path = os.path.join(MUSIC_LIBRARY_DIR, ref[len("/assets/sounds/music/"):].replace("/", os.sep))
        elif ref.startswith("musics/"):
            path = os.path.join(MUSIC_DIR, ref[len("musics/"):].replace("/", os.sep))
        else:
            path = ref
        picked = {"path": path}
    elif mode == "random":
        picked = select_random_music(history=history)
    else:
        picked = select_music(merged.get("story_tone", ""), history=history)
        # Tone-based selection finds nothing when no track carries that tone
        # (e.g. a fresh library where everything sits in default/). Rather than
        # fail the whole job at Assembly, fall back to a random track — there is
        # music available, just not tone-tagged.
        if not picked or not picked.get("path"):
            picked = select_random_music(history=history)
    if not picked or not picked.get("path"):
        raise AdapterError("MUSIC_NOT_FOUND", "No matching music track is available")
    payload = {
        "project_id": pid, "path": _managed_track(picked["path"]),
        "filename": os.path.basename(picked["path"]),
        "volume": merged.get("volume", picked.get("volume", 0.15)),
        "fade_in": merged.get("fade_in", picked.get("fade_in", 2.0)),
        "fade_out": merged.get("fade_out", picked.get("fade_out", 3.0)),
        "loop": merged.get("loop", picked.get("loop", True)),
        "ducking_enabled": merged.get("ducking_enabled", picked.get("ducking_enabled", True)),
        "ducking_level": merged.get("ducking_level", picked.get("ducking_level", 0.2)),
        "pending_history": picked.get("history", history),
        "artifact_refs": [],
    }
    return outputs(track=payload)
