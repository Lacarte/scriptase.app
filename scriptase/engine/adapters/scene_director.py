"""Workflow adapter for the Scene Blueprint node (`scenes.blueprint`).

Dispatches generically through the `scene_director` provider hub (step 13.4).
The adapter never imports a concrete scene service; adding another scene-
director provider is a package drop, not a node/adapter edit.
"""

from __future__ import annotations

import os

from config import SCENES_DIR
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
    """Resolve an id or alias to the registry's canonical provider id."""
    instance = hub.get(DOMAIN, selected)
    return instance.id if instance is not None else selected


def blueprint(inputs, config, context):
    pid = project_id(context, inputs)
    merged = inherited_config(config, inputs.get("settings"), {"tone": "story_tone"})
    merged["text"] = inputs["script"]
    # `provider_id` is absent on every workflow saved before step 12.3, so it
    # resolves to the domain default (`n8n` after 13.4). The transitional
    # `builtin` value remains an input alias of that provider (§40.3). M4 needs
    # no `type_version` bump (§41.3) because nothing is renamed on the node.
    selected = provider_id(DOMAIN, merged)
    canonical = _canonical_provider_id(selected)
    provider = resolve_provider(DOMAIN, selected)
    # Request-wins merge of portable saved settings + per-run provider_options.
    merged.update(provider_run_options(DOMAIN, selected, merged))
    merged["provider_id"] = canonical
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
        result["provider"] = canonical
    payload = with_artifacts(result, path)
    prompts = with_artifacts(
        {
            "project_id": pid,
            "image_prompts": [s.get("image_prompt", "") for s in result.get("scenes", [])],
        },
        path,
    )
    return outputs(scenes=payload, image_prompts=prompts)
