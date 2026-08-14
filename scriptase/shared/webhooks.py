"""Shared webhook helpers — retry, backoff, n8n response unwrapping."""

import json
import time

import requests as http_requests
from loguru import logger

MAX_RETRIES = 3
BASE_DELAY = 2  # seconds — doubles each retry (2s, 4s, 8s)
RETRYABLE_STATUS = {502, 503, 504, 429}


class RetryableWebhookResponseError(RuntimeError):
    """Raised when the webhook responded, but the body is transiently unusable."""


def call_webhook(webhook_url, payload, *, timeout=180, label="Webhook"):
    """POST payload to webhook with retry + exponential backoff.

    Retries on connection errors, timeouts, and 502/503/504/429 responses.
    Also retries on empty responses / empty arrays from flaky webhook runs.
    Fails immediately on 4xx (except 429) or bad JSON / unexpected formats.
    """
    last_exc = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = http_requests.post(webhook_url, json=payload, timeout=timeout)

            # Retryable HTTP status
            if resp.status_code in RETRYABLE_STATUS:
                body_text = resp.text[:300]
                logger.warning(
                    "{} returned {} (attempt {}/{}) — {}",
                    label, resp.status_code, attempt, MAX_RETRIES, body_text,
                )
                last_exc = RuntimeError(
                    f"{label} returned {resp.status_code}: {body_text[:200]}"
                )
                if attempt < MAX_RETRIES:
                    _backoff(attempt)
                    continue
                raise last_exc

            # Non-retryable HTTP error — fail immediately
            if resp.status_code != 200:
                body_text = resp.text[:500]
                logger.error("{} returned {} — {}", label, resp.status_code, body_text)
                error_msg = f"{label} returned {resp.status_code}"
                try:
                    err_data = resp.json()
                    msg = err_data.get("message", "")
                    hint = err_data.get("hint", "")
                    if msg:
                        error_msg = msg
                    if hint:
                        error_msg += f". {hint}"
                except Exception:
                    if body_text:
                        error_msg += f": {body_text[:200]}"
                raise RuntimeError(error_msg)

            # Parse response body
            try:
                return parse_webhook_response(resp, label=label)
            except RetryableWebhookResponseError as e:
                logger.warning(
                    "{} transient response issue (attempt {}/{}): {}",
                    label, attempt, MAX_RETRIES, e,
                )
                last_exc = e
                if attempt < MAX_RETRIES:
                    _backoff(attempt)
                    continue
                raise

        except (http_requests.ConnectionError, http_requests.Timeout) as e:
            logger.warning(
                "{} {} (attempt {}/{}): {}",
                label, type(e).__name__, attempt, MAX_RETRIES, e,
            )
            last_exc = e
            if attempt < MAX_RETRIES:
                _backoff(attempt)
                continue
            raise

    raise last_exc  # type: ignore[misc]


def _backoff(attempt):
    """Sleep with exponential backoff: 2s, 4s, 8s..."""
    delay = BASE_DELAY * (2 ** (attempt - 1))
    logger.info("Retrying webhook in {}s...", delay)
    time.sleep(delay)


def parse_webhook_response(resp, *, label="Webhook"):
    """Validate and parse a successful webhook response (handles n8n array wrapping)."""
    body = resp.text.strip()
    if not body:
        raise RetryableWebhookResponseError(
            f"{label} returned an empty response. If using n8n, make sure "
            "the workflow is activated and uses the production URL (/webhook/) "
            "instead of the test URL (/webhook-test/)."
        )

    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError(f"{label} returned non-JSON response: {body[:200]}")

    # n8n returns an array — unwrap the first element
    if isinstance(result, list):
        if not result:
            raise RetryableWebhookResponseError(f"{label} returned an empty array")
        result = result[0]

    if not isinstance(result, dict):
        raise RuntimeError(f"{label} returned unexpected format (expected JSON object)")

    return result
