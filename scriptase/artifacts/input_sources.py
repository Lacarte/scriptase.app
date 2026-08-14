"""Input sources for standalone / isolated node runs (step 4.1 / §9.1).

A node cannot run without its required inputs. This module resolves a binding
per port into a concrete port payload and the artifact ids that supplied it.

Supported sources (product §9.1):

* ``current_job`` — active artifact on the caller's Job (by kind / scene)
* ``job``         — artifact from a previous or other Job
* ``library``     — pick by artifact id from the index (any owner)
* ``upload``      — just-uploaded managed artifact (same resolve path as library)
* ``manual``      — operator-supplied JSON / text value
* ``sample``      — generated sample-data stub payload
* ``run_deps``    — not a payload; callers switch to ``node_with_deps``

Resolved payloads always carry ``artifact_ids`` when the source is an indexed
artifact so the execution record can record where the input came from.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Mapping

from scriptase.artifacts.models import ARTIFACT_ID_RE, ARTIFACT_KINDS, Artifact
from scriptase.artifacts.resolve import (
    artifact_ids_for_payload,
    resolve_many,
    resolve_ref,
)
from scriptase.artifacts.store import (
    ArtifactMissing,
    ArtifactNotFound,
    ArtifactSuperseded,
    ArtifactValidationError,
    absolute_path,
    active_artifact,
    get_artifact,
)
from scriptase.engine.sample_data import sample_payload

# Pseudo job id for managed uploads that are not owned by a production Job.
# Artifact.job_id is free-form (not constrained to job_XXXXXX); Job documents
# still use the strict id shape.
LIBRARY_JOB_ID = "library"

# §9.1 vocabulary. ``run_deps`` is handled by the caller (run-mode switch).
INPUT_SOURCES: tuple[str, ...] = (
    "current_job",
    "job",
    "library",
    "upload",
    "manual",
    "sample",
    "run_deps",
)

# Port type → preferred Artifact kind when resolving from a Job chain.
PORT_TYPE_TO_KIND: dict[str, str] = {
    "script": "script",
    "audio_file": "audio",
    "tts_metadata": "audio",
    "alignment": "alignment",
    "segments": "segments",
    "scenes": "scene_spec",
    "image_prompts": "scene_spec",
    "storyboard_images": "image",
    "animation_assets": "video",
    "captions": "captions",
    "music_track": "music",
    "editor_project": "timeline",
    "video_file": "export",
    "export_profile": "export",
}

# Kind → default port type when materializing without an explicit port type.
KIND_TO_PORT_TYPE: dict[str, str] = {
    "script": "script",
    "audio": "audio_file",
    "alignment": "alignment",
    "segments": "segments",
    "scene_spec": "scenes",
    "image": "storyboard_images",
    "video": "animation_assets",
    "captions": "captions",
    "music": "music_track",
    "timeline": "editor_project",
    "export": "video_file",
}


class InputSourceError(ValueError):
    """Binding could not be resolved to a port payload."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _as_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InputSourceError(
            "BAD_REQUEST",
            "Input binding must be an object",
        )
    return dict(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _load_json_file(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _is_json_path(path: str, mime: str) -> bool:
    lower = path.lower()
    if lower.endswith(".json"):
        return True
    return "json" in (mime or "").lower()


def _with_source_identity(payload: Any, artifact: Artifact) -> Any:
    """Attach artifact identity without dropping adapter-shaped envelopes."""
    if isinstance(payload, str):
        # Script / text ports are bare strings; wrap only when we must carry refs.
        return payload
    if not isinstance(payload, Mapping):
        return payload
    result = dict(payload)
    refs = list(result.get("artifact_refs") or [])
    if artifact.path not in refs:
        refs.append(artifact.path)
    result["artifact_refs"] = refs
    ids = list(result.get("artifact_ids") or [])
    if artifact.id not in ids:
        ids.append(artifact.id)
    result["artifact_ids"] = ids
    return result


def _media_envelope(artifact: Artifact, *, port_type: str) -> dict[str, Any]:
    """Build a minimal file-backed port payload for a binary artifact."""
    name = os.path.basename(artifact.path)
    base = {
        "artifact_refs": [artifact.path],
        "artifact_ids": [artifact.id],
        "filename": name,
        "mime": artifact.mime,
        "size_bytes": artifact.size_bytes,
        "content_hash": artifact.content_hash,
    }
    if port_type == "storyboard_images":
        scene_key = artifact.scene_id or "0"
        return {
            **base,
            "total": 1,
            "ready": 1,
            "errors": 0,
            "status": "done",
            "scene_statuses": {
                scene_key: {
                    "image_url": None,
                    "local_path": artifact.path,
                    "status": "ready",
                    "scene_id": artifact.scene_id,
                }
            },
        }
    if port_type == "audio_file":
        return {**base, "path": artifact.path, "duration_s": None}
    if port_type == "music_track":
        return {**base, "path": artifact.path, "title": name}
    if port_type in {"animation_assets", "video_file"}:
        return {
            **base,
            "total": 1,
            "ready": 1,
            "errors": 0,
            "status": "done",
            "path": artifact.path,
        }
    if port_type == "editor_project":
        return {**base, "project_id": None, "path": artifact.path}
    # Generic file-backed envelope.
    return {**base, "path": artifact.path}


def materialize_artifact(
    artifact: Artifact | str,
    *,
    port_type: str | None = None,
) -> Any:
    """Turn an indexed Artifact into a port payload.

    JSON documents are loaded and stamped with identity. Binary media becomes
    a typed envelope with ``artifact_refs`` / ``artifact_ids``.
    """
    if isinstance(artifact, str):
        try:
            artifact = get_artifact(artifact)
        except ArtifactNotFound as exc:
            raise InputSourceError(
                "ARTIFACT_NOT_FOUND",
                f"Artifact {artifact} not found",
                details={"artifact_id": artifact},
            ) from exc
        except ArtifactValidationError as exc:
            raise InputSourceError(
                "ARTIFACT_INVALID",
                "Artifact document failed validation",
                details={"problems": exc.problems},
            ) from exc

    resolved_port = port_type or KIND_TO_PORT_TYPE.get(artifact.kind)
    if not resolved_port:
        raise InputSourceError(
            "BAD_REQUEST",
            f"No default port type for artifact kind {artifact.kind}",
            details={"kind": artifact.kind},
        )

    try:
        abs_path = absolute_path(artifact)
    except ArtifactValidationError as exc:
        raise InputSourceError(
            "ARTIFACT_UNMANAGED",
            "Artifact path is outside the managed output root",
            details={"path": artifact.path},
        ) from exc

    if not os.path.isfile(abs_path) or os.path.getsize(abs_path) <= 0:
        raise InputSourceError(
            "ARTIFACT_MISSING",
            f"Artifact file missing or empty: {artifact.path}",
            details={"path": artifact.path, "artifact_id": artifact.id},
        )

    if _is_json_path(artifact.path, artifact.mime):
        try:
            loaded = _load_json_file(abs_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise InputSourceError(
                "ARTIFACT_INVALID",
                f"Could not parse artifact JSON: {artifact.path}",
                details={"path": artifact.path},
            ) from exc
        # Script port may be stored as {"text": "..."} or a bare string file.
        if resolved_port in {"script", "text"} and isinstance(loaded, Mapping):
            if "text" in loaded and isinstance(loaded["text"], str):
                return loaded["text"]
        if resolved_port == "script" and isinstance(loaded, str):
            return loaded
        return _with_source_identity(loaded, artifact)

    return _media_envelope(artifact, port_type=resolved_port)


def _resolve_artifact_id(artifact_id: str) -> Artifact:
    if not isinstance(artifact_id, str) or not ARTIFACT_ID_RE.fullmatch(artifact_id.strip()):
        raise InputSourceError(
            "BAD_REQUEST",
            "artifact_id must match art_[A-Z0-9]{6}",
            details={"artifact_id": artifact_id},
        )
    try:
        return get_artifact(artifact_id.strip())
    except ArtifactNotFound as exc:
        raise InputSourceError(
            "ARTIFACT_NOT_FOUND",
            f"Artifact {artifact_id} not found",
            details={"artifact_id": artifact_id},
        ) from exc
    except ArtifactSuperseded as exc:
        raise InputSourceError(
            "ARTIFACT_SUPERSEDED",
            str(exc),
            details={
                "artifact_id": exc.artifact_id,
                "superseded_by": exc.superseded_by,
            },
        ) from exc
    except ArtifactValidationError as exc:
        raise InputSourceError(
            "ARTIFACT_INVALID",
            "Artifact document failed validation",
            details={"problems": exc.problems},
        ) from exc


def _resolve_from_job(
    *,
    job_id: str,
    kind: str,
    scene_id: str | None,
    artifact_id: str | None,
    port_type: str | None,
) -> tuple[Any, list[str]]:
    if artifact_id:
        artifact = _resolve_artifact_id(artifact_id)
        if artifact.job_id != job_id:
            raise InputSourceError(
                "BAD_REQUEST",
                f"Artifact {artifact.id} belongs to job {artifact.job_id}, not {job_id}",
                details={
                    "artifact_id": artifact.id,
                    "artifact_job_id": artifact.job_id,
                    "expected_job_id": job_id,
                },
            )
        payload = materialize_artifact(artifact, port_type=port_type)
        return payload, [artifact.id]

    if kind not in ARTIFACT_KINDS:
        raise InputSourceError(
            "BAD_REQUEST",
            f"kind must be one of: {', '.join(ARTIFACT_KINDS)}",
            details={"kind": kind},
        )
    artifact = active_artifact(job_id, kind, scene_id=scene_id)
    if artifact is None:
        raise InputSourceError(
            "ARTIFACT_NOT_FOUND",
            f"No active {kind} artifact for job {job_id}"
            + (f" scene {scene_id}" if scene_id else ""),
            details={"job_id": job_id, "kind": kind, "scene_id": scene_id},
        )
    payload = materialize_artifact(artifact, port_type=port_type)
    return payload, [artifact.id]


def resolve_binding(
    binding: Mapping[str, Any] | None,
    *,
    port_type: str | None = None,
    current_job_id: str | None = None,
) -> tuple[Any, list[str]]:
    """Resolve one port binding to ``(payload, source_artifact_ids)``.

    Raises ``InputSourceError`` with a stable ``code`` on failure. ``run_deps``
    raises ``InputSourceError(code="RUN_DEPS")`` so the caller can switch modes
    rather than synthesizing a payload.
    """
    data = _as_mapping(binding)
    source = _optional_str(data.get("source"))
    if source not in INPUT_SOURCES:
        raise InputSourceError(
            "BAD_REQUEST",
            f"source must be one of: {', '.join(INPUT_SOURCES)}",
            details={"source": source},
        )

    if source == "run_deps":
        raise InputSourceError(
            "RUN_DEPS",
            "run_deps is not a payload source — use run_mode node_with_deps",
            details={"source": "run_deps"},
        )

    if source == "manual":
        if "value" not in data:
            raise InputSourceError(
                "BAD_REQUEST",
                "manual source requires a value",
            )
        value = data["value"]
        # Manual values may still name artifacts by id/ref for bookkeeping.
        ids: list[str] = []
        if isinstance(value, Mapping):
            ids = list(value.get("artifact_ids") or [])
            ids.extend(item.id for item in resolve_many(value.get("artifact_refs") or []))
            ids = list(dict.fromkeys(ids))
            if ids and "artifact_ids" not in value:
                value = dict(value)
                value["artifact_ids"] = ids
        return value, ids

    if source == "sample":
        sample_type = _optional_str(data.get("port_type")) or port_type
        if not sample_type:
            raise InputSourceError(
                "BAD_REQUEST",
                "sample source requires port_type",
            )
        try:
            payload = sample_payload(sample_type)
        except Exception as exc:
            raise InputSourceError(
                "SAMPLE_FIXTURE_MISSING",
                f"No sample payload for port type {sample_type}",
                details={"port_type": sample_type},
            ) from exc
        return deepcopy(payload), []

    # library / upload / job / current_job — artifact-backed.
    artifact_id = _optional_str(data.get("artifact_id"))
    job_id = _optional_str(data.get("job_id"))
    scene_id = _optional_str(data.get("scene_id"))
    kind = _optional_str(data.get("kind"))
    if not kind and port_type:
        kind = PORT_TYPE_TO_KIND.get(port_type)

    if source in {"library", "upload"}:
        if not artifact_id:
            raise InputSourceError(
                "BAD_REQUEST",
                f"{source} source requires artifact_id",
            )
        artifact = _resolve_artifact_id(artifact_id)
        payload = materialize_artifact(artifact, port_type=port_type)
        return payload, [artifact.id]

    if source == "current_job":
        resolved_job = job_id or current_job_id
        if not resolved_job:
            raise InputSourceError(
                "BAD_REQUEST",
                "current_job source requires job_id or current_job_id context",
            )
        if not kind and not artifact_id:
            raise InputSourceError(
                "BAD_REQUEST",
                "current_job source requires kind or artifact_id",
            )
        return _resolve_from_job(
            job_id=resolved_job,
            kind=kind or "",
            scene_id=scene_id,
            artifact_id=artifact_id,
            port_type=port_type,
        )

    if source == "job":
        if not job_id:
            raise InputSourceError(
                "BAD_REQUEST",
                "job source requires job_id",
            )
        if not kind and not artifact_id:
            raise InputSourceError(
                "BAD_REQUEST",
                "job source requires kind or artifact_id",
            )
        return _resolve_from_job(
            job_id=job_id,
            kind=kind or "",
            scene_id=scene_id,
            artifact_id=artifact_id,
            port_type=port_type,
        )

    raise InputSourceError("BAD_REQUEST", f"Unhandled source: {source}")


def resolve_input_bindings(
    bindings: Mapping[str, Mapping[str, Any]] | None,
    *,
    current_job_id: str | None = None,
    port_types: Mapping[tuple[str, str], str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], list[str]]:
    """Resolve ``{node_id: {port_id: binding}}`` to overrides and source ids.

    Returns
    -------
    (input_overrides, source_artifact_ids_by_node, sample_fed_node_ids)
        ``sample_fed_node_ids`` lists nodes that received at least one
        ``source: "sample"`` binding so the scheduler can stamp
        ``from_sample_data`` (step 4.2 — stub/sample-derived output is never
        mistaken for real output).
    """
    if bindings is None:
        return {}, {}, []
    if not isinstance(bindings, Mapping):
        raise InputSourceError("BAD_REQUEST", "input_bindings must be an object")

    overrides: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}
    sample_fed: list[str] = []
    type_map = port_types or {}

    for node_id, ports in bindings.items():
        if not isinstance(ports, Mapping):
            raise InputSourceError(
                "BAD_REQUEST",
                f"input_bindings[{node_id}] must be an object",
            )
        node_key = str(node_id)
        overrides[node_key] = {}
        collected: list[str] = []
        node_sample = False
        for port_id, binding in ports.items():
            port_key = str(port_id)
            port_type = type_map.get((node_key, port_key))
            if port_type is None and isinstance(binding, Mapping):
                port_type = _optional_str(binding.get("port_type"))
            if (
                isinstance(binding, Mapping)
                and _optional_str(binding.get("source")) == "sample"
            ):
                node_sample = True
            payload, ids = resolve_binding(
                binding,
                port_type=port_type,
                current_job_id=current_job_id,
            )
            overrides[node_key][port_key] = payload
            collected.extend(ids)
        sources[node_key] = list(dict.fromkeys(collected))
        if node_sample:
            sample_fed.append(node_key)

    return overrides, sources, list(dict.fromkeys(sample_fed))


def source_artifact_ids_from_inputs(inputs: Mapping[str, Any] | None) -> list[str]:
    """Collect artifact ids already stamped on resolved input payloads."""
    if not isinstance(inputs, Mapping):
        return []
    ids: list[str] = []
    for value in inputs.values():
        if isinstance(value, Mapping):
            for item in value.get("artifact_ids") or []:
                if isinstance(item, str) and item:
                    ids.append(item)
            ids.extend(item.id for item in resolve_many(value.get("artifact_refs") or []))
            # Nested single ref fields.
            for key in ("artifact_id", "id"):
                candidate = value.get(key)
                if isinstance(candidate, str) and ARTIFACT_ID_RE.fullmatch(candidate):
                    ids.append(candidate)
    return list(dict.fromkeys(ids))


def port_types_for_workflow(
    workflow: Mapping[str, Any],
) -> dict[tuple[str, str], str]:
    """Map ``(node_id, port_id) → port type`` from the registry."""
    from scriptase.engine.registry import get_node_type

    result: dict[tuple[str, str], str] = {}
    for node in workflow.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str):
            continue
        definition = get_node_type(node.get("type")) or {}
        for port in definition.get("inputs") or []:
            port_id = port.get("id")
            port_type = port.get("type")
            if port_type == "dynamic":
                port_type = (node.get("configuration") or {}).get("port_type")
            if isinstance(port_id, str) and isinstance(port_type, str):
                result[(node_id, port_id)] = port_type
    return result


def artifact_summary(artifact: Artifact) -> dict[str, Any]:
    """Public list/detail shape — no absolute paths, no secrets."""
    generation = None
    if artifact.generation is not None:
        generation = (
            artifact.generation.to_document()
            if hasattr(artifact.generation, "to_document")
            else dict(artifact.generation)
        )
    return {
        "id": artifact.id,
        "job_id": artifact.job_id,
        "scene_id": artifact.scene_id,
        "kind": artifact.kind,
        "version": artifact.version,
        "content_hash": artifact.content_hash,
        "path": artifact.path,
        "size_bytes": artifact.size_bytes,
        "mime": artifact.mime,
        "provenance_ref": artifact.provenance_ref,
        "generation": generation,
        "created_at": artifact.created_at,
        "superseded_by": artifact.superseded_by,
        "from_sample_data": artifact.from_sample_data,
        "is_superseded": artifact.is_superseded,
    }


__all__ = [
    "LIBRARY_JOB_ID",
    "INPUT_SOURCES",
    "PORT_TYPE_TO_KIND",
    "KIND_TO_PORT_TYPE",
    "InputSourceError",
    "materialize_artifact",
    "resolve_binding",
    "resolve_input_bindings",
    "source_artifact_ids_from_inputs",
    "port_types_for_workflow",
    "artifact_summary",
]
