"""Apply structured Channel visual direction to planner outputs (step 5.2).

This module never composes free-form LLM prompts. It maps typed
``VisualDirectionInput`` fields onto the visual bible, scene blueprints, and
``SceneSpec`` slots. Provider packages own prompt wording.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from scriptase.modules.scene_director.providers.contract import (
    SceneSpec,
    VisualDirectionInput,
    coerce_scene_specs,
)


def coerce_visual_direction(value: Any) -> VisualDirectionInput:
    """Accept a Channel snapshot block, request field, or empty."""
    try:
        return VisualDirectionInput.coerce(value)
    except (TypeError, ValueError):
        return VisualDirectionInput()


def pattern_camera_grammar(
    visual_direction: VisualDirectionInput | Mapping[str, Any] | None,
    *,
    base: Mapping[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Merge Channel pattern shots into the planner's camera grammar.

    Pattern entries win for their narrative role: the Channel shot becomes the
    preferred (first) option so two Channels with different patterns produce
    different target shots for the same role.
    """
    direction = coerce_visual_direction(visual_direction)
    grammar: dict[str, list[str]] = {
        str(role): list(shots)
        for role, shots in dict(base or {}).items()
    }
    for role, shot in direction.pattern_shot_map().items():
        existing = grammar.get(role) or []
        # Prefer the Channel shot; keep prior options as fallbacks for variety.
        rest = [s for s in existing if s != shot]
        grammar[role] = [shot, *rest]
    return grammar


def apply_visual_direction_to_bible(
    visual_bible: Mapping[str, Any] | None,
    visual_direction: VisualDirectionInput | Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Overlay Channel palette / lighting / camera / continuity / negatives."""
    bible = dict(visual_bible or {})
    direction = coerce_visual_direction(visual_direction)
    if direction.is_empty():
        return bible

    if direction.palette:
        # Channel palette is a free-form constraint string; split lightly for
        # guardrail lists without turning it into prompt prose.
        terms = _split_constraint_terms(direction.palette)
        if terms:
            bible["palette_guardrails"] = terms[:8]
            bible["channel_palette"] = direction.palette

    if direction.lighting:
        bible["lighting_baseline"] = direction.lighting
        bible["channel_lighting"] = direction.lighting

    if direction.camera:
        bible["channel_camera"] = direction.camera

    if direction.character_style:
        bible["character_style"] = direction.character_style
        subject = _strip(bible.get("anchor_subject"))
        if subject and direction.character_style not in subject:
            bible["anchor_subject"] = f"{subject}; character style: {direction.character_style}"
        elif not subject:
            bible["anchor_subject"] = direction.character_style

    if direction.continuity:
        rules = list(bible.get("environment_rules") or [])
        note = direction.continuity
        if note not in rules:
            rules.insert(0, note)
        bible["environment_rules"] = rules
        bible["channel_continuity"] = note

    if direction.negative_prompt:
        negatives = list(bible.get("negative_guardrails") or [])
        for term in _split_constraint_terms(direction.negative_prompt):
            if term not in negatives:
                negatives.append(term)
        bible["negative_guardrails"] = negatives
        bible["channel_negative_prompt"] = direction.negative_prompt

    if direction.references:
        bible["channel_references"] = list(direction.references)

    if direction.style:
        bible.setdefault("channel_style", direction.style)

    # Structured pattern snapshot for prompt builders / debugging — not prose.
    if direction.pattern:
        bible["channel_pattern"] = [
            {"narrative_role": entry.narrative_role, "shot": entry.shot}
            for entry in direction.pattern
        ]

    return bible


def apply_visual_direction_to_scenes(
    scenes: Iterable[Any],
    visual_direction: VisualDirectionInput | Mapping[str, Any] | None,
    *,
    blueprints: Iterable[Mapping[str, Any]] | None = None,
) -> list[SceneSpec]:
    """Fill empty SceneSpec camera / lighting / continuity / mood from Channel.

    Existing non-empty SceneSpec fields win (provider or LLM already chose).
    Pattern-driven blueprint target shots fill ``camera`` when still empty.
    """
    direction = coerce_visual_direction(visual_direction)
    by_index: dict[int, Mapping[str, Any]] = {}
    for blueprint in blueprints or ():
        if not isinstance(blueprint, Mapping):
            continue
        try:
            by_index[int(blueprint.get("index"))] = blueprint
        except (TypeError, ValueError):
            continue

    pattern_map = direction.pattern_shot_map()
    stamped: list[SceneSpec] = []
    for position, scene in enumerate(scenes or ()):
        spec = SceneSpec.coerce(scene, position=position)
        updates: dict[str, Any] = {}

        blueprint = by_index.get(spec.index) or by_index.get(position)
        role = (spec.narrative_role or "").strip().lower()
        if not role and blueprint:
            role = _strip(blueprint.get("narrative_role")).lower()
            if role:
                updates["narrative_role"] = _strip(blueprint.get("narrative_role"))

        if not spec.camera:
            camera = direction.camera
            if not camera and blueprint:
                camera = _strip(
                    blueprint.get("target_shot_type")
                    or blueprint.get("camera_move")
                )
            if not camera and role:
                camera = pattern_map.get(role, "")
            if camera:
                updates["camera"] = camera

        if not spec.lighting and direction.lighting:
            updates["lighting"] = direction.lighting

        if not spec.continuity and direction.continuity:
            updates["continuity"] = direction.continuity

        if not spec.mood and direction.style:
            # Style id is not a mood, but character_style can seed mood when empty.
            pass
        if not spec.mood and direction.character_style:
            updates["mood"] = direction.character_style

        # Preserve extras: channel pattern shot as annotation when present.
        if role and role in pattern_map:
            extras = dict(spec.model_extra or {}) if hasattr(spec, "model_extra") else {}
            # SceneSpec uses extra="allow"; dump and re-merge via model_copy.
            if not getattr(spec, "channel_shot", None):
                updates["channel_shot"] = pattern_map[role]

        if updates:
            spec = spec.model_copy(update=updates)
        stamped.append(spec)
    return stamped


def plan_scene_specs_from_direction(
    segments: Iterable[Mapping[str, Any]] | None,
    visual_direction: VisualDirectionInput | Mapping[str, Any] | None,
    *,
    script: str = "",
    style_spec: Mapping[str, Any] | None = None,
) -> list[SceneSpec]:
    """Offline Director planning: blueprints + Channel direction → SceneSpecs.

    Deterministic, credential-free, no LLM. Used by the fixture provider and
    by the step 5.2 divergence test. Prompt *wording* for image_prompt is a
    minimal structured composition that lives in the calling provider package
    when that package wants free-form text; this helper only fills §8 slots
    from structured inputs.
    """
    from scriptase.modules.scene_director.planner import (
        build_scene_blueprints,
        build_visual_bible,
    )

    direction = coerce_visual_direction(visual_direction)
    speech = [
        dict(seg)
        for seg in (segments or ())
        if isinstance(seg, Mapping) and not seg.get("is_filler")
    ]
    if not speech:
        speech = [dict(seg) for seg in (segments or ()) if isinstance(seg, Mapping)]

    # Dense indexes for the planner.
    planning = []
    for i, seg in enumerate(speech):
        row = dict(seg)
        row["index"] = i
        planning.append(row)

    style = dict(style_spec or {})
    if direction.style and not style.get("identity"):
        style.setdefault("identity", {})
        if isinstance(style["identity"], dict):
            style["identity"] = {
                **style["identity"],
                "render_mode": style["identity"].get("render_mode") or direction.style,
            }

    bible = build_visual_bible(script, planning, style)
    bible = apply_visual_direction_to_bible(bible, direction)
    blueprints = build_scene_blueprints(
        planning, bible, style, visual_direction=direction
    )

    scenes: list[dict[str, Any]] = []
    for bp in blueprints:
        idx = int(bp.get("index", 0))
        words = _strip(bp.get("segment_words"))
        role = _strip(bp.get("narrative_role"))
        shot = _strip(bp.get("target_shot_type"))
        scenes.append({
            "index": idx,
            "scene_id": _strip(planning[idx].get("scene_id")) if idx < len(planning) else "",
            "narration": words,
            "narrative_role": role,
            "visual_description": words,
            "camera": shot or direction.camera,
            "lighting": direction.lighting,
            "mood": direction.character_style or "",
            "continuity": direction.continuity,
            "type_of_scene": bp.get("preferred_scene_type") or "video",
            "channel_shot": shot,
        })

    return apply_visual_direction_to_scenes(
        coerce_scene_specs(scenes),
        direction,
        blueprints=blueprints,
    )


def _split_constraint_terms(text: str) -> list[str]:
    raw = _strip(text)
    if not raw:
        return []
    parts = []
    for chunk in raw.replace(";", ",").replace("/", ",").split(","):
        term = chunk.strip()
        if term:
            parts.append(term)
    if not parts and raw:
        parts = [raw]
    return parts


def _strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = [
    "coerce_visual_direction",
    "pattern_camera_grammar",
    "apply_visual_direction_to_bible",
    "apply_visual_direction_to_scenes",
    "plan_scene_specs_from_direction",
]
