"""The `llm_judge` viral provider: request shape, reply mapping, error mapping."""

from __future__ import annotations

import unittest

from scriptase.modules.viral.models import DIMENSION_IDS
from scriptase.modules.viral.providers.contract import ViralRequest
from scriptase.modules.viral.providers.llm_judge.provider import (
    LlmJudgeViralProvider,
    _build_score,
)
from scriptase.providers.errors import (
    PROVIDER_AUTH_FAILED,
    PROVIDER_QUOTA_EXHAUSTED,
    PROVIDER_REQUEST_INVALID,
    PROVIDER_RESPONSE_MALFORMED,
    ProviderError,
)
from scriptase.shared.webhooks import WebhookResponseError

_SCRIPT = (
    "Hook: A mind can betray itself.\n"
    "Build: It starts with one small lie.\n"
    "Climax: The truth finally surfaces.\n"
    "CTA: Watch what you tell yourself."
)

_GOOD_REPLY = {
    "dimensions": {
        "hook": {"score": 0.9, "reason": "strong"},
        "opening_line": {"score": 0.8, "reason": "arresting"},
        "pacing": {"score": 0.7, "reason": "tight"},
        "open_loops": {"score": 0.85, "reason": "curiosity"},
        "cta": {"score": 0.6, "reason": "ok"},
        "balance": {"score": 0.75, "reason": "even"},
    },
    "summary": "Strong hook, solid loops.",
    "model": "google/gemini-2.5-flash-lite",
}


class BuildScoreTests(unittest.TestCase):
    def test_maps_reply_into_the_frozen_shape(self):
        score = _build_score(_GOOD_REPLY)
        self.assertEqual(score.scorer, "llm_judge")
        self.assertEqual([d.id for d in score.dimensions], list(DIMENSION_IDS))
        self.assertGreater(score.score, 0)
        self.assertIn(score.band, ("poor", "weak", "solid", "strong"))
        self.assertEqual(score.metrics["summary"], "Strong hook, solid loops.")

    def test_missing_dimension_scores_zero_not_raises(self):
        reply = {"dimensions": {"hook": {"score": 1.0}}}  # only one dimension
        score = _build_score(reply)
        # Every frozen dimension is still present; the absent ones score 0.
        self.assertEqual(len(score.dimensions), len(DIMENSION_IDS))
        hook = score.dimension("hook")
        cta = score.dimension("cta")
        self.assertEqual(hook.score, 1.0)
        self.assertEqual(cta.score, 0.0)

    def test_out_of_range_scores_are_clamped(self):
        reply = {"dimensions": {name: {"score": 5} for name in DIMENSION_IDS}}
        score = _build_score(reply)
        self.assertTrue(all(d.score <= 1.0 for d in score.dimensions))
        self.assertLessEqual(score.score, 100)


class ScoreTests(unittest.TestCase):
    def _provider_with_caller(self, caller):
        return LlmJudgeViralProvider(), {"_webhook_caller": caller, "webhook_url": "http://localhost:5678/webhook/virality-llm"}

    def test_score_calls_webhook_and_returns_viral_score(self):
        provider, settings = self._provider_with_caller(lambda *a, **k: _GOOD_REPLY)
        req = ViralRequest(job_id="job_TEST", story_text=_SCRIPT, target_duration=30)
        score = provider.score(req, settings=settings)
        self.assertEqual(score.scorer, "llm_judge")
        self.assertEqual(score.dimension("hook").score, 0.9)

    def test_payload_asks_for_exactly_the_frozen_dimensions(self):
        captured = {}

        def caller(url, payload, **k):
            captured.update(payload)
            return _GOOD_REPLY

        provider, settings = self._provider_with_caller(caller)
        provider.score(ViralRequest(job_id="j", story_text=_SCRIPT), settings=settings)
        self.assertEqual(captured["dimensions"], list(DIMENSION_IDS))

    def test_empty_script_is_request_invalid(self):
        provider = LlmJudgeViralProvider()
        with self.assertRaises(ProviderError) as ctx:
            provider.score(ViralRequest(job_id="j", story_text=""), settings={})
        self.assertEqual(ctx.exception.code, PROVIDER_REQUEST_INVALID)

    def test_no_dimensions_in_reply_is_response_malformed(self):
        provider, settings = self._provider_with_caller(lambda *a, **k: {"summary": "oops"})
        with self.assertRaises(ProviderError) as ctx:
            provider.score(ViralRequest(job_id="j", story_text=_SCRIPT), settings=settings)
        self.assertEqual(ctx.exception.code, PROVIDER_RESPONSE_MALFORMED)

    def test_webhook_payment_maps_to_quota_exhausted(self):
        def caller(*a, **k):
            raise WebhookResponseError("Payment required - check your details SECRET", status=500)

        provider, settings = self._provider_with_caller(caller)
        with self.assertRaises(ProviderError) as ctx:
            provider.score(ViralRequest(job_id="j", story_text=_SCRIPT), settings=settings)
        self.assertEqual(ctx.exception.code, PROVIDER_QUOTA_EXHAUSTED)
        self.assertNotIn("SECRET", ctx.exception.message)

    def test_webhook_401_maps_to_auth_failed(self):
        def caller(*a, **k):
            raise WebhookResponseError("unauthorized", status=401)

        provider, settings = self._provider_with_caller(caller)
        with self.assertRaises(ProviderError) as ctx:
            provider.score(ViralRequest(job_id="j", story_text=_SCRIPT), settings=settings)
        self.assertEqual(ctx.exception.code, PROVIDER_AUTH_FAILED)


class RegistrationTests(unittest.TestCase):
    def test_registered_in_the_viral_catalog(self):
        from scriptase.providers.hub import ProviderHub

        reg = ProviderHub().discover("viral")
        self.assertIn("llm_judge", reg.list_ids())
        inst = reg.get("llm_judge")
        self.assertEqual(inst.manifest.kind, "webhook")


if __name__ == "__main__":
    unittest.main()
