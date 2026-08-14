"""Timing Module — Force Alignment Service

The aligner itself, lifted out of the Flask blueprint (V2 `studio/timing/routes.py`)
so nothing has to import a `routes.py` to run alignment: `_run_alignment`,
`_validate_alignment`, `_fix_gaps_with_audio`, `_fix_zero_duration_words`, plus
the stable-ts model cache they share. `_step_timing` — the in-process pipeline
step — moves here too, from V2 `studio/pipeline/services.py`.
"""

import os
import re
import shutil
import threading
import time
import warnings
from datetime import datetime

import numpy as np
import soundfile as sf
from loguru import logger

from config import ALIGN_DIR
from scriptase.shared.io_utils import safe_json_write

# ---------------------------------------------------------------------------
# Alignment model (stable-ts / Whisper)
# ---------------------------------------------------------------------------
alignment_model = None
alignment_lock = threading.Lock()
alignment_available = None


def _check_alignment_available():
    global alignment_available
    if alignment_available is not None:
        return alignment_available
    try:
        import stable_whisper  # noqa: F401
        alignment_available = True
    except ImportError:
        alignment_available = False
    return alignment_available


def _load_alignment_model():
    global alignment_model
    if alignment_model is not None:
        return alignment_model
    import stable_whisper
    with alignment_lock:
        if alignment_model is None:
            alignment_model = stable_whisper.load_model("tiny.en")
    return alignment_model
def _run_alignment(wav_path, prompt_text):
    try:
        model = _load_alignment_model()
        audio, sr = sf.read(wav_path, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 16000:
            target_len = int(len(audio) * 16000 / sr)
            audio = np.interp(
                np.linspace(0, len(audio), target_len, endpoint=False),
                np.arange(len(audio), dtype=np.float32),
                audio,
            ).astype(np.float32)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = model.align(audio, prompt_text, language="en", fast_mode=True)
        for w in caught:
            msg = str(w.message)
            if "failed to align" in msg:
                logger.warning("Align partial: {}", msg)
            else:
                logger.debug("Align warning: {}", msg)
        alignment = []
        for w in result.all_words():
            word_text = w.word.strip()
            if word_text:
                alignment.append({
                    "word": word_text,
                    "begin": round(w.start, 3),
                    "end": round(w.end, 3),
                })
        # Post-process: validate and repair common alignment failures
        alignment = _validate_alignment(alignment, wav_path)
        return alignment if alignment else None
    except Exception:
        logger.exception("Alignment failed for {}", wav_path)
        return None


def _validate_alignment(alignment, wav_path=None):
    """Full alignment validation and repair pipeline.

    Catches and fixes:
    1. Zero-duration words (clustered at same timestamp)
    2. Out-of-order timestamps
    3. Overlapping words
    4. Large gaps where audio has speech (uses waveform energy)
    5. Words with end < begin (negative duration)
    """
    if not alignment:
        return alignment

    fixes = []

    # Step 1: Fix zero-duration word clusters
    alignment = _fix_zero_duration_words(alignment)
    zero_count = sum(1 for w in alignment if w["end"] - w["begin"] < 0.01)
    if zero_count:
        # Second pass: steal time from next word for remaining zero-dur
        for i in range(len(alignment)):
            if alignment[i]["end"] - alignment[i]["begin"] < 0.01 and i + 1 < len(alignment):
                alignment[i]["end"] = round(alignment[i]["begin"] + 0.05, 3)
                if alignment[i + 1]["begin"] < alignment[i]["end"]:
                    alignment[i + 1]["begin"] = alignment[i]["end"]
        fixed = zero_count - sum(1 for w in alignment if w["end"] - w["begin"] < 0.01)
        if fixed:
            fixes.append(f"fixed {fixed} zero-dur words")

    # Step 2: Fix negative durations (end < begin)
    for w in alignment:
        if w["end"] < w["begin"]:
            w["end"] = round(w["begin"] + 0.05, 3)
            fixes.append(f"fixed negative dur at {w['begin']:.2f}s")

    # Step 3: Sort by begin time (out-of-order words)
    was_sorted = all(alignment[i]["begin"] <= alignment[i + 1]["begin"]
                     for i in range(len(alignment) - 1))
    if not was_sorted:
        alignment.sort(key=lambda w: w["begin"])
        fixes.append("re-sorted out-of-order words")

    # Step 4: Fix overlaps (word end > next word begin)
    for i in range(len(alignment) - 1):
        if alignment[i]["end"] > alignment[i + 1]["begin"] + 0.001:
            alignment[i]["end"] = round(alignment[i + 1]["begin"], 3)

    # Step 5: Detect large gaps where audio has speech
    # If we have the audio file, check waveform energy in gap regions
    if wav_path:
        try:
            alignment = _fix_gaps_with_audio(alignment, wav_path)
        except Exception as e:
            logger.debug("Gap detection skipped: {}", e)

    if fixes:
        logger.info("Alignment validation: {}", ", ".join(fixes))

    return alignment


def _fix_gaps_with_audio(alignment, wav_path):
    """Detect gaps > 2s where audio has speech and redistribute words."""
    import numpy as np

    audio, sr = sf.read(wav_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    def has_speech(start_s, end_s, threshold=0.01):
        """Check if audio region has speech energy."""
        s = int(start_s * sr)
        e = int(end_s * sr)
        if s >= len(audio) or e > len(audio) or s >= e:
            return False
        rms = np.sqrt(np.mean(audio[s:e] ** 2))
        return rms > threshold

    # Find gaps > 2s between consecutive words
    for i in range(len(alignment) - 1):
        gap_start = alignment[i]["end"]
        gap_end = alignment[i + 1]["begin"]
        gap = gap_end - gap_start

        if gap <= 2.0:
            continue

        # Check if there's speech in the gap
        if not has_speech(gap_start + 0.2, gap_end - 0.2):
            continue  # genuine silence, leave it

        # Speech detected in gap — find the run of words that should fill it
        # Collect all words from i+1 until we find one with proper duration
        run_start = i + 1
        run_end = run_start
        while run_end < len(alignment) and alignment[run_end]["end"] - alignment[run_end]["begin"] < 0.1:
            run_end += 1

        if run_end - run_start < 3:
            continue  # not enough words to fix

        # Find where speech actually ends (scan audio for silence)
        speech_end = gap_end
        for t in range(int(gap_end * 10), int(min(gap_end + 15, len(audio) / sr) * 10)):
            t_s = t / 10.0
            if not has_speech(t_s, t_s + 0.2, threshold=0.008):
                speech_end = t_s
                break

        # Redistribute words across the speech region
        time_start = gap_start + 0.1
        time_end = speech_end
        count = run_end - run_start
        if time_end > time_start and count > 0:
            slot = (time_end - time_start) / count
            for j in range(run_start, run_end):
                offset = j - run_start
                alignment[j]["begin"] = round(time_start + offset * slot, 3)
                alignment[j]["end"] = round(time_start + (offset + 1) * slot, 3)
            logger.info("Alignment gap fix: redistributed {} words across {:.1f}-{:.1f}s",
                        count, time_start, time_end)

    return alignment


def _fix_zero_duration_words(alignment):
    """Redistribute zero-duration words evenly across their time window.

    Whisper alignment sometimes fails to timestamp words after long silences,
    collapsing many words into begin==end at the same instant.  This finds
    all words clustered at the same timestamp and spreads them evenly across
    the time window up to the next properly-spaced word.
    """
    if not alignment:
        return alignment

    # Find clusters: groups of words sharing the same begin timestamp (within 0.02s)
    i = 0
    while i < len(alignment):
        w = alignment[i]
        # Look for a cluster: 3+ words within 0.02s of each other
        cluster_start = i
        cluster_time = w["begin"]
        while i < len(alignment) and abs(alignment[i]["begin"] - cluster_time) < 0.02:
            i += 1
        cluster_end = i  # exclusive
        cluster_count = cluster_end - cluster_start

        if cluster_count < 3:
            continue  # not a cluster, skip

        # Find the time window to redistribute into:
        # Start: the cluster timestamp (or prev word's end if earlier)
        time_start = cluster_time
        if cluster_start > 0:
            time_start = max(time_start, alignment[cluster_start - 1]["end"])

        # End: scan forward for a word with a different timestamp AND real duration
        time_end = time_start + 2.0  # fallback: 2 seconds
        for j in range(cluster_end, min(cluster_end + 20, len(alignment))):
            if alignment[j]["begin"] - cluster_time > 0.1 and alignment[j]["end"] - alignment[j]["begin"] >= 0.05:
                time_end = alignment[j]["begin"]
                break

        # Include any short-duration words between cluster and time_end
        # (they might be partially-timed words from the same failed region)
        actual_end = cluster_end
        for j in range(cluster_end, min(cluster_end + 10, len(alignment))):
            if alignment[j]["begin"] < time_end and alignment[j]["end"] - alignment[j]["begin"] < 0.05:
                actual_end = j + 1
            else:
                break

        total_words = actual_end - cluster_start
        if time_end > time_start and total_words > 0:
            slot = (time_end - time_start) / total_words
            for j in range(cluster_start, actual_end):
                offset = j - cluster_start
                alignment[j]["begin"] = round(time_start + offset * slot, 3)
                alignment[j]["end"] = round(time_start + (offset + 1) * slot, 3)

    return alignment


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------

def _step_timing(tts_result, config, project_id):
    """Run force alignment on TTS output."""
    wav_path = tts_result["wav_path"]
    clean_text = re.sub(r'[\[\]*_#`~]', '', config["text"]).strip()
    clean_text = re.sub(r'\s+', ' ', clean_text)

    start = time.perf_counter()
    alignment = _run_alignment(wav_path, clean_text)
    elapsed = time.perf_counter() - start

    if not alignment:
        raise RuntimeError("Alignment produced no results")

    # Save to alignment directory
    folder_name = tts_result["folder"]
    align_dir = os.path.join(ALIGN_DIR, folder_name)
    os.makedirs(align_dir, exist_ok=True)

    dest_audio = os.path.join(align_dir, tts_result["filename"])
    if not os.path.exists(dest_audio):
        shutil.copy2(wav_path, dest_audio)

    result_data = {
        "project_id": project_id,
        "source_file": tts_result["filename"],
        "folder": folder_name,
        "transcript": clean_text,
        "alignment": alignment,
        "word_count": len(alignment),
        "inference_time": round(elapsed, 3),
        "timestamp": datetime.now().isoformat(),
    }

    safe_json_write(os.path.join(align_dir, "alignment.json"), result_data, indent=2)

    logger.success("Pipeline Alignment: {} words in {:.2f}s",
                   len(alignment), elapsed)
    return result_data
