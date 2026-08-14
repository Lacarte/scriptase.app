"""Scene-blueprint domain request and result models (contracts.md §32.2).

Filled into `DomainSpec.request_model` / `result_model` by step 13.4. Every
scene-blueprint provider — the shipped n8n webhook path and any future plugin —
accepts and returns these shapes.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SegmentInput(BaseModel):
    """One non-filler speech segment the planner numbers densely from zero."""

    index: int = Field(ge=0)
    words: Any = ""
    start: Optional[float] = None
    end: Optional[float] = None
    is_filler: bool = False

    model_config = {"extra": "allow"}


class SceneBlueprintRequest(BaseModel):
    """Frozen §32.2 request. Unknown keys are rejected (not silently ignored)."""

    script: str = ""
    segments: list[SegmentInput] = Field(default_factory=list)
    style: str = "cinematic"
    style_notes: str = ""
    tone: str = ""
    aspect_ratio: str = "9:16"

    model_config = {"extra": "forbid"}

    @field_validator("script", "style", "style_notes", "tone", "aspect_ratio", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @classmethod
    def from_configuration(
        cls,
        configuration: Mapping[str, Any] | None,
        *,
        segments: list | None = None,
        script: str | None = None,
    ) -> "SceneBlueprintRequest":
        """Map adapter/legacy configuration keys onto the frozen request.

        Accepts both node/legacy names (`style_prompt`, `custom_style_notes`,
        `story_tone`, `text`) and the §32.2 names so the same provider can be
        driven by `scenes.blueprint` and by a direct v2 invocation.
        """
        data = dict(configuration or {})
        style_notes = (
            data.get("style_notes")
            or data.get("style_prompt")
            or data.get("custom_style_notes")
            or ""
        )
        script_text = script if script is not None else (data.get("script") or data.get("text") or "")
        segs = segments if segments is not None else (data.get("segments") or [])
        normalized: list[SegmentInput] = []
        for i, seg in enumerate(segs):
            if isinstance(seg, SegmentInput):
                normalized.append(seg)
            elif isinstance(seg, Mapping):
                payload = dict(seg)
                if "index" not in payload:
                    payload["index"] = i
                normalized.append(SegmentInput.model_validate(payload))
            else:
                normalized.append(SegmentInput(index=i, words=str(seg)))
        return cls(
            script=str(script_text or ""),
            segments=normalized,
            style=data.get("style") or "cinematic",
            style_notes=str(style_notes or ""),
            tone=data.get("tone") or data.get("story_tone") or "",
            aspect_ratio=data.get("aspect_ratio") or "9:16",
        )


class SceneItem(BaseModel):
    """One planned scene. Extra keys (timing, annotations) are preserved."""

    index: int = Field(ge=0)
    image_prompt: str = ""
    start: Optional[float] = None
    end: Optional[float] = None
    narrative_role: str = ""

    model_config = {"extra": "allow"}


class CoherenceBlock(BaseModel):
    score: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class SceneBlueprintResultPayload(BaseModel):
    """Frozen §32.2 result payload — the shape a scene-blueprint provider returns."""

    scenes: list[dict[str, Any]] = Field(default_factory=list)
    style_spec: dict[str, Any] = Field(default_factory=dict)
    style_prompt: str = ""
    analysis: dict[str, Any] = Field(default_factory=dict)
    coherence: CoherenceBlock = Field(default_factory=CoherenceBlock)
    sfx_report: Optional[dict[str, Any]] = None
    total_duration_s: float = 0.0

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _require_scenes(self) -> "SceneBlueprintResultPayload":
        if not self.scenes:
            raise ValueError("scenes must be non-empty")
        return self

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SceneBlueprintResultPayload":
        """Coerce a provider/legacy `scenes.json` document into the payload."""
        payload = dict(data or {})
        scenes = payload.get("scenes") or []
        if not isinstance(scenes, list):
            scenes = []
        coherence_score = payload.get("coherence_score")
        coherence_warnings = payload.get("coherence_warnings") or []
        coherence_metrics = payload.get("coherence_metrics") or {}
        coherence_block = payload.get("coherence")
        if isinstance(coherence_block, Mapping):
            coherence = CoherenceBlock(
                score=float(coherence_block.get("score") or coherence_score or 0.0),
                warnings=list(coherence_block.get("warnings") or coherence_warnings or []),
                metrics=dict(coherence_block.get("metrics") or coherence_metrics or {}),
            )
        else:
            coherence = CoherenceBlock(
                score=float(coherence_score or 0.0),
                warnings=list(coherence_warnings) if isinstance(coherence_warnings, list) else [],
                metrics=dict(coherence_metrics) if isinstance(coherence_metrics, Mapping) else {},
            )
        total = payload.get("total_duration_s")
        if total is None:
            total = payload.get("total_duration") or 0.0
        sfx = payload.get("sfx_report")
        if sfx is not None and not isinstance(sfx, Mapping):
            sfx = None
        return cls(
            scenes=[dict(s) if isinstance(s, Mapping) else {"index": i, "image_prompt": str(s)}
                    for i, s in enumerate(scenes)],
            style_spec=dict(payload.get("style_spec") or {}),
            style_prompt=str(payload.get("style_prompt") or ""),
            analysis=dict(payload.get("analysis") or {}),
            coherence=coherence,
            sfx_report=dict(sfx) if sfx is not None else None,
            total_duration_s=float(total or 0.0),
        )


__all__ = [
    "SegmentInput",
    "SceneBlueprintRequest",
    "SceneItem",
    "CoherenceBlock",
    "SceneBlueprintResultPayload",
]
