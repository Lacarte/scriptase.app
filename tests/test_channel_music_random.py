"""Channel random-music default: model, migration v8, and adapter wiring."""

from __future__ import annotations

import unittest

from scriptase.channels.migrations import apply_migrations
from scriptase.channels.models import (
    AudioDefaults,
    CHANNEL_SCHEMA_VERSION,
    DEFAULT_MUSIC_FOLDER,
    MusicLibrary,
)
from scriptase.engine.adapters.music import _resolve_mode
from scriptase.jobs.channel_settings import channel_settings_from_snapshot


class ModelDefaultsTests(unittest.TestCase):
    def test_music_random_is_on_by_default(self):
        self.assertIs(AudioDefaults().music_random, True)

    def test_music_folder_defaults_to_bundled_location(self):
        self.assertEqual(MusicLibrary().folder, DEFAULT_MUSIC_FOLDER)


class MigrationTests(unittest.TestCase):
    def test_no_bed_gets_random_on(self):
        migrated, changed = apply_migrations({
            "schema_version": 7,
            "audio_defaults": {},
        })
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], CHANNEL_SCHEMA_VERSION)
        self.assertIs(migrated["audio_defaults"]["music_random"], True)
        self.assertEqual(migrated["music_library"]["folder"], DEFAULT_MUSIC_FOLDER)

    def test_curated_bed_keeps_random_off(self):
        # A Channel that deliberately chose a bed must not silently go random.
        migrated, _ = apply_migrations({
            "schema_version": 7,
            "audio_defaults": {"music_profile": "musics/theme.mp3"},
        })
        self.assertIs(migrated["audio_defaults"]["music_random"], False)

    def test_user_folder_is_not_overwritten(self):
        migrated, _ = apply_migrations({
            "schema_version": 7,
            "music_library": {"folder": "D:/mine", "tracks": []},
            "audio_defaults": {},
        })
        self.assertEqual(migrated["music_library"]["folder"], "D:/mine")

    def test_existing_music_random_is_respected(self):
        migrated, _ = apply_migrations({
            "schema_version": 7,
            "audio_defaults": {"music_random": False, "music_profile": ""},
        })
        self.assertIs(migrated["audio_defaults"]["music_random"], False)


class AdapterModeTests(unittest.TestCase):
    def test_random_on_selects_random(self):
        self.assertEqual(
            _resolve_mode({"mode": "tone"}, {"music_random": True}), "random"
        )

    def test_random_off_with_profile_selects_specific(self):
        self.assertEqual(
            _resolve_mode(
                {"mode": "tone"},
                {"music_random": False, "music_profile": "musics/theme.mp3"},
            ),
            "specific",
        )

    def test_explicit_node_mode_wins_over_channel(self):
        # An author who dialed a non-default mode on the node means it.
        self.assertEqual(
            _resolve_mode({"mode": "specific"}, {"music_random": True}), "specific"
        )

    def test_nothing_set_falls_back_to_tone(self):
        self.assertEqual(_resolve_mode({"mode": "tone"}, {}), "tone")


class ChannelSettingsTests(unittest.TestCase):
    def test_snapshot_emits_music_random(self):
        settings = channel_settings_from_snapshot({
            "audio_defaults": {"music_random": False},
        })
        self.assertIs(settings["music_random"], False)

    def test_snapshot_defaults_music_random_true(self):
        settings = channel_settings_from_snapshot({"audio_defaults": {}})
        self.assertIs(settings["music_random"], True)


if __name__ == "__main__":
    unittest.main()
