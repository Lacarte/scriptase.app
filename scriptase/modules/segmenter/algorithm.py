"""Timing Module — Scene Segmenter

Splits a word-level alignment into timed segments suitable for scene generation.
Each segment targets a natural speech boundary (punctuation + silence) and falls
within configurable duration limits.

Usage (CLI):
    python -m scriptase.modules.segmenter.algorithm input.json
    python -m scriptase.modules.segmenter.algorithm input.json --target-min 1.5 --target-max 3.0
"""

import json
import os
import re
import sys
from datetime import datetime

from scriptase.shared.io_utils import safe_json_write

# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "target_min": 1.5,
    "target_max": 4.0,
    "hard_max": 5.0,
    "hard_min": 0.8,
    "gap_filler": 0.3,
}

# Scene-pacing presets: how long each scene stays on screen, as a duration band
# the segmenter aims for while still cutting on a natural speech pause. A band
# is chosen per Channel (its brand/format) and maps to these algorithm knobs.
# `hard_max` caps the longest a scene may run before a cut is forced, kept a
# little above `target_max` so a natural boundary can still be preferred.
#
#   fast      — tight, punchy cuts (TikTok tension, high energy)
#   balanced  — one scene per ~5s clip (matches a 5s video-clip model)
#   cinematic — slow, contemplative shots (documentary, philosophy)
PACING_PRESETS = {
    "fast": {"target_min": 2.5, "target_max": 4.0, "hard_max": 5.0},
    "balanced": {"target_min": 3.5, "target_max": 5.0, "hard_max": 6.0},
    "cinematic": {"target_min": 5.0, "target_max": 7.0, "hard_max": 8.5},
}
DEFAULT_PACING = "balanced"


def pacing_config(preset):
    """The segmenter knobs for a pacing preset, or `{}` for an unknown one."""
    return dict(PACING_PRESETS.get(str(preset or "").strip().lower(), {}))

# ---------------------------------------------------------------------------
# Vocabulary sets for break scoring
# ---------------------------------------------------------------------------
MOOD_SHIFT_WORDS = frozenset([
    "but", "yet", "however", "suddenly", "then", "meanwhile", "instead",
    "although", "except", "until", "unless", "still", "anyway", "nevertheless",
    "finally", "so", "therefore", "now", "and",
])

VISUAL_NOUNS = frozenset([
    "sky", "sun", "moon", "star", "stars", "cloud", "clouds", "rain", "snow",
    "fire", "flame", "water", "ocean", "sea", "river", "lake", "mountain",
    "tree", "forest", "garden", "flower", "flowers", "rose", "roses",
    "gate", "door", "wall", "walls", "window", "road", "path", "bridge",
    "house", "castle", "tower", "city", "village", "light", "shadow",
    "bird", "birds", "horse", "wolf", "dragon", "king", "queen",
    "sword", "ship", "stone", "iron", "gold", "silver", "blood",
    "eye", "eyes", "hand", "hands", "face", "heart", "crown",
    "ivy", "thorns", "branches", "fountain", "apple", "fruit", "skin",
])

ACTION_VERBS = frozenset([
    "ran", "run", "runs", "running", "walked", "walk", "fell", "fall",
    "climbed", "climb", "jumped", "jump", "flew", "fly", "turned",
    "opened", "closed", "broke", "burned", "burst", "crashed", "died",
    "screamed", "whispered", "shouted", "fought", "struck", "grew",
    "covered", "locking", "picked", "answered", "refused", "abandoned",
])


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def load_alignment(filepath):
    """Read alignment JSON, return (alignment_array, metadata_dict)."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    alignment = data.get("alignment", data if isinstance(data, list) else [])
    metadata = {
        "source_folder": data.get("source_folder", ""),
        "style": data.get("style", ""),
        "aspect_ratio": data.get("aspect_ratio", ""),
        "transcript": data.get("transcript", ""),
    }
    return alignment, metadata


def clean_word(word):
    """Lowercase, strip punctuation for matching."""
    return re.sub(r"[^a-zA-Z']", "", word).lower()


def get_punctuation(word):
    """Detect punctuation type at end of word."""
    stripped = word.rstrip()
    if stripped.endswith((".","!","?")):
        return "sentence_end"
    if stripped.endswith(","):
        return "comma"
    if stripped.endswith((";",":","—","–","-")):
        return "clause_end"
    return "none"


def get_break_score(word, next_gap, next_word=None, weights=None):
    """Score 0-20+ indicating how good a break point this word is.

    Higher = better break.  Factors:
      - punctuation type (scaled by weights["punctuation"], default 8)
      - silence gap after word (scaled by weights["pause"], default 6)
      - mood-shift word following (0-3)
      - current word is a visual noun or action verb (0-3)

    Optional weights dict from blueprint break_weights:
      {"punctuation": 8, "pause": 6, "density": 3}
    """
    w = weights or {}
    punc_max = w.get("punctuation", 8)
    pause_max = w.get("pause", 6)

    score = 0
    punc = get_punctuation(word)

    # Punctuation (scaled)
    if punc == "sentence_end":
        score += punc_max
    elif punc == "clause_end":
        score += max(1, round(punc_max * 0.625))
    elif punc == "comma":
        score += max(1, round(punc_max * 0.375))

    # Silence gap (scaled)
    if next_gap >= 0.5:
        score += pause_max
    elif next_gap >= 0.3:
        score += max(1, round(pause_max * 0.67))
    elif next_gap >= 0.15:
        score += max(1, round(pause_max * 0.33))

    # Mood shift (next word starts a new mood)
    if next_word:
        cw = clean_word(next_word)
        if cw in MOOD_SHIFT_WORDS:
            score += 3

    # Visual noun / action verb (current word ends on strong imagery)
    cw_current = clean_word(word)
    if cw_current in VISUAL_NOUNS:
        score += 2
    if cw_current in ACTION_VERBS:
        score += 1

    return score


def segment(alignment, config=None):
    """Main segmentation algorithm — greedy scan with score-based cutting.

    Returns list of raw segment dicts (before merge/fill post-processing).
    Config may include "break_weights" dict to customize scoring.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    target_min = cfg["target_min"]
    target_max = cfg["target_max"]
    hard_max = cfg["hard_max"]
    break_weights = cfg.get("break_weights")

    if not alignment:
        return []

    segments = []
    seg_start_idx = 0
    seg_start_time = alignment[0]["begin"]
    best_break_idx = None
    best_break_score = -1

    i = 0
    while i < len(alignment):
        w = alignment[i]
        elapsed = w["end"] - seg_start_time

        # Compute gap to next word
        if i + 1 < len(alignment):
            next_gap = alignment[i + 1]["begin"] - w["end"]
            next_word = alignment[i + 1]["word"]
        else:
            next_gap = 0
            next_word = None

        # Track best break point once we've reached minimum duration
        if elapsed >= target_min:
            score = get_break_score(w["word"], next_gap, next_word, break_weights)
            if score > best_break_score:
                best_break_score = score
                best_break_idx = i

        # Decision: cut at best break if we hit target max or hard max
        should_cut = False
        reason = ""

        if i == len(alignment) - 1:
            should_cut = True
            reason = "end_of_text"
            best_break_idx = i
        elif elapsed >= hard_max:
            should_cut = True
            reason = "hard_max"
            if best_break_idx is None:
                best_break_idx = i
        elif elapsed >= target_max and best_break_score >= 3:
            should_cut = True
            reason = "natural_break"
        elif elapsed >= target_min and best_break_score >= 8:
            should_cut = True
            reason = "strong_break"

        if should_cut and best_break_idx is not None:
            cut_idx = best_break_idx
            words_in_seg = [alignment[j]["word"] for j in range(seg_start_idx, cut_idx + 1)]
            seg = {
                "index": len(segments),
                "words": " ".join(words_in_seg),
                "start": seg_start_time,
                "end": alignment[cut_idx]["end"],
                "duration": round(alignment[cut_idx]["end"] - seg_start_time, 3),
                "word_count": len(words_in_seg),
                "is_filler": False,
                "break_reason": reason,
            }
            segments.append(seg)

            # Restart scanning from word after cut point
            next_idx = cut_idx + 1
            if next_idx < len(alignment):
                seg_start_idx = next_idx
                seg_start_time = alignment[next_idx]["begin"]
                best_break_idx = None
                best_break_score = -1
                i = next_idx
                continue
            else:
                break

        i += 1

    return segments


def merge_short(segments, config=None):
    """Post-process: merge segments shorter than hard_min with their neighbor."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    hard_min = cfg["hard_min"]

    if len(segments) <= 1:
        return segments

    merged = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        if seg["is_filler"]:
            merged.append(seg)
            i += 1
            continue

        if seg["duration"] < hard_min and merged:
            # Merge with previous non-filler segment
            prev = merged[-1]
            if not prev["is_filler"]:
                prev["words"] += " " + seg["words"]
                prev["end"] = seg["end"]
                prev["duration"] = round(prev["end"] - prev["start"], 3)
                prev["word_count"] += seg["word_count"]
                prev["break_reason"] = seg["break_reason"]
                i += 1
                continue

        merged.append(seg)
        i += 1

    # Re-index
    idx = 0
    for s in merged:
        s["index"] = idx
        idx += 1

    return merged


def fill_gaps(segments, config=None):
    """Post-process: insert silence fillers for gaps > gap_filler threshold.

    Long silence gaps (> MAX_SILENCE) are capped — the filler only covers
    MAX_SILENCE seconds and the remaining dead time is discarded.  This
    prevents a single long TTS paragraph pause from inflating one scene.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    gap_threshold = cfg["gap_filler"]
    MAX_SILENCE = cfg.get("max_silence", 2.0)  # cap silence fillers

    if not segments:
        return segments

    filled = []
    for i, seg in enumerate(segments):
        if i > 0:
            prev_end = filled[-1]["end"]
            gap = seg["start"] - prev_end
            if gap >= gap_threshold:
                # Cap long silences — only keep MAX_SILENCE worth of pause
                filler_dur = min(gap, MAX_SILENCE)
                filler = {
                    "index": 0,  # re-indexed later
                    "words": "",
                    "start": prev_end,
                    "end": round(prev_end + filler_dur, 3),
                    "duration": round(filler_dur, 3),
                    "word_count": 0,
                    "is_filler": True,
                    "break_reason": "silence" if gap <= MAX_SILENCE else "silence_capped",
                }
                filled.append(filler)
        filled.append(seg)

    # Re-index
    for idx, s in enumerate(filled):
        s["index"] = idx

    return filled


def run_segmenter(alignment, config=None, metadata=None):
    """Full pipeline: segment -> merge short -> fill gaps -> build output."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    meta = metadata or {}

    raw = segment(alignment, cfg)
    merged = merge_short(raw, cfg)
    final = fill_gaps(merged, cfg)

    # Compute stats
    speech_segs = [s for s in final if not s["is_filler"]]
    filler_segs = [s for s in final if s["is_filler"]]
    durations = [s["duration"] for s in speech_segs] if speech_segs else [0]
    total_duration = final[-1]["end"] - final[0]["start"] if final else 0

    output = {
        "metadata": {
            "project_id": meta.get("project_id", ""),
            "source_folder": meta.get("source_folder", ""),
            "style": meta.get("style", ""),
            "aspect_ratio": meta.get("aspect_ratio", ""),
            "transcript": meta.get("transcript", ""),
            "total_duration": round(total_duration, 3),
            "segmented_at": datetime.now().isoformat(),
        },
        "config": cfg,
        "segments": final,
        "stats": {
            "segment_count": len(speech_segs),
            "filler_count": len(filler_segs),
            "total_count": len(final),
            "avg_duration": round(sum(durations) / len(durations), 3),
            "min_duration": round(min(durations), 3),
            "max_duration": round(max(durations), 3),
        },
    }
    return output


def save_output(result, output_path):
    """Write segmenter result JSON to disk."""
    safe_json_write(output_path, result, indent=2)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(result):
    stats = result["stats"]
    segments = result["segments"]
    print()
    print(f"  Segments: {stats['segment_count']}  |  Fillers: {stats['filler_count']}  |  Total: {stats['total_count']}")
    print(f"  Duration: {result['metadata']['total_duration']:.1f}s  |  Avg: {stats['avg_duration']:.2f}s  |  Range: {stats['min_duration']:.2f}s - {stats['max_duration']:.2f}s")
    print()
    for s in segments:
        tag = "SILENCE" if s["is_filler"] else f"seg {s['index']:>2}"
        dur = f"{s['duration']:.2f}s"
        reason = s["break_reason"]
        words = s["words"][:60] + ("..." if len(s["words"]) > 60 else "")
        print(f"  [{tag}] {s['start']:6.2f} - {s['end']:6.2f}  ({dur:>6})  {reason:<14}  {words}")
    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scene Segmenter — split alignment into timed segments")
    parser.add_argument("input", help="Path to alignment JSON file")
    parser.add_argument("--target-min", type=float, default=DEFAULT_CONFIG["target_min"])
    parser.add_argument("--target-max", type=float, default=DEFAULT_CONFIG["target_max"])
    parser.add_argument("--hard-max", type=float, default=DEFAULT_CONFIG["hard_max"])
    parser.add_argument("--hard-min", type=float, default=DEFAULT_CONFIG["hard_min"])
    parser.add_argument("--gap-filler", type=float, default=DEFAULT_CONFIG["gap_filler"])
    parser.add_argument("-o", "--output", help="Output path (default: auto-generated)")
    args = parser.parse_args()

    config = {
        "target_min": args.target_min,
        "target_max": args.target_max,
        "hard_max": args.hard_max,
        "hard_min": args.hard_min,
        "gap_filler": args.gap_filler,
    }

    alignment, metadata = load_alignment(args.input)
    result = run_segmenter(alignment, config, metadata)

    if args.output:
        out_path = args.output
    else:
        from config import SEGMENTER_DIR, generate_project_id
        folder = generate_project_id("pm")
        out_path = os.path.join(SEGMENTER_DIR, folder, "segmented.json")

    save_output(result, out_path)
    print(f"  Saved: {out_path}")
    _print_summary(result)
