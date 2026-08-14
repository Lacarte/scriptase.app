"""Inbound push / callback intake — step 14.4.

Validates, bounds, redacts, and correlates pushed job status before it reaches
``MediaJobService.apply_callback``. The frozen correlation tuple is
``(domain, provider_id, project_id, job_id)`` (contracts.md §33.3 / D32):

  * unknown correlation → drop + warn (never apply)
  * domain/provider mismatch against a live job → drop + warn
  * duplicate terminal-unit status → idempotent ignore
  * oversized body → reject without parsing
  * malformed body → reject without side effects

Legacy Automa HTTP routes (``/api/animator/grabber/results``, ``…/upload``)
and extension WebSocket handlers stay at their existing URLs; they call into
this module for the correlation gate rather than writing foreign jobs.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Mapping

from loguru import logger

from scriptase.providers.jobs import JobHandle, JobStatus
from scriptase.providers.media_jobs import (
    MediaJobService,
    MediaJobStore,
    default_store,
)
from scriptase.providers.validation import sanitize_message

# Status-only pushes (JobStatus JSON). Media base64 uploads use the larger cap.
MAX_CALLBACK_BODY_BYTES = 64 * 1024
MAX_MEDIA_CALLBACK_BYTES = 32 * 1024 * 1024

APPLIED = "applied"
DROPPED_UNKNOWN = "dropped_unknown"
DROPPED_MISMATCH = "dropped_mismatch"
REJECTED_OVERSIZED = "rejected_oversized"
REJECTED_MALFORMED = "rejected_malformed"
IGNORED_DUPLICATE = "ignored_duplicate"

_VALID_OUTCOMES = frozenset({
    APPLIED, DROPPED_UNKNOWN, DROPPED_MISMATCH,
    REJECTED_OVERSIZED, REJECTED_MALFORMED, IGNORED_DUPLICATE,
})


@dataclass(frozen=True)
class CallbackDisposition:
    """Outcome of one inbound callback attempt."""

    outcome: str
    correlation: tuple[str, str, str, str] | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in {APPLIED, IGNORED_DUPLICATE}

    @property
    def applied(self) -> bool:
        return self.outcome == APPLIED


def correlation_tuple(
    domain: str,
    provider_id: str,
    project_id: str,
    job_id: str,
) -> tuple[str, str, str, str]:
    """Build the frozen push-correlation tuple (§33.3)."""
    return (
        str(domain or ""),
        str(provider_id or ""),
        str(project_id or ""),
        str(job_id or ""),
    )


def parse_correlation(
    payload: Mapping[str, Any] | None,
    *,
    domain: str = "",
    provider_id: str = "",
    defaults: Mapping[str, str] | None = None,
) -> tuple[str, str, str, str] | None:
    """Extract a correlation tuple from a callback body.

    Accepts either nested ``correlation`` / top-level keys, or the legacy
    Automa/extension field names (``projectId``, ``jobId``, ``provider``).
    Returns ``None`` when any of the four components is missing.
    """
    data = dict(payload or {})
    base = dict(defaults or {})
    nested = data.get("correlation")
    if isinstance(nested, Mapping):
        data = {**base, **dict(nested), **data}
    else:
        data = {**base, **data}

    resolved_domain = str(
        data.get("domain") or domain or base.get("domain") or ""
    ).strip()
    resolved_provider = str(
        data.get("provider_id")
        or data.get("provider")
        or provider_id
        or base.get("provider_id")
        or ""
    ).strip()
    project_id = str(
        data.get("project_id")
        or data.get("projectId")
        or base.get("project_id")
        or ""
    ).strip()
    job_id = str(
        data.get("job_id")
        or data.get("jobId")
        or project_id  # legacy: public job id is the project id
        or base.get("job_id")
        or ""
    ).strip()

    if not (resolved_domain and resolved_provider and project_id and job_id):
        return None
    return correlation_tuple(resolved_domain, resolved_provider, project_id, job_id)


def measure_body(body: Any) -> int:
    """Byte length of a raw request body (bytes / str / mapping)."""
    if body is None:
        return 0
    if isinstance(body, (bytes, bytearray)):
        return len(body)
    if isinstance(body, str):
        return len(body.encode("utf-8", errors="replace"))
    try:
        return len(json.dumps(body, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(body).encode("utf-8", errors="replace"))


def job_matches_provider(
    job: Mapping[str, Any] | None,
    *,
    provider_id: str,
    aliases: Mapping[str, str] | None = None,
) -> bool:
    """True when a legacy job document is owned by ``provider_id``.

    An empty/missing ``provider`` field is treated as a match so jobs written
    before 14.2/14.3 still accept their original Automa/extension callbacks.
    """
    if not job or not isinstance(job, Mapping):
        return False
    recorded = str(job.get("provider") or "").strip()
    if not recorded:
        return True
    expected = str(provider_id or "").strip()
    if not expected:
        return False
    if recorded == expected:
        return True
    # Alias tables map both directions: legacy → canonical and vice-versa.
    alias_map = dict(aliases or {})
    canonical_recorded = alias_map.get(recorded, recorded)
    canonical_expected = alias_map.get(expected, expected)
    return canonical_recorded == canonical_expected or recorded == expected or recorded in {
        alias for alias, canonical in alias_map.items() if canonical == expected
    }


class CallbackIntake:
    """Gate between a push transport and ``MediaJobService.apply_callback``."""

    def __init__(
        self,
        service: MediaJobService | None = None,
        *,
        store: MediaJobStore | None = None,
        max_body_bytes: int = MAX_CALLBACK_BODY_BYTES,
    ) -> None:
        if service is not None:
            self.service = service
        else:
            self.service = MediaJobService(store=store if store is not None else default_store())
        self.max_body_bytes = max_body_bytes
        self._lock = threading.Lock()
        self._seen: dict[tuple[str, str, str, str], int] = {}

    def accept(
        self,
        *,
        correlation: tuple[str, str, str, str] | None = None,
        status: JobStatus | Mapping[str, Any] | None = None,
        body: Any = None,
        domain: str = "",
        provider_id: str = "",
        payload: Mapping[str, Any] | None = None,
        max_body_bytes: int | None = None,
        source: str = "push",
    ) -> CallbackDisposition:
        """Validate and apply a pushed status.

        Supply either a ready ``correlation`` + ``status``, or a raw ``payload``
        (plus optional domain/provider defaults) to parse both from the body.
        """
        limit = self.max_body_bytes if max_body_bytes is None else max_body_bytes
        size = measure_body(body if body is not None else payload if payload is not None else status)
        if size > limit:
            logger.warning(
                "[callbacks] rejecting oversized {} callback ({} bytes > {})",
                source, size, limit,
            )
            return CallbackDisposition(
                outcome=REJECTED_OVERSIZED,
                message=f"callback body exceeds {limit} bytes",
            )

        resolved = correlation
        if resolved is None:
            resolved = parse_correlation(
                payload if payload is not None else (
                    status if isinstance(status, Mapping) else None
                ),
                domain=domain,
                provider_id=provider_id,
            )
        if resolved is None:
            logger.warning("[callbacks] rejecting malformed {} callback — no correlation", source)
            return CallbackDisposition(
                outcome=REJECTED_MALFORMED,
                message="callback is missing domain/provider/project/job identity",
            )

        domain_id, prov_id, project_id, job_id = resolved
        if not all(resolved):
            return CallbackDisposition(
                outcome=REJECTED_MALFORMED,
                correlation=resolved,
                message="callback correlation has empty components",
            )

        # If a live job exists under a *different* provider/domain for the same
        # project+job, refuse to apply — that is cross-provider contamination.
        live = self.service.store.get(resolved)
        if live is None:
            # Look for any live job with the same project/job under another provider.
            for other in self.service.store.snapshot():
                handle = other.handle
                if (
                    handle.project_id == project_id
                    and handle.job_id == job_id
                    and (handle.domain != domain_id or handle.provider_id != prov_id)
                ):
                    logger.warning(
                        "[callbacks] dropping {} callback — correlation {} mismatches live {}",
                        source, resolved, handle.correlation,
                    )
                    return CallbackDisposition(
                        outcome=DROPPED_MISMATCH,
                        correlation=resolved,
                        message="callback provider/domain does not match the live job",
                    )

        if status is None and payload is not None:
            status = payload.get("status") if isinstance(payload.get("status"), (Mapping, JobStatus)) else payload

        if status is None:
            return CallbackDisposition(
                outcome=REJECTED_MALFORMED,
                correlation=resolved,
                message="callback has no status payload",
            )

        try:
            if isinstance(status, JobStatus):
                job_status = status
            elif isinstance(status, Mapping):
                # Ensure job_id is present for JobStatus construction.
                body_status = dict(status)
                body_status.setdefault("job_id", job_id)
                job_status = JobStatus.from_dict(body_status)
            else:
                return CallbackDisposition(
                    outcome=REJECTED_MALFORMED,
                    correlation=resolved,
                    message="callback status has an unexpected type",
                )
        except Exception as exc:
            logger.warning(
                "[callbacks] rejecting malformed status for {}: {}",
                resolved, sanitize_message(exc),
            )
            return CallbackDisposition(
                outcome=REJECTED_MALFORMED,
                correlation=resolved,
                message="callback status could not be parsed",
            )

        # Snapshot unit states before apply so we can detect pure-duplicate pushes.
        before = None
        live_before = self.service.store.get(resolved)
        if live_before is not None:
            before = tuple(
                (unit.unit_index, unit.state) for unit in live_before.status.units
            )

        applied = self.service.apply_callback(resolved, job_status)
        if not applied:
            logger.warning(
                "[callbacks] dropping {} callback for unknown correlation {}",
                source, resolved,
            )
            return CallbackDisposition(
                outcome=DROPPED_UNKNOWN,
                correlation=resolved,
                message="no live job for correlation",
            )

        live_after = self.service.store.get(resolved)
        after = None
        if live_after is not None:
            after = tuple(
                (unit.unit_index, unit.state) for unit in live_after.status.units
            )
        if before is not None and before == after:
            return CallbackDisposition(
                outcome=IGNORED_DUPLICATE,
                correlation=resolved,
                message="duplicate terminal status ignored",
            )
        return CallbackDisposition(
            outcome=APPLIED,
            correlation=resolved,
            message="callback applied",
        )

    def accept_legacy_job(
        self,
        *,
        domain: str,
        provider_id: str,
        project_id: str,
        job: Mapping[str, Any] | None,
        body: Any = None,
        max_body_bytes: int | None = None,
        aliases: Mapping[str, str] | None = None,
        source: str = "legacy",
    ) -> CallbackDisposition:
        """Gate a legacy Automa/extension write against the job's recorded provider.

        Does **not** push into ``MediaJobService`` — legacy routes still write
        the domain manifest. This only decides whether the write is allowed.
        """
        limit = (
            MAX_MEDIA_CALLBACK_BYTES if max_body_bytes is None else max_body_bytes
        )
        size = measure_body(body)
        if size > limit:
            logger.warning(
                "[callbacks] rejecting oversized {} body for {}/{} ({} bytes)",
                source, domain, project_id, size,
            )
            return CallbackDisposition(
                outcome=REJECTED_OVERSIZED,
                correlation=correlation_tuple(domain, provider_id, project_id, project_id),
                message=f"callback body exceeds {limit} bytes",
            )

        if not project_id:
            return CallbackDisposition(
                outcome=REJECTED_MALFORMED,
                message="callback is missing project identity",
            )

        if job is None:
            logger.warning(
                "[callbacks] dropping {} for unknown project {} (domain={})",
                source, project_id, domain,
            )
            return CallbackDisposition(
                outcome=DROPPED_UNKNOWN,
                correlation=correlation_tuple(domain, provider_id, project_id, project_id),
                message="no job for project",
            )

        if not job_matches_provider(job, provider_id=provider_id, aliases=aliases):
            recorded = str(job.get("provider") or "")
            logger.warning(
                "[callbacks] dropping {} for {} — expected provider {}, job has {}",
                source, project_id, provider_id, recorded or "(none)",
            )
            return CallbackDisposition(
                outcome=DROPPED_MISMATCH,
                correlation=correlation_tuple(domain, provider_id, project_id, project_id),
                message="callback provider does not match the job",
            )

        return CallbackDisposition(
            outcome=APPLIED,
            correlation=correlation_tuple(
                domain,
                str(job.get("provider") or provider_id),
                project_id,
                str(job.get("grabber_id") or job.get("job_id") or project_id),
            ),
            message="legacy callback accepted",
        )


_DEFAULT_INTAKE: CallbackIntake | None = None
_DEFAULT_LOCK = threading.Lock()


def default_callback_intake() -> CallbackIntake:
    """Process-wide intake sharing the default media-job store."""
    global _DEFAULT_INTAKE
    with _DEFAULT_LOCK:
        if _DEFAULT_INTAKE is None:
            _DEFAULT_INTAKE = CallbackIntake()
        return _DEFAULT_INTAKE


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
    "correlation_tuple",
    "default_callback_intake",
    "job_matches_provider",
    "measure_body",
    "parse_correlation",
]
