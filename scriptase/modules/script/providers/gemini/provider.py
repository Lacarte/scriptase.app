"""AI script provider — thin wrap over `scriptase.modules.script.service` (step 13.2).

Deliberately not a reimplementation. `generate()` translates the generic script
request configuration into the unchanged service contract, then maps service and
transport failures onto the shared `ProviderError` catalog with correct
retryability. Artifact writes, section parsing, and diversity history stay inside
`generate_story`.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

import requests as http_requests

from config import N8N_STORY_WEBHOOK_URL
from scriptase.shared.security import is_safe_webhook_url
from scriptase.providers.errors import (
    PROVIDER_FAILED,
    PROVIDER_REQUEST_INVALID,
    PROVIDER_RESPONSE_MALFORMED,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
)
from scriptase.modules.script.providers.base import ScriptProvider
from scriptase.modules.script.service import StoryServiceError, generate_story

_DOMAIN = "script"
_PROVIDER_ID = "gemini"

# Stable service codes -> (provider code, safe public message). The original
# `str(exc)` is never copied (§34.4).
_SERVICE_ERROR_MAP: dict[str, tuple[str, str]] = {
    "STORY_WEBHOOK_UNSAFE": (
        PROVIDER_REQUEST_INVALID,
        "The story webhook URL is not allowed",
    ),
    "STORY_TEXT_MISSING": (
        PROVIDER_RESPONSE_MALFORMED,
        "The story webhook returned no story text",
    ),
}


class GeminiScriptProvider(ScriptProvider):
    """Registered AI script provider for the current n8n/Gemini story path."""

    def generate(
        self,
        configuration: Mapping[str, Any],
        *,
        project_id: str,
        webhook_caller: Callable[..., Mapping[str, Any]] | None = None,
    ) -> dict:
        kwargs: dict[str, Any] = {
            "project_id": project_id,
            # Canonical id, never the `builtin` input alias (P33 / step 13.3).
            "provider_id": _PROVIDER_ID,
        }
        if webhook_caller is not None:
            kwargs["webhook_caller"] = webhook_caller
        try:
            return generate_story(configuration, **kwargs)
        except StoryServiceError as exc:
            raise self._map_service_error(exc) from exc
        except http_requests.Timeout as exc:
            raise ProviderError(
                PROVIDER_TIMEOUT,
                "The story webhook timed out",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc
        except http_requests.ConnectionError as exc:
            raise ProviderError(
                PROVIDER_TRANSPORT_FAILED,
                "Could not reach the story webhook",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc
        except RuntimeError as exc:
            # `call_webhook` exhausts retries or fails closed on non-200 bodies.
            # Never forward the raw body — it may embed third-party text (L2).
            raise ProviderError(
                PROVIDER_TRANSPORT_FAILED,
                "The story webhook failed after retries",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc

    @staticmethod
    def _map_service_error(exc: StoryServiceError) -> ProviderError:
        code, message = _SERVICE_ERROR_MAP.get(
            getattr(exc, "code", "") or "",
            (PROVIDER_FAILED, "Story generation failed"),
        )
        return ProviderError(
            code,
            message,
            domain=_DOMAIN,
            provider_id=_PROVIDER_ID,
            cause_type=type(exc).__name__,
        )


def create() -> GeminiScriptProvider:
    return GeminiScriptProvider()


def health_check(settings: dict) -> dict:
    """Report whether a story webhook is configured. No request is made."""
    configured = bool((settings or {}).get("webhook_url") or N8N_STORY_WEBHOOK_URL)
    return {
        "status": "ok" if configured else "warn",
        "latency_ms": 0,
        "message": (
            "Story webhook configured"
            if configured
            else "No story webhook URL is configured"
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
