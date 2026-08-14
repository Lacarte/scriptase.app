"""The provider invocation context — step 11.4.

Implements contracts.md §30: one frozen `ProviderInvocation` passed to every
domain invocation, plus the three collaborators it always carries.
`cancel`, `progress`, and `log` are **never `None`** (§30.1), so a provider never
writes the `stop = context_value(context, "stop_requested"); if stop and stop():`
guard the two visual adapters carry today.

The context is a provider's only access to caller state: no Flask, no
`flask.request`, no `os.environ`, no globals.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from loguru import logger

from scriptase.providers.errors import ProviderCancelled
from scriptase.providers.validation import sanitize_message


# §30.4: at most one emitted progress event per second per invocation, so a
# per-scene provider cannot flood the bounded 1000-event SSE ring.
PROGRESS_MIN_INTERVAL_S = 1.0
PROGRESS_MESSAGE_MAX = 200

# §35.3 domain deadlines, taken from today's values. `deadline_s=None` on an
# invocation means "use the domain default".
DOMAIN_DEADLINE_S = {
    "script": 300.0,
    "scene_director": 600.0,
    "tts": 900.0,
    "image": 1800.0,
    "video": 7200.0,
}
DEFAULT_DEADLINE_S = 900.0


def domain_deadline(domain: str) -> float:
    """The platform-owned default deadline for a domain (§35.3)."""
    from scriptase.providers.domains import canonical_domain

    return DOMAIN_DEADLINE_S.get(canonical_domain(domain), DEFAULT_DEADLINE_S)


# -- cancellation (contracts.md §30.3) --------------------------------------


class CancellationToken:
    """Cooperative cancellation over the scheduler's existing stop callable.

    A wrapper, not a new mechanism: no thread is killed and no process is
    signalled. `on_cancel` callbacks run once, on the thread that first observes
    cancellation, because the scheduler exposes only `threading.Event.is_set` as
    a callable and there is no hook on the thread that calls `Event.set`.
    """

    def __init__(self, is_cancelled: Callable[[], bool] | None = None):
        self._probe = is_cancelled
        self._callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._fired = False
        self._latched = False

    def is_cancelled(self) -> bool:
        if self._latched:
            return True
        if self._probe is None:
            return False
        try:
            flagged = bool(self._probe())
        except Exception as exc:  # a broken probe must not fail the invocation
            logger.warning("[invocation] cancellation probe raised: {}", exc)
            return False
        if flagged:
            # Latch: cancellation is monotonic, and re-probing after the
            # scheduler has torn the event down must not un-cancel the call.
            self._latched = True
            self._fire()
        return flagged

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise ProviderCancelled()

    def on_cancel(self, callback: Callable[[], None]) -> None:
        """Register a best-effort, idempotent cancellation callback."""
        if not callable(callback):
            return
        with self._lock:
            already = self._fired
            if not already:
                self._callbacks.append(callback)
        if already:
            self._run(callback)

    def _fire(self) -> None:
        with self._lock:
            if self._fired:
                return
            self._fired = True
            pending = list(self._callbacks)
            self._callbacks.clear()
        for callback in pending:
            self._run(callback)

    @staticmethod
    def _run(callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:
            # Callbacks must not block or raise; exceptions are logged and
            # swallowed (§30.3).
            logger.warning("[invocation] on_cancel callback raised: {}", exc)


NULL_CANCELLATION = CancellationToken()


# -- progress (contracts.md §30.4) ------------------------------------------


@dataclass(frozen=True)
class ProgressEvent:
    """One normalized, emitted progress observation."""

    ready: int | None = None
    total: int | None = None
    fraction: float | None = None
    message: str | None = None
    unit_index: int | None = None
    state: str | None = None

    def to_dict(self) -> dict:
        return {
            key: value
            for key, value in (
                ("ready", self.ready),
                ("total", self.total),
                ("fraction", self.fraction),
                ("message", self.message),
                ("unit_index", self.unit_index),
                ("state", self.state),
            )
            if value is not None
        }


class ProgressReporter:
    """Advisory, lossy, rate-limited progress (§30.4).

    Dropping a call never changes the outcome, and the reporter never raises.
    `ready` is monotonic non-decreasing; `total` may only be set once after the
    first report. The last value before a terminal state is always emitted.
    """

    def __init__(
        self,
        sink: Callable[[ProgressEvent], None] | None = None,
        *,
        min_interval_s: float = PROGRESS_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        secrets: Any = (),
    ):
        self._sink = sink
        self._min_interval_s = max(0.0, min_interval_s)
        self._clock = clock
        self._secrets = set(secrets or ())
        self._lock = threading.Lock()
        self._ready: int | None = None
        self._total: int | None = None
        self._last_emit: float | None = None
        self._pending: ProgressEvent | None = None

    def __call__(
        self,
        *,
        ready: int | None = None,
        total: int | None = None,
        fraction: float | None = None,
        message: str | None = None,
        unit_index: int | None = None,
        state: str | None = None,
    ) -> None:
        try:
            event = self._normalize(ready, total, fraction, message, unit_index, state)
        except Exception as exc:
            logger.debug("[invocation] progress normalization failed: {}", exc)
            return
        if event is None:
            return
        terminal = state in {"succeeded", "partial", "failed", "cancelled", "timed_out"}
        self._maybe_emit(event, force=terminal)

    def flush(self) -> None:
        """Emit the coalesced value held back by rate limiting, if any."""
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is not None:
            self._emit(pending)

    # -- internals ---------------------------------------------------------

    def _normalize(self, ready, total, fraction, message, unit_index, state):
        with self._lock:
            if total is not None:
                total = max(0, int(total))
                if self._total is None:
                    self._total = total
                elif total != self._total:
                    # `total` may only be set once per invocation (§30.4).
                    logger.debug("[invocation] progress total re-set is ignored")
                    total = self._total
                else:
                    total = self._total
            if ready is not None:
                ready = max(0, int(ready))
                if self._ready is not None and ready < self._ready:
                    logger.warning(
                        "[invocation] progress ready went backwards ({} < {}); ignored",
                        ready, self._ready,
                    )
                    ready = self._ready
                self._ready = ready
            effective_total = self._total
        if fraction is not None:
            fraction = min(1.0, max(0.0, float(fraction)))
        if message is not None:
            message = self._safe_message(message)
        if unit_index is not None:
            unit_index = int(unit_index)
        if state is not None:
            state = str(state)[:32]
        event = ProgressEvent(
            ready=ready,
            total=total if total is not None else (effective_total if ready is not None else None),
            fraction=fraction,
            message=message,
            unit_index=unit_index,
            state=state,
        )
        return event if event.to_dict() else None

    def _safe_message(self, message: str) -> str:
        # Redaction, path stripping, and the 200-character cap all live in
        # sanitize_message; a progress message must carry neither a filesystem
        # path nor a provider response body (§30.4).
        from scriptase.engine.redaction import redact_text

        text = sanitize_message(redact_text(str(message), self._secrets))
        return text[:PROGRESS_MESSAGE_MAX]

    def _maybe_emit(self, event: ProgressEvent, *, force: bool) -> None:
        now = self._clock()
        with self._lock:
            due = (
                force
                or self._last_emit is None
                or (now - self._last_emit) >= self._min_interval_s
            )
            if not due:
                self._pending = event
                return
            self._last_emit = now
            self._pending = None
        self._emit(event)

    def _emit(self, event: ProgressEvent) -> None:
        if self._sink is None:
            return
        try:
            self._sink(event)
        except Exception as exc:
            # A failure inside the reporter is logged and swallowed (§30.4).
            logger.warning("[invocation] progress sink raised: {}", exc)


NULL_PROGRESS = ProgressReporter()


def message_progress(
    sink: Callable[[str], None] | None,
    *,
    secrets: Any = (),
    **kwargs,
) -> ProgressReporter:
    """Wrap `AdapterContext.progress`, which accepts only a message (§30.6)."""
    if sink is None:
        return ProgressReporter(None, secrets=secrets, **kwargs)

    def adapt(event: ProgressEvent) -> None:
        text = event.message
        if text is None and event.ready is not None and event.total:
            text = f"{event.ready}/{event.total}"
        if text:
            sink(text)

    return ProgressReporter(adapt, secrets=secrets, **kwargs)


# -- logging (contracts.md §30.5) -------------------------------------------


class ProviderLogger:
    """The only logging surface a provider may use (§30.5).

    Every message and every field value passes through workflow redaction seeded
    with the invocation's secrets before it reaches loguru, and every record is
    tagged with the invocation identity so a provider never formats it itself.
    """

    LEVELS = ("debug", "info", "warning", "error")

    def __init__(self, tags: Mapping[str, Any] | None = None, *, secrets: Any = ()):
        self.tags = dict(tags or {})
        self._secrets = set(secrets or ())
        self.records: list[dict] = []

    def bind(self, **tags) -> "ProviderLogger":
        merged = dict(self.tags)
        merged.update(tags)
        return ProviderLogger(merged, secrets=self._secrets)

    def debug(self, message: str, **fields) -> None:
        self._write("debug", message, fields)

    def info(self, message: str, **fields) -> None:
        self._write("info", message, fields)

    def warning(self, message: str, **fields) -> None:
        self._write("warning", message, fields)

    def error(self, message: str, **fields) -> None:
        """Write a log line. This does not fail the invocation (§30.5)."""
        self._write("error", message, fields)

    def internal(self, message: str, **fields) -> None:
        """Log a diagnostic that may never become an execution-record entry.

        Used by the exception boundary for the full traceback: it is emitted at
        error level but is explicitly internal-only (§30.5, §34.4 rule 1).
        """
        self._write("error", message, fields, internal=True)

    def entries(self, levels=("warning", "error")) -> list[dict]:
        """Provider-authored records eligible to become execution-record logs.

        Internal-only diagnostics are excluded by construction.
        """
        return [
            record
            for record in self.records
            if record["level"] in levels and not record["internal"]
        ]

    def _write(self, level: str, message: str, fields: dict, *, internal: bool = False) -> None:
        from scriptase.engine.redaction import redact, redact_text

        safe_message = redact_text(str(message), self._secrets)
        safe_fields = redact(dict(fields), secrets=self._secrets)
        record = {
            "level": level,
            "message": safe_message,
            "fields": safe_fields,
            "internal": internal,
        }
        self.records.append(record)
        tagged = " ".join(f"{key}={value}" for key, value in self.tags.items() if value)
        rendered = f"[provider] {tagged} {safe_message}" if tagged else f"[provider] {safe_message}"
        getattr(logger, level)("{}", rendered)


NULL_LOGGER = ProviderLogger()


# -- staged artifacts (contracts.md §30.2) ----------------------------------


class ArtifactStager:
    """Wraps the scheduler's `stage_path` and remembers what was staged.

    Provider output is staged and validated before promotion, so a failed
    invocation publishes nothing. The recorded destinations are what let the
    boundary tell "the provider never produced this artifact" apart from "the
    artifact exists but has not been promoted yet" — without them every staged
    write would look like `PROVIDER_ARTIFACT_MISSING`.
    """

    def __init__(self, stage: Callable[[str], str] | None = None):
        self._stage = stage
        self.destinations: list[str] = []

    def __call__(self, destination: str) -> str:
        self.destinations.append(os.path.abspath(destination))
        return self._stage(destination) if self._stage is not None else destination

    def staged(self, absolute_path: str) -> bool:
        return os.path.abspath(absolute_path) in self.destinations


# -- the invocation (contracts.md §30.1) ------------------------------------


@dataclass(frozen=True)
class ProviderInvocation:
    """Everything one provider call is allowed to know (§30.1).

    Constructed per call, never retained by a provider, and never passed to the
    memoized `create()` factory (§21.1).
    """

    domain: str
    provider_id: str
    project_id: str
    execution_id: str = ""
    node_id: str = ""
    attempt: int = 1
    invocation_id: str = ""
    output_dir: str = ""
    stage_artifact: Callable[[str], str] | None = None
    cancel: CancellationToken = field(default_factory=CancellationToken)
    progress: ProgressReporter = field(default_factory=ProgressReporter)
    log: ProviderLogger = field(default_factory=ProviderLogger)
    deadline_s: float | None = None
    # Durable per-provider values with the env fallback already resolved. May
    # contain secrets; never echoed into a result (§30.1, §22.6).
    settings: Mapping[str, Any] = field(default_factory=dict)
    # Per-run node/request values. Never contains secrets.
    options: Mapping[str, Any] = field(default_factory=dict)
    selection_reason: str = "default"

    @property
    def deadline(self) -> float:
        """The effective deadline in seconds (§35.3)."""
        return (
            domain_deadline(self.domain)
            if self.deadline_s is None
            else float(self.deadline_s)
        )

    def identity(self) -> dict:
        """The six tags every log record carries (§30.5)."""
        return {
            "domain": self.domain,
            "provider_id": self.provider_id,
            "project_id": self.project_id,
            "execution_id": self.execution_id,
            "node_id": self.node_id,
            "invocation_id": self.invocation_id,
        }


def new_invocation_id() -> str:
    """A fresh uuid4 hex. A retried invocation gets a new one (§35.2)."""
    return uuid.uuid4().hex


def build_invocation(
    context: Any,
    *,
    domain: str,
    provider_id: str,
    project_id: str,
    output_dir: str = "",
    settings: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
    deadline_s: float | None = None,
    attempt: int = 1,
    selection_reason: str = "default",
) -> ProviderInvocation:
    """Build a `ProviderInvocation` from an `AdapterContext` (§30.6).

    Exactly one construction site per domain exists, and a legacy route can
    build the same object with `context=None` and no scheduler.
    """
    from scriptase.engine.adapters.common import context_value
    from scriptase.engine.redaction import collect_secrets

    settings = dict(settings or {})
    options = dict(options or {})
    secrets = collect_secrets(settings)

    stop_requested = context_value(context, "stop_requested") if context is not None else None
    progress_sink = context_value(context, "progress") if context is not None else None
    stage_artifact = context_value(context, "stage_artifact") if context is not None else None
    execution_id = context_value(context, "execution_id", "") if context is not None else ""
    node_id = context_value(context, "node_id", "") if context is not None else ""

    invocation_id = new_invocation_id()
    return ProviderInvocation(
        domain=domain,
        provider_id=provider_id,
        project_id=project_id,
        execution_id=execution_id or "",
        node_id=node_id or "",
        attempt=attempt,
        invocation_id=invocation_id,
        output_dir=output_dir,
        stage_artifact=ArtifactStager(stage_artifact),
        cancel=CancellationToken(stop_requested),
        progress=message_progress(progress_sink, secrets=secrets),
        log=ProviderLogger(
            {
                "domain": domain,
                "provider_id": provider_id,
                "project_id": project_id,
                "execution_id": execution_id or "",
                "node_id": node_id or "",
                "invocation_id": invocation_id,
            },
            secrets=secrets,
        ),
        deadline_s=deadline_s,
        settings=settings,
        options=options,
        selection_reason=selection_reason,
    )


__all__ = [
    "DEFAULT_DEADLINE_S",
    "DOMAIN_DEADLINE_S",
    "NULL_CANCELLATION",
    "NULL_LOGGER",
    "NULL_PROGRESS",
    "PROGRESS_MESSAGE_MAX",
    "PROGRESS_MIN_INTERVAL_S",
    "ArtifactStager",
    "CancellationToken",
    "ProgressEvent",
    "ProgressReporter",
    "ProviderInvocation",
    "ProviderLogger",
    "build_invocation",
    "domain_deadline",
    "message_progress",
    "new_invocation_id",
]
