"""Workflow adapter for the Story Generator node (`story.generate`).

Dispatches generically through the `script` provider hub (steps 13.1–13.3). The
adapter never imports a concrete story service; adding another script provider
is a package drop, not a node/adapter edit.
"""

from __future__ import annotations

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

DOMAIN = "script"


def _canonical_provider_id(selected: str) -> str:
    """Resolve an id or alias to the registry's canonical provider id."""
    instance = hub.get(DOMAIN, selected)
    return instance.id if instance is not None else selected


def generate(inputs, config, context):
    configuration = inherited_config(
        config,
        inputs.get("settings"),
        aliases={"style": "preset_style", "tone": "story_tone"},
    )
    configuration["project_name_id"] = project_id(context, inputs)
    # `provider_id` is absent on every workflow saved before step 12.3, so it
    # resolves to the domain default (`gemini` after 13.2). The transitional
    # `builtin` value remains an input alias of that provider (§40.3). M4 needs
    # no `type_version` bump (§41.3) because nothing is renamed on the node.
    selected = provider_id(DOMAIN, configuration)
    canonical = _canonical_provider_id(selected)
    provider = resolve_provider(DOMAIN, selected)
    # Request-wins merge of portable saved settings + per-run provider_options.
    # The merged keys become part of the configuration the provider sees; the
    # saved workflow configuration is not rewritten, so fingerprints stay
    # stable for M4 while still differing when provider_id / provider_options
    # change (step 13.3 cache requirement).
    configuration.update(provider_run_options(DOMAIN, selected, configuration))
    configuration["provider_id"] = canonical
    try:
        result = provider.generate(
            configuration, project_id=configuration["project_name_id"]
        )
    except ProviderError as exc:
        raise exc.as_adapter_error() from exc
    except ValueError as exc:
        raise AdapterError("STORY_CONFIG_INVALID", str(exc)) from exc
    path = result.pop("path")
    # Ensure the document metadata carries the resolved identity even when a
    # provider forgets to stamp it (P33 / contracts §43).
    metadata = result.get("metadata")
    if isinstance(metadata, dict) and not metadata.get("provider"):
        metadata["provider"] = canonical
    return outputs(
        script=result["story_text"],
        story=with_artifacts(result, path),
    )
