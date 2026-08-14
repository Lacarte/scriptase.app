"""Per-node / per-chain attempt history and side-by-side comparison (step 4.3).

Surfaces 1.2's immutable artifact versions with the generation axes the product
needs: resolved provider instance, seed, and prompt revision. Comparison is a
pure function over two index records — it never mutates the chain.
"""

from __future__ import annotations

from typing import Any

from scriptase.artifacts.generation import GenerationSnapshot, normalize_generation
from scriptase.artifacts.input_sources import artifact_summary
from scriptase.artifacts.models import ARTIFACT_KINDS, Artifact
from scriptase.artifacts.store import (
    ArtifactNotFound,
    ArtifactValidationError,
    get_artifact,
    list_artifacts,
)


class HistoryError(RuntimeError):
    """History / comparison could not be built."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _generation_dict(artifact: Artifact) -> dict[str, Any] | None:
    gen = artifact.generation
    if gen is None:
        return None
    if isinstance(gen, GenerationSnapshot):
        return gen.to_document()
    normalized = normalize_generation(gen)
    return normalized.to_document() if normalized is not None else None


def attempt_entry(artifact: Artifact) -> dict[str, Any]:
    """One attempt row for the History UI / API."""
    generation = _generation_dict(artifact)
    axes = (
        GenerationSnapshot.model_validate(generation).comparison_axes()
        if generation
        else {
            "provider_instance_id": None,
            "seed": None,
            "prompt_revision": None,
        }
    )
    summary = artifact_summary(artifact)
    return {
        "artifact_id": artifact.id,
        "version": artifact.version,
        "kind": artifact.kind,
        "scene_id": artifact.scene_id,
        "job_id": artifact.job_id,
        "path": artifact.path,
        "content_hash": artifact.content_hash,
        "mime": artifact.mime,
        "size_bytes": artifact.size_bytes,
        "created_at": artifact.created_at,
        "superseded_by": artifact.superseded_by,
        "is_superseded": artifact.is_superseded,
        "from_sample_data": artifact.from_sample_data,
        "provenance_ref": artifact.provenance_ref,
        "generation": generation,
        "provider_instance_id": axes["provider_instance_id"],
        "seed": axes["seed"],
        "prompt_revision": axes["prompt_revision"],
        "artifact": summary,
    }


def list_version_chain(
    *,
    job_id: str,
    kind: str,
    scene_id: str | None = None,
) -> list[Artifact]:
    """Return every version of a (job, scene, kind) chain, oldest first.

    Includes superseded versions so a regenerate always keeps prior evidence
    visible for side-by-side comparison.
    """
    if not isinstance(job_id, str) or not job_id.strip():
        raise HistoryError("BAD_REQUEST", "job_id is required")
    kind_text = str(kind or "").strip()
    if kind_text not in ARTIFACT_KINDS:
        raise HistoryError(
            "BAD_REQUEST",
            f"kind must be one of: {', '.join(ARTIFACT_KINDS)}",
            details={"kind": kind_text},
        )
    job_id = job_id.strip()
    scene = scene_id.strip() if isinstance(scene_id, str) and scene_id.strip() else None

    items = list_artifacts(
        job_id=job_id,
        scene_id=scene,
        kind=kind_text,
        include_superseded=True,
        limit=500,
    )
    # list_artifacts with scene_id=None means any scene — filter exact match.
    exact = [
        item
        for item in items
        if item.job_id == job_id
        and item.kind == kind_text
        and item.scene_id == scene
    ]
    exact.sort(key=lambda item: (item.version, item.created_at or "", item.id))
    return exact


def history_for_artifact(artifact_id: str) -> dict[str, Any]:
    """Full version history for the chain that owns ``artifact_id``."""
    try:
        tip = get_artifact(artifact_id)
    except ArtifactNotFound as exc:
        raise HistoryError("ARTIFACT_NOT_FOUND", "Artifact not found") from exc
    except ArtifactValidationError as exc:
        raise HistoryError(
            "ARTIFACT_INVALID",
            "Artifact document failed validation",
            details={"problems": exc.problems},
        ) from exc

    chain = list_version_chain(
        job_id=tip.job_id,
        kind=tip.kind,
        scene_id=tip.scene_id,
    )
    attempts = [attempt_entry(item) for item in chain]
    active = next((a for a in reversed(attempts) if not a["is_superseded"]), None)
    # Default comparison pair: last two versions when a regenerate happened.
    compare = None
    if len(attempts) >= 2:
        compare = compare_attempts(attempts[-2]["artifact_id"], attempts[-1]["artifact_id"])

    return {
        "job_id": tip.job_id,
        "scene_id": tip.scene_id,
        "kind": tip.kind,
        "focus_artifact_id": tip.id,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "active": active,
        "comparison": compare,
    }


def history_for_chain(
    *,
    job_id: str,
    kind: str,
    scene_id: str | None = None,
) -> dict[str, Any]:
    """History for an explicit (job, scene, kind) chain without a focus id."""
    chain = list_version_chain(job_id=job_id, kind=kind, scene_id=scene_id)
    attempts = [attempt_entry(item) for item in chain]
    active = next((a for a in reversed(attempts) if not a["is_superseded"]), None)
    compare = None
    if len(attempts) >= 2:
        compare = compare_attempts(attempts[-2]["artifact_id"], attempts[-1]["artifact_id"])
    return {
        "job_id": job_id.strip(),
        "scene_id": scene_id.strip() if isinstance(scene_id, str) and scene_id.strip() else None,
        "kind": kind,
        "focus_artifact_id": active["artifact_id"] if active else None,
        "attempt_count": len(attempts),
        "attempts": attempts,
        "active": active,
        "comparison": compare,
    }


def compare_attempts(left_id: str, right_id: str) -> dict[str, Any]:
    """Side-by-side comparison of two artifact versions.

    Returns both attempt entries plus a field-level diff of the three
    comparison axes (provider_instance_id, seed, prompt_revision).
    """
    if not left_id or not right_id:
        raise HistoryError("BAD_REQUEST", "left and right artifact ids are required")
    if left_id == right_id:
        raise HistoryError(
            "BAD_REQUEST",
            "comparison requires two distinct artifact versions",
            details={"artifact_id": left_id},
        )
    try:
        left = get_artifact(left_id)
        right = get_artifact(right_id)
    except ArtifactNotFound as exc:
        raise HistoryError("ARTIFACT_NOT_FOUND", "Artifact not found") from exc
    except ArtifactValidationError as exc:
        raise HistoryError(
            "ARTIFACT_INVALID",
            "Artifact document failed validation",
            details={"problems": exc.problems},
        ) from exc

    left_entry = attempt_entry(left)
    right_entry = attempt_entry(right)

    # Prefer chronological left→right (older on the left).
    if (
        left.job_id == right.job_id
        and left.kind == right.kind
        and left.scene_id == right.scene_id
        and left.version > right.version
    ):
        left_entry, right_entry = right_entry, left_entry
        left, right = right, left

    axes = ("provider_instance_id", "seed", "prompt_revision")
    diff: dict[str, Any] = {}
    for axis in axes:
        lv = left_entry.get(axis)
        rv = right_entry.get(axis)
        diff[axis] = {
            "left": lv,
            "right": rv,
            "changed": lv != rv,
        }

    same_chain = (
        left.job_id == right.job_id
        and left.kind == right.kind
        and left.scene_id == right.scene_id
    )

    return {
        "left": left_entry,
        "right": right_entry,
        "same_chain": same_chain,
        "axes": diff,
        "changed_axes": [name for name, body in diff.items() if body["changed"]],
    }


__all__ = [
    "HistoryError",
    "attempt_entry",
    "list_version_chain",
    "history_for_artifact",
    "history_for_chain",
    "compare_attempts",
]
