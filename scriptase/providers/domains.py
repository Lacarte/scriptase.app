"""Domain catalog — the single declaration of the supported provider domains.

Music and Captions are out of scope by owner decision (local services, not
provider domains). Adding a domain is one `DomainSpec` entry plus a provider
folder — it must not require editing the registry class, the settings manager, a
route, or a Vue component. Step 7.3 added `review` that way.

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
    default_provider: str | None
    capability_vocabulary: frozenset[str]
    legacy_selection_key: str | None = None
    request_model: str | None = None
    result_model: str | None = None
    # Product catalogue allowlist. ``None`` deliberately means unrestricted so
    # fixture/plugin DomainSpecs keep proving folder-only extensibility.  The
    # shipped specs use an explicit set (including the empty set) so provider
    # packages can remain on disk for contract tests without reaching the UI.
    catalog_provider_ids: frozenset[str] | None = None
    contract_provider_ids: frozenset[str] = frozenset()
    # Extra catalog types a fresh install binds beyond ``default_provider`` so a
    # non-default provider still appears on the settings page out of the box.
    # Each entry is ``(type_id, label)``. Provider ids belong on the spec (§19.1),
    # which keeps the seeding logic in settings_manager a §26 zero-touch surface.
    seeded_instances: tuple[tuple[str, str], ...] = ()
    # Display label for the seeded *default* instance. Defaults to the provider
    # id; set it when the settings page should read a friendlier name.
    default_instance_label: str | None = None


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
            # Step 7.1 restores the catalogue that step 5.3 emptied: Auto and
            # Idea source modes need a script provider, so both shipped
            # providers are exposed. The 12.3 `builtin` bridge ID and the former
            # `gemini` id both remain permanent *input* aliases on the
            # script_n8n package (contracts.md §40.3).
            default_provider="script_n8n",
            capability_vocabulary=_caps("structured_sections", "language_select", "offline"),
            request_model="scriptase.modules.script.providers.contract:ScriptRequest",
            result_model="scriptase.modules.script.providers.contract:ScriptResultPayload",
            catalog_provider_ids=frozenset({"script_n8n", "n8n", "random_template"}),
            contract_provider_ids=frozenset({"scaffold_check"}),
            # Friendly settings-page labels: the script_n8n default reads as
            # "Story Generator", and the n8n passerelle "Script Generator" is
            # seeded beside it so both show without hand-configuration.
            default_instance_label="Story Generator",
            seeded_instances=(("n8n", "Script Generator"),),
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
            catalog_provider_ids=frozenset({"n8n"}),
            # The n8n passerelle reads as "Scene Director" on the settings page —
            # the same name as the capability, since it is the one provider for it.
            default_instance_label="Scene Director",
        ),
        DomainSpec(
            id="tts",
            label="Text to Speech",
            package="scriptase.modules.tts.providers",
            providers_base=_base("scriptase", "modules", "tts", "providers"),
            default_provider="inworld",
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
            catalog_provider_ids=frozenset({"inworld"}),
            default_instance_label="Voice Generator",
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
            catalog_provider_ids=frozenset({"gemini_ws"}),
            default_instance_label="Image Generator",
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
            catalog_provider_ids=frozenset({"grok_automa"}),
            default_instance_label="Video Generator",
        ),
        # Step 7.3 — sixth domain. Semantic / AI review producing structured
        # ReviewIssue records. Deterministic technical validators (7.1) stay
        # outside the provider platform; this domain is the expensive layer.
        DomainSpec(
            id="review",
            label="Review",
            package="scriptase.review.providers",
            providers_base=_base("scriptase", "review", "providers"),
            default_provider=None,
            capability_vocabulary=_caps(
                "image_review",
                "video_review",
                "text_review",
                "structured_output",
            ),
            request_model="scriptase.review.providers.contract:ReviewRequest",
            result_model="scriptase.review.providers.contract:ReviewResultPayload",
            catalog_provider_ids=frozenset(),
        ),
        # Step 16.2 — seventh domain, and the only *optional* one: no stage
        # depends on a virality score, so a graph without `script.analyze`
        # never resolves a provider here at all. The shipped default is the
        # offline deterministic scorer from 16.1, which costs nothing and
        # always answers; the domain exists so an LLM judge can replace the
        # arithmetic later without touching the node contract.
        DomainSpec(
            id="viral",
            label="Virality",
            package="scriptase.modules.viral.providers",
            providers_base=_base("scriptase", "modules", "viral", "providers"),
            default_provider="deterministic",
            capability_vocabulary=_caps(
                # Scores a whole script into a 0-100 number and a band.
                "script_scoring",
                # Returns the per-dimension breakdown the Script stage panel
                # renders (16.3). A judge that only answers with a total
                # declares this False and the panel shows the total alone.
                "dimension_breakdown",
                # No network and no credentials — the property that lets this
                # run on every script before a paid stage does.
                "offline",
            ),
            request_model="scriptase.modules.viral.providers.contract:ViralRequest",
            result_model="scriptase.modules.viral.providers.contract:ViralResultPayload",
            catalog_provider_ids=frozenset({"deterministic", "llm_judge"}),
            default_instance_label="Virality Scorer",
        ),
    )
}

DOMAIN_IDS: frozenset[str] = frozenset(DOMAINS)

# V2 domain spellings, retired in step 0.2 when the packages were renamed. These
# are *input* aliases only: nothing serializes them back out, exactly as a
# provider manifest alias never becomes a canonical id (contracts.md §40.3).
# They exist so a pre-migration V2 `settings.json`, a workflow saved before the
# rename, and an API caller written against the old wire value all keep
# resolving. Step 10.1 (`scriptase.migration.v2`) rewrites persisted documents
# through settings migration v5 so stored blocks use the canonical keys; this
# map remains the runtime input alias for un-migrated callers.
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
