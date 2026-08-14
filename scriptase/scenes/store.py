"""Scene identity store — stable ``scn_`` records per Job.

Layout (contracts.md §4):

* Index records live at ``output/scene_records/{scn_id}.json``.
* Distinct from ``output/scenes/`` (Scene Director blueprint payloads).

Active scenes have ``superseded_by is None``. Re-segmentation may update span
fields in place on a rebind (same id) or set ``superseded_by`` when a prior
scene is replaced. Documents remain resolvable by id forever so repair history
can still name them.
"""

from __future__ import annotations

import os
import random
import string
import threading
from typing import Any

from config import SCENE_RECORDS_DIR
from scriptase.scenes.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.scenes.models import (
    SCENE_ID_RE,
    Scene,
    parse_scene,
    validation_problems,
)
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

from pydantic import ValidationError


class SceneNotFound(FileNotFoundError):
    """Raised when a scene id does not resolve in the index."""

    def __init__(self, scene_id: str):
        super().__init__(scene_id)
        self.scene_id = scene_id
        self.code = "SCENE_NOT_FOUND"


class SceneSuperseded(RuntimeError):
    """Operation targeted a superseded scene."""

    def __init__(self, scene_id: str, superseded_by: str):
        super().__init__(
            f"Scene {scene_id} was superseded by {superseded_by}"
        )
        self.scene_id = scene_id
        self.superseded_by = superseded_by
        self.code = "SCENE_SUPERSEDED"


class SceneValidationError(ValueError):
    """Schema validation failed; ``problems`` carries structured details."""

    def __init__(self, problems: list[dict[str, Any]], *, code: str = "SCENE_INVALID"):
        super().__init__("Scene document failed validation")
        self.problems = problems
        self.code = code


# Module-level roots so tests can rebind without patching config.
_scenes_dir: str = SCENE_RECORDS_DIR

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _path(scene_id: str) -> str:
    if not isinstance(scene_id, str) or not SCENE_ID_RE.fullmatch(scene_id):
        raise ValueError("scene_id must match scn_[A-Z0-9]{6}")
    return safe_join(_scenes_dir, f"{scene_id}.json")


def _generate_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "scn_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(_path(candidate)):
            return candidate
    raise RuntimeError("Could not allocate a scene id")


def _validate_document(data: dict[str, Any]) -> Scene:
    try:
        return parse_scene(data)
    except ValidationError as exc:
        raise SceneValidationError(validation_problems(exc)) from exc


def _write(document: Scene) -> Scene:
    os.makedirs(_scenes_dir, exist_ok=True)
    path = _path(document.id)
    safe_json_write(path, document.to_document(), indent=2)
    return document


def _load_raw(scene_id: str) -> dict[str, Any]:
    path = _path(scene_id)
    try:
        return safe_json_read(path)
    except FileNotFoundError as exc:
        raise SceneNotFound(scene_id) from exc


def get_scene(scene_id: str, *, require_active: bool = False) -> Scene:
    """Load, migrate, and validate a scene. Raises SceneNotFound.

    When ``require_active`` is True and the record has been superseded, raises
    ``SceneSuperseded`` (or ``SceneNotFound`` when the successor is a pure
    invalidation tombstone pointing at the same id).
    """
    if not isinstance(scene_id, str) or not SCENE_ID_RE.fullmatch(scene_id):
        raise SceneNotFound(scene_id or "")
    raw = _load_raw(scene_id)
    migrated, changed = apply_migrations(raw)
    document = _validate_document(migrated)
    if changed:
        _write(document)
    if require_active and document.superseded_by is not None:
        raise SceneSuperseded(document.id, document.superseded_by)
    return document


def resolve_scene(scene_id: str) -> Scene:
    """Resolve an *active* scene id. Raises SceneNotFound if missing or superseded.

    This is the lookup used by repair and review: a superseded id does not
    resolve, matching contracts.md error code ``SCENE_NOT_FOUND``.
    """
    try:
        return get_scene(scene_id, require_active=True)
    except SceneSuperseded as exc:
        raise SceneNotFound(scene_id) from exc


def list_scenes(
    *,
    job_id: str | None = None,
    include_superseded: bool = True,
    limit: int = 500,
) -> list[Scene]:
    """Return scenes newest-first by ``created_at`` then id."""
    os.makedirs(_scenes_dir, exist_ok=True)
    items: list[Scene] = []
    for filename in os.listdir(_scenes_dir):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        scene_id = filename[:-5]
        if not SCENE_ID_RE.fullmatch(scene_id):
            continue
        try:
            item = get_scene(scene_id)
        except (SceneNotFound, SceneValidationError, ValueError, OSError):
            continue
        if job_id is not None and item.job_id != job_id:
            continue
        if not include_superseded and item.superseded_by is not None:
            continue
        items.append(item)
    items.sort(
        key=lambda item: (item.created_at or "", item.id),
        reverse=True,
    )
    return items[:limit]


def active_scenes_for_job(job_id: str) -> list[Scene]:
    """Active scenes for a job, ordered by ordinal (presentation order)."""
    items = list_scenes(job_id=job_id, include_superseded=False, limit=500)
    items.sort(key=lambda item: (item.ordinal, item.id))
    return items


def create_scene(
    *,
    job_id: str,
    ordinal: int,
    start: float,
    end: float,
    segment_words: str = "",
    duration: float | None = None,
    scene_id: str | None = None,
) -> Scene:
    """Allocate a new stable scene id and persist the record."""
    if not isinstance(job_id, str) or not job_id.strip():
        raise SceneValidationError(
            [{"loc": ["job_id"], "msg": "job_id is required", "type": "value_error"}]
        )
    job_id = job_id.strip()
    start_f = float(start)
    end_f = float(end)
    if end_f < start_f:
        raise SceneValidationError(
            [{"loc": ["end"], "msg": "end must be >= start", "type": "value_error"}]
        )
    dur = float(duration) if duration is not None else round(end_f - start_f, 6)
    timestamp = now_iso()

    with _GLOBAL_LOCK:
        allocated = scene_id if scene_id and SCENE_ID_RE.fullmatch(scene_id) else _generate_id()
        if os.path.exists(_path(allocated)):
            raise SceneValidationError(
                [{"loc": ["id"], "msg": f"scene id already exists: {allocated}", "type": "value_error"}]
            )
        try:
            document = Scene(
                id=allocated,
                schema_version=SCHEMA_VERSION,
                job_id=job_id,
                ordinal=int(ordinal),
                start=start_f,
                end=end_f,
                duration=dur,
                segment_words=segment_words or "",
                superseded_by=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
        except ValidationError as exc:
            raise SceneValidationError(validation_problems(exc)) from exc
        return _write(document)


def update_scene_span(
    scene_id: str,
    *,
    ordinal: int | None = None,
    start: float | None = None,
    end: float | None = None,
    duration: float | None = None,
    segment_words: str | None = None,
) -> Scene:
    """Update presentation/span fields on an active scene (rebind path)."""
    lock = _thread_lock(scene_id)
    with lock:
        current = get_scene(scene_id, require_active=True)
        next_start = float(start) if start is not None else current.start
        next_end = float(end) if end is not None else current.end
        if next_end < next_start:
            raise SceneValidationError(
                [{"loc": ["end"], "msg": "end must be >= start", "type": "value_error"}]
            )
        if duration is not None:
            next_duration = float(duration)
        elif start is not None or end is not None:
            next_duration = round(next_end - next_start, 6)
        else:
            next_duration = current.duration
        updates: dict[str, Any] = {
            "start": next_start,
            "end": next_end,
            "duration": next_duration,
            "updated_at": now_iso(),
        }
        if ordinal is not None:
            updates["ordinal"] = int(ordinal)
        if segment_words is not None:
            updates["segment_words"] = segment_words
        document = current.model_copy(update=updates)
        return _write(document)


def mark_superseded(scene_id: str, successor_id: str) -> Scene:
    """Point a prior scene at its successor. Idempotent when already set.

    ``successor_id`` may equal ``scene_id`` for a pure invalidation tombstone
    (no temporal successor after re-segmentation).
    """
    if not isinstance(successor_id, str) or not SCENE_ID_RE.fullmatch(successor_id):
        raise ValueError("successor_id must match scn_[A-Z0-9]{6}")
    lock = _thread_lock(scene_id)
    with lock:
        current = get_scene(scene_id)
        if current.superseded_by == successor_id:
            return current
        if current.superseded_by is not None and current.superseded_by != successor_id:
            raise SceneSuperseded(current.id, current.superseded_by)
        document = current.model_copy(
            update={"superseded_by": successor_id, "updated_at": now_iso()}
        )
        return _write(document)


def scene_resolves(scene_id: str) -> bool:
    """True when the id exists and is not superseded."""
    try:
        resolve_scene(scene_id)
        return True
    except SceneNotFound:
        return False


__all__ = [
    "SceneNotFound",
    "SceneSuperseded",
    "SceneValidationError",
    "active_scenes_for_job",
    "create_scene",
    "get_scene",
    "list_scenes",
    "mark_superseded",
    "resolve_scene",
    "scene_resolves",
    "update_scene_span",
]
