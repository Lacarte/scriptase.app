"""The `n8n` script provider: payload shape, parsing, and error mapping."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import requests as http_requests

from scriptase.modules.script.providers.n8n import provider as n8n_provider
from scriptase.modules.script.providers.n8n.provider import (
    N8nScriptProvider,
    _build_payload,
)
from scriptase.providers.errors import (
    PROVIDER_REQUEST_INVALID,
    PROVIDER_RESPONSE_MALFORMED,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
)

_CONFIG = {
    "niche_preset": "dark_psychology",
    "preset_style": "cinematic",
    "story_category": "dark_psychology",
    "story_tone": "suspenseful",
    "language": "en",
    "duration": 60,
    "template_brief": "Open with a hook, turn, why, reframe, landing.",
    "template_sections": ["Hook", "Turn", "Why", "Reframe", "Landing"],
    "webhook_url": "http://localhost:5678/webhook/story-generator",
}

_SCRIPT = (
    "Hook: A mind can betray itself.\n"
    "Build: It starts with one small lie.\n"
    "Climax: The truth finally surfaces.\n"
    "CTA: Watch what you tell yourself."
)


class PayloadTests(unittest.TestCase):
    def test_payload_carries_the_channel_shape_verbatim(self):
        payload = _build_payload(_CONFIG)
        self.assertEqual(payload["niche_preset"], "dark_psychology")
        self.assertEqual(payload["preset_style"], "cinematic")
        self.assertEqual(payload["story_category"], "dark_psychology")
        self.assertEqual(payload["story_tone"], "suspenseful")
        self.assertEqual(payload["language"], "en")
        self.assertEqual(payload["duration"], 60)
        self.assertEqual(payload["template_brief"], _CONFIG["template_brief"])
        self.assertEqual(payload["template_sections"], _CONFIG["template_sections"])

    def test_payload_accepts_v2_request_key_aliases(self):
        payload = _build_payload({
            "style": "noir",
            "category": "true_crime",
            "tone": "grim",
            "target_duration_s": 90,
        })
        self.assertEqual(payload["preset_style"], "noir")
        self.assertEqual(payload["story_category"], "true_crime")
        self.assertEqual(payload["story_tone"], "grim")
        self.assertEqual(payload["duration"], 90)

    def test_payload_defaults_template_when_absent(self):
        payload = _build_payload({"niche_preset": "x"})
        self.assertTrue(payload["template_brief"])
        self.assertEqual(payload["template_sections"][0], "Hook")
        self.assertEqual(payload["duration"], 60)


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(
            n8n_provider, "STORIES_DIR", self._tmp.name
        )
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_generate_posts_payload_and_writes_document(self):
        sent = {}

        def caller(url, payload, timeout=120, label=""):
            sent["url"] = url
            sent["payload"] = payload
            return {"story_text": _SCRIPT}

        doc = N8nScriptProvider().generate(
            _CONFIG, project_id="pm_TEST01", webhook_caller=caller
        )
        self.assertEqual(sent["url"], _CONFIG["webhook_url"])
        self.assertEqual(sent["payload"]["niche_preset"], "dark_psychology")
        self.assertEqual(sent["payload"]["template_sections"][0], "Hook")
        self.assertEqual(doc["metadata"]["provider"], "n8n")
        self.assertGreater(doc["metadata"]["word_count"], 0)
        self.assertIn("hook", doc["sections"])
        self.assertTrue(os.path.isfile(doc["path"]))

    def test_generate_reads_script_from_output_key(self):
        doc = N8nScriptProvider().generate(
            _CONFIG,
            project_id="pm_TEST02",
            webhook_caller=lambda *a, **k: {"output": _SCRIPT},
        )
        self.assertIn("betray", doc["story_text"].lower())

    def test_empty_response_is_response_malformed(self):
        with self.assertRaises(ProviderError) as ctx:
            N8nScriptProvider().generate(
                _CONFIG,
                project_id="pm_TEST03",
                webhook_caller=lambda *a, **k: {"story_text": "   "},
            )
        self.assertEqual(ctx.exception.code, PROVIDER_RESPONSE_MALFORMED)

    def test_unsafe_webhook_is_request_invalid(self):
        with self.assertRaises(ProviderError) as ctx:
            N8nScriptProvider().generate(
                {**_CONFIG, "webhook_url": "not-a-url"},
                project_id="pm_TEST04",
                webhook_caller=lambda *a, **k: {"story_text": _SCRIPT},
            )
        self.assertEqual(ctx.exception.code, PROVIDER_REQUEST_INVALID)

    def test_timeout_maps_to_provider_timeout(self):
        def caller(*a, **k):
            raise http_requests.Timeout("slow")

        with self.assertRaises(ProviderError) as ctx:
            N8nScriptProvider().generate(
                _CONFIG, project_id="pm_TEST05", webhook_caller=caller
            )
        self.assertEqual(ctx.exception.code, PROVIDER_TIMEOUT)

    def test_connection_error_maps_to_transport_failed(self):
        def caller(*a, **k):
            raise http_requests.ConnectionError("down")

        with self.assertRaises(ProviderError) as ctx:
            N8nScriptProvider().generate(
                _CONFIG, project_id="pm_TEST06", webhook_caller=caller
            )
        self.assertEqual(ctx.exception.code, PROVIDER_TRANSPORT_FAILED)

    def test_error_never_carries_the_response_body(self):
        def caller(*a, **k):
            raise RuntimeError("SECRET webhook body 12345")

        with self.assertRaises(ProviderError) as ctx:
            N8nScriptProvider().generate(
                _CONFIG, project_id="pm_TEST07", webhook_caller=caller
            )
        self.assertNotIn("SECRET", ctx.exception.message)
        self.assertNotIn("12345", ctx.exception.message)


class RegistrationTests(unittest.TestCase):
    def test_registered_in_the_script_catalog(self):
        from scriptase.providers.hub import hub

        hub.discover_all()
        instance = hub.get("script", "n8n")
        self.assertIsNotNone(instance)
        self.assertEqual(instance.domain, "script")
        self.assertEqual(instance.kind, "webhook")
        self.assertEqual(instance.label, "Script Generator")


class SeededInstanceTests(unittest.TestCase):
    """The passerelle is seeded beside the gemini default (fresh + migration)."""

    def test_fresh_install_seeds_the_script_generator_instance(self):
        from scriptase.providers.settings_manager import _default_settings

        script = _default_settings()["domains"]["script"]
        self.assertIn("n8n", script["instances"])
        self.assertEqual(script["instances"]["n8n"]["label"], "Script Generator")
        # The default selection is untouched.
        self.assertEqual(script["selected_instance_id"], "gemini")

    def test_migration_adds_the_instance_without_disturbing_gemini(self):
        from scriptase.providers.settings_migrations import (
            apply_migrations,
            SETTINGS_VERSION,
        )

        old = {
            "version": 11,
            "domains": {
                "script": {
                    "selected_instance_id": "gemini",
                    "instances": {
                        "gemini": {"type": "gemini", "label": "gemini", "settings": {}},
                    },
                }
            },
        }
        migrated, changed = apply_migrations(old, {})
        self.assertTrue(changed)
        self.assertEqual(migrated["version"], SETTINGS_VERSION)
        script = migrated["domains"]["script"]
        self.assertIn("n8n", script["instances"])
        self.assertEqual(script["instances"]["n8n"]["label"], "Script Generator")
        self.assertIn("gemini", script["instances"])
        self.assertEqual(script["selected_instance_id"], "gemini")

    def test_migration_is_idempotent(self):
        from scriptase.providers.settings_migrations import apply_migrations

        seeded = {
            "version": 12,
            "domains": {
                "script": {
                    "selected_instance_id": "gemini",
                    "instances": {
                        "gemini": {"type": "gemini", "label": "gemini", "settings": {}},
                        "n8n": {"type": "n8n", "label": "Script Generator", "settings": {}},
                    },
                }
            },
        }
        _migrated, changed = apply_migrations(seeded, {})
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
