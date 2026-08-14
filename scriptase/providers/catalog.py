"""Catalog assembly and versioning for the provider API (contracts.md §25).

The catalog is *content*-versioned rather than URL-versioned: `catalog_version` is
a digest of the browser-safe payload, so a client can cache by it and refetch when
a provider is added, removed, relabeled, excluded, or changes availability.
"""

import hashlib
import json

from scriptase.providers import hub, settings_manager
from scriptase.providers.domains import DOMAINS


def selected_providers() -> dict[str, str | None]:
    """`domain -> selected_provider_id` from the one authoritative store (§24)."""
    stored = settings_manager.load_settings().get("domains", {})
    return {
        domain: (stored.get(domain) or {}).get("selected_provider")
        for domain in hub.domains()
    }


def build_catalog() -> dict:
    """The full `domain -> serialized registry` map, enriched with catalog data."""
    catalog = hub.catalog(selected=selected_providers())
    for domain, payload in catalog.items():
        spec = DOMAINS.get(domain)
        if spec is not None:
            payload["label"] = spec.label
            payload["default_provider"] = spec.default_provider
            # Step 16.1: `legacy_selection_key` is no longer shipped. The retired
            # app-config keys were adopted by the v2 settings migration; the field
            # remains on DomainSpec only so that one-time upgrade can still find
            # them on an un-migrated machine.
    return catalog


def catalog_version(catalog: dict) -> str:
    """A stable digest of the catalog payload.

    Deterministic across processes: the payload is dumped with sorted keys, so an
    unchanged catalog always hashes to the same value.
    """
    canonical = json.dumps(catalog, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
