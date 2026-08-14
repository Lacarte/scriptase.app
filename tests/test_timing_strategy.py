"""Step 5.3: Timing strategy AUTO.

Done when:
  * both strategies produce an identical alignment schema
  * the segmenter cannot determine which one ran
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from scriptase.engine.registry import get_node_type
from scriptase.modules.segmenter.algorithm import run_segmenter
from scriptase.modules.timing.service import (
    CANONICAL_ALIGNMENT_KEYS,
    WORD_TIMING_KEYS,
    _step_timing,
    normalize_word_timings,
)
from scriptase.providers.domains import DOMAINS


def _words(*pairs):
    """Build canonical timed words from (word, begin, end) triples."""
    return [
        {"word": word, "begin": begin, "end": end}
        for word, begin, end in pairs
    ]


SAMPLE_WORDS = _words(
    ("Hello", 0.0, 0.3),
    ("world", 0.35, 0.7),
    ("from", 0.75, 1.0),
    ("native", 1.05, 1.4),
    ("timing.", 1.45, 1.9),
)

# Provider spellings that must normalise to the same shape.
PROVIDER_STYLE_WORDS = [
    {"text": "Hello", "start": 0.0, "end": 0.3},
    {"token": "world", "start_time": 0.35, "end_time": 0.7},
    {"word": "from", "begin": 0.75, "end": 1.0},
    {"word": "native", "start": 1.05, "end": 1.4},
    {"word": "timing.", "begin": 1.45, "end": 1.9},
]


class NormalizeWordTimingsTests(unittest.TestCase):
    def test_canonical_shape_passthrough(self):
        out = normalize_word_timings(SAMPLE_WORDS)
        self.assertIsNotNone(out)
        self.assertEqual(len(out), len(SAMPLE_WORDS))
        for entry in out:
            self.assertEqual(set(entry.keys()), WORD_TIMING_KEYS)

    def test_provider_spellings_normalise(self):
        out = normalize_word_timings(PROVIDER_STYLE_WORDS)
        self.assertEqual([w["word"] for w in out], [w["word"] for w in SAMPLE_WORDS])
        self.assertEqual(out[0]["begin"], 0.0)
        self.assertEqual(out[1]["begin"], 0.35)

    def test_empty_or_invalid_returns_none(self):
        self.assertIsNone(normalize_word_timings(None))
        self.assertIsNone(normalize_word_timings([]))
        self.assertIsNone(normalize_word_timings("nope"))
        self.assertIsNone(normalize_word_timings([{"word": "x", "begin": "bad", "end": 1}]))


class TimingStrategyAutoTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.align_root = self._tmpdir.name
        # Minimal silent-ish wav so validation gap-detection can open a path
        # when present; native path still works if the file is missing.
        self.wav_path = os.path.join(self.align_root, "voice.wav")
        with open(self.wav_path, "wb") as handle:
            # Minimal RIFF header + silence (same shape as fixture TTS provider).
            handle.write(b"RIFF$\x00\x00\x00WAVEfmt ")

    def _run(self, tts_result, text="Hello world from native timing."):
        with mock.patch("scriptase.modules.timing.service.ALIGN_DIR", self.align_root):
            return _step_timing(tts_result, {"text": text}, project_id="pm_TEST")

    def test_display_name_is_timing(self):
        definition = get_node_type("timing.align")
        self.assertEqual(definition["display_name"], "Timing")
        self.assertNotIn("Force Alignment", definition["display_name"])

    def test_native_word_timing_is_in_tts_vocabulary(self):
        self.assertIn("native_word_timing", DOMAINS["tts"].capability_vocabulary)

    def test_native_path_skips_whisper_and_matches_schema(self):
        tts_result = {
            "wav_path": self.wav_path,
            "folder": "pm_native",
            "filename": "voice.wav",
            "native_word_timing": True,
            "word_timings": PROVIDER_STYLE_WORDS,
        }
        with mock.patch(
            "scriptase.modules.timing.service._run_alignment",
            side_effect=AssertionError("force-align must not run when native timings are valid"),
        ) as force_align:
            result = self._run(tts_result)
            force_align.assert_not_called()

        self.assertEqual(CANONICAL_ALIGNMENT_KEYS, set(result.keys()))
        self.assertEqual(result["word_count"], len(result["alignment"]))
        for entry in result["alignment"]:
            self.assertEqual(set(entry.keys()), WORD_TIMING_KEYS)
        self.assertNotIn("strategy", result)
        self.assertNotIn("source", result)
        self.assertNotIn("timing_strategy", result)

    def test_force_align_path_matches_same_schema(self):
        tts_result = {
            "wav_path": self.wav_path,
            "folder": "pm_align",
            "filename": "voice.wav",
            # No native_word_timing advertisement.
        }
        with mock.patch(
            "scriptase.modules.timing.service._run_alignment",
            return_value=list(SAMPLE_WORDS),
        ) as force_align:
            result = self._run(tts_result)
            force_align.assert_called_once()

        self.assertEqual(CANONICAL_ALIGNMENT_KEYS, set(result.keys()))
        self.assertEqual(result["word_count"], len(SAMPLE_WORDS))
        for entry in result["alignment"]:
            self.assertEqual(set(entry.keys()), WORD_TIMING_KEYS)
        self.assertNotIn("strategy", result)

    def test_both_strategies_identical_schema_keys(self):
        native_tts = {
            "wav_path": self.wav_path,
            "folder": "pm_a",
            "filename": "voice.wav",
            "native_word_timing": True,
            "word_timings": SAMPLE_WORDS,
        }
        force_tts = {
            "wav_path": self.wav_path,
            "folder": "pm_b",
            "filename": "voice.wav",
        }
        with mock.patch(
            "scriptase.modules.timing.service._run_alignment",
            return_value=list(SAMPLE_WORDS),
        ):
            native = self._run(native_tts)
            force = self._run(force_tts)

        self.assertEqual(set(native.keys()), set(force.keys()))
        self.assertEqual(set(native.keys()), CANONICAL_ALIGNMENT_KEYS)
        # Word entry shape is identical regardless of path.
        self.assertEqual(
            {frozenset(w.keys()) for w in native["alignment"]},
            {frozenset(w.keys()) for w in force["alignment"]},
        )

    def test_advertised_but_missing_timings_falls_back(self):
        tts_result = {
            "wav_path": self.wav_path,
            "folder": "pm_fallback",
            "filename": "voice.wav",
            "native_word_timing": True,
            # No word_timings key.
        }
        with mock.patch(
            "scriptase.modules.timing.service._run_alignment",
            return_value=list(SAMPLE_WORDS),
        ) as force_align:
            result = self._run(tts_result)
            force_align.assert_called_once()
        self.assertEqual(set(result.keys()), CANONICAL_ALIGNMENT_KEYS)

    def test_unadvertised_timings_are_ignored(self):
        """Capability must be advertised — raw timings alone do not select native."""
        tts_result = {
            "wav_path": self.wav_path,
            "folder": "pm_ignore",
            "filename": "voice.wav",
            "word_timings": SAMPLE_WORDS,  # present but not advertised
        }
        with mock.patch(
            "scriptase.modules.timing.service._run_alignment",
            return_value=list(SAMPLE_WORDS),
        ) as force_align:
            self._run(tts_result)
            force_align.assert_called_once()

    def test_segmenter_cannot_distinguish_strategies(self):
        """Segmenter sees the same keys and succeeds on either artifact."""
        native_tts = {
            "wav_path": self.wav_path,
            "folder": "pm_seg_n",
            "filename": "voice.wav",
            "native_word_timing": True,
            "word_timings": SAMPLE_WORDS,
        }
        force_tts = {
            "wav_path": self.wav_path,
            "folder": "pm_seg_f",
            "filename": "voice.wav",
        }
        with mock.patch(
            "scriptase.modules.timing.service._run_alignment",
            return_value=list(SAMPLE_WORDS),
        ):
            native = self._run(native_tts)
            force = self._run(force_tts)

        # No strategy marker the segmenter could key on.
        for payload in (native, force):
            self.assertNotIn("strategy", payload)
            self.assertNotIn("timing_strategy", payload)
            self.assertNotIn("source", payload)
            self.assertNotIn("native_word_timing", payload)

        # Same public key set.
        self.assertEqual(set(native.keys()), set(force.keys()))

        native_result = run_segmenter(native["alignment"], None, {"transcript": native["transcript"]})
        force_result = run_segmenter(force["alignment"], None, {"transcript": force["transcript"]})
        self.assertIsInstance(native_result.get("segments"), list)
        self.assertIsInstance(force_result.get("segments"), list)
        self.assertGreater(len(native_result["segments"]), 0)
        self.assertGreater(len(force_result["segments"]), 0)
        # Segmenter outputs the same shape for both inputs — no strategy branch.
        self.assertEqual(set(native_result.keys()), set(force_result.keys()))


class TimingAdapterAutoTests(unittest.TestCase):
    def test_adapter_forwards_native_timings(self):
        from scriptase.engine.adapters import timing as timing_adapter
        from scriptase.engine.adapters.common import AdapterContext

        seen = {}
        ctx = AdapterContext(project_id="pm_ABC123")

        def capture(metadata, config, pid):
            seen.update(metadata)
            return {
                "project_id": pid,
                "source_file": metadata["filename"],
                "folder": metadata["folder"],
                "transcript": config["text"],
                "alignment": SAMPLE_WORDS,
                "word_count": len(SAMPLE_WORDS),
                "inference_time": 0.0,
                "timestamp": "2026-01-01T00:00:00",
            }

        with mock.patch.object(timing_adapter, "_step_timing", capture), \
             mock.patch.object(timing_adapter, "ALIGN_DIR", "/tmp/align"), \
             mock.patch.object(
                 timing_adapter, "with_artifacts",
                 lambda payload, *paths: {**payload, "artifact_refs": list(paths)},
             ), \
             mock.patch.object(
                 timing_adapter, "resolve_ref",
                 lambda ref, **kwargs: f"D:/managed/{ref.replace('/', os.sep)}",
             ):
            result = timing_adapter.align(
                {
                    "audio": {
                        "artifact_refs": ["tts/pm_ABC123/voice.wav"],
                        "filename": "voice.wav",
                        "folder": "pm_ABC123",
                        "native_word_timing": True,
                        "word_timings": PROVIDER_STYLE_WORDS,
                    },
                    "script": "Hello world from native timing.",
                },
                {},
                ctx,
            )

        self.assertTrue(seen.get("native_word_timing"))
        self.assertEqual(seen.get("word_timings"), PROVIDER_STYLE_WORDS)
        self.assertEqual(set(result["alignment"].keys()) - {"artifact_refs"}, CANONICAL_ALIGNMENT_KEYS)


if __name__ == "__main__":
    unittest.main()
