"""Workflow adapter for the Scene Blueprint node (`scenes.blueprint`).

Dispatches generically through the `scene_director` provider hub (step 13.4).
The adapter never imports a concrete scene service; adding another scene-
director provider is a package drop, not a node/adapter edit.
"""

from __future__ import annotations

import os

from config import SCENES_DIR
from scriptase.modules.scene_director.providers.contract import (
    SceneBlueprintResultPayload,
    coerce_scene_specs,
)
from scriptase.providers.errors import ProviderError
from scriptase.providers.hub import hub

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

DOMAIN = "scene_director"


def _canonical_provider_id(selected: str) -> str:
    """Resolve an instance id, type id, or alias to the registry type id."""
    from .common import resolve_provider_binding

    _iid, type_id = resolve_provider_binding(DOMAIN, selected)
    package = hub.get(DOMAIN, type_id)
    return package.id if package is not None else type_id


def blueprint(inputs, config, context):
    pid = project_id(context, inputs)
    merged = inherited_config(config, inputs.get("settings"), {"tone": "story_tone"})
    merged["text"] = inputs["script"]
    # Step 5.2: ensure structured Channel visual direction reaches the provider
    # even when the settings port was empty (e.g. V2-era project.setup with no
    # passthrough). Never compose prompt text here — typed block only.
    if not isinstance(merged.get("visual_direction"), dict):
        try:
            from scriptase.jobs.channel_settings import resolve_channel_settings

            channel_settings = resolve_channel_settings(context)
            visual_direction = (
                channel_settings.get("visual_direction")
                if isinstance(channel_settings, dict)
                else None
            )
            if isinstance(visual_direction, dict) and visual_direction:
                merged["visual_direction"] = visual_direction
        except Exception:
            pass
    # `provider_id` is absent on every workflow saved before step 12.3, so it
    # resolves to the domain default (`n8n` after 13.4). The transitional
    # `builtin` value remains an input alias of that provider (§40.3). M4 needs
    # no `type_version` bump (§41.3) because nothing is renamed on the node.
    # After 3.2 the stored value is an instance id.
    selected = provider_id(DOMAIN, merged)
    type_id = _canonical_provider_id(selected)
    provider = resolve_provider(DOMAIN, selected)
    # Request-wins merge of portable saved settings + per-run provider_options.
    merged.update(provider_run_options(DOMAIN, selected, merged))
    merged["provider_id"] = selected
    merged["provider_type"] = type_id
    try:
        result = provider.generate(inputs["segments"], merged, project_id=pid)
    except ProviderError as exc:
        raise exc.as_adapter_error() from exc
    except ValueError as exc:
        raise AdapterError("SCENES_CONFIG_INVALID", str(exc)) from exc
    path = result.pop("path", None) or os.path.join(SCENES_DIR, pid, "scenes.json")
    # Ensure the document carries the resolved identity even when a provider
    # forgets to stamp it (P33 / contracts §43).
    if not result.get("provider"):
        result["provider"] = type_id
    # Step 5.1: normalize every scene through SceneSpec so the scenes port
    # always carries the frozen §8 field set for image/video adapters.
    try:
        typed = SceneBlueprintResultPayload.from_mapping(result)
        result["scenes"] = typed.scenes_as_dicts()
    except (TypeError, ValueError):
        specs = coerce_scene_specs(result.get("scenes") or [])
        if specs:
            result["scenes"] = [spec.to_port_dict() for spec in specs]
    payload = with_artifacts(result, path)
    prompts = with_artifacts(
        {
            "project_id": pid,
            "image_prompts": [
                s.get("image_prompt", "") for s in result.get("scenes", [])
            ],
        },
        path,
    )
    return outputs(scenes=payload, image_prompts=prompts)
