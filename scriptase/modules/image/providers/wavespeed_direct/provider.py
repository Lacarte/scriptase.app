"""Direct WaveSpeed storyboard provider — Provider Contract v2 (step 14.2).

The v1 body called `sb_routes._generate_storyboard(...)` without a `style`, so
the transport heuristic inside that function (`image_model or (style and not
is_default_model(style))`) evaluated false whenever no model override was set
and the "direct" provider ran the n8n webhook. Selecting this provider now
selects the direct API unconditionally — the transport is the provider's, not a
guess made from the request.
"""

from __future__ import annotations

import threading

from config import WAVESPEED_API_KEY
from scriptase.providers.jobs import JobHandle, JobStatus
from scriptase.modules.image import generation, jobs
from scriptase.modules.image.providers.base import StoryboardProvider, StoryboardRequest

PROVIDER_ID = "wavespeed_direct"


class WaveSpeedDirectProvider(StoryboardProvider):
    """Storyboard frames from the WaveSpeed API, called directly."""

    def submit(self, request: StoryboardRequest, invocation) -> JobHandle:
        options = {**dict(invocation.settings), **dict(invocation.options)}
        transport = generation.direct_transport(
            style=request.style,
            image_model=str(options.get("image_model") or ""),
        )

        jobs.seed(invocation.project_id, request, provider_id=PROVIDER_ID)
        project_id = invocation.project_id
        threading.Thread(
            target=generation.run_batch,
            args=(project_id, request, transport),
            kwargs={"is_cancelled": invocation.cancel.is_cancelled},
            name=f"storyboard-direct-{project_id}",
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


def create() -> WaveSpeedDirectProvider:
    return WaveSpeedDirectProvider()


def validate_settings(settings: dict) -> list[dict]:
    api_key = str((settings or {}).get("api_key") or "").strip() or WAVESPEED_API_KEY
    if not api_key:
        return [{
            "field": "api_key",
            "severity": "warning",
            "message": "No API key configured — will use environment variable",
        }]
    return []


def list_models(_settings: dict) -> list[dict]:
    """The models this provider can be pointed at (§22.4).

    Read by the `image_models` option source, which used to import
    this catalog directly and would therefore have offered these models for any
    provider selected.
    """
    from scriptase.modules.image.wavespeed import get_models_for_style

    return list(get_models_for_style("default"))


def health_check(settings: dict) -> dict:
    """Credential presence only. The live key check belongs to a test call.

    An invalid key is reported by the invocation as `PROVIDER_AUTH_FAILED` on
    the units it rejects, not here: this hook runs on catalog reads and must not
    spend a request per provider.
    """
    api_key = str((settings or {}).get("api_key") or "").strip() or WAVESPEED_API_KEY
    if not api_key:
        return {"status": "warn", "message": "No API key (will use env var)"}
    return {"status": "ok", "latency_ms": 0, "message": "WaveSpeed API key configured"}
