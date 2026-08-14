"""Artifact Pydantic model — contracts.md §3 / product §15.

Replaces V2's ``artifact_refs: list[str]`` naming convention with a real type:
stable id, kind, owning job, owning scene, version, content hash, relative
managed path, size, mime, provenance reference, and ``superseded_by``.

Records are immutable and additive. The only field that mutates after create is
``superseded_by``, set when a newer version of the same (job, scene, kind)
chain is registered. Files stay under the V2 per-module output layout; this
model is the index that records them.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scriptase.artifacts.generation import GenerationSnapshot, normalize_generation

# Server-generated artifact id: art_ + 6 uppercase alphanumerics
# (matches channel / workflow id style in contracts.md).
ARTIFACT_ID_RE = re.compile(r"^art_[A-Z0-9]{6}$")

# Schema version of the on-disk document format (migrations.py). Distinct from
# the content ``version`` field, which is 1-based and monotonic per
# (job_id, scene_id, kind) chain.
# v2 (step 4.3): optional ``generation`` snapshot for attempt comparison.
ARTIFACT_SCHEMA_VERSION = 2

# contracts.md §3 kind vocabulary.
ArtifactKind = Literal[
    "script",
    "audio",
    "alignment",
    "segments",
    "scene_spec",
    "image",
    "video",
    "captions",
    "music",
    "timeline",
    "export",
]

ARTIFACT_KINDS: tuple[str, ...] = (
    "script",
    "audio",
    "alignment",
    "segments",
    "scene_spec",
    "image",
    "video",
    "captions",
    "music",
    "timeline",
    "export",
)

# Absolute path shapes — never allowed on ``path``.
_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: Any) -> str | None:
    text = _strip_str(value)
    return text or None


def normalize_content_hash(value: Any) -> str:
    """Normalize a content hash to ``sha256:<64 hex lowercase>``."""
    text = _strip_str(value)
    if not text:
        raise ValueError("content_hash is required")
    if text.startswith("sha256:"):
        digest = text[7:]
    else:
        digest = text
    digest = digest.lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("content_hash must be a sha256 hex digest")
    return f"sha256:{digest}"


def normalize_managed_path(value: Any) -> str:
    """Normalize a managed relative path: forward slashes, no absolute, no ``..``."""
    text = _strip_str(value).replace("\\", "/")
    if not text:
        raise ValueError("path is required")
    if _ABSOLUTE_PATH_RE.match(text):
        raise ValueError("path must be relative to the managed output root")
    if text.startswith("./"):
        text = text[2:]
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts:
        raise ValueError("path is required")
    if any(part == ".." for part in parts):
        raise ValueError("path must not contain '..'")
    return "/".join(parts)


class Artifact(BaseModel):
    """Persisted artifact index record (contracts.md §3).

    ``version`` is 1-based and monotonic per (job_id, scene_id, kind).
    ``schema_version`` is the on-disk format revision (migrations.py).
    Records are immutable except for ``superseded_by``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: int = Field(default=ARTIFACT_SCHEMA_VERSION, ge=1)
    job_id: str = Field(min_length=1, max_length=120)
    scene_id: str | None = None
    kind: ArtifactKind
    version: int = Field(ge=1)
    content_hash: str
    path: str
    size_bytes: int = Field(ge=0)
    mime: str = "application/octet-stream"
    provenance_ref: str | None = None
    # Compact generation reproducibility for side-by-side attempt comparison
    # (step 4.3). Full Provenance remains referenced by provenance_ref when
    # present; this block is the durable comparison surface.
    generation: GenerationSnapshot | None = None
    created_at: str = ""
    superseded_by: str | None = None
    from_sample_data: bool = False

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not ARTIFACT_ID_RE.fullmatch(value):
            raise ValueError("id must match art_[A-Z0-9]{6}")
        return value

    @field_validator("generation", mode="before")
    @classmethod
    def _generation(cls, value: Any) -> GenerationSnapshot | None:
        return normalize_generation(value)

    @field_validator("job_id", mode="before")
    @classmethod
    def _job_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("job_id is required")
        return text

    @field_validator("scene_id", mode="before")
    @classmethod
    def _scene_id(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, value: Any) -> str:
        text = _strip_str(value)
        if text not in ARTIFACT_KINDS:
            raise ValueError(
                f"kind must be one of: {', '.join(ARTIFACT_KINDS)}"
            )
        return text

    @field_validator("content_hash", mode="before")
    @classmethod
    def _content_hash(cls, value: Any) -> str:
        return normalize_content_hash(value)

    @field_validator("path", mode="before")
    @classmethod
    def _path(cls, value: Any) -> str:
        return normalize_managed_path(value)

    @field_validator("mime", mode="before")
    @classmethod
    def _mime(cls, value: Any) -> str:
        text = _strip_str(value)
        return text or "application/octet-stream"

    @field_validator("provenance_ref", mode="before")
    @classmethod
    def _provenance_ref(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("superseded_by", mode="before")
    @classmethod
    def _superseded_by(cls, value: Any) -> str | None:
        text = _optional_str(value)
        if text is None:
            return None
        if not ARTIFACT_ID_RE.fullmatch(text):
            raise ValueError("superseded_by must match art_[A-Z0-9]{6}")
        return text

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by is not None

    @property
    def content_digest(self) -> str:
        """Bare 64-char hex digest (no ``sha256:`` prefix)."""
        return self.content_hash.removeprefix("sha256:")

    def to_document(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for ``safe_json_write``."""
        return self.model_dump(mode="json")


def parse_artifact(data: dict[str, Any]) -> Artifact:
    """Validate a full artifact document."""
    return Artifact.model_validate(data)


def validation_problems(exc: Exception) -> list[dict[str, Any]]:
    """Turn a Pydantic ``ValidationError`` into structured problem dicts."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return [
            {
                "loc": list(item.get("loc", ())),
                "msg": item.get("msg", "invalid"),
                "type": item.get("type", "value_error"),
            }
            for item in errors(include_url=False, include_context=False)
        ]
    return [{"loc": [], "msg": str(exc), "type": "value_error"}]


__all__ = [
    "ARTIFACT_ID_RE",
    "ARTIFACT_SCHEMA_VERSION",
    "ARTIFACT_KINDS",
    "ArtifactKind",
    "Artifact",
    "GenerationSnapshot",
    "normalize_content_hash",
    "normalize_generation",
    "normalize_managed_path",
    "parse_artifact",
    "validation_problems",
]
