"""Script domain request and result models (contracts.md §32.1).

Filled into `DomainSpec.request_model` / `result_model` by step 13.1. Every
script provider — the offline `random_template` catalog, the AI generator, and
any future plugin — accepts and returns these shapes.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


SUPPORTED_LANGUAGES = ("english", "french", "spanish")
LANGUAGE_LEVELS = ("beginner", "intermediate", "advanced", "native")


class ScriptRequest(BaseModel):
    """Frozen §32.1 request. Unknown keys are rejected (not silently ignored)."""

    idea: str = Field(default="", max_length=4000)
    category: str = Field(default="", max_length=80)
    style: str = ""
    tone: str = ""
    language: str = "english"
    language_level: str = ""
    target_duration_s: int = Field(default=45, ge=15, le=180)
    niche_preset: str = ""
    seed: Optional[int] = None  # deterministic providers only (13.1)

    model_config = {"extra": "forbid"}

    @field_validator("idea", "category", "style", "tone", "language_level", "niche_preset", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("language", mode="before")
    @classmethod
    def _normalize_language(cls, value: Any) -> str:
        language = str(value or "english").strip().lower() or "english"
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language {language!r}; expected one of {SUPPORTED_LANGUAGES}"
            )
        return language

    @field_validator("language_level")
    @classmethod
    def _normalize_language_level(cls, value: str) -> str:
        if not value:
            return ""
        level = value.lower()
        if level not in LANGUAGE_LEVELS:
            raise ValueError(
                f"Unsupported language_level {level!r}; expected one of {LANGUAGE_LEVELS}"
            )
        return level

    @field_validator("seed", mode="before")
    @classmethod
    def _normalize_seed(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @classmethod
    def from_configuration(cls, configuration: Mapping[str, Any] | None) -> "ScriptRequest":
        """Map the adapter/legacy configuration keys onto the frozen request.

        Accepts both the node/legacy names (`story_category`, `preset_style`,
        `story_tone`, `duration`) and the §32.1 names so the same provider can
        be driven by the Story Generator node and by a direct v2 invocation.
        """
        data = dict(configuration or {})
        return cls(
            idea=data.get("idea") or "",
            category=data.get("category") or data.get("story_category") or "",
            style=data.get("style") or data.get("preset_style") or "",
            tone=data.get("tone") or data.get("story_tone") or "",
            language=data.get("language") or "english",
            language_level=data.get("language_level") or "",
            target_duration_s=data.get("target_duration_s")
            if data.get("target_duration_s") not in (None, "")
            else data.get("duration", 45),
            niche_preset=data.get("niche_preset") or "",
            seed=data.get("seed"),
        )


class ScriptResultPayload(BaseModel):
    """Frozen §32.1 result payload — the only shape a script provider returns."""

    script_text: str
    sections: dict[str, str] = Field(default_factory=dict)
    word_count: int
    estimated_duration_s: int
    language: str

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _require_non_empty_script(self) -> "ScriptResultPayload":
        if not (self.script_text or "").strip():
            raise ValueError("script_text must be non-empty")
        if self.word_count < 0:
            raise ValueError("word_count must be non-negative")
        if self.estimated_duration_s < 0:
            raise ValueError("estimated_duration_s must be non-negative")
        return self

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ScriptResultPayload":
        """Coerce a provider dict (or legacy `story_text` document) into the payload."""
        payload = dict(data or {})
        script_text = payload.get("script_text") or payload.get("story_text") or ""
        sections = payload.get("sections") or {}
        if not isinstance(sections, Mapping):
            sections = {}
        word_count = payload.get("word_count")
        if word_count is None and isinstance(payload.get("metadata"), Mapping):
            word_count = payload["metadata"].get("word_count")
        if word_count is None:
            word_count = len(str(script_text).split())
        estimated = payload.get("estimated_duration_s")
        if estimated is None and isinstance(payload.get("metadata"), Mapping):
            estimated = payload["metadata"].get("estimated_duration")
        if estimated is None:
            estimated = 0
        language = payload.get("language")
        if not language and isinstance(payload.get("metadata"), Mapping):
            language = payload["metadata"].get("language")
        return cls(
            script_text=str(script_text),
            sections={str(k): str(v) for k, v in sections.items()},
            word_count=int(word_count or 0),
            estimated_duration_s=int(estimated or 0),
            language=str(language or "english"),
        )


__all__ = [
    "SUPPORTED_LANGUAGES",
    "LANGUAGE_LEVELS",
    "ScriptRequest",
    "ScriptResultPayload",
]
