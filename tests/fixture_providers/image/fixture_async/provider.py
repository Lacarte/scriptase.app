"""Async multi-asset provider body — submit, poll, per-unit results.

Advances one unit per poll so a test drives the whole §33.2 state machine
without a clock: `submitted → running → succeeded|partial`. Every unit writes a
real file inside the managed directory, so the boundary's artifact check
(§34.2 `PROVIDER_ARTIFACT_MISSING`) is exercised rather than bypassed.

`fail_last_unit` turns the same job into the partial case, which is the branch
§31.5 exists for and the one an all-success fixture would never reach.
"""

import os

_PNG = b"\x89PNG\r\n\x1a\n"


class FixtureAsyncProvider:
    """A provider whose work happens between polls."""

    def __init__(self):
        self.shutdown_calls = 0
        self.jobs: dict = {}

    # -- submit / poll / cancel (contracts.md §33) -----------------------

    def submit(self, request, invocation):
        from scriptase.providers.jobs import JobHandle, JobStatus, RUNNING

        options = {**dict(invocation.settings), **dict(invocation.options)}
        total = _unit_count(request, options)
        handle = JobHandle(
            job_id=f"fixture-async-{invocation.invocation_id[:12]}",
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            project_id=invocation.project_id,
            invocation_id=invocation.invocation_id,
        )
        self.jobs[handle.job_id] = {
            "status": JobStatus(job_id=handle.job_id, state=RUNNING, ready=0, total=total),
            "invocation": invocation,
            "fail_last": bool(options.get("fail_last_unit")),
            "units": [],
        }
        invocation.progress(ready=0, total=total, message="submitted")
        return handle

    def poll(self, job_id: str, invocation):
        from scriptase.providers.jobs import SUCCEEDED
        from scriptase.providers.results import (
            PARTIAL,
            UNIT_FAILED,
            UNIT_SUCCEEDED,
            UnitResult,
        )

        job = self.jobs.get(job_id)
        if job is None:
            from scriptase.providers.jobs import unknown_job_status

            return unknown_job_status(job_id)

        status = job["status"]
        index = len(job["units"])
        last = index == status.total - 1
        if job["fail_last"] and last:
            job["units"].append(UnitResult(index, UNIT_FAILED, error=_unit_error()))
        else:
            ref = _write_unit(job["invocation"], index)
            job["units"].append(
                UnitResult(index, UNIT_SUCCEEDED, artifact_refs=(ref,),
                           metadata={"unit": index})
            )

        produced = sum(1 for unit in job["units"] if unit.state == UNIT_SUCCEEDED)
        if len(job["units"]) >= status.total:
            status = status.advance(
                state=PARTIAL if job["fail_last"] else SUCCEEDED,
                ready=produced,
                units=tuple(job["units"]),
            )
        else:
            status = status.advance(ready=produced, units=tuple(job["units"]))
        job["status"] = status
        invocation.progress(ready=produced, total=status.total)
        return status

    def cancel_job(self, job_id: str, invocation) -> None:
        from scriptase.providers.jobs import JOB_CANCELLED

        job = self.jobs.get(job_id)
        if job is not None:
            job["status"] = job["status"].advance(state=JOB_CANCELLED)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _unit_count(request, options: dict) -> int:
    """Count units from a dict request or a domain pydantic model."""
    if options.get("unit_count") is not None:
        return int(options["unit_count"])
    count = getattr(request, "unit_count", None)
    if callable(count):
        try:
            count = count()
        except TypeError:
            count = None
    if isinstance(count, int) and not isinstance(count, bool) and count > 0:
        return count
    if isinstance(request, dict):
        return int(len(request.get("units") or request.get("scenes") or ()) or 3)
    scenes = getattr(request, "scenes", None)
    if isinstance(scenes, (list, tuple)) and scenes:
        return len(scenes)
    return 3


def _write_unit(invocation, index: int) -> str:
    from scriptase.providers.results import normalize_ref

    destination = os.path.join(invocation.output_dir, f"unit-{index}.png")
    path = (
        invocation.stage_artifact(destination)
        if invocation.stage_artifact is not None
        else destination
    )
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(_PNG)
    try:
        return normalize_ref(destination)
    except Exception:
        return f"unit-{index}.png"


def _unit_error():
    from scriptase.providers.errors import (
        PROVIDER_UNIT_FAILED,
        ProviderError,
        ProviderErrorPayload,
    )

    return ProviderErrorPayload.from_error(ProviderError(
        PROVIDER_UNIT_FAILED, "The renderer could not produce this unit", retryable=True
    ))


def create() -> FixtureAsyncProvider:
    return FixtureAsyncProvider()


def validate_settings(settings: dict) -> list[dict]:
    url = str(settings.get("endpoint_url") or "")
    if url and not url.startswith("https://"):
        return [{
            "field": "endpoint_url",
            "severity": "error",
            "message": "The endpoint must be https",
        }]
    return []


def health_check(settings: dict) -> dict:
    if not settings.get("endpoint_url"):
        return {"status": "warn", "message": "No endpoint is configured"}
    return {"status": "ok", "latency_ms": 0, "message": "Fixture renderer is reachable"}
