"""ChannelProfile Pydantic models — contracts.md §5 / product §15.1.

A Channel is reusable identity and production rules for a content brand. It
lives *above* Jobs and is never a processing node.

``visual_direction.pattern`` is a structured ordered list of
``{narrative_role, shot}`` entries — never free text. That is what makes Scene
Director deterministic and a Channel genuinely reusable.

``provider_defaults`` and ``fallback_policies`` hold provider **instance ids**
only. Credentials never appear on a Channel document.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Server-generated channel id: ch_ + 6 uppercase alphanumerics (matches
# workflow/execution id style in contracts.md §1.4).
CHANNEL_ID_RE = re.compile(r"^ch_[A-Z0-9]{6}$")

# Schema version of the on-disk document format (migrations.py). Distinct from
# the content ``version`` field, which bumps on every successful update.
CHANNEL_SCHEMA_VERSION = 1

# Domains that may appear in provider_defaults / fallback_policies keys.
PROVIDER_DEFAULT_DOMAINS = (
    "script",
    "tts",
    "scene_director",
    "image",
    "video",
    "review",
)


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: Any) -> str | None:
    text = _strip_str(value)
    return text or None


# ---------------------------------------------------------------------------
# Nested blocks
# ---------------------------------------------------------------------------


class Branding(BaseModel):
    """Logo and on-screen brand treatment. Paths are managed asset ids only."""

    model_config = ConfigDict(extra="forbid")

    logo_asset_id: str | None = None
    enabled: bool = False
    position: str = "bottom-right"
    size: float = Field(default=0.12, ge=0.0, le=1.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    margin: float = Field(default=0.04, ge=0.0, le=0.5)

    @field_validator("logo_asset_id", mode="before")
    @classmethod
    def _logo(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("position", mode="before")
    @classmethod
    def _position(cls, value: Any) -> str:
        return _strip_str(value) or "bottom-right"


class Content(BaseModel):
    """Editorial identity: niche, audience, tone, duration targets."""

    model_config = ConfigDict(extra="forbid")

    niche: str = ""
    language: str = "en"
    audience: str = ""
    script_style: str = ""
    tone: str = ""
    mood: str = ""
    hook_style: str = ""
    cta_style: str = ""
    duration_target: int | None = Field(default=None, ge=1, le=600)

    @field_validator(
        "niche",
        "language",
        "audience",
        "script_style",
        "tone",
        "mood",
        "hook_style",
        "cta_style",
        mode="before",
    )
    @classmethod
    def _strip_fields(cls, value: Any) -> str:
        return _strip_str(value)


class PatternEntry(BaseModel):
    """One narrative-role → shot-direction mapping.

    Order in the parent list is significant (hook first, ending last). Free-text
    strings are rejected at the ``VisualDirection.pattern`` boundary — this is
    the structured form only.
    """

    model_config = ConfigDict(extra="forbid")

    narrative_role: str = Field(min_length=1)
    shot: str = Field(min_length=1)

    @field_validator("narrative_role", "shot", mode="before")
    @classmethod
    def _strip_required(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("must be a non-empty string")
        return text


class VisualDirection(BaseModel):
    """Style, structured pattern, palette, lighting, camera, continuity."""

    model_config = ConfigDict(extra="forbid")

    style: str = ""
    pattern: list[PatternEntry] = Field(default_factory=list)
    palette: str = ""
    lighting: str = ""
    camera: str = ""
    character_style: str = ""
    continuity: str = ""
    negative_prompt: str = ""
    references: list[str] = Field(default_factory=list)

    @field_validator(
        "style",
        "palette",
        "lighting",
        "camera",
        "character_style",
        "continuity",
        "negative_prompt",
        mode="before",
    )
    @classmethod
    def _strip_fields(cls, value: Any) -> str:
        return _strip_str(value)

    @field_validator("pattern", mode="before")
    @classmethod
    def _pattern_must_be_structured(cls, value: Any) -> Any:
        """Reject free-text pattern blocks with a structured error.

        Contracts require an ordered map of narrative role → shot direction,
        never one free-text field. A bare string (or other non-list) is the
        classic malformed input this gate exists to catch.
        """
        if value is None:
            return []
        if isinstance(value, str):
            raise ValueError(
                "pattern must be a list of {narrative_role, shot} objects, "
                "not free text"
            )
        if isinstance(value, dict):
            # Ordered map form: {role: shot, ...} — accept and normalize.
            return [
                {"narrative_role": role, "shot": shot}
                for role, shot in value.items()
            ]
        if not isinstance(value, list):
            raise ValueError(
                "pattern must be a list of {narrative_role, shot} objects"
            )
        return value

    @field_validator("references", mode="before")
    @classmethod
    def _refs(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("references must be a list of strings")
        return [_strip_str(item) for item in value if _strip_str(item)]


class AudioDefaults(BaseModel):
    """TTS / music defaults. Provider identity is an instance id, never a key."""

    model_config = ConfigDict(extra="forbid")

    tts_provider_instance_id: str | None = None
    voice: str = ""
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    music_profile: str = ""
    loudness: float | None = None
    ducking: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("tts_provider_instance_id", mode="before")
    @classmethod
    def _tts_id(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("voice", "music_profile", mode="before")
    @classmethod
    def _strip_fields(cls, value: Any) -> str:
        return _strip_str(value)


class CaptionsDefaults(BaseModel):
    """Caption presentation defaults. Captions are a local service, not a domain."""

    model_config = ConfigDict(extra="forbid")

    preset: str = ""
    position: str = ""
    font_treatment: str = ""
    animation: str = ""

    @field_validator("preset", "position", "font_treatment", "animation", mode="before")
    @classmethod
    def _strip_fields(cls, value: Any) -> str:
        return _strip_str(value)


class ProviderDefaults(BaseModel):
    """Default provider instance id per capable domain. No credentials."""

    model_config = ConfigDict(extra="forbid")

    script: str | None = None
    tts: str | None = None
    scene_director: str | None = None
    image: str | None = None
    video: str | None = None
    review: str | None = None

    @field_validator(*PROVIDER_DEFAULT_DOMAINS, mode="before")
    @classmethod
    def _instance_id(cls, value: Any) -> str | None:
        return _optional_str(value)


class FallbackPolicy(BaseModel):
    """Primary + ordered fallbacks for one stage. All values are instance ids."""

    model_config = ConfigDict(extra="forbid")

    primary: str | None = None
    fallbacks: list[str] = Field(default_factory=list)

    @field_validator("primary", mode="before")
    @classmethod
    def _primary(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("fallbacks", mode="before")
    @classmethod
    def _fallbacks(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("fallbacks must be a list of instance ids")
        return [_strip_str(item) for item in value if _strip_str(item)]


class ReviewPolicy(BaseModel):
    """Quality thresholds, repair budget, escalation, human checkpoints."""

    model_config = ConfigDict(extra="forbid")

    thresholds: dict[str, Any] = Field(default_factory=dict)
    max_repairs: int = Field(default=3, ge=0, le=50)
    escalation: str = ""
    human_checkpoints: list[str] = Field(default_factory=list)

    @field_validator("thresholds", mode="before")
    @classmethod
    def _thresholds(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("thresholds must be an object")
        return value

    @field_validator("escalation", mode="before")
    @classmethod
    def _escalation(cls, value: Any) -> str:
        return _strip_str(value)

    @field_validator("human_checkpoints", mode="before")
    @classmethod
    def _checkpoints(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("human_checkpoints must be a list of strings")
        return [_strip_str(item) for item in value if _strip_str(item)]


class Budget(BaseModel):
    """Optional generation / cost ceilings for Jobs created from this Channel."""

    model_config = ConfigDict(extra="forbid")

    max_generations: int | None = Field(default=None, ge=0)
    max_cost: float | None = Field(default=None, ge=0.0)
    currency: str = "USD"

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, value: Any) -> str:
        return _strip_str(value) or "USD"


class ExportDefaults(BaseModel):
    """Target delivery format."""

    model_config = ConfigDict(extra="forbid")

    aspect_ratio: str = "9:16"
    resolution: str = ""
    fps: int | None = Field(default=None, ge=1, le=120)
    profile: str = ""

    @field_validator("aspect_ratio", "resolution", "profile", mode="before")
    @classmethod
    def _strip_fields(cls, value: Any) -> str:
        text = _strip_str(value)
        return text


# ---------------------------------------------------------------------------
# Top-level document
# ---------------------------------------------------------------------------


class ChannelProfile(BaseModel):
    """Persisted Channel document (contracts.md §5).

    ``version`` is the content revision (starts at 1, bumps on update).
    ``schema_version`` is the on-disk format revision (migrations.py).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(default=1, ge=1)
    schema_version: int = Field(default=CHANNEL_SCHEMA_VERSION, ge=1)

    branding: Branding = Field(default_factory=Branding)
    content: Content = Field(default_factory=Content)
    visual_direction: VisualDirection = Field(default_factory=VisualDirection)
    audio_defaults: AudioDefaults = Field(default_factory=AudioDefaults)
    captions: CaptionsDefaults = Field(default_factory=CaptionsDefaults)
    provider_defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)
    fallback_policies: dict[str, FallbackPolicy] = Field(default_factory=dict)
    review_policy: ReviewPolicy = Field(default_factory=ReviewPolicy)
    budget: Budget = Field(default_factory=Budget)
    export_defaults: ExportDefaults = Field(default_factory=ExportDefaults)
    default_workflow_id: str | None = None

    created_at: str = ""
    updated_at: str = ""

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not CHANNEL_ID_RE.fullmatch(value):
            raise ValueError("id must match ch_[A-Z0-9]{6}")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("name is required")
        return text

    @field_validator("default_workflow_id", mode="before")
    @classmethod
    def _workflow_id(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("fallback_policies", mode="before")
    @classmethod
    def _fallback_policies(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("fallback_policies must be an object")
        return value

    @model_validator(mode="after")
    def _export_aspect_default(self) -> ChannelProfile:
        if not self.export_defaults.aspect_ratio:
            self.export_defaults.aspect_ratio = "9:16"
        return self

    def to_document(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for ``safe_json_write``."""
        return self.model_dump(mode="json")


class ChannelDraft(BaseModel):
    """Create/update payload: identity fields are owned by the store."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    branding: Branding = Field(default_factory=Branding)
    content: Content = Field(default_factory=Content)
    visual_direction: VisualDirection = Field(default_factory=VisualDirection)
    audio_defaults: AudioDefaults = Field(default_factory=AudioDefaults)
    captions: CaptionsDefaults = Field(default_factory=CaptionsDefaults)
    provider_defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)
    fallback_policies: dict[str, FallbackPolicy] = Field(default_factory=dict)
    review_policy: ReviewPolicy = Field(default_factory=ReviewPolicy)
    budget: Budget = Field(default_factory=Budget)
    export_defaults: ExportDefaults = Field(default_factory=ExportDefaults)
    default_workflow_id: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("name is required")
        return text

    @field_validator("default_workflow_id", mode="before")
    @classmethod
    def _workflow_id(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("fallback_policies", mode="before")
    @classmethod
    def _fallback_policies(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("fallback_policies must be an object")
        return value


def validation_problems(exc: Exception) -> list[dict[str, Any]]:
    """Turn a Pydantic ``ValidationError`` into structured problem dicts.

    Shape mirrors the shared request validator: ``loc``, ``msg``, ``type``.
    Callers that need a single error envelope attach these under ``details``.
    """
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return [{
            "loc": (),
            "msg": str(exc),
            "type": "value_error",
        }]
    return [
        {
            "loc": list(err.get("loc", ())),
            "msg": err.get("msg", "validation error"),
            "type": err.get("type", "value_error"),
        }
        for err in exc.errors(include_url=False, include_context=False)
    ]


def parse_channel(data: dict[str, Any]) -> ChannelProfile:
    """Validate a raw dict as a full ChannelProfile document."""
    return ChannelProfile.model_validate(data)


def parse_draft(data: dict[str, Any]) -> ChannelDraft:
    """Validate a create/update draft (no id / version / timestamps)."""
    # Drop store-owned keys so partial PUT bodies from a previous GET work.
    payload = {
        key: value
        for key, value in data.items()
        if key not in {"id", "version", "schema_version", "created_at", "updated_at"}
    }
    return ChannelDraft.model_validate(payload)


__all__ = [
    "CHANNEL_ID_RE",
    "CHANNEL_SCHEMA_VERSION",
    "PROVIDER_DEFAULT_DOMAINS",
    "Branding",
    "Content",
    "PatternEntry",
    "VisualDirection",
    "AudioDefaults",
    "CaptionsDefaults",
    "ProviderDefaults",
    "FallbackPolicy",
    "ReviewPolicy",
    "Budget",
    "ExportDefaults",
    "ChannelProfile",
    "ChannelDraft",
    "validation_problems",
    "parse_channel",
    "parse_draft",
]
