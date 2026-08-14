"""Map a Job's channel snapshot onto project-settings keys.

Adapters merge these via ``inherited_config()`` (contracts.md §1 / product §4):
explicit node configuration wins; an empty string is not explicit. The snapshot
carries provider **instance references** only — never credentials.
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.engine.adapters.common import inherited_config


def channel_settings_from_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Flatten a channel snapshot into the settings dict project.setup emits.

    Keys match what downstream adapters already inherit (tone/style/voice/…)
    plus the legacy ``project.setup`` field names. Nested Channel blocks stay
    out of this dict so adapters never see structures they do not understand.
    """
    if not isinstance(snapshot, Mapping):
        return {}

    content = snapshot.get("content") if isinstance(snapshot.get("content"), Mapping) else {}
    visual = (
        snapshot.get("visual_direction")
        if isinstance(snapshot.get("visual_direction"), Mapping)
        else {}
    )
    audio = (
        snapshot.get("audio_defaults")
        if isinstance(snapshot.get("audio_defaults"), Mapping)
        else {}
    )
    branding = snapshot.get("branding") if isinstance(snapshot.get("branding"), Mapping) else {}
    export = (
        snapshot.get("export_defaults")
        if isinstance(snapshot.get("export_defaults"), Mapping)
        else {}
    )
    captions = snapshot.get("captions") if isinstance(snapshot.get("captions"), Mapping) else {}
    providers = (
        snapshot.get("provider_defaults")
        if isinstance(snapshot.get("provider_defaults"), Mapping)
        else {}
    )

    tone = _text(content.get("tone"))
    style = _text(visual.get("style"))
    aspect = _text(export.get("aspect_ratio"))

    settings: dict[str, Any] = {
        # project.setup field names
        "channel_name": _text(snapshot.get("name")),
        "tone": tone,
        "style": style,
        "aspect_ratio": aspect,
        # Adapter alias targets used by inherited_config(..., aliases=...)
        "story_tone": tone,
        "visual_style": style,
        # Audio defaults consumed by tts / music when node fields are empty
        "voice": _text(audio.get("voice")),
        "speed": audio.get("speed") if audio.get("speed") is not None else "",
        "music_profile": _text(audio.get("music_profile")),
        # Branding (setup-shaped; logo asset path resolution is step 1.7)
        "logo_enabled": bool(branding.get("enabled")),
        "logo_position": _text(branding.get("position")),
        # Captions are a local service — mode/preset fields only
        "caption_preset": _text(captions.get("preset")),
        "caption_position": _text(captions.get("position")),
        # Export
        "export_profile": _text(export.get("profile")),
        "fps": export.get("fps") if export.get("fps") is not None else "",
        # Provider instance *references* (ids only) for later instance-aware routing
        "provider_defaults": {
            key: value
            for key, value in providers.items()
            if isinstance(key, str) and _text(value)
        },
    }

    # Drop empty strings so inherited_config treats them as non-explicit when
    # nested further (explicit empty never overrides non-empty inherited).
    return {key: value for key, value in settings.items() if value not in (None, "")}


def merge_node_config_with_channel(
    node_config: Mapping[str, Any] | None,
    channel_settings: Mapping[str, Any] | None,
    *,
    aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Explicit node config beats channel settings; empty string is not explicit."""
    return inherited_config(node_config, channel_settings, aliases=aliases)


def script_text_from_source(source: Mapping[str, Any] | None) -> str:
    """Resolve the Script-stage text a Job should feed into ``script.input``.

    ``paste`` / ``manual`` prefer ``pasted_script``; ``idea`` / ``topic`` /
    ``automatic`` fall through the idea → topic → pasted chain so a Job always
    has one narration string for the default full-video graph.
    """
    if not isinstance(source, Mapping):
        return ""
    mode = _text(source.get("mode")) or "topic"
    pasted = _text(source.get("pasted_script"))
    idea = _text(source.get("idea"))
    topic = _text(source.get("topic"))
    if mode in {"paste", "manual"}:
        return pasted or idea or topic
    if mode == "idea":
        return idea or topic or pasted
    if mode == "topic":
        return topic or idea or pasted
    # automatic — still needs *some* seed text for script.input graphs
    return idea or topic or pasted


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = [
    "channel_settings_from_snapshot",
    "merge_node_config_with_channel",
    "script_text_from_source",
]
