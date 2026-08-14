"""Provider compatibility surface — the one residual boundary (step 16.1).

Provider *input* aliases live on each package's manifest (`aliases=[]`) and are
resolved by the registry hub (id first, then alias). That is the only place a
shipped provider identity is translated for dispatch.

This module holds the two things that are *not* provider-declared:

  1. ``LEGACY_SELECTION_ALIASES`` — the retired ``app-config.json`` selection
     store wrote legacy wire spellings (``gemini``, ``grok``, ``kie-ai``, …).
     The one-time settings migration (v2) rewrites those into canonical ids
     before they enter ``settings.json``. After that migration has run, the
     table is never consulted at runtime.

  2. ``LEGACY_SELECTION_KEYS`` — the three key names that store used to own.
     The catalog no longer ships them, the frontend no longer defaults or
     mirrors them, and a load/write of ``app-config.json`` drops them.

Everything else — pipeline request fields, workflow node configs, extension
activate targets — speaks **canonical provider ids**. Aliases remain accepted
as *input* through the hub so un-migrated clients keep working.
"""

from __future__ import annotations

from typing import Mapping, MutableMapping


# Retired ``app-config.json`` selection values → canonical registry ids.
# Kept for the v2 settings migration and node-config upgrades (step 16.4).
# Not used at dispatch time — the hub resolves manifest aliases there.
#
# Domain-aware: ``gemini`` is an *image* wire alias for ``gemini_ws`` and
# simultaneously the *canonical* script provider id. A flat map would rewrite
# a correct script selection into an image id (§40.3).
#
# Keys are canonical domain ids. Callers holding a retired V2 domain spelling
# reach the right table through ``canonical_domain`` below rather than through
# a duplicated entry.
DOMAIN_SELECTION_ALIASES: dict[str, dict[str, str]] = {
    "script": {
        "builtin": "gemini",
    },
    "scene_director": {
        "builtin": "n8n",
    },
    "image": {
        "gemini": "gemini_ws",
        "webhook": "wavespeed_webhook",
        "direct": "wavespeed_direct",
    },
    "video": {
        "grok": "grok_automa",
        "midjourney": "grok_automa",
        "kie-ai": "kie_ai",
    },
}

# Cross-domain fallback used when the caller has no domain context (the retired
# app-config keys each already imply one domain via LEGACY_SELECTION_KEYS).
LEGACY_SELECTION_ALIASES: dict[str, str] = {
    "gemini": "gemini_ws",
    "grok": "grok_automa",
    "midjourney": "grok_automa",
    "kie-ai": "kie_ai",
    "webhook": "wavespeed_webhook",
    "direct": "wavespeed_direct",
}

# The three keys the retired store used. DomainSpecs keep the same strings so
# the v2 migration can still find them on an un-migrated machine; nothing else
# may read or write them after step 16.1.
LEGACY_SELECTION_KEYS: frozenset[str] = frozenset({
    "sts-tts-provider",
    "sts-storyboard-provider",
    "sts-asset-provider",
})


def normalize_selection_alias(value: str, *, domain: str | None = None) -> str:
    """Map a retired selection string onto a canonical provider id.

    When ``domain`` is known the domain table wins, so a script selection of
    ``gemini`` stays ``gemini`` while an image selection of ``gemini`` becomes
    ``gemini_ws``. Without a domain the cross-domain table is used.

    ``domain`` may be a retired V2 spelling: an un-migrated settings file or
    node config carries ``storyboard``/``animator``/``scene_blueprint``, and
    those documents are exactly the ones that still need alias normalisation.
    """
    from scriptase.providers.domains import canonical_domain

    raw = (value or "").strip()
    if not raw:
        return raw
    if domain:
        table = DOMAIN_SELECTION_ALIASES.get(canonical_domain(domain))
        if table is not None:
            return table.get(raw, raw)
        return raw
    return LEGACY_SELECTION_ALIASES.get(raw, raw)


def strip_legacy_selection_keys(user: MutableMapping | Mapping) -> dict:
    """Return a copy of an ``app-config.json['user']`` blob without the three keys.

    Used on every read-through of the retired store so a stale key cannot re-
    enter the browser defaults, and on write so the file itself converges.
    """
    if not isinstance(user, Mapping):
        return {}
    return {k: v for k, v in user.items() if k not in LEGACY_SELECTION_KEYS}


__all__ = [
    "DOMAIN_SELECTION_ALIASES",
    "LEGACY_SELECTION_ALIASES",
    "LEGACY_SELECTION_KEYS",
    "normalize_selection_alias",
    "strip_legacy_selection_keys",
]
