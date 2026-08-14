"""WaveSpeed-via-n8n storyboard provider — Provider Contract v2 (step 14.2).

The v1 body called `sb_routes.generate(StoryboardGenerateRequest(...))` — the
Flask view function, decorated with `@validate_json`, which reads the request
off the Flask context. It could not have run outside a request, and it never
did. `submit` now starts the shared generation loop directly on a worker
thread and returns immediately; the media-job service owns the wait.
"""

from __future__ import annotations

import threading
import time

from config import N8N_STORYBOARD_WEBHOOK_URL, WAVESPEED_API_KEY
from scriptase.providers.jobs import JobHandle, JobStatus
from scriptase.modules.image import generation, jobs
from scriptase.modules.image.providers.base import StoryboardProvider, StoryboardRequest

PROVIDER_ID = "wavespeed_webhook"


class WaveSpeedWebhookProvider(StoryboardProvider):
    """Storyboard frames from WaveSpeed through a user-supplied n8n webhook."""

    def submit(self, request: StoryboardRequest, invocation) -> JobHandle:
        options = {**dict(invocation.settings), **dict(invocation.options)}
        transport = generation.webhook_transport(
            options.get("webhook_url") or N8N_STORYBOARD_WEBHOOK_URL,
            api_key=options.get("api_key") or WAVESPEED_API_KEY,
        )

        jobs.seed(invocation.project_id, request, provider_id=PROVIDER_ID)
        project_id = invocation.project_id
        threading.Thread(
            target=generation.run_batch,
            args=(project_id, request, transport),
            kwargs={"is_cancelled": invocation.cancel.is_cancelled},
            name=f"storyboard-webhook-{project_id}",
            daemon=True,
        ).start()

        return JobHandle(
            job_id=project_id,
            domain=invocation.domain,
            provider_id=PROVIDER_ID,
            project_id=project_id,
            invocation_id=invocation.invocation_id,
        )

    def poll(self, job_id: str, invocation) -> JobStatus:
        return jobs.status(invocation.project_id or job_id, job_id)

    def shutdown(self) -> None:
        pass


def create() -> WaveSpeedWebhookProvider:
    return WaveSpeedWebhookProvider()


def validate_settings(settings: dict) -> list[dict]:
    if not str((settings or {}).get("webhook_url") or "").strip():
        return [{
            "field": "webhook_url",
            "severity": "error",
            "message": "Webhook URL is required",
        }]
    return []


def list_models(_settings: dict) -> list[dict]:
    """The models the webhook can be pointed at (§22.4)."""
    from scriptase.modules.image.wavespeed import get_models_for_style

    return list(get_models_for_style("default"))


def health_check(settings: dict) -> dict:
    import requests

    webhook_url = (settings or {}).get("webhook_url") or N8N_STORYBOARD_WEBHOOK_URL
    if not webhook_url:
        return {"status": "fail", "message": "No webhook URL is configured"}

    try:
        start = time.perf_counter()
        response = requests.get(webhook_url, timeout=5)
        elapsed = int((time.perf_counter() - start) * 1000)
    except Exception as exc:
        # The registry sanitizes this before serving it; a connection error can
        # embed the URL, a local path, or a token (§36 L4).
        return {"status": "fail", "message": str(exc)}

    if response.status_code in (200, 405):
        return {"status": "ok", "latency_ms": elapsed, "message": "Webhook reachable"}
    if response.status_code in (401, 403):
        return {"status": "fail", "message": "The webhook rejected the credentials"}
    return {"status": "warn", "message": f"Webhook returned {response.status_code}"}
