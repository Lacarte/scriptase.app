"""Atomic JSON store for first-class Script Studio documents."""

from __future__ import annotations

import os
import random
import shutil
import string
import threading
from typing import Any

from pydantic import ValidationError

from config import SCRIPTS_DIR, TRASH_DIR
from scriptase.artifacts.models import Artifact
from scriptase.artifacts.store import ArtifactNotFound, get_artifact
from scriptase.scripts.models import (
    SCRIPT_ID_RE,
    SCRIPT_SCHEMA_VERSION,
    ScriptDraft,
    StudioScript,
    parse_draft,
    parse_script,
    script_metrics,
    validation_problems,
)
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join


class ScriptNotFound(FileNotFoundError):
    def __init__(self, script_id: str):
        super().__init__(script_id)
        self.script_id = script_id


class ScriptConflict(RuntimeError):
    def __init__(self, script_id: str):
        super().__init__(f"Script version conflict: {script_id}")
        self.script_id = script_id


class ScriptValidationError(ValueError):
    def __init__(self, problems: list[dict[str, Any]]):
        super().__init__("Script document failed schema validation")
        self.problems = problems
        self.code = "SCRIPT_INVALID"


_scripts_dir: str = SCRIPTS_DIR
_trash_dir: str = os.path.join(TRASH_DIR, "scripts")
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _path(script_id: str) -> str:
    if not isinstance(script_id, str) or not SCRIPT_ID_RE.fullmatch(script_id):
        raise ValueError("script_id must match scr_[A-Z0-9]{6}")
    return safe_join(_scripts_dir, f"{script_id}.json")


def _generate_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "scr_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(_path(candidate)):
            return candidate
    raise RuntimeError("Could not allocate a script id")


def _draft(data: dict[str, Any]) -> ScriptDraft:
    try:
        return parse_draft(data)
    except ValidationError as exc:
        raise ScriptValidationError(validation_problems(exc)) from exc


def _document(data: dict[str, Any]) -> StudioScript:
    try:
        return parse_script(data)
    except ValidationError as exc:
        raise ScriptValidationError(validation_problems(exc)) from exc


def _write(document: StudioScript) -> StudioScript:
    os.makedirs(_scripts_dir, exist_ok=True)
    safe_json_write(_path(document.id), document.to_document(), indent=2)
    return document


def _validate_audio_owner(script_id: str, draft: ScriptDraft) -> None:
    artifact_id = draft.narration.audio_artifact_id
    if artifact_id is None:
        return
    try:
        artifact = get_artifact(artifact_id)
    except ArtifactNotFound as exc:
        raise ScriptValidationError([{
            "loc": ["narration", "audio_artifact_id"],
            "msg": "audio artifact does not exist",
            "type": "value_error",
        }]) from exc
    if artifact.kind != "audio":
        raise ScriptValidationError([{
            "loc": ["narration", "audio_artifact_id"],
            "msg": "artifact must have kind audio",
            "type": "value_error",
        }])
    if artifact.job_id != script_id:
        raise ScriptValidationError([{
            "loc": ["narration", "audio_artifact_id"],
            "msg": "audio artifact is not owned by this script",
            "type": "value_error",
        }])


def _build(
    script_id: str,
    draft: ScriptDraft,
    *,
    version: int,
    created_at: str,
    updated_at: str,
) -> StudioScript:
    word_count, estimated_duration_s = script_metrics(draft.body)
    return StudioScript(
        **draft.model_dump(mode="python"),
        id=script_id,
        version=version,
        schema_version=SCRIPT_SCHEMA_VERSION,
        created_at=created_at,
        updated_at=updated_at,
        word_count=word_count,
        estimated_duration_s=estimated_duration_s,
    )


def create_script(draft: dict[str, Any]) -> StudioScript:
    parsed = _draft(draft)
    script_id = _generate_id()
    _validate_audio_owner(script_id, parsed)
    timestamp = now_iso()
    return _write(_build(
        script_id, parsed, version=1, created_at=timestamp, updated_at=timestamp
    ))


def get_script(script_id: str) -> StudioScript:
    try:
        raw = safe_json_read(_path(script_id))
    except FileNotFoundError as exc:
        raise ScriptNotFound(script_id) from exc
    return _document(raw)


def list_scripts(
    *,
    channel_id: str | None = None,
    origin: str | None = None,
    query: str | None = None,
    limit: int = 200,
) -> list[StudioScript]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    needle = (query or "").strip().casefold()
    os.makedirs(_scripts_dir, exist_ok=True)
    items: list[StudioScript] = []
    for filename in os.listdir(_scripts_dir):
        script_id = filename[:-5] if filename.endswith(".json") else ""
        if not SCRIPT_ID_RE.fullmatch(script_id):
            continue
        try:
            item = get_script(script_id)
        except (ScriptNotFound, ScriptValidationError, ValueError, OSError):
            continue
        if channel_id is not None and item.channel_id != channel_id:
            continue
        if origin is not None and item.origin != origin:
            continue
        if needle and needle not in f"{item.title}\n{item.body}".casefold():
            continue
        items.append(item)
    items.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
    return items[:limit]


def update_script(
    script_id: str,
    draft: dict[str, Any],
    *,
    expected_version: int | None = None,
) -> StudioScript:
    with _thread_lock(script_id):
        current = get_script(script_id)
        if expected_version is not None and current.version != expected_version:
            raise ScriptConflict(script_id)
        parsed = _draft(draft)
        _validate_audio_owner(script_id, parsed)
        return _write(_build(
            script_id,
            parsed,
            version=current.version + 1,
            created_at=current.created_at,
            updated_at=now_iso(),
        ))


def delete_script(script_id: str, *, expected_version: int | None = None) -> None:
    with _thread_lock(script_id):
        path = _path(script_id)
        if not os.path.isfile(path) and not os.path.isfile(path + ".bak"):
            raise ScriptNotFound(script_id)
        if expected_version is not None and get_script(script_id).version != expected_version:
            raise ScriptConflict(script_id)
        os.makedirs(_trash_dir, exist_ok=True)
        stamp = now_iso().replace(":", "").replace("+", "_")
        destination = os.path.join(_trash_dir, f"{script_id}_{stamp}.json")
        if os.path.isfile(path + ".bak"):
            shutil.move(path + ".bak", destination + ".bak")
        if os.path.isfile(path):
            shutil.move(path, destination)
        score_path = safe_join(_scripts_dir, f"{script_id}.virality.json")
        if os.path.isfile(score_path):
            shutil.move(score_path, destination + ".virality")


def resolve_narration_audio(script: StudioScript | str) -> Artifact | None:
    """Resolve a Script's narration ID through the shared artifact store."""
    document = get_script(script) if isinstance(script, str) else script
    artifact_id = document.narration.audio_artifact_id
    if artifact_id is None:
        return None
    try:
        artifact = get_artifact(artifact_id)
    except ArtifactNotFound as exc:
        raise ScriptValidationError([{
            "loc": ["narration", "audio_artifact_id"],
            "msg": "audio artifact does not exist",
            "type": "value_error",
        }]) from exc
    if artifact.kind != "audio" or artifact.job_id != document.id:
        raise ScriptValidationError([{
            "loc": ["narration", "audio_artifact_id"],
            "msg": "narration reference does not resolve to this script's audio",
            "type": "value_error",
        }])
    return artifact


def script_summary(document: StudioScript) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "channel_id": document.channel_id,
        "origin": document.origin,
        "version": document.version,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "word_count": document.word_count,
        "estimated_duration_s": document.estimated_duration_s,
        "narration": document.narration.model_dump(mode="json"),
    }


__all__ = [
    "ScriptNotFound", "ScriptConflict", "ScriptValidationError",
    "create_script", "get_script", "list_scripts", "update_script",
    "delete_script", "resolve_narration_audio", "script_summary",
]
