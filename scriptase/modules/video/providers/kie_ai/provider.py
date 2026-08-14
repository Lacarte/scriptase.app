"""Kie AI Animator Provider — Provider Contract v2 (step 14.3).

Uses the direct Kie AI API for image generation:

  1. POST /jobs/createTask  -> returns taskId
  2. GET  /jobs/recordInfo?taskId=...  -> poll until resultJson populated
  3. Download image from resultJson.resultUrls[0]

The v1 body wrote into `animator_routes._jobs` (the WebSocket store, not the
grabber store) and was never called from a route. Step 14.3 is the first real
execution path: `submit` seeds `grabber_job.json`, starts the batch worker, and
`poll` reports from the same manifest the status route reads.

Request options win over durable settings for every key (§40.2 O4) — the legacy
`_kie_ai_options.update(provider_settings)` inversion is gone.
"""

from __future__ import annotations

import json
import threading
import time

import requests as http_requests
from loguru import logger

from config import KIE_AI_API_KEY, KIE_AI_BASE_URL, KIE_AI_MODEL
from scriptase.modules.video import generation, jobs
from scriptase.modules.video.providers.base import AnimatorProvider, AnimatorRequest
from scriptase.providers.jobs import JobHandle, JobStatus
from scriptase.providers.transports.direct_api import (
    DirectApiClient,
    DirectApiError,
    classify_http_error,
)

PROVIDER_ID = "kie_ai"
POLL_INTERVAL = 3
POLL_TIMEOUT = 180


def _client(api_key: str) -> DirectApiClient:
    """Shared direct-API client for this provider (step 14.4)."""
    return DirectApiClient(
        base_url=KIE_AI_BASE_URL,
        default_headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
        domain="video",
        provider_id=PROVIDER_ID,
    )


def _create_task(prompt, aspect_ratio, resolution, output_format, model, api_key):
    """POST /jobs/createTask -> returns taskId. Submit is never transport-retried (D40)."""
    if model == "google/nano-banana":
        fmt = "jpeg" if output_format in ("jpg", "jpeg") else output_format
        input_params = {
            "prompt": prompt,
            "image_size": aspect_ratio,
            "output_format": fmt,
        }
    else:
        res_map = {"1": "1K", "2": "2K"}
        input_params = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": res_map.get(resolution, resolution),
            "output_format": output_format,
        }

    payload = {"model": model, "input": input_params}
    client = _client(api_key)
    try:
        data = client.post_json("/jobs/createTask", payload, timeout=30)
    finally:
        client.close()

    task_id = data.get("taskId") or (data.get("data") or {}).get("taskId")
    if not task_id:
        raise DirectApiError(
            "PROVIDER_RESPONSE_MALFORMED",
            "The API returned an unusable response",
            domain="video",
            provider_id=PROVIDER_ID,
        )
    return task_id


def _poll_result(task_id, api_key):
    """GET /jobs/recordInfo?taskId=... -> poll until result ready."""
    client = _client(api_key)
    try:
        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            data = client.get_json(
                "/jobs/recordInfo",
                params={"taskId": task_id},
                timeout=30,
                retries=2,
            )
            record = data if "status" in data else data.get("data", {})
            if not isinstance(record, dict):
                record = {}
            status = record.get("status", "")

            if status in ("failed", "error"):
                raise DirectApiError(
                    "PROVIDER_TRANSPORT_FAILED",
                    "The remote job failed",
                    domain="video",
                    provider_id=PROVIDER_ID,
                )

            result_json = record.get("resultJson")
            if result_json:
                if isinstance(result_json, str):
                    result_json = json.loads(result_json)
                result_urls = result_json.get("resultUrls", [])
                if result_urls:
                    logger.success(
                        "Kie AI task {} complete: {} image(s)", task_id, len(result_urls)
                    )
                    return {
                        "url": result_urls[0],
                        "task_id": task_id,
                        "all_urls": result_urls,
                    }

            time.sleep(POLL_INTERVAL)
    finally:
        client.close()

    raise DirectApiError(
        "PROVIDER_TIMEOUT",
        "The remote job timed out",
        retryable=True,
        domain="video",
        provider_id=PROVIDER_ID,
    )


def generate_image(
    prompt,
    aspect_ratio="9:16",
    resolution="1",
    output_format="jpg",
    model=None,
    api_key=None,
):
    """Generate an image via Kie AI API. Returns {"url": ..., "task_id": ...}."""
    key = api_key or KIE_AI_API_KEY
    if not key:
        raise ValueError("KIE_AI_API_KEY not configured")
    try:
        task_id = _create_task(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            output_format=output_format,
            model=model or KIE_AI_MODEL,
            api_key=key,
        )
        logger.info("Kie AI task created: {}", task_id)
        return _poll_result(task_id, api_key=key)
    except DirectApiError:
        raise
    except Exception as exc:
        raise classify_http_error(
            exc, domain="video", provider_id=PROVIDER_ID
        ) from exc


class KieAIProvider(AnimatorProvider):
    """Animator provider using the direct Kie AI API."""

    def submit(self, request: AnimatorRequest, invocation) -> JobHandle:
        # Request options win over durable settings (§40.2 O4).
        options = {**dict(invocation.settings), **dict(invocation.options)}
        api_key = (
            str(options.get("api_key") or "").strip()
            or str(invocation.settings.get("api_key") or "").strip()
            or KIE_AI_API_KEY
        )
        if not api_key:
            raise ValueError("KIE_AI_API_KEY not configured")

        # Credentials never reach the job file (§22.6). Only portable options.
        portable = {
            key: value
            for key, value in options.items()
            if key not in {"api_key"}
        }
        portable.setdefault("aspect_ratio", request.aspect_ratio)
        portable.setdefault("model", KIE_AI_MODEL)
        portable.setdefault("resolution", "1")
        portable.setdefault("output_format", "jpg")

        jobs.seed(
            invocation.project_id,
            request,
            provider_id=PROVIDER_ID,
            payload={
                "projectId": invocation.project_id,
                "aspect_ratio": request.aspect_ratio,
                "scenes": request.legacy_scenes(),
            },
            status="generating",
        )

        def transport(**kwargs):
            return generate_image(api_key=api_key, **kwargs)

        project_id = invocation.project_id
        threading.Thread(
            target=generation.run_batch,
            args=(project_id, request, transport),
            kwargs={
                "options": portable,
                "is_cancelled": invocation.cancel.is_cancelled,
            },
            name=f"animator-kie-{project_id}",
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


def create() -> KieAIProvider:
    return KieAIProvider()


def validate_settings(settings: dict) -> list[dict]:
    issues = []
    api_key = str((settings or {}).get("api_key") or "").strip() or KIE_AI_API_KEY
    if not api_key:
        issues.append({
            "field": "api_key",
            "severity": "warning",
            "message": "No API key — will use environment variable",
        })
    return issues


def health_check(settings: dict) -> dict:
    api_key = str((settings or {}).get("api_key") or "").strip() or KIE_AI_API_KEY
    if not api_key:
        return {"status": "warn", "message": "No API key configured"}

    url = f"{KIE_AI_BASE_URL}/jobs/recordInfo?taskId=test"
    try:
        start = time.perf_counter()
        resp = http_requests.get(url, timeout=5)
        elapsed = int((time.perf_counter() - start) * 1000)
        if resp.status_code in (200, 404):
            return {
                "status": "ok",
                "latency_ms": elapsed,
                "message": "Kie AI API reachable",
            }
        return {"status": "warn", "message": f"Unexpected status {resp.status_code}"}
    except Exception as exc:
        return {"status": "fail", "message": str(exc)}
