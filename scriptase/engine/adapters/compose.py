from __future__ import annotations

import os

from config import PROJECTS_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.modules.music.selector import persist_project_audio_history
from scriptase.modules.pipeline.services import _step_assemble
from .common import AdapterError, context_value, outputs, project_id, with_artifacts


def assemble(inputs, config, context):
    pid = project_id(context, inputs)
    # Typed inputs are readiness assertions. The legacy assembly service reads
    # the corresponding managed artifacts from disk (contracts D3/D4).
    result = _step_assemble(pid)
    path = os.path.join(PROJECTS_DIR, pid, "initial.json")
    assembled = result.get("assembled_data") or {}
    captions = inputs.get("captions")
    if isinstance(captions, dict):
        assembled["captions"] = captions
        assembled["captionsEnabled"] = bool(captions.get("captions"))
    track = inputs.get("music")
    if isinstance(track, dict) and track.get("path"):
        audio_tracks = [item for item in assembled.get("audio_tracks", []) if item.get("type") != "music"]
        audio_tracks.append({
            "id": "at_music_workflow", "label": "Music", "type": "music",
            "file": track.get("filename", ""), "path": track["path"], "duration": 0,
            "timelineOffset": 0, "startOffset": 0, "trimmedDuration": None,
            "volume": track.get("volume", 0.15), "loop": track.get("loop", True), "muted": False,
            "duckingEnabled": track.get("ducking_enabled", True), "duckingLevel": track.get("ducking_level", 0.2),
            "fadeIn": track.get("fade_in", 2.0), "fadeOut": track.get("fade_out", 3.0),
        })
        assembled["audio_tracks"] = audio_tracks
        if track.get("pending_history") is not None:
            assembled["music_history"] = track["pending_history"]
            persist_project_audio_history(pid, music_history=track["pending_history"])
    settings = inputs.get("settings")
    if isinstance(settings, dict):
        if settings.get("project_name"):
            assembled["project_name"] = settings["project_name"]
        assembled["project_settings"] = settings
    safe_json_write(path, assembled, indent=2)
    return outputs(project=with_artifacts({**result, "project_id": pid}, path))


def timeline_project(inputs, config, context):
    pid = project_id(context, inputs)
    payload = dict(inputs["project"])
    assembled = payload.get("assembled_data")
    if not isinstance(assembled, dict):
        raise AdapterError("EDITOR_PROJECT_INVALID", "Editor project payload is missing assembled_data")
    path = os.path.join(PROJECTS_DIR, pid, "initial.json")
    if os.path.basename(path) != "initial.json":
        raise AdapterError("ARTIFACT_UNMANAGED", "Invalid editor project path")
    safe_json_write(path, assembled, indent=2)
    result = with_artifacts({**payload, "project_id": pid}, path)
    return outputs(project=result, project_id={"project_id": pid})
