"""Async multi-asset animator body — submit, poll, per-unit results.

Advances one unit per poll so a test drives the whole §33.2 state machine
without a clock. Every unit writes a real file inside the managed directory.
"""

import os

_PNG = b"\x89PNG\r\n\x1a\n"


class FixtureAsyncAnimatorProvider:
    """A provider whose work happens between polls."""

    def __init__(self):
        self.shutdown_calls = 0
        self.jobs: dict = {}

    def submit(self, request, invocation):
        from scriptase.providers.jobs import JobHandle, JobStatus, RUNNING

        options = {**dict(invocation.settings), **dict(invocation.options)}
        unit_count = getattr(request, "unit_count", None)
        if unit_count is None:
            unit_count = int(
                options.get("unit_count")
                or len(getattr(request, "scenes", None) or request.get("units") or ())
                or 3
            )
        handle = JobHandle(
            job_id=f"fixture-anim-{invocation.invocation_id[:12]}",
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            project_id=invocation.project_id,
            invocation_id=invocation.invocation_id,
        )
        self.jobs[handle.job_id] = {
            "status": JobStatus(
                job_id=handle.job_id, state=RUNNING, ready=0, total=int(unit_count)
            ),
            "invocation": invocation,
            "fail_last": bool(options.get("fail_last_unit")),
            "units": [],
        }
        invocation.progress(ready=0, total=int(unit_count), message="submitted")
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
                UnitResult(
                    index, UNIT_SUCCEEDED, artifact_refs=(ref,),
                    metadata={"unit": index, "kind": "image"},
                )
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


def _write_unit(invocation, index: int) -> str:
    destination = os.path.join(invocation.output_dir, f"unit-{index}.png")
    path = (
        invocation.stage_artifact(destination)
        if invocation.stage_artifact is not None
        else destination
    )
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(_PNG)
    # Prefer a managed ref when the output sits under OUTPUT_DIR; fall back to
    # a relative name so a test with a private temp dir still works.
    try:
        from scriptase.providers.results import normalize_ref

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


def create() -> FixtureAsyncAnimatorProvider:
    return FixtureAsyncAnimatorProvider()


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
