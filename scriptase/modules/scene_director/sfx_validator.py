"""SFX hint validation and budget enforcement for generated scenes.

The scene planner LLM optionally tags each scene with `sfx_hint` — a key from
the controlled vocabulary in resources/sfx-vocabulary.json. This module:

  1. Loads the vocabulary (cached after first read)
  2. Drops unknown / hallucinated hints silently
  3. Drops tonally-mismatched hints (cartoon_pop / crowd_laugh on non-comedy)
  4. Caps text_* hints to text-type scenes only
  5. Enforces video-level budget rules:
     - 3-4 hints maximum per video (under-30s videos: 2-3)
     - bass_drop_impact at most ONCE per video (keep last)
     - tension_riser at most ONCE per video (keep last)
     - Two consecutive scenes may not both have hints unless the pattern is
       tension_riser → impact (bass_drop_impact / cinematic_hit / glass_shatter)
     - text_appear and text_disappear may not both be on the same scene

The validator runs at the end of finalize_scene_result so it sees the final,
already-annotated scene list. Its decisions are recorded as warnings on the
result dict (matching the existing coherence_warnings pattern).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from loguru import logger

from config import APP_ASSETS_DIR


# ── Vocabulary loading (cached) ──────────────────────────────────────────────

_VOCAB_PATH = os.path.join(os.path.dirname(APP_ASSETS_DIR), "resources", "sfx-vocabulary.json")
_vocab_cache: dict | None = None
_vocab_lock = threading.Lock()


def load_sfx_vocabulary() -> dict:
    """Load and cache the SFX vocabulary file. Returns empty dict on failure."""
    global _vocab_cache
    with _vocab_lock:
        if _vocab_cache is not None:
            return _vocab_cache
        try:
            with open(_VOCAB_PATH, encoding="utf-8") as f:
                _vocab_cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning("Could not load SFX vocabulary at {}: {}", _VOCAB_PATH, e)
            _vocab_cache = {"version": 0, "hints": {}}
        return _vocab_cache


def reload_sfx_vocabulary() -> dict:
    """Force a reload of the vocabulary (used by hot-reload paths and tests)."""
    global _vocab_cache
    with _vocab_lock:
        _vocab_cache = None
    return load_sfx_vocabulary()


# ── Budget configuration ─────────────────────────────────────────────────────

# Hard cap on hints per video. The LLM is asked for 3-4 in the prompt; the
# validator will trim down to MAX if it overshoots, and emit a warning if the
# count is below MIN (it can't invent hints to meet the floor — that has to
# come from the LLM, this is the warning that tells you the LLM under-shot).
SFX_BUDGET_MIN = 3
SFX_BUDGET_MAX = 4
SFX_BUDGET_MAX_SHORT = 3   # for videos under SFX_SHORT_THRESHOLD seconds
SFX_BUDGET_MIN_SHORT = 2
SFX_SHORT_THRESHOLD_SECONDS = 30

# Hints that may appear at most ONCE per video. If duplicates are found, the
# LAST occurrence is kept (assumed to be the climax / final reveal — the LLM
# usually places the strongest hit late in the script).
_AT_MOST_ONCE = {"bass_drop_impact", "tension_riser"}

# Hints that count as "impact" landings (legal targets for a riser → impact
# pair on consecutive scenes).
_IMPACT_HINTS = {"bass_drop_impact", "cinematic_hit", "glass_shatter", "gunshot_punctuation"}

# Hints that are forbidden on non-comedy visual styles. The LLM is told this
# in the prompt, but the validator catches misuse.
_COMEDY_ONLY_HINTS = {"cartoon_pop", "crowd_laugh"}
_COMEDY_VISUAL_STYLES = {"comedy", "stickman_animation", "cartoon", "anime_comedy"}
_COMEDY_CATEGORIES = {"comedy"}
_COMEDY_TONES = {"comedic"}

# Hints that may only appear on text-type scenes.
_TEXT_ONLY_HINTS = {"text_appear", "text_disappear", "text_emphasis"}

# Drop priority — when over budget, hints are dropped in this order (highest
# priority dropped first). Lower-numbered = dropped first.
_DROP_PRIORITY = {
    "cartoon_pop":           1,   # decorative
    "crowd_laugh":           2,   # decorative
    "click_confirm":         3,   # subtle, easy to lose
    "notification_ding":     4,
    "camera_shutter":        5,
    "money_sting":           6,
    "telephone_ring":        7,
    "magic_shimmer":         8,
    "thinking_pad":          9,
    "nature_ambience":      10,
    "rain_ambience":        11,
    "viscous_liquid":       12,
    "glitch_distort":       13,
    "keyboard_typing":      14,
    "text_emphasis":        15,
    "text_disappear":       16,
    "text_appear":          17,
    "whoosh_transition":    18,
    "rocket_whoosh":        19,
    "heartbeat_pulse":      20,
    "clock_tick":           21,
    "crowd_cheer":          22,
    "gunshot_punctuation":  30,   # narrative-event-only, almost never drop
    "glass_shatter":        31,
    "cinematic_hit":        32,
    "tension_riser":        40,   # structural, rarely drop
    "bass_drop_impact":     50,   # climax, never drop unless duplicate
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _allowed_hint_keys() -> set[str]:
    """The full set of legal sfx_hint values, as defined by the vocabulary."""
    return set((load_sfx_vocabulary().get("hints") or {}).keys())


def _is_comedy_context(visual_style: str | None, category: str | None, tone: str | None) -> bool:
    if visual_style and visual_style in _COMEDY_VISUAL_STYLES:
        return True
    if category and category in _COMEDY_CATEGORIES:
        return True
    if tone and tone in _COMEDY_TONES:
        return True
    return False


def _scene_is_text(scene: dict) -> bool:
    """Detect a text-type scene under the various keys the planner uses."""
    return (
        scene.get("type") == "text"
        or scene.get("type_of_scene") == "text"
        or scene.get("preferred_scene_type") == "text"
    )


def _drop_score(hint_id: str) -> int:
    return _DROP_PRIORITY.get(hint_id, 25)  # unknown hints get a mid-priority drop score


# ── Main validator ───────────────────────────────────────────────────────────

def validate_and_enforce_sfx(
    scenes: list[dict],
    *,
    visual_style: str | None = None,
    category: str | None = None,
    story_tone: str | None = None,
    total_duration_seconds: float | None = None,
) -> dict:
    """Validate sfx_hint fields on scenes IN PLACE and enforce the budget.

    Returns a dict with:
      - hint_count: number of hints retained
      - hint_max: the budget ceiling that was applied
      - hint_min: the budget floor (not enforced, just reported)
      - dropped: list of {scene_index, hint, reason} for each removed hint
      - warnings: human-readable warnings for the coherence report
    """
    vocab_keys = _allowed_hint_keys()
    if not vocab_keys:
        # No vocabulary loaded — clear all sfx_hint fields and bail.
        for scene in scenes:
            if "sfx_hint" in scene:
                scene["sfx_hint"] = None
        return {
            "hint_count": 0,
            "hint_max": 0,
            "hint_min": 0,
            "dropped": [],
            "warnings": ["SFX vocabulary not loaded — all sfx_hint fields cleared."],
        }

    # Decide the budget for THIS video based on duration.
    is_short = (total_duration_seconds or 0) > 0 and total_duration_seconds < SFX_SHORT_THRESHOLD_SECONDS
    hint_max = SFX_BUDGET_MAX_SHORT if is_short else SFX_BUDGET_MAX
    hint_min = SFX_BUDGET_MIN_SHORT if is_short else SFX_BUDGET_MIN

    is_comedy = _is_comedy_context(visual_style, category, story_tone)
    dropped: list[dict] = []
    warnings: list[str] = []

    # ── Pass 1: per-scene validation ─────────────────────────────────────────
    # Drops hints that are individually invalid (unknown, wrong scene type,
    # tonal mismatch). Done before the budget check so the budget operates
    # on a clean set.
    for idx, scene in enumerate(scenes):
        hint = scene.get("sfx_hint")
        if hint in (None, ""):
            scene["sfx_hint"] = None
            continue

        # Unknown hint → drop silently
        if hint not in vocab_keys:
            dropped.append({"scene_index": idx, "hint": hint, "reason": "unknown_hint"})
            scene["sfx_hint"] = None
            continue

        # Comedy-only hint on non-comedy content → drop
        if hint in _COMEDY_ONLY_HINTS and not is_comedy:
            dropped.append({"scene_index": idx, "hint": hint, "reason": "comedy_only_on_non_comedy"})
            scene["sfx_hint"] = None
            continue

        # Text-only hint on non-text scene → drop
        if hint in _TEXT_ONLY_HINTS and not _scene_is_text(scene):
            dropped.append({"scene_index": idx, "hint": hint, "reason": "text_hint_on_non_text_scene"})
            scene["sfx_hint"] = None
            continue

    # ── Pass 2: enforce "at most once per video" rules ───────────────────────
    # For each restricted hint, find all occurrences. If more than one, keep
    # the LAST (typically the climax) and drop the others.
    for restricted in _AT_MOST_ONCE:
        positions = [i for i, s in enumerate(scenes) if s.get("sfx_hint") == restricted]
        if len(positions) > 1:
            keep = positions[-1]
            for i in positions:
                if i == keep:
                    continue
                dropped.append({"scene_index": i, "hint": restricted, "reason": "duplicate_unique_hint"})
                scenes[i]["sfx_hint"] = None
            warnings.append(
                f"`{restricted}` appeared {len(positions)} times — kept the last occurrence (scene {keep})."
            )

    # ── Pass 3: enforce consecutive-hint rule ────────────────────────────────
    # Two scenes in a row may not both have a hint unless the pattern is
    # tension_riser → (bass_drop_impact | cinematic_hit | glass_shatter).
    #
    # Runs BEFORE the budget pass because legal stacks must be preserved
    # at all costs. If we ran budget first, it could drop a hint adjacent
    # to a legal stack and create a NEW collision (e.g. whoosh + riser
    # becomes adjacent because magic was dropped, then the consecutive
    # pass would drop the riser and break the riser → impact pair).
    # Running consecutive first lets the legal stack be detected and
    # protected before any priority-based trimming happens.
    for i in range(len(scenes) - 1):
        a = scenes[i].get("sfx_hint")
        b = scenes[i + 1].get("sfx_hint")
        if not a or not b:
            continue
        # Legal stack: tension_riser → impact
        if a == "tension_riser" and b in _IMPACT_HINTS:
            continue
        # Otherwise, drop the second one (preserve the earlier hint —
        # usually the more structurally important of the pair, and
        # narratively the chronology bias favors earlier hits).
        dropped.append({"scene_index": i + 1, "hint": b, "reason": "consecutive_hint_collision"})
        scenes[i + 1]["sfx_hint"] = None

    # ── Pass 4: enforce hard cap (drop low-priority hints first) ─────────────
    # Runs after the consecutive cleanup so it operates on a list that
    # already respects the legal-stack rule. In dense-hint pathological
    # cases the consecutive pass may have already trimmed below budget;
    # in that case this pass does nothing.
    indexed_hints = [(i, s.get("sfx_hint")) for i, s in enumerate(scenes) if s.get("sfx_hint")]
    if len(indexed_hints) > hint_max:
        # Sort by drop priority ascending — first to drop are lowest priority.
        # Stable on scene index so ties drop the earlier scene first (a soft
        # bias toward keeping later/climactic accents).
        indexed_hints.sort(key=lambda pair: (_drop_score(pair[1]), pair[0]))
        excess = len(indexed_hints) - hint_max
        for scene_idx, hint_id in indexed_hints[:excess]:
            dropped.append({"scene_index": scene_idx, "hint": hint_id, "reason": "over_budget"})
            scenes[scene_idx]["sfx_hint"] = None

    # ── Final accounting ─────────────────────────────────────────────────────
    final_count = sum(1 for s in scenes if s.get("sfx_hint"))
    if final_count > hint_max:
        # Defensive — should be impossible after pass 4, but log if it happens.
        warnings.append(
            f"SFX over-budget after enforcement: {final_count} > {hint_max} (this is a validator bug)."
        )
    if final_count < hint_min and len(scenes) >= 4:
        # Only warn for videos with enough scenes to reasonably support the floor.
        warnings.append(
            f"SFX under-budget: {final_count} hints, expected at least {hint_min}. "
            f"The planner may have under-used the SFX vocabulary."
        )

    if dropped:
        # Roll up the drop reasons for the warning summary.
        reasons = {}
        for d in dropped:
            reasons[d["reason"]] = reasons.get(d["reason"], 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            warnings.append(f"Dropped {count} sfx_hint(s) — reason: {reason}")

    return {
        "hint_count": final_count,
        "hint_max": hint_max,
        "hint_min": hint_min,
        "dropped": dropped,
        "warnings": warnings,
    }
