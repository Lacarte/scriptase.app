"""Workflow adapter for the Animator node (`animator.generate`).

Dispatches generically through the `animator` provider hub (step 14.3). The
adapter no longer knows how any provider starts a job: it resolves one, builds
the §32.5 request, and hands it to the shared media-job service, which owns the
deadline, cadence, cancellation, progress, and aggregation (step 14.1).

Step 6.2 — optional image dependency: when the optional ``storyboard`` port is
connected the run prefers ``image_to_video``; when it is absent the selected
provider must grant ``text_to_video`` and consumes Scene Director output only.
Never silently substitute a different provider.

The node payload is unchanged — `{total, ready, errors, provider}` plus
artifact refs — so the `assets` port, the cache, and every downstream consumer
see what they always did. Remote `urls` never cross into the port (D38).
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from pydantic import ValidationError

from config import ANIMATOR_DIR

from scriptase.modules.scene_director.providers.contract import coerce_scene_specs
from scriptase.modules.video.providers.contract import AnimatorRequest
from scriptase.modules.video.routing import (
    VideoCapabilityError,
    resolve_motion_mode,
    storyboard_is_present,
)

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


def _provider_capabilities(selected: str) -> dict[str, bool]:
    """Granted capabilities of the selected type (empty when unknown)."""
    from scriptase.providers.hub import hub

    from .common import resolve_provider_binding

    _iid, type_id = resolve_provider_binding(DOMAIN, selected)
    package = hub.get(DOMAIN, type_id)
    if package is None:
        return {}
    caps = getattr(package, "capabilities", None)
    if isinstance(caps, Mapping):
        return dict(caps)
    manifest = getattr(package, "manifest", None)
    raw = getattr(manifest, "capabilities", None) if manifest is not None else None
    return dict(raw) if isinstance(raw, Mapping) else {}


def _resolved_settings(provider: str) -> dict:
    """The instance's durable settings with the env fallback applied (§22.6)."""
    from scriptase.providers import settings_manager
    from scriptase.providers.hub import hub

    from .common import resolve_provider_binding

    instance_id, type_id = resolve_provider_binding(DOMAIN, provider)
    saved = settings_manager.get_instance_settings(DOMAIN, instance_id)
    package = hub.get(DOMAIN, type_id)
    if package is None:
        return dict(saved)
    return package.resolve_settings(saved, instance_id=instance_id)


def _resolve_motion_mode_for_run(
    *,
    has_storyboard: bool,
    selected: str,
    type_id: str,
) -> str:
    """Capability gate for the graph shape; raises AdapterError on mismatch."""
    try:
        return resolve_motion_mode(
            has_storyboard=has_storyboard,
            capabilities=_provider_capabilities(selected),
        )
    except VideoCapabilityError as exc:
        details = dict(exc.details)
        details["provider"] = type_id
        raise AdapterError(exc.code, exc.message, details=details) from exc


def _step_assets(
    scenes_result,
    config,
    pid,
    context,
    *,
    has_storyboard: bool = False,
):
    """Run the selected provider; the shared media-job service owns the wait."""
    # Step 5.1: adapters consume SceneSpec, not loose dicts. Motion prompt is
    # preferred; image_prompt is the i2v fallback inside SceneSpec.
    specs = coerce_scene_specs((scenes_result or {}).get("scenes") or [])
    try:
        request = AnimatorRequest.from_scene_specs(
            specs,
            aspect_ratio=config.get("aspect_ratio") or "9:16",
            mode=config.get("mode") or "video",
        )
    except ValidationError as exc:
        raise AdapterError(
            "SCENES_EMPTY", "No scenes have prompts for animation"
        ) from exc

    selected = config.get("animator_provider_override") or provider_id(DOMAIN, config)
    type_id = _canonical_provider_id(selected)
    motion_mode = _resolve_motion_mode_for_run(
        has_storyboard=has_storyboard,
        selected=selected,
        type_id=type_id,
    )
    provider = resolve_provider(DOMAIN, selected)
    options = dict(config.get("animator_provider_options") or {})
    # `mode` may still arrive as a top-level node field for compatibility.
    if config.get("mode") and "mode" not in options:
        options["mode"] = config["mode"]
    # Record the resolved motion path so media-job / provider logs can tell
    # image_to_video from text_to_video without re-deriving the graph shape.
    options.setdefault("motion_mode", motion_mode)

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
        failure_details={"provider": type_id, "motion_mode": motion_mode},
    )
    # The animator node has never exposed the raw per-scene map on its port,
    # and those entries still carry remote URLs for redownload (D38).
    result.pop("scene_statuses", None)
    result["provider"] = type_id
    result["motion_mode"] = motion_mode
    return result


def generate(inputs, config, context):
    pid = project_id(context, inputs)
    merged = inherited_config(config, inputs.get("settings"))
    selected = provider_id(DOMAIN, merged)
    merged["animator_provider_override"] = selected
    merged["animator_provider_options"] = provider_run_options(DOMAIN, selected, merged)
    has_storyboard = storyboard_is_present(inputs)
    result = _step_assets(
        inputs["scenes"],
        merged,
        pid,
        context,
        has_storyboard=has_storyboard,
    )
    # Verified live (step 6.1): a provider that errors every scene still
    # completes the job manifest — zero produced assets must fail the node.
    if not result.get("ready"):
        raise AdapterError(
            "ANIMATOR_FAILED",
            f"All {result.get('total', 0)} animator scenes failed",
            details={
                "errors": result.get("errors"),
                "provider": result.get("provider"),
                "motion_mode": result.get("motion_mode"),
            },
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
