"""Scene planning helpers for visual bible and per-scene blueprints."""

from __future__ import annotations

import math
import re
from collections import Counter


STOPWORDS = {
    "about", "after", "again", "also", "always", "among", "because", "before",
    "being", "between", "could", "every", "first", "found", "from", "have",
    "into", "just", "like", "many", "more", "most", "much", "only", "other",
    "over", "same", "some", "such", "than", "that", "their", "there", "these",
    "they", "this", "those", "through", "under", "very", "what", "when", "where",
    "which", "while", "with", "would", "your", "you", "once", "learn", "something",
    "suddenly", "called", "then", "still", "into", "them", "been", "were", "will",
}

CAMERA_GRAMMAR = {
    "hook": ["wide", "low-angle", "centered-symmetrical"],
    "buildup": ["medium", "over-shoulder", "POV", "close-up"],
    "peak": ["extreme-close-up", "low-angle", "high-angle"],
    "transition": ["wide", "bird's-eye", "centered-symmetrical"],
    "text_accent": ["medium", "centered-symmetrical", "close-up"],
    "cta": ["wide", "medium", "low-angle"],
}

VIDEO_CAMERA_MOVES = {
    "hook": [
        "slow push-in zoom toward subject over 4s; focal length ramps 24mm→55mm",
        "rack focus shift from foreground to subject at 2s; shallow depth of field",
    ],
    "buildup": [
        "slow left-to-right pan with 10° upward tilt; constant speed",
        "gentle pull-back from close-up to wide shot over 5s; subtle parallax",
        "handheld style with slight micro-jitter; naturalistic feel",
    ],
    "peak": [
        "180° orbit around subject at eye level over 6s; keep subject centered",
        "rapid push-in zoom over 2s; dramatic focal compression",
        "handheld style with slight micro-jitter; urgent energy",
    ],
    "transition": [
        "gentle pull-back from close-up to wide shot over 5s; reveal new environment",
        "slow left-to-right pan with subtle downward drift; contemplative pace",
    ],
    "cta": [
        "slow push-in zoom toward subject over 4s; focal length ramps 24mm→55mm",
        "rack focus shift from background to subject at 2.5s; draw focus to message",
    ],
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'-]+", (text or "").lower())


def extract_theme_keywords(script: str, limit: int = 6) -> list[str]:
    tokens = [
        token for token in _tokenize(script)
        if len(token) >= 4 and token not in STOPWORDS
    ]
    counts = Counter(tokens)
    return [word for word, _ in counts.most_common(limit)]


def _first_value(container: dict, *path: str) -> str:
    current = container
    for part in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    if isinstance(current, list):
        return current[0] if current else ""
    if isinstance(current, str):
        return current
    return ""


def _choose_text_indexes(total: int) -> set[int]:
    if total < 5:
        return set()
    indexes = {max(1, min(total - 2, int(round(total * 0.58))))}
    if total >= 14:
        indexes.add(max(1, min(total - 2, int(round(total * 0.82)))))
    return indexes


def _choose_peak_index(total: int) -> int:
    if total <= 2:
        return max(0, total - 1)
    return max(1, min(total - 2, int(round((total - 1) * 0.68))))


def _choose_transition_indexes(segments: list[dict], total: int, blocked: set[int]) -> set[int]:
    candidates = []
    for seg in segments:
        try:
            idx = int(seg.get("index"))
        except (TypeError, ValueError):
            continue
        if idx in blocked or idx <= 0 or idx >= total - 1:
            continue
        reason = str(seg.get("break_reason", "")).lower()
        if reason in {"strong_break", "end_of_text"}:
            candidates.append(idx)

    if not candidates and total >= 6:
        midpoint = max(1, min(total - 2, total // 2))
        candidates.append(midpoint)
    if total >= 10:
        candidates.append(max(1, min(total - 2, int(round(total * 0.35)))))

    max_transitions = max(1, total // 6)
    ordered = []
    seen = set()
    for idx in sorted(candidates):
        if idx in seen:
            continue
        seen.add(idx)
        ordered.append(idx)
        if len(ordered) >= max_transitions:
            break
    return set(ordered)


def build_visual_bible(script: str, segments: list[dict], style_spec: dict) -> dict:
    """Create a story-specific continuity contract for one generation request."""
    identity = style_spec.get("identity", {})
    hard = style_spec.get("hard_constraints", {})
    soft = style_spec.get("soft_preferences", {})

    keywords = extract_theme_keywords(script)
    environments = hard.get("environments") or []
    palette = hard.get("palette") or []
    lighting = hard.get("lighting_baseline") or []
    motifs = soft.get("motifs") or []

    primary_keyword = keywords[0] if keywords else "subject"
    secondary_keyword = keywords[1] if len(keywords) > 1 else ""
    world_anchor = environments[0] if environments else identity.get("render_mode", "")
    anchor_subject = (
        f"a recurring central figure tied to {primary_keyword}"
        if primary_keyword and primary_keyword != "subject"
        else "a recurring central figure"
    )
    if secondary_keyword:
        anchor_subject += f" and {secondary_keyword}"

    anchor_keywords = keywords[:3]
    anchor_motifs = motifs[:3] or keywords[:2]

    return {
        "core_theme_hint": (
            f"Use {primary_keyword}"
            + (f" and {secondary_keyword}" if secondary_keyword else "")
            + " as the emotional throughline."
        ),
        "tone_arc": "hook -> escalation -> peak -> release",
        "world_anchor": world_anchor or "one cohesive visual world",
        "anchor_subject": anchor_subject,
        "anchor_keywords": anchor_keywords,
        "anchor_motifs": anchor_motifs,
        "palette_guardrails": palette[:5],
        "lighting_baseline": lighting[0] if lighting else identity.get("render_mode", ""),
        "camera_grammar": CAMERA_GRAMMAR,
        "environment_rules": [
            f"Keep scenes inside the same visual world anchored by {world_anchor or 'the chosen style'}.",
            "Allow location shifts only when the narration clearly changes place or context.",
        ],
        "negative_guardrails": style_spec.get("negative_rules") or [],
        "style_keywords": identity.get("style_keywords") or [],
        "render_mode": identity.get("render_mode", ""),
    }


def build_scene_blueprints(segments: list[dict], visual_bible: dict, style_spec: dict) -> list[dict]:
    """Pre-plan narrative roles, scene types, and shot targets."""
    total = len(segments)
    if total <= 0:
        return []

    text_indexes = _choose_text_indexes(total)
    peak_index = _choose_peak_index(total)
    blocked = {0, total - 1, peak_index, *text_indexes}
    transition_indexes = _choose_transition_indexes(segments, total, blocked)
    target_image_count = max(1, int(round(total * 0.25))) if total >= 4 else 0

    blueprints = []
    prev_shot = ""
    prev_camera_move = ""
    image_count = 0

    for order, segment in enumerate(segments):
        idx = int(segment.get("index", order))
        if order == 0:
            role = "hook"
        elif order == total - 1:
            role = "cta"
        elif order == peak_index:
            role = "peak"
        elif order in text_indexes:
            role = "text_accent"
        elif order in transition_indexes:
            role = "transition"
        else:
            role = "buildup"

        if role == "text_accent":
            scene_type = "text"
        elif role == "transition" or (image_count < target_image_count and order % 4 == 0 and role == "buildup"):
            scene_type = "image"
            image_count += 1
        else:
            scene_type = "video"

        shots = CAMERA_GRAMMAR.get(role, CAMERA_GRAMMAR["buildup"])
        target_shot = next((shot for shot in shots if shot != prev_shot), shots[0])
        prev_shot = target_shot

        base_intensity = order / max(1, total - 1)
        if role == "hook":
            intensity = 0.8
        elif role == "peak":
            intensity = 1.0
        elif role == "cta":
            intensity = 0.78
        elif role == "transition":
            intensity = max(0.25, base_intensity * 0.6)
        else:
            intensity = max(0.35, min(0.9, 0.45 + base_intensity * 0.45))

        anchor_required = role in {"hook", "buildup", "peak", "text_accent", "cta"}
        continuity_priority = "high" if role in {"hook", "peak", "cta", "text_accent"} else "medium"

        camera_move = None
        if scene_type == "video":
            moves = VIDEO_CAMERA_MOVES.get(role, VIDEO_CAMERA_MOVES["buildup"])
            camera_move = next((m for m in moves if m != prev_camera_move), moves[0])
            prev_camera_move = camera_move

        blueprint = {
            "index": idx,
            "segment_words": segment.get("words", ""),
            "narrative_role": role,
            "preferred_scene_type": scene_type,
            "text_scene_allowed": role == "text_accent",
            "target_shot_type": target_shot,
            "intensity_level": round(float(intensity), 3),
            "anchor_required": anchor_required,
            "continuity_priority": continuity_priority,
            "world_anchor": visual_bible.get("world_anchor", ""),
            "style_keywords": visual_bible.get("style_keywords", [])[:4],
        }
        if camera_move:
            blueprint["camera_move"] = camera_move
        blueprints.append(blueprint)

    return blueprints


def slice_scene_blueprints(scene_blueprints: list[dict], segments: list[dict]) -> list[dict]:
    wanted = []
    order = []
    for seg in segments:
        try:
            idx = int(seg.get("index"))
        except (TypeError, ValueError):
            continue
        order.append(idx)
    by_index = {int(bp.get("index")): bp for bp in scene_blueprints if "index" in bp}
    for idx in order:
        blueprint = by_index.get(idx)
        if blueprint:
            wanted.append(blueprint)
    return wanted


def summarize_blueprints(scene_blueprints: list[dict]) -> dict:
    type_counts = Counter(bp.get("preferred_scene_type", "video") for bp in scene_blueprints)
    role_counts = Counter(bp.get("narrative_role", "buildup") for bp in scene_blueprints)
    return {
        "scene_count": len(scene_blueprints),
        "type_counts": dict(type_counts),
        "role_counts": dict(role_counts),
        "text_scene_target": type_counts.get("text", 0),
        "anchor_target_ratio": round(
            sum(1 for bp in scene_blueprints if bp.get("anchor_required")) / max(1, len(scene_blueprints)),
            3,
        ),
    }
