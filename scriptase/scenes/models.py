"""Scene identity model — contracts.md §4 / product §15.

Scenes in V2 were array indices inside ``scenes.json``. Review and repair are
per-scene, and re-segmentation shifts every index — so identity must be a
stable ``scn_XXXXXX`` that survives boundary changes. Ordinal position is
presentation data only.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Server-generated scene id: scn_ + 6 uppercase alphanumerics
# (matches channel / job / artifact id style in contracts.md).
SCENE_ID_RE = re.compile(r"^scn_[A-Z0-9]{6}$")

# Schema version of the on-disk document format (migrations.py).
SCENE_SCHEMA_VERSION = 1


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: Any) -> str | None:
    text = _strip_str(value)
    return text or None


class Scene(BaseModel):
    """Persisted scene identity record (contracts.md §4).

    ``ordinal`` is presentation order only — never used as identity.
    ``superseded_by`` is set when re-segmentation replaces this scene.
    Records are immutable except for ``superseded_by`` and span fields that
    update in place on a rebind (same id, refreshed boundaries).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: int = Field(default=SCENE_SCHEMA_VERSION, ge=1)
    job_id: str = Field(min_length=1, max_length=120)
    ordinal: int = Field(ge=0)
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    duration: float = Field(ge=0.0)
    segment_words: str = ""
    superseded_by: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not SCENE_ID_RE.fullmatch(value):
            raise ValueError("id must match scn_[A-Z0-9]{6}")
        return value

    @field_validator("job_id", mode="before")
    @classmethod
    def _job_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("job_id is required")
        return text

    @field_validator("segment_words", mode="before")
    @classmethod
    def _segment_words(cls, value: Any) -> str:
        return _strip_str(value)

    @field_validator("superseded_by", mode="before")
    @classmethod
    def _superseded_by(cls, value: Any) -> str | None:
        text = _optional_str(value)
        if text is None:
            return None
        if not SCENE_ID_RE.fullmatch(text):
            raise ValueError("superseded_by must match scn_[A-Z0-9]{6}")
        return text

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _timestamps(cls, value: Any) -> str:
        return _strip_str(value)

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by is not None

    @property
    def is_active(self) -> bool:
        return self.superseded_by is None

    def to_document(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for ``safe_json_write``."""
        return self.model_dump(mode="json")


def parse_scene(data: dict[str, Any]) -> Scene:
    """Validate a full scene document."""
    return Scene.model_validate(data)


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
    "SCENE_ID_RE",
    "SCENE_SCHEMA_VERSION",
    "Scene",
    "parse_scene",
    "validation_problems",
]
