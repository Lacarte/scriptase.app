"""Prompt Lab service + routes: preview, decomposition, and recent listing."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from scriptase.modules.lab import service as lab_service
from scriptase.modules.lab.service import list_recent_prompts, preview_prompt


class PreviewTests(unittest.TestCase):
    def test_preview_builds_both_prompts(self):
        r = preview_prompt({
            "preset_style": "stickman_animation",
            "story_category": "psychology",
            "niche_preset": "dark_psychology",
            "duration": 60,
            "idea": "guilt to control people",
        })
        self.assertTrue(r["system_prompt"].strip())
        self.assertTrue(r["user_prompt"].strip())
        # 60s * 2.5 words/sec.
        self.assertEqual(r["word_target"], 150)
        self.assertEqual(r["inputs"]["idea"], "guilt to control people")

    def test_preview_decomposes_the_user_prompt_into_labeled_parts(self):
        r = preview_prompt({"story_category": "psychology", "duration": 60,
                            "niche_preset": "dark_psychology"})
        labels = [p["label"] for p in r["decomposed"]]
        self.assertIn("Base instruction", labels)
        self.assertIn("CREATIVE DIRECTION", labels)
        # The idea block only appears when an idea was supplied.
        self.assertNotIn("Build the story around this idea", labels)

    def test_preview_tolerates_empty_input(self):
        r = preview_prompt({})
        self.assertTrue(r["system_prompt"])
        self.assertEqual(r["inputs"]["language"], "english")


class RecentTests(unittest.TestCase):
    def test_lists_only_stories_that_carry_a_prompt_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            # One story with a prompt, one without.
            for pid, has_prompt in (("pm_AAA111", True), ("pm_BBB222", False)):
                os.makedirs(os.path.join(tmp, pid))
                doc = {
                    "project_id": pid,
                    "story_text": "Hook: a line.",
                    "metadata": {"timestamp": f"2026-01-0{1 if has_prompt else 2}T00:00:00",
                                 "story_category": "psychology", "word_count": 3},
                }
                if has_prompt:
                    doc["prompt"] = {
                        "system_prompt": "SYS", "user_prompt": "CREATIVE DIRECTION: x",
                        "word_target": 150, "inputs": {"idea": "y"},
                    }
                with open(os.path.join(tmp, pid, "story.json"), "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)

            with mock.patch.object(lab_service, "STORIES_DIR", tmp):
                rows = list_recent_prompts()

            ids = [r["project_id"] for r in rows]
            self.assertIn("pm_AAA111", ids)
            self.assertNotIn("pm_BBB222", ids)
            self.assertIn("decomposed", rows[0]["prompt"])

    def test_missing_stories_dir_is_empty(self):
        with mock.patch.object(lab_service, "STORIES_DIR", "/no/such/dir"):
            self.assertEqual(list_recent_prompts(), [])


class RouteTests(unittest.TestCase):
    def _client(self):
        from flask import Flask
        from scriptase.modules.lab import lab_bp

        app = Flask(__name__)
        app.register_blueprint(lab_bp)
        return app.test_client()

    def test_preview_endpoint(self):
        client = self._client()
        resp = client.post("/api/lab/prompt-preview", json={
            "story_category": "psychology", "duration": 30, "niche_preset": "dark_psychology",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["word_target"], 75)

    def test_preview_rejects_non_object_body(self):
        client = self._client()
        resp = client.post("/api/lab/prompt-preview", json=[1, 2, 3])
        self.assertEqual(resp.status_code, 400)

    def test_recent_endpoint_shape(self):
        client = self._client()
        resp = client.get("/api/lab/prompts?limit=3")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("prompts", resp.get_json())


if __name__ == "__main__":
    unittest.main()
