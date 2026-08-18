"""Storyboard domain request and result models (contracts.md §32.4).

Filled into `DomainSpec.request_model` / `result_model` by step 14.2. Every
storyboard provider — the browser extension, the n8n webhook, the direct
WaveSpeed API, and any future plugin — accepts and returns these shapes.

Deliberately *provider-neutral*: `image_model`, `prompt_prefix`, and `auto_type`
are provider settings (§26, §32.4), not request fields, so the request never
freezes a value that is also a durable setting. Per-scene detail belongs in
`units[]`, not in the payload; `scene_statuses` survives only inside
`storyboard.json` for the legacy status route (§17.1) and is derived from units.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field, field_validator

from scriptase.modules.scene_director.providers.contract import SceneSpec, coerce_scene_specs
from scriptase.prompts.visual import compose_visual_prompt


DEFAULT_ASPECT_RATIO = "9:16"


class StoryboardScene(BaseModel):
    """One requested unit. `index` is the `unit_index` the result reports."""

    index: int = Field(ge=0)
    prompt: str = Field(min_length=1)

    model_config = {"extra": "forbid"}

    @field_validator("prompt", mode="before")
    @classmethod
    def _strip_prompt(cls, value: Any) -> str:
        return str(value or "").strip()


class StoryboardRequest(BaseModel):
    """Frozen §32.4 request. Unknown keys are rejected, not silently ignored."""

    scenes: list[StoryboardScene] = Field(min_length=1)
    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    style: str = ""

    model_config = {"extra": "forbid"}

    @field_validator("aspect_ratio", mode="before")
    @classmethod
    def _default_aspect_ratio(cls, value: Any) -> str:
        return str(value or "").strip() or DEFAULT_ASPECT_RATIO

    @field_validator("style", mode="before")
    @classmethod
    def _strip_style(cls, value: Any) -> str:
        return str(value or "").strip()

    @property
    def unit_count(self) -> int:
        return len(self.scenes)

    def indices(self) -> list[int]:
        return [scene.index for scene in self.scenes]

    def legacy_scenes(self) -> list[dict]:
        """The `{scene, prompt}` shape `storyboard.json` and the extension use.

        The two historical producers disagreed: the route emitted `scene` and
        the workflow adapter emitted `index`, so `gemini_ws._push_to_grok`
        silently dropped every adapter-started scene. One spelling now leaves
        the contract.
        """
        return [{"scene": scene.index, "prompt": scene.prompt} for scene in self.scenes]

    @classmethod
    def from_scene_specs(
        cls,
        scenes: Iterable[SceneSpec],
        *,
        aspect_ratio: Any = DEFAULT_ASPECT_RATIO,
        style: Any = "",
    ) -> "StoryboardRequest":
        """Build a request from typed :class:`SceneSpec` rows (step 5.1).

        Uses ``SceneSpec.image_prompt`` — never a free-form loose dict lookup.
        """
        units: list[dict] = []
        for position, scene in enumerate(scenes or ()):
            if not isinstance(scene, SceneSpec):
                scene = SceneSpec.coerce(scene, position=position)
            # Rebuild from the Director-stamped components through the one
            # canonical composer. Legacy SceneSpecs without components retain
            # their existing image_prompt unchanged.
            if scene.scene_subject:
                prompt = compose_visual_prompt(
                    scene.scene_subject,
                    scene.visual_style_prompt,
                    scene.mood,
                    scene.prompt_aspect_ratio or aspect_ratio,
                )
            else:
                prompt = scene.image_prompt_text()
            if not prompt:
                continue
            units.append({"index": scene.unit_index(position), "prompt": prompt})
        return cls(scenes=units, aspect_ratio=aspect_ratio, style=style)

    @classmethod
    def from_scenes(
        cls,
        scenes: Iterable[Any],
        *,
        aspect_ratio: Any = DEFAULT_ASPECT_RATIO,
        style: Any = "",
    ) -> "StoryboardRequest":
        """Build a request from SceneSpec or any historical scene shape.

        Accepts typed ``SceneSpec`` instances and legacy mappings
        (`index`/`scene`, `prompt`/`image_prompt`) so the workflow node, the
        legacy page, and the pipeline all reach the same provider.
        """
        return cls.from_scene_specs(
            coerce_scene_specs(scenes),
            aspect_ratio=aspect_ratio,
            style=style,
        )


class StoryboardResultPayload(BaseModel):
    """Frozen §32.4 result payload — the only shape a storyboard provider returns."""

    total: int = Field(ge=0)
    ready: int = Field(ge=0)
    errors: int = Field(ge=0)
    manifest_ref: str = ""

    model_config = {"extra": "forbid"}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StoryboardResultPayload":
        payload = dict(data or {})
        return cls(
            total=int(payload.get("total") or 0),
            ready=int(payload.get("ready") or 0),
            errors=int(payload.get("errors") or 0),
            manifest_ref=str(payload.get("manifest_ref") or ""),
        )


__all__ = [
    "DEFAULT_ASPECT_RATIO",
    "StoryboardRequest",
    "StoryboardResultPayload",
    "StoryboardScene",
]
