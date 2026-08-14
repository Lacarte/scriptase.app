"""Outbound n8n / webhook transport — step 14.4.

Wraps ``scriptase.shared.webhooks.call_webhook`` so providers share one retry policy and
map every failure onto the shared ``ProviderError`` catalog without copying
response bodies (contracts.md §34.4 / L2). Domain-specific payload shape and
response field extraction stay in the provider.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

import requests as http_requests

from scriptase.shared.security import is_safe_webhook_url
from scriptase.providers.errors import (
    PROVIDER_AUTH_FAILED,
    PROVIDER_REQUEST_INVALID,
    PROVIDER_RESPONSE_MALFORMED,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
)
from scriptase.shared.webhooks import call_webhook

_AUTH_MARKERS = (
    "401", "403", "unauthorized", "forbidden", "invalid api key", "api key",
)


def classify_webhook_error(
    exc: BaseException,
    *,
    domain: str = "",
    provider_id: str = "",
) -> ProviderError:
    """Map a webhook/transport failure onto the shared catalog.

    The original text never reaches the message: a raw body may embed URLs,
    tokens, or third-party stack traces.
    """
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, http_requests.Timeout):
        return ProviderError(
            PROVIDER_TIMEOUT,
            "The webhook timed out",
            retryable=True,
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    if isinstance(exc, http_requests.ConnectionError):
        return ProviderError(
            PROVIDER_TRANSPORT_FAILED,
            "Could not reach the webhook",
            retryable=True,
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    text = str(exc).lower()
    if any(marker in text for marker in _AUTH_MARKERS):
        return ProviderError(
            PROVIDER_AUTH_FAILED,
            "The webhook rejected the credentials",
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return ProviderError(
            PROVIDER_RESPONSE_MALFORMED,
            "The webhook returned an unusable response",
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    return ProviderError(
        PROVIDER_TRANSPORT_FAILED,
        "The webhook failed",
        retryable=True,
        domain=domain,
        provider_id=provider_id,
        cause_type=type(exc).__name__,
    )


def post_webhook(
    url: str,
    payload: Mapping[str, Any],
    *,
    timeout: int = 180,
    label: str = "Webhook",
    allow_private: bool = True,
    domain: str = "",
    provider_id: str = "",
    caller: Callable[..., Mapping[str, Any]] | None = None,
) -> Mapping[str, Any]:
    """POST ``payload`` to ``url`` with the shared retry policy.

    Raises ``ProviderError`` (never a raw transport exception). An unsafe URL
    fails closed as ``PROVIDER_REQUEST_INVALID`` before any network call.
    """
    target = (url or "").strip()
    if not target:
        raise ProviderError(
            PROVIDER_REQUEST_INVALID,
            "No webhook URL is configured",
            domain=domain,
            provider_id=provider_id,
        )
    if not is_safe_webhook_url(target, allow_private=allow_private):
        raise ProviderError(
            PROVIDER_REQUEST_INVALID,
            "The webhook URL is not allowed",
            domain=domain,
            provider_id=provider_id,
        )

    invoke = caller or call_webhook
    try:
        result = invoke(target, dict(payload), timeout=timeout, label=label)
    except Exception as exc:
        raise classify_webhook_error(exc, domain=domain, provider_id=provider_id) from exc

    if result is None:
        raise ProviderError(
            PROVIDER_RESPONSE_MALFORMED,
            "The webhook returned an empty response",
            domain=domain,
            provider_id=provider_id,
        )
    if not isinstance(result, Mapping):
        raise ProviderError(
            PROVIDER_RESPONSE_MALFORMED,
            "The webhook returned an unusable response",
            domain=domain,
            provider_id=provider_id,
        )
    return result


def webhook_transport(
    url: str,
    *,
    build_payload: Callable[..., Mapping[str, Any]],
    extract: Callable[[Mapping[str, Any]], Any],
    timeout: int = 180,
    label: str = "Webhook",
    allow_private: bool = True,
    domain: str = "",
    provider_id: str = "",
    caller: Callable[..., Mapping[str, Any]] | None = None,
) -> Callable[..., Any]:
    """Build a per-call transport: ``(*args, **kwargs) -> extract(response)``.

    ``build_payload`` and ``extract`` are the only domain-specific pieces. A
    missing extract value becomes ``PROVIDER_RESPONSE_MALFORMED``.
    """

    def generate(*args: Any, **kwargs: Any) -> Any:
        payload = build_payload(*args, **kwargs)
        result = post_webhook(
            url,
            payload,
            timeout=timeout,
            label=label,
            allow_private=allow_private,
            domain=domain,
            provider_id=provider_id,
            caller=caller,
        )
        try:
            value = extract(result)
        except Exception as exc:
            raise classify_webhook_error(
                exc, domain=domain, provider_id=provider_id
            ) from exc
        if value is None or value == "":
            raise ProviderError(
                PROVIDER_RESPONSE_MALFORMED,
                "The webhook returned no usable result",
                domain=domain,
                provider_id=provider_id,
            )
        return value

    return generate


__all__ = [
    "classify_webhook_error",
    "post_webhook",
    "webhook_transport",
]
