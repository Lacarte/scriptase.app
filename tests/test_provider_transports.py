"""Step 14.4 — shared extension, webhook, direct-API, and callback transports.

Done-when coverage:

  * Storyboard and Animator providers use shared transports without sharing
    business logic.
  * Cross-provider / cross-job callbacks cannot contaminate results.
  * Replay / duplicate / oversized / unknown callbacks are rejected safely.
  * Old extension / Automa URLs remain the frozen public surface.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from scriptase.providers.errors import (
    PROVIDER_AUTH_FAILED,
    PROVIDER_REQUEST_INVALID,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
)
from scriptase.providers.jobs import JobHandle, JobStatus
from scriptase.providers.media_jobs import MediaJobService, MediaJobStore
from scriptase.providers.results import UNIT_SUCCEEDED
from scriptase.providers.transports import (
    APPLIED,
    DROPPED_MISMATCH,
    DROPPED_UNKNOWN,
    IGNORED_DUPLICATE,
    MAX_CALLBACK_BODY_BYTES,
    REJECTED_MALFORMED,
    REJECTED_OVERSIZED,
    CallbackIntake,
    DirectApiClient,
    ExtensionWebSocketHub,
    classify_http_error,
    classify_webhook_error,
    correlation_tuple,
    job_matches_provider,
    measure_body,
    parse_correlation,
    post_webhook,
    webhook_transport,
)
from scriptase.providers.transports.direct_api import submit_and_poll
from scriptase.modules.image import gemini_ws
from scriptase.modules.video import ws_runtime as animator_runtime


PROJECT = "proj_transport_14_4"


def _unit(index: int = 0, state: str = UNIT_SUCCEEDED):
    from scriptase.providers.results import UnitResult

    return UnitResult(unit_index=index, state=state)


def _status(job_id: str, state: str = "succeeded", units=(), ready: int | None = None):
    units = tuple(units)
    return JobStatus(
        job_id=job_id,
        state=state,
        ready=ready if ready is not None else sum(1 for u in units if u.state == UNIT_SUCCEEDED),
        total=len(units) or 1,
        units=units,
    )


# -- extension hub -----------------------------------------------------------


class FakeWs:
    def __init__(self):
        self.sent: list[str] = []
        self.alive = True

    def send(self, data):
        if not self.alive:
            raise RuntimeError("closed")
        self.sent.append(data)

    def receive(self):
        return None


class ExtensionHubTests(unittest.TestCase):
    def test_frozen_routes_are_unchanged(self):
        self.assertEqual(gemini_ws.WS_ROUTE, "/ws/storyboard-gemini-image-grabber")
        self.assertEqual(animator_runtime.WS_ROUTE, "/ws/animator-grok-video-grabber")
        self.assertIsInstance(gemini_ws.hub, ExtensionWebSocketHub)
        self.assertIsInstance(animator_runtime.hub, ExtensionWebSocketHub)

    def test_queue_delivers_and_keeps_pending_for_list_mode(self):
        hub = ExtensionWebSocketHub("test", "/ws/test", pending_mode="list")
        ws = FakeWs()
        hub.clients.append(ws)
        sent = hub.queue({"type": "IMAGE_JOB", "projectId": "p1", "scenes": [1]})
        self.assertTrue(sent)
        self.assertEqual(hub.pending_count(), 1)
        self.assertEqual(json.loads(ws.sent[0])["type"], "IMAGE_JOB")

        late = FakeWs()
        hub.flush_pending(late)
        self.assertEqual(json.loads(late.sent[0])["projectId"], "p1")

        hub.drop_pending("p1")
        self.assertEqual(hub.pending_count(), 0)

    def test_single_pending_mode_keeps_only_the_latest(self):
        hub = ExtensionWebSocketHub("test", "/ws/test", pending_mode="single")
        hub.queue({"type": "GRABBER_START", "projectId": "a", "scenes": []})
        hub.queue({"type": "GRABBER_START", "projectId": "b", "scenes": []})
        self.assertEqual(hub.pending_count(), 1)
        late = FakeWs()
        hub.flush_pending(late)
        self.assertEqual(json.loads(late.sent[0])["projectId"], "b")

    def test_storyboard_and_animator_hubs_do_not_share_client_pools(self):
        # Contaminating one extension must not affect the other.
        gemini_ws.hub.clients.clear()
        animator_runtime.hub.clients.clear()
        gemini_ws.hub.clients.append(FakeWs())
        self.assertTrue(gemini_ws.is_extension_connected())
        self.assertFalse(animator_runtime.is_extension_connected())
        gemini_ws.hub.clients.clear()


# -- webhook transport -------------------------------------------------------


class WebhookTransportTests(unittest.TestCase):
    def test_post_webhook_rejects_empty_and_unsafe_urls(self):
        with self.assertRaises(ProviderError) as empty:
            post_webhook("", {"a": 1})
        self.assertEqual(empty.exception.code, PROVIDER_REQUEST_INVALID)

        with self.assertRaises(ProviderError) as unsafe:
            post_webhook("javascript:alert(1)", {"a": 1}, allow_private=False)
        self.assertEqual(unsafe.exception.code, PROVIDER_REQUEST_INVALID)

    def test_post_webhook_maps_failures_without_leaking_body(self):
        def boom(url, payload, **kwargs):
            raise RuntimeError(f"POST {url}?token=supersecret failed: stacktrace")

        with self.assertRaises(ProviderError) as caught:
            post_webhook(
                "https://n8n.example/hook",
                {"x": 1},
                caller=boom,
            )
        self.assertEqual(caught.exception.code, PROVIDER_TRANSPORT_FAILED)
        self.assertNotIn("supersecret", caught.exception.message)
        self.assertNotIn("stacktrace", caught.exception.message)

    def test_classify_auth_and_timeout(self):
        auth = classify_webhook_error(RuntimeError("401 Unauthorized"))
        self.assertEqual(auth.code, PROVIDER_AUTH_FAILED)
        self.assertFalse(auth.retryable)

        import requests

        timed = classify_webhook_error(requests.Timeout())
        self.assertEqual(timed.code, PROVIDER_TIMEOUT)
        self.assertTrue(timed.retryable)

    def test_webhook_transport_extracts_domain_fields(self):
        def caller(url, payload, **kwargs):
            self.assertEqual(payload["prompt"], "lighthouse")
            return {"image_url": "https://cdn.test/a.png"}

        transport = webhook_transport(
            "https://n8n.example/hook",
            build_payload=lambda prompt: {"prompt": prompt},
            extract=lambda body: body.get("image_url"),
            caller=caller,
            domain="storyboard",
            provider_id="wavespeed_webhook",
        )
        self.assertEqual(transport("lighthouse"), "https://cdn.test/a.png")

    def test_storyboard_generation_uses_shared_post_webhook(self):
        from scriptase.modules.image import generation as gen

        transport = gen.webhook_transport("https://n8n.example/hook")
        with mock.patch.object(
            gen, "call_webhook", return_value={"image_url": "https://cdn.test/a.png"}
        ) as call:
            url = transport({"scene": 0, "prompt": "x"}, "9:16", PROJECT)
        self.assertEqual(url, "https://cdn.test/a.png")
        self.assertEqual(call.call_args[0][0], "https://n8n.example/hook")


# -- direct API transport ----------------------------------------------------


class DirectApiTransportTests(unittest.TestCase):
    def test_post_is_not_retried(self):
        session = mock.Mock()
        response = mock.Mock()
        response.status_code = 500
        response.raise_for_status.side_effect = Exception("server error")
        session.request.return_value = response

        client = DirectApiClient(
            base_url="https://api.example",
            session=session,
            domain="animator",
            provider_id="kie_ai",
        )
        with self.assertRaises(ProviderError):
            client.post_json("/jobs", {"a": 1})
        self.assertEqual(session.request.call_count, 1)

    def test_get_retries_transient_failures(self):
        session = mock.Mock()
        fail = mock.Mock(status_code=503)
        fail.raise_for_status.side_effect = Exception("unavailable")
        ok = mock.Mock(status_code=200)
        ok.raise_for_status.return_value = None
        ok.json.return_value = {"status": "ok"}
        session.request.side_effect = [fail, ok]

        client = DirectApiClient(session=session, domain="animator", provider_id="kie_ai")
        with mock.patch("scriptase.providers.transports.direct_api.time.sleep"):
            data = client.get_json("/status", retries=2)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(session.request.call_count, 2)

    def test_submit_and_poll_posts_once_then_polls(self):
        session = mock.Mock()
        submit = mock.Mock(status_code=200)
        submit.raise_for_status.return_value = None
        submit.json.return_value = {"taskId": "t1"}
        poll_running = mock.Mock(status_code=200)
        poll_running.raise_for_status.return_value = None
        poll_running.json.return_value = {"status": "running"}
        poll_done = mock.Mock(status_code=200)
        poll_done.raise_for_status.return_value = None
        poll_done.json.return_value = {
            "status": "done",
            "resultJson": {"resultUrls": ["https://cdn.test/a.png"]},
        }
        session.request.side_effect = [submit, poll_running, poll_done]

        client = DirectApiClient(
            base_url="https://api.example",
            session=session,
            domain="animator",
            provider_id="kie_ai",
        )
        clock = {"t": 0.0}

        def now():
            return clock["t"]

        def sleep(seconds):
            clock["t"] += seconds

        result = submit_and_poll(
            client,
            submit_path="/jobs/createTask",
            submit_payload={"model": "x"},
            poll_path="/jobs/recordInfo",
            is_done=lambda body: body.get("status") == "done",
            is_failed=lambda body: body.get("status") == "failed",
            extract=lambda body: body["resultJson"]["resultUrls"][0],
            poll_interval_s=1.0,
            poll_timeout_s=10.0,
            clock=now,
            sleeper=sleep,
        )
        self.assertEqual(result, "https://cdn.test/a.png")
        # One POST + two GETs.
        methods = [call.args[0] for call in session.request.call_args_list]
        self.assertEqual(methods, ["POST", "GET", "GET"])

    def test_classify_http_auth(self):
        err = classify_http_error(RuntimeError("403 Forbidden"))
        self.assertEqual(err.code, PROVIDER_AUTH_FAILED)


# -- callback intake ---------------------------------------------------------


class CallbackIntakeTests(unittest.TestCase):
    def setUp(self):
        self.store = MediaJobStore()
        self.service = MediaJobService(store=self.store)
        self.intake = CallbackIntake(service=self.service)

    def _register(self, domain="storyboard", provider="gemini_ws", job_id=PROJECT):
        handle = JobHandle(
            job_id=job_id,
            domain=domain,
            provider_id=provider,
            project_id=PROJECT,
        )
        self.store.register(
            handle,
            JobStatus(job_id=job_id, state="running", ready=0, total=1),
        )
        return handle

    def test_unknown_correlation_is_dropped(self):
        result = self.intake.accept(
            correlation=("storyboard", "gemini_ws", PROJECT, "missing"),
            status=_status("missing", units=[_unit(0)]),
        )
        self.assertEqual(result.outcome, DROPPED_UNKNOWN)
        self.assertFalse(result.applied)

    def test_cross_provider_callback_cannot_contaminate(self):
        handle = self._register(provider="wavespeed_direct")
        # Push claims to be gemini_ws for the same project/job.
        result = self.intake.accept(
            correlation=("storyboard", "gemini_ws", PROJECT, handle.job_id),
            status=_status(handle.job_id, units=[_unit(0)]),
        )
        self.assertEqual(result.outcome, DROPPED_MISMATCH)
        live = self.store.get(handle.correlation)
        self.assertEqual(live.status.ready, 0)

    def test_duplicate_terminal_unit_is_idempotent(self):
        handle = self._register()
        first = self.intake.accept(
            correlation=handle.correlation,
            status=_status(handle.job_id, units=[_unit(0)]),
        )
        self.assertEqual(first.outcome, APPLIED)
        second = self.intake.accept(
            correlation=handle.correlation,
            status=_status(handle.job_id, units=[_unit(0)]),
        )
        self.assertEqual(second.outcome, IGNORED_DUPLICATE)

    def test_oversized_body_is_rejected(self):
        handle = self._register()
        huge = "x" * (MAX_CALLBACK_BODY_BYTES + 1)
        result = self.intake.accept(
            correlation=handle.correlation,
            status=_status(handle.job_id, units=[_unit(0)]),
            body=huge,
        )
        self.assertEqual(result.outcome, REJECTED_OVERSIZED)
        self.assertEqual(self.store.get(handle.correlation).status.ready, 0)

    def test_malformed_correlation_is_rejected(self):
        result = self.intake.accept(payload={"status": "done"})
        self.assertEqual(result.outcome, REJECTED_MALFORMED)

    def test_parse_correlation_accepts_legacy_field_names(self):
        tup = parse_correlation(
            {"projectId": "p1", "jobId": "j1", "provider": "gemini_ws"},
            domain="storyboard",
        )
        self.assertEqual(tup, ("storyboard", "gemini_ws", "p1", "j1"))

    def test_job_matches_provider_aliases_and_empty(self):
        self.assertTrue(job_matches_provider({"provider": ""}, provider_id="grok_automa"))
        self.assertTrue(
            job_matches_provider(
                {"provider": "grok"},
                provider_id="grok_automa",
                aliases={"grok": "grok_automa"},
            )
        )
        self.assertFalse(
            job_matches_provider(
                {"provider": "kie_ai"},
                provider_id="grok_automa",
                aliases={"grok": "grok_automa"},
            )
        )

    def test_legacy_accept_blocks_cross_provider_automa_callback(self):
        disposition = self.intake.accept_legacy_job(
            domain="animator",
            provider_id="grok_automa",
            project_id=PROJECT,
            job={"provider": "kie_ai", "project_id": PROJECT},
            body={"scenes": []},
            aliases={"grok": "grok_automa"},
        )
        self.assertEqual(disposition.outcome, DROPPED_MISMATCH)

    def test_measure_body_handles_bytes_and_mappings(self):
        self.assertEqual(measure_body(b"abc"), 3)
        self.assertGreater(measure_body({"a": 1}), 0)

    def test_correlation_tuple_shape(self):
        self.assertEqual(
            correlation_tuple("storyboard", "gemini_ws", "p", "j"),
            ("storyboard", "gemini_ws", "p", "j"),
        )


# -- preflight alias acceptance ---------------------------------------------


class PreflightAliasTests(unittest.TestCase):
    def test_extension_ops_accept_legacy_and_canonical(self):
        """Step 16.1: resolve returns canonical ids; cloud providers are skipped."""
        from scriptase.providers.extension_ops import resolve_extension

        gemini = resolve_extension("gemini")
        self.assertIsNotNone(gemini)
        self.assertEqual(gemini.provider_id, "gemini_ws")

        gemini_ws = resolve_extension("gemini_ws")
        self.assertIsNotNone(gemini_ws)
        self.assertEqual(gemini_ws.provider_id, "gemini_ws")

        grok = resolve_extension("grok")
        self.assertIsNotNone(grok)
        self.assertEqual(grok.provider_id, "grok_automa")

        midjourney = resolve_extension("midjourney")
        self.assertIsNotNone(midjourney)
        self.assertEqual(midjourney.provider_id, "grok_automa")

        # Cloud / non-extension providers must not be treated as extension targets.
        self.assertIsNone(resolve_extension("wavespeed_direct"))
        self.assertIsNone(resolve_extension("kie_ai"))


if __name__ == "__main__":
    unittest.main()
