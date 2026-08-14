"""Map a Job's channel snapshot onto project-settings keys.

Adapters merge these via ``inherited_config()`` (contracts.md §1 / product §4):
explicit node configuration wins; an empty string is not explicit. The snapshot
carries provider **instance references** only — never credentials.

``project.setup`` (step 1.7) is the reader of the Job channel snapshot: empty
fields on a V2-era node yield to channel values; the logo block is inherited as
a package when the node has no managed logo asset of its own.
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.engine.adapters.common import inherited_config

# project.setup schema field names that map from a channel snapshot.
_SETUP_FIELD_NAMES: frozenset[str] = frozenset({
    "channel_name",
    "tone",
    "style",
    "aspect_ratio",
    "logo_enabled",
    "logo",
    "logo_position",
    "logo_size",
    "logo_opacity",
    "logo_margin",
})

# Logo presentation keys travel with the logo package.
_LOGO_PACKAGE_KEYS: frozenset[str] = frozenset({
    "logo",
    "logo_enabled",
    "logo_position",
    "logo_size",
    "logo_opacity",
    "logo_margin",
})


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
    fallback_policies = (
        snapshot.get("fallback_policies")
        if isinstance(snapshot.get("fallback_policies"), Mapping)
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
        # Step 8.3: stage → {primary, fallbacks[]} for runtime chain execution.
        # Values are instance ids only — never credentials.
        "fallback_policies": {
            key: value
            for key, value in fallback_policies.items()
            if isinstance(key, str) and value not in (None, "", {}, [])
        },
    }

    # Step 5.2: structured Channel visual direction for Scene Director.
    # Nested object (pattern is structured, never free text). Provider packages
    # own prompt wording; adapters only forward the typed block.
    visual_direction = _visual_direction_block(visual)
    if visual_direction:
        settings["visual_direction"] = visual_direction

    # Branding → setup logo block (managed ref only; never a filesystem path).
    settings.update(_logo_settings_from_branding(branding))

    # Drop empty strings so inherited_config treats them as non-explicit when
    # nested further (explicit empty never overrides non-empty inherited).
    return {key: value for key, value in settings.items() if value not in (None, "")}


def setup_seed_from_channel_settings(channel_settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """project.setup-shaped seed: schema keys only, position already normalized."""
    if not isinstance(channel_settings, Mapping):
        return {}
    seed: dict[str, Any] = {}
    for key in _SETUP_FIELD_NAMES:
        if key not in channel_settings:
            continue
        value = channel_settings[key]
        if key == "logo_position" and isinstance(value, str):
            # Channel branding uses hyphenated CSS-ish positions; setup uses
            # underscored option ids (top_right, bottom_left, …).
            value = value.replace("-", "_")
        seed[key] = value
    return seed


def merge_setup_config_with_channel(
    node_config: Mapping[str, Any] | None,
    channel_settings: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge project.setup configuration with channel defaults.

    Explicit non-empty node fields win. Empty strings yield to the channel.
    The logo block is a package: when the node has no managed logo asset of
    its own, channel branding (enabled flag, asset, presentation) fills in
    so a V2-era workflow with schema defaults still inherits Channel identity
    when run inside a Job.

    Nested values are deep-copied so node configuration never shares object
    identity with ``channel_settings`` (workflow validation rejects shared
    refs as recursive JSON — step 10.4 acceptance).
    """
    from copy import deepcopy

    seed = setup_seed_from_channel_settings(channel_settings)
    config = dict(node_config or {})

    if not _has_logo_asset(config.get("logo")) and seed:
        # Inherit the full logo package from the channel when the node never
        # selected a logo. Explicit logo_enabled=True without an asset is left
        # alone so LOGO_REQUIRED still fires (user turned it on, forgot asset).
        if not config.get("logo_enabled"):
            for key in _LOGO_PACKAGE_KEYS:
                if key in seed:
                    config[key] = deepcopy(seed[key])
        elif "logo" in seed:
            # Enabled on the node but no asset — take channel asset only.
            config["logo"] = deepcopy(seed["logo"])

    return inherited_config(config, seed)


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


def resolve_channel_settings(context: Any) -> dict[str, Any]:
    """Pull flat channel settings off an AdapterContext or mapping.

    Job orchestration stamps ``extensions.channel_settings`` on the workflow
    document; the scheduler copies that onto AdapterContext.channel_settings
    so ``project.setup`` can read the snapshot at runtime without knowing
    about Jobs.
    """
    if context is None:
        return {}
    if isinstance(context, Mapping):
        direct = context.get("channel_settings")
        if isinstance(direct, Mapping):
            return dict(direct)
        extensions = context.get("workflow_extensions") or context.get("extensions") or {}
        if isinstance(extensions, Mapping):
            nested = extensions.get("channel_settings")
            if isinstance(nested, Mapping):
                return dict(nested)
        return {}
    direct = getattr(context, "channel_settings", None)
    if isinstance(direct, Mapping):
        return dict(direct)
    extensions = getattr(context, "workflow_extensions", None) or {}
    if isinstance(extensions, Mapping):
        nested = extensions.get("channel_settings")
        if isinstance(nested, Mapping):
            return dict(nested)
    return {}


def _logo_settings_from_branding(branding: Mapping[str, Any]) -> dict[str, Any]:
    """Map Channel branding onto project.setup logo field names."""
    out: dict[str, Any] = {}
    enabled = bool(branding.get("enabled"))
    # Always surface enabled so merge can see an explicit channel True/False.
    out["logo_enabled"] = enabled

    asset = _text(branding.get("logo_asset_id"))
    if asset:
        ref = asset if asset.startswith("branding/") else f"branding/{asset.lstrip('/')}"
        # Reject absolute / drive-letter leakage — managed relative refs only.
        if ":" not in ref and not ref.startswith("/") and "\\" not in ref:
            out["logo"] = {"ref": ref, "path": ref}

    position = _text(branding.get("position"))
    if position:
        out["logo_position"] = position.replace("-", "_")

    size = branding.get("size")
    if size is not None:
        try:
            # Channel size is a 0–1 fraction of frame width → setup percent.
            out["logo_size"] = max(2, min(40, round(float(size) * 100)))
        except (TypeError, ValueError):
            pass

    opacity = branding.get("opacity")
    if opacity is not None:
        try:
            out["logo_opacity"] = max(0.05, min(1.0, float(opacity)))
        except (TypeError, ValueError):
            pass

    margin = branding.get("margin")
    if margin is not None:
        try:
            m = float(margin)
            # Channel margin is a 0–0.5 fraction; setup uses pixels. Scale by
            # a 1080 short-side reference so defaults land near the V2 32 px.
            out["logo_margin"] = max(0, min(200, round(m * 1080)))
        except (TypeError, ValueError):
            pass

    return out


def _has_logo_asset(logo: Any) -> bool:
    if not isinstance(logo, Mapping):
        return False
    ref = logo.get("ref") or logo.get("path")
    return bool(str(ref or "").strip())


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _visual_direction_block(visual: Mapping[str, Any]) -> dict[str, Any] | None:
    """Copy structured visual_direction fields; drop empties; never invent prompts."""
    if not isinstance(visual, Mapping) or not visual:
        return None

    block: dict[str, Any] = {}
    for key in (
        "style",
        "palette",
        "lighting",
        "camera",
        "character_style",
        "continuity",
        "negative_prompt",
    ):
        text = _text(visual.get(key))
        if text:
            block[key] = text

    pattern = visual.get("pattern")
    if isinstance(pattern, list) and pattern:
        entries: list[dict[str, str]] = []
        for item in pattern:
            if not isinstance(item, Mapping):
                continue
            role = _text(item.get("narrative_role"))
            shot = _text(item.get("shot"))
            if role and shot:
                entries.append({"narrative_role": role, "shot": shot})
        if entries:
            block["pattern"] = entries
    elif isinstance(pattern, dict) and pattern:
        entries = []
        for role, shot in pattern.items():
            r, s = _text(role), _text(shot)
            if r and s:
                entries.append({"narrative_role": r, "shot": s})
        if entries:
            block["pattern"] = entries

    refs = visual.get("references")
    if isinstance(refs, list):
        cleaned = [_text(item) for item in refs if _text(item)]
        if cleaned:
            block["references"] = cleaned

    return block or None


__all__ = [
    "channel_settings_from_snapshot",
    "merge_node_config_with_channel",
    "merge_setup_config_with_channel",
    "resolve_channel_settings",
    "script_text_from_source",
    "setup_seed_from_channel_settings",
]
