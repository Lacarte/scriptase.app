"""Step 1.1 — ChannelProfile model and store.

Done when: a Channel round-trips create/read/update/delete with a version bump,
and schema validation rejects a malformed pattern block with a structured error.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy

from pydantic import ValidationError

from scriptase.channels import models as channel_models
from scriptase.channels import store as channel_store
from scriptase.channels.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.channels.models import (
    ChannelProfile,
    VisualDirection,
    parse_draft,
    validation_problems,
)
from scriptase.channels.store import (
    ChannelConflict,
    ChannelNotFound,
    ChannelValidationError,
    create_channel,
    default_draft,
    delete_channel,
    get_channel,
    list_channels,
    update_channel,
)


class ChannelStoreTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_channels_")
        self.old_channels = channel_store._channels_dir
        self.old_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(self.temp.name, "channels")
        channel_store._trash_dir = os.path.join(self.temp.name, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_trash
        self.temp.cleanup()

    def _draft(self, **overrides):
        draft = default_draft(name="Philosophy Daily")
        draft["content"] = {
            "niche": "stoicism",
            "language": "en",
            "tone": "educational",
            "duration_target": 60,
        }
        draft["visual_direction"] = {
            "style": "cinematic",
            "pattern": [
                {"narrative_role": "hook", "shot": "extreme close-up"},
                {"narrative_role": "explanation", "shot": "medium cinematic"},
                {"narrative_role": "emotional_beat", "shot": "wide environmental"},
                {"narrative_role": "ending", "shot": "symbolic visual"},
            ],
            "palette": "dark blue + amber",
            "lighting": "moody high contrast",
        }
        draft["audio_defaults"] = {"voice": "Ashley", "speed": 0.95}
        draft["provider_defaults"] = {"script": "inst_script_1", "tts": "inst_tts_1"}
        draft["export_defaults"] = {"aspect_ratio": "9:16", "fps": 30}
        draft.update(overrides)
        return draft


class ChannelCrudTests(ChannelStoreTestBase):
    def test_create_read_update_delete_round_trip_with_version_bump(self):
        created = create_channel(self._draft())
        self.assertRegex(created.id, r"^ch_[A-Z0-9]{6}$")
        self.assertEqual(created.version, 1)
        self.assertEqual(created.schema_version, SCHEMA_VERSION)
        self.assertEqual(created.name, "Philosophy Daily")
        self.assertEqual(created.content.niche, "stoicism")
        self.assertEqual(len(created.visual_direction.pattern), 4)
        self.assertEqual(created.visual_direction.pattern[0].narrative_role, "hook")
        self.assertEqual(created.visual_direction.pattern[0].shot, "extreme close-up")
        self.assertEqual(created.provider_defaults.script, "inst_script_1")
        self.assertIn("immediate hook", created.script_template.brief)
        self.assertEqual(
            created.script_template.sections,
            ["Hook", "Turn", "Why", "Reframe", "Landing"],
        )
        self.assertTrue(created.created_at)
        self.assertEqual(created.created_at, created.updated_at)

        # On-disk document is valid JSON and reloads cleanly.
        path = os.path.join(channel_store._channels_dir, f"{created.id}.json")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(raw["id"], created.id)
        self.assertEqual(raw["version"], 1)

        loaded = get_channel(created.id)
        self.assertEqual(loaded.to_document(), created.to_document())

        # Update bumps content version and refreshes updated_at.
        updated_draft = self._draft(name="Philosophy Nightly")
        updated_draft["content"]["tone"] = "dramatic"
        updated_draft["script_template"] = {
            "brief": "Start with tension and resolve it with one useful insight.",
            "sections": ["Cold Open", "Tension", "Insight", "Close"],
        }
        updated = update_channel(
            created.id, updated_draft, expected_version=created.version
        )
        self.assertEqual(updated.id, created.id)
        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.name, "Philosophy Nightly")
        self.assertEqual(updated.content.tone, "dramatic")
        self.assertEqual(updated.script_template.sections[1], "Tension")
        self.assertEqual(updated.created_at, created.created_at)
        self.assertGreaterEqual(updated.updated_at, created.updated_at)

        reloaded = get_channel(created.id)
        self.assertEqual(reloaded.version, 2)
        self.assertEqual(reloaded.name, "Philosophy Nightly")

        listed = list_channels()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].id, created.id)
        self.assertEqual(listed[0].version, 2)

        # Stale expected_version is a conflict, not a silent overwrite.
        with self.assertRaises(ChannelConflict):
            update_channel(created.id, self._draft(), expected_version=1)

        delete_channel(created.id, expected_version=2)
        with self.assertRaises(ChannelNotFound):
            get_channel(created.id)
        self.assertEqual(list_channels(), [])

        # Soft-delete left a trashed copy.
        trash_entries = os.listdir(channel_store._trash_dir)
        self.assertTrue(any(created.id in name for name in trash_entries))

    def test_music_library_survives_create_and_update(self):
        """Step 6.4 — the ported music panel is read-write, not write-only.

        Both constructors used to omit ``music_library``, so every save silently
        reset the folder and track list to empty.
        """
        draft = self._draft()
        draft["music_library"] = {
            "folder": "Cinematic beds",
            "tracks": ["musics/bed_12345678.mp3"],
        }
        created = create_channel(draft)
        self.assertEqual(created.music_library.folder, "Cinematic beds")
        self.assertEqual(created.music_library.tracks, ["musics/bed_12345678.mp3"])
        self.assertEqual(
            get_channel(created.id).music_library.tracks,
            ["musics/bed_12345678.mp3"],
        )

        draft["music_library"]["tracks"].append("musics/swell_87654321.mp3")
        updated = update_channel(
            created.id, draft, expected_version=created.version
        )
        self.assertEqual(
            updated.music_library.tracks,
            ["musics/bed_12345678.mp3", "musics/swell_87654321.mp3"],
        )
        self.assertEqual(
            get_channel(created.id).music_library.folder, "Cinematic beds"
        )

    def test_update_without_expected_version_still_bumps(self):
        created = create_channel(self._draft())
        updated = update_channel(created.id, self._draft(name="Renamed"))
        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.name, "Renamed")

    def test_delete_missing_raises_not_found(self):
        with self.assertRaises(ChannelNotFound):
            delete_channel("ch_AAAAAA")

    def test_create_rejects_malformed_pattern_with_structured_error(self):
        draft = self._draft()
        draft["visual_direction"]["pattern"] = "hook goes extreme close-up then wide"
        with self.assertRaises(ChannelValidationError) as ctx:
            create_channel(draft)
        problems = ctx.exception.problems
        self.assertTrue(problems, "expected structured validation problems")
        self.assertEqual(ctx.exception.code, "CHANNEL_INVALID")
        # Loc points at the pattern field; message names the free-text rejection.
        joined = " ".join(
            f"{'.'.join(str(p) for p in item.get('loc', ()))} {item.get('msg', '')}"
            for item in problems
        ).lower()
        self.assertIn("pattern", joined)
        self.assertTrue(
            "free text" in joined or "list" in joined,
            f"expected free-text/list rejection, got: {problems}",
        )

    def test_create_rejects_pattern_entry_missing_shot(self):
        draft = self._draft()
        draft["visual_direction"]["pattern"] = [
            {"narrative_role": "hook"},  # missing shot
        ]
        with self.assertRaises(ChannelValidationError) as ctx:
            create_channel(draft)
        problems = ctx.exception.problems
        locs = [".".join(str(p) for p in item.get("loc", ())) for item in problems]
        self.assertTrue(any("pattern" in loc for loc in locs), problems)

    def test_create_rejects_empty_name(self):
        with self.assertRaises(ChannelValidationError):
            create_channel(self._draft(name="   "))

    def test_credentials_are_not_accepted_as_extra_fields(self):
        draft = self._draft()
        draft["api_key"] = "sk-secret"
        with self.assertRaises(ChannelValidationError) as ctx:
            create_channel(draft)
        joined = " ".join(item.get("msg", "") for item in ctx.exception.problems).lower()
        self.assertTrue("extra" in joined or "api_key" in joined.lower())


class PatternValidationTests(unittest.TestCase):
    """Unit-level pattern contract without the store."""

    def test_ordered_map_dict_normalizes_to_list(self):
        direction = VisualDirection.model_validate({
            "pattern": {
                "hook": "extreme close-up",
                "explanation": "medium cinematic",
            }
        })
        self.assertEqual(len(direction.pattern), 2)
        self.assertEqual(direction.pattern[0].narrative_role, "hook")
        self.assertEqual(direction.pattern[0].shot, "extreme close-up")

    def test_free_text_pattern_raises_structured_validation_error(self):
        with self.assertRaises(ValidationError) as ctx:
            VisualDirection.model_validate({"pattern": "just do cinematic stuff"})
        problems = validation_problems(ctx.exception)
        self.assertTrue(problems)
        self.assertTrue(any("pattern" in item.get("loc", []) for item in problems))
        self.assertTrue(
            any("free text" in item.get("msg", "").lower() for item in problems)
        )

    def test_parse_draft_accepts_full_contract_shape(self):
        draft = parse_draft(default_draft(name="Test"))
        self.assertEqual(draft.name, "Test")
        self.assertEqual(len(draft.visual_direction.pattern), 4)


class ChannelMigrationTests(ChannelStoreTestBase):
    def test_v4_channel_migrates_media_library(self):
        created = create_channel(self._draft())
        path = os.path.join(channel_store._channels_dir, f"{created.id}.json")
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw["schema_version"] = 4
        raw["branding"].pop("thumbnail_asset_id", None)
        raw.pop("music_library", None)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)

        loaded = get_channel(created.id)

        self.assertEqual(loaded.schema_version, SCHEMA_VERSION)
        self.assertIsNone(loaded.branding.thumbnail_asset_id)
        self.assertEqual(loaded.music_library.tracks, [])

    def test_media_library_rejects_browser_filesystem_paths(self):
        draft = self._draft()
        draft["branding"] = {"thumbnail_asset_id": r"C:\\Users\\me\\thumb.png"}
        with self.assertRaises(ChannelValidationError):
            create_channel(draft)

        draft = self._draft()
        draft["music_library"] = {
            "folder": "Bad",
            "tracks": [r"C:\\Music\\track.mp3"],
        }
        with self.assertRaises(ChannelValidationError):
            create_channel(draft)

    def test_v1_channel_migrates_to_default_script_template(self):
        created = create_channel(self._draft())
        path = os.path.join(channel_store._channels_dir, f"{created.id}.json")
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw["schema_version"] = 1
        raw.pop("script_template")
        raw["visual_direction"].pop("style_prompt", None)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)

        loaded = get_channel(created.id)

        self.assertEqual(loaded.schema_version, SCHEMA_VERSION)
        self.assertEqual(
            loaded.script_template.sections,
            ["Hook", "Turn", "Why", "Reframe", "Landing"],
        )
        self.assertEqual(loaded.visual_direction.style_prompt, "cinematic")
        self.assertEqual(loaded.version, 1)
        with open(path, encoding="utf-8") as handle:
            persisted = json.load(handle)
        self.assertEqual(persisted["script_template"], loaded.script_template.model_dump())

    def test_missing_schema_version_is_stamped_on_load(self):
        created = create_channel(self._draft())
        path = os.path.join(channel_store._channels_dir, f"{created.id}.json")
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw.pop("schema_version", None)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)

        loaded = get_channel(created.id)
        self.assertEqual(loaded.schema_version, SCHEMA_VERSION)
        # Content version is untouched by schema stamping.
        self.assertEqual(loaded.version, 1)

        # Second load is a no-op rewrite (already current).
        again = get_channel(created.id)
        self.assertEqual(again.schema_version, SCHEMA_VERSION)

    def test_apply_migrations_is_idempotent(self):
        doc = {
            "id": "ch_AAAAAA",
            "name": "X",
            "version": 1,
            "schema_version": SCHEMA_VERSION,
        }
        migrated, changed = apply_migrations(doc)
        self.assertFalse(changed)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)

    def test_channel_profile_round_trips_through_model_dump(self):
        created = create_channel(self._draft())
        restored = ChannelProfile.model_validate(created.to_document())
        self.assertEqual(restored.to_document(), created.to_document())


if __name__ == "__main__":
    unittest.main()
