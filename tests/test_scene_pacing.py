"""Channel scene-pacing default: model, migration, settings, and segmenter wiring."""

from __future__ import annotations

import unittest

from scriptase.channels.migrations import apply_migrations
from scriptase.channels.models import AudioDefaults, CHANNEL_SCHEMA_VERSION
from scriptase.jobs.channel_settings import channel_settings_from_snapshot
from scriptase.engine.adapters.segmenter import _with_channel_pacing
from scriptase.modules.segmenter.algorithm import PACING_PRESETS, pacing_config


class ModelTests(unittest.TestCase):
    def test_defaults_to_balanced(self):
        self.assertEqual(AudioDefaults().scene_pacing, "balanced")

    def test_accepts_the_three_presets(self):
        for preset in ("fast", "balanced", "cinematic"):
            self.assertEqual(AudioDefaults(scene_pacing=preset).scene_pacing, preset)

    def test_rejects_an_unknown_preset(self):
        with self.assertRaises(ValueError):
            AudioDefaults(scene_pacing="wild")


class MigrationTests(unittest.TestCase):
    def test_legacy_channel_gets_balanced(self):
        migrated, changed = apply_migrations({"schema_version": 8, "audio_defaults": {}})
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], CHANNEL_SCHEMA_VERSION)
        self.assertEqual(migrated["audio_defaults"]["scene_pacing"], "balanced")

    def test_existing_pacing_is_preserved(self):
        migrated, _ = apply_migrations(
            {"schema_version": 8, "audio_defaults": {"scene_pacing": "cinematic"}}
        )
        self.assertEqual(migrated["audio_defaults"]["scene_pacing"], "cinematic")


class SettingsTests(unittest.TestCase):
    def test_snapshot_emits_scene_pacing(self):
        settings = channel_settings_from_snapshot({"audio_defaults": {"scene_pacing": "fast"}})
        self.assertEqual(settings["scene_pacing"], "fast")

    def test_snapshot_defaults_to_balanced(self):
        settings = channel_settings_from_snapshot({"audio_defaults": {}})
        self.assertEqual(settings["scene_pacing"], "balanced")


class PresetTests(unittest.TestCase):
    def test_balanced_band_targets_a_five_second_clip(self):
        band = PACING_PRESETS["balanced"]
        self.assertLessEqual(band["target_max"], 5.0)
        self.assertLess(band["target_min"], band["target_max"])
        self.assertGreaterEqual(band["hard_max"], band["target_max"])

    def test_bands_increase_from_fast_to_cinematic(self):
        self.assertLess(PACING_PRESETS["fast"]["target_max"], PACING_PRESETS["balanced"]["target_max"])
        self.assertLess(PACING_PRESETS["balanced"]["target_max"], PACING_PRESETS["cinematic"]["target_max"])

    def test_unknown_preset_yields_no_knobs(self):
        self.assertEqual(pacing_config("nope"), {})


class _Ctx:
    def __init__(self, pacing):
        self.channel_settings = {"scene_pacing": pacing}


class AdapterTests(unittest.TestCase):
    def test_channel_pacing_fills_the_band(self):
        cfg = _with_channel_pacing({}, _Ctx("cinematic"))
        self.assertEqual(cfg["target_min"], 5.0)
        self.assertEqual(cfg["target_max"], 7.0)
        self.assertEqual(cfg["hard_max"], 8.5)

    def test_explicit_node_knob_wins_over_the_band(self):
        cfg = _with_channel_pacing({"target_max": 3.0}, _Ctx("cinematic"))
        self.assertEqual(cfg["target_max"], 3.0)
        # The knobs the node did not set still come from the band.
        self.assertEqual(cfg["target_min"], 5.0)

    def test_a_segment_config_override_owns_every_knob(self):
        cfg = _with_channel_pacing({"segment_config": {"target_min": 9}}, _Ctx("cinematic"))
        self.assertNotIn("target_min", cfg)
        self.assertEqual(cfg["segment_config"], {"target_min": 9})

    def test_no_channel_pacing_leaves_config_untouched(self):
        cfg = _with_channel_pacing({}, _Ctx(""))
        self.assertNotIn("target_min", cfg)


if __name__ == "__main__":
    unittest.main()
