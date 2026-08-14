"""Domain catalog — the single declaration of the supported provider domains.

Frozen by contracts.md §19.1: exactly five domains (Music and Captions are out of
scope by owner decision). Adding a sixth domain is one `DomainSpec` entry plus a
provider folder — it must not require editing the registry class, the settings
manager, a route, or a Vue component.

This module is the only place a domain name is written down. `ProviderRegistry.VALID_DOMAINS`,
`settings_manager.validate_settings`, and `settings_manager._default_settings` all derive
from `DOMAINS` so they can never drift.

Step 0.2 renames three domain ids alongside their packages
(`scene_blueprint`→`scene_director`, `storyboard`→`image`, `animator`→`video`).
Domains being data is exactly the property that makes that a one-file change.
`DOMAIN_ALIASES` keeps settings files, saved workflows, and API callers written
against the V2 spellings resolving; `canonical_domain()` is the single
translation point.
"""

import os
from dataclasses import dataclass

from config import ROOT_DIR


# Capabilities every domain understands (contracts.md §20.4).
#
# `exclusive_execution` is added by step 15.1. It is a scheduling property, not a
# feature: a provider owning a heavy in-process singleton (§20.2 `local`) declares
# it, and the platform serializes that provider's invocations on one process-wide
# lock. It belongs in the shared set rather than the `tts` vocabulary because
# nothing about it is TTS-specific — any domain may ship a local provider.
SHARED_CAPABILITIES = frozenset({
    "test_connection",
    "single_scene",
    "batch",
    "async_job",
    "push_callbacks",
    "cancel",
    "progress",
    "exclusive_execution",
})


@dataclass(frozen=True)
class DomainSpec:
    """Declarative description of one provider domain."""

    id: str
    label: str
    package: str
    providers_base: str
    default_provider: str
    capability_vocabulary: frozenset[str]
    legacy_selection_key: str | None = None
    request_model: str | None = None
    result_model: str | None = None


def _base(*parts: str) -> str:
    return os.path.join(ROOT_DIR, *parts)


def _caps(*extra: str) -> frozenset[str]:
    return SHARED_CAPABILITIES | frozenset(extra)


# Declaration order is the discovery/registration order (contracts.md §21.2).
DOMAINS: dict[str, DomainSpec] = {
    spec.id: spec
    for spec in (
        DomainSpec(
            id="script",
            label="Script / Story",
            package="scriptase.modules.script.providers",
            providers_base=_base("scriptase", "modules", "script", "providers"),
            # Historical AI path (step 13.2). The 12.3 `builtin` bridge ID remains
            # a permanent *input* alias on the gemini package (contracts.md §40.3).
            default_provider="gemini",
            capability_vocabulary=_caps("structured_sections", "language_select", "offline"),
            request_model="scriptase.modules.script.providers.contract:ScriptRequest",
            result_model="scriptase.modules.script.providers.contract:ScriptResultPayload",
        ),
        DomainSpec(
            id="scene_director",
            label="Scene Director",
            package="scriptase.modules.scene_director.providers",
            providers_base=_base("scriptase", "modules", "scene_director", "providers"),
            # Historical AI path (step 13.4). The 12.3 `builtin` bridge ID remains
            # a permanent *input* alias on the n8n package (contracts.md §40.3).
            default_provider="n8n",
            capability_vocabulary=_caps("chaptering", "coherence_scoring", "sfx_report"),
            request_model="scriptase.modules.scene_director.providers.contract:SceneBlueprintRequest",
            result_model="scriptase.modules.scene_director.providers.contract:SceneBlueprintResultPayload",
        ),
        DomainSpec(
            id="tts",
            label="Text to Speech",
            package="scriptase.modules.tts.providers",
            providers_base=_base("scriptase", "modules", "tts", "providers"),
            default_provider="kokoro",
            capability_vocabulary=_caps(
                "streaming",
                "voice_list",
                "voice_blend",
                "speed_control",
                "model_download",
                # Step 5.3: when True, Timing AUTO normalises provider word
                # timestamps instead of running Whisper force-alignment.
                "native_word_timing",
            ),
            legacy_selection_key="sts-tts-provider",
            request_model="scriptase.modules.tts.providers.contract:TTSRequest",
            result_model="scriptase.modules.tts.providers.contract:TTSResultPayload",
        ),
        DomainSpec(
            id="image",
            label="Image",
            package="scriptase.modules.image.providers",
            providers_base=_base("scriptase", "modules", "image", "providers"),
            default_provider="gemini_ws",
            # Step 6.1 routing vocabulary (text_to_image / image_edit /
            # reference_image / inpainting) plus operational flags already
            # declared by shipped providers. `auto_animate` is the image→video
            # hand-off the Gemini extension performs on job completion:
            # declared by the provider that does it, never hardcoded.
            capability_vocabulary=_caps(
                "text_to_image",
                "image_edit",
                "reference_image",
                "inpainting",
                "watermark_removal",
                "prompt_prefix",
                "auto_animate",
            ),
            legacy_selection_key="sts-storyboard-provider",
            request_model="scriptase.modules.image.providers.contract:StoryboardRequest",
            result_model="scriptase.modules.image.providers.contract:StoryboardResultPayload",
        ),
        DomainSpec(
            id="video",
            label="Video",
            package="scriptase.modules.video.providers",
            providers_base=_base("scriptase", "modules", "video", "providers"),
            default_provider="grok_automa",
            # Step 6.1 routing vocabulary (image_to_video / text_to_video /
            # reference_image / duration_control). `resolution_select` stays so
            # providers that expose it keep declaring it without a platform edit.
            capability_vocabulary=_caps(
                "image_to_video",
                "text_to_video",
                "reference_image",
                "duration_control",
                "resolution_select",
            ),
            legacy_selection_key="sts-asset-provider",
            request_model="scriptase.modules.video.providers.contract:AnimatorRequest",
            result_model="scriptase.modules.video.providers.contract:AnimatorResultPayload",
        ),
    )
}

DOMAIN_IDS: frozenset[str] = frozenset(DOMAINS)

# V2 domain spellings, retired in step 0.2 when the packages were renamed. These
# are *input* aliases only: nothing serializes them back out, exactly as a
# provider manifest alias never becomes a canonical id (contracts.md §40.3).
# They exist so an imported V2 `settings.json`, a workflow saved before the
# rename, and an API caller written against the old wire value all keep
# resolving. Phase 10.1 rewrites persisted documents; until then this map is
# what makes those documents readable.
DOMAIN_ALIASES: dict[str, str] = {
    "scene_blueprint": "scene_director",
    "storyboard": "image",
    "animator": "video",
}


def canonical_domain(domain_id: str) -> str:
    """Resolve a domain id or retired V2 alias to its canonical id.

    Unknown ids are returned unchanged so the caller's own error path — which
    knows whether an unknown domain is a 404, a validation problem, or an empty
    list — stays in charge of reporting it.
    """
    if domain_id in DOMAINS:
        return domain_id
    return DOMAIN_ALIASES.get(domain_id, domain_id)


def get_domain(domain_id: str) -> DomainSpec:
    """Return the `DomainSpec` for `domain_id`, or raise `ValueError`.

    Retired V2 domain spellings resolve through `DOMAIN_ALIASES`.
    """
    try:
        return DOMAINS[canonical_domain(domain_id)]
    except KeyError:
        raise ValueError(
            f"Unknown provider domain: {domain_id!r}. Known domains: {sorted(DOMAINS)}"
        ) from None


__all__ = [
    "DomainSpec",
    "DOMAINS",
    "DOMAIN_ALIASES",
    "DOMAIN_IDS",
    "SHARED_CAPABILITIES",
    "canonical_domain",
    "get_domain",
]
