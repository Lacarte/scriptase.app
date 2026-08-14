"""Animator domain request and result models (contracts.md §32.5).

Filled into `DomainSpec.request_model` / `result_model` by step 14.3. Every
animator provider — the browser extension and the Kie AI API, and any future
plugin — accepts and returns these shapes.

Deliberately *provider-neutral*: `quality`, `duration`, `auto_type`, and Kie's
`resolution`/`output_format`/`model` are provider settings (§26, §32.5), not
request fields. Per-scene detail belongs in `units[]`; `scene_statuses` survives
only inside `grabber_job.json` for the legacy status route (§17.1).

`arguments` is not part of the frozen request — it was a free-text Automa
passthrough for a Midjourney path that no longer exists (P12). The HTTP schema
still accepts the field for old callers and drops it.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field, field_validator

from scriptase.modules.scene_director.providers.contract import SceneSpec, coerce_scene_specs


DEFAULT_ASPECT_RATIO = "9:16"
DEFAULT_MODE = "video"
VALID_MODES = frozenset({"video", "image"})


class AnimatorScene(BaseModel):
    """One requested unit. `index` is the `unit_index` the result reports."""

    index: int = Field(ge=0)
    prompt: str = Field(min_length=1)
    reference_ref: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("prompt", mode="before")
    @classmethod
    def _strip_prompt(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("reference_ref", mode="before")
    @classmethod
    def _empty_ref_is_none(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None


class AnimatorRequest(BaseModel):
    """Frozen §32.5 request. Unknown keys are rejected, not silently ignored."""

    scenes: list[AnimatorScene] = Field(min_length=1)
    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    mode: str = DEFAULT_MODE

    model_config = {"extra": "forbid"}

    @field_validator("aspect_ratio", mode="before")
    @classmethod
    def _default_aspect_ratio(cls, value: Any) -> str:
        return str(value or "").strip() or DEFAULT_ASPECT_RATIO

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> str:
        text = str(value or "").strip().lower() or DEFAULT_MODE
        return text if text in VALID_MODES else DEFAULT_MODE

    @property
    def unit_count(self) -> int:
        return len(self.scenes)

    def indices(self) -> list[int]:
        return [scene.index for scene in self.scenes]

    def legacy_scenes(self) -> list[dict]:
        """The `{scene, prompt}` shape `grabber_job.json` and Automa use.

        The route historically emitted `scene` and the workflow adapter emitted
        `index`, so both spellings collapse here into one outbound list.
        """
        return [{"scene": scene.index, "prompt": scene.prompt} for scene in self.scenes]

    @classmethod
    def from_scene_specs(
        cls,
        scenes: Iterable[SceneSpec],
        *,
        aspect_ratio: Any = DEFAULT_ASPECT_RATIO,
        mode: Any = DEFAULT_MODE,
    ) -> "AnimatorRequest":
        """Build a request from typed :class:`SceneSpec` rows (step 5.1).

        Uses ``SceneSpec.motion_prompt`` (falling back to ``image_prompt``) so
        the video adapter never digs in a loose dict for prompt text.
        """
        units: list[dict] = []
        for position, scene in enumerate(scenes or ()):
            if not isinstance(scene, SceneSpec):
                scene = SceneSpec.coerce(scene, position=position)
            prompt = scene.motion_prompt_text()
            if not prompt:
                continue
            entry: dict[str, Any] = {
                "index": scene.unit_index(position),
                "prompt": prompt,
            }
            ref = getattr(scene, "reference_ref", None)
            if ref in (None, ""):
                extras = getattr(scene, "__pydantic_extra__", None) or {}
                ref = extras.get("reference_ref") if isinstance(extras, Mapping) else None
            if ref not in (None, ""):
                entry["reference_ref"] = ref
            units.append(entry)
        return cls(scenes=units, aspect_ratio=aspect_ratio, mode=mode)

    @classmethod
    def from_scenes(
        cls,
        scenes: Iterable[Any],
        *,
        aspect_ratio: Any = DEFAULT_ASPECT_RATIO,
        mode: Any = DEFAULT_MODE,
    ) -> "AnimatorRequest":
        """Build a request from SceneSpec or any historical scene shape.

        Accepts typed ``SceneSpec`` instances and legacy mappings
        (`index`/`scene`, `prompt`/`image_prompt`/`motion_prompt`,
        optional `reference_ref`).
        """
        return cls.from_scene_specs(
            coerce_scene_specs(scenes),
            aspect_ratio=aspect_ratio,
            mode=mode,
        )


class AnimatorResultPayload(BaseModel):
    """Frozen §32.5 result payload — the only shape an animator provider returns."""

    total: int = Field(ge=0)
    ready: int = Field(ge=0)
    errors: int = Field(ge=0)
    manifest_ref: str = ""

    model_config = {"extra": "forbid"}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AnimatorResultPayload":
        payload = dict(data or {})
        return cls(
            total=int(payload.get("total") or 0),
            ready=int(payload.get("ready") or 0),
            errors=int(payload.get("errors") or 0),
            manifest_ref=str(payload.get("manifest_ref") or ""),
        )


__all__ = [
    "DEFAULT_ASPECT_RATIO",
    "DEFAULT_MODE",
    "VALID_MODES",
    "AnimatorRequest",
    "AnimatorResultPayload",
    "AnimatorScene",
]
