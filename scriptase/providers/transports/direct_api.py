"""Outbound direct HTTP API transport — step 14.4.

Shared submit / poll helpers for cloud providers that talk to a REST API
directly (WaveSpeed, Kie AI). Generation POSTs are **not** transport-retried
by default (D40 / contracts.md §35): a lost response after the remote accepted
the work would duplicate side effects. Poll GETs may retry transient failures.

Providers keep model/payload construction; this module owns HTTP mechanics and
the mapping onto ``ProviderError``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping

import requests as http_requests
from loguru import logger

from scriptase.providers.errors import (
    PROVIDER_AUTH_FAILED,
    PROVIDER_RATE_LIMITED,
    PROVIDER_RESPONSE_MALFORMED,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
)

_AUTH_STATUS = frozenset({401, 403})
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
_AUTH_MARKERS = (
    "401", "403", "unauthorized", "forbidden", "invalid api key", "api key",
)


class DirectApiError(ProviderError):
    """Transport-layer ``ProviderError`` raised by this module."""


def classify_http_error(
    exc: BaseException,
    *,
    domain: str = "",
    provider_id: str = "",
    response: http_requests.Response | None = None,
) -> ProviderError:
    """Map an HTTP / network failure onto the shared catalog without body text."""
    if isinstance(exc, ProviderError):
        return exc

    status = response.status_code if response is not None else None
    if status is None and isinstance(exc, http_requests.HTTPError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)

    if status in _AUTH_STATUS:
        return DirectApiError(
            PROVIDER_AUTH_FAILED,
            "The API rejected the credentials",
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    if status == 429:
        return DirectApiError(
            PROVIDER_RATE_LIMITED,
            "The API rate-limited the request",
            retryable=True,
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    if isinstance(exc, http_requests.Timeout) or (
        isinstance(exc, TimeoutError)
    ):
        return DirectApiError(
            PROVIDER_TIMEOUT,
            "The API request timed out",
            retryable=True,
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    if isinstance(exc, http_requests.ConnectionError):
        return DirectApiError(
            PROVIDER_TRANSPORT_FAILED,
            "Could not reach the API",
            retryable=True,
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )

    text = str(exc).lower()
    if any(marker in text for marker in _AUTH_MARKERS):
        return DirectApiError(
            PROVIDER_AUTH_FAILED,
            "The API rejected the credentials",
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    if "timeout" in text:
        return DirectApiError(
            PROVIDER_TIMEOUT,
            "The API request timed out",
            retryable=True,
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    if isinstance(exc, (ValueError, KeyError, TypeError, json.JSONDecodeError)):
        return DirectApiError(
            PROVIDER_RESPONSE_MALFORMED,
            "The API returned an unusable response",
            domain=domain,
            provider_id=provider_id,
            cause_type=type(exc).__name__,
        )
    return DirectApiError(
        PROVIDER_TRANSPORT_FAILED,
        "The API request failed",
        retryable=True,
        domain=domain,
        provider_id=provider_id,
        cause_type=type(exc).__name__,
    )


class DirectApiClient:
    """Thin requests session wrapper with shared classification and no POST retry.

    Parameters
    ----------
    base_url:
        Optional prefix for relative paths.
    default_headers:
        Merged into every request (Authorization, Content-Type, …).
    timeout:
        Default per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        base_url: str = "",
        default_headers: Mapping[str, str] | None = None,
        timeout: float = 30,
        domain: str = "",
        provider_id: str = "",
        session: http_requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.default_headers = dict(default_headers or {})
        self.timeout = timeout
        self.domain = domain
        self.provider_id = provider_id
        self.session = session or http_requests.Session()

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        if not self.base_url:
            return path_or_url
        return f"{self.base_url}/{path_or_url.lstrip('/')}"

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        retries: int = 0,
    ) -> http_requests.Response:
        """Issue one HTTP request. ``retries`` applies only to GET-like methods.

        Generation POSTs pass ``retries=0`` (the default) so a lost response
        cannot duplicate remote work (D40).
        """
        method_u = method.upper()
        if method_u not in {"GET", "HEAD"} and retries:
            # Defensive: never silently retry a non-idempotent verb.
            logger.warning(
                "[direct_api] ignoring retries={} for non-idempotent {}",
                retries, method_u,
            )
            retries = 0

        url = self._url(path_or_url)
        hdrs = {**self.default_headers, **dict(headers or {})}
        last_exc: BaseException | None = None
        attempts = max(1, retries + 1)

        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method_u,
                    url,
                    json=json,
                    params=params,
                    headers=hdrs,
                    timeout=timeout if timeout is not None else self.timeout,
                )
                if response.status_code in _AUTH_STATUS:
                    raise classify_http_error(
                        http_requests.HTTPError(response=response),
                        domain=self.domain,
                        provider_id=self.provider_id,
                        response=response,
                    )
                if (
                    response.status_code in _RETRYABLE_STATUS
                    and attempt < attempts - 1
                    and method_u in {"GET", "HEAD"}
                ):
                    time.sleep(min(2 ** attempt, 8))
                    continue
                response.raise_for_status()
                return response
            except ProviderError:
                raise
            except Exception as exc:
                last_exc = exc
                response = getattr(exc, "response", None)
                if attempt < attempts - 1 and method_u in {"GET", "HEAD"}:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise classify_http_error(
                    exc,
                    domain=self.domain,
                    provider_id=self.provider_id,
                    response=response,
                ) from exc

        raise classify_http_error(
            last_exc or RuntimeError("request failed"),
            domain=self.domain,
            provider_id=self.provider_id,
        )

    def post_json(
        self,
        path_or_url: str,
        payload: Mapping[str, Any],
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        """POST once (no transport retry) and return the JSON body."""
        response = self.request(
            "POST", path_or_url, json=payload, timeout=timeout, headers=headers, retries=0
        )
        try:
            data = response.json()
        except Exception as exc:
            raise classify_http_error(
                exc, domain=self.domain, provider_id=self.provider_id, response=response
            ) from exc
        if not isinstance(data, Mapping):
            raise DirectApiError(
                PROVIDER_RESPONSE_MALFORMED,
                "The API returned an unusable response",
                domain=self.domain,
                provider_id=self.provider_id,
            )
        return data

    def get_json(
        self,
        path_or_url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        retries: int = 2,
    ) -> Mapping[str, Any]:
        """GET with optional transient retries and return the JSON body."""
        response = self.request(
            "GET",
            path_or_url,
            params=params,
            timeout=timeout,
            headers=headers,
            retries=retries,
        )
        try:
            data = response.json()
        except Exception as exc:
            raise classify_http_error(
                exc, domain=self.domain, provider_id=self.provider_id, response=response
            ) from exc
        if not isinstance(data, Mapping):
            raise DirectApiError(
                PROVIDER_RESPONSE_MALFORMED,
                "The API returned an unusable response",
                domain=self.domain,
                provider_id=self.provider_id,
            )
        return data

    def close(self) -> None:
        self.session.close()


def submit_and_poll(
    client: DirectApiClient,
    *,
    submit_path: str,
    submit_payload: Mapping[str, Any],
    poll_path: str | Callable[[Mapping[str, Any]], str],
    is_done: Callable[[Mapping[str, Any]], bool],
    is_failed: Callable[[Mapping[str, Any]], bool] | None = None,
    extract: Callable[[Mapping[str, Any]], Any],
    poll_interval_s: float = 3.0,
    poll_timeout_s: float = 180.0,
    submit_timeout: float | None = None,
    poll_timeout: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    extract_poll_params: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
) -> Any:
    """POST once, then poll until ``is_done`` / failure / deadline.

    ``poll_path`` may be a string or a callable of the submit response so the
    provider can build ``/jobs/{id}`` style URLs. The submit is never retried.
    """
    submitted = client.post_json(
        submit_path, submit_payload, timeout=submit_timeout
    )

    if callable(poll_path):
        path = poll_path(submitted)
    else:
        path = poll_path

    deadline = clock() + poll_timeout_s
    last: Mapping[str, Any] = submitted
    while clock() < deadline:
        params = None
        if extract_poll_params is not None:
            params = extract_poll_params(submitted)
        last = client.get_json(path, params=params, timeout=poll_timeout)
        if is_failed is not None and is_failed(last):
            raise DirectApiError(
                PROVIDER_TRANSPORT_FAILED,
                "The remote job failed",
                domain=client.domain,
                provider_id=client.provider_id,
            )
        if is_done(last):
            try:
                return extract(last)
            except Exception as exc:
                raise classify_http_error(
                    exc, domain=client.domain, provider_id=client.provider_id
                ) from exc
        sleeper(poll_interval_s)

    raise DirectApiError(
        PROVIDER_TIMEOUT,
        "The remote job timed out",
        retryable=True,
        domain=client.domain,
        provider_id=client.provider_id,
    )


__all__ = [
    "DirectApiClient",
    "DirectApiError",
    "classify_http_error",
    "submit_and_poll",
]
