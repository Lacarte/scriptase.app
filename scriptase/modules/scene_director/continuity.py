"""Helpers for carrying continuity state across chapter/chunk generation."""

from __future__ import annotations

from collections import Counter

from scriptase.modules.scene_director.validators import extract_shot_type_from_prompt, scene_uses_anchor


def build_progress_state(scenes: list[dict], visual_bible: dict, plan_summary: dict | None = None) -> dict:
    """Summarize already generated scenes for continuation prompts."""
    type_counts = Counter()
    recent_shots = []
    motifs = []
    anchor_hits = 0

    for scene in scenes or []:
        scene_type = scene.get("type_of_scene") or scene.get("type") or "video"
        type_counts[scene_type] += 1
        shot_type = scene.get("shot_type") or extract_shot_type_from_prompt(scene.get("image_prompt", ""))
        if shot_type:
            recent_shots.append(shot_type)
        motif = scene.get("motif_used")
        if motif:
            motifs.append(motif)
        if scene.get("anchor_used") or scene_uses_anchor(scene, visual_bible):
            anchor_hits += 1

    generated_count = len(scenes or [])
    return {
        "generated_scene_count": generated_count,
        "type_counts": dict(type_counts),
        "recent_shot_types": recent_shots[-2:],
        "anchor_coverage": round(anchor_hits / max(1, generated_count), 3) if generated_count else 0.0,
        "active_environment": visual_bible.get("world_anchor", ""),
        "last_motif": motifs[-1] if motifs else "",
        "global_targets": dict(plan_summary or {}),
    }
