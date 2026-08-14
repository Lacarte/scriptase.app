"""AI scene-blueprint provider — thin wrap over `scriptase.modules.scene_director.service`.

Deliberately not a reimplementation. `generate()` translates the generic
request configuration into the unchanged service contract, then maps service
and transport failures onto the shared `ProviderError` catalog with correct
retryability. Artifact writes, chaptering, and coherence scoring stay inside
`generate_scenes`.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

import requests as http_requests

from config import N8N_WEBHOOK_URL
from scriptase.modules.scene_director.providers.base import SceneBlueprintProvider
from scriptase.modules.scene_director.service import SceneServiceError, generate_scenes
from scriptase.shared.security import is_safe_webhook_url
from scriptase.providers.errors import (
    PROVIDER_FAILED,
    PROVIDER_REQUEST_INVALID,
    PROVIDER_RESPONSE_MALFORMED,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
)

_DOMAIN = "scene_director"
_PROVIDER_ID = "n8n"

# Stable service codes -> (provider code, safe public message). The original
# `str(exc)` is never copied (§34.4 / L2).
_SERVICE_ERROR_MAP: dict[str, tuple[str, str]] = {
    "SCENES_WEBHOOK_UNSAFE": (
        PROVIDER_REQUEST_INVALID,
        "The scene webhook URL is not allowed",
    ),
    "SCENES_SEGMENTS_EMPTY": (
        PROVIDER_REQUEST_INVALID,
        "No non-filler segments were provided",
    ),
    "SCENES_RESPONSE_MALFORMED": (
        PROVIDER_RESPONSE_MALFORMED,
        "The scene webhook returned a malformed or incomplete response",
    ),
}


class N8nSceneBlueprintProvider(SceneBlueprintProvider):
    """Registered AI scene-blueprint provider for the current n8n path."""

    def generate(
        self,
        segments: Mapping[str, Any],
        configuration: Mapping[str, Any],
        *,
        project_id: str,
        webhook_caller: Callable[..., Mapping[str, Any]] | None = None,
        progress_cb: Callable[[str], None] | None = None,
        parent_id: str | None = None,
        source_folder: str | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {
            "project_id": project_id,
            # Canonical id, never the `builtin` input alias (P33 / step 13.4).
            "provider_id": _PROVIDER_ID,
        }
        if webhook_caller is not None:
            kwargs["webhook_caller"] = webhook_caller
        if progress_cb is not None:
            kwargs["progress_cb"] = progress_cb
        if parent_id is not None:
            kwargs["parent_id"] = parent_id
        if source_folder is not None:
            kwargs["source_folder"] = source_folder
        try:
            return generate_scenes(segments, configuration, **kwargs)
        except SceneServiceError as exc:
            raise self._map_service_error(exc) from exc
        except http_requests.Timeout as exc:
            raise ProviderError(
                PROVIDER_TIMEOUT,
                "The scene webhook timed out",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc
        except http_requests.ConnectionError as exc:
            raise ProviderError(
                PROVIDER_TRANSPORT_FAILED,
                "Could not reach the scene webhook",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc
        except RuntimeError as exc:
            # `call_webhook` exhausts retries or fails closed on non-200 bodies.
            # Never forward the raw body — it may embed third-party text (L2).
            raise ProviderError(
                PROVIDER_TRANSPORT_FAILED,
                "The scene webhook failed after retries",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc

    @staticmethod
    def _map_service_error(exc: SceneServiceError) -> ProviderError:
        code, message = _SERVICE_ERROR_MAP.get(
            getattr(exc, "code", "") or "",
            (PROVIDER_FAILED, "Scene blueprint generation failed"),
        )
        return ProviderError(
            code,
            message,
            domain=_DOMAIN,
            provider_id=_PROVIDER_ID,
            cause_type=type(exc).__name__,
        )


def create() -> N8nSceneBlueprintProvider:
    return N8nSceneBlueprintProvider()


def health_check(settings: dict) -> dict:
    """Report whether a scene webhook is configured. No request is made."""
    configured = bool((settings or {}).get("webhook_url") or N8N_WEBHOOK_URL)
    return {
        "status": "ok" if configured else "warn",
        "latency_ms": 0,
        "message": (
            "Scene blueprint webhook configured"
            if configured
            else "No scene blueprint webhook URL is configured"
        ),
    }


def validate_settings(settings: dict) -> list[dict]:
    issues: list[dict] = []
    url = str((settings or {}).get("webhook_url") or "").strip()
    if not url:
        return issues
    allow_private = os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
    if not is_safe_webhook_url(url, allow_private=allow_private):
        issues.append({
            "field": "webhook_url",
            "severity": "error",
            "message": "Unsafe webhook URL",
        })
    return issues
