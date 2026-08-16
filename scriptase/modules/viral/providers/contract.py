"""Viral domain request and result models (step 16.2 / contracts.md §9).

Every virality provider — the offline ``deterministic`` scorer and any future
LLM judge — accepts and returns these shapes.

The result is deliberately **not** a new schema. Step 16.1 froze
:class:`~scriptase.modules.viral.models.ViralScore` as the thing the node emits
and the Script panel renders, precisely so the arithmetic behind it can be
replaced without a contract change. Wrapping it here in a second, structurally
identical model would create exactly the drift that decision was meant to
prevent, so ``ViralResultPayload`` is that model.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, Field, field_validator

from scriptase.modules.viral.models import ViralScore
from scriptase.modules.viral.service import DEFAULT_TARGET_DURATION

# The mandated section vocabulary (16.1). Anything else in a `sections` map is
# dropped rather than scored, because a scorer that silently invents a seventh
# section produces a number nobody can reproduce.
SECTION_KEYS: tuple[str, ...] = ("hook", "build", "climax", "cta")

_TEXT_MAX = 50_000
_MIN_DURATION = 5
_MAX_DURATION = 600


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class ViralRequest(BaseModel):
    """Frozen virality request. Unknown keys are rejected, not ignored."""

    model_config = {"extra": "forbid"}

    job_id: str = Field(min_length=1, max_length=120)

    # Either is enough; supplying both scores the most (16.1).
    sections: dict[str, str] = Field(default_factory=dict)
    story_text: str = ""

    # What the script was *written to*, which is what pacing is judged against.
    target_duration: int = Field(
        default=DEFAULT_TARGET_DURATION, ge=_MIN_DURATION, le=_MAX_DURATION
    )

    # Ordered Scene Director roles when scenes already exist. Sharpens hook
    # position; ignored when absent.
    narrative_roles: list[str] = Field(default_factory=list)

    @field_validator("job_id", mode="before")
    @classmethod
    def _job_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("job_id is required")
        return text

    @field_validator("sections", mode="before")
    @classmethod
    def _sections(cls, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("sections must be an object")
        return {
            key: _strip_str(value.get(key))[:_TEXT_MAX]
            for key in SECTION_KEYS
            if _strip_str(value.get(key))
        }

    @field_validator("story_text", mode="before")
    @classmethod
    def _story_text(cls, value: Any) -> str:
        return _strip_str(value)[:_TEXT_MAX]

    @field_validator("target_duration", mode="before")
    @classmethod
    def _target_duration(cls, value: Any) -> int:
        if value in (None, ""):
            return DEFAULT_TARGET_DURATION
        try:
            seconds = int(float(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("target_duration must be a number of seconds") from exc
        # Clamp rather than reject: a Channel or story document asking for a
        # 900-second script is a scoring input, not a validation failure.
        return max(_MIN_DURATION, min(_MAX_DURATION, seconds))

    @field_validator("narrative_roles", mode="before")
    @classmethod
    def _narrative_roles(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = _strip_str(value)
            return [text] if text else []
        if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
            raise ValueError("narrative_roles must be a list of strings")
        return [_strip_str(item) for item in value if _strip_str(item)]

    @classmethod
    def from_configuration(cls, configuration: Mapping[str, Any] | None) -> "ViralRequest":
        """Map adapter / node configuration keys onto the frozen request."""
        data = dict(configuration or {})
        return cls(
            job_id=data.get("job_id") or data.get("project_id") or "job_UNKNOWN",
            sections=data.get("sections") or {},
            story_text=(
                data.get("story_text")
                or data.get("script")
                or data.get("text")
                or ""
            ),
            target_duration=data.get("target_duration") or data.get("duration"),
            narrative_roles=data.get("narrative_roles") or [],
        )

    @property
    def has_content(self) -> bool:
        """True when there is anything at all to score."""
        return bool(self.story_text or self.sections)


# The domain result *is* the frozen 16.1 score. See the module docstring.
ViralResultPayload = ViralScore


__all__ = [
    "SECTION_KEYS",
    "ViralRequest",
    "ViralResultPayload",
]
