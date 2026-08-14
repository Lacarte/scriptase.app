"""The one asynchronous job contract — step 11.4.

Implements contracts.md §33, replacing the two field-for-field duplicate
`JobHandle`/`JobStatus`/`SceneResult` definitions that lived in
`scriptase/modules/image/providers/base.py` and `scriptase/modules/video/providers/base.py`
(§14.6). Those modules now re-export these types.

Two deliberate changes from the duplicated dataclasses:

  * `status: str` becomes `state` with a closed vocabulary — the old field held
    provider-defined strings, so no caller could branch on it safely;
  * `result: dict | None` becomes `units: tuple[UnitResult, ...]`, so a partial
    result is expressible while the job is still running.

Every terminal state maps to exactly one invocation outcome, which is what makes
a synchronous and an asynchronous provider indistinguishable to the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

from scriptase.shared.io_utils import now_iso
from scriptase.providers.errors import (
    CANCELLED,
    PROVIDER_NOT_FOUND,
    PROVIDER_TIMEOUT,
    PROVIDER_UNIT_FAILED,
    ProviderCancelled,
    ProviderError,
    ProviderErrorPayload,
)
from scriptase.providers.results import (
    FAILED,
    PARTIAL,
    SUCCEEDED,
    UnitResult,
)
from scriptase.providers.validation import sanitize_message


JOB_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

# -- state machine (contracts.md §33.2, frozen) -----------------------------

SUBMITTED = "submitted"
RUNNING = "running"
TIMED_OUT = "timed_out"
# The job-state spelling of the `CANCELLED` error code.
JOB_CANCELLED = CANCELLED.lower()

JOB_STATES = (SUBMITTED, RUNNING, SUCCEEDED, PARTIAL, FAILED, JOB_CANCELLED, TIMED_OUT)
TERMINAL_STATES = frozenset({SUCCEEDED, PARTIAL, FAILED, JOB_CANCELLED, TIMED_OUT})
JOB_STATE_SET = frozenset(JOB_STATES)

# Poll cadence (§33.3). The first poll is early so a fast job is not held for a
# whole interval; the push watchdog is what stops a lost callback hanging a job.
FIRST_POLL_DELAY_S = 2.0
POLL_JITTER = 0.10
DOMAIN_POLL_INTERVAL_S = {"image": 10.0, "video": 10.0}
PUSH_WATCHDOG_INTERVAL_S = 60.0
# The current loop swallows every poll exception forever, which turns a
# permanently broken provider into a 30-minute wait (§33.3).
MAX_CONSECUTIVE_POLL_FAILURES = 3


def poll_interval(domain: str, *, push: bool = False) -> float:
    """The frozen poll cadence for a domain (§33.3)."""
    if push:
        return PUSH_WATCHDOG_INTERVAL_S
    return DOMAIN_POLL_INTERVAL_S.get(domain, 10.0)


@dataclass(frozen=True)
class JobHandle:
    """Stable identity only. Live state belongs exclusively to `JobStatus`.

    Putting `state` on the frozen handle would either go stale at the first
    transition or force replacing the identity object on every poll (§33.1).
    """

    job_id: str
    domain: str = ""
    provider_id: str = ""
    project_id: str = ""
    invocation_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not JOB_ID_RE.fullmatch(str(self.job_id or "")):
            raise ProviderError(
                "PROVIDER_RESULT_INVALID",
                "Job id must match ^[A-Za-z0-9_.:-]{1,128}$",
                domain=self.domain,
                provider_id=self.provider_id,
            )
        if not self.created_at:
            object.__setattr__(self, "created_at", now_iso())

    @property
    def correlation(self) -> tuple[str, str, str, str]:
        """The frozen push-correlation tuple (§33.3).

        A pushed status whose tuple does not match a live job is dropped and
        warned, never applied.
        """
        return (self.domain, self.provider_id, self.project_id, self.job_id)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "domain": self.domain,
            "provider_id": self.provider_id,
            "project_id": self.project_id,
            "invocation_id": self.invocation_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JobHandle":
        return cls(
            job_id=str(data.get("job_id", "")),
            domain=str(data.get("domain", "")),
            provider_id=str(data.get("provider_id", "")),
            project_id=str(data.get("project_id", "")),
            invocation_id=str(data.get("invocation_id", "")),
            created_at=str(data.get("created_at", "")),
        )


@dataclass(frozen=True)
class JobStatus:
    """A point-in-time snapshot of one job (§33.1)."""

    job_id: str
    state: str = SUBMITTED
    ready: int = 0
    total: int = 0
    fraction: float | None = None
    message: str | None = None
    units: tuple[UnitResult, ...] = ()
    error: ProviderErrorPayload | None = None
    updated_at: str = ""

    def __post_init__(self):
        if self.state not in JOB_STATE_SET:
            raise ProviderError(
                "PROVIDER_RESULT_INVALID", f"Unknown job state {self.state!r}"
            )
        if self.message is not None:
            object.__setattr__(self, "message", sanitize_message(self.message))
        if self.fraction is not None:
            object.__setattr__(self, "fraction", min(1.0, max(0.0, float(self.fraction))))
        if not self.updated_at:
            object.__setattr__(self, "updated_at", now_iso())
        if self.state == FAILED and self.error is None:
            object.__setattr__(self, "error", ProviderErrorPayload.from_error(
                ProviderError(PROVIDER_UNIT_FAILED, "The provider job failed")
            ))

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def advance(self, **changes) -> "JobStatus":
        """Return the next snapshot, enforcing the monotonic rules of §33.2.

        A terminal job never returns to `running`, and `total` may only be set
        once, at or before the first `running` status.
        """
        if self.terminal and changes.get("state", self.state) != self.state:
            raise ProviderError(
                "PROVIDER_RESULT_INVALID",
                f"Job {self.job_id} is terminal in state {self.state!r}",
            )
        if "total" in changes and self.total and changes["total"] != self.total:
            changes.pop("total")
        if "ready" in changes:
            changes["ready"] = max(int(changes["ready"]), self.ready)
        changes.setdefault("updated_at", now_iso())
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "state": self.state,
            "ready": self.ready,
            "total": self.total,
            "fraction": self.fraction,
            "message": self.message,
            "units": [unit.to_dict() for unit in self.units],
            "error": self.error.to_dict() if self.error is not None else None,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JobStatus":
        error = data.get("error")
        return cls(
            job_id=str(data.get("job_id", "")),
            state=str(data.get("state", SUBMITTED)),
            ready=int(data.get("ready", 0)),
            total=int(data.get("total", 0)),
            fraction=data.get("fraction"),
            message=data.get("message"),
            units=tuple(
                UnitResult.from_dict(unit)
                for unit in (data.get("units") or [])
                if isinstance(unit, Mapping)
            ),
            error=(
                ProviderErrorPayload.from_error(ProviderError.from_payload(error))
                if isinstance(error, Mapping)
                else None
            ),
            updated_at=str(data.get("updated_at", "")),
        )


# The per-scene status vocabulary both visual domains actually persist
# (`storyboard/routes.py:390`, `animator/routes.py:365-410`). All five shipped
# `poll()` bodies counted `"complete"`, which neither domain has ever written.
SCENE_DONE = frozenset({"ready", "done"})
SCENE_FAILED = frozenset({"error", "failed"})

# `gemini_ws.py:396-398` writes a job-level completion marker into the per-scene
# map under key "-1". It is not a unit: counting it inflated both `total` and
# `ready`, which every legacy counter excludes by hand (`routes.py:389-391`).
SCENE_SENTINEL_KEY = "-1"


def status_from_scenes(job_id: str, scenes: Mapping[str, Any]) -> JobStatus:
    """Derive a `JobStatus` from a persisted per-scene status map.

    One definition for both visual domains, so the two `poll()` bodies cannot
    disagree about what "done" means — and so §33.2's rule that zero produced
    units can never be `succeeded` is applied in exactly one place.
    """
    entries = [
        entry if isinstance(entry, Mapping) else {}
        for key, entry in (scenes or {}).items()
        if str(key) != SCENE_SENTINEL_KEY
    ]
    total = len(entries)
    ready = sum(1 for entry in entries if entry.get("status") in SCENE_DONE)
    failed = sum(1 for entry in entries if entry.get("status") in SCENE_FAILED)

    if not total or ready + failed < total:
        state = RUNNING
    elif ready == 0:
        state = FAILED
    elif failed:
        state = PARTIAL
    else:
        state = SUCCEEDED
    return JobStatus(
        job_id=job_id,
        state=state,
        ready=ready,
        total=total,
        fraction=(ready + failed) / total if total else 0.0,
        error=(
            ProviderErrorPayload.from_error(ProviderError(
                PROVIDER_UNIT_FAILED, f"All {total} units failed"
            ))
            if state == FAILED
            else None
        ),
    )


def unknown_job_status(job_id: str) -> JobStatus:
    """The status of a job the provider has no record of.

    The pre-11.4 dataclasses answered the provider-defined string `"unknown"`,
    which no caller could branch on: a poll loop treated it as neither done nor
    failed and waited out the whole deadline. `state` is a closed vocabulary now
    (§33.1) and a job the provider cannot find will never complete, so it is
    `failed` with `PROVIDER_NOT_FOUND` — the rule §33.4 already applies to a
    rehydrated job whose provider is gone.
    """
    return JobStatus(
        job_id=job_id,
        state=FAILED,
        error=ProviderErrorPayload.from_error(ProviderError(
            PROVIDER_NOT_FOUND, "The provider has no record of this job"
        )),
    )


def terminal_outcome(status: JobStatus, *, domain: str = "", provider_id: str = "") -> str:
    """Map a terminal job state onto its one invocation outcome (§33.2).

    Returns `succeeded` or `partial`; raises for the three failure states, so a
    caller never has to re-derive the mapping.
    """
    if not status.terminal:
        raise ProviderError(
            "PROVIDER_RESULT_INVALID",
            f"Job {status.job_id} is not terminal ({status.state})",
            domain=domain, provider_id=provider_id,
        )
    if status.state == JOB_CANCELLED:
        raise ProviderCancelled(domain=domain, provider_id=provider_id)
    if status.state == TIMED_OUT:
        raise ProviderError(
            PROVIDER_TIMEOUT,
            "The provider job exceeded its deadline",
            retryable=True,
            domain=domain, provider_id=provider_id,
            details=_partial_diagnostic(status),
        )
    if status.state == FAILED:
        error = status.error.as_error() if status.error is not None else None
        raise ProviderError(
            error.code if error else PROVIDER_UNIT_FAILED,
            error.message if error else "The provider job failed",
            retryable=error.retryable if error else False,
            domain=domain, provider_id=provider_id,
            details=_partial_diagnostic(status),
        )
    # Zero produced units can never be `succeeded` (§33.2) — the defect class
    # currently guarded by hand in both visual adapters.
    if status.state == SUCCEEDED and status.units and not any(
        unit.state == "succeeded" for unit in status.units
    ):
        raise ProviderError(
            PROVIDER_UNIT_FAILED,
            f"All {len(status.units)} units failed",
            domain=domain, provider_id=provider_id,
            details=_partial_diagnostic(status),
        )
    return status.state


def _partial_diagnostic(status: JobStatus) -> dict:
    """Units already terminal, preserved as diagnostics on a failed job (§35.3)."""
    return {
        "ready": status.ready,
        "total": status.total,
        "units": [unit.to_dict() for unit in status.units],
    }


@dataclass
class JobRecord:
    """`JobHandle` + last `JobStatus`, the unit of job persistence (§33.4)."""

    handle: JobHandle
    status: JobStatus

    def to_dict(self) -> dict:
        return {"handle": self.handle.to_dict(), "status": self.status.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JobRecord":
        return cls(
            handle=JobHandle.from_dict(data.get("handle") or {}),
            status=JobStatus.from_dict(data.get("status") or {}),
        )


# -- domain aliases (contracts.md §33.1) ------------------------------------
#
# 11.4 keeps thin domain aliases so 14.2/14.3 can diff the migrated shape
# against the old one. They are the *same* classes, not copies: importing
# `SceneResult` from either `base.py` now yields `UnitResult`.

SceneResult = UnitResult


@dataclass(frozen=True)
class JobProgress:
    """The `{ready, total}` shape the SSE frame and the legacy poll loop share."""

    ready: int = 0
    total: int = 0

    def to_dict(self) -> dict:
        return {"ready": self.ready, "total": self.total}


__all__ = [
    "DOMAIN_POLL_INTERVAL_S",
    "FIRST_POLL_DELAY_S",
    "JOB_CANCELLED",
    "JOB_ID_RE",
    "JOB_STATES",
    "JOB_STATE_SET",
    "MAX_CONSECUTIVE_POLL_FAILURES",
    "POLL_JITTER",
    "SCENE_DONE",
    "SCENE_FAILED",
    "SCENE_SENTINEL_KEY",
    "status_from_scenes",
    "PUSH_WATCHDOG_INTERVAL_S",
    "RUNNING",
    "SUBMITTED",
    "TERMINAL_STATES",
    "TIMED_OUT",
    "JobHandle",
    "JobProgress",
    "JobRecord",
    "JobStatus",
    "SceneResult",
    "UnitResult",
    "poll_interval",
    "terminal_outcome",
    "unknown_job_status",
]
