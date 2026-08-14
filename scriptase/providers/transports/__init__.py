"""Domain-neutral provider transports — step 14.4.

Four adapters live here. Providers opt in; none of this code knows about
storyboard frames, animator takes, or any other domain business logic:

  * ``extension``  — browser WebSocket / Automa client pool + pending queue
  * ``webhook``    — outbound n8n-style HTTP webhooks with safe error mapping
  * ``direct_api`` — outbound REST submit/poll without accidental POST retries
  * ``callbacks``  — inbound push intake, correlation-scoped and bounded

Cross-provider and cross-job contamination is blocked by the frozen push
correlation tuple ``(domain, provider_id, project_id, job_id)`` (contracts.md
§33.3 / D32). Existing external WebSocket and Automa HTTP URLs stay as
compatibility facades on the domain routes.
"""

from scriptase.providers.transports.callbacks import (
    MAX_CALLBACK_BODY_BYTES,
    MAX_MEDIA_CALLBACK_BYTES,
    APPLIED,
    DROPPED_MISMATCH,
    DROPPED_UNKNOWN,
    IGNORED_DUPLICATE,
    REJECTED_MALFORMED,
    REJECTED_OVERSIZED,
    CallbackDisposition,
    CallbackIntake,
    correlation_tuple,
    default_callback_intake,
    job_matches_provider,
    measure_body,
    parse_correlation,
)
from scriptase.providers.transports.direct_api import (
    DirectApiClient,
    DirectApiError,
    classify_http_error,
    submit_and_poll,
)
from scriptase.providers.transports.extension import (
    ExtensionWebSocketHub,
    extension_connected,
)
from scriptase.providers.transports.webhook import (
    classify_webhook_error,
    post_webhook,
    webhook_transport,
)

__all__ = [
    "APPLIED",
    "DROPPED_MISMATCH",
    "DROPPED_UNKNOWN",
    "IGNORED_DUPLICATE",
    "MAX_CALLBACK_BODY_BYTES",
    "MAX_MEDIA_CALLBACK_BYTES",
    "REJECTED_MALFORMED",
    "REJECTED_OVERSIZED",
    "CallbackDisposition",
    "CallbackIntake",
    "DirectApiClient",
    "DirectApiError",
    "ExtensionWebSocketHub",
    "classify_http_error",
    "classify_webhook_error",
    "correlation_tuple",
    "default_callback_intake",
    "extension_connected",
    "job_matches_provider",
    "measure_body",
    "parse_correlation",
    "post_webhook",
    "submit_and_poll",
    "webhook_transport",
]
