"""Artifact index store — content-addressed metadata over managed files.

Layout (contracts.md §3 store layout decision):

* Blob files stay under the V2 per-module trees (``output/tts/``,
  ``output/scenes/``, …). This package never relocates them.
* Index records live at ``output/artifacts/{art_id}.json``.
* A secondary content-hash index at
  ``output/artifacts/by_hash/{hh}/{content_digest}.json`` lists artifact ids
  that share a digest, so the store is content-addressable without a parallel
  blob store.

Versions are immutable and additive. Registering a new file for the same
``(job_id, scene_id, kind)`` chain creates version N+1 and sets
``superseded_by`` on the prior active record — the only mutation an existing
record ever receives. Prior versions remain resolvable forever.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import random
import string
import threading
from typing import Any, Iterable

from config import ARTIFACTS_DIR, OUTPUT_DIR
from scriptase.artifacts.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.artifacts.models import (
    ARTIFACT_ID_RE,
    ARTIFACT_KINDS,
    Artifact,
    ArtifactKind,
    normalize_managed_path,
    parse_artifact,
    validation_problems,
)
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

from pydantic import ValidationError


class ArtifactNotFound(FileNotFoundError):
    """Raised when an artifact id does not resolve in the index."""

    def __init__(self, artifact_id: str):
        super().__init__(artifact_id)
        self.artifact_id = artifact_id
        self.code = "ARTIFACT_NOT_FOUND"


class ArtifactValidationError(ValueError):
    """Schema or path validation failed; ``problems`` carries structured details."""

    def __init__(self, problems: list[dict[str, Any]], *, code: str = "ARTIFACT_INVALID"):
        super().__init__("Artifact document failed validation")
        self.problems = problems
        self.code = code


class ArtifactSuperseded(RuntimeError):
    """Operation targeted a superseded artifact version."""

    def __init__(self, artifact_id: str, superseded_by: str):
        super().__init__(
            f"Artifact {artifact_id} was superseded by {superseded_by}"
        )
        self.artifact_id = artifact_id
        self.superseded_by = superseded_by
        self.code = "ARTIFACT_SUPERSEDED"


class ArtifactMissing(FileNotFoundError):
    """Managed path does not exist or is empty on disk."""

    def __init__(self, path: str, *, reason: str = "artifact_missing"):
        super().__init__(path)
        self.path = path
        self.reason = reason
        self.code = "ARTIFACT_MISSING"


# Module-level roots so tests can rebind without patching config.
_artifacts_dir: str = ARTIFACTS_DIR
_output_dir: str = OUTPUT_DIR

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _chain_key(job_id: str, scene_id: str | None, kind: str) -> str:
    scene = scene_id or "_"
    return f"{job_id}\0{scene}\0{kind}"


def _path(artifact_id: str) -> str:
    if not isinstance(artifact_id, str) or not ARTIFACT_ID_RE.fullmatch(artifact_id):
        raise ValueError("artifact_id must match art_[A-Z0-9]{6}")
    return safe_join(_artifacts_dir, f"{artifact_id}.json")


def _hash_index_path(content_digest: str) -> str:
    """Secondary content-addressed index path for a bare hex digest."""
    digest = content_digest.lower()
    if len(digest) != 64:
        raise ValueError("content digest must be 64 hex chars")
    return safe_join(_artifacts_dir, "by_hash", digest[:2], f"{digest}.json")


def _generate_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "art_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(_path(candidate)):
            return candidate
    raise RuntimeError("Could not allocate an artifact id")


def _validate_document(data: dict[str, Any]) -> Artifact:
    try:
        return parse_artifact(data)
    except ValidationError as exc:
        raise ArtifactValidationError(validation_problems(exc)) from exc


def _write(document: Artifact) -> Artifact:
    os.makedirs(_artifacts_dir, exist_ok=True)
    path = _path(document.id)
    safe_json_write(path, document.to_document(), indent=2)
    _index_by_hash(document)
    return document


def _index_by_hash(document: Artifact) -> None:
    """Append ``document.id`` to the content-hash secondary index (idempotent)."""
    index_path = _hash_index_path(document.content_digest)
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    try:
        payload = safe_json_read(index_path)
    except FileNotFoundError:
        payload = {
            "content_hash": document.content_hash,
            "artifact_ids": [],
        }
    ids = list(payload.get("artifact_ids") or [])
    if document.id not in ids:
        ids.append(document.id)
    payload = {
        "content_hash": document.content_hash,
        "artifact_ids": ids,
    }
    safe_json_write(index_path, payload, indent=2)


def _load_raw(artifact_id: str) -> dict[str, Any]:
    path = _path(artifact_id)
    try:
        return safe_json_read(path)
    except FileNotFoundError as exc:
        raise ArtifactNotFound(artifact_id) from exc


def _absolute_for(relative_path: str) -> str:
    """Resolve a managed relative path under the output root."""
    rel = normalize_managed_path(relative_path)
    try:
        absolute = safe_join(_output_dir, *rel.split("/"))
    except ValueError as exc:
        raise ArtifactValidationError(
            [{"loc": ["path"], "msg": "path escapes the managed output root", "type": "value_error"}],
            code="ARTIFACT_UNMANAGED",
        ) from exc
    return absolute


def hash_file(absolute_path: str) -> tuple[str, int]:
    """Return ``(sha256:<hex>, size_bytes)`` for a file on disk.

    Empty / missing files fail closed (matches engine cache integrity).
    """
    if not os.path.isfile(absolute_path):
        raise ArtifactMissing(absolute_path, reason="artifact_missing")
    size = os.path.getsize(absolute_path)
    if size <= 0:
        raise ArtifactMissing(absolute_path, reason="artifact_empty")
    digest = hashlib.sha256()
    with open(absolute_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}", size


def guess_mime(relative_path: str, explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    guessed, _ = mimetypes.guess_type(relative_path)
    return guessed or "application/octet-stream"


def versioned_relative_path(base_path: str, version: int) -> str:
    """Insert ``_v{N}`` before the extension: ``image.png`` → ``image_v2.png``.

    Callers that want additive on-disk versions (so a repair never overwrites
    the prior file) use this helper when choosing the destination path for
    ``ArtifactPromoter`` / adapters. The index records whatever path is given.
    """
    rel = normalize_managed_path(base_path)
    if version < 1:
        raise ValueError("version must be >= 1")
    directory, _, filename = rel.rpartition("/")
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        # No extension: ``storyboard`` → ``storyboard_v2``
        name = f"{filename}_v{version}"
    else:
        name = f"{stem}_v{version}.{ext}"
    return f"{directory}/{name}" if directory else name


def get_artifact(artifact_id: str, *, require_active: bool = False) -> Artifact:
    """Load, migrate, and validate an artifact. Raises ArtifactNotFound.

    When ``require_active`` is True and the record has been superseded, raises
    ``ArtifactSuperseded`` (error code ``ARTIFACT_SUPERSEDED``).
    """
    raw = _load_raw(artifact_id)
    migrated, changed = apply_migrations(raw)
    document = _validate_document(migrated)
    if changed:
        _write(document)
    if require_active and document.superseded_by is not None:
        raise ArtifactSuperseded(document.id, document.superseded_by)
    return document


def list_artifacts(
    *,
    job_id: str | None = None,
    scene_id: str | None = None,
    kind: str | None = None,
    include_superseded: bool = True,
    limit: int = 500,
) -> list[Artifact]:
    """Return artifacts newest-first (by created_at, then id)."""
    os.makedirs(_artifacts_dir, exist_ok=True)
    items: list[Artifact] = []
    for filename in os.listdir(_artifacts_dir):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        artifact_id = filename[:-5]
        if not ARTIFACT_ID_RE.fullmatch(artifact_id):
            continue
        try:
            item = get_artifact(artifact_id)
        except (ArtifactNotFound, ArtifactValidationError, ValueError, OSError):
            continue
        if job_id is not None and item.job_id != job_id:
            continue
        if scene_id is not None and item.scene_id != scene_id:
            continue
        if kind is not None and item.kind != kind:
            continue
        if not include_superseded and item.superseded_by is not None:
            continue
        items.append(item)
    items.sort(
        key=lambda item: (item.created_at or "", item.id),
        reverse=True,
    )
    return items[:limit]


def find_by_content_hash(content_hash: str) -> list[Artifact]:
    """Resolve artifacts by content hash (content-addressed lookup)."""
    from scriptase.artifacts.models import normalize_content_hash

    normalized = normalize_content_hash(content_hash)
    digest = normalized.removeprefix("sha256:")
    index_path = _hash_index_path(digest)
    try:
        payload = safe_json_read(index_path)
    except FileNotFoundError:
        return []
    results: list[Artifact] = []
    for artifact_id in payload.get("artifact_ids") or []:
        if not isinstance(artifact_id, str):
            continue
        try:
            results.append(get_artifact(artifact_id))
        except (ArtifactNotFound, ArtifactValidationError, ValueError, OSError):
            continue
    return results


def active_artifact(
    job_id: str,
    kind: str,
    *,
    scene_id: str | None = None,
) -> Artifact | None:
    """Return the non-superseded artifact for a (job, scene, kind) chain."""
    if kind not in ARTIFACT_KINDS:
        raise ArtifactValidationError(
            [{"loc": ["kind"], "msg": f"unknown kind: {kind}", "type": "value_error"}]
        )
    candidates = list_artifacts(
        job_id=job_id,
        scene_id=scene_id,
        kind=kind,
        include_superseded=False,
        limit=50,
    )
    # list_artifacts with scene_id=None means "any scene". Filter exactly.
    exact = [
        item
        for item in candidates
        if item.scene_id == scene_id and item.kind == kind and item.job_id == job_id
    ]
    if not exact:
        return None
    # Highest version wins if more than one somehow lacks superseded_by.
    exact.sort(key=lambda item: item.version, reverse=True)
    return exact[0]


def register_artifact(
    *,
    job_id: str,
    kind: ArtifactKind | str,
    path: str,
    scene_id: str | None = None,
    provenance_ref: str | None = None,
    from_sample_data: bool = False,
    mime: str | None = None,
    content_hash: str | None = None,
    size_bytes: int | None = None,
) -> Artifact:
    """Record a managed file as an immutable Artifact version.

    Hashes the file on disk (unless both ``content_hash`` and ``size_bytes``
    are supplied — used by tests / already-verified callers). If an active
    artifact already exists for the same ``(job_id, scene_id, kind)``, this
    creates version N+1 and marks the prior record ``superseded_by`` the new id.

    The blob is not moved. Callers write via ``ArtifactPromoter`` (or any other
    managed write) first, then register.
    """
    if not isinstance(job_id, str) or not job_id.strip():
        raise ArtifactValidationError(
            [{"loc": ["job_id"], "msg": "job_id is required", "type": "value_error"}]
        )
    job_id = job_id.strip()
    kind_text = str(kind).strip()
    if kind_text not in ARTIFACT_KINDS:
        raise ArtifactValidationError(
            [{"loc": ["kind"], "msg": f"kind must be one of: {', '.join(ARTIFACT_KINDS)}", "type": "value_error"}]
        )

    try:
        rel = normalize_managed_path(path)
    except ValueError as exc:
        raise ArtifactValidationError(
            [{"loc": ["path"], "msg": str(exc), "type": "value_error"}],
            code="ARTIFACT_UNMANAGED",
        ) from exc

    absolute = _absolute_for(rel)
    if content_hash is None or size_bytes is None:
        computed_hash, computed_size = hash_file(absolute)
        content_hash = content_hash or computed_hash
        size_bytes = size_bytes if size_bytes is not None else computed_size
    if size_bytes <= 0:
        raise ArtifactMissing(rel, reason="artifact_empty")

    resolved_mime = guess_mime(rel, mime)
    chain = _chain_key(job_id, scene_id, kind_text)
    lock = _thread_lock(chain)

    with lock:
        prior = active_artifact(job_id, kind_text, scene_id=scene_id)
        next_version = (prior.version + 1) if prior is not None else 1
        artifact_id = _generate_id()
        timestamp = now_iso()

        try:
            document = Artifact(
                id=artifact_id,
                schema_version=SCHEMA_VERSION,
                job_id=job_id,
                scene_id=scene_id,
                kind=kind_text,  # type: ignore[arg-type]
                version=next_version,
                content_hash=content_hash,
                path=rel,
                size_bytes=int(size_bytes),
                mime=resolved_mime,
                provenance_ref=provenance_ref,
                created_at=timestamp,
                superseded_by=None,
                from_sample_data=bool(from_sample_data),
            )
        except ValidationError as exc:
            raise ArtifactValidationError(validation_problems(exc)) from exc

        # Write the new version first so a crash mid-supersede leaves an
        # extra active tip rather than a hole in the chain.
        _write(document)

        if prior is not None:
            superseded = prior.model_copy(update={"superseded_by": document.id})
            _write(superseded)

        return document


def register_from_refs(
    *,
    job_id: str,
    kind: ArtifactKind | str,
    refs: Iterable[str],
    scene_id: str | None = None,
    provenance_ref: str | None = None,
    from_sample_data: bool = False,
    mime: str | None = None,
) -> list[Artifact]:
    """Register each relative ``artifact_refs`` entry. Order preserved.

    Adapters keep emitting relative refs; callers that own a Job id use this
    to attach artifact identity without changing adapter code.
    """
    registered: list[Artifact] = []
    for ref in refs or ():
        if not isinstance(ref, str) or not ref.strip():
            continue
        registered.append(
            register_artifact(
                job_id=job_id,
                kind=kind,
                path=ref,
                scene_id=scene_id,
                provenance_ref=provenance_ref,
                from_sample_data=from_sample_data,
                mime=mime,
            )
        )
    return registered


def absolute_path(artifact: Artifact | str) -> str:
    """Absolute filesystem path for an artifact (or its id)."""
    if isinstance(artifact, str):
        artifact = get_artifact(artifact)
    return _absolute_for(artifact.path)


def verify_integrity(artifact: Artifact | str) -> dict[str, Any]:
    """Re-hash the on-disk file and compare to the recorded content hash.

    Returns ``{"ok": True, "size": N, "content_hash": "..."}`` or raises
    ``ArtifactMissing`` / returns ``{"ok": False, "reason": ...}``.
    """
    if isinstance(artifact, str):
        artifact = get_artifact(artifact)
    absolute = _absolute_for(artifact.path)
    try:
        current_hash, size = hash_file(absolute)
    except ArtifactMissing as exc:
        return {"ok": False, "reason": exc.reason, "path": artifact.path}
    if current_hash != artifact.content_hash:
        return {
            "ok": False,
            "reason": "artifact_integrity_failed",
            "path": artifact.path,
            "expected": artifact.content_hash,
            "actual": current_hash,
            "size": size,
        }
    return {
        "ok": True,
        "path": artifact.path,
        "size": size,
        "content_hash": current_hash,
    }


def retire_artifact(artifact_id: str) -> Artifact:
    """Mark an active artifact superseded without a replacement version.

    Used when re-segmentation invalidates a scene's media (contracts.md §4):
    the prior file remains resolvable as evidence, but is no longer the active
    tip. ``superseded_by`` is set to the artifact's own id (self-tombstone) so
    the field stays within ``art_[A-Z0-9]{6}`` shape.
    """
    if not isinstance(artifact_id, str) or not ARTIFACT_ID_RE.fullmatch(artifact_id):
        raise ValueError("artifact_id must match art_[A-Z0-9]{6}")
    lock = _thread_lock(artifact_id)
    with lock:
        current = get_artifact(artifact_id)
        if current.superseded_by is not None:
            return current
        document = current.model_copy(update={"superseded_by": current.id})
        return _write(document)


def retire_artifacts_for_scene(job_id: str, scene_id: str) -> list[Artifact]:
    """Retire every active artifact bound to ``(job_id, scene_id)``."""
    active = list_artifacts(
        job_id=job_id,
        scene_id=scene_id,
        include_superseded=False,
        limit=500,
    )
    retired: list[Artifact] = []
    for item in active:
        if item.scene_id != scene_id:
            continue
        retired.append(retire_artifact(item.id))
    return retired


def assert_no_active_artifact_on_dead_scenes(
    job_id: str,
    active_scene_ids: list[str] | set[str],
) -> None:
    """Raise if any active artifact still names a scene outside the active set."""
    active = set(active_scene_ids)
    offenders: list[str] = []
    for item in list_artifacts(job_id=job_id, include_superseded=False, limit=500):
        if item.scene_id is None:
            continue
        if item.scene_id not in active:
            offenders.append(f"{item.id}:{item.scene_id}")
    if offenders:
        raise RuntimeError(
            "active artifacts bound to scenes that no longer resolve: "
            + ", ".join(offenders)
        )


__all__ = [
    "ArtifactNotFound",
    "ArtifactValidationError",
    "ArtifactSuperseded",
    "ArtifactMissing",
    "hash_file",
    "guess_mime",
    "versioned_relative_path",
    "get_artifact",
    "list_artifacts",
    "find_by_content_hash",
    "active_artifact",
    "register_artifact",
    "register_from_refs",
    "absolute_path",
    "verify_integrity",
    "retire_artifact",
    "retire_artifacts_for_scene",
    "assert_no_active_artifact_on_dead_scenes",
]
