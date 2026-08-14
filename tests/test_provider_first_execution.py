"""Step 11.4: first-ever execution of the shipped provider methods.

contracts.md §16 records that `TTSProvider.synthesize`, `Storyboard`/
`AnimatorProvider.submit`/`poll`, and every `get_provider()` factory have **zero
call sites** — execution branches on `if provider_id == …` into legacy modules
instead. Step 11.4 therefore treats every existing `provider.py` body as
unverified code under first-time test.

Each test here calls a method that has never run in this repository, with its
network, model, and filesystem collaborators stubbed. The point is not to prove
the provider is correct against a live service — that is what §46's recorded
fixtures and the `STS_LIVE` tests are for — but to prove the code executes at
all, produces the shapes the v2 contract expects, and does not leak.

Modules are reached through `ProviderInstance.provider_module` rather than by
import, because five of the seven provider folders have no `__init__.py` and are
loadable only through discovery. That also guarantees the object under test is
the one the registry actually serves.
"""

import unittest
from unittest import mock

from studio.animator.providers.base import AnimatorProvider
from studio.shared.providers_common.hub import hub
from studio.shared.providers_common.jobs import (
    FAILED,
    RUNNING,
    SUBMITTED,
    SUCCEEDED,
    JobHandle,
    JobStatus,
)
from studio.shared.providers_common.invocation import build_invocation
from studio.shared.providers_common.results import validate_egress
from studio.storyboard.providers.base import StoryboardProvider
from studio.storyboard.providers.contract import StoryboardRequest
from studio.tts.providers.base import TTSProvider, TTSResult

PROJECT_ID = "pm_ABC123"


def provider_module(domain, provider_id):
    instance = hub.get(domain, provider_id)
    assert instance is not None, f"{domain}/{provider_id} is not registered"
    return instance.provider_module


def storyboard_request(*, scenes=None, aspect_ratio="9:16", style=""):
    return StoryboardRequest.from_scenes(
        scenes or [{"index": 0, "prompt": "a lighthouse"}],
        aspect_ratio=aspect_ratio,
        style=style,
    )


def storyboard_invocation(provider_id, *, settings=None, options=None, output_dir=""):
    return build_invocation(
        None,
        domain="storyboard",
        provider_id=provider_id,
        project_id=PROJECT_ID,
        output_dir=output_dir,
        settings=settings or {},
        options=options or {},
    )


class ShippedProviderCase(unittest.TestCase):
    domain = ""
    provider_id = ""

    def setUp(self):
        self.module = provider_module(self.domain, self.provider_id)
        self.instance = hub.create(self.domain, self.provider_id)
        self.assertIsNotNone(self.instance)


# -- tts ---------------------------------------------------------------------
#
# The two TTS providers were first executed here against the v1 ABC. Step 15.1
# brought them onto Provider Contract v2 — a typed `TTSRequest`/`TTSResultPayload`
# invocation, catalog errors, and manifest-declared exclusive execution — so
# their contract tests moved to `tests/test_tts_providers.py`, beside the
# voice/audio and redaction tests that exercise them end to end.


# -- storyboard --------------------------------------------------------------
#
# The three storyboard providers were first executed here against the v1
# `submit(project_id, scenes, settings, on_progress)` signature. Step 14.2
# replaced that with the Contract v2 async shape and moved the manifest,
# transport, and metadata decisions into the providers, so their contract tests
# moved to `tests/test_storyboard_dispatch.py`, beside the dispatch tests that
# exercise them end to end.


# -- animator ----------------------------------------------------------------
#
# The two animator providers were first executed here against the v1
# `submit(project_id, scenes, settings, on_progress)` signature. Step 14.3
# replaced that with the Contract v2 async shape and moved the manifest,
# transport, and metadata decisions into the providers, so their contract tests
# moved to `tests/test_animator_dispatch.py`, beside the dispatch tests that
# exercise them end to end.


# -- the abstract base classes ----------------------------------------------


class AbstractBaseTests(unittest.TestCase):
    """The optional hooks nothing has ever called."""

    def test_tts_optional_hooks(self):
        class Minimal(TTSProvider):
            def synthesize(self, text, settings, voice=None, speed=1.0, on_progress=None):
                return TTSResult(audio_path="", duration_seconds=0.0)

            def list_voices(self, settings):
                return []

        provider = Minimal()
        self.assertEqual(provider.list_models({}), [])
        with self.assertRaises(NotImplementedError):
            provider.download_model("kokoro", {})
        with self.assertRaises(NotImplementedError):
            next(iter(provider.stream("hi", {})))
        provider.shutdown()

    def test_storyboard_generate_one_default(self):
        class Minimal(StoryboardProvider):
            def submit(self, request, invocation):
                return JobHandle(job_id=invocation.project_id)

            def poll(self, job_id, invocation):
                return JobStatus(job_id=job_id)

        provider = Minimal()
        with self.assertRaises(NotImplementedError):
            provider.generate_one(storyboard_request(), storyboard_invocation("gemini_ws"))
        # `cancel_job` is optional and defaults to a no-op (§33).
        self.assertIsNone(
            provider.cancel_job("pm_ABC123", storyboard_invocation("gemini_ws"))
        )
        provider.shutdown()

    def test_animator_open_url_default(self):
        from studio.animator.providers.contract import AnimatorRequest
        from studio.shared.providers_common.invocation import build_invocation

        class Minimal(AnimatorProvider):
            def submit(self, request, invocation):
                return JobHandle(job_id=invocation.project_id)

            def poll(self, job_id, invocation):
                return JobStatus(job_id=job_id)

        provider = Minimal()
        self.assertIsNone(provider.open_url({}))
        inv = build_invocation(
            None, domain="animator", provider_id="x", project_id="pm_ABC123",
        )
        self.assertIsNone(provider.cancel_job("pm_ABC123", inv))
        provider.shutdown()

    def test_every_shipped_provider_constructs_and_reports_a_job_shape(self):
        """One assertion that spans all seven providers (§21.1 + §33.1)."""
        shipped = [
            ("tts", "kokoro"), ("tts", "inworld"),
            ("storyboard", "gemini_ws"), ("storyboard", "wavespeed_direct"),
            ("storyboard", "wavespeed_webhook"),
            ("animator", "grok_automa"), ("animator", "kie_ai"),
        ]
        for domain, provider_id in shipped:
            with self.subTest(provider=f"{domain}/{provider_id}"):
                instance = hub.create(domain, provider_id)
                self.assertIsNotNone(instance)
                self.assertTrue(callable(getattr(instance, "shutdown")))


if __name__ == "__main__":
    unittest.main()
