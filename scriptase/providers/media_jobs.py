"""Shared asynchronous media-job orchestration — step 14.1.

One orchestration layer over the Phase 11 job contract (`jobs.py` §33) for
multi-unit submit, poll/callback, progress, per-unit results, retry,
cancellation, timeout, resume/reconciliation, and terminal aggregation.

The service is **media-neutral**: Storyboard and Animator share it without any
domain-specific branches. Domain-only values (poll cadence, default deadline)
come from the frozen tables already in `jobs.py` / `invocation.py`. Providers
own only remote/local generation mechanics; this module owns:

  * the poll loop (first delay, cadence ± jitter, 3-strike poll-failure limit)
  * push-callback correlation and terminal-unit idempotence
  * job persistence / rehydration for restart reconciliation
  * progress emission through `ProviderInvocation.progress`
  * terminal aggregation into a `ProviderResult` (or a raised `ProviderError`)
  * per-unit retry that reuses already-succeeded units (D34)

Public job IDs are whatever the provider returns from `submit()` — the service
never invents a different identity. Legacy storyboard / animator stores keep
using `project_id` as the public key; the record file sits next to the domain
manifest and does not replace it.
"""

from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from loguru import logger

from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.providers.boundary import Deadline, wrap_exception
from scriptase.providers.errors import (
    PROVIDER_NOT_FOUND,
    PROVIDER_UNIT_FAILED,
    ProviderCancelled,
    ProviderError,
    ProviderErrorPayload,
)
from scriptase.providers.invocation import ProviderInvocation
from scriptase.providers.jobs import (
    FIRST_POLL_DELAY_S,
    JOB_CANCELLED,
    MAX_CONSECUTIVE_POLL_FAILURES,
    POLL_JITTER,
    RUNNING,
    SUBMITTED,
    TERMINAL_STATES,
    TIMED_OUT,
    JobHandle,
    JobRecord,
    JobStatus,
    poll_interval,
    terminal_outcome,
)
from scriptase.providers.results import (
    FAILED,
    PARTIAL,
    SUCCEEDED,
    UNIT_FAILED,
    UNIT_SUCCEEDED,
    ProviderResult,
    UnitResult,
    dedupe_refs,
)


# Filename written next to the domain manifest (storyboard.json / grabber_job.json).
# Deliberately separate so legacy public job IDs and status endpoints stay put.
RECORD_FILENAME = "media_job.json"


# -- provider protocol (v2 async shape) -------------------------------------


@runtime_checkable
class AsyncMediaProvider(Protocol):
    """The minimum a provider must implement for the media-job service.

    This is the Provider Contract v2 async shape the visual providers adopt in
    14.2 / 14.3.
    """

    def submit(self, request: Any, invocation: ProviderInvocation) -> JobHandle: ...

    def poll(self, job_id: str, invocation: ProviderInvocation) -> JobStatus: ...

    def cancel_job(self, job_id: str, invocation: ProviderInvocation) -> None: ...


# -- live job + persistence -------------------------------------------------


@dataclass
class LiveJob:
    """In-memory view of one in-flight media job."""

    handle: JobHandle
    status: JobStatus
    record_path: str = ""
    consecutive_poll_failures: int = 0
    # Units already terminal from a prior attempt — reused on retry / resume.
    prior_units: tuple[UnitResult, ...] = ()
    # Condition notified when a push callback lands so the wait loop wakes early.
    event: threading.Event = field(default_factory=threading.Event)


class MediaJobStore:
    """Thread-safe live registry + disk persistence for `JobRecord` (§33.4).

    Live jobs are keyed by the frozen push-correlation tuple
    `(domain, provider_id, project_id, job_id)`. A pushed status whose tuple
    does not match is dropped and warned, never applied (§33.3).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[tuple[str, str, str, str], LiveJob] = {}

    # -- live registry ------------------------------------------------------

    def register(
        self,
        handle: JobHandle,
        status: JobStatus,
        *,
        record_path: str = "",
        prior_units: tuple[UnitResult, ...] = (),
    ) -> LiveJob:
        live = LiveJob(
            handle=handle,
            status=status,
            record_path=record_path,
            prior_units=prior_units,
        )
        with self._lock:
            self._live[handle.correlation] = live
        return live

    def get(self, correlation: tuple[str, str, str, str]) -> LiveJob | None:
        with self._lock:
            return self._live.get(correlation)

    def get_by_job_id(self, job_id: str) -> LiveJob | None:
        with self._lock:
            for live in self._live.values():
                if live.handle.job_id == job_id:
                    return live
        return None

    def drop(self, correlation: tuple[str, str, str, str]) -> None:
        with self._lock:
            self._live.pop(correlation, None)

    def snapshot(self) -> list[LiveJob]:
        with self._lock:
            return list(self._live.values())

    # -- status application (poll + push) -----------------------------------

    def apply_status(
        self,
        correlation: tuple[str, str, str, str],
        incoming: JobStatus,
        *,
        source: str = "poll",
    ) -> JobStatus | None:
        """Merge an incoming status into the live job.

        Returns the new status, or `None` if the correlation does not match a
        live job (push path: drop + warn). Terminal-unit updates are idempotent
        — a duplicate callback for a unit already terminal is ignored (§33.3).
        """
        with self._lock:
            live = self._live.get(correlation)
            if live is None:
                logger.warning(
                    "[media_jobs] dropping {} status for unknown correlation {}",
                    source,
                    correlation,
                )
                return None
            if live.status.terminal:
                # A terminal job never returns to running; duplicates are no-ops.
                return live.status
            merged_units = _merge_units_idempotent(live.status.units, incoming.units)
            if live.prior_units:
                merged_units = _merge_units_idempotent(live.prior_units, merged_units)
            # Ready is derived from the merged unit set so a retry that only
            # reports the re-requested units cannot clobber prior successes.
            ready = sum(1 for unit in merged_units if unit.state == UNIT_SUCCEEDED)
            if not merged_units:
                ready = max(incoming.ready, live.status.ready)
            # Terminal state also re-derived when units are present, so a provider
            # that claims `succeeded` with zero produced units cannot pass.
            state = incoming.state
            if merged_units and state in TERMINAL_STATES - {JOB_CANCELLED, TIMED_OUT}:
                failed = sum(1 for unit in merged_units if unit.state == UNIT_FAILED)
                produced = ready
                pending = len(merged_units) - produced - failed
                if pending <= 0:
                    if produced == 0:
                        state = FAILED
                    elif failed:
                        state = PARTIAL
                    else:
                        state = SUCCEEDED
            changes: dict[str, Any] = {
                "state": state,
                "ready": ready,
                "units": merged_units,
                "message": incoming.message,
                "fraction": incoming.fraction,
                "error": incoming.error,
            }
            if incoming.total:
                changes["total"] = incoming.total
            elif merged_units and not live.status.total:
                changes["total"] = len(merged_units)
            try:
                live.status = live.status.advance(**changes)
            except ProviderError:
                # Incoming tried an illegal transition (e.g. total rewrite after
                # terminal). Keep the current status; do not raise through push.
                if source == "poll":
                    raise
                logger.warning(
                    "[media_jobs] illegal {} transition ignored for {}",
                    source,
                    correlation,
                )
                return live.status
            # Only a *push* needs to wake the wait loop — poll runs on the same
            # thread. Setting the event on every poll made the next sleep see
            # `event.is_set()` and skip forever, spinning the poll loop.
            if source == "push":
                live.event.set()
            return live.status

    # -- disk ---------------------------------------------------------------

    def save(self, handle: JobHandle, status: JobStatus, path: str) -> None:
        """Persist `JobHandle` + last `JobStatus` via atomic write (§33.4)."""
        if not path:
            return
        record = JobRecord(handle=handle, status=status)
        payload = record.to_dict()
        # §31.2: the record must not carry absolute paths / credentials. The
        # egress validator is applied by callers of the public API; here we
        # simply write the sanitized job types (messages already sanitized).
        safe_json_write(path, payload, indent=2)

    def load(self, path: str) -> JobRecord | None:
        if not path or not os.path.isfile(path):
            return None
        try:
            data = safe_json_read(path)
        except (OSError, ValueError) as exc:
            logger.warning("[media_jobs] failed to read job record {}: {}", path, exc)
            return None
        if not isinstance(data, Mapping):
            return None
        try:
            return JobRecord.from_dict(data)
        except ProviderError as exc:
            logger.warning("[media_jobs] invalid job record {}: {}", path, exc.message)
            return None

    def rehydrate(
        self,
        path: str,
        *,
        provider_registered: bool = True,
    ) -> JobRecord | None:
        """Load a persisted job and register it live when still running.

        A job whose provider is no longer registered is marked `failed` with
        `PROVIDER_NOT_FOUND` rather than being retried forever (§33.4).
        """
        record = self.load(path)
        if record is None:
            return None
        if not provider_registered and not record.status.terminal:
            failed = JobStatus(
                job_id=record.handle.job_id,
                state=FAILED,
                ready=record.status.ready,
                total=record.status.total,
                units=record.status.units,
                error=ProviderErrorPayload.from_error(
                    ProviderError(
                        PROVIDER_NOT_FOUND,
                        "The provider is no longer registered",
                        domain=record.handle.domain,
                        provider_id=record.handle.provider_id,
                    )
                ),
            )
            record = JobRecord(handle=record.handle, status=failed)
            self.save(record.handle, record.status, path)
            return record
        if not record.status.terminal:
            self.register(record.handle, record.status, record_path=path)
        return record


# Process-wide default store — Storyboard and Animator share one registry so a
# cross-provider push cannot be applied by accident to the wrong domain.
_DEFAULT_STORE = MediaJobStore()


def default_store() -> MediaJobStore:
    return _DEFAULT_STORE


def record_path_for(output_dir: str) -> str:
    """Standard record path next to the domain manifest (§33.4)."""
    return os.path.join(output_dir, RECORD_FILENAME)


# -- unit merge helpers -----------------------------------------------------


def _unit_terminal(state: str) -> bool:
    return state in {UNIT_SUCCEEDED, UNIT_FAILED, "skipped", "cancelled"}


def _merge_units_idempotent(
    existing: tuple[UnitResult, ...] | list[UnitResult],
    incoming: tuple[UnitResult, ...] | list[UnitResult],
) -> tuple[UnitResult, ...]:
    """Merge by `unit_index`. A terminal existing unit is never overwritten.

    This is the rule that makes a duplicate callback for an already-ready scene
    a no-op (D32). Inbound push validation and body bounds live in
    `providers_common.transports.callbacks` (step 14.4).
    """
    by_index: dict[int, UnitResult] = {unit.unit_index: unit for unit in existing}
    for unit in incoming:
        current = by_index.get(unit.unit_index)
        if current is not None and _unit_terminal(current.state):
            continue
        by_index[unit.unit_index] = unit
    return tuple(by_index[index] for index in sorted(by_index))


def merge_prior_units(
    prior: tuple[UnitResult, ...] | list[UnitResult],
    fresh: tuple[UnitResult, ...] | list[UnitResult],
) -> tuple[UnitResult, ...]:
    """Restart / retry reconciliation: succeeded priors win, then fresh results.

    Re-requests only cover units not already terminal-succeeded; this helper
    rebuilds the full ordered unit list the caller originally requested (D34).
    """
    by_index: dict[int, UnitResult] = {}
    for unit in prior:
        if unit.state == UNIT_SUCCEEDED:
            by_index[unit.unit_index] = unit
    for unit in fresh:
        if unit.unit_index in by_index and by_index[unit.unit_index].state == UNIT_SUCCEEDED:
            continue
        by_index[unit.unit_index] = unit
    # Preserve any prior non-succeeded that the retry never re-attempted.
    for unit in prior:
        by_index.setdefault(unit.unit_index, unit)
    return tuple(by_index[index] for index in sorted(by_index))


def units_needing_retry(
    units: tuple[UnitResult, ...] | list[UnitResult],
) -> list[int]:
    """Indices not in a terminal succeeded state — the set a retry re-requests."""
    return [unit.unit_index for unit in units if unit.state != UNIT_SUCCEEDED]


def filter_request_units(request: Mapping[str, Any] | list, indices: list[int]) -> Any:
    """Strip a multi-unit request down to the units a retry still needs.

    Accepts either a bare unit list or a mapping with a `units` / `scenes` key
    so both storyboard and animator request shapes work without a domain branch.
    """
    wanted = set(indices)
    if isinstance(request, list):
        return [
            item
            for item in request
            if _request_unit_index(item) in wanted
        ]
    if not isinstance(request, Mapping):
        return request
    payload = dict(request)
    for key in ("units", "scenes"):
        if key in payload and isinstance(payload[key], list):
            payload[key] = [
                item
                for item in payload[key]
                if _request_unit_index(item) in wanted
            ]
            break
    return payload


def _request_unit_index(item: Any) -> int:
    if isinstance(item, Mapping):
        for key in ("unit_index", "index", "scene"):
            if key in item:
                return int(item[key])
    for key in ("unit_index", "index", "scene"):
        value = getattr(item, key, None)
        if value is not None and not callable(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return -1


# -- result construction ----------------------------------------------------


def result_from_status(
    status: JobStatus,
    invocation: ProviderInvocation,
    *,
    require_all: bool = False,
) -> ProviderResult:
    """Map a terminal job onto a `ProviderResult` or raise (§33.2 / §31.5).

    Zero produced units can never be success. `require_all=True` upgrades a
    `partial` outcome into a raised failure (opt-in; default off per §31.5).
    """
    if not status.terminal:
        raise ProviderError(
            "PROVIDER_RESULT_INVALID",
            f"Job {status.job_id} is not terminal ({status.state})",
            domain=invocation.domain,
            provider_id=invocation.provider_id,
        )

    # Timeout / cancel keep their own codes even when no unit succeeded — the
    # partial diagnostic rides in `details` (§35.3). All-failed is the residual.
    if status.state not in {TIMED_OUT, JOB_CANCELLED} and status.units:
        produced = sum(1 for unit in status.units if unit.state == UNIT_SUCCEEDED)
        if produced == 0:
            raise ProviderError(
                PROVIDER_UNIT_FAILED,
                f"All {len(status.units)} units failed",
                domain=invocation.domain,
                provider_id=invocation.provider_id,
                details={
                    "ready": 0,
                    "total": status.total or len(status.units),
                    "units": [unit.to_dict() for unit in status.units],
                },
            )

    outcome = terminal_outcome(
        status, domain=invocation.domain, provider_id=invocation.provider_id
    )

    if require_all and outcome == PARTIAL:
        raise ProviderError(
            PROVIDER_UNIT_FAILED,
            f"Only {status.ready}/{status.total} units succeeded",
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            details={
                "ready": status.ready,
                "total": status.total,
                "units": [unit.to_dict() for unit in status.units],
            },
        )

    units = list(status.units)
    refs = dedupe_refs(ref for unit in units for ref in unit.artifact_refs)
    result = ProviderResult(
        domain=invocation.domain,
        provider_id=invocation.provider_id,
        status=outcome,
        payload={"ready": status.ready, "total": status.total},
        artifact_refs=refs,
        units=units,
        job=status,
    )
    if outcome == PARTIAL:
        failed = sum(1 for unit in units if unit.state == UNIT_FAILED)
        result.warn(
            "PARTIAL_UNITS",
            f"{status.ready}/{status.total or len(units)} units succeeded"
            + (f", {failed} failed" if failed else ""),
        )
    return result


# -- the service ------------------------------------------------------------


class MediaJobService:
    """Orchestrate multi-unit async media generation for any visual domain.

    Construct once per process (or once per test with a private store). Call
    `run()` for a fresh submit+poll, `resume()` after a process restart, and
    `apply_callback()` from a push transport. Domain identity is taken only from
    the `ProviderInvocation` — there are no storyboard/animator branches here.
    """

    def __init__(
        self,
        store: MediaJobStore | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.store = store if store is not None else default_store()
        self._clock = clock
        self._sleeper = sleeper
        self._rng = rng if rng is not None else random.Random()

    # -- public entry points ------------------------------------------------

    def run(
        self,
        provider: Any,
        request: Any,
        invocation: ProviderInvocation,
        *,
        push: bool = False,
        prior_units: tuple[UnitResult, ...] | list[UnitResult] = (),
        require_all: bool = False,
        record_path: str | None = None,
    ) -> ProviderResult:
        """Submit a job, poll/push until terminal, return the envelope.

        Raises `ProviderCancelled`, `ProviderError(PROVIDER_TIMEOUT)`, or a
        unit/provider failure. Never returns success when every unit failed.
        """
        path = record_path if record_path is not None else record_path_for(invocation.output_dir)
        prior = tuple(prior_units or ())

        handle = self._submit(provider, request, invocation)
        initial = JobStatus(
            job_id=handle.job_id,
            state=SUBMITTED,
            total=_request_total(request, prior),
            units=prior if prior else (),
            ready=sum(1 for unit in prior if unit.state == UNIT_SUCCEEDED),
        )
        live = self.store.register(
            handle, initial, record_path=path, prior_units=prior
        )
        self.store.save(handle, live.status, path)
        invocation.progress(
            ready=live.status.ready,
            total=live.status.total or None,
            message="submitted",
            state=SUBMITTED,
        )

        # Wire cancel → provider.cancel_job once, best-effort.
        self._bind_cancel(provider, handle, invocation)

        try:
            final = self._await_terminal(provider, handle, invocation, push=push)
            return result_from_status(final, invocation, require_all=require_all)
        finally:
            self.store.drop(handle.correlation)
            invocation.progress.flush()

    def resume(
        self,
        provider: Any | None,
        invocation: ProviderInvocation,
        *,
        record_path: str | None = None,
        push: bool = False,
        require_all: bool = False,
        provider_registered: bool | None = None,
    ) -> ProviderResult:
        """Rehydrate a persisted job and continue polling (§33.4, D33).

        `provider=None` or `provider_registered=False` marks a still-running job
        as `failed` with `PROVIDER_NOT_FOUND` rather than hanging forever.
        """
        path = record_path if record_path is not None else record_path_for(invocation.output_dir)
        registered = (
            provider_registered
            if provider_registered is not None
            else provider is not None
        )
        record = self.store.rehydrate(path, provider_registered=registered)
        if record is None:
            raise ProviderError(
                PROVIDER_NOT_FOUND,
                "No media job record was found to resume",
                domain=invocation.domain,
                provider_id=invocation.provider_id,
            )
        if record.status.terminal:
            return result_from_status(record.status, invocation, require_all=require_all)
        if provider is None:
            # rehydrate already flipped the record when provider_registered=False;
            # if the caller passed None but left the flag True, fail here.
            failed = JobStatus(
                job_id=record.handle.job_id,
                state=FAILED,
                ready=record.status.ready,
                total=record.status.total,
                units=record.status.units,
                error=ProviderErrorPayload.from_error(
                    ProviderError(
                        PROVIDER_NOT_FOUND,
                        "The provider is no longer registered",
                        domain=record.handle.domain,
                        provider_id=record.handle.provider_id,
                    )
                ),
            )
            self.store.save(record.handle, failed, path)
            return result_from_status(failed, invocation, require_all=require_all)

        live = self.store.get(record.handle.correlation)
        if live is None:
            live = self.store.register(
                record.handle, record.status, record_path=path
            )
        self._bind_cancel(provider, record.handle, invocation)
        try:
            final = self._await_terminal(
                provider, record.handle, invocation, push=push
            )
            return result_from_status(final, invocation, require_all=require_all)
        finally:
            self.store.drop(record.handle.correlation)
            invocation.progress.flush()

    def retry(
        self,
        provider: Any,
        request: Any,
        invocation: ProviderInvocation,
        prior_status: JobStatus,
        *,
        push: bool = False,
        require_all: bool = False,
        record_path: str | None = None,
    ) -> ProviderResult:
        """Re-request only units not already succeeded; reuse the rest (D34)."""
        prior = tuple(prior_status.units or ())
        needed = units_needing_retry(prior)
        if not needed:
            return result_from_status(prior_status, invocation, require_all=require_all)
        filtered = filter_request_units(request, needed)
        return self.run(
            provider,
            filtered,
            invocation,
            push=push,
            prior_units=tuple(u for u in prior if u.state == UNIT_SUCCEEDED),
            require_all=require_all,
            record_path=record_path,
        )

    def apply_callback(
        self,
        correlation: tuple[str, str, str, str],
        status: JobStatus | Mapping[str, Any],
    ) -> bool:
        """Apply a pushed status. Returns True when applied, False when dropped.

        Duplicate status for a unit already terminal is idempotent (§33.3).
        Callers that receive raw HTTP/WS bodies should go through
        `transports.callbacks.CallbackIntake` first so oversized, malformed,
        and cross-provider pushes never reach this method.
        """
        if isinstance(status, Mapping):
            status = JobStatus.from_dict(status)
        applied = self.store.apply_status(correlation, status, source="push")
        if applied is None:
            return False
        live = self.store.get(correlation)
        if live is not None and live.record_path:
            self.store.save(live.handle, applied, live.record_path)
        return True

    # -- internals ----------------------------------------------------------

    def _submit(
        self, provider: Any, request: Any, invocation: ProviderInvocation
    ) -> JobHandle:
        try:
            handle = provider.submit(request, invocation)
        except ProviderCancelled:
            raise
        except ProviderError:
            raise
        except BaseException as exc:
            raise wrap_exception(
                exc,
                domain=invocation.domain,
                provider_id=invocation.provider_id,
                log=invocation.log,
            ) from None
        if not isinstance(handle, JobHandle):
            raise ProviderError(
                "PROVIDER_RESULT_INVALID",
                "Provider submit() must return a JobHandle",
                domain=invocation.domain,
                provider_id=invocation.provider_id,
            )
        # Fill identity the provider may have left blank so correlation works.
        if not handle.domain or not handle.provider_id or not handle.project_id:
            handle = JobHandle(
                job_id=handle.job_id,
                domain=handle.domain or invocation.domain,
                provider_id=handle.provider_id or invocation.provider_id,
                project_id=handle.project_id or invocation.project_id,
                invocation_id=handle.invocation_id or invocation.invocation_id,
                created_at=handle.created_at,
            )
        return handle

    def _bind_cancel(
        self, provider: Any, handle: JobHandle, invocation: ProviderInvocation
    ) -> None:
        cancel_job = getattr(provider, "cancel_job", None)
        if not callable(cancel_job):
            return

        def _on_cancel() -> None:
            try:
                cancel_job(handle.job_id, invocation)
            except Exception as exc:  # best-effort; never raise through cancel
                logger.warning(
                    "[media_jobs] cancel_job raised for {}: {}", handle.job_id, exc
                )
            # Reflect cancellation on the live record so waiters observe it.
            cancelled = JobStatus(
                job_id=handle.job_id,
                state=JOB_CANCELLED,
                ready=0,
                total=0,
            )
            live = self.store.get(handle.correlation)
            if live is not None and not live.status.terminal:
                try:
                    live.status = live.status.advance(
                        state=JOB_CANCELLED,
                        ready=live.status.ready,
                        total=live.status.total,
                        units=live.status.units,
                    )
                except ProviderError:
                    pass
                live.event.set()
                if live.record_path:
                    self.store.save(handle, live.status, live.record_path)

        invocation.cancel.on_cancel(_on_cancel)

    def _await_terminal(
        self,
        provider: Any,
        handle: JobHandle,
        invocation: ProviderInvocation,
        *,
        push: bool,
    ) -> JobStatus:
        deadline = Deadline(invocation.deadline, clock=self._clock)
        first = True
        last_status: JobStatus | None = None

        while True:
            invocation.cancel.raise_if_cancelled()

            live = self.store.get(handle.correlation)
            if live is not None and live.status.terminal:
                return live.status

            # Sleep first (FIRST_POLL_DELAY_S), then poll — a delayed push during
            # the sleep wakes us via live.event so we don't wait a full interval.
            interval = (
                FIRST_POLL_DELAY_S
                if first
                else poll_interval(invocation.domain, push=push)
            )
            first = False
            jitter = 1.0 + self._rng.uniform(-POLL_JITTER, POLL_JITTER)
            wait_s = max(0.0, interval * jitter)
            wait_s = min(wait_s, max(0.0, deadline.remaining()))
            self._interruptible_sleep(wait_s, handle, invocation, deadline)

            invocation.cancel.raise_if_cancelled()
            if deadline.expired():
                return self._timeout(handle, last_status, invocation)

            # A push may have completed the job while we slept.
            live = self.store.get(handle.correlation)
            if live is not None and live.status.terminal:
                return live.status
            if live is not None:
                live.event.clear()

            status = self._poll_once(provider, handle, invocation)
            if status is None:
                # Consecutive poll failures exhausted → already failed & saved.
                live = self.store.get(handle.correlation)
                if live is not None and live.status.terminal:
                    return live.status
                continue

            last_status = status
            applied = self.store.apply_status(
                handle.correlation, status, source="poll"
            )
            if applied is None:
                # Job was dropped under us — treat the polled status as truth.
                applied = status
            live = self.store.get(handle.correlation)
            if live is not None and live.record_path:
                self.store.save(handle, applied, live.record_path)

            invocation.progress(
                ready=applied.ready,
                total=applied.total or None,
                fraction=applied.fraction,
                message=applied.message,
                state=applied.state if applied.terminal else RUNNING,
            )

            if applied.terminal:
                return applied

            if deadline.expired():
                return self._timeout(handle, applied, invocation)

    def _interruptible_sleep(
        self,
        seconds: float,
        handle: JobHandle,
        invocation: ProviderInvocation,
        deadline: Deadline,
    ) -> None:
        """Sleep up to `seconds`, waking on cancel, push, or deadline.

        Time passage goes through the injected `sleeper` so tests can drive a
        fake clock without real wall waits. A push sets `live.event` and is
        observed on the next loop iteration (or immediately if already set).
        """
        if seconds <= 0:
            return
        invocation.cancel.raise_if_cancelled()
        if deadline.expired():
            return
        live = self.store.get(handle.correlation)
        if live is not None and (live.status.terminal or live.event.is_set()):
            return
        self._sleeper(min(seconds, max(0.0, deadline.remaining())))

    def _poll_once(
        self,
        provider: Any,
        handle: JobHandle,
        invocation: ProviderInvocation,
    ) -> JobStatus | None:
        """One poll attempt. Returns None when a transient failure was absorbed."""
        live = self.store.get(handle.correlation)
        try:
            status = provider.poll(handle.job_id, invocation)
        except ProviderCancelled:
            raise
        except ProviderError as exc:
            return self._record_poll_failure(handle, live, invocation, exc)
        except BaseException as exc:
            wrapped = wrap_exception(
                exc,
                domain=invocation.domain,
                provider_id=invocation.provider_id,
                log=invocation.log,
            )
            return self._record_poll_failure(handle, live, invocation, wrapped)

        if not isinstance(status, JobStatus):
            raise ProviderError(
                "PROVIDER_RESULT_INVALID",
                "Provider poll() must return a JobStatus",
                domain=invocation.domain,
                provider_id=invocation.provider_id,
            )
        if live is not None:
            live.consecutive_poll_failures = 0
        return status

    def _record_poll_failure(
        self,
        handle: JobHandle,
        live: LiveJob | None,
        invocation: ProviderInvocation,
        exc: ProviderError,
    ) -> JobStatus | None:
        if live is None:
            raise exc
        live.consecutive_poll_failures += 1
        invocation.log.warning(
            "poll failed",
            consecutive=live.consecutive_poll_failures,
            code=exc.code,
        )
        if live.consecutive_poll_failures < MAX_CONSECUTIVE_POLL_FAILURES:
            return None
        failed = live.status.advance(
            state=FAILED,
            error=ProviderErrorPayload.from_error(
                ProviderError(
                    exc.code,
                    "The provider poll failed repeatedly",
                    retryable=exc.retryable,
                    domain=invocation.domain,
                    provider_id=invocation.provider_id,
                    details={
                        "ready": live.status.ready,
                        "total": live.status.total,
                        "units": [unit.to_dict() for unit in live.status.units],
                        "consecutive_poll_failures": live.consecutive_poll_failures,
                    },
                )
            ),
        )
        live.status = failed
        live.event.set()
        if live.record_path:
            self.store.save(handle, failed, live.record_path)
        return failed

    def _timeout(
        self,
        handle: JobHandle,
        last: JobStatus | None,
        invocation: ProviderInvocation,
    ) -> JobStatus:
        """Mark the job timed_out, preserving any units already terminal (§35.3)."""
        live = self.store.get(handle.correlation)
        base = last or (live.status if live is not None else JobStatus(job_id=handle.job_id))
        try:
            timed = base.advance(state=TIMED_OUT) if not base.terminal else base
        except ProviderError:
            timed = JobStatus(
                job_id=handle.job_id,
                state=TIMED_OUT,
                ready=base.ready,
                total=base.total,
                units=base.units,
                message=base.message,
            )
        if live is not None:
            live.status = timed
            live.event.set()
            if live.record_path:
                self.store.save(handle, timed, live.record_path)
        invocation.progress(
            ready=timed.ready,
            total=timed.total or None,
            state=TIMED_OUT,
            message="timed out",
        )
        return timed


def _request_total(
    request: Any, prior: tuple[UnitResult, ...]
) -> int:
    """Best-effort total for the initial status; poll may raise it once later.

    Accepts dict/list requests and the domain pydantic models (StoryboardRequest /
    AnimatorRequest) so progress events after submit already carry the real unit
    count instead of `0` until the first poll.
    """
    indices: list[int] = [unit.unit_index for unit in prior]
    explicit = _request_unit_count(request)
    if explicit is not None:
        return max(explicit, len(indices))
    if isinstance(request, list):
        indices.extend(_request_unit_index(item) for item in request)
    else:
        for collection in _request_unit_collections(request):
            indices.extend(_request_unit_index(item) for item in collection)
    indices = [index for index in indices if index >= 0]
    if not indices:
        if isinstance(request, list):
            return len(request)
        return 0
    # 0-based dense indices → max+1; sparse still gives a safe upper bound.
    return max(len(indices), max(indices) + 1)


def _request_unit_count(request: Any) -> int | None:
    """Return an explicit unit count when the request declares one."""
    if isinstance(request, Mapping) and "unit_count" in request:
        return int(request["unit_count"])
    count = getattr(request, "unit_count", None)
    if callable(count):
        try:
            count = count()
        except TypeError:
            count = None
    if isinstance(count, int) and not isinstance(count, bool):
        return count
    return None


def _request_unit_collections(request: Any) -> list[list[Any]]:
    """Yield unit/scene lists from a mapping or a domain request model."""
    collections: list[list[Any]] = []
    if isinstance(request, Mapping):
        for key in ("units", "scenes"):
            value = request.get(key)
            if isinstance(value, list):
                collections.append(value)
        return collections
    for key in ("units", "scenes"):
        value = getattr(request, key, None)
        if isinstance(value, list):
            collections.append(value)
    return collections


# -- legacy bridge (public job IDs preserved) -------------------------------
#
# Storyboard keys jobs by `project_id` and persists `storyboard.json`.
# Animator keys jobs by `project_id` and persists `grabber_job.json`.
# The media-job record sits *beside* those files; these helpers let 14.2/14.3
# keep the same public IDs and the same `{ready, total}` progress shape while
# the orchestration itself stays domain-free.


def _legacy_ref(value: Any) -> str:
    """Turn a legacy `/output/...` web path into a managed relative ref (§31.2).

    Persisted job records must not carry absolute paths; the legacy stores write
    browser-facing `/output/<domain>/...` strings, which is what the storyboard
    adapter already strips by hand before recording artifacts.
    """
    ref = str(value or "").replace("\\", "/")
    return ref.removeprefix("/output/").removeprefix("output/").lstrip("/")


def legacy_progress(status: JobStatus) -> dict[str, int]:
    """The `{ready, total}` shape both SSE frames and legacy status routes share."""
    return {"ready": int(status.ready), "total": int(status.total)}


# Job-level completion markers the legacy stores write. Only "done" is produced
# today; "completed" is carried over from the animator loop, which accepted it,
# so an older manifest on disk still reads as finished.
JOB_DONE_STATES = frozenset({"done", "completed"})


def settled_state(units: tuple[UnitResult, ...], total: int) -> str:
    """The terminal state of a store that declared itself done (§33.2).

    A legacy store may write `status: "done"` over a per-scene map that still
    has pending entries — the extension does exactly that. Those units never
    arrive, so the outcome settles from what was produced rather than waiting
    out the deadline. Zero produced units still cannot become success.
    """
    produced = sum(1 for unit in units if unit.state == UNIT_SUCCEEDED)
    failed = sum(1 for unit in units if unit.state == UNIT_FAILED)
    if produced == 0:
        return FAILED
    if failed or produced < total:
        return PARTIAL
    return SUCCEEDED


def units_from_legacy_scenes(
    scene_statuses: Mapping[str, Any],
) -> tuple[UnitResult, ...]:
    """Map a legacy `scene_statuses` dict onto media-neutral `UnitResult`s.

    Accepts both storyboard (`ready`/`done`/`error`/`failed`) and animator
    (`ready`/`error`) vocabularies so adapters do not need a domain branch.
    """
    from scriptase.providers.jobs import (
        SCENE_DONE,
        SCENE_FAILED,
        SCENE_SENTINEL_KEY,
    )

    units: list[UnitResult] = []
    for key, entry in sorted(
        (scene_statuses or {}).items(),
        key=lambda item: int(item[0]) if str(item[0]).lstrip("-").isdigit() else 0,
    ):
        if str(key) == SCENE_SENTINEL_KEY:
            continue
        if not isinstance(entry, Mapping):
            continue
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        raw = str(entry.get("status") or "pending")
        if raw in SCENE_DONE:
            refs: list[str] = []
            for field_name in ("local_path", "local_files", "path"):
                value = entry.get(field_name)
                if isinstance(value, str) and value:
                    refs.append(_legacy_ref(value))
                    break
                if isinstance(value, list):
                    refs.extend(_legacy_ref(item) for item in value if item)
                    break
            refs = [ref for ref in refs if ref]
            units.append(
                UnitResult(
                    unit_index=index,
                    state=UNIT_SUCCEEDED,
                    artifact_refs=tuple(dedupe_refs(refs)),
                )
            )
        elif raw in SCENE_FAILED:
            message = entry.get("error") or entry.get("message") or "Unit failed"
            if not isinstance(message, str):
                message = "Unit failed"
            units.append(
                UnitResult(
                    unit_index=index,
                    state=UNIT_FAILED,
                    error=ProviderErrorPayload.from_error(
                        ProviderError(PROVIDER_UNIT_FAILED, message)
                    ),
                )
            )
        # pending / generating / waiting → omitted; the service treats missing
        # units as not-yet-attempted until the provider reports them.
    return tuple(units)


__all__ = [
    "JOB_DONE_STATES",
    "RECORD_FILENAME",
    "AsyncMediaProvider",
    "LiveJob",
    "MediaJobService",
    "MediaJobStore",
    "default_store",
    "filter_request_units",
    "legacy_progress",
    "merge_prior_units",
    "record_path_for",
    "result_from_status",
    "settled_state",
    "units_from_legacy_scenes",
    "units_needing_retry",
]
