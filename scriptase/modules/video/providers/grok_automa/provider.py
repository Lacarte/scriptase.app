"""Grok Automa Animator Provider — Provider Contract v2 (step 14.3).

Owns everything the REST layer and the workflow adapter used to branch on for
this provider:

  * seeding `grabber_job.json` and dispatching `GRABBER_START` over the WebSocket;
  * mode / quality / duration / auto_type, which are this provider's own
    settings (§26 / §41.3 M3) rather than node fields;
  * attaching storyboard reference images as base64 for the extension.

`poll` reads the manifest the upload/results handlers write. The v1 body read
`ws_runtime._jobs` (a different store) with the wrong status vocabulary.
"""

from __future__ import annotations

import base64
import os

from loguru import logger

from config import STORYBOARD_DIR
from scriptase.modules.video import jobs
from scriptase.modules.video.providers.base import AnimatorProvider, AnimatorRequest
from scriptase.providers.jobs import JobHandle, JobStatus

PROVIDER_ID = "grok_automa"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class GrokAutomaProvider(AnimatorProvider):
    """Animator takes driven by the Grok Chrome extension via WebSocket."""

    def _runtime(self):
        from scriptase.modules.video import ws_runtime as animator_runtime

        return animator_runtime

    def submit(self, request: AnimatorRequest, invocation) -> JobHandle:
        options = {**dict(invocation.settings), **dict(invocation.options)}
        mode = str(options.get("mode") or request.mode or "video")
        quality = str(options.get("quality") or "480p")
        duration = str(options.get("duration") or "6s")
        auto_type = bool(options.get("auto_type", False))

        scene_list = self._scenes_with_references(
            invocation.project_id, request.legacy_scenes()
        )
        payload = {
            "projectId": invocation.project_id,
            "arguments": "",
            "aspect_ratio": request.aspect_ratio,
            "scenes": scene_list,
            "grok_mode": mode,
            "grok_quality": quality,
            "grok_duration": duration,
            "auto_type": auto_type,
        }

        jobs.seed(
            invocation.project_id,
            request,
            provider_id=PROVIDER_ID,
            payload=payload,
            status="waiting",
        )

        runtime = self._runtime()
        connected = False
        try:
            connected = bool(runtime.is_extension_connected())
        except Exception:
            connected = False

        runtime.queue_grabber_start({
            "type": "GRABBER_START",
            "projectId": invocation.project_id,
            "scenes": scene_list,
            "aspectRatio": request.aspect_ratio,
            "grokMode": mode,
            "grokDuration": duration,
            "autoType": auto_type,
        })
        # A disconnected extension is not a submit failure: the job stays queued
        # and is flushed on the next handshake (§21.5).
        invocation.log.info(
            "queued animator job for the extension",
            scenes=len(scene_list), extension_connected=connected,
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

    def open_url(self, settings: dict | None = None) -> str | None:
        return "https://grok.com/imagine"

    def shutdown(self) -> None:
        pass

    def _scenes_with_references(self, project_id: str, scenes: list[dict]) -> list[dict]:
        """Attach storyboard stills as base64 for the extension UI."""
        result = []
        for scene in scenes:
            entry = {"prompt": scene["prompt"], "scene": scene["scene"]}
            image = self._storyboard_image(project_id, scene["scene"])
            if image:
                entry["image"] = image
            result.append(entry)
        return result

    def _storyboard_image(self, project_id: str, index) -> str | None:
        directory = os.path.join(STORYBOARD_DIR, project_id, str(index))
        if not os.path.isdir(directory):
            return None
        for name in os.listdir(directory):
            if not (name.startswith("image") and name.lower().endswith(IMAGE_EXTS)):
                continue
            path = os.path.join(directory, name)
            try:
                with open(path, "rb") as handle:
                    raw = handle.read()
            except OSError:
                return None
            ext = os.path.splitext(name)[1].lstrip(".").lower()
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(
                ext, "jpeg"
            )
            return f"data:image/{mime};base64,{base64.b64encode(raw).decode()}"
        return None


def create() -> GrokAutomaProvider:
    return GrokAutomaProvider()


def register_runtime(app, sock=None):
    """Register the extension's WebSocket route (`manifest.kind == "extension"`)."""
    from scriptase.modules.video import ws_runtime as animator_runtime

    animator_runtime.init_animator_ws(sock)


def validate_settings(settings: dict) -> list[dict]:
    return []


def health_check(settings: dict) -> dict:
    """Extension connectivity, isolated from generation errors (§21.5)."""
    from scriptase.modules.video import ws_runtime as animator_runtime

    clients = len(animator_runtime._ws_clients)
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
