"""TTS Audio Processing Helpers

Padding, chunk concatenation with crossfade, and loudnorm via ffmpeg.
"""

import os
import subprocess
import json

import numpy as np
import soundfile as sf
from loguru import logger

from scriptase.shared.ffmpeg_utils import find_ffmpeg


def pad_audio(audio, sample_rate=24000, pad_ms=50):
    """Prepend/append short silence to prevent clipping on hard consonants."""
    pad = np.zeros(int(sample_rate * pad_ms / 1000), dtype=np.float32)
    return np.concatenate([pad, audio, pad])


def concatenate_chunks(chunks: list, sample_rate: int = 24000,
                       gap_ms: int = 80, crossfade_ms: int = 20) -> np.ndarray:
    """Concatenate audio chunks with silence gaps and crossfade."""
    if not chunks:
        return np.array([], dtype=np.float32)
    flat = [c.squeeze() for c in chunks]
    if len(flat) == 1:
        return flat[0]

    gap_samples = int(sample_rate * gap_ms / 1000)
    xfade_samples = int(sample_rate * crossfade_ms / 1000)
    silence = np.zeros(gap_samples, dtype=np.float32)

    parts = []
    for i, chunk in enumerate(flat):
        if i == 0:
            parts.append(chunk)
            continue
        prev = parts[-1]
        if xfade_samples > 0 and len(prev) >= xfade_samples and len(chunk) >= xfade_samples:
            fade_out = np.linspace(1.0, 0.0, xfade_samples, dtype=np.float32)
            fade_in = np.linspace(0.0, 1.0, xfade_samples, dtype=np.float32)
            tail = prev[-xfade_samples:] * fade_out
            head = chunk[:xfade_samples] * fade_in
            parts[-1] = prev[:-xfade_samples]
            parts.append(tail + head)
            parts.append(silence)
            parts.append(chunk[xfade_samples:])
        else:
            parts.append(silence)
            parts.append(chunk)

    return np.concatenate(parts)


def _parse_loudnorm_stats(stderr: str) -> dict | None:
    """Extract measured loudness stats from ffmpeg loudnorm pass-1 output."""
    # loudnorm prints a JSON block in its summary output
    idx = stderr.rfind('"input_i"')
    if idx == -1:
        return None
    # Walk back to the opening brace
    brace = stderr.rfind('{', 0, idx)
    if brace == -1:
        return None
    end = stderr.find('}', idx)
    if end == -1:
        return None
    try:
        return json.loads(stderr[brace:end + 1])
    except Exception:
        return None


def run_loudnorm(wav_path):
    """Normalize audio volume using two-pass ffmpeg loudnorm. Overwrites in-place.

    Two-pass avoids the "settling" artefact that distorts the first ~100 ms of
    audio in single-pass mode.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False
    tmp_path = wav_path + ".tmp.wav"
    try:
        try:
            info = sf.info(wav_path)
            sr = info.samplerate
        except Exception:
            sr = 24000

        # ── Pass 1: measure loudness stats ──
        pass1 = subprocess.run(
            [ffmpeg, "-nostdin", "-y", "-i", wav_path,
             "-af", "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json",
             "-f", "null", os.devnull],
            capture_output=True, timeout=60,
        )
        if pass1.returncode != 0:
            stderr = pass1.stderr.decode(errors='replace')
            logger.error("loudnorm pass-1 failed (rc={}): {}", pass1.returncode, stderr[-500:])
            return False

        stats = _parse_loudnorm_stats(pass1.stderr.decode(errors='replace'))
        if not stats:
            logger.warning("Could not parse loudnorm stats – falling back to single-pass")
            # Fallback: single-pass with relaxed TP
            af = "loudnorm=I=-16:LRA=11:TP=-1.5"
        else:
            af = (
                f"loudnorm=I=-16:LRA=11:TP=-1.5"
                f":measured_I={stats['input_i']}"
                f":measured_LRA={stats['input_lra']}"
                f":measured_TP={stats['input_tp']}"
                f":measured_thresh={stats['input_thresh']}"
                f":linear=true"
            )

        # ── Pass 2: apply correction with known measurements ──
        pass2 = subprocess.run(
            [ffmpeg, "-nostdin", "-y", "-i", wav_path,
             "-af", af,
             "-ar", str(sr), "-ac", "1",
             tmp_path],
            capture_output=True, timeout=60,
        )
        if pass2.returncode == 0 and os.path.exists(tmp_path):
            os.replace(tmp_path, wav_path)
            return True
        else:
            stderr = pass2.stderr.decode(errors='replace')
            err_lines = [ln for ln in stderr.splitlines()
                         if ln.strip() and not ln.startswith(('  ', 'ffmpeg version', '(c)', 'built with', 'configuration:', 'lib'))]
            err_msg = '\n'.join(err_lines[-5:]) if err_lines else stderr[-500:]
            logger.error("ffmpeg loudnorm pass-2 failed (rc={}): {}", pass2.returncode, err_msg)
            return False
    except subprocess.TimeoutExpired:
        logger.warning("Loudnorm timed out for {}", wav_path)
        return False
    except Exception:
        logger.exception("Loudnorm error for {}", wav_path)
        return False
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
