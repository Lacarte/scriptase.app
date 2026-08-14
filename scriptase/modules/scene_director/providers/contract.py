"""Scene-director domain request and result models (contracts.md §8 / §32.2).

Filled into `DomainSpec.request_model` / `result_model` by step 13.4. Every
scene-director provider — the shipped n8n webhook path and any future plugin —
accepts and returns these shapes.

Step 5.1 freezes ``SceneSpec`` as the structured visual-scene contract carried
on the stable scene id from §4. Image and Video adapters consume ``SceneSpec``,
not loose dicts.

Step 5.2 freezes structured Channel ``visual_direction`` as typed request
inputs. The provider package owns prompt wording; no prompt text lives outside
a provider package.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Product §11 / contracts §8 narrative roles. The planner also uses
# ``text_accent`` (ported SceneItem vocabulary); unknown roles pass through so
# a Channel can extend the set without a schema bump.
NARRATIVE_ROLES = frozenset({
    "hook",
    "buildup",
    "explanation",
    "emotional_beat",
    "peak",
    "transition",
    "cta",
    "ending",
    "text_accent",
})

# Frozen §8 field names — the round-trip contract for SceneSpec.
SCENESPEC_FIELDS = (
    "scene_id",
    "narration",
    "visual_description",
    "image_prompt",
    "motion_prompt",
    "camera",
    "lighting",
    "mood",
    "continuity",
    "narrative_role",
    "overlay_hints",
    "sfx_hints",
)


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_str_list(value: Any) -> list[str]:
    """Coerce a string, list, or null into a list of non-empty strings."""
    if value is None or value is False:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            text = _strip_str(item)
            if text:
                out.append(text)
        return out
    text = _strip_str(value)
    return [text] if text else []


class SegmentInput(BaseModel):
    """One non-filler speech segment the planner numbers densely from zero."""

    index: int = Field(ge=0)
    words: Any = ""
    start: Optional[float] = None
    end: Optional[float] = None
    is_filler: bool = False
    scene_id: str = ""

    model_config = {"extra": "allow"}

    @field_validator("scene_id", mode="before")
    @classmethod
    def _scene_id(cls, value: Any) -> str:
        return _strip_str(value)


class PatternShotInput(BaseModel):
    """One narrative-role → shot mapping from Channel visual direction."""

    model_config = {"extra": "forbid"}

    narrative_role: str = Field(min_length=1)
    shot: str = Field(min_length=1)

    @field_validator("narrative_role", "shot", mode="before")
    @classmethod
    def _required(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("must be a non-empty string")
        return text


class VisualDirectionInput(BaseModel):
    """Typed Channel visual direction on the Scene Director request (step 5.2).

    Mirrors ``channels.models.VisualDirection`` so a Job channel snapshot feeds
    the Director without free-text prompt composition at the Channel/Job layer.
    The provider package owns how these fields become prompt wording.
    """

    model_config = {"extra": "forbid"}

    style: str = ""
    pattern: list[PatternShotInput] = Field(default_factory=list)
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
    def _pattern(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            raise ValueError(
                "pattern must be a list of {narrative_role, shot} objects, "
                "not free text"
            )
        if isinstance(value, dict):
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
        return _as_str_list(value)

    def is_empty(self) -> bool:
        """True when every structured field is unset."""
        return not (
            self.style
            or self.pattern
            or self.palette
            or self.lighting
            or self.camera
            or self.character_style
            or self.continuity
            or self.negative_prompt
            or self.references
        )

    def pattern_shot_map(self) -> dict[str, str]:
        """Ordered role → shot map; later entries overwrite earlier ones."""
        mapping: dict[str, str] = {}
        for entry in self.pattern:
            mapping[entry.narrative_role.strip().lower()] = entry.shot
        return mapping

    @classmethod
    def coerce(cls, value: Any) -> "VisualDirectionInput":
        """Build from a Channel snapshot block, request field, or empty."""
        if value is None or value is False:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls.model_validate(dict(value))
        raise ValueError("visual_direction must be an object")


class SceneBlueprintRequest(BaseModel):
    """Frozen §32.2 request extended with Channel visual direction (step 5.2).

    Unknown keys are rejected (not silently ignored). ``visual_direction`` is
    structured Channel input; the provider owns prompt wording.
    """

    script: str = ""
    segments: list[SegmentInput] = Field(default_factory=list)
    style: str = "cinematic"
    style_notes: str = ""
    tone: str = ""
    aspect_ratio: str = "9:16"
    visual_direction: VisualDirectionInput = Field(default_factory=VisualDirectionInput)

    model_config = {"extra": "forbid"}

    @field_validator("script", "style", "style_notes", "tone", "aspect_ratio", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("visual_direction", mode="before")
    @classmethod
    def _visual_direction(cls, value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, VisualDirectionInput):
            return value
        return value

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

        Channel ``visual_direction`` is accepted as a nested object (preferred)
        or as flat keys when an adapter has already unpacked them.
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

        visual_direction = visual_direction_from_config(data)
        style = data.get("style") or visual_direction.style or "cinematic"

        return cls(
            script=str(script_text or ""),
            segments=normalized,
            style=str(style or "cinematic"),
            style_notes=str(style_notes or ""),
            tone=data.get("tone") or data.get("story_tone") or "",
            aspect_ratio=data.get("aspect_ratio") or "9:16",
            visual_direction=visual_direction,
        )


def visual_direction_from_config(data: Mapping[str, Any] | None) -> VisualDirectionInput:
    """Pull structured visual direction out of a configuration mapping."""
    data = dict(data or {})
    nested = data.get("visual_direction")
    if nested is not None and nested is not False:
        try:
            return VisualDirectionInput.coerce(nested)
        except (TypeError, ValueError):
            pass

    # Flat fallbacks used when channel_settings was partially flattened.
    payload: dict[str, Any] = {}
    for key in (
        "style",
        "palette",
        "lighting",
        "camera",
        "character_style",
        "continuity",
        "negative_prompt",
        "references",
        "pattern",
    ):
        # Prefer explicit visual_* aliases if present.
        alias = data.get(f"visual_{key}")
        if alias not in (None, "", []):
            payload[key] = alias
            continue
        # style is already mapped onto request.style; do not re-lift it here.
        if key == "style":
            continue
        value = data.get(key)
        if key == "pattern" and value not in (None, "", []):
            payload[key] = value
        elif key != "pattern" and value not in (None, ""):
            payload[key] = value
    return VisualDirectionInput.coerce(payload)


# Backward-compatible private alias.
_visual_direction_from_config = visual_direction_from_config


class SceneSpec(BaseModel):
    """Structured visual scene specification (contracts.md §8 / product §11).

    Carried on the stable scene id from §4 (step 1.6). Image and Video adapters
    consume this model rather than loose dicts. Extra keys (timing annotations,
    coherence markers, legacy planner fields) are preserved so the provider
    result envelope can round-trip without loss.
    """

    # --- §8 core fields -------------------------------------------------------
    scene_id: str = ""
    narration: str = ""
    visual_description: str = ""
    image_prompt: str = ""
    motion_prompt: str = ""
    camera: str = ""
    lighting: str = ""
    mood: str = ""
    continuity: str = ""
    narrative_role: str = ""
    overlay_hints: list[str] = Field(default_factory=list)
    sfx_hints: list[str] = Field(default_factory=list)

    # --- Presentation / legacy fields retained from ported SceneItem ----------
    index: int = Field(default=0, ge=0)
    start: Optional[float] = None
    end: Optional[float] = None
    type_of_scene: str = ""
    title: str = ""
    text_content: Optional[str] = None

    model_config = {"extra": "allow"}

    @field_validator(
        "scene_id",
        "narration",
        "visual_description",
        "image_prompt",
        "motion_prompt",
        "camera",
        "lighting",
        "mood",
        "continuity",
        "narrative_role",
        "type_of_scene",
        "title",
        mode="before",
    )
    @classmethod
    def _strip_core(cls, value: Any) -> str:
        return _strip_str(value)

    @field_validator("overlay_hints", "sfx_hints", mode="before")
    @classmethod
    def _hints(cls, value: Any) -> list[str]:
        return _as_str_list(value)

    @field_validator("text_content", mode="before")
    @classmethod
    def _text_content(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = _strip_str(value)
        return text or None

    def image_prompt_text(self) -> str:
        """Provider-ready still-image prompt (empty when the scene has none)."""
        return self.image_prompt.strip()

    def motion_prompt_text(self) -> str:
        """Provider-ready motion prompt; falls back to the image prompt for i2v."""
        return (self.motion_prompt or self.image_prompt).strip()

    def unit_index(self, fallback: int = 0) -> int:
        """Presentation index used as the media-unit index."""
        try:
            return int(self.index)
        except (TypeError, ValueError):
            return int(fallback)

    @classmethod
    def coerce(cls, data: Any, *, position: int = 0) -> "SceneSpec":
        """Build a SceneSpec from any historical scene shape.

        Accepts a ``SceneSpec``, a mapping (legacy scenes.json row, webhook
        scene, adapter port payload), or a bare prompt string. Singular
        ``sfx_hint`` / ``overlay_hint`` collapse into the plural list fields;
        ``scene_id`` also accepts ``id`` when it looks like ``scn_*``.
        """
        if isinstance(data, cls):
            return data
        if not isinstance(data, Mapping):
            prompt = _strip_str(data)
            return cls(index=position, image_prompt=prompt, visual_description=prompt)

        raw = dict(data)
        payload: dict[str, Any] = {}

        # Identity
        scene_id = _strip_str(raw.pop("scene_id", None) or "")
        if not scene_id:
            maybe_id = _strip_str(raw.get("id"))
            if maybe_id.startswith("scn_"):
                scene_id = maybe_id
                raw.pop("id", None)
        payload["scene_id"] = scene_id

        # Index / timing
        index = raw.pop("index", None)
        if index is None:
            index = raw.pop("scene", None)
        if index is None:
            index = position
        try:
            payload["index"] = int(index)
        except (TypeError, ValueError):
            payload["index"] = position

        for key in ("start", "end"):
            if key in raw:
                payload[key] = raw.pop(key)

        # Narration: prefer explicit field, then segment words.
        narration = raw.pop("narration", None)
        if narration in (None, ""):
            narration = raw.pop("words", None)
        if narration in (None, ""):
            narration = raw.pop("segment_words", None)
        payload["narration"] = _strip_str(narration)

        # Visual description
        visual = raw.pop("visual_description", None)
        if visual in (None, ""):
            visual = raw.get("title")  # soft fallback; title also kept as itself
        payload["visual_description"] = _strip_str(visual)

        # Prompts
        image_prompt = raw.pop("image_prompt", None)
        if image_prompt in (None, ""):
            image_prompt = raw.pop("prompt", None)
        payload["image_prompt"] = _strip_str(image_prompt)

        motion = raw.pop("motion_prompt", None)
        if motion in (None, ""):
            # camera_move is the historical motion cue from the planner.
            motion = raw.get("camera_move")
        payload["motion_prompt"] = _strip_str(motion)

        # Camera / lighting / mood / continuity
        camera = raw.pop("camera", None)
        if camera in (None, ""):
            camera = raw.get("camera_move") or raw.get("shot_type") or raw.get("target_shot_type")
        payload["camera"] = _strip_str(camera)

        payload["lighting"] = _strip_str(raw.pop("lighting", None))
        payload["mood"] = _strip_str(raw.pop("mood", None))

        continuity = raw.pop("continuity", None)
        if continuity in (None, ""):
            continuity = raw.pop("continuity_note", None)
        payload["continuity"] = _strip_str(continuity)

        role = raw.pop("narrative_role", None)
        if role in (None, ""):
            role = raw.get("blueprint_role")
        payload["narrative_role"] = _strip_str(role)

        # Hints: plural wins; singular aliases merge in.
        overlays = list(_as_str_list(raw.pop("overlay_hints", None)))
        overlays.extend(_as_str_list(raw.pop("overlay_hint", None)))
        # text_content on a text scene is an overlay cue when no overlays given.
        text_content = raw.get("text_content")
        if not overlays and text_content not in (None, ""):
            overlays.extend(_as_str_list(text_content))
        payload["overlay_hints"] = overlays

        sfx = list(_as_str_list(raw.pop("sfx_hints", None)))
        sfx.extend(_as_str_list(raw.pop("sfx_hint", None)))
        # De-dupe while preserving order.
        seen_sfx: set[str] = set()
        unique_sfx: list[str] = []
        for item in sfx:
            if item not in seen_sfx:
                seen_sfx.add(item)
                unique_sfx.append(item)
        payload["sfx_hints"] = unique_sfx

        # Explicit presentation fields
        for key in ("type_of_scene", "title", "text_content"):
            if key in raw:
                payload[key] = raw.pop(key)

        # Remaining keys become extras (annotations, legacy planner fields).
        for key, value in raw.items():
            if key in payload:
                continue
            payload[key] = value

        return cls.model_validate(payload)

    def to_port_dict(self) -> dict[str, Any]:
        """Serialize for the scenes port / scenes.json document.

        Emits both the frozen §8 plural hint fields and the singular
        ``sfx_hint`` alias so pre-5.1 consumers (SFX validator dumps, compose)
        keep working on the same document.
        """
        data = self.model_dump(mode="python")
        hints = list(data.get("sfx_hints") or [])
        data["sfx_hint"] = hints[0] if len(hints) == 1 else (hints or None)
        return data


# Backward-compatible name used by the ported SceneItem contract.
SceneItem = SceneSpec


def coerce_scene_specs(
    scenes: Iterable[Any] | None,
) -> list[SceneSpec]:
    """Coerce a list of historical scene shapes into SceneSpec instances."""
    return [
        SceneSpec.coerce(scene, position=position)
        for position, scene in enumerate(scenes or ())
    ]


class CoherenceBlock(BaseModel):
    score: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class SceneBlueprintResultPayload(BaseModel):
    """Frozen §32.2 result payload — the shape a scene-director provider returns.

    ``scenes`` is a list of :class:`SceneSpec` (contracts.md §8). Legacy
    documents coerce through :meth:`from_mapping`.
    """

    scenes: list[SceneSpec] = Field(default_factory=list)
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
        scenes_raw = payload.get("scenes") or []
        if not isinstance(scenes_raw, list):
            scenes_raw = []
        scenes = coerce_scene_specs(scenes_raw)
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
            scenes=scenes,
            style_spec=dict(payload.get("style_spec") or {}),
            style_prompt=str(payload.get("style_prompt") or ""),
            analysis=dict(payload.get("analysis") or {}),
            coherence=coherence,
            sfx_report=dict(sfx) if sfx is not None else None,
            total_duration_s=float(total or 0.0),
        )

    def scenes_as_dicts(self) -> list[dict[str, Any]]:
        """Port-ready scene list (includes singular sfx_hint alias)."""
        return [scene.to_port_dict() for scene in self.scenes]


def stamp_scene_specs_from_segments(
    scenes: Iterable[Any],
    segments: Iterable[Mapping[str, Any]] | None,
) -> list[SceneSpec]:
    """Carry stable scene ids and narration from segmenter output onto scenes.

    Matching is by dense order (non-filler speech order), which is how the
    planner numbers scenes. Existing SceneSpec fields win over segment defaults.
    """
    seg_list = [dict(s) for s in (segments or ()) if isinstance(s, Mapping)]
    # Prefer non-filler speech segments when the flag is present.
    speech = [s for s in seg_list if not s.get("is_filler")]
    if not speech:
        speech = seg_list

    stamped: list[SceneSpec] = []
    for position, scene in enumerate(scenes or ()):
        spec = SceneSpec.coerce(scene, position=position)
        if position < len(speech):
            seg = speech[position]
            updates: dict[str, Any] = {}
            if not spec.scene_id:
                sid = _strip_str(seg.get("scene_id") or "")
                if sid:
                    updates["scene_id"] = sid
            if not spec.narration:
                words = seg.get("words") or seg.get("segment_words") or ""
                if isinstance(words, list):
                    words = " ".join(str(w) for w in words)
                text = _strip_str(words)
                if text:
                    updates["narration"] = text
            if updates:
                spec = spec.model_copy(update=updates)
        stamped.append(spec)
    return stamped


__all__ = [
    "NARRATIVE_ROLES",
    "SCENESPEC_FIELDS",
    "SegmentInput",
    "PatternShotInput",
    "VisualDirectionInput",
    "visual_direction_from_config",
    "SceneBlueprintRequest",
    "SceneSpec",
    "SceneItem",
    "coerce_scene_specs",
    "stamp_scene_specs_from_segments",
    "CoherenceBlock",
    "SceneBlueprintResultPayload",
]
