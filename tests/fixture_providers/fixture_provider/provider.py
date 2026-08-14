"""The reference v2 provider body — contracts.md §46.3.

Deterministic, offline, and credential-free. Every branch a contract test needs
is selected through `invocation.options["scenario"]`, so one provider exercises
sync success, async success, progress, cancellation, timeout, retryable and
terminal errors, malformed results, partial unit failure, unmanaged and missing
artifacts, and a secret-bearing exception — without a single network call.

Note what this provider does *not* do, because that is the contract: it never
imports loguru, never reads `os.environ`, never touches `flask.request`, never
writes outside `invocation.output_dir`, and never retries an invocation itself.
"""

import os

from scriptase.providers.errors import (
    PROVIDER_AUTH_FAILED,
    PROVIDER_RATE_LIMITED,
    ProviderError,
)
from scriptase.providers.jobs import (
    JobHandle,
    JobStatus,
    RUNNING,
    SUCCEEDED,
)
from scriptase.providers.results import (
    UNIT_FAILED,
    UNIT_SUCCEEDED,
    ProviderResult,
    UnitResult,
)


class FixtureProvider:
    """A provider whose behavior is chosen by the caller, not by its id."""

    def __init__(self):
        self.constructed = True
        self.shutdown_calls = 0
        self.jobs: dict[str, JobStatus] = {}

    # -- the v2 invocation contract ------------------------------------

    def invoke(self, request: dict, invocation):
        scenario = str(invocation.options.get("scenario", "sync"))
        handler = getattr(self, f"_scenario_{scenario}", None)
        if handler is None:
            raise ProviderError(
                "PROVIDER_REQUEST_INVALID", f"Unknown scenario {scenario!r}"
            )
        return handler(request, invocation)

    # -- success paths --------------------------------------------------

    def _scenario_sync(self, request, invocation):
        ref = self._write_artifact(invocation, "voice.wav", b"RIFF-fixture")
        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            payload={
                "audio_ref": ref,
                "duration_seconds": 8.0,
                "sample_rate": 24000,
                "format": "wav",
                "voice": str(request.get("voice", "")),
                "characters_billed": len(str(request.get("text", ""))),
            },
            artifact_refs=[ref],
            metadata={"engine": "fixture"},
        )

    def _scenario_batch(self, request, invocation):
        units = []
        refs = []
        for index in range(int(invocation.options.get("units", 3))):
            ref = self._write_artifact(invocation, f"{index}.png", b"PNG-fixture")
            refs.append(ref)
            units.append(UnitResult(
                unit_index=index,
                state=UNIT_SUCCEEDED,
                artifact_refs=(ref,),
                metadata={"kind": "image"},
            ))
            invocation.progress(ready=index + 1, total=len(range(3)))
        return ProviderResult(payload={"total": len(units)}, units=units, artifact_refs=refs)

    def _scenario_partial(self, request, invocation):
        """One unit produced, one failed, one never attempted (§31.5 rule 1)."""
        ref = self._write_artifact(invocation, "0.png", b"PNG-fixture")
        return ProviderResult(
            payload={"total": 3},
            units=[
                UnitResult(0, UNIT_SUCCEEDED, artifact_refs=(ref,)),
                UnitResult(1, UNIT_FAILED, error=_unit_error()),
                UnitResult(2, "skipped"),
            ],
        )

    def _scenario_all_units_failed(self, request, invocation):
        """Zero produced units can never be success (§31.4, §33.2)."""
        return ProviderResult(
            payload={"total": 2},
            units=[
                UnitResult(0, UNIT_FAILED, error=_unit_error()),
                UnitResult(1, UNIT_FAILED, error=_unit_error()),
            ],
        )

    # -- asynchronous job ------------------------------------------------

    def submit(self, request, invocation) -> JobHandle:
        handle = JobHandle(
            job_id=f"fixture-{invocation.invocation_id[:12]}",
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            project_id=invocation.project_id,
            invocation_id=invocation.invocation_id,
        )
        self.jobs[handle.job_id] = JobStatus(
            job_id=handle.job_id, state=RUNNING, ready=0, total=2
        )
        return handle

    def poll(self, job_id: str, invocation) -> JobStatus:
        status = self.jobs[job_id]
        if status.ready + 1 >= status.total:
            status = status.advance(
                state=SUCCEEDED,
                ready=status.total,
                units=tuple(
                    UnitResult(index, UNIT_SUCCEEDED, artifact_refs=(f"fixture/{index}.png",))
                    for index in range(status.total)
                ),
            )
        else:
            status = status.advance(ready=status.ready + 1)
        self.jobs[job_id] = status
        return status

    def cancel_job(self, job_id: str, invocation) -> None:
        self.jobs[job_id] = self.jobs[job_id].advance(state="cancelled")

    # -- progress and cancellation ---------------------------------------

    def _scenario_progress(self, request, invocation):
        for ready in range(1, 6):
            invocation.progress(ready=ready, total=5, message="rendering")
        invocation.progress(ready=5, total=5, state="succeeded")
        return ProviderResult(payload={"total": 5})

    def _scenario_cancel(self, request, invocation):
        # A provider declaring `cancel` polls at least every 5s during any wait
        # and returns or raises within 10s of the flag being set (§30.3).
        for _ in range(1000):
            invocation.cancel.raise_if_cancelled()
        return ProviderResult(payload={"never": True})

    def _scenario_slow(self, request, invocation):
        from scriptase.providers.boundary import wait_until

        wait_until(lambda: False, invocation=invocation, interval_s=0.01)
        return ProviderResult(payload={"never": True})

    # -- failure paths ----------------------------------------------------

    def _scenario_terminal_error(self, request, invocation):
        raise ProviderError(
            PROVIDER_AUTH_FAILED, "The provider rejected the credentials",
            domain=invocation.domain, provider_id=invocation.provider_id,
        )

    def _scenario_retryable_error(self, request, invocation):
        raise ProviderError(
            PROVIDER_RATE_LIMITED, "The provider is rate limiting this account",
            domain=invocation.domain, provider_id=invocation.provider_id,
        )

    def _scenario_secret_bearing_exception(self, request, invocation):
        # The exact shape §36 requires a test for: a key and an absolute path
        # inside an unclassified exception.
        raise RuntimeError("key sk-abc123def456 at C:\\secret\\file.txt")

    def _scenario_malformed_result(self, request, invocation):
        return "not an object"

    def _scenario_unknown_result_keys(self, request, invocation):
        return {"payload": {"ok": True}, "from_a_newer_build": 1, "status": "succeeded"}

    def _scenario_leaky_result(self, request, invocation):
        return ProviderResult(payload={"path": os.path.abspath(os.sep), "api_key": "x"})

    def _scenario_unmanaged_artifact(self, request, invocation):
        from scriptase.providers.results import normalize_ref

        normalize_ref(os.path.join(os.path.abspath(os.sep), "elsewhere", "x.wav"))
        return ProviderResult(payload={"never": True})

    def _scenario_missing_artifact(self, request, invocation):
        # Declares a ref for a file it never wrote.
        return ProviderResult(
            payload={"audio_ref": "fixture/never-written.wav"},
            artifact_refs=["fixture/never-written.wav"],
        )

    # -- helpers -----------------------------------------------------------

    def _write_artifact(self, invocation, name: str, data: bytes) -> str:
        """Write inside the managed directory and return the relative ref."""
        from scriptase.providers.results import normalize_ref

        if invocation.stage_artifact is not None:
            destination = os.path.join(invocation.output_dir, name)
            path = invocation.stage_artifact(destination)
        else:
            path = os.path.join(invocation.output_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return normalize_ref(os.path.join(invocation.output_dir, name))

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _unit_error():
    from scriptase.providers.errors import (
        PROVIDER_UNIT_FAILED,
        ProviderErrorPayload,
    )

    return ProviderErrorPayload.from_error(ProviderError(
        PROVIDER_UNIT_FAILED, "The provider could not render this unit", retryable=True
    ))


def create():
    return FixtureProvider()


def validate_settings(settings: dict) -> list[dict]:
    if settings.get("mode") == "batch" and not settings.get("unit_count"):
        return [{
            "field": "unit_count",
            "severity": "error",
            "message": "Batch mode needs a unit count",
        }]
    return []


def health_check(settings: dict) -> dict:
    return {"status": "ok", "latency_ms": 0, "message": "Fixture provider is offline-only"}
