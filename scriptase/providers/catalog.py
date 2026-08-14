"""Catalog assembly and versioning for the provider API (contracts.md §25).

The catalog is *content*-versioned rather than URL-versioned: `catalog_version` is
a digest of the browser-safe payload, so a client can cache by it and refetch when
a provider is added, removed, relabeled, excluded, or changes availability.

Step 3.1: selection is an *instance* id. The type catalog still lists discovered
packages; each domain payload also carries the configured `instances` map and
`selected_instance_id` so two bindings of one type can be distinguished.
"""

import hashlib
import json

from scriptase.providers import hub, settings_manager
from scriptase.providers.domains import DOMAINS


def selected_instances() -> dict[str, str | None]:
    """`domain -> selected_instance_id` from the one authoritative store (§7 / §24)."""
    stored = settings_manager.load_settings().get("domains", {})
    result: dict[str, str | None] = {}
    for domain in hub.domains():
        block = stored.get(domain) or {}
        value = block.get("selected_instance_id")
        if isinstance(value, str) and value:
            result[domain] = value
            continue
        # Compat for un-migrated in-memory blobs used by tests.
        legacy = block.get("selected_provider")
        result[domain] = legacy if isinstance(legacy, str) and legacy else None
    return result


def selected_providers() -> dict[str, str | None]:
    """`domain -> selected provider type id` (derived from the selected instance).

    Kept for call sites that need the discovered package id rather than the
    instance id (catalog `selected` enrichment for type rows, option sources).
    """
    stored = settings_manager.load_settings().get("domains", {})
    result: dict[str, str | None] = {}
    for domain in hub.domains():
        block = stored.get(domain) or {}
        instance_id = block.get("selected_instance_id")
        if not (isinstance(instance_id, str) and instance_id):
            instance_id = block.get("selected_provider")
        if not (isinstance(instance_id, str) and instance_id):
            result[domain] = None
            continue
        instances = block.get("instances") or {}
        rec = instances.get(instance_id) if isinstance(instances, dict) else None
        if isinstance(rec, dict) and isinstance(rec.get("type"), str) and rec.get("type"):
            result[domain] = rec["type"]
        else:
            # Default-instance convention: instance_id == type id.
            result[domain] = instance_id
    return result


def build_catalog() -> dict:
    """The full `domain -> serialized registry` map, enriched with catalog data."""
    instance_selection = selected_instances()
    type_selection = selected_providers()
    catalog = hub.catalog(selected=type_selection)
    stored = settings_manager.load_settings().get("domains", {})
    for domain, payload in catalog.items():
        spec = DOMAINS.get(domain)
        if spec is not None:
            payload["label"] = spec.label
            payload["default_provider"] = spec.default_provider
            # Step 6.1: closed capability vocabulary travels with the catalog so
            # the node/step UI can only offer keys the domain understands.
            payload["capability_vocabulary"] = sorted(spec.capability_vocabulary)
            # Step 16.1: `legacy_selection_key` is no longer shipped. The retired
            # app-config keys were adopted by the v2 settings migration; the field
            # remains on DomainSpec only so that one-time upgrade can still find
            # them on an un-migrated machine.
        block = stored.get(domain) or {}
        instances_out = []
        raw_instances = block.get("instances") if isinstance(block, dict) else None
        if isinstance(raw_instances, dict):
            for iid, rec in raw_instances.items():
                if not isinstance(iid, str) or not isinstance(rec, dict):
                    continue
                type_id = rec.get("type") if isinstance(rec.get("type"), str) else iid
                provider = hub.get(domain, type_id)
                settings = rec.get("settings") if isinstance(rec.get("settings"), dict) else {}
                entry = {
                    "instance_id": iid,
                    "provider_type": type_id,
                    "label": rec.get("label") if isinstance(rec.get("label"), str) else type_id,
                    "selected": instance_selection.get(domain) == iid,
                }
                if provider is not None:
                    entry["availability"] = provider.availability(
                        settings, instance_id=iid
                    )
                else:
                    entry["availability"] = "needs_configuration"
                instances_out.append(entry)
        payload["instances"] = instances_out
        payload["selected_instance_id"] = instance_selection.get(domain)
    return catalog


def catalog_version(catalog: dict) -> str:
    """A stable digest of the catalog payload.

    Deterministic across processes: the payload is dumped with sorted keys, so an
    unchanged catalog always hashes to the same value.
    """
    canonical = json.dumps(catalog, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
