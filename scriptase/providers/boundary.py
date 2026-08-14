"""The single provider exception boundary — step 11.4.

Implements contracts.md §34.4 and §35.3. Exactly one place wraps provider
exceptions, and the substantive rule is rule 3: **the original exception's
`str(exc)` is never copied into `message` or `details`.** The full traceback goes
to the redacted logger tagged internal-only, so §30.5 cannot promote it into an
execution-record entry, an SSE frame, or an API response.

`invoke()` is the entry point every domain call goes through. It owns the
deadline, the cancellation checks around dispatch, result coercion, provenance,
and the wrap — so no domain re-implements any of them.
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Any, Callable

from scriptase.shared.io_utils import now_iso
from scriptase.providers import errors as E
from scriptase.providers.errors import (
    ProviderCancelled,
    ProviderError,
)
from scriptase.providers.invocation import ProviderInvocation
from scriptase.providers.results import (
    Provenance,
    ProviderResult,
    coerce_result,
    resolve_ref,
    validate_egress,
)


# Exception classes whose meaning is unambiguous enough to classify without the
# provider's cooperation. Everything else becomes PROVIDER_FAILED (§34.4).
_CLASSIFIED: tuple[tuple[tuple[type, ...], str], ...] = (
    ((TimeoutError,), E.PROVIDER_TIMEOUT),
    ((ConnectionError,), E.PROVIDER_TRANSPORT_FAILED),
    ((ValueError, TypeError, KeyError), E.PROVIDER_RESPONSE_MALFORMED),
)


def classify(exc: BaseException) -> str:
    """The provider code for an unclassified exception (§34.2)."""
    for types, code in _CLASSIFIED:
        if isinstance(exc, types):
            return code
    return E.PROVIDER_FAILED


def wrap_exception(
    exc: BaseException,
    *,
    domain: str = "",
    provider_id: str = "",
    log=None,
    code: str | None = None,
) -> ProviderError:
    """Convert any exception into a safe `ProviderError` (§34.4).

    1. the full traceback goes to the redacted logger, marked internal-only;
    2. a generic per-domain sentence becomes the message;
    3. `str(exc)` is never copied into `message` or `details`.
    """
    if isinstance(exc, ProviderError):
        return exc

    resolved = code or classify(exc)
    if log is not None:
        log.internal(
            "provider invocation failed",
            cause_type=type(exc).__name__,
            traceback="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        )
    return ProviderError(
        resolved,
        E.generic_message(domain),
        retryable=E.is_retryable(resolved),
        domain=domain,
        provider_id=provider_id,
        cause_type=type(exc).__name__,
    )


class Deadline:
    """A platform-owned wall clock for one invocation (§35.3).

    A provider never decides how long the caller waits; it may read
    `remaining()` to size its own waits and must poll `check()` while waiting.
    """

    def __init__(self, seconds: float, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._started = clock()
        self.seconds = float(seconds)

    def remaining(self) -> float:
        return max(0.0, self.seconds - (self._clock() - self._started))

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def check(self, *, domain: str = "", provider_id: str = "", details: Any = None) -> None:
        """Raise `PROVIDER_TIMEOUT` once the deadline has passed."""
        if self.expired():
            raise ProviderError(
                E.PROVIDER_TIMEOUT,
                f"The provider exceeded its {int(self.seconds)}s deadline",
                retryable=True,
                domain=domain,
                provider_id=provider_id,
                details=details if isinstance(details, dict) else None,
            )


def wait_until(
    predicate: Callable[[], Any],
    *,
    invocation: ProviderInvocation,
    interval_s: float = 1.0,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    details: Callable[[], dict] | None = None,
) -> Any:
    """Poll `predicate` until it is truthy, honoring cancellation and deadline.

    Replaces the hand-written `while time.monotonic() < deadline:` loops in the
    two visual adapters, including their two wrong error codes: cancellation
    raises `ProviderCancelled` (workflow `CANCELLED`) and expiry raises
    `PROVIDER_TIMEOUT` (workflow `POLL_TIMEOUT`), not `EXECUTION_CANCELLED` and
    `NODE_TIMEOUT` (§35.1, §35.3).
    """
    deadline = Deadline(invocation.deadline, clock=clock)
    while True:
        invocation.cancel.raise_if_cancelled()
        outcome = predicate()
        if outcome:
            return outcome
        invocation.cancel.raise_if_cancelled()
        if deadline.expired():
            deadline.check(
                domain=invocation.domain,
                provider_id=invocation.provider_id,
                details=details() if details is not None else None,
            )
        sleeper(max(0.01, min(interval_s, deadline.remaining())))


def invoke(
    call: Callable[[ProviderInvocation], Any],
    invocation: ProviderInvocation,
    *,
    provider_version: str = "",
    contract_version: int = 1,
    settings_version: int = 0,
    cache_hit: bool = False,
    verify_artifacts: bool = True,
) -> ProviderResult:
    """Run one provider call behind the boundary and return a valid envelope.

    Every failure leaves here as a `ProviderError` whose message is safe to
    persist. Cancellation is checked before dispatch and after return, matching
    the scheduler's own behavior for providers that do not declare `cancel`.
    """
    started_at = now_iso()
    started = time.perf_counter()
    invocation.cancel.raise_if_cancelled()

    try:
        returned = call(invocation)
        invocation.cancel.raise_if_cancelled()
        result = coerce_result(
            returned,
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            provider_version=provider_version,
            contract_version=contract_version,
        )
        if verify_artifacts:
            check_artifacts(result, invocation)
    except ProviderCancelled:
        raise
    except BaseException as exc:  # a provider is a plugin boundary
        raise wrap_exception(
            exc,
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            log=invocation.log,
        ) from None
    finally:
        invocation.progress.flush()

    result.provenance = build_provenance(
        invocation,
        provider_version=provider_version,
        contract_version=contract_version,
        settings_version=settings_version,
        started_at=started_at,
        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        cache_hit=cache_hit,
    )
    # Provenance is platform-authored but still crosses the same boundary, and
    # it is the one place a settings value is echoed at all (§31.3, §36 L6).
    leaks = validate_egress(result.provenance.to_dict(), path="provenance")
    if leaks:
        raise ProviderError(
            E.PROVIDER_RESULT_INVALID,
            f"Provenance rejected at the egress boundary: {leaks[0]}",
            domain=invocation.domain,
            provider_id=invocation.provider_id,
        )
    return result


def check_artifacts(result: ProviderResult, invocation: ProviderInvocation) -> None:
    """Every declared artifact must actually exist (§34.2 `PROVIDER_ARTIFACT_MISSING`).

    A ref whose destination was handed to `stage_artifact()` counts as produced:
    it lives in the staging directory until the node succeeds and is only then
    promoted, so checking the final path would fail every staged write.
    """
    stager = invocation.stage_artifact
    staged = getattr(stager, "staged", None)
    missing = []
    for ref in result.artifact_refs:
        absolute = resolve_ref(ref)
        if os.path.exists(absolute):
            continue
        if callable(staged) and staged(absolute):
            continue
        missing.append(os.path.basename(ref))
    if missing:
        raise ProviderError(
            E.PROVIDER_ARTIFACT_MISSING,
            f"The provider declared {len(missing)} artifact(s) it did not produce",
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            details={"artifacts": missing[:20]},
        )


def build_provenance(
    invocation: ProviderInvocation,
    *,
    provider_version: str = "",
    contract_version: int = 1,
    settings_version: int = 0,
    started_at: str = "",
    duration_ms: int = 0,
    cache_hit: bool = False,
) -> Provenance:
    """Fill §31.3 provenance. A provider can never write this."""
    from scriptase.providers import settings_manager

    return Provenance(
        invocation_id=invocation.invocation_id,
        domain=invocation.domain,
        provider_id=invocation.provider_id,
        provider_version=provider_version,
        contract_version=contract_version,
        settings_version=settings_version,
        # The only echo of settings a result may carry (§36 L6).
        resolved_settings_redacted=settings_manager.redact_settings(
            dict(invocation.settings)
        ),
        options=dict(invocation.options),
        selection_reason=invocation.selection_reason,
        started_at=started_at,
        finished_at=now_iso(),
        duration_ms=duration_ms,
        cache_hit=cache_hit,
    )


__all__ = [
    "Deadline",
    "build_provenance",
    "check_artifacts",
    "classify",
    "invoke",
    "wait_until",
    "wrap_exception",
]
