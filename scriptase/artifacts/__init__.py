"""Typed, versioned, content-addressed artifacts (step 1.2).

Replaces V2's ``artifact_refs: list[str]`` naming convention with a real
``Artifact``: stable id, kind, owning job, owning scene, version, content hash,
relative managed path, size, mime, provenance reference, and ``superseded_by``.

Versions are immutable and additive — a repair never erases the evidence of what
it replaced. This layer sits *above* the engine's ``ArtifactPromoter`` and cache
integrity re-hashing and records what they produce.

Adapters keep emitting relative refs; :mod:`scriptase.artifacts.resolve` maps
those refs onto artifact identity when the index knows about them.
"""

from scriptase.artifacts.models import (
    ARTIFACT_ID_RE,
    ARTIFACT_KINDS,
    ARTIFACT_SCHEMA_VERSION,
    Artifact,
    ArtifactKind,
    normalize_content_hash,
    normalize_managed_path,
    parse_artifact,
    validation_problems,
)
from scriptase.artifacts.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.artifacts.resolve import (
    artifact_ids_for_payload,
    extract_refs,
    resolve_many,
    resolve_ref,
    with_artifact_ids,
)
from scriptase.artifacts.store import (
    ArtifactMissing,
    ArtifactNotFound,
    ArtifactSuperseded,
    ArtifactValidationError,
    absolute_path,
    active_artifact,
    find_by_content_hash,
    get_artifact,
    guess_mime,
    hash_file,
    list_artifacts,
    register_artifact,
    register_from_refs,
    verify_integrity,
    versioned_relative_path,
)

__all__ = [
    "ARTIFACT_ID_RE",
    "ARTIFACT_KINDS",
    "ARTIFACT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "Artifact",
    "ArtifactKind",
    "ArtifactMissing",
    "ArtifactNotFound",
    "ArtifactSuperseded",
    "ArtifactValidationError",
    "absolute_path",
    "active_artifact",
    "apply_migrations",
    "artifact_ids_for_payload",
    "extract_refs",
    "find_by_content_hash",
    "get_artifact",
    "guess_mime",
    "hash_file",
    "list_artifacts",
    "normalize_content_hash",
    "normalize_managed_path",
    "parse_artifact",
    "register_artifact",
    "register_from_refs",
    "resolve_many",
    "resolve_ref",
    "validation_problems",
    "verify_integrity",
    "versioned_relative_path",
    "with_artifact_ids",
]
