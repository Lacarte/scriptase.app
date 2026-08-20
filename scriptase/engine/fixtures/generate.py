"""Deterministic sample-fixture generator (step 2.5, contracts.md §10).

Regenerates every file in scriptase/engine/fixtures/ from a tiny canonical
script — no live providers, no network, no timestamps, no absolute paths.
Media is produced locally: WAVs via the stdlib wave module, images via
Pillow, and the tiny MP4 via ffmpeg in bitexact mode.

Run from the repository root:

    python scriptase/engine/fixtures/generate.py

The committed bytes plus manifest SHA-256 values are canonical; the script
exists so the set can be reproduced and audited without provider access.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent
REPO_ROOT = FIXTURES_DIR.parents[2]
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw  # noqa: E402  (after sys.path fix)

from scriptase.engine.sample_data import (  # noqa: E402
    CANONICAL_AUDIO_SECONDS,
    FIXTURE_SCHEMA_VERSION,
    SAMPLE_PROJECT_ID,
    validate_fixtures,
)

MEDIA_DIR = FIXTURES_DIR / "media"
FIXED_TIMESTAMP = "2026-01-01T00:00:00Z"
SAMPLE_RATE = 8000
MUSIC_SECONDS = 2.0

SCRIPT_TEXT = (
    "A lighthouse keeper climbs the spiral stairs at dusk. "
    "The lamp turns, sweeping gold across the waves. "
    "Far below, a small boat finds its way home. "
    "The keeper smiles, writes the date in the log, and watches the stars arrive."
)

SENTENCES = [
    "A lighthouse keeper climbs the spiral stairs at dusk.",
    "The lamp turns, sweeping gold across the waves.",
    "Far below, a small boat finds its way home. The keeper smiles, writes the "
    "date in the log, and watches the stars arrive.",
]

IMAGE_PROMPTS = [
    "wide shot, a lighthouse keeper climbing a spiral staircase at dusk, warm "
    "lantern light on stone walls, deep blue evening sky through narrow windows",
    "close-up, the great lighthouse lamp turning, a beam of golden light sweeping "
    "across dark rolling waves, spray catching the glow",
    "aerial shot, a small fishing boat following the light home to a quiet harbor, "
    "stars appearing above a calm indigo sea",
]

WORD_STEP = 0.17
WORD_LENGTH = 0.15
FIRST_WORD_AT = 0.7


def _round(value: float) -> float:
    return round(value, 2)


def _words() -> list[str]:
    return SCRIPT_TEXT.replace(",", "").replace(".", "").split()


def _alignment_words() -> list[dict]:
    entries = []
    for index, word in enumerate(_words()):
        begin = _round(FIRST_WORD_AT + index * WORD_STEP)
        entries.append({"word": word, "begin": begin, "end": _round(begin + WORD_LENGTH)})
    return entries


def _sentence_spans(words: list[dict]) -> list[tuple[int, int]]:
    """Word-index ranges per sentence: 9 + 8 + 23 words."""
    counts = [len(sentence.replace(",", "").replace(".", "").split()) for sentence in SENTENCES]
    spans, cursor = [], 0
    for count in counts:
        spans.append((cursor, cursor + count))
        cursor += count
    assert cursor == len(words), "sentence spans must cover the canonical script"
    return spans


def _write_json(name: str, payload: dict) -> None:
    path = FIXTURES_DIR / name
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _write_wav(path: Path, seconds: float, frequencies: list[float], amplitude: int) -> None:
    frame_count = int(SAMPLE_RATE * seconds)
    frames = bytearray()
    for index in range(frame_count):
        t = index / SAMPLE_RATE
        # Gentle fade at both ends so the tone never clicks.
        envelope = min(1.0, index / 400, (frame_count - index) / 400)
        value = sum(math.sin(2 * math.pi * freq * t) for freq in frequencies)
        frames += struct.pack("<h", int(amplitude * envelope * value / len(frequencies)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))


def _paint_gradient(width: int, height: int, top: tuple, bottom: tuple) -> Image.Image:
    image = Image.new("RGB", (width, height))
    for y in range(height):
        mix = y / max(1, height - 1)
        row = tuple(int(top[i] + (bottom[i] - top[i]) * mix) for i in range(3))
        for x in range(width):
            image.putpixel((x, y), row)
    return image


def _write_storyboard_png(path: Path) -> None:
    image = _paint_gradient(90, 160, (24, 32, 64), (8, 10, 24))
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 60, 50, 130], fill=(230, 220, 180))       # lighthouse tower
    draw.polygon([(38, 60), (52, 60), (45, 46)], fill=(200, 60, 50))  # roof
    draw.ellipse([41, 52, 49, 60], fill=(255, 214, 120))          # lamp
    image.save(path, format="PNG", optimize=True)


def _write_scene_jpg(path: Path) -> None:
    image = _paint_gradient(90, 160, (16, 40, 72), (4, 8, 20))
    draw = ImageDraw.Draw(image)
    draw.polygon([(30, 120), (60, 120), (45, 108)], fill=(120, 90, 60))  # boat hull
    draw.line([(45, 108), (45, 88)], fill=(220, 220, 220), width=2)      # mast
    image.save(path, format="JPEG", quality=80)


def _write_logo_png(path: Path) -> None:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([4, 4, 60, 60], outline=(78, 205, 196, 255), width=4)
    draw.ellipse([24, 24, 40, 40], fill=(255, 214, 120, 255))
    image.save(path, format="PNG", optimize=True)


def _write_scene_mp4(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to generate the sample MP4")
    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=0x18284a:s=90x160:r=12:d=1",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "35", "-map_metadata", "-1",
            "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-movflags", "+faststart",
            str(path),
        ],
        check=True,
    )


def _media_info(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        with wave.open(str(path), "rb") as handle:
            return {
                "kind": "audio/wav",
                "duration_seconds": round(handle.getnframes() / handle.getframerate(), 3),
                "sample_rate": handle.getframerate(),
            }
    if suffix in {".png", ".jpg", ".jpeg"}:
        with Image.open(path) as image:
            return {"kind": f"image/{image.format.lower()}", "width": image.width, "height": image.height}
    if suffix == ".mp4":
        return {"kind": "video/mp4", "width": 90, "height": 160, "duration_seconds": 1.0}
    return {"kind": "binary"}


def build() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    words = _alignment_words()
    spans = _sentence_spans(words)
    duration = CANONICAL_AUDIO_SECONDS

    # ── media ────────────────────────────────────────────────────────────
    _write_wav(MEDIA_DIR / "voice.wav", duration, [220.0, 330.0], amplitude=9000)
    _write_wav(MEDIA_DIR / "music.wav", MUSIC_SECONDS, [110.0, 165.0], amplitude=4000)
    _write_storyboard_png(MEDIA_DIR / "storyboard.png")
    _write_scene_jpg(MEDIA_DIR / "scene.jpg")
    _write_logo_png(MEDIA_DIR / "logo.png")
    _write_scene_mp4(MEDIA_DIR / "scene.mp4")

    # ── script / tts / audio ─────────────────────────────────────────────
    _write_json("script.json", {
        "project_id": SAMPLE_PROJECT_ID,
        "text": SCRIPT_TEXT,
        "word_count": len(words),
    })
    _write_json("tts.json", {
        "artifact_refs": ["media/voice.wav"],
        "duration_seconds": duration,
        "filename": "voice.wav",
        "folder": SAMPLE_PROJECT_ID,
        "model": "sample-fixture",
        "project_id": SAMPLE_PROJECT_ID,
        "prompt": SCRIPT_TEXT,
        "provider": "sample",
        "sample_rate": SAMPLE_RATE,
        "speed": 1.0,
        "timestamp": FIXED_TIMESTAMP,
        "voice": "Ashley",
        "wav_path": "media/voice.wav",
        "words": len(words),
    })
    _write_json("audio_file.json", {
        "artifact_refs": ["media/voice.wav"],
        "duration_seconds": duration,
        "filename": "voice.wav",
        "folder": SAMPLE_PROJECT_ID,
        "sample_rate": SAMPLE_RATE,
        "wav_path": "media/voice.wav",
    })

    # ── alignment ────────────────────────────────────────────────────────
    _write_json("alignment.json", {
        "alignment": words,
        "folder": SAMPLE_PROJECT_ID,
        "inference_time": 0.0,
        "project_id": SAMPLE_PROJECT_ID,
        "source_file": "voice.wav",
        "timestamp": FIXED_TIMESTAMP,
        "transcript": SCRIPT_TEXT,
        "word_count": len(words),
    })

    # ── segments (3 non-filler, one per sentence) ────────────────────────
    segments = []
    for index, (start_word, end_word) in enumerate(spans):
        start = words[start_word]["begin"]
        end = words[end_word - 1]["end"]
        segments.append({
            "break_reason": "strong_break",
            "duration": _round(end - start),
            "end": end,
            "index": index,
            "is_filler": False,
            "start": start,
            "word_count": end_word - start_word,
            "words": SENTENCES[index],
        })
    _write_json("segmented.json", {
        "config": {
            "target_min": 1.5, "target_max": 4.0, "hard_max": 5.0,
            "hard_min": 0.8, "gap_filler": 0.3,
        },
        "metadata": {
            "aspect_ratio": "9:16",
            "project_id": SAMPLE_PROJECT_ID,
            "segmented_at": FIXED_TIMESTAMP,
            "source_folder": SAMPLE_PROJECT_ID,
            "style": "cinematic",
            "total_duration": duration,
            "transcript": SCRIPT_TEXT,
        },
        "segments": segments,
    })

    # ── scenes / image prompts ───────────────────────────────────────────
    timeline_edges = [0.0, segments[1]["start"], segments[2]["start"], duration]
    scenes = []
    for index, segment in enumerate(segments):
        scenes.append({
            "duration": _round(timeline_edges[index + 1] - timeline_edges[index]),
            "image_prompt": IMAGE_PROMPTS[index],
            "index": index,
            "narrative_role": ["hook", "escalation", "release"][index],
            "segment_end": segment["end"],
            "segment_start": segment["start"],
            "segment_words": segment["words"],
            "shot_type": ["wide", "close", "aerial"][index],
            "timeline_end": timeline_edges[index + 1],
            "timeline_start": timeline_edges[index],
            "title": ["The Climb", "The Beam", "The Way Home"][index],
            "type_of_scene": "video",
        })
    _write_json("scenes.json", {
        "analysis": {
            "core_theme": "A keeper's steady light guides a small boat home.",
            "mood": "Calm, warm, hopeful.",
            "tone": "gentle",
            "visual_style": "Painterly coastal dusk with warm lamplight.",
        },
        "project_id": SAMPLE_PROJECT_ID,
        "scenes": scenes,
        "source_folder": SAMPLE_PROJECT_ID,
        "style": "cinematic",
        "timestamp": FIXED_TIMESTAMP,
        "total_duration": duration,
    })
    _write_json("image_prompts.json", {
        "project_id": SAMPLE_PROJECT_ID,
        "prompts": [
            {"image_prompt": scene["image_prompt"], "index": scene["index"]}
            for scene in scenes
        ],
    })

    # ── storyboard / animation assets ────────────────────────────────────
    _write_json("storyboard.json", {
        "artifact_refs": ["media/storyboard.png"],
        "aspect_ratio": "9:16",
        "errors": 0,
        "project_id": SAMPLE_PROJECT_ID,
        "ready": 3,
        "scene_statuses": {
            str(index): {
                "image_url": None,
                "local_path": "media/storyboard.png",
                "status": "ready",
            }
            for index in range(3)
        },
        "status": "done",
        "total": 3,
    })
    scene_media = ["media/scene.mp4", "media/scene.jpg", "media/scene.mp4"]
    _write_json("metadata.json", {
        "artifact_refs": ["media/scene.mp4", "media/scene.jpg"],
        "errors": 0,
        "project_id": SAMPLE_PROJECT_ID,
        "provider": "grok_automa",
        "ready": 3,
        "scenes": {
            str(index): {
                "file_count": 1,
                "local_files": [scene_media[index]],
                "scene": str(index),
                "source_urls": [],
            }
            for index in range(3)
        },
        "total": 3,
    })

    # ── captions (3 words per group) ─────────────────────────────────────
    captions = []
    for start_word in range(0, len(words), 3):
        group = words[start_word:start_word + 3]
        captions.append({
            "end": group[-1]["end"],
            "start": group[0]["begin"],
            "text": " ".join(item["word"] for item in group),
            "words": group,
        })
    _write_json("captions.json", {
        "captions": captions,
        "preset": "bold_popup",
        "project_id": SAMPLE_PROJECT_ID,
        "source_folder": SAMPLE_PROJECT_ID,
    })

    # ── music track ──────────────────────────────────────────────────────
    _write_json("music_track.json", {
        "artifact_refs": ["media/music.wav"],
        "ducking_enabled": True,
        "ducking_level": 0.2,
        "duration_seconds": MUSIC_SECONDS,
        "fade_in": 2.0,
        "fade_out": 3.0,
        "loop": True,
        "title": "Sample Tone",
        "track_ref": "media/music.wav",
        "volume": 0.15,
    })

    # ── editor project ───────────────────────────────────────────────────
    _write_json("initial.json", {
        "artifact_refs": [
            "media/scene.mp4", "media/scene.jpg", "media/voice.wav", "media/music.wav",
        ],
        "audio_tracks": [
            {
                "duckingEnabled": False, "duckingLevel": 0.2, "duration": duration,
                "fadeIn": 0, "fadeOut": 0, "file": "voice.wav", "id": "at_voice",
                "label": "Voice", "loop": False, "muted": False,
                "path": "media/voice.wav", "startOffset": 0, "timelineOffset": 0,
                "trimmedDuration": None, "type": "voice", "volume": 1,
            },
            {
                "duckingEnabled": True, "duckingLevel": 0.2, "duration": MUSIC_SECONDS,
                "fadeIn": 2.0, "fadeOut": 3.0, "file": "music.wav", "id": "at_music",
                "label": "Music", "loop": True, "muted": False,
                "path": "media/music.wav", "startOffset": 0, "timelineOffset": 0,
                "trimmedDuration": None, "type": "music", "volume": 0.15,
            },
        ],
        "captions": captions,
        "captionsEnabled": True,
        "disabled_tracks": [],
        "edit_history": [],
        "grain_overlay": False,
        "history_index": -1,
        "project_id": SAMPLE_PROJECT_ID,
        "project_name": "Sample Project",
        "saved_at": FIXED_TIMESTAMP,
        "scene_count": 3,
        "scenes": [
            {
                "duration": scene["duration"],
                "effect": {"type": "none"},
                "id": scene["index"],
                "image": "",
                "image_prompt": scene["image_prompt"],
                "mediaUrl": scene_media[scene["index"]],
                "scene_id": scene["index"],
                "scene_type": scene["narrative_role"],
                "transition": {"duration": 0, "type": "none"},
                "type": "video" if scene_media[scene["index"]].endswith(".mp4") else "image",
                "visual_fx": "static",
            }
            for scene in scenes
        ],
        "source_folder": SAMPLE_PROJECT_ID,
        "style": "cinematic",
        "total_duration": duration,
    })

    # ── project settings ─────────────────────────────────────────────────
    _write_json("project_settings.json", {
        "artifact_refs": ["media/logo.png"],
        "aspect_ratio": "9:16",
        "channel_name": "Sample Channel",
        "logo": {"filename": "logo.png", "path": "media/logo.png"},
        "logo_enabled": True,
        "logo_margin": 32,
        "logo_opacity": 0.9,
        "logo_position": "top_right",
        "logo_size": 10,
        "project_name": "Sample Project",
        "style": "cinematic",
        "tone": "gentle",
    })

    # ── video file ───────────────────────────────────────────────────────
    _write_json("video_file.json", {
        "artifact_refs": ["media/scene.mp4"],
        "path": "media/scene.mp4",
        "profile": "yt_shorts",
    })

    # ── manifest ─────────────────────────────────────────────────────────
    port_types_by_file = {
        "script.json": ["text", "script"],
        "audio_file.json": ["audio_file"],
        "tts.json": ["tts_metadata"],
        "alignment.json": ["alignment"],
        "segmented.json": ["segments"],
        "scenes.json": ["scenes"],
        "image_prompts.json": ["image_prompts"],
        "storyboard.json": ["storyboard_images"],
        "metadata.json": ["animation_assets"],
        "captions.json": ["captions"],
        "music_track.json": ["music_track"],
        "initial.json": ["editor_project"],
        "project_settings.json": ["project_settings"],
        "video_file.json": ["video_file"],
        "media/voice.wav": ["audio_file", "tts_metadata"],
        "media/music.wav": ["music_track"],
        "media/storyboard.png": ["storyboard_images"],
        "media/scene.jpg": ["animation_assets", "editor_project"],
        "media/scene.mp4": ["animation_assets", "editor_project", "video_file"],
        "media/logo.png": ["project_settings"],
    }
    files = {}
    for relpath in sorted(port_types_by_file):
        path = FIXTURES_DIR / relpath
        data = path.read_bytes()
        entry = {
            "bytes": len(data),
            "port_types": port_types_by_file[relpath],
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if path.suffix.lower() in {".wav", ".png", ".jpg", ".jpeg", ".mp4"}:
            entry["media"] = _media_info(path)
        files[relpath] = entry
    _write_json("manifest.json", {
        "canonical_audio_seconds": CANONICAL_AUDIO_SECONDS,
        "files": files,
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "generated_by": "scriptase/engine/fixtures/generate.py",
        "project_id": SAMPLE_PROJECT_ID,
    })


def main() -> int:
    build()
    problems = validate_fixtures()
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        return 1
    total = sum(
        path.stat().st_size for path in FIXTURES_DIR.rglob("*")
        if path.is_file() and path.name != "generate.py"
    )
    print(f"Fixture set OK — {total / 1024:.0f} KiB under {FIXTURES_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
