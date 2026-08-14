"""Provider errors and the stable code catalog — step 11.4.

Implements contracts.md §34. `ProviderError` is the one exception type that
crosses the provider boundary; every other exception is wrapped by
`boundary.wrap_exception()` without ever copying `str(exc)` (§34.4).

This module is a leaf: it imports only the sanitizer, so `results`,
`invocation`, `jobs`, and `boundary` can all build on it without a cycle. In
particular it does **not** import `scriptase.engine.adapters.common` —
`as_adapter_error()` constructs the adapter carrier lazily so the provider layer
and the workflow layer never import each other's module (§34.4).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from scriptase.providers.validation import sanitize_message


# -- code catalog (contracts.md §34.2, frozen) ------------------------------

PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
PROVIDER_REQUEST_INVALID = "PROVIDER_REQUEST_INVALID"
PROVIDER_RESULT_INVALID = "PROVIDER_RESULT_INVALID"
PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
PROVIDER_QUOTA_EXHAUSTED = "PROVIDER_QUOTA_EXHAUSTED"
PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
PROVIDER_TRANSPORT_FAILED = "PROVIDER_TRANSPORT_FAILED"
PROVIDER_RESPONSE_MALFORMED = "PROVIDER_RESPONSE_MALFORMED"
PROVIDER_UNIT_FAILED = "PROVIDER_UNIT_FAILED"
PROVIDER_ARTIFACT_MISSING = "PROVIDER_ARTIFACT_MISSING"
PROVIDER_ARTIFACT_UNMANAGED = "PROVIDER_ARTIFACT_UNMANAGED"
PROVIDER_FAILED = "PROVIDER_FAILED"
CANCELLED = "CANCELLED"

# `retryable` is a property of the code, not of the provider: a provider may not
# mark PROVIDER_AUTH_FAILED retryable to force retries (§34.3). `None` means
# "per-case" — only PROVIDER_UNIT_FAILED, whose caller decides.
RETRYABLE: dict[str, bool | None] = {
    PROVIDER_NOT_FOUND: False,
    PROVIDER_UNAVAILABLE: True,
    PROVIDER_NOT_CONFIGURED: False,
    PROVIDER_REQUEST_INVALID: False,
    PROVIDER_RESULT_INVALID: False,
    PROVIDER_AUTH_FAILED: False,
    PROVIDER_RATE_LIMITED: True,
    PROVIDER_QUOTA_EXHAUSTED: False,
    PROVIDER_TIMEOUT: True,
    PROVIDER_TRANSPORT_FAILED: True,
    PROVIDER_RESPONSE_MALFORMED: True,
    PROVIDER_UNIT_FAILED: None,
    PROVIDER_ARTIFACT_MISSING: False,
    PROVIDER_ARTIFACT_UNMANAGED: False,
    PROVIDER_FAILED: False,
    CANCELLED: False,
}

PROVIDER_CODES = frozenset(RETRYABLE)

# Provider code -> the §7 stable workflow code. The workflow-facing set does not
# grow for provider internals; the finer code travels in `details.provider_code`.
WORKFLOW_CODE = {
    PROVIDER_UNAVAILABLE: "PROVIDER_UNAVAILABLE",
    PROVIDER_NOT_CONFIGURED: "PROVIDER_UNAVAILABLE",
    PROVIDER_NOT_FOUND: "PROVIDER_UNAVAILABLE",
    PROVIDER_TIMEOUT: "POLL_TIMEOUT",
    CANCELLED: "CANCELLED",
    PROVIDER_ARTIFACT_MISSING: "ARTIFACT_MISSING",
    PROVIDER_ARTIFACT_UNMANAGED: "ARTIFACT_MISSING",
}
DEFAULT_WORKFLOW_CODE = "NODE_EXECUTION_FAILED"

MESSAGE_MAX = 300
DETAILS_MAX_BYTES = 4096

# Generic, per-domain replacements for a wrapped unknown exception (§34.4 rule 2).
# The original `str(exc)` is never one of these.
_GENERIC_MESSAGE = {
    "script": "The script provider failed while generating the story.",
    "scene_director": "The scene director provider failed while planning scenes.",
    "tts": "The speech provider failed while synthesizing audio.",
    "image": "The image provider failed while generating images.",
    "video": "The video provider failed while generating assets.",
}
_GENERIC_FALLBACK = "The provider failed while handling the request."

_RECOVERY = {
    PROVIDER_NOT_CONFIGURED: "Open provider settings and fill in the required fields.",
    PROVIDER_AUTH_FAILED: "Check the provider credentials in settings, then retry.",
    PROVIDER_QUOTA_EXHAUSTED: "Top up the provider account or choose another provider.",
    PROVIDER_RATE_LIMITED: "Wait for the provider rate limit to reset, then retry.",
    PROVIDER_TIMEOUT: "Retry the node, or choose a faster provider.",
    CANCELLED: "Start a new run when ready.",
}
_DEFAULT_RECOVERY = "Review the provider settings and inputs, then retry the node."


def is_retryable(code: str, *, default: bool = False) -> bool:
    """Retryability for a code, from the frozen table (§34.3)."""
    value = RETRYABLE.get(code, default)
    return default if value is None else value


def workflow_code(code: str) -> str:
    """Map a provider code onto the §7 stable workflow code."""
    return WORKFLOW_CODE.get(code, DEFAULT_WORKFLOW_CODE)


def generic_message(domain: str) -> str:
    """The per-domain sentence used when an unknown exception is wrapped."""
    return _GENERIC_MESSAGE.get(domain, _GENERIC_FALLBACK)


def _safe_details(details: Any) -> dict | None:
    """JSON-only, redacted, size-capped `details` (§34.1).

    Anything that will not serialize, or that exceeds 4 KiB, is dropped whole
    rather than truncated into an unparseable fragment.
    """
    if details is None:
        return None
    if not isinstance(details, dict):
        return None
    from scriptase.engine.redaction import redact

    scrubbed = redact(details)
    try:
        encoded = json.dumps(scrubbed, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > DETAILS_MAX_BYTES:
        return {"truncated": True}
    return scrubbed


def _clip(text: object, limit: int) -> str:
    message = sanitize_message(text)
    if len(message) > limit:
        message = message[: limit - 1].rstrip() + "\u2026"
    return message


class ProviderError(Exception):
    """A provider failure that is safe to persist, log, and serialize (§34.1).

    `message` is sanitized on construction, so there is no way to build one that
    leaks a path or a `key=value` secret — including through subclasses.
    """

    default_code = PROVIDER_FAILED

    def __init__(
        self,
        code: str = "",
        message: str = "",
        *,
        retryable: bool | None = None,
        domain: str = "",
        provider_id: str = "",
        details: Any = None,
        recovery_suggestion: str | None = None,
        unit_index: int | None = None,
        cause_type: str | None = None,
    ):
        self.code = code or self.default_code
        self.message = _clip(message, MESSAGE_MAX) or generic_message(domain)
        self.retryable = (
            is_retryable(self.code) if retryable is None else bool(retryable)
        )
        self.domain = domain
        self.provider_id = provider_id
        self.details = _safe_details(details)
        self.recovery_suggestion = recovery_suggestion or _RECOVERY.get(
            self.code, _DEFAULT_RECOVERY
        )
        self.unit_index = unit_index
        # The class name only — never the cause's message (§34.1).
        self.cause_type = cause_type
        super().__init__(self.message)

    @property
    def workflow_code(self) -> str:
        return workflow_code(self.code)

    def to_payload(self) -> dict:
        """The `ProviderErrorPayload` JSON form (§34.1)."""
        payload = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.domain:
            payload["domain"] = self.domain
        if self.provider_id:
            payload["provider_id"] = self.provider_id
        if self.details is not None:
            payload["details"] = self.details
        if self.recovery_suggestion:
            payload["recovery_suggestion"] = self.recovery_suggestion
        if self.unit_index is not None:
            payload["unit_index"] = self.unit_index
        if self.cause_type:
            payload["cause_type"] = self.cause_type
        return payload

    def as_adapter_error(self):
        """Convert to the adapter→scheduler carrier (§34.4).

        `AdapterError` is not replaced by `ProviderError`; this is the one
        mapping between the two layers, and it is imported lazily so neither
        module depends on the other.
        """
        from scriptase.engine.adapters.common import AdapterError

        details = dict(self.details or {})
        # The workflow code is coarser than the provider code, so the precise
        # one travels in details and a UI can still tell auth from malformed.
        details.setdefault("provider_code", self.code)
        details.setdefault("retryable", self.retryable)
        if self.provider_id:
            details.setdefault("provider_id", self.provider_id)
        if self.unit_index is not None:
            details.setdefault("unit_index", self.unit_index)
        error = AdapterError(self.workflow_code, self.message, details=details)
        error.retryable = self.retryable
        error.recovery_suggestion = self.recovery_suggestion
        return error

    @classmethod
    def from_payload(cls, payload: dict) -> "ProviderError":
        """Rebuild from a persisted `ProviderErrorPayload`."""
        data = dict(payload or {})
        code = data.get("code") or PROVIDER_FAILED
        error_cls = ProviderCancelled if code == CANCELLED else cls
        return error_cls(
            code,
            data.get("message", ""),
            retryable=data.get("retryable"),
            domain=data.get("domain", ""),
            provider_id=data.get("provider_id", ""),
            details=data.get("details"),
            recovery_suggestion=data.get("recovery_suggestion"),
            unit_index=data.get("unit_index"),
            cause_type=data.get("cause_type"),
        )


class ProviderCancelled(ProviderError):
    """Cooperative cancellation. The one subclass with fixed semantics (§34.1).

    Never a failure and never retried: it maps to workflow `CANCELLED` and node
    status `cancelled`, which is the only code the scheduler recognizes (§35.1).
    """

    default_code = CANCELLED

    def __init__(self, message: str = "Execution was cancelled", **kwargs):
        kwargs.pop("code", None)
        kwargs["retryable"] = False
        super().__init__(CANCELLED, message, **kwargs)


@dataclass(frozen=True)
class ProviderErrorPayload:
    """Typed view of the JSON error form carried by jobs and units (§34.1)."""

    code: str
    message: str
    retryable: bool = False
    unit_index: int | None = None
    details: dict | None = None
    cause_type: str | None = None
    recovery_suggestion: str | None = None
    domain: str = ""
    provider_id: str = ""

    @classmethod
    def from_error(cls, error: ProviderError) -> "ProviderErrorPayload":
        return cls(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            unit_index=error.unit_index,
            details=error.details,
            cause_type=error.cause_type,
            recovery_suggestion=error.recovery_suggestion,
            domain=error.domain,
            provider_id=error.provider_id,
        )

    def as_error(self) -> ProviderError:
        """Rebuild the exception, re-running every §34.1 safety rule."""
        return ProviderError.from_payload(asdict(self))

    def to_dict(self) -> dict:
        return self.as_error().to_payload()


__all__ = [
    "CANCELLED",
    "DEFAULT_WORKFLOW_CODE",
    "DETAILS_MAX_BYTES",
    "MESSAGE_MAX",
    "PROVIDER_ARTIFACT_MISSING",
    "PROVIDER_ARTIFACT_UNMANAGED",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_CODES",
    "PROVIDER_FAILED",
    "PROVIDER_NOT_CONFIGURED",
    "PROVIDER_NOT_FOUND",
    "PROVIDER_QUOTA_EXHAUSTED",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_REQUEST_INVALID",
    "PROVIDER_RESPONSE_MALFORMED",
    "PROVIDER_RESULT_INVALID",
    "PROVIDER_TIMEOUT",
    "PROVIDER_TRANSPORT_FAILED",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_UNIT_FAILED",
    "RETRYABLE",
    "WORKFLOW_CODE",
    "ProviderCancelled",
    "ProviderError",
    "ProviderErrorPayload",
    "generic_message",
    "is_retryable",
    "workflow_code",
]
