"""Step 2.3 — Channel narration defaults, script overrides, and TTS processing."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import numpy as np
import soundfile as sf

from scriptase.channels.migrations import apply_migrations
from scriptase.channels.models import CHANNEL_SCHEMA_VERSION
from scriptase.engine.adapters.common import AdapterContext
from scriptase.engine.adapters.tts import generate as generate_tts
from scriptase.engine.templates import narration_only_template
from scriptase.jobs.models import Job
from scriptase.jobs.migrations import apply_migrations as apply_job_migrations
from scriptase.jobs.orchestration import prepare_workflow_for_job
from scriptase.modules.tts.audio import remove_long_silence
from scriptase.modules.tts.dispatch import cache_key
from scriptase.modules.tts.processing import resolve_narration_processing


class NarrationResolutionTests(unittest.TestCase):
    def test_channel_v3_migrates_remove_silence_default(self):
        migrated, changed = apply_migrations({
            "schema_version": 3,
            "audio_defaults": {"speed": 0.95},
        })
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], CHANNEL_SCHEMA_VERSION)
        self.assertIs(migrated["audio_defaults"]["remove_silence"], True)

    def test_script_override_wins_channel(self):
        active = resolve_narration_processing(
            {"remove_silence": True, "speed": 0.9},
            {"remove_silence": False, "speed": 1.25},
            {"speed": 1.0},
        )
        self.assertEqual(active["remove_silence"], False)
        self.assertEqual(active["speed"], 1.25)
        self.assertEqual(active["remove_silence_source"], "script")
        self.assertEqual(active["speed_source"], "script")
        self.assertFalse(active["inherited"])

    def test_legacy_job_migrates_nullable_script_overrides(self):
        migrated, changed = apply_job_migrations({
            "schema_version": 1,
            "source": {"mode": "paste", "pasted_script": "Narration"},
        })
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], 3)
        self.assertIsNone(migrated["source"]["remove_silence"])
        self.assertIsNone(migrated["source"]["speed"])
        self.assertIsNone(migrated["source"]["script_id"])

    def test_job_snapshot_stamps_active_tts_parameters(self):
        job = Job(
            id="job_ABC123",
            channel_id="ch_ABC123",
            channel_snapshot={
                "audio_defaults": {
                    "remove_silence": True,
                    "speed": 0.9,
                }
            },
            source={
                "mode": "paste",
                "pasted_script": "A finished narration.",
                "remove_silence": False,
                "speed": 1.25,
            },
        )
        workflow = narration_only_template()
        prepared = prepare_workflow_for_job(job, workflow)
        tts = next(node for node in prepared["nodes"] if node["type"] == "tts.generate")
        active = prepared["extensions"]["narration_processing"][tts["id"]]
        self.assertEqual(active["remove_silence"], False)
        self.assertEqual(active["speed"], 1.25)
        # Runtime parameters do not become a second saved-node schema.
        self.assertNotIn("remove_silence", tts["configuration"])

    def test_resolved_parameters_reach_the_tts_service(self):
        captured = {}

        def stop_after_capture(config, _project_id, _context):
            captured.update(config)
            raise RuntimeError("captured")

        context = AdapterContext(
            project_id="pm_ABC123",
            node_id="n_tts",
            narration_processing={"remove_silence": False, "speed": 1.25},
        )
        with mock.patch(
            "scriptase.engine.adapters.tts._step_tts",
            side_effect=stop_after_capture,
        ):
            with self.assertRaisesRegex(RuntimeError, "captured"):
                generate_tts(
                    {"script": "Narration", "settings": {"speed": 0.9}},
                    {"speed": 1.0, "provider_id": "fixture"},
                    context,
                )

        self.assertEqual(captured["speed"], 1.25)
        self.assertIs(captured["remove_silence"], False)


class SilenceProcessingTests(unittest.TestCase):
    def test_long_silence_is_compressed_in_place(self):
        sample_rate = 8_000
        tone_t = np.arange(int(sample_rate * 0.25), dtype=np.float32) / sample_rate
        tone = (0.25 * np.sin(2 * np.pi * 220 * tone_t)).astype(np.float32)
        audio = np.concatenate([
            np.zeros(sample_rate, dtype=np.float32),
            tone,
            np.zeros(sample_rate, dtype=np.float32),
            tone,
            np.zeros(sample_rate, dtype=np.float32),
        ])
        with tempfile.TemporaryDirectory(prefix="scriptase_narration_") as root:
            path = os.path.join(root, "voice.wav")
            sf.write(path, audio, sample_rate)
            result = remove_long_silence(path)
            after = sf.info(path).duration

        self.assertTrue(result["changed"])
        self.assertGreater(result["removed_seconds"], 2.0)
        self.assertLess(after, 1.0)

    def test_cache_separates_processed_and_unprocessed_audio(self):
        plain = cache_key("Text", "Voice", 1.0, "tts", False)
        trimmed = cache_key("Text", "Voice", 1.0, "tts", True)
        self.assertNotEqual(plain, trimmed)


if __name__ == "__main__":
    unittest.main()
