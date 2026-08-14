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

Step 8.3 adds optional fallback-chain execution: when a primary instance fails,
the next configured instance is tried and each unit carries sparse provenance
for its producer.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Mapping, Sequence

from scriptase.shared.io_utils import now_iso, safe_json_read
from scriptase.providers.boundary import build_provenance
from scriptase.providers.errors import (
    PROVIDER_UNIT_FAILED,
    ProviderCancelled,
    ProviderError,
)
from scriptase.providers.fallback import run_with_fallback
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
    filter_request_units,
    settled_state,
    units_from_legacy_scenes,
    units_needing_retry,
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


def _legacy_payload(
    *,
    result: Any,
    scenes: list[Mapping[str, Any]],
    job_provider: Any,
    manifest_path: str,
    read: Callable[[], Mapping[str, Any] | None] | None,
    fallback_record: Any = None,
) -> dict:
    """Map a `ProviderResult` onto the legacy adapter payload shape."""
    payload = result.payload if isinstance(result.payload, Mapping) else {}
    observed = getattr(job_provider, "scene_statuses", None)
    if observed is None:
        manifest = read or (lambda: read_manifest(manifest_path))
        raw = manifest()
        scene_map = raw.get("scene_statuses") if isinstance(raw, Mapping) else None
        observed = dict(scene_map) if isinstance(scene_map, Mapping) else {}
    out: dict[str, Any] = {
        "total": int(payload.get("total") or len(scenes)),
        "ready": int(payload.get("ready") or 0),
        "errors": sum(1 for unit in result.units if unit.state == UNIT_FAILED),
        "scene_statuses": observed,
        # Step 8.3: per-unit provenance for the record / History UI.
        "units": [unit.to_dict() for unit in result.units],
        "provenance": (
            result.provenance.to_dict()
            if getattr(result, "provenance", None) is not None
            else None
        ),
    }
    if fallback_record is not None:
        out["fallback"] = {
            "chain": list(fallback_record.chain),
            "attempts": [attempt.to_dict() for attempt in fallback_record.attempts],
            "units_effective": fallback_record.units_effective(),
        }
    return out


def _raise_adapter_failure(
    exc: ProviderError,
    *,
    failure_code: str,
    failure_details: Mapping[str, Any] | None,
) -> None:
    if exc.code == PROVIDER_UNIT_FAILED:
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
    fallback_chain: Sequence[str] | None = None,
    resolve_job_provider: Callable[[str], Any] | None = None,
    resolve_settings: Callable[[str], Mapping[str, Any]] | None = None,
    resolve_type: Callable[[str], str] | None = None,
    primary_selection_reason: str = "node_config",
    selection_reason: str = "node_config",
    provider_instance_id: str = "",
) -> dict:
    """Run one multi-scene job through the shared service.

    Returns the legacy `{total, ready, errors, scene_statuses}` payload. Raises
    the `AdapterError` the scheduler already understands: `CANCELLED` on stop,
    `POLL_TIMEOUT` on deadline, and `failure_code` when nothing was produced.

    `job_provider` is a real `AsyncMediaProvider` — storyboard (14.2) and
    animator (14.3) both pass one. The `start`/`read` path remains for tests
    that synthesize a legacy store without constructing a provider package.

    Step 8.3: when ``fallback_chain`` has more than one instance id and
    ``resolve_job_provider`` is provided, a primary failure falls through to
    the next instance with per-unit provenance stamped on the result.
    """
    chain = [str(i).strip() for i in (fallback_chain or ()) if str(i).strip()]
    use_fallback = len(chain) > 1 and resolve_job_provider is not None

    if job_provider is None and not use_fallback:
        if start is None:
            raise ValueError("run_manifest_job needs either job_provider or start")
        job_provider = ManifestJobProvider(
            start=start, read=read or (lambda: read_manifest(manifest_path)),
            unit_count=len(scenes),
        )

    output_dir = os.path.dirname(manifest_path)
    if request is None:
        request = {"scenes": list(scenes), "unit_count": len(scenes)}
    media = service or MediaJobService()
    instance_id = provider_instance_id or provider

    if not use_fallback:
        invocation = build_invocation(
            context,
            domain=domain,
            provider_id=provider,
            project_id=project_id,
            output_dir=output_dir,
            settings=settings,
            options=options,
            selection_reason=selection_reason,
            provider_instance_id=instance_id,
        )
        started_at = now_iso()
        started = time.perf_counter()
        try:
            result = media.run(job_provider, request, invocation)
        except ProviderCancelled as exc:
            raise exc.as_adapter_error() from None
        except ProviderError as exc:
            _raise_adapter_failure(
                exc, failure_code=failure_code, failure_details=failure_details
            )
            raise  # pragma: no cover
        result.provenance = build_provenance(
            invocation,
            result=result,
            provider_version=getattr(job_provider, "version", "") or "",
            contract_version=int(getattr(job_provider, "contract_version", 1) or 1),
            started_at=started_at,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            provider_instance_id=instance_id,
        )
        return _legacy_payload(
            result=result,
            scenes=scenes,
            job_provider=job_provider,
            manifest_path=manifest_path,
            read=read,
        )

    # --- fallback chain (step 8.3) -----------------------------------------
    last_provider = job_provider

    def type_of(iid: str) -> str:
        if resolve_type is not None:
            return str(resolve_type(iid) or iid)
        return iid

    def run_one(iid: str, reason: str, prior):
        nonlocal last_provider
        type_id = type_of(iid)
        provider_obj = resolve_job_provider(iid)
        last_provider = provider_obj
        settings_map = (
            dict(resolve_settings(iid))
            if resolve_settings is not None
            else dict(settings or {})
        )
        options_map = dict(options or {})
        invocation = build_invocation(
            context,
            domain=domain,
            provider_id=type_id,
            project_id=project_id,
            output_dir=output_dir,
            settings=settings_map,
            options=options_map,
            selection_reason=reason,
            provider_instance_id=iid,
        )
        started_at = now_iso()
        started = time.perf_counter()
        attempt_request = request
        prior_units = tuple(prior or ())
        if prior_units:
            needed = units_needing_retry(prior_units)
            if needed:
                attempt_request = filter_request_units(request, needed)
        result = media.run(
            provider_obj,
            attempt_request,
            invocation,
            prior_units=prior_units,
        )
        result.provenance = build_provenance(
            invocation,
            result=result,
            provider_version=getattr(provider_obj, "version", "") or "",
            contract_version=int(getattr(provider_obj, "contract_version", 1) or 1),
            started_at=started_at,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            provider_instance_id=iid,
        )
        return result

    try:
        record = run_with_fallback(
            domain=domain,
            chain=chain,
            run_one=run_one,
            multi_unit=True,
            primary_selection_reason=primary_selection_reason,
            resolve_type=type_of,
            expected_unit_count=len(scenes),
        )
    except ProviderCancelled as exc:
        raise exc.as_adapter_error() from None
    except ProviderError as exc:
        _raise_adapter_failure(
            exc, failure_code=failure_code, failure_details=failure_details
        )
        raise  # pragma: no cover

    return _legacy_payload(
        result=record.result,
        scenes=scenes,
        job_provider=last_provider,
        manifest_path=manifest_path,
        read=read,
        fallback_record=record,
    )


__all__ = [
    "JOB_DONE_STATES",
    "ManifestJobProvider",
    "read_manifest",
    "run_manifest_job",
]
