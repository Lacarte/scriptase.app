"""Step 1.3 — Channel API, UI-facing routes, and niche-preset migration.

Done when: every niche preset appears as an editable starter Channel and a new
Channel can be created, edited, and deleted end-to-end.
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from unittest import mock

from app import create_app
from scriptase.channels import presets as channel_presets
from scriptase.channels import store as channel_store
from scriptase.channels.presets import (
    get_presets,
    preset_to_channel_draft,
    seed_starter_channels,
)
from scriptase.channels.store import create_channel, get_channel, list_channels


class ChannelApiTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_ch_api_")
        self.old_channels = channel_store._channels_dir
        self.old_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(self.temp.name, "channels")
        channel_store._trash_dir = os.path.join(self.temp.name, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)

        # Avoid discovering real providers for a thin route suite.
        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_trash
        self.temp.cleanup()


class NichePresetMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_ch_seed_")
        self.old_channels = channel_store._channels_dir
        self.old_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(self.temp.name, "channels")
        channel_store._trash_dir = os.path.join(self.temp.name, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_trash
        self.temp.cleanup()

    def test_preset_maps_onto_content_visual_and_audio(self):
        presets = get_presets()
        self.assertGreaterEqual(len(presets), 20, "expected a full niche catalog")

        # Prefer a known built-in; fall back to the first entry.
        preset_id = "stoicism_cinematic"
        if preset_id not in presets:
            preset_id = next(iter(presets))
        preset = presets[preset_id]
        draft = preset_to_channel_draft(preset_id, preset)

        self.assertEqual(draft["name"], preset.get("label") or draft["name"])
        self.assertEqual(draft["content"]["niche"], preset.get("niche") or preset_id)
        self.assertEqual(draft["content"]["tone"], preset.get("story_tone") or "")
        self.assertEqual(
            draft["content"]["duration_target"],
            int(preset.get("duration") or 0) or draft["content"]["duration_target"],
        )
        self.assertEqual(
            draft["visual_direction"]["style"],
            preset.get("visual_style") or draft["visual_direction"]["style"],
        )
        self.assertEqual(draft["audio_defaults"]["voice"], preset.get("voice") or "")
        self.assertAlmostEqual(
            float(draft["audio_defaults"]["speed"]),
            float(preset.get("speed") or 1.0),
            places=2,
        )
        # Structured pattern — never free text.
        pattern = draft["visual_direction"]["pattern"]
        self.assertIsInstance(pattern, list)
        self.assertGreaterEqual(len(pattern), 1)
        self.assertIn("narrative_role", pattern[0])
        self.assertIn("shot", pattern[0])
        # No credentials, no account config.
        self.assertIsNone(draft["audio_defaults"]["tts_provider_instance_id"])
        self.assertEqual(draft["provider_defaults"], {})

    def test_seed_creates_one_channel_per_preset_idempotently(self):
        presets = get_presets()
        first = seed_starter_channels()
        self.assertEqual(first["total_presets"], len(presets))
        self.assertEqual(first["created"], len(presets))
        self.assertEqual(first["skipped"], 0)
        self.assertEqual(len(list_channels(limit=500)), len(presets))

        second = seed_starter_channels()
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], len(presets))
        self.assertEqual(len(list_channels(limit=500)), len(presets))

        # Every preset is represented and loadable/editable.
        for preset_id, channel_id in first["channel_ids"].items():
            document = get_channel(channel_id)
            self.assertEqual(document.id, channel_id)
            self.assertTrue(document.name)
            # Mapped fields survived create.
            source = presets[preset_id]
            if source.get("niche"):
                self.assertEqual(document.content.niche, source["niche"])
            if source.get("visual_style"):
                self.assertEqual(
                    document.visual_direction.style, source["visual_style"]
                )
            self.assertTrue(document.script_template.brief)
            self.assertEqual(
                document.script_template.sections,
                ["Hook", "Turn", "Why", "Reframe", "Landing"],
            )


class ChannelCrudApiTests(ChannelApiTestBase):
    def test_create_get_update_delete_end_to_end(self):
        create = self.client.post(
            "/api/channels",
            json={
                "channel": {
                    "name": "Philosophy Daily",
                    "content": {
                        "niche": "stoicism",
                        "tone": "educational",
                        "duration_target": 60,
                    },
                    "script_template": {
                        "brief": "Start with a paradox and resolve it practically.",
                        "sections": ["Paradox", "Example", "Lesson"],
                    },
                    "visual_direction": {
                        "style": "cinematic",
                        "pattern": [
                            {"narrative_role": "hook", "shot": "extreme close-up"},
                            {"narrative_role": "ending", "shot": "symbolic visual"},
                        ],
                    },
                    "audio_defaults": {"voice": "af_heart", "speed": 0.95},
                    "provider_defaults": {"script": "inst_script_1"},
                }
            },
        )
        self.assertEqual(create.status_code, 201, create.get_json())
        body = create.get_json()
        channel = body["channel"]
        channel_id = channel["id"]
        self.assertRegex(channel_id, r"^ch_[A-Z0-9]{6}$")
        self.assertEqual(channel["version"], 1)
        self.assertEqual(channel["name"], "Philosophy Daily")
        self.assertEqual(channel["provider_defaults"]["script"], "inst_script_1")
        self.assertEqual(
            channel["script_template"]["sections"],
            ["Paradox", "Example", "Lesson"],
        )
        # No secret fields ever appear.
        blob = str(body)
        self.assertNotIn("api_key", blob.lower())
        self.assertNotIn("secret", blob.lower())

        got = self.client.get(f"/api/channels/{channel_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["channel"]["id"], channel_id)

        updated = self.client.put(
            f"/api/channels/{channel_id}",
            json={
                "expected_version": 1,
                "channel": {
                    "name": "Philosophy Nightly",
                    "content": {
                        "niche": "stoicism",
                        "tone": "dramatic",
                        "duration_target": 75,
                    },
                    "script_template": {
                        "brief": "Lead with the lesson, then reveal its cause.",
                        "sections": ["Lesson", "Cause", "Landing"],
                    },
                    "visual_direction": {
                        "style": "noir",
                        "pattern": [
                            {"narrative_role": "hook", "shot": "wide environmental"},
                        ],
                    },
                    "audio_defaults": {"voice": "am_michael", "speed": 0.9},
                },
            },
        )
        self.assertEqual(updated.status_code, 200, updated.get_json())
        doc = updated.get_json()["channel"]
        self.assertEqual(doc["version"], 2)
        self.assertEqual(doc["name"], "Philosophy Nightly")
        self.assertEqual(doc["content"]["tone"], "dramatic")
        self.assertEqual(doc["visual_direction"]["style"], "noir")
        self.assertEqual(doc["script_template"]["sections"], ["Lesson", "Cause", "Landing"])

        # Stale version → conflict.
        conflict = self.client.put(
            f"/api/channels/{channel_id}",
            json={
                "expected_version": 1,
                "channel": {"name": "stale"},
            },
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.get_json()["error"]["code"], "CHANNEL_CONFLICT")

        # Free-text pattern rejected with structured problems.
        bad = self.client.put(
            f"/api/channels/{channel_id}",
            json={
                "expected_version": 2,
                "channel": {
                    "name": "x",
                    "visual_direction": {"pattern": "just do cinematic stuff"},
                },
            },
        )
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.get_json()["error"]["code"], "CHANNEL_INVALID")
        problems = bad.get_json()["error"]["details"]["problems"]
        self.assertTrue(problems)

        deleted = self.client.delete(
            f"/api/channels/{channel_id}?expected_version=2"
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.get_json()["deleted"])
        missing = self.client.get(f"/api/channels/{channel_id}")
        self.assertEqual(missing.status_code, 404)

    def test_list_seeds_starters_and_returns_summaries(self):
        response = self.client.get("/api/channels?limit=500")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        presets = get_presets()
        self.assertEqual(payload["seed"]["total_presets"], len(presets))
        self.assertEqual(payload["seed"]["created"], len(presets))
        self.assertEqual(payload["total"], len(presets))
        self.assertEqual(len(payload["channels"]), len(presets))
        self.assertEqual(len(payload["starter_mappings"]), len(presets))

        # Second list is a no-op reseed.
        again = self.client.get("/api/channels?limit=500")
        self.assertEqual(again.get_json()["seed"]["created"], 0)
        self.assertEqual(again.get_json()["seed"]["skipped"], len(presets))

        # Every starter is editable via GET.
        sample_id = payload["channels"][0]["id"]
        detail = self.client.get(f"/api/channels/{sample_id}")
        self.assertEqual(detail.status_code, 200)
        channel = detail.get_json()["channel"]
        self.assertTrue(channel["visual_direction"]["pattern"])

    def test_seed_endpoint(self):
        response = self.client.post("/api/channels/seed", json={})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["created"], body["total_presets"])
        self.assertGreaterEqual(body["total_presets"], 20)

    def test_logo_ref_accepted_from_managed_branding_path(self):
        """Channel stores a managed branding ref — never a raw filesystem path."""
        create = self.client.post(
            "/api/channels",
            json={
                "channel": {
                    "name": "Branded",
                    "branding": {
                        "logo_asset_id": "branding/logo_deadbeef.png",
                        "enabled": True,
                        "position": "top_right",
                        "size": 0.1,
                        "opacity": 0.9,
                        "margin": 0.04,
                    },
                }
            },
        )
        self.assertEqual(create.status_code, 201, create.get_json())
        branding = create.get_json()["channel"]["branding"]
        self.assertEqual(branding["logo_asset_id"], "branding/logo_deadbeef.png")
        self.assertTrue(branding["enabled"])
        # Absolute paths must never be the stored form.
        self.assertFalse(branding["logo_asset_id"].startswith("/"))
        self.assertNotIn(":\\", branding["logo_asset_id"])


class BrandingUploadStillWorks(unittest.TestCase):
    """Managed branding endpoint remains the logo ingress for the Channel UI."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_brand_")
        self.branding_dir = os.path.join(self.temp.name, "branding")
        os.makedirs(self.branding_dir, exist_ok=True)
        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.patcher = mock.patch(
            "scriptase.engine.routes.BRANDING_DIR", self.branding_dir
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_png_upload_returns_managed_ref(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), color=(20, 40, 80)).save(buf, format="PNG")
        png = buf.getvalue()
        response = self.client.post(
            "/api/workflow/branding",
            data={"file": (io.BytesIO(png), "logo.png")},
            content_type="multipart/form-data",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        asset = response.get_json()["asset"]
        self.assertTrue(asset["ref"].startswith("branding/"))
        self.assertTrue(asset["url"].startswith("/output/branding/"))


if __name__ == "__main__":
    unittest.main()
