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

    def test_run_failure_returns_nested_error_with_code(self):
        # A failed run must return {"error": {"code", "message"}} — the shape the
        # frontend api client parses — never a bodyless 500 or a flat string.
        import scriptase.modules.lab.experiment as E

        def boom(*a, **k):
            raise RuntimeError("connection refused")

        client = self._client()
        with mock.patch.object(E, "call_webhook", boom, create=True):
            resp = client.post("/api/lab/run", json={
                "variant_id": "builtin",
                "overrides": {"story_category": "psychology",
                              "niche_preset": "dark_psychology", "duration": 30},
            })
        self.assertEqual(resp.status_code, 502)
        err = resp.get_json()["error"]
        self.assertEqual(err["code"], "GENERATION_FAILED")
        self.assertTrue(err["message"])

    def test_run_with_malformed_channel_is_404_not_500(self):
        # A bad channel-id format used to raise ValueError -> uncaught 500; it
        # must now be a clean CHANNEL_NOT_FOUND.
        client = self._client()
        resp = client.post("/api/lab/run", json={"channel_id": "not-a-real-id"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["error"]["code"], "CHANNEL_NOT_FOUND")


class VariantTests(unittest.TestCase):
    def setUp(self):
        import scriptase.modules.lab.variants as V
        self._tmp = tempfile.mkdtemp()
        self._patch = mock.patch.object(V, "VARIANTS_DIR", self._tmp)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_builtin_is_always_first_and_readonly(self):
        from scriptase.modules.lab.variants import list_variants, delete_variant
        vs = list_variants()
        self.assertEqual(vs[0]["id"], "builtin")
        self.assertTrue(vs[0]["builtin"])
        self.assertFalse(delete_variant("builtin"))

    def test_create_update_delete_roundtrip(self):
        from scriptase.modules.lab.variants import (
            create_variant, update_variant, delete_variant, get_variant,
        )
        v = create_variant({"name": "Q hooks", "angle_pool": ["Ask a question"],
                             "word_target_ratio": 0.8})
        self.assertEqual(v["version"], 1)
        self.assertEqual(v["word_target_ratio"], 0.8)
        v2 = update_variant(v["id"], {"name": "Q hooks v2"})
        self.assertEqual(v2["version"], 2)
        self.assertEqual(get_variant(v["id"])["name"], "Q hooks v2")
        self.assertTrue(delete_variant(v["id"]))
        self.assertIsNone(get_variant(v["id"]))

    def test_rejects_bad_temperature(self):
        from scriptase.modules.lab.variants import create_variant
        with self.assertRaises(ValueError):
            create_variant({"name": "bad", "temperature": 5})


class ExperimentTests(unittest.TestCase):
    def test_variant_overrides_reach_the_prompt(self):
        from scriptase.modules.lab import variants as V
        from scriptase.modules.lab.experiment import build_prompt
        tmp = tempfile.mkdtemp()
        with mock.patch.object(V, "VARIANTS_DIR", tmp):
            var = V.create_variant({
                "name": "forced",
                "angle_pool": ["Begin with a provocative question that challenges assumptions"],
                "extra_directives": ["Make it more emotional"],
                "word_target_ratio": 0.8,
            })
            p = build_prompt(variant_id=var["id"], overrides={
                "story_category": "psychology", "niche_preset": "dark_psychology", "duration": 60,
            })
        self.assertIn("provocative question", p["user_prompt"])
        self.assertIn("Make it more emotional", p["user_prompt"])
        self.assertEqual(p["word_target"], 120)  # 150 * 0.8

    def test_run_generates_and_scores(self):
        import scriptase.modules.lab.experiment as E
        tmp = tempfile.mkdtemp()

        def fake(url, payload, timeout=120, label=""):
            return {"story_text":
                    "Hook: Your mind lies to you.\n"
                    "Build: It starts small, a whisper of doubt that grows louder.\n"
                    "Climax: But the truth is you were capable all along.\n"
                    "CTA: So what will you choose tomorrow?"}

        with mock.patch.object(E, "RUNS_DIR", tmp):
            run = E.run_experiment(
                variant_id="builtin",
                overrides={"story_category": "psychology", "niche_preset": "dark_psychology", "duration": 60},
                webhook_caller=fake,
            )
        self.assertIn("score", run)
        self.assertGreaterEqual(run["score"]["score"], 0)
        self.assertTrue(run["score"]["dimensions"])
        self.assertTrue(run["story_text"])

    def test_empty_result_raises(self):
        from scriptase.modules.lab.experiment import run_experiment, ExperimentError
        with self.assertRaises(ExperimentError):
            run_experiment(webhook_caller=lambda *a, **k: {"story_text": "   "})

    def test_run_includes_llm_second_opinion_when_available(self):
        # With the LLM judge reachable, the run carries both scores.
        import scriptase.modules.lab.experiment as E
        import scriptase.modules.viral.providers.llm_judge.provider as J
        from scriptase.modules.viral.service import score_script
        tmp = tempfile.mkdtemp()
        story = ("Hook: Your mind lies.\nBuild: A whisper grows.\n"
                 "Climax: The truth is you were capable.\nCTA: Choose tomorrow.")
        fake_llm = score_script(story_text=story, target_duration=60)

        with mock.patch.object(E, "RUNS_DIR", tmp), \
             mock.patch.object(J.LlmJudgeViralProvider, "score",
                               lambda self, req, settings=None: fake_llm):
            run = E.run_experiment(
                overrides={"story_category": "psychology", "niche_preset": "dark_psychology", "duration": 60},
                webhook_caller=lambda *a, **k: {"story_text": story},
            )
        self.assertIn("score", run)
        self.assertIsNotNone(run["llm_score"])
        self.assertEqual(run["llm_error"], "")

    def test_llm_judge_failure_is_non_fatal(self):
        # If the LLM judge fails, the run still succeeds on the structural score.
        import scriptase.modules.lab.experiment as E
        import scriptase.modules.viral.providers.llm_judge.provider as J
        from scriptase.providers.errors import ProviderError, PROVIDER_QUOTA_EXHAUSTED
        tmp = tempfile.mkdtemp()

        def boom(self, req, settings=None):
            raise ProviderError(PROVIDER_QUOTA_EXHAUSTED, "out of credit",
                                domain="viral", provider_id="llm_judge")

        with mock.patch.object(E, "RUNS_DIR", tmp), \
             mock.patch.object(J.LlmJudgeViralProvider, "score", boom):
            run = E.run_experiment(
                overrides={"story_category": "psychology", "niche_preset": "dark_psychology", "duration": 30},
                webhook_caller=lambda *a, **k: {"story_text": "Hook: a.\nBuild: b.\nClimax: c.\nCTA: d."},
            )
        self.assertIn("id", run)
        self.assertIsNone(run["llm_score"])
        self.assertIn("credit", run["llm_error"])

    def test_run_can_skip_the_llm_judge(self):
        import scriptase.modules.lab.experiment as E
        tmp = tempfile.mkdtemp()
        with mock.patch.object(E, "RUNS_DIR", tmp):
            run = E.run_experiment(
                overrides={"story_category": "psychology", "niche_preset": "dark_psychology", "duration": 30},
                webhook_caller=lambda *a, **k: {"story_text": "Hook: a.\nBuild: b.\nClimax: c.\nCTA: d."},
                with_llm_judge=False,
            )
        self.assertIsNone(run["llm_score"])

    def test_webhook_error_surfaces_the_real_reason(self):
        # When the webhook reports a failure (its own error body), the Lab shows
        # the categorized reason — not a generic "Script generation failed".
        from scriptase.modules.lab.experiment import run_experiment, ExperimentError
        from scriptase.shared.webhooks import WebhookResponseError

        def caller(*a, **k):
            raise WebhookResponseError("Payment required - perhaps check your payment details?",
                                       status=500)

        with self.assertRaises(ExperimentError) as ctx:
            run_experiment(
                overrides={"story_category": "psychology", "niche_preset": "dark_psychology",
                           "duration": 30},
                webhook_caller=caller,
            )
        self.assertEqual(ctx.exception.code, "WEBHOOK_ERROR")
        self.assertIn("credit", str(ctx.exception).lower())


class RegistryTests(unittest.TestCase):
    def test_script_lab_is_registered_with_metadata(self):
        from scriptase.modules.lab.registry import get_lab, list_labs
        ids = [l.id for l in list_labs()]
        self.assertIn("script_prompt", ids)
        m = get_lab("script_prompt").meta()
        for key in ("name", "description", "purpose", "how_to", "measures", "variant_fields", "default_variant"):
            self.assertTrue(m.get(key), f"lab meta missing {key}")

    def test_builtin_variant_is_prefilled_from_the_lab_default(self):
        from scriptase.modules.lab.variants import builtin_variant
        b = builtin_variant("script_prompt")
        self.assertTrue(b["builtin"])
        # The real engine defaults are surfaced, not blank.
        self.assertGreater(len(b["angle_pool"]), 0)
        self.assertEqual(b["word_target_ratio"], 1.0)

    def test_variants_are_scoped_by_lab(self):
        from scriptase.modules.lab import variants as V
        tmp = tempfile.mkdtemp()
        with mock.patch.object(V, "VARIANTS_DIR", tmp):
            V.create_variant({"name": "A"}, lab_id="script_prompt")
            V.create_variant({"name": "B"}, lab_id="other_lab")
            script_names = [v["name"] for v in V.list_variants("script_prompt") if not v["builtin"]]
            other_names = [v["name"] for v in V.list_variants("other_lab") if not v["builtin"]]
        self.assertIn("A", script_names)
        self.assertNotIn("B", script_names)
        self.assertIn("B", other_names)


if __name__ == "__main__":
    unittest.main()
