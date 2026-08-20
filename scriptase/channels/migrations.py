"""Forward-only schema migrations for ChannelProfile documents.

Mirrors ``scriptase.providers.settings_migrations``: ``MIGRATIONS`` maps a
**target** schema version to the function that upgrades data from the previous
version to it. ``apply_migrations`` runs every registered target greater than
the stored version, in ascending order, and stamps ``schema_version`` after
each step.

``schema_version`` is the document-format revision. It is distinct from the
content ``version`` field, which the store bumps on every successful update.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from scriptase.channels.models import (
    CHANNEL_SCHEMA_VERSION,
    DEFAULT_MUSIC_FOLDER,
    DEFAULT_SCRIPT_TEMPLATE_BRIEF,
    DEFAULT_SCRIPT_TEMPLATE_SECTIONS,
    DEFAULT_VISUAL_STYLE_PROMPT,
)

# Freshly written Channel documents carry this schema_version.
SCHEMA_VERSION = CHANNEL_SCHEMA_VERSION

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _register(version: int):
    """Register the function that upgrades a document *to* ``version``."""

    def decorator(func: Callable[[dict[str, Any]], dict[str, Any]]):
        MIGRATIONS[version] = func
        return func

    return decorator


@_register(2)
def _add_script_template(data: dict[str, Any]) -> dict[str, Any]:
    """Add the step 2.1 template to legacy Channel documents."""
    migrated = deepcopy(data)
    migrated.setdefault("script_template", {
        "brief": DEFAULT_SCRIPT_TEMPLATE_BRIEF,
        "sections": list(DEFAULT_SCRIPT_TEMPLATE_SECTIONS),
    })
    return migrated


@_register(3)
def _add_visual_style_prompt(data: dict[str, Any]) -> dict[str, Any]:
    """Add the step 2.2 house-look prompt to legacy Channel documents."""
    migrated = deepcopy(data)
    visual = migrated.get("visual_direction")
    if not isinstance(visual, dict):
        visual = {}
        migrated["visual_direction"] = visual
    if not str(visual.get("style_prompt") or "").strip():
        # Preserve the old Channel's chosen look when possible.  Blank legacy
        # Channels receive the same useful default as newly created Channels.
        visual["style_prompt"] = (
            str(visual.get("style") or "").strip() or DEFAULT_VISUAL_STYLE_PROMPT
        )
    return migrated


@_register(4)
def _add_narration_processing(data: dict[str, Any]) -> dict[str, Any]:
    """Add the step 2.3 silence-processing default to legacy Channels."""
    migrated = deepcopy(data)
    audio = migrated.get("audio_defaults")
    if not isinstance(audio, dict):
        audio = {}
        migrated["audio_defaults"] = audio
    audio.setdefault("remove_silence", True)
    return migrated


@_register(5)
def _add_channel_media_library(data: dict[str, Any]) -> dict[str, Any]:
    """Add step 2.4 thumbnail and music collection defaults."""
    migrated = deepcopy(data)
    branding = migrated.get("branding")
    if not isinstance(branding, dict):
        branding = {}
        migrated["branding"] = branding
    branding.setdefault("thumbnail_asset_id", None)
    migrated.setdefault("music_library", {"folder": "", "tracks": []})
    return migrated


_PROTOTYPE_PROVIDER_REPLACEMENTS: dict[str, dict[str, str | None]] = {
    # Step 7.1 restored gemini and random_template to the script catalogue;
    # only the legacy bridge alias and the contract-only provider still retire.
    "script": {
        "builtin": "gemini",
        "scaffold_check": None,
    },
    "tts": {"kokoro": "inworld"},
    "scene_director": {"builtin": "n8n"},
    "image": {
        "gemini": "gemini_ws",
        "wavespeed": "gemini_ws",
        "webhook": "gemini_ws",
        "direct": "gemini_ws",
        "wavespeed_direct": "gemini_ws",
        "wavespeed_webhook": "gemini_ws",
    },
    "video": {
        "grok": "grok_automa",
        "midjourney": "grok_automa",
        "kie-ai": "grok_automa",
        "kie_ai": "grok_automa",
    },
    "review": {"semantic": None},
}


def _replacement(domain: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return _PROTOTYPE_PROVIDER_REPLACEMENTS.get(domain, {}).get(value, value)


@_register(6)
def _restrict_provider_references(data: dict[str, Any]) -> dict[str, Any]:
    """Rewrite direct retired-provider ids in a Channel (step 5.3).

    Named instance ids are intentionally left alone: settings migration v10
    changes their provider type in place, so their stable references remain
    valid. Only default instance ids equal a retired type id and need rewriting.
    """
    migrated = deepcopy(data)
    defaults = migrated.get("provider_defaults")
    if isinstance(defaults, dict):
        for domain in tuple(defaults):
            defaults[domain] = _replacement(domain, defaults[domain])

    audio = migrated.get("audio_defaults")
    if isinstance(audio, dict):
        audio["tts_provider_instance_id"] = _replacement(
            "tts", audio.get("tts_provider_instance_id")
        )

    policies = migrated.get("fallback_policies")
    if isinstance(policies, dict):
        for domain, policy in policies.items():
            if not isinstance(policy, dict):
                continue
            policy["primary"] = _replacement(domain, policy.get("primary"))
            fallbacks = policy.get("fallbacks")
            if isinstance(fallbacks, list):
                rewritten: list[str] = []
                for item in fallbacks:
                    replacement = _replacement(domain, item)
                    if isinstance(replacement, str) and replacement and replacement not in rewritten:
                        rewritten.append(replacement)
                policy["fallbacks"] = rewritten
    return migrated


@_register(7)
def _add_presentation_identity(data: dict[str, Any]) -> dict[str, Any]:
    """Add the prototype's accent colour and platform chips."""
    migrated = deepcopy(data)
    branding = migrated.get("branding")
    if not isinstance(branding, dict):
        branding = {}
        migrated["branding"] = branding
    branding.setdefault("accent_color", None)
    content = migrated.get("content")
    if not isinstance(content, dict):
        content = {}
        migrated["content"] = content
    content.setdefault("platforms", [])
    return migrated


@_register(8)
def _add_random_music_default(data: dict[str, Any]) -> dict[str, Any]:
    """Add the random-music default and the bundled music folder.

    ``music_random`` is on by default for new Channels, but a legacy Channel
    that already curated a specific ``music_profile`` kept a deliberate choice —
    flipping it to random would silently change its output. So the default is
    ``True`` only when no bed was chosen, and ``False`` otherwise. The music
    ``folder`` is defaulted to the bundled location only when it is blank, never
    overwriting a folder the user set.
    """
    migrated = deepcopy(data)
    audio = migrated.get("audio_defaults")
    if not isinstance(audio, dict):
        audio = {}
        migrated["audio_defaults"] = audio
    if "music_random" not in audio:
        audio["music_random"] = not str(audio.get("music_profile") or "").strip()

    library = migrated.get("music_library")
    if not isinstance(library, dict):
        library = {"tracks": []}
        migrated["music_library"] = library
    if not str(library.get("folder") or "").strip():
        library["folder"] = DEFAULT_MUSIC_FOLDER
    return migrated


# Future schema changes register the next consecutive target here and land in
# the same step that changes the model (CLAUDE.md non-negotiable).


def apply_migrations(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Upgrade ``data`` to ``SCHEMA_VERSION``.

    Returns ``(migrated_data, changed)``. ``changed`` is ``True`` only when a
    migration ran, so an already-current document is not rewritten — the
    migration is idempotent and the version stamp is the completion marker.

    Missing or non-integer ``schema_version`` is treated as 0 so a pre-stamp
    document still walks every registered hop.
    """
    if not isinstance(data, dict):
        raise TypeError("channel document must be an object")

    current = data.get("schema_version")
    if not isinstance(current, int) or isinstance(current, bool):
        current = 0

    migrated = deepcopy(data)
    changed = False

    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        migrated = MIGRATIONS[version](migrated)
        # Stamped per step: an interrupted write leaves the previous version on
        # disk and the next load retries from there.
        migrated["schema_version"] = version
        changed = True
        current = version

    if migrated.get("schema_version") != SCHEMA_VERSION:
        # No hops registered yet (v1 is the birth version): still stamp so
        # documents written without the field become current on first load.
        if current < SCHEMA_VERSION and not MIGRATIONS:
            migrated["schema_version"] = SCHEMA_VERSION
            changed = True
        elif changed:
            migrated["schema_version"] = SCHEMA_VERSION

    return migrated, changed


__all__ = [
    "SCHEMA_VERSION",
    "MIGRATIONS",
    "apply_migrations",
]
