"""Gemini extension storyboard provider — Provider Contract v2 (step 14.2).

Owns everything the routes and the workflow adapter used to branch on:

  * seeding the manifest and dispatching `IMAGE_JOB` over the WebSocket;
  * the aspect ratio — `gemini_ws.add_job` hardcoded `16:9`, so a workflow node
    configured `9:16` silently produced landscape frames. The request's value is
    used now, and the extension protocol keeps its `aspectRatio` spelling;
  * `auto_type` and `prompt_prefix`, which are this provider's own settings
    (§26 / §41.3 M2) rather than node fields.

`poll` reads the manifest the WebSocket handler writes. The v1 body answered a
constant `submitted`, which made the shared watchdog useless: a lost
`JOB_COMPLETE` message could only end at the 30-minute deadline.
"""

from __future__ import annotations

from scriptase.providers.jobs import JobHandle, JobStatus
from scriptase.modules.image import jobs
from scriptase.modules.image.providers.base import StoryboardProvider, StoryboardRequest

PROVIDER_ID = "gemini_ws"


class GeminiWSProvider(StoryboardProvider):
    """Storyboard frames driven by the Gemini browser extension."""

    def _runtime(self):
        from scriptase.modules.image import gemini_ws

        return gemini_ws

    def submit(self, request: StoryboardRequest, invocation) -> JobHandle:
        runtime = self._runtime()
        options = {**dict(invocation.settings), **dict(invocation.options)}
        prefix = str(options.get("prompt_prefix") or "")
        scenes = [
            {"scene": scene["scene"], "prompt": prefix + scene["prompt"]}
            for scene in request.legacy_scenes()
        ]

        jobs.seed(invocation.project_id, request, provider_id=PROVIDER_ID)
        jobs.save_scene_prompts(invocation.project_id, scenes)

        connected = runtime.is_extension_connected()
        runtime.queue_image_job({
            "type": "IMAGE_JOB",
            "projectId": invocation.project_id,
            "aspectRatio": request.aspect_ratio,
            "autoType": bool(options.get("auto_type", True)),
            "scenes": scenes,
        })
        # A disconnected extension is not a submit failure: the job stays queued
        # and is flushed on the next handshake, which is what the Storyboard
        # page and the pipeline have always relied on. It surfaces as a health
        # state instead (§21.5).
        invocation.log.info(
            "queued storyboard job for the extension",
            scenes=len(scenes), extension_connected=connected,
        )
        if not connected:
            invocation.progress(
                total=request.unit_count,
                message="waiting for the browser extension",
            )

        return JobHandle(
            job_id=invocation.project_id,
            domain=invocation.domain,
            provider_id=PROVIDER_ID,
            project_id=invocation.project_id,
            invocation_id=invocation.invocation_id,
        )

    def poll(self, job_id: str, invocation) -> JobStatus:
        return jobs.status(invocation.project_id or job_id, job_id)

    def shutdown(self) -> None:
        pass


def create() -> GeminiWSProvider:
    return GeminiWSProvider()


def register_runtime(app, sock=None):
    """Register the extension's WebSocket route (`manifest.kind == "extension"`)."""
    from scriptase.modules.image import gemini_ws

    gemini_ws.register_runtime(app, sock)


def validate_settings(settings: dict) -> list[dict]:
    return []


def health_check(settings: dict) -> dict:
    """Extension connectivity, isolated from generation errors (§21.5).

    An unavailable extension is `warn`, never `fail`: nothing is misconfigured,
    the operator simply has not opened the browser yet.
    """
    from scriptase.modules.image import gemini_ws

    clients = len(gemini_ws._ws_clients)
    return {
        "status": "ok" if clients else "warn",
        "latency_ms": 0,
        "message": (
            "Browser extension connected"
            if clients
            else "No browser extension is connected"
        ),
        "details": {"clients": clients},
    }
