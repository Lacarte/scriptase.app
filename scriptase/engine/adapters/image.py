"""Workflow adapter for the Storyboard node (`storyboard.generate`).

Dispatches generically through the `storyboard` provider hub (step 14.2). The
adapter no longer knows how any provider starts a job: it resolves one, builds
the §32.4 request, and hands it to the shared media-job service, which owns the
deadline, cadence, cancellation, progress, and aggregation (step 14.1).

The node payload is unchanged — `{total, ready, errors, scene_statuses}` plus
artifact refs — so the `images` port, the cache, and every downstream consumer
see what they always did.
"""

from __future__ import annotations

import os

from pydantic import ValidationError

from config import STORYBOARD_DIR

from scriptase.modules.image.providers.contract import StoryboardRequest
from scriptase.modules.scene_director.providers.contract import coerce_scene_specs

from .common import (
    AdapterError,
    inherited_config,
    outputs,
    project_id,
    provider_id,
    provider_run_options,
    provider_selection_reason,
    request_provider_override,
    resolve_provider,
    with_artifacts,
)
from .media_job import run_manifest_job

DOMAIN = "image"


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
    if package is None:
        return dict(saved)
    return package.resolve_settings(saved, instance_id=instance_id)


def _step_storyboard(scenes_result, config, pid, context):
    """Run the selected provider; the shared media-job service owns the wait."""
    # Step 5.1: adapters consume SceneSpec, not loose dicts.
    specs = coerce_scene_specs((scenes_result or {}).get("scenes") or [])
    try:
        request = StoryboardRequest.from_scene_specs(
            specs,
            aspect_ratio=config.get("aspect_ratio") or "9:16",
            style=config.get("style"),
        )
    except ValidationError as exc:
        raise AdapterError(
            "SCENES_EMPTY", "No scenes have image prompts for storyboard"
        ) from exc

    selected = (
        request_provider_override(config)
        or config.get("storyboard_provider_override")
        or provider_id(DOMAIN, config)
    )
    type_id = _canonical_provider_id(selected)
    provider = resolve_provider(DOMAIN, selected)
    options = dict(config.get("storyboard_provider_options") or {})
    # `image_model` is still a node field for compatibility; it reaches the
    # provider as the per-run option its settings schema declares (§26).
    if config.get("image_model"):
        options.setdefault("image_model", config["image_model"])

    from .common import resolve_fallback_chain_for_context, resolve_provider_binding

    chain = resolve_fallback_chain_for_context(
        DOMAIN, selected, context, config, stage="image"
    )

    def _resolve_type(iid: str) -> str:
        _iid, tid = resolve_provider_binding(DOMAIN, iid)
        return tid

    def _resolve_provider(iid: str):
        return resolve_provider(DOMAIN, iid)

    return run_manifest_job(
        domain=DOMAIN,
        provider=type_id,
        project_id=pid,
        context=context,
        scenes=request.legacy_scenes(),
        manifest_path=os.path.join(STORYBOARD_DIR, pid, "storyboard.json"),
        job_provider=provider,
        request=request,
        settings=_resolved_settings(selected),
        options=options,
        failure_code="STORYBOARD_FAILED",
        fallback_chain=chain,
        resolve_job_provider=_resolve_provider if len(chain) > 1 else None,
        resolve_settings=_resolved_settings if len(chain) > 1 else None,
        resolve_type=_resolve_type if len(chain) > 1 else None,
        provider_instance_id=selected,
        primary_selection_reason=provider_selection_reason(config),
        selection_reason=provider_selection_reason(config),
    )


def generate(inputs, config, context):
    pid = project_id(context, inputs)
    merged = inherited_config(config, inputs.get("settings"))
    selected = provider_id(DOMAIN, merged)
    merged["storyboard_provider_override"] = selected
    merged["storyboard_provider_options"] = provider_run_options(DOMAIN, selected, merged)
    result = _step_storyboard(inputs["scenes"], merged, pid, context)
    # Verified live (step 6.1): a provider failure such as a rejected API key
    # completes the manifest with only errors — that is a node failure, not a
    # success with zero images.
    if not result.get("ready"):
        raise AdapterError(
            "STORYBOARD_FAILED",
            f"All {result.get('total', 0)} storyboard scenes failed",
            details={"errors": result.get("errors")},
        )
    result["artifact_refs"] = [
        str(item.get("local_path")).replace("\\", "/").removeprefix("/output/")
        for item in result.get("scene_statuses", {}).values()
        if isinstance(item, dict) and item.get("local_path")
    ]
    return outputs(
        images=with_artifacts(
            {**result, "project_id": pid},
            os.path.join(STORYBOARD_DIR, pid, "storyboard.json"),
        )
    )
