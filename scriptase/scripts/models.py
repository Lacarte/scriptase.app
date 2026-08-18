"""First-class Script Studio document models (implementation plan 3.1)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scriptase.artifacts.models import ARTIFACT_ID_RE
from scriptase.channels.models import CHANNEL_ID_RE
from scriptase.modules.script.prompts import WORDS_PER_SECOND


SCRIPT_ID_RE = re.compile(r"^scr_[A-Z0-9]{6}$")
SCRIPT_SCHEMA_VERSION = 1
SCRIPT_ORIGINS = ("auto", "paste", "idea", "manual")
NARRATION_STATES = ("none", "generating", "ready")

ScriptOrigin = Literal["auto", "paste", "idea", "manual"]
NarrationState = Literal["none", "generating", "ready"]


def _strip(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _optional(value: Any) -> str | None:
    text = _strip(value)
    return text or None


def script_metrics(body: str) -> tuple[int, int]:
    """Return the canonical ``(word_count, estimated_duration_s)`` pair."""
    word_count = len(body.split())
    duration = round(word_count / WORDS_PER_SECOND) if word_count else 0
    return word_count, duration


class Narration(BaseModel):
    """Narration lifecycle and its reference into the shared artifact store."""

    model_config = ConfigDict(extra="forbid")

    state: NarrationState = "none"
    voice: str = ""
    duration_s: float | None = Field(default=None, ge=0)
    audio_artifact_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_reference_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        if "duration_s" not in result and "duration" in result:
            result["duration_s"] = result.pop("duration")
        if "audio_artifact_id" not in result:
            for alias in ("audio_artifact_ref", "artifact_id"):
                if alias in result:
                    result["audio_artifact_id"] = result.pop(alias)
                    break
        return result

    @field_validator("state", mode="before")
    @classmethod
    def _state(cls, value: Any) -> str:
        text = _strip(value) or "none"
        if text not in NARRATION_STATES:
            raise ValueError(f"state must be one of: {', '.join(NARRATION_STATES)}")
        return text

    @field_validator("voice", mode="before")
    @classmethod
    def _voice(cls, value: Any) -> str:
        return _strip(value)

    @field_validator("audio_artifact_id", mode="before")
    @classmethod
    def _artifact_id(cls, value: Any) -> str | None:
        text = _optional(value)
        if text is not None and not ARTIFACT_ID_RE.fullmatch(text):
            raise ValueError("audio_artifact_id must match art_[A-Z0-9]{6}")
        return text

    @model_validator(mode="after")
    def _ready_has_audio(self) -> Narration:
        if self.state == "ready" and self.audio_artifact_id is None:
            raise ValueError("ready narration requires audio_artifact_id")
        return self

    @property
    def duration(self) -> float | None:
        """Plan-language alias retained for service callers."""
        return self.duration_s

    @property
    def audio_artifact_ref(self) -> str | None:
        return self.audio_artifact_id


class ScriptDraft(BaseModel):
    """Client-authored fields; identity, dates and metrics are server-owned."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    channel_id: str
    origin: ScriptOrigin = "manual"
    narration: Narration = Field(default_factory=Narration)

    @model_validator(mode="before")
    @classmethod
    def _accept_channel_alias(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        if "channel_id" not in result and "channel" in result:
            result["channel_id"] = result.pop("channel")
        return result

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, value: Any) -> str:
        text = _strip(value)
        if not text:
            raise ValueError("title is required")
        return text

    @field_validator("body", mode="before")
    @classmethod
    def _body(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("channel_id", mode="before")
    @classmethod
    def _channel_id(cls, value: Any) -> str:
        text = _strip(value)
        if not CHANNEL_ID_RE.fullmatch(text):
            raise ValueError("channel_id must match ch_[A-Z0-9]{6}")
        return text

    @field_validator("origin", mode="before")
    @classmethod
    def _origin(cls, value: Any) -> str:
        text = _strip(value) or "manual"
        if text not in SCRIPT_ORIGINS:
            raise ValueError(f"origin must be one of: {', '.join(SCRIPT_ORIGINS)}")
        return text

    @property
    def channel(self) -> str:
        return self.channel_id


class StudioScript(ScriptDraft):
    """Persisted, versioned Script Studio document."""

    id: str
    version: int = Field(default=1, ge=1)
    schema_version: int = Field(default=SCRIPT_SCHEMA_VERSION, ge=1)
    created_at: str
    updated_at: str
    word_count: int = Field(ge=0)
    estimated_duration_s: int = Field(ge=0)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not SCRIPT_ID_RE.fullmatch(value):
            raise ValueError("id must match scr_[A-Z0-9]{6}")
        return value

    @model_validator(mode="after")
    def _metrics_match_body(self) -> StudioScript:
        expected = script_metrics(self.body)
        if (self.word_count, self.estimated_duration_s) != expected:
            raise ValueError("word_count and estimated_duration_s must match body")
        return self

    @property
    def estimated_duration(self) -> int:
        return self.estimated_duration_s

    def to_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def parse_script(data: dict[str, Any]) -> StudioScript:
    return StudioScript.model_validate(data)


def parse_draft(data: dict[str, Any]) -> ScriptDraft:
    return ScriptDraft.model_validate(data)


def validation_problems(exc: Exception) -> list[dict[str, Any]]:
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
    "SCRIPT_ID_RE", "SCRIPT_SCHEMA_VERSION", "SCRIPT_ORIGINS",
    "NARRATION_STATES", "Narration", "ScriptDraft", "StudioScript",
    "script_metrics", "parse_script", "parse_draft", "validation_problems",
]
