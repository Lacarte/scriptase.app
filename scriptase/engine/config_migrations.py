"""Node configuration migrations for the provider conversion (step 12.3).

The complete, frozen set of `type_version` bumps the provider platform is
permitted to make is contracts.md §41.3. This module ships M1–M3; M4
(`story.generate`, `scenes.blueprint`) is deliberately *not* here, because a
non-mutating read fallback in the adapter is enough for a key that is new and
optional — `setdefault` would change the fingerprinted configuration and
invalidate exactly the cache it is meant to preserve.

Every function is a pure `dict -> dict`. It receives a deep copy from
`migrate_workflow`, so mutating and returning the argument is safe, and it must
not touch files, settings, or the provider registry: a migration has to produce
the same result on a machine where the provider was never installed.

The fallback ids are today's *effective* defaults, taken from the v1 schema —
not from the domain catalog. A workflow saved before this step ran on the node's
own default, so reproducing it byte-for-byte means using that value even where
the domain default now differs (the `image` domain defaults to `gemini_ws`,
while a v1 `storyboard.generate` with no explicit `provider` ran
`wavespeed_webhook`).

Function names track the *node type* (`storyboard.generate`, `animator.generate`),
which step 0.2 deliberately does not rename — a saved workflow stores the node
type, and the graph contract has to survive the port. Only the `domain` argument
moved to the renamed provider domains.
"""

from __future__ import annotations

from scriptase.providers.compatibility import normalize_selection_alias

# The v1 config-schema defaults, frozen here so a later registry edit cannot
# silently change what an old workflow migrates to.
TTS_V1_DEFAULT_ENGINE = "kokoro"
STORYBOARD_V1_DEFAULT_PROVIDER = "wavespeed_webhook"
ANIMATOR_V1_DEFAULT_PROVIDER = "grok_automa"

_PROTOTYPE_PROVIDER_IDS = {
    "tts": {"kokoro": "inworld"},
    "image": {
        "webhook": "gemini_ws",
        "direct": "gemini_ws",
        "wavespeed": "gemini_ws",
        "wavespeed_direct": "gemini_ws",
        "wavespeed_webhook": "gemini_ws",
    },
    "video": {"kie-ai": "grok_automa", "kie_ai": "grok_automa"},
}

# Keys the node used to own that now belong to the provider's own settings.
# Only keys actually present are moved: inventing one would write a value the
# saved workflow never had.
STORYBOARD_V1_PROVIDER_KEYS = ("prompt_prefix", "auto_type")
ANIMATOR_V1_PROVIDER_KEYS = ("mode", "quality", "duration", "auto_type")


def _rename_provider(config: dict, legacy_key: str, default: str, *, domain: str) -> None:
    """Pop the legacy key and persist the *canonical* provider id.

    A saved v1 document may still carry a wire alias (`webhook`, `grok`, …).
    contracts.md §40.3 rule 1: only the canonical id is written after upgrade.
    """
    raw = config.pop(legacy_key, default)
    if not isinstance(raw, str) or not raw.strip():
        raw = default
    config["provider_id"] = normalize_selection_alias(raw, domain=domain)


def _move_to_provider_options(config: dict, keys) -> None:
    """Move present `keys` into `provider_options` without clobbering it.

    An existing `provider_options` entry wins: it was written against the
    provider explicitly and is the more specific value.
    """
    options = config.get("provider_options")
    options = dict(options) if isinstance(options, dict) else {}
    for key in keys:
        if key in config:
            options.setdefault(key, config.pop(key))
    config["provider_options"] = options


def tts_generate_1_to_2(config: dict) -> dict:
    """M1 — `engine` becomes `provider_id`; `voice`/`speed`/options untouched."""
    _rename_provider(config, "engine", TTS_V1_DEFAULT_ENGINE, domain="tts")
    return config


def storyboard_generate_1_to_2(config: dict) -> dict:
    """M2 — `provider` becomes `provider_id`; the gemini_ws fields move."""
    _rename_provider(
        config, "provider", STORYBOARD_V1_DEFAULT_PROVIDER, domain="image"
    )
    _move_to_provider_options(config, STORYBOARD_V1_PROVIDER_KEYS)
    return config


def animator_generate_1_to_2(config: dict) -> dict:
    """M3 — `provider` becomes `provider_id`; the grok_automa fields move."""
    _rename_provider(
        config, "provider", ANIMATOR_V1_DEFAULT_PROVIDER, domain="video"
    )
    _move_to_provider_options(config, ANIMATOR_V1_PROVIDER_KEYS)
    return config


def _prototype_provider(config: dict, domain: str) -> dict:
    provider_id = config.get("provider_id")
    if isinstance(provider_id, str):
        config["provider_id"] = _PROTOTYPE_PROVIDER_IDS.get(domain, {}).get(
            provider_id, provider_id
        )
    return config


def tts_generate_2_to_3(config: dict) -> dict:
    """Step 5.3: retire Kokoro and normalize its voice onto Inworld."""
    _prototype_provider(config, "tts")
    voice = config.get("voice")
    if isinstance(voice, str) and voice.startswith(("af_", "am_", "bf_", "bm_")):
        config["voice"] = "Ashley"
    return config


#: Curated-voice cutover: the narration catalog is now the fixed starred set,
#: which no longer contains "Ashley". Saved workflows carrying the old default
#: (or any voice dropped from the catalog) would fail validation, so they are
#: normalized onto the new default. A voice still present in the catalog is left
#: alone — only the names that no longer resolve are rewritten.
TTS_CURATED_DEFAULT_VOICE = "Sarah"


def tts_generate_3_to_4(config: dict) -> dict:
    """Step: curate narration voices — retire dropped names onto the new default.

    The catalog shrank to the starred set. Any saved `voice` that is not in it
    (notably the former default "Ashley") is remapped to the curated default so
    the node keeps validating; a voice still in the catalog is untouched.
    """
    from scriptase.modules.tts.providers.inworld.starred_voices import (
        STARRED_VOICE_IDS,
    )

    voice = config.get("voice")
    if isinstance(voice, str) and voice and voice not in STARRED_VOICE_IDS:
        config["voice"] = TTS_CURATED_DEFAULT_VOICE
    return config


def storyboard_generate_2_to_3(config: dict) -> dict:
    """Step 5.3: move WaveSpeed selections onto Gemini."""
    return _prototype_provider(config, "image")


def animator_generate_2_to_3(config: dict) -> dict:
    """Step 5.3: move Kie selections onto Grok."""
    return _prototype_provider(config, "video")


__all__ = [
    "animator_generate_1_to_2",
    "animator_generate_2_to_3",
    "storyboard_generate_1_to_2",
    "storyboard_generate_2_to_3",
    "tts_generate_1_to_2",
    "tts_generate_2_to_3",
]
