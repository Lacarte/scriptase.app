"""WaveSpeed storyboard generation mechanics — step 14.2.

The per-scene loop the two WaveSpeed providers share. It used to live in
`storyboard/routes.py` as `_generate_storyboard`, where it also *chose* the
transport: `use_direct = image_model or (style and not is_default_model(style))`.
That heuristic is why selecting `wavespeed_direct` with no model override
silently ran the n8n webhook instead — the provider selection never reached the
loop at all. The transport is now an explicit argument supplied by the provider
that owns it, and the heuristic survives only for legacy callers that pass
neither.

Failures are recorded through the sanitized message the provider maps them to,
never `str(exc)`: `storyboard.json` is handed to the `images` port verbatim, so
a raw exception here becomes browser-visible provider response text (§36 L2).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from loguru import logger

from config import N8N_STORYBOARD_WEBHOOK_URL, WAVESPEED_API_KEY
from scriptase.providers.errors import ProviderError
from scriptase.providers.file_download import download_file
from scriptase.providers.transports.webhook import (
    classify_webhook_error,
    post_webhook,
)
from scriptase.providers.validation import sanitize_message
from scriptase.modules.image import jobs
from scriptase.shared.webhooks import call_webhook

MAX_DL_RETRIES = 3
DL_RETRY_DELAY = 2  # seconds
WEBHOOK_TIMEOUT_S = 300

_DL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


def download_image(url: str, destination: str) -> bool:
    """Download an image URL to a local file with retries."""
    parsed = urlparse(url)
    headers = {**_DL_HEADERS, "Referer": f"{parsed.scheme}://{parsed.netloc}/"}
    return download_file(
        url,
        destination,
        headers=headers,
        timeout=120,
        max_retries=MAX_DL_RETRIES,
    )


def classify(exc: BaseException) -> ProviderError:
    """Map a transport failure onto the shared error catalog.

    The original text never reaches the message: `wrap_exception`'s rule (§34.4)
    applies here too, because this message is persisted into `storyboard.json`.
    """
    if isinstance(exc, ProviderError):
        # Drop domain/provider identity so the persisted unit error stays small.
        return ProviderError(exc.code, exc.message, retryable=exc.retryable)
    return classify_webhook_error(exc)


def webhook_transport(
    webhook_url: str | None = None, *, api_key: str | None = None
) -> Callable[[Mapping[str, Any], str, str], str]:
    """The n8n webhook transport: one POST per scene, returns the image URL.

    Built on the shared ``post_webhook`` adapter (step 14.4). Domain-only pieces
    are the payload shape and the `image_url` extraction.
    """
    url = webhook_url or N8N_STORYBOARD_WEBHOOK_URL
    key = api_key or WAVESPEED_API_KEY

    def generate(scene: Mapping[str, Any], aspect_ratio: str, project_id: str) -> str:
        # Prefer the module-level name so tests can still patch `call_webhook`.
        result = post_webhook(
            url,
            {
                "image_prompt": scene["prompt"],
                "aspect_ratio": aspect_ratio,
                "wavespeed_api_key": key,
                "project_id": project_id,
                "scene": scene["scene"],
            },
            timeout=WEBHOOK_TIMEOUT_S,
            label=f"Storyboard scene {scene['scene']}",
            domain="storyboard",
            provider_id="wavespeed_webhook",
            caller=call_webhook,
        )
        image_url = (result or {}).get("image_url")
        if not image_url:
            raise ValueError("webhook returned no image_url")
        return image_url

    return generate


def direct_transport(
    *, style: str = "", image_model: str = ""
) -> Callable[[Mapping[str, Any], str, str], str]:
    """The direct WaveSpeed API transport, model chosen by style or override.

    Model selection and WaveSpeed payload construction stay in
    ``scriptase.modules.image.wavespeed``; this only supplies the callable shape the
    batch loop expects.
    """

    def generate(scene: Mapping[str, Any], aspect_ratio: str, _project_id: str) -> str:
        # Resolved per call, not per transport: the model catalog is read from
        # disk, and binding here would freeze it for the life of the process.
        from scriptase.modules.image.wavespeed import generate_image

        return generate_image(
            prompt=scene["prompt"],
            style=style or "default",
            aspect_ratio=aspect_ratio,
            model_override=image_model or None,
        )

    return generate


def run_batch(
    project_id: str,
    request,
    transport: Callable[[Mapping[str, Any], str, str], str],
    *,
    remove_watermark: bool = False,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Generate every requested scene, recording each unit as it settles.

    Runs to completion in the caller's thread; the media-job service polls the
    manifest this writes. A per-scene failure is isolated: the loop records it
    and continues, so one rejected prompt cannot lose the rest of the batch.
    """
    aspect_ratio = request.aspect_ratio
    for scene in request.legacy_scenes():
        if is_cancelled is not None and is_cancelled():
            logger.info("[storyboard] {} cancelled before scene {}", project_id, scene["scene"])
            return
        index = scene["scene"]
        jobs.mark_scene(project_id, index, "generating", image_url=None, local_path=None)
        try:
            image_url = transport(scene, aspect_ratio, project_id)
        except Exception as exc:
            error = classify(exc)
            logger.error("[storyboard] {} scene {} failed: {}", project_id, index, exc)
            jobs.record_error(project_id, index, error.message)
            continue

        jobs.mark_scene(project_id, index, "downloading", image_url=image_url)
        destination = jobs.prepare_scene_file(
            project_id, index, jobs.extension_for(image_url)
        )
        if download_image(image_url, destination):
            jobs.record_ready(
                project_id, index, destination,
                image_url=image_url, remove_watermark=remove_watermark,
            )
            logger.success("[storyboard] {} scene {} ready", project_id, index)
        else:
            jobs.record_error(
                project_id, index,
                sanitize_message("The generated image could not be downloaded"),
                image_url=image_url,
            )


__all__ = [
    "MAX_DL_RETRIES",
    "classify",
    "direct_transport",
    "download_image",
    "run_batch",
    "webhook_transport",
]
