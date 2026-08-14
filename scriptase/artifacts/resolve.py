"""Artifact resolver — relative refs keep working; identity comes for free.

Adapters continue to emit ``artifact_refs: [relpaths]`` (contracts.md §1.1).
This module maps those refs (and ``art_`` ids) onto the typed Artifact index
without requiring adapters to know about the store.

Lookup order for a single ref:

1. Exact ``art_XXXXXX`` id → index record.
2. Managed relative path → newest index record with that ``path``.
3. Unregistered path → ``None`` (adapters still resolve files via
   ``scriptase.providers.results.resolve_ref`` / engine helpers).
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.artifacts.models import ARTIFACT_ID_RE, Artifact, normalize_managed_path
from scriptase.artifacts.store import (
    ArtifactNotFound,
    ArtifactValidationError,
    get_artifact,
    list_artifacts,
)


def resolve_ref(ref: str) -> Artifact | None:
    """Resolve a relative path or artifact id to an Artifact, or None."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    text = ref.strip().replace("\\", "/")

    if ARTIFACT_ID_RE.fullmatch(text):
        try:
            return get_artifact(text)
        except (ArtifactNotFound, ArtifactValidationError, ValueError, OSError):
            return None

    try:
        path = normalize_managed_path(text)
    except ValueError:
        return None

    # Newest first from list_artifacts; prefer the active (non-superseded) tip
    # when multiple versions share a path (overwrite-in-place case).
    matches = [
        item
        for item in list_artifacts(include_superseded=True, limit=500)
        if item.path == path
    ]
    if not matches:
        return None
    active = [item for item in matches if item.superseded_by is None]
    if active:
        active.sort(key=lambda item: item.version, reverse=True)
        return active[0]
    matches.sort(key=lambda item: item.version, reverse=True)
    return matches[0]


def resolve_many(refs: list[str] | tuple[str, ...] | None) -> list[Artifact]:
    """Resolve a list of refs; skips unknowns. Order follows input."""
    results: list[Artifact] = []
    seen: set[str] = set()
    for ref in refs or ():
        artifact = resolve_ref(ref)
        if artifact is None or artifact.id in seen:
            continue
        seen.add(artifact.id)
        results.append(artifact)
    return results


def artifact_ids_for_payload(payload: Mapping[str, Any] | None) -> list[str]:
    """Collect artifact ids for every ``artifact_refs`` entry that is indexed."""
    if not isinstance(payload, Mapping):
        return []
    refs = payload.get("artifact_refs")
    if not isinstance(refs, list):
        return []
    return [item.id for item in resolve_many(refs)]


def with_artifact_ids(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` with ``artifact_ids`` filled from the index.

    Existing ``artifact_refs`` are left untouched so adapters and the engine
    cache keep working. Unknown refs simply produce no id.
    """
    result = dict(payload)
    ids = artifact_ids_for_payload(result)
    if ids:
        result["artifact_ids"] = ids
    return result


def extract_refs(value: Any) -> list[str]:
    """Walk a nested payload and collect ``artifact_refs`` (order-stable)."""
    refs: list[str] = []
    if isinstance(value, Mapping):
        candidates = value.get("artifact_refs")
        if isinstance(candidates, list):
            refs.extend(item for item in candidates if isinstance(item, str))
        for child in value.values():
            refs.extend(extract_refs(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            refs.extend(extract_refs(child))
    # Dedupe, preserve order.
    return list(dict.fromkeys(refs))


__all__ = [
    "resolve_ref",
    "resolve_many",
    "artifact_ids_for_payload",
    "with_artifact_ids",
    "extract_refs",
]
