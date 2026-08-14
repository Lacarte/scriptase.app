"""Deterministic technical validators (step 7.1 / §12.4).

These checks run before any semantic AI review and never call a provider.
Each failure emits a structured :class:`TechnicalIssue` — free-form text is
not an acceptable review output (contracts.md §9).

Checks covered (§12.4 examples):

* ``file_exists``
* ``readable_media``
* ``resolution``
* ``duration``
* ``aspect_ratio``
* ``audio_presence``
* ``frame_count``
* ``expected_artifact_count``

Step 7.2 persists these as full ``ReviewIssue`` documents via
:func:`scriptase.review.store.create_from_technical`. The fields here already
align with that schema so the upgrade is additive.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import wave
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scriptase.shared.ffmpeg_utils import find_ffprobe

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

TECHNICAL_CHECK_IDS: tuple[str, ...] = (
    "file_exists",
    "readable_media",
    "resolution",
    "duration",
    "aspect_ratio",
    "audio_presence",
    "frame_count",
    "expected_artifact_count",
)

TechnicalCheckId = Literal[
    "file_exists",
    "readable_media",
    "resolution",
    "duration",
    "aspect_ratio",
    "audio_presence",
    "frame_count",
    "expected_artifact_count",
]

Severity = Literal["low", "medium", "high", "critical"]
SuggestedAction = Literal["regenerate", "re-prompt", "adjust", "escalate", "accept"]

_REASON_MAX = 500
_INSTRUCTION_MAX = 500

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})
_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"})
_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"})

_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def _strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _bound(text: str, limit: int = _REASON_MAX) -> str:
    text = _strip(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _relative_ref(path: str | None) -> str | None:
    """Return a path safe for issue payloads — never absolute."""
    text = _strip(path)
    if not text:
        return None
    if _ABSOLUTE_PATH_RE.match(text):
        return os.path.basename(text.replace("\\", "/"))
    return text.replace("\\", "/")


# ---------------------------------------------------------------------------
# Structured issue model
# ---------------------------------------------------------------------------


class TechnicalIssue(BaseModel):
    """Structured technical-review finding (contracts.md §9 precursor).

    Free text alone is never a valid result: every issue carries a machine
    ``check_id``, ``issue_type``, ``severity``, ``confidence``, and structured
    ``observed`` / ``expected`` maps. ``reason`` and ``repair_instruction`` are
    human-readable but bounded and always accompanied by the structured fields.
    """

    model_config = ConfigDict(extra="forbid")

    check_id: TechnicalCheckId
    issue_type: Literal["technical_defect"] = "technical_defect"
    severity: Severity
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=_REASON_MAX)
    suggested_action: SuggestedAction = "regenerate"
    repair_instruction: str = Field(default="", max_length=_INSTRUCTION_MAX)
    target_node_id: str | None = None
    target_artifact_id: str | None = None
    scene_id: str | None = None
    path_ref: str | None = None
    observed: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reason", "repair_instruction", mode="before")
    @classmethod
    def _bound_text(cls, value: Any) -> str:
        return _bound(_strip(value) if value is not None else "")

    @field_validator("target_node_id", "target_artifact_id", "scene_id", "path_ref", mode="before")
    @classmethod
    def _optional(cls, value: Any) -> str | None:
        text = _strip(value)
        return text or None

    @field_validator("path_ref", mode="after")
    @classmethod
    def _no_absolute_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _ABSOLUTE_PATH_RE.match(value):
            return os.path.basename(value.replace("\\", "/"))
        return value.replace("\\", "/")

    @field_validator("observed", "expected", mode="before")
    @classmethod
    def _dict(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("observed/expected must be mappings")
        return dict(value)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class TechnicalContext:
    """Optional attribution attached to every issue from a check."""

    target_node_id: str | None = None
    target_artifact_id: str | None = None
    scene_id: str | None = None
    path_ref: str | None = None  # managed relative path; never absolute

    def bind(self, issue_kwargs: dict[str, Any]) -> dict[str, Any]:
        out = dict(issue_kwargs)
        if self.target_node_id and not out.get("target_node_id"):
            out["target_node_id"] = self.target_node_id
        if self.target_artifact_id and not out.get("target_artifact_id"):
            out["target_artifact_id"] = self.target_artifact_id
        if self.scene_id and not out.get("scene_id"):
            out["scene_id"] = self.scene_id
        path_ref = _relative_ref(out.get("path_ref") or self.path_ref)
        if path_ref:
            out["path_ref"] = path_ref
        return out


def _issue(
    check_id: TechnicalCheckId,
    *,
    severity: Severity,
    reason: str,
    suggested_action: SuggestedAction = "regenerate",
    repair_instruction: str = "",
    observed: Mapping[str, Any] | None = None,
    expected: Mapping[str, Any] | None = None,
    context: TechnicalContext | None = None,
    confidence: float = 1.0,
) -> TechnicalIssue:
    payload = {
        "check_id": check_id,
        "issue_type": "technical_defect",
        "severity": severity,
        "confidence": confidence,
        "reason": reason,
        "suggested_action": suggested_action,
        "repair_instruction": repair_instruction
        or f"Repair the {check_id.replace('_', ' ')} defect and re-run technical validation.",
        "observed": dict(observed or {}),
        "expected": dict(expected or {}),
    }
    if context is not None:
        payload = context.bind(payload)
    return TechnicalIssue.model_validate(payload)


# ---------------------------------------------------------------------------
# Media probe (deterministic, no provider)
# ---------------------------------------------------------------------------


@dataclass
class MediaProbe:
    """Local filesystem media facts used by technical validators."""

    path: str
    exists: bool = False
    readable: bool = False
    kind: str | None = None  # image | audio | video | unknown
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    frame_count: int | None = None
    has_audio: bool | None = None
    sample_rate: int | None = None
    channels: int | None = None
    error_code: str | None = None  # machine code, not free text
    details: dict[str, Any] = field(default_factory=dict)


def _suffix(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _guess_kind(path: str) -> str | None:
    suffix = _suffix(path)
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _AUDIO_SUFFIXES:
        return "audio"
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    return None


def _probe_image(path: str, probe: MediaProbe) -> MediaProbe:
    from PIL import Image

    try:
        with Image.open(path) as image:
            image.load()
            probe.readable = True
            probe.kind = "image"
            probe.width = int(image.width)
            probe.height = int(image.height)
            probe.details["format"] = image.format
            probe.details["mode"] = image.mode
    except Exception:
        probe.readable = False
        probe.error_code = "image_unreadable"
    return probe


def _probe_wav(path: str, probe: MediaProbe) -> MediaProbe:
    try:
        with wave.open(path, "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            channels = handle.getnchannels()
            probe.readable = True
            probe.kind = "audio"
            probe.sample_rate = rate
            probe.channels = channels
            probe.frame_count = frames
            probe.duration_seconds = (frames / float(rate)) if rate else 0.0
            probe.has_audio = frames > 0 and channels > 0
    except Exception:
        # Non-WAV audio (mp3/flac/…) — try soundfile when present.
        try:
            import soundfile as sf

            info = sf.info(path)
            probe.readable = True
            probe.kind = "audio"
            probe.sample_rate = int(info.samplerate)
            probe.channels = int(info.channels)
            probe.frame_count = int(info.frames)
            probe.duration_seconds = float(info.duration)
            probe.has_audio = info.frames > 0 and info.channels > 0
        except Exception:
            probe.readable = False
            probe.error_code = "audio_unreadable"
    return probe


def _ffprobe_json(path: str) -> dict[str, Any] | None:
    binary = find_ffprobe()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [
                binary,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _parse_fraction(value: Any) -> float | None:
    text = _strip(value)
    if not text or text in {"0/0", "N/A"}:
        return None
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _probe_with_ffprobe(path: str, probe: MediaProbe) -> MediaProbe:
    data = _ffprobe_json(path)
    if data is None:
        if not probe.readable:
            probe.error_code = probe.error_code or "ffprobe_unavailable_or_failed"
        return probe

    streams = data.get("streams") or []
    if not isinstance(streams, list) or not streams:
        probe.readable = False
        probe.error_code = "no_streams"
        return probe

    video_stream: dict[str, Any] | None = None
    audio_stream: dict[str, Any] | None = None
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = stream.get("codec_type")
        if codec_type == "video" and video_stream is None:
            video_stream = stream
        elif codec_type == "audio" and audio_stream is None:
            audio_stream = stream

    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    duration = None
    try:
        if fmt.get("duration") is not None:
            duration = float(fmt["duration"])
    except (TypeError, ValueError):
        duration = None

    if video_stream is not None:
        probe.readable = True
        probe.kind = "video"
        try:
            probe.width = int(video_stream.get("width") or 0) or None
            probe.height = int(video_stream.get("height") or 0) or None
        except (TypeError, ValueError):
            pass
        nb_frames = video_stream.get("nb_frames")
        frame_count: int | None = None
        try:
            if nb_frames not in (None, "N/A", ""):
                frame_count = int(nb_frames)
        except (TypeError, ValueError):
            frame_count = None
        if frame_count is None:
            fps = _parse_fraction(video_stream.get("avg_frame_rate")) or _parse_fraction(
                video_stream.get("r_frame_rate")
            )
            stream_dur = None
            try:
                if video_stream.get("duration") is not None:
                    stream_dur = float(video_stream["duration"])
            except (TypeError, ValueError):
                stream_dur = None
            use_dur = stream_dur if stream_dur is not None else duration
            if fps and use_dur is not None and use_dur > 0:
                frame_count = max(1, int(round(fps * use_dur)))
        probe.frame_count = frame_count
        if duration is None:
            try:
                if video_stream.get("duration") is not None:
                    duration = float(video_stream["duration"])
            except (TypeError, ValueError):
                pass
        probe.duration_seconds = duration
        probe.has_audio = audio_stream is not None
        return probe

    if audio_stream is not None:
        probe.readable = True
        probe.kind = "audio"
        probe.has_audio = True
        try:
            if audio_stream.get("sample_rate") is not None:
                probe.sample_rate = int(audio_stream["sample_rate"])
        except (TypeError, ValueError):
            pass
        try:
            if audio_stream.get("channels") is not None:
                probe.channels = int(audio_stream["channels"])
        except (TypeError, ValueError):
            pass
        nb_frames = audio_stream.get("nb_frames")
        try:
            if nb_frames not in (None, "N/A", ""):
                probe.frame_count = int(nb_frames)
        except (TypeError, ValueError):
            pass
        if duration is None:
            try:
                if audio_stream.get("duration") is not None:
                    duration = float(audio_stream["duration"])
            except (TypeError, ValueError):
                pass
        probe.duration_seconds = duration
        return probe

    probe.readable = False
    probe.error_code = "no_av_streams"
    return probe


def probe_media(path: str) -> MediaProbe:
    """Inspect a local media file without calling any provider."""
    probe = MediaProbe(path=path)
    if not path or not isinstance(path, str):
        probe.error_code = "invalid_path"
        return probe
    if not os.path.isfile(path):
        probe.exists = False
        probe.error_code = "missing"
        return probe
    probe.exists = True
    if os.path.getsize(path) <= 0:
        probe.readable = False
        probe.error_code = "empty_file"
        return probe

    kind = _guess_kind(path)
    if kind == "image":
        return _probe_image(path, probe)
    if kind == "audio":
        # Prefer stdlib/soundfile for WAV; fall back to ffprobe for other codecs.
        _probe_wav(path, probe)
        if probe.readable:
            return probe
        return _probe_with_ffprobe(path, probe)
    if kind == "video":
        return _probe_with_ffprobe(path, probe)

    # Unknown extension — try image, then ffprobe.
    _probe_image(path, probe)
    if probe.readable:
        return probe
    return _probe_with_ffprobe(path, probe)


# ---------------------------------------------------------------------------
# Aspect-ratio helpers
# ---------------------------------------------------------------------------


def parse_aspect_ratio(value: Any) -> Fraction | None:
    """Parse ``'9:16'``, ``'16/9'``, or a positive float into a Fraction."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        return Fraction(value).limit_denominator(1000)
    text = _strip(value).replace(" ", "")
    if not text:
        return None
    if ":" in text:
        left, right = text.split(":", 1)
    elif "/" in text:
        left, right = text.split("/", 1)
    else:
        try:
            number = float(text)
        except ValueError:
            return None
        if number <= 0:
            return None
        return Fraction(number).limit_denominator(1000)
    try:
        num = float(left)
        den = float(right)
    except ValueError:
        return None
    if num <= 0 or den <= 0:
        return None
    return Fraction(num / den).limit_denominator(1000)


def _ratio_from_dims(width: int, height: int) -> Fraction | None:
    if width <= 0 or height <= 0:
        return None
    return Fraction(width, height)


def _ratios_close(left: Fraction, right: Fraction, *, tolerance: float) -> bool:
    if left == 0 or right == 0:
        return False
    return abs(float(left) - float(right)) <= tolerance


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------


def check_file_exists(
    path: str,
    *,
    context: TechnicalContext | None = None,
) -> list[TechnicalIssue]:
    """Fail when the managed file is missing or not a regular file."""
    if path and os.path.isfile(path):
        return []
    return [
        _issue(
            "file_exists",
            severity="critical",
            reason="Expected media file is missing on disk.",
            suggested_action="regenerate",
            repair_instruction="Regenerate the missing artifact; the prior path no longer resolves.",
            observed={"exists": False, "path_ref": _relative_ref(context.path_ref if context else None) or _relative_ref(path)},
            expected={"exists": True},
            context=context,
        )
    ]


def check_readable_media(
    path: str,
    *,
    context: TechnicalContext | None = None,
    probe: MediaProbe | None = None,
) -> list[TechnicalIssue]:
    """Fail when the file exists but cannot be decoded as media."""
    exists_issues = check_file_exists(path, context=context)
    if exists_issues:
        return exists_issues
    media = probe if probe is not None else probe_media(path)
    if media.readable:
        return []
    return [
        _issue(
            "readable_media",
            severity="critical",
            reason="Media file exists but is not readable as image, audio, or video.",
            suggested_action="regenerate",
            repair_instruction="Regenerate the artifact with a supported codec/container.",
            observed={
                "readable": False,
                "error_code": media.error_code,
                "kind": media.kind,
            },
            expected={"readable": True},
            context=context,
        )
    ]


def check_resolution(
    path: str,
    *,
    width: int | None = None,
    height: int | None = None,
    min_width: int | None = None,
    min_height: int | None = None,
    tolerance_px: int = 0,
    context: TechnicalContext | None = None,
    probe: MediaProbe | None = None,
) -> list[TechnicalIssue]:
    """Fail when width/height do not meet the expected resolution."""
    readable = check_readable_media(path, context=context, probe=probe)
    if readable:
        # Missing/unreadable media is the stronger defect; resolution is moot.
        return readable

    media = probe if probe is not None else probe_media(path)
    if media.width is None or media.height is None:
        return [
            _issue(
                "resolution",
                severity="high",
                reason="Could not determine media resolution.",
                suggested_action="regenerate",
                repair_instruction="Regenerate so the media exposes width and height.",
                observed={"width": media.width, "height": media.height, "kind": media.kind},
                expected={
                    k: v
                    for k, v in {
                        "width": width,
                        "height": height,
                        "min_width": min_width,
                        "min_height": min_height,
                    }.items()
                    if v is not None
                },
                context=context,
            )
        ]

    tol = max(0, int(tolerance_px))
    problems: list[str] = []
    if width is not None and abs(media.width - int(width)) > tol:
        problems.append("width")
    if height is not None and abs(media.height - int(height)) > tol:
        problems.append("height")
    if min_width is not None and media.width < int(min_width):
        problems.append("min_width")
    if min_height is not None and media.height < int(min_height):
        problems.append("min_height")
    if not problems:
        return []

    return [
        _issue(
            "resolution",
            severity="high",
            reason=f"Media resolution does not match expectation ({', '.join(problems)}).",
            suggested_action="regenerate",
            repair_instruction="Regenerate at the expected resolution; preserve subject and composition.",
            observed={"width": media.width, "height": media.height, "failed": problems},
            expected={
                k: v
                for k, v in {
                    "width": width,
                    "height": height,
                    "min_width": min_width,
                    "min_height": min_height,
                    "tolerance_px": tol,
                }.items()
                if v is not None
            },
            context=context,
        )
    ]


def check_duration(
    path: str,
    *,
    min_seconds: float | None = None,
    max_seconds: float | None = None,
    expected_seconds: float | None = None,
    tolerance_seconds: float = 0.15,
    context: TechnicalContext | None = None,
    probe: MediaProbe | None = None,
) -> list[TechnicalIssue]:
    """Fail when duration is outside the expected range."""
    readable = check_readable_media(path, context=context, probe=probe)
    if readable:
        return readable

    media = probe if probe is not None else probe_media(path)
    if media.duration_seconds is None:
        return [
            _issue(
                "duration",
                severity="high",
                reason="Could not determine media duration.",
                suggested_action="regenerate",
                repair_instruction="Regenerate so the media exposes a measurable duration.",
                observed={"duration_seconds": None, "kind": media.kind},
                expected={
                    k: v
                    for k, v in {
                        "min_seconds": min_seconds,
                        "max_seconds": max_seconds,
                        "expected_seconds": expected_seconds,
                    }.items()
                    if v is not None
                },
                context=context,
            )
        ]

    duration = float(media.duration_seconds)
    tol = max(0.0, float(tolerance_seconds))
    failed: list[str] = []
    if min_seconds is not None and duration + 1e-9 < float(min_seconds):
        failed.append("min_seconds")
    if max_seconds is not None and duration - 1e-9 > float(max_seconds):
        failed.append("max_seconds")
    if expected_seconds is not None and abs(duration - float(expected_seconds)) > tol:
        failed.append("expected_seconds")
    if not failed:
        return []

    return [
        _issue(
            "duration",
            severity="high",
            reason=f"Media duration does not match expectation ({', '.join(failed)}).",
            suggested_action="regenerate",
            repair_instruction="Regenerate with the expected duration; preserve narration content.",
            observed={"duration_seconds": round(duration, 4), "failed": failed},
            expected={
                k: v
                for k, v in {
                    "min_seconds": min_seconds,
                    "max_seconds": max_seconds,
                    "expected_seconds": expected_seconds,
                    "tolerance_seconds": tol,
                }.items()
                if v is not None
            },
            context=context,
        )
    ]


def check_aspect_ratio(
    path: str,
    *,
    aspect_ratio: str | float | Fraction,
    tolerance: float = 0.02,
    context: TechnicalContext | None = None,
    probe: MediaProbe | None = None,
) -> list[TechnicalIssue]:
    """Fail when width:height does not match the expected aspect ratio."""
    readable = check_readable_media(path, context=context, probe=probe)
    if readable:
        return readable

    expected_ratio = parse_aspect_ratio(aspect_ratio)
    if expected_ratio is None:
        return [
            _issue(
                "aspect_ratio",
                severity="high",
                reason="Invalid expected aspect ratio configuration.",
                suggested_action="adjust",
                repair_instruction="Configure a valid aspect ratio such as 9:16 or 16:9.",
                observed={},
                expected={"aspect_ratio": _strip(aspect_ratio)},
                context=context,
            )
        ]

    media = probe if probe is not None else probe_media(path)
    if media.width is None or media.height is None:
        return [
            _issue(
                "aspect_ratio",
                severity="high",
                reason="Could not determine media aspect ratio (missing dimensions).",
                suggested_action="regenerate",
                repair_instruction="Regenerate so the media exposes width and height.",
                observed={"width": media.width, "height": media.height},
                expected={"aspect_ratio": str(aspect_ratio)},
                context=context,
            )
        ]

    observed_ratio = _ratio_from_dims(media.width, media.height)
    assert observed_ratio is not None
    tol = max(0.0, float(tolerance))
    if _ratios_close(observed_ratio, expected_ratio, tolerance=tol):
        return []

    return [
        _issue(
            "aspect_ratio",
            severity="high",
            reason="Media aspect ratio does not match the channel/export expectation.",
            suggested_action="regenerate",
            repair_instruction="Regenerate at the expected aspect ratio; preserve subject framing intent.",
            observed={
                "width": media.width,
                "height": media.height,
                "aspect_ratio": f"{media.width}:{media.height}",
                "aspect_ratio_float": round(float(observed_ratio), 6),
            },
            expected={
                "aspect_ratio": str(aspect_ratio),
                "aspect_ratio_float": round(float(expected_ratio), 6),
                "tolerance": tol,
            },
            context=context,
        )
    ]


def check_audio_presence(
    path: str,
    *,
    require: bool = True,
    context: TechnicalContext | None = None,
    probe: MediaProbe | None = None,
) -> list[TechnicalIssue]:
    """Fail when audio is required but the media has no audio stream/samples."""
    if not require:
        return []

    readable = check_readable_media(path, context=context, probe=probe)
    if readable:
        return readable

    media = probe if probe is not None else probe_media(path)
    if media.has_audio is True:
        return []

    # Images never carry audio — treat as a technical defect when required.
    return [
        _issue(
            "audio_presence",
            severity="high" if media.kind == "video" else "medium",
            reason="Media is missing required audio.",
            suggested_action="regenerate",
            repair_instruction="Regenerate or remux so the deliverable includes an audio track.",
            observed={
                "has_audio": media.has_audio,
                "kind": media.kind,
                "channels": media.channels,
            },
            expected={"has_audio": True},
            context=context,
        )
    ]


def check_frame_count(
    path: str,
    *,
    min_frames: int | None = None,
    expected_frames: int | None = None,
    tolerance_frames: int = 0,
    context: TechnicalContext | None = None,
    probe: MediaProbe | None = None,
) -> list[TechnicalIssue]:
    """Fail when video/audio frame count is outside the expected range."""
    readable = check_readable_media(path, context=context, probe=probe)
    if readable:
        return readable

    media = probe if probe is not None else probe_media(path)
    if media.frame_count is None:
        return [
            _issue(
                "frame_count",
                severity="high",
                reason="Could not determine media frame count.",
                suggested_action="regenerate",
                repair_instruction="Regenerate so the media exposes a frame count.",
                observed={"frame_count": None, "kind": media.kind},
                expected={
                    k: v
                    for k, v in {
                        "min_frames": min_frames,
                        "expected_frames": expected_frames,
                    }.items()
                    if v is not None
                },
                context=context,
            )
        ]

    count = int(media.frame_count)
    tol = max(0, int(tolerance_frames))
    failed: list[str] = []
    if min_frames is not None and count < int(min_frames):
        failed.append("min_frames")
    if expected_frames is not None and abs(count - int(expected_frames)) > tol:
        failed.append("expected_frames")
    if not failed:
        return []

    return [
        _issue(
            "frame_count",
            severity="high",
            reason=f"Media frame count does not match expectation ({', '.join(failed)}).",
            suggested_action="regenerate",
            repair_instruction="Regenerate with the expected frame count / duration.",
            observed={"frame_count": count, "failed": failed, "kind": media.kind},
            expected={
                k: v
                for k, v in {
                    "min_frames": min_frames,
                    "expected_frames": expected_frames,
                    "tolerance_frames": tol,
                }.items()
                if v is not None
            },
            context=context,
        )
    ]


def check_expected_artifact_count(
    artifacts: Sequence[Any],
    *,
    expected: int,
    kind: str | None = None,
    context: TechnicalContext | None = None,
) -> list[TechnicalIssue]:
    """Fail when the number of artifacts (optionally filtered by kind) is wrong.

    ``artifacts`` may be plain mappings, objects with attributes, or raw ids —
    only ``kind`` is inspected when filtering; everything else counts as one.
    """
    items = list(artifacts or [])
    if kind is not None:
        filtered: list[Any] = []
        for item in items:
            item_kind = None
            if isinstance(item, Mapping):
                item_kind = item.get("kind")
            else:
                item_kind = getattr(item, "kind", None)
            if _strip(item_kind) == _strip(kind):
                filtered.append(item)
        items = filtered

    actual = len(items)
    if actual == int(expected):
        return []

    return [
        _issue(
            "expected_artifact_count",
            severity="high",
            reason="Artifact count does not match the expected total.",
            suggested_action="regenerate",
            repair_instruction=(
                f"Produce exactly {int(expected)} artifact(s)"
                + (f" of kind '{kind}'" if kind else "")
                + "; remove extras or regenerate missing units."
            ),
            observed={"count": actual, "kind": kind},
            expected={"count": int(expected), "kind": kind},
            context=context,
        )
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

# Map check_id → callable metadata for discovery / tests.
VALIDATOR_NAMES: tuple[str, ...] = TECHNICAL_CHECK_IDS


def run_technical_validators(
    *,
    path: str | None = None,
    artifacts: Sequence[Any] | None = None,
    context: TechnicalContext | None = None,
    expect_exists: bool = True,
    expect_readable: bool = True,
    width: int | None = None,
    height: int | None = None,
    min_width: int | None = None,
    min_height: int | None = None,
    tolerance_px: int = 0,
    min_seconds: float | None = None,
    max_seconds: float | None = None,
    expected_seconds: float | None = None,
    tolerance_seconds: float = 0.15,
    aspect_ratio: str | float | Fraction | None = None,
    aspect_tolerance: float = 0.02,
    require_audio: bool | None = None,
    min_frames: int | None = None,
    expected_frames: int | None = None,
    tolerance_frames: int = 0,
    expected_artifact_count: int | None = None,
    artifact_kind: str | None = None,
    checks: Iterable[str] | None = None,
) -> list[TechnicalIssue]:
    """Run the selected technical checks and return structured issues only.

    When ``checks`` is omitted, every check that has enough inputs is run.
    Missing / unreadable media short-circuits dimension/duration checks so a
    single bad file does not produce a cascade of secondary noise — callers
    that want every check still get ``file_exists`` / ``readable_media``.
    """
    selected = set(checks) if checks is not None else None
    issues: list[TechnicalIssue] = []
    media: MediaProbe | None = None

    def want(name: str) -> bool:
        return selected is None or name in selected

    if path is not None and want("file_exists") and expect_exists:
        issues.extend(check_file_exists(path, context=context))
        if issues:
            # File is gone — further media checks would only restate the same fact.
            if expected_artifact_count is not None and want("expected_artifact_count"):
                issues.extend(
                    check_expected_artifact_count(
                        artifacts or [],
                        expected=expected_artifact_count,
                        kind=artifact_kind,
                        context=context,
                    )
                )
            return issues

    if path is not None:
        media = probe_media(path)

    if path is not None and want("readable_media") and expect_readable:
        issues.extend(check_readable_media(path, context=context, probe=media))
        if any(i.check_id == "readable_media" for i in issues):
            if expected_artifact_count is not None and want("expected_artifact_count"):
                issues.extend(
                    check_expected_artifact_count(
                        artifacts or [],
                        expected=expected_artifact_count,
                        kind=artifact_kind,
                        context=context,
                    )
                )
            return issues

    if path is not None and want("resolution") and any(
        v is not None for v in (width, height, min_width, min_height)
    ):
        issues.extend(
            check_resolution(
                path,
                width=width,
                height=height,
                min_width=min_width,
                min_height=min_height,
                tolerance_px=tolerance_px,
                context=context,
                probe=media,
            )
        )

    if path is not None and want("duration") and any(
        v is not None for v in (min_seconds, max_seconds, expected_seconds)
    ):
        issues.extend(
            check_duration(
                path,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
                expected_seconds=expected_seconds,
                tolerance_seconds=tolerance_seconds,
                context=context,
                probe=media,
            )
        )

    if path is not None and want("aspect_ratio") and aspect_ratio is not None:
        issues.extend(
            check_aspect_ratio(
                path,
                aspect_ratio=aspect_ratio,
                tolerance=aspect_tolerance,
                context=context,
                probe=media,
            )
        )

    if path is not None and want("audio_presence") and require_audio is not None:
        issues.extend(
            check_audio_presence(
                path,
                require=bool(require_audio),
                context=context,
                probe=media,
            )
        )

    if path is not None and want("frame_count") and any(
        v is not None for v in (min_frames, expected_frames)
    ):
        issues.extend(
            check_frame_count(
                path,
                min_frames=min_frames,
                expected_frames=expected_frames,
                tolerance_frames=tolerance_frames,
                context=context,
                probe=media,
            )
        )

    if expected_artifact_count is not None and want("expected_artifact_count"):
        issues.extend(
            check_expected_artifact_count(
                artifacts or [],
                expected=expected_artifact_count,
                kind=artifact_kind,
                context=context,
            )
        )

    return issues


def assert_structured_issues(issues: Sequence[Any]) -> list[TechnicalIssue]:
    """Validate that a validator result is structured issues, never free text."""
    if isinstance(issues, str):
        raise TypeError("technical validators must not return free-text results")
    out: list[TechnicalIssue] = []
    for item in issues:
        if isinstance(item, str):
            raise TypeError("technical validators must not emit free-text issues")
        if isinstance(item, TechnicalIssue):
            out.append(item)
            continue
        if isinstance(item, Mapping):
            out.append(TechnicalIssue.model_validate(item))
            continue
        raise TypeError(f"unexpected technical issue type: {type(item)!r}")
    return out


def technical_issues_to_review_drafts(
    issues: Sequence[Any],
    *,
    job_id: str,
) -> list[Any]:
    """Map technical findings onto ReviewIssue drafts for persistence (step 7.2)."""
    from scriptase.review.models import technical_to_draft

    validated = assert_structured_issues(issues)
    return [technical_to_draft(item, job_id=job_id) for item in validated]


__all__ = [
    "TECHNICAL_CHECK_IDS",
    "VALIDATOR_NAMES",
    "MediaProbe",
    "TechnicalCheckId",
    "TechnicalContext",
    "TechnicalIssue",
    "assert_structured_issues",
    "check_aspect_ratio",
    "check_audio_presence",
    "check_duration",
    "check_expected_artifact_count",
    "check_file_exists",
    "check_frame_count",
    "check_readable_media",
    "check_resolution",
    "parse_aspect_ratio",
    "probe_media",
    "run_technical_validators",
    "technical_issues_to_review_drafts",
]
