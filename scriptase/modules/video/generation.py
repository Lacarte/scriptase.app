"""Kie AI generation mechanics — step 14.3.

The per-scene loop the Kie AI provider owns. It used to live in
`animation_routes._kie_ai_generate_all`, which imported `generate_image`
straight out of the provider package without going through the registry (B8 /
P1) and inverted option precedence by updating request options with stored
settings last (§40.2 O4 / C4).

The transport is now an explicit callable supplied by the provider, and
request options win over durable settings for every key. Failures are recorded
through a sanitized message, never `str(exc)`, because `grabber_job.json` is
handed to legacy status callers and may be archived.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from loguru import logger

from config import ANIMATOR_DIR
from scriptase.modules.video import jobs
from scriptase.modules.video.organizer import organize_grabber_assets
from scriptase.providers.errors import (
    PROVIDER_AUTH_FAILED,
    PROVIDER_RESPONSE_MALFORMED,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
)
from scriptase.providers.validation import sanitize_message

Transport = Callable[..., Mapping[str, Any]]

_AUTH_MARKERS = ("401", "403", "unauthorized", "forbidden", "invalid api key", "api key")


def classify(exc: BaseException) -> ProviderError:
    """Map a transport failure onto the shared error catalog."""
    if isinstance(exc, TimeoutError):
        return ProviderError(PROVIDER_TIMEOUT, "The image request timed out", retryable=True)
    text = str(exc).lower()
    if any(marker in text for marker in _AUTH_MARKERS):
        return ProviderError(
            PROVIDER_AUTH_FAILED, "The image service rejected the credentials"
        )
    if "timeout" in text:
        return ProviderError(PROVIDER_TIMEOUT, "The image request timed out", retryable=True)
    if "no taskid" in text or "malformed" in text:
        return ProviderError(
            PROVIDER_RESPONSE_MALFORMED, "The image service returned an unusable response"
        )
    return ProviderError(
        PROVIDER_TRANSPORT_FAILED, "Could not reach the image service", retryable=True
    )


def run_batch(
    project_id: str,
    request,
    transport: Transport,
    *,
    options: Mapping[str, Any] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Generate every scene sequentially through `transport`.

    `transport(prompt, **options) -> {"url": ..., "all_urls": [...]}`. The
    provider builds the callable so this loop never imports a concrete client.
    """
    opts = dict(options or {})
    aspect_ratio = str(opts.get("aspect_ratio") or request.aspect_ratio or "9:16")
    resolution = str(opts.get("resolution") or "1")
    output_format = str(opts.get("output_format") or "jpg")
    model = opts.get("model")

    scenes = list(request.scenes)
    logger.info(
        "[animator] Kie batch started: {} scenes, model={}, ar={}, res={}, fmt={}",
        len(scenes), model, aspect_ratio, resolution, output_format,
    )
    jobs.mark_status(project_id, "generating")

    for scene in scenes:
        if is_cancelled is not None and is_cancelled():
            logger.info("[animator] Kie batch cancelled for {}", project_id)
            return

        index = scene.index
        prompt = scene.prompt
        jobs.mark_scene(project_id, index, "generating")
        logger.info("[animator] Kie scene {}: generating ({})", index, prompt[:80])

        try:
            result = transport(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                output_format=output_format,
                model=model,
            )
            image_urls = list(result.get("all_urls") or [])
            if not image_urls and result.get("url"):
                image_urls = [result["url"]]
            if not image_urls:
                raise ProviderError(
                    PROVIDER_RESPONSE_MALFORMED,
                    "The image service returned no image URLs",
                )

            jobs.mark_scene(
                project_id, index, "downloading", urls=image_urls, local_files=[]
            )
            local_files = organize_grabber_assets(
                project_id=project_id,
                scene_num=str(index),
                urls=image_urls,
                assets_dir=ANIMATOR_DIR,
            )
            jobs.record_ready(
                project_id, index, local_files,
                urls=image_urls, kind="image",
            )
            logger.success(
                "[animator] Kie scene {} ready: {} files", index, len(local_files)
            )
        except Exception as exc:
            # Already-safe ProviderError messages pass through; everything else
            # is sanitized so a raw stack/path never reaches the manifest.
            if isinstance(exc, ProviderError):
                message = exc.message
            else:
                classified = classify(exc)
                message = classified.message or sanitize_message(exc)
            logger.error("[animator] Kie scene {} failed: {}", index, message)
            jobs.record_error(project_id, index, message)

    if jobs.maybe_finish(project_id):
        logger.success("[animator] Kie generation complete for {}", project_id)


__all__ = ["Transport", "classify", "run_batch"]
