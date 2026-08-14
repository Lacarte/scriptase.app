"""Step 7.1 — Technical validators.

Done when: each validator has a failing fixture and emits a structured issue
rather than free text.
"""

from __future__ import annotations

import os
import struct
import subprocess
import tempfile
import unittest
import wave

from PIL import Image

from scriptase.review.technical import (
    TECHNICAL_CHECK_IDS,
    TechnicalContext,
    TechnicalIssue,
    assert_structured_issues,
    check_aspect_ratio,
    check_audio_presence,
    check_duration,
    check_expected_artifact_count,
    check_file_exists,
    check_frame_count,
    check_readable_media,
    check_resolution,
    parse_aspect_ratio,
    probe_media,
    run_technical_validators,
)
from scriptase.shared.ffmpeg_utils import find_ffmpeg, find_ffprobe


def _assert_structured_failure(issues, *, check_id: str) -> TechnicalIssue:
    """Shared assertions: one structured issue for the named check."""
    validated = assert_structured_issues(issues)
    assert validated, f"expected a failing issue for {check_id}, got none"
    issue = validated[0]
    assert isinstance(issue, TechnicalIssue)
    assert issue.check_id == check_id
    assert issue.issue_type == "technical_defect"
    assert 0.0 <= issue.confidence <= 1.0
    assert issue.severity in {"low", "medium", "high", "critical"}
    assert issue.suggested_action in {
        "regenerate",
        "re-prompt",
        "adjust",
        "escalate",
        "accept",
    }
    assert isinstance(issue.reason, str) and issue.reason.strip()
    assert isinstance(issue.observed, dict)
    assert isinstance(issue.expected, dict)
    # Free-text-only output is forbidden: structured maps must carry signal.
    assert issue.observed or issue.expected, "issue must carry observed/expected structure"
    return issue


def _write_png(path: str, width: int, height: int, color=(20, 40, 80)) -> str:
    image = Image.new("RGB", (width, height), color)
    image.save(path, format="PNG")
    return path


def _write_wav(path: str, *, seconds: float = 0.5, rate: int = 8000, amplitude: int = 1000) -> str:
    frame_count = max(1, int(rate * seconds))
    frames = bytearray()
    for index in range(frame_count):
        # Simple square-ish tone so has_audio is unambiguously true.
        value = amplitude if (index // 40) % 2 == 0 else -amplitude
        frames += struct.pack("<h", value)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return path


def _write_mp4(
    path: str,
    *,
    width: int = 90,
    height: int = 160,
    seconds: float = 1.0,
    fps: int = 12,
    with_audio: bool = False,
) -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise unittest.SkipTest("ffmpeg required for video fixtures")
    # Even dimensions required by yuv420p.
    width = width - (width % 2)
    height = height - (height % 2)
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x18284a:s={width}x{height}:r={fps}:d={seconds}",
    ]
    if with_audio:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={seconds}",
                "-shortest",
                "-c:a",
                "aac",
            ]
        )
    cmd.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "35",
            "-movflags",
            "+faststart",
            path,
        ]
    )
    subprocess.run(cmd, check=True, capture_output=True)
    return path


class TechnicalIssueModelTests(unittest.TestCase):
    def test_rejects_free_text_via_assert_helper(self):
        with self.assertRaises(TypeError):
            assert_structured_issues("file is bad")
        with self.assertRaises(TypeError):
            assert_structured_issues(["file is bad"])

    def test_path_ref_never_keeps_absolute(self):
        issue = TechnicalIssue(
            check_id="file_exists",
            severity="critical",
            reason="missing",
            path_ref=r"D:\secrets\media\scene.png",
            observed={"exists": False},
            expected={"exists": True},
        )
        self.assertEqual(issue.path_ref, "scene.png")
        self.assertNotIn(":\\", issue.path_ref or "")


class FileExistsValidatorTests(unittest.TestCase):
    def test_missing_file_emits_structured_issue(self):
        missing = os.path.join(tempfile.gettempdir(), "scriptase_missing_7_1_no_such_file.bin")
        if os.path.exists(missing):
            os.remove(missing)
        ctx = TechnicalContext(path_ref="storyboard/job/scene_01.png", scene_id="scn_AAAAAA")
        issues = check_file_exists(missing, context=ctx)
        issue = _assert_structured_failure(issues, check_id="file_exists")
        self.assertEqual(issue.severity, "critical")
        self.assertEqual(issue.scene_id, "scn_AAAAAA")
        self.assertEqual(issue.path_ref, "storyboard/job/scene_01.png")
        self.assertFalse(issue.observed.get("exists"))


class ReadableMediaValidatorTests(unittest.TestCase):
    def test_garbage_bytes_emits_structured_issue(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = os.path.join(tmp, "broken.png")
            with open(path, "wb") as handle:
                handle.write(b"this is not an image payload at all")
            ctx = TechnicalContext(path_ref="storyboard/broken.png", target_artifact_id="art_ABC123")
            issues = check_readable_media(path, context=ctx)
            issue = _assert_structured_failure(issues, check_id="readable_media")
            self.assertEqual(issue.severity, "critical")
            self.assertEqual(issue.target_artifact_id, "art_ABC123")
            self.assertFalse(issue.observed.get("readable"))


class ResolutionValidatorTests(unittest.TestCase):
    def test_wrong_resolution_emits_structured_issue(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_png(os.path.join(tmp, "tiny.png"), 32, 32)
            issues = check_resolution(path, width=1080, height=1920)
            issue = _assert_structured_failure(issues, check_id="resolution")
            self.assertEqual(issue.observed["width"], 32)
            self.assertEqual(issue.observed["height"], 32)
            self.assertEqual(issue.expected["width"], 1080)
            self.assertEqual(issue.expected["height"], 1920)

    def test_matching_resolution_passes(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_png(os.path.join(tmp, "ok.png"), 90, 160)
            self.assertEqual(check_resolution(path, width=90, height=160), [])


class DurationValidatorTests(unittest.TestCase):
    def test_too_short_audio_emits_structured_issue(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_wav(os.path.join(tmp, "short.wav"), seconds=0.2)
            issues = check_duration(path, min_seconds=2.0)
            issue = _assert_structured_failure(issues, check_id="duration")
            self.assertIn("min_seconds", issue.observed["failed"])
            self.assertLess(issue.observed["duration_seconds"], 2.0)
            self.assertEqual(issue.expected["min_seconds"], 2.0)

    def test_matching_duration_passes(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_wav(os.path.join(tmp, "ok.wav"), seconds=0.5)
            self.assertEqual(
                check_duration(path, expected_seconds=0.5, tolerance_seconds=0.05),
                [],
            )


class AspectRatioValidatorTests(unittest.TestCase):
    def test_wrong_aspect_ratio_emits_structured_issue(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            # 1:1 square when 9:16 is required.
            path = _write_png(os.path.join(tmp, "square.png"), 100, 100)
            issues = check_aspect_ratio(path, aspect_ratio="9:16")
            issue = _assert_structured_failure(issues, check_id="aspect_ratio")
            self.assertEqual(issue.observed["width"], 100)
            self.assertEqual(issue.observed["height"], 100)
            self.assertEqual(issue.expected["aspect_ratio"], "9:16")

    def test_matching_aspect_ratio_passes(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_png(os.path.join(tmp, "portrait.png"), 90, 160)
            self.assertEqual(check_aspect_ratio(path, aspect_ratio="9:16"), [])

    def test_parse_aspect_ratio_forms(self):
        self.assertIsNotNone(parse_aspect_ratio("9:16"))
        self.assertIsNotNone(parse_aspect_ratio("16/9"))
        self.assertIsNotNone(parse_aspect_ratio(1.777))
        self.assertIsNone(parse_aspect_ratio(""))
        self.assertIsNone(parse_aspect_ratio("nope"))


class AudioPresenceValidatorTests(unittest.TestCase):
    def test_video_without_audio_emits_structured_issue(self):
        if not find_ffprobe() or not find_ffmpeg():
            self.skipTest("ffmpeg/ffprobe required")
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_mp4(os.path.join(tmp, "silent.mp4"), with_audio=False)
            issues = check_audio_presence(path, require=True)
            issue = _assert_structured_failure(issues, check_id="audio_presence")
            self.assertNotEqual(issue.observed.get("has_audio"), True)
            self.assertTrue(issue.expected.get("has_audio"))

    def test_wav_with_samples_passes(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_wav(os.path.join(tmp, "voice.wav"), seconds=0.3)
            self.assertEqual(check_audio_presence(path, require=True), [])


class FrameCountValidatorTests(unittest.TestCase):
    def test_too_few_frames_emits_structured_issue(self):
        if not find_ffprobe() or not find_ffmpeg():
            self.skipTest("ffmpeg/ffprobe required")
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            # 1 second @ 12 fps → 12 frames; demand far more.
            path = _write_mp4(os.path.join(tmp, "clip.mp4"), seconds=1.0, fps=12)
            issues = check_frame_count(path, min_frames=100)
            issue = _assert_structured_failure(issues, check_id="frame_count")
            self.assertIn("min_frames", issue.observed["failed"])
            self.assertLess(issue.observed["frame_count"], 100)
            self.assertEqual(issue.expected["min_frames"], 100)

    def test_matching_frame_count_passes(self):
        if not find_ffprobe() or not find_ffmpeg():
            self.skipTest("ffmpeg/ffprobe required")
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_mp4(os.path.join(tmp, "clip.mp4"), seconds=1.0, fps=12)
            media = probe_media(path)
            self.assertTrue(media.readable)
            self.assertIsNotNone(media.frame_count)
            self.assertEqual(
                check_frame_count(
                    path,
                    expected_frames=media.frame_count,
                    tolerance_frames=2,
                    probe=media,
                ),
                [],
            )


class ExpectedArtifactCountValidatorTests(unittest.TestCase):
    def test_wrong_count_emits_structured_issue(self):
        artifacts = [
            {"id": "art_AAAAAA", "kind": "image"},
            {"id": "art_BBBBBB", "kind": "image"},
            {"id": "art_CCCCCC", "kind": "video"},
        ]
        issues = check_expected_artifact_count(artifacts, expected=5, kind="image")
        issue = _assert_structured_failure(issues, check_id="expected_artifact_count")
        self.assertEqual(issue.observed["count"], 2)
        self.assertEqual(issue.expected["count"], 5)
        self.assertEqual(issue.expected["kind"], "image")

    def test_matching_count_passes(self):
        artifacts = [{"kind": "image"}, {"kind": "image"}, {"kind": "video"}]
        self.assertEqual(
            check_expected_artifact_count(artifacts, expected=2, kind="image"),
            [],
        )


class CoverageAndRunnerTests(unittest.TestCase):
    """Meta: every §12.4 check id has a failing fixture exercise above."""

    # check_id → test method that must produce a structured failure
    FAILING_FIXTURE_OWNERS = {
        "file_exists": "FileExistsValidatorTests.test_missing_file_emits_structured_issue",
        "readable_media": "ReadableMediaValidatorTests.test_garbage_bytes_emits_structured_issue",
        "resolution": "ResolutionValidatorTests.test_wrong_resolution_emits_structured_issue",
        "duration": "DurationValidatorTests.test_too_short_audio_emits_structured_issue",
        "aspect_ratio": "AspectRatioValidatorTests.test_wrong_aspect_ratio_emits_structured_issue",
        "audio_presence": "AudioPresenceValidatorTests.test_video_without_audio_emits_structured_issue",
        "frame_count": "FrameCountValidatorTests.test_too_few_frames_emits_structured_issue",
        "expected_artifact_count": (
            "ExpectedArtifactCountValidatorTests.test_wrong_count_emits_structured_issue"
        ),
    }

    def test_every_check_id_has_failing_fixture_owner(self):
        self.assertEqual(set(TECHNICAL_CHECK_IDS), set(self.FAILING_FIXTURE_OWNERS))

    def test_runner_aggregates_structured_issues_only(self):
        with tempfile.TemporaryDirectory(prefix="scriptase_tech_") as tmp:
            path = _write_png(os.path.join(tmp, "square.png"), 64, 64)
            issues = run_technical_validators(
                path=path,
                width=1080,
                height=1920,
                aspect_ratio="9:16",
                artifacts=[{"kind": "image"}],
                expected_artifact_count=3,
                artifact_kind="image",
                context=TechnicalContext(
                    path_ref="storyboard/pm_TEST/scene_01.png",
                    scene_id="scn_ZZZZZZ",
                    target_node_id="image_1",
                ),
            )
            validated = assert_structured_issues(issues)
            self.assertTrue(validated)
            check_ids = {issue.check_id for issue in validated}
            self.assertIn("resolution", check_ids)
            self.assertIn("aspect_ratio", check_ids)
            self.assertIn("expected_artifact_count", check_ids)
            for issue in validated:
                self.assertEqual(issue.issue_type, "technical_defect")
                self.assertEqual(issue.scene_id, "scn_ZZZZZZ")
                self.assertEqual(issue.target_node_id, "image_1")
                # Absolute paths must never leak into the structured payload.
                dumped = issue.to_dict()
                as_text = str(dumped)
                self.assertNotRegex(as_text, r"[A-Za-z]:\\")
                self.assertFalse(str(issue.path_ref or "").startswith("/"))


if __name__ == "__main__":
    unittest.main()
