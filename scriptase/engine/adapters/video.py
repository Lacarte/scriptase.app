"""Workflow adapter for the Animator node (`animator.generate`).

Dispatches generically through the `animator` provider hub (step 14.3). The
adapter no longer knows how any provider starts a job: it resolves one, builds
the §32.5 request, and hands it to the shared media-job service, which owns the
deadline, cadence, cancellation, progress, and aggregation (step 14.1).

The node payload is unchanged — `{total, ready, errors, provider}` plus
artifact refs — so the `assets` port, the cache, and every downstream consumer
see what they always did. Remote `urls` never cross into the port (D38).
"""

from __future__ import annotations

import os

from pydantic import ValidationError

from config import ANIMATOR_DIR

from scriptase.modules.video.providers.contract import AnimatorRequest

from .common import (
    AdapterError,
    inherited_config,
    outputs,
    project_id,
    provider_id,
    provider_run_options,
    resolve_provider,
    with_artifacts,
)
from .media_job import run_manifest_job

DOMAIN = "video"


def _canonical_provider_id(selected: str) -> str:
    """Resolve an instance id, type id, or alias to the registry type id."""
    from scriptase.providers.hub import hub

    from .common import resolve_provider_binding

    _iid, type_id = resolve_provider_binding(DOMAIN, selected)
    package = hub.get(DOMAIN, type_id)
    return package.id if package is not None else type_id


def _resolved_settings(provider: str) -> dict:
    """The instance's durable settings with the env fallback applied (§22.6)."""
    from scriptase.providers import settings_manager
    from scriptase.providers.hub import hub

    from .common import resolve_provider_binding

    instance_id, type_id = resolve_provider_binding(DOMAIN, provider)
    saved = settings_manager.get_instance_settings(DOMAIN, instance_id)
    package = hub.get(DOMAIN, type_id)
    return package.resolve_settings(saved) if package is not None else dict(saved)


def _step_assets(scenes_result, config, pid, context):
    """Run the selected provider; the shared media-job service owns the wait."""
    try:
        request = AnimatorRequest.from_scenes(
            scenes_result.get("scenes") or [],
            aspect_ratio=config.get("aspect_ratio") or "9:16",
            mode=config.get("mode") or "video",
        )
    except ValidationError as exc:
        raise AdapterError(
            "SCENES_EMPTY", "No scenes have prompts for animation"
        ) from exc

    selected = config.get("animator_provider_override") or provider_id(DOMAIN, config)
    type_id = _canonical_provider_id(selected)
    provider = resolve_provider(DOMAIN, selected)
    options = dict(config.get("animator_provider_options") or {})
    # `mode` may still arrive as a top-level node field for compatibility.
    if config.get("mode") and "mode" not in options:
        options["mode"] = config["mode"]

    result = run_manifest_job(
        domain=DOMAIN,
        provider=type_id,
        project_id=pid,
        context=context,
        scenes=request.legacy_scenes(),
        manifest_path=os.path.join(ANIMATOR_DIR, pid, "grabber_job.json"),
        job_provider=provider,
        request=request,
        settings=_resolved_settings(selected),
        options=options,
        failure_code="ANIMATOR_FAILED",
        failure_details={"provider": type_id},
    )
    # The animator node has never exposed the raw per-scene map on its port,
    # and those entries still carry remote URLs for redownload (D38).
    result.pop("scene_statuses", None)
    result["provider"] = type_id
    return result


def generate(inputs, config, context):
    pid = project_id(context, inputs)
    merged = inherited_config(config, inputs.get("settings"))
    selected = provider_id(DOMAIN, merged)
    merged["animator_provider_override"] = selected
    merged["animator_provider_options"] = provider_run_options(DOMAIN, selected, merged)
    result = _step_assets(inputs["scenes"], merged, pid, context)
    # Verified live (step 6.1): a provider that errors every scene still
    # completes the job manifest — zero produced assets must fail the node.
    if not result.get("ready"):
        raise AdapterError(
            "ANIMATOR_FAILED",
            f"All {result.get('total', 0)} animator scenes failed",
            details={"errors": result.get("errors"), "provider": result.get("provider")},
        )
    asset_root = os.path.join(ANIMATOR_DIR, pid)
    result["artifact_refs"] = []
    if os.path.isdir(asset_root):
        result["artifact_refs"] = [
            "animator/" + os.path.relpath(os.path.join(root, name), ANIMATOR_DIR).replace("\\", "/")
            for root, _dirs, files in os.walk(asset_root) for name in files
        ]
    return outputs(
        assets=with_artifacts(
            {**result, "project_id": pid},
            os.path.join(ANIMATOR_DIR, pid, "grabber_job.json"),
        )
    )
