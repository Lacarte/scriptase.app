from __future__ import annotations

import os

from config import MUSIC_LIBRARY_DIR
from scriptase.modules.music.selector import load_project_audio_history, select_music, select_random_music
from .common import AdapterError, inherited_config, outputs, project_id


def _managed_track(path: str) -> str:
    root = os.path.abspath(MUSIC_LIBRARY_DIR)
    absolute = os.path.abspath(path)
    try:
        if os.path.commonpath([root, absolute]) != root:
            raise ValueError
    except ValueError as exc:
        raise AdapterError("ARTIFACT_UNMANAGED", "Music must come from the managed music library") from exc
    if not os.path.isfile(absolute):
        raise AdapterError("ARTIFACT_MISSING", "The selected music track does not exist")
    rel = os.path.relpath(absolute, root).replace("\\", "/")
    return f"/assets/sounds/music/{rel}"


def select(inputs, config, context):
    merged = inherited_config(config, inputs.get("settings"), {"tone": "story_tone"})
    pid = project_id(context, inputs)
    history = load_project_audio_history(pid).get("music_history", [])
    mode = merged.get("mode", "tone")
    if mode == "specific":
        ref = str(merged.get("track_ref") or "")
        if ref.startswith("/assets/sounds/music/"):
            path = os.path.join(MUSIC_LIBRARY_DIR, ref[len("/assets/sounds/music/"):].replace("/", os.sep))
        else:
            path = ref
        picked = {"path": path}
    elif mode == "random":
        picked = select_random_music(history=history)
    else:
        picked = select_music(merged.get("story_tone", ""), history=history)
    if not picked:
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
