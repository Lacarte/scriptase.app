"""Manifest-backed bridge onto the shared media-job service — step 14.1.

Storyboard and Animator both start a legacy job store and then wait for a
per-scene status map to settle. Before this step each adapter carried its own
copy of that wait: its own deadline, its own cancellation check, its own
"how many are ready" arithmetic, and no progress reporting at all.

This module replaces both loops with one call into `MediaJobService`. The two
domains differ only in *data* — where the manifest lives, how to start the job,
and which failure code the node has always reported — so there is no domain
branch here or in the service. Domain-only values (poll cadence, deadline) come
from the frozen tables in `providers_common`.

What is deliberately preserved:

  * public job IDs — the job ID is still the project ID, and the legacy
    `storyboard.json` / `grabber_job.json` manifests stay authoritative;
    `media_job.json` is written *beside* them (§33.4) and replaces nothing.
  * the `{total, ready, errors}` shape the node outputs and the UI read.
  * the `CANCELLED` / `POLL_TIMEOUT` / `STORYBOARD_FAILED` / `ANIMATOR_FAILED`
    codes the scheduler and its tests already branch on.

Legacy providers write their assets straight to the managed output tree while
the UI previews them, so staging/promotion stays a no-op for this bridge; real
staging arrives with the provider migrations in 14.2/14.3.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from scriptase.shared.io_utils import safe_json_read
from scriptase.providers.errors import (
    PROVIDER_UNIT_FAILED,
    ProviderCancelled,
    ProviderError,
)
from scriptase.providers.invocation import build_invocation
from scriptase.providers.jobs import (
    RUNNING,
    JobHandle,
    JobStatus,
    status_from_scenes,
)
from scriptase.providers.media_jobs import (
    JOB_DONE_STATES,
    MediaJobService,
    settled_state,
    units_from_legacy_scenes,
)
from scriptase.providers.results import UNIT_FAILED

from .common import AdapterError


class ManifestJobProvider:
    """An `AsyncMediaProvider` over a legacy manifest-backed job store.

    `start` kicks the existing service off exactly as the adapter used to.
    `read` returns the current manifest mapping (in-memory store first, file
    second — the animator store is authoritative while the process lives).
    """

    def __init__(
        self,
        *,
        start: Callable[[], None],
        read: Callable[[], Mapping[str, Any] | None],
        unit_count: int,
    ) -> None:
        self._start = start
        self._read = read
        self._unit_count = unit_count
        # Last per-scene map observed, so the caller can keep returning the
        # legacy `scene_statuses` payload without re-reading the manifest.
        self.scene_statuses: dict[str, Any] = {}

    def submit(self, request: Any, invocation: Any) -> JobHandle:
        self._start()
        return JobHandle(
            job_id=invocation.project_id,
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            project_id=invocation.project_id,
            invocation_id=invocation.invocation_id,
        )

    def poll(self, job_id: str, invocation: Any) -> JobStatus:
        raw = self._read()
        if not isinstance(raw, Mapping):
            return JobStatus(job_id=job_id, state=RUNNING, total=self._unit_count)
        scenes = raw.get("scene_statuses")
        scenes = scenes if isinstance(scenes, Mapping) else {}
        self.scene_statuses = dict(scenes)

        status = status_from_scenes(job_id, scenes)
        units = units_from_legacy_scenes(scenes)
        total = status.total or self._unit_count
        state = status.state
        if not status.terminal and str(raw.get("status") or "") in JOB_DONE_STATES:
            # `gemini_ws._mark_job_done` writes `status: "done"` whatever the
            # per-scene map says, and the legacy loops honoured it. Units still
            # pending at that point never arrive, so settle the outcome from
            # what was produced instead of waiting out the deadline. Zero
            # produced units still cannot become success (§33.2).
            state = settled_state(units, total)
        return JobStatus(
            job_id=job_id,
            state=state,
            ready=status.ready,
            total=total,
            fraction=status.fraction,
            units=units,
            error=status.error,
        )

    def cancel_job(self, job_id: str, invocation: Any) -> None:
        """The legacy stores expose no remote cancel; 14.2/14.3 add real ones."""
        return None


def read_manifest(path: str) -> Mapping[str, Any] | None:
    """Read a job manifest, treating an absent or unreadable file as pending."""
    if not os.path.isfile(path):
        return None
    try:
        data = safe_json_read(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, Mapping) else None


def run_manifest_job(
    *,
    domain: str,
    provider: str,
    project_id: str,
    context: Any,
    scenes: list[Mapping[str, Any]],
    manifest_path: str,
    start: Callable[[], None] | None = None,
    read: Callable[[], Mapping[str, Any] | None] | None = None,
    failure_code: str,
    failure_details: Mapping[str, Any] | None = None,
    service: MediaJobService | None = None,
    job_provider: Any = None,
    request: Any = None,
    settings: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict:
    """Run one multi-scene job through the shared service.

    Returns the legacy `{total, ready, errors, scene_statuses}` payload. Raises
    the `AdapterError` the scheduler already understands: `CANCELLED` on stop,
    `POLL_TIMEOUT` on deadline, and `failure_code` when nothing was produced.

    `job_provider` is a real `AsyncMediaProvider` — storyboard (14.2) and
    animator (14.3) both pass one. The `start`/`read` path remains for tests
    that synthesize a legacy store without constructing a provider package.
    """
    if job_provider is None:
        if start is None:
            raise ValueError("run_manifest_job needs either job_provider or start")
        job_provider = ManifestJobProvider(
            start=start, read=read or (lambda: read_manifest(manifest_path)),
            unit_count=len(scenes),
        )
    invocation = build_invocation(
        context,
        domain=domain,
        provider_id=provider,
        project_id=project_id,
        output_dir=os.path.dirname(manifest_path),
        settings=settings,
        options=options,
    )
    if request is None:
        request = {"scenes": list(scenes), "unit_count": len(scenes)}

    try:
        result = (service or MediaJobService()).run(
            job_provider, request, invocation
        )
    except ProviderCancelled as exc:
        raise exc.as_adapter_error() from None
    except ProviderError as exc:
        if exc.code == PROVIDER_UNIT_FAILED:
            # Preserve the node-level code the adapter has always reported for
            # "the provider completed but produced nothing".
            reported = exc.details if isinstance(exc.details, dict) else {}
            failed = [
                unit
                for unit in (reported.get("units") or [])
                if isinstance(unit, Mapping) and unit.get("state") == UNIT_FAILED
            ]
            raise AdapterError(
                failure_code,
                exc.message,
                details={**dict(failure_details or {}), "errors": len(failed)},
            ) from None
        raise exc.as_adapter_error() from None

    payload = result.payload if isinstance(result.payload, Mapping) else {}
    # A synthesized `ManifestJobProvider` remembers the last map it polled; a
    # real provider does not, so the manifest it owns is read once at the end.
    observed = getattr(job_provider, "scene_statuses", None)
    if observed is None:
        manifest = read or (lambda: read_manifest(manifest_path))
        raw = manifest()
        scene_map = raw.get("scene_statuses") if isinstance(raw, Mapping) else None
        observed = dict(scene_map) if isinstance(scene_map, Mapping) else {}
    return {
        "total": int(payload.get("total") or len(scenes)),
        "ready": int(payload.get("ready") or 0),
        "errors": sum(1 for unit in result.units if unit.state == UNIT_FAILED),
        "scene_statuses": observed,
    }


__all__ = [
    "JOB_DONE_STATES",
    "ManifestJobProvider",
    "read_manifest",
    "run_manifest_job",
]
