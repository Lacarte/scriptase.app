"""Generation reproducibility snapshot attached to an Artifact (step 4.3).

Side-by-side attempt comparison needs the resolved provider instance, seed, and
prompt revision for each immutable version. Full Provenance (contracts.md §2)
is richer; this compact block is the comparison surface stored with the
artifact index so prior versions stay comparable after the execution is gone.

``prompt_revision`` is the product term used in the History UI; when only a
provider ``model_revision`` is known it is copied across so both axes are
populated without inventing values.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_seed(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class GenerationSnapshot(BaseModel):
    """Immutable generation metadata recorded when an artifact version is born."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = ""
    provider_instance_id: str = ""
    seed: int | None = None
    # Product comparison axis (step 4.3 done-when). Often mirrors model_revision.
    prompt_revision: str = ""
    model_revision: str = ""
    request_id: str = ""
    invocation_id: str = ""
    selection_reason: str = ""

    @field_validator(
        "provider_id",
        "provider_instance_id",
        "prompt_revision",
        "model_revision",
        "request_id",
        "invocation_id",
        "selection_reason",
        mode="before",
    )
    @classmethod
    def _str_fields(cls, value: Any) -> str:
        return _strip_str(value)

    @field_validator("seed", mode="before")
    @classmethod
    def _seed(cls, value: Any) -> int | None:
        return _coerce_seed(value)

    def is_empty(self) -> bool:
        return not any(
            (
                self.provider_id,
                self.provider_instance_id,
                self.seed is not None,
                self.prompt_revision,
                self.model_revision,
                self.request_id,
                self.invocation_id,
                self.selection_reason,
            )
        )

    def comparison_axes(self) -> dict[str, Any]:
        """The three fields the History comparison UI always shows."""
        return {
            "provider_instance_id": self.provider_instance_id or None,
            "seed": self.seed,
            "prompt_revision": self.prompt_revision or None,
        }

    def to_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def normalize_generation(value: Any) -> GenerationSnapshot | None:
    """Coerce a mapping / Provenance-like object into a GenerationSnapshot.

    Returns ``None`` for empty / missing input so Artifact can store null.
    Never invents seed or revision values.
    """
    if value is None:
        return None
    if isinstance(value, GenerationSnapshot):
        return None if value.is_empty() else value

    data: dict[str, Any]
    if isinstance(value, Mapping):
        data = dict(value)
    elif hasattr(value, "to_dict") and callable(value.to_dict):
        data = dict(value.to_dict())
    else:
        return None

    # Accept common aliases from result envelopes and unit overrides.
    provider_instance_id = (
        data.get("provider_instance_id")
        or data.get("instance_id")
        or ""
    )
    model_revision = data.get("model_revision") or data.get("model") or ""
    prompt_revision = data.get("prompt_revision") or ""
    if not prompt_revision and model_revision:
        prompt_revision = model_revision

    try:
        snapshot = GenerationSnapshot(
            provider_id=_strip_str(data.get("provider_id")),
            provider_instance_id=_strip_str(provider_instance_id),
            seed=_coerce_seed(data.get("seed")),
            prompt_revision=_strip_str(prompt_revision),
            model_revision=_strip_str(model_revision),
            request_id=_strip_str(data.get("request_id")),
            invocation_id=_strip_str(data.get("invocation_id")),
            selection_reason=_strip_str(data.get("selection_reason")),
        )
    except Exception:
        return None
    return None if snapshot.is_empty() else snapshot


def generation_from_provenance(provenance: Any) -> GenerationSnapshot | None:
    """Lift a contracts.md §2 Provenance (or dict) into a generation snapshot."""
    return normalize_generation(provenance)


__all__ = [
    "GenerationSnapshot",
    "normalize_generation",
    "generation_from_provenance",
]
