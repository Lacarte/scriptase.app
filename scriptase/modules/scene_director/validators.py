"""Validation and annotation helpers for generated scene results."""

from __future__ import annotations

import re

from scriptase.modules.scene_director.sfx_validator import validate_and_enforce_sfx


SHOT_TYPES = [
    "extreme-close-up",
    "close-up",
    "medium",
    "wide",
    "pov",
    "bird's-eye",
    "low-angle",
    "high-angle",
    "over-shoulder",
    "centered-symmetrical",
]

COLOR_WORDS = {
    "black", "white", "gray", "grey", "red", "blue", "green", "gold",
    "orange", "purple", "violet", "teal", "cyan", "pink", "brown",
    "silver", "amber", "cream", "navy", "charcoal",
}


def extract_shot_type_from_prompt(prompt: str) -> str:
    first_clause = (prompt or "").split(",", 1)[0].strip().lower()
    for shot_type in SHOT_TYPES:
        if shot_type in first_clause:
            return shot_type
    replacements = {
        "medium shot": "medium",
        "wide shot": "wide",
        "close shot": "close-up",
        "point of view": "pov",
    }
    for phrase, shot_type in replacements.items():
        if phrase in first_clause:
            return shot_type
    return ""


def _significant_tokens(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[A-Za-z][A-Za-z'-]+", (text or "").lower())
        if len(token) >= 4
    ]


def _pick_motif(prompt: str, visual_bible: dict) -> str:
    lowered = (prompt or "").lower()
    for motif in visual_bible.get("anchor_motifs", []) or []:
        motif_tokens = _significant_tokens(motif)
        if motif_tokens and any(token in lowered for token in motif_tokens):
            return motif
    return ""


def scene_uses_anchor(scene: dict, visual_bible: dict) -> bool:
    prompt = (scene.get("image_prompt") or "").lower()
    anchor_tokens = set()
    for item in visual_bible.get("anchor_keywords", []) or []:
        anchor_tokens.update(_significant_tokens(item))
    anchor_tokens.update(_significant_tokens(visual_bible.get("anchor_subject", ""))[:2])
    anchor_tokens.update(_significant_tokens(visual_bible.get("world_anchor", ""))[:2])
    if any(token in prompt for token in anchor_tokens if token):
        return True
    return bool(_pick_motif(prompt, visual_bible))


def _palette_terms(visual_bible: dict) -> list[str]:
    terms = []
    for item in visual_bible.get("palette_guardrails", []) or []:
        tokens = _significant_tokens(item)
        for token in tokens:
            if token in COLOR_WORDS or len(token) >= 5:
                terms.append(token)
    seen = set()
    result = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return result


def ensure_analysis_payload(result: dict, visual_bible: dict, style_spec: dict, template: dict | None = None) -> dict:
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}

    identity = style_spec.get("identity", {})
    analysis.setdefault("core_theme", visual_bible.get("core_theme_hint", ""))
    analysis.setdefault("mood", visual_bible.get("tone_arc", ""))
    analysis.setdefault("environment", visual_bible.get("world_anchor", ""))
    analysis.setdefault("color_palette", visual_bible.get("palette_guardrails", []))
    analysis.setdefault("tone", (template or {}).get("description", ""))
    analysis.setdefault("visual_style", identity.get("render_mode", (template or {}).get("name", "")))
    analysis["visual_bible"] = visual_bible
    result["analysis"] = analysis
    return analysis


def annotate_scenes(scenes: list[dict], scene_blueprints: list[dict], visual_bible: dict) -> list[dict]:
    by_index = {}
    for blueprint in scene_blueprints:
        try:
            by_index[int(blueprint.get("index"))] = blueprint
        except (TypeError, ValueError):
            continue

    annotated = []
    for scene in scenes:
        try:
            idx = int(scene.get("index"))
        except (TypeError, ValueError):
            idx = None
        blueprint = by_index.get(idx)

        updated = dict(scene)
        updated["shot_type"] = extract_shot_type_from_prompt(updated.get("image_prompt", "")) or (
            blueprint.get("target_shot_type", "") if blueprint else ""
        )
        updated["anchor_used"] = scene_uses_anchor(updated, visual_bible)
        updated["motif_used"] = _pick_motif(updated.get("image_prompt", ""), visual_bible)
        if blueprint:
            updated["blueprint_role"] = blueprint.get("narrative_role", "")
            updated["blueprint_type"] = blueprint.get("preferred_scene_type", "")
        annotated.append(updated)
    return annotated


def score_scene_coherence(scenes: list[dict], scene_blueprints: list[dict], visual_bible: dict) -> dict:
    warnings = []
    penalty = 0.0

    if not scenes:
        return {
            "coherence_score": 0.0,
            "coherence_warnings": ["No scenes were generated."],
            "coherence_metrics": {},
        }

    if scenes[0].get("type_of_scene") == "text":
        warnings.append("First scene should not be text.")
        penalty += 0.12
    if scenes[-1].get("type_of_scene") == "text":
        warnings.append("Last scene should not be text.")
        penalty += 0.12

    text_count = sum(1 for scene in scenes if scene.get("type_of_scene") == "text")
    if text_count > 2:
        warnings.append(f"Text scene count is high ({text_count}); target is 1-2.")
        penalty += 0.08

    repeated_shots = []
    for left, right in zip(scenes, scenes[1:]):
        left_shot = left.get("shot_type", "")
        right_shot = right.get("shot_type", "")
        if left_shot and left_shot == right_shot:
            repeated_shots.append((left.get("index"), right.get("index"), left_shot))
    if repeated_shots:
        for left_idx, right_idx, shot in repeated_shots[:4]:
            warnings.append(f"Shot type repeats across scenes {left_idx} and {right_idx}: {shot}.")
        penalty += min(0.2, 0.04 * len(repeated_shots))

    anchor_hits = sum(1 for scene in scenes if scene.get("anchor_used"))
    anchor_ratio = anchor_hits / max(1, len(scenes))
    if anchor_ratio < 0.6:
        warnings.append(f"Anchor subject or motif appears in only {anchor_ratio:.0%} of scenes.")
        penalty += 0.12

    palette_terms = _palette_terms(visual_bible)
    palette_hits = 0
    if palette_terms:
        for scene in scenes:
            prompt = (scene.get("image_prompt") or "").lower()
            if any(term in prompt for term in palette_terms):
                palette_hits += 1
        palette_ratio = palette_hits / max(1, len(scenes))
        if palette_ratio < 0.4:
            warnings.append("Palette terms rarely appear in prompts; scenes may drift from the intended color world.")
            penalty += 0.06
    else:
        palette_ratio = 0.0

    by_index = {}
    for blueprint in scene_blueprints:
        try:
            by_index[int(blueprint.get("index"))] = blueprint
        except (TypeError, ValueError):
            continue

    role_mismatches = 0
    type_mismatches = 0
    for scene in scenes:
        try:
            idx = int(scene.get("index"))
        except (TypeError, ValueError):
            continue
        blueprint = by_index.get(idx)
        if not blueprint:
            continue
        if blueprint.get("narrative_role") and scene.get("narrative_role") != blueprint.get("narrative_role"):
            role_mismatches += 1
        if blueprint.get("preferred_scene_type") and scene.get("type_of_scene") != blueprint.get("preferred_scene_type"):
            type_mismatches += 1

    if role_mismatches:
        warnings.append(f"{role_mismatches} scenes diverged from the planned narrative role.")
        penalty += min(0.08, role_mismatches * 0.015)
    if type_mismatches:
        warnings.append(f"{type_mismatches} scenes diverged from the planned scene type mix.")
        penalty += min(0.08, type_mismatches * 0.015)

    score = max(0.0, 1.0 - penalty)
    return {
        "coherence_score": round(score, 3),
        "coherence_warnings": warnings,
        "coherence_metrics": {
            "scene_count": len(scenes),
            "text_scene_count": text_count,
            "repeated_shot_pairs": len(repeated_shots),
            "anchor_coverage": round(anchor_ratio, 3),
            "palette_coverage": round(palette_ratio, 3),
            "role_mismatches": role_mismatches,
            "type_mismatches": type_mismatches,
        },
    }


def finalize_scene_result(result: dict, scene_blueprints: list[dict], visual_bible: dict) -> dict:
    scenes = result.get("scenes", []) if isinstance(result, dict) else []
    annotated = annotate_scenes(scenes, scene_blueprints, visual_bible)
    result["scenes"] = annotated
    result.update(score_scene_coherence(annotated, scene_blueprints, visual_bible))

    # SFX hint validation + budget enforcement.
    # Reads context from the result dict (the route-level hydration sets these
    # fields before calling finalize_scene_result). Mutates scenes IN PLACE,
    # then merges its warnings into the existing coherence_warnings list so
    # there's a single warning surface for callers.
    analysis = result.get("analysis") or {}
    sfx_report = validate_and_enforce_sfx(
        annotated,
        visual_style=result.get("style") or analysis.get("visual_style"),
        category=analysis.get("category") or result.get("category"),
        story_tone=analysis.get("story_tone") or result.get("story_tone"),
        total_duration_seconds=result.get("total_duration") or analysis.get("total_duration"),
    )
    result["sfx_report"] = {
        "hint_count": sfx_report["hint_count"],
        "hint_max": sfx_report["hint_max"],
        "hint_min": sfx_report["hint_min"],
        "dropped": sfx_report["dropped"],
    }
    if sfx_report.get("warnings"):
        existing_warnings = list(result.get("coherence_warnings") or [])
        existing_warnings.extend(f"[sfx] {w}" for w in sfx_report["warnings"])
        result["coherence_warnings"] = existing_warnings

    return result
