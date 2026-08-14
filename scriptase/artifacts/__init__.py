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
from scriptase.artifacts.input_sources import (
    INPUT_SOURCES,
    KIND_TO_PORT_TYPE,
    LIBRARY_JOB_ID,
    PORT_TYPE_TO_KIND,
    InputSourceError,
    artifact_summary,
    materialize_artifact,
    port_types_for_workflow,
    resolve_binding,
    resolve_input_bindings,
    source_artifact_ids_from_inputs,
)
from scriptase.artifacts.store import (
    ArtifactMissing,
    ArtifactNotFound,
    ArtifactSuperseded,
    ArtifactValidationError,
    absolute_path,
    active_artifact,
    assert_no_active_artifact_on_dead_scenes,
    find_by_content_hash,
    get_artifact,
    guess_mime,
    hash_file,
    list_artifacts,
    register_artifact,
    register_from_refs,
    retire_artifact,
    retire_artifacts_for_scene,
    verify_integrity,
    versioned_relative_path,
)
from scriptase.artifacts.routes import artifacts_bp

__all__ = [
    "ARTIFACT_ID_RE",
    "ARTIFACT_KINDS",
    "ARTIFACT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "INPUT_SOURCES",
    "KIND_TO_PORT_TYPE",
    "LIBRARY_JOB_ID",
    "PORT_TYPE_TO_KIND",
    "Artifact",
    "ArtifactKind",
    "ArtifactMissing",
    "ArtifactNotFound",
    "ArtifactSuperseded",
    "ArtifactValidationError",
    "InputSourceError",
    "absolute_path",
    "active_artifact",
    "apply_migrations",
    "artifact_ids_for_payload",
    "artifact_summary",
    "artifacts_bp",
    "assert_no_active_artifact_on_dead_scenes",
    "extract_refs",
    "find_by_content_hash",
    "get_artifact",
    "guess_mime",
    "hash_file",
    "list_artifacts",
    "materialize_artifact",
    "normalize_content_hash",
    "normalize_managed_path",
    "parse_artifact",
    "port_types_for_workflow",
    "register_artifact",
    "register_from_refs",
    "resolve_binding",
    "resolve_input_bindings",
    "resolve_many",
    "resolve_ref",
    "retire_artifact",
    "retire_artifacts_for_scene",
    "source_artifact_ids_from_inputs",
    "validation_problems",
    "verify_integrity",
    "versioned_relative_path",
    "with_artifact_ids",
]
