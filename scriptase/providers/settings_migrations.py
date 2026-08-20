"""Settings migrations — versioned, forward-only upgrades of settings.json.

`MIGRATIONS` maps a **target** version to the function that upgrades data from the
previous version to it. `apply_migrations` runs every registered target greater
than the stored version, in ascending order, and stamps the version after each
step. The pre-11.3 loop skipped every version `>= current_version`, which meant it
could never run an upgrade — contracts.md §24.3 assigns that correction here.

v2 implements §24.3: adopt the three legacy `app-config.json` provider selections
into `settings.json`, which is the single selection authority (§24).

A migration reads *stored* data, so it speaks whatever spelling was on disk when
it was written. v2–v4 predate the step 0.2 domain rename and therefore still have
to recognise `scene_blueprint`, `storyboard`, and `animator` as block keys; v5 is
the step that rewrites them. Rewriting history in v2–v4 instead would silently
drop a V2 file's stored selections and per-provider settings.
"""

from typing import Callable

from scriptase.providers.compatibility import (
    LEGACY_SELECTION_ALIASES,
    normalize_selection_alias,
)
from scriptase.providers.domains import DOMAIN_ALIASES, DOMAINS


# The version a freshly written settings.json carries.
# v2 = §24.3 five-domain catalog + legacy selection adoption (step 11.3).
# v3 = S6 script selection `builtin` → `gemini` (step 13.3).
# v4 = S7 scene_blueprint selection `builtin` → `n8n` (step 13.4).
# v5 = domain rename: scene_blueprint → scene_director, storyboard → image,
#      animator → video (step 0.2).
# v6 = provider type/instance split (step 3.1): selected_provider + per_provider
#      → selected_instance_id + instances.
# v7 = secret references (step 3.4): plaintext credentials → {"$secret": ref}.
# v8 = backfill domains added to the catalog after v6 (step 7.3 `review`).
# v9 = the same backfill for `viral` (step 16.2). See `migrate_to_v9`.
# v10 = prototype-only provider catalogue (step 5.3).
# v11 = restore script catalogue (step 7.1). v10 removed it; Auto and Idea
#        need a script provider, so backfill gemini as the default.
SETTINGS_VERSION = 12

MIGRATIONS: dict[int, Callable[[dict, dict], dict]] = {}

# Canonical domain id -> the retired V2 block keys that may still hold its data.
_RETIRED_KEYS: dict[str, tuple[str, ...]] = {}
for _alias, _canonical in DOMAIN_ALIASES.items():
    _RETIRED_KEYS[_canonical] = _RETIRED_KEYS.get(_canonical, ()) + (_alias,)


def _stored_key(domains: dict, domain_id: str) -> str:
    """The key `domain_id`'s block actually lives under in a stored document.

    Returns the canonical id when the block is absent, so a caller creating a
    missing block writes the canonical spelling.
    """
    if isinstance(domains.get(domain_id), dict):
        return domain_id
    for retired in _RETIRED_KEYS.get(domain_id, ()):
        if isinstance(domains.get(retired), dict):
            return retired
    return domain_id


def _register(version: int):
    """Register the function that upgrades data *to* `version`."""
    def decorator(func: Callable[[dict, dict], dict]):
        MIGRATIONS[version] = func
        return func
    return decorator


@_register(2)
def migrate_to_v2(data: dict, legacy_user: dict) -> dict:
    """Adopt the legacy per-domain provider selections, then never look again.

    `settings.json` always wins: the legacy key is only read when the domain has
    no explicit `selected_provider`. The missing domain blocks of a settings file
    written before the five-domain catalog are backfilled at the same time, so the
    upgrade is lossless in both directions.
    """
    domains = data.setdefault("domains", {})

    for domain_id, spec in DOMAINS.items():
        # A pre-rename document keeps its V2 block key here; v5 moves it.
        key = _stored_key(domains, domain_id)
        block = domains.get(key)
        if not isinstance(block, dict):
            block = {"selected_provider": spec.default_provider, "per_provider": {}}
            domains[key] = block
        block.setdefault("per_provider", {})

        if block.get("selected_provider"):
            # settings.json wins over the legacy key, but an alias that was
            # already stored is rewritten to its canonical id (§39 rule 1 /
            # §40.3 rule 1 — only canonical ids persist).
            block["selected_provider"] = normalize_selection_alias(
                block["selected_provider"], domain=domain_id
            )
            continue

        legacy_key = spec.legacy_selection_key
        legacy_value = legacy_user.get(legacy_key) if legacy_key else None
        if isinstance(legacy_value, str) and legacy_value.strip():
            block["selected_provider"] = normalize_selection_alias(
                legacy_value, domain=domain_id
            )
        else:
            # An absent or null selection resolves to the catalog default (§24.1
            # rule 4), written down so the store is complete after the upgrade.
            block["selected_provider"] = spec.default_provider

    return data


@_register(3)
def migrate_to_v3(data: dict, legacy_user: dict) -> dict:
    """S6 — rewrite only the transitional script selection `builtin` → `gemini`.

    The 12.3 bridge id was the domain default until 13.2 landed the real
    `gemini` provider. Any explicit selection other than `builtin`
    (`random_template`, a future plugin, …) is left alone (contracts.md §42 S6).
    """
    domains = data.setdefault("domains", {})
    block = domains.get("script")
    if isinstance(block, dict) and block.get("selected_provider") == "builtin":
        block["selected_provider"] = "gemini"
    return data


@_register(4)
def migrate_to_v4(data: dict, legacy_user: dict) -> dict:
    """S7 — rewrite only the transitional scene-director selection `builtin` → `n8n`.

    The 12.3 bridge id was the domain default until 13.4 landed the real
    `n8n` provider. Any explicit selection other than `builtin` is left alone
    (contracts.md §42 S7).

    Reached with the block still under its V2 key on any document written before
    v5, which is every document this migration can legally run on.
    """
    domains = data.setdefault("domains", {})
    block = domains.get(_stored_key(domains, "scene_director"))
    if isinstance(block, dict) and block.get("selected_provider") == "builtin":
        block["selected_provider"] = "n8n"
    return data


@_register(5)
def migrate_to_v5(data: dict, legacy_user: dict) -> dict:
    """Rename the three domain blocks the step 0.2 package rename retired.

    `scene_blueprint` → `scene_director`, `storyboard` → `image`,
    `animator` → `video`. Selections and per-provider settings move with the
    block; provider ids inside it are untouched, because only the *domain* was
    renamed.

    A document carrying both spellings keeps the canonical block — it is the
    newer write — and discards the retired one rather than merging two
    selections into an order-dependent result.
    """
    domains = data.get("domains")
    if not isinstance(domains, dict):
        return data
    for retired, canonical in DOMAIN_ALIASES.items():
        if retired not in domains:
            continue
        block = domains.pop(retired)
        if canonical not in domains and isinstance(block, dict):
            domains[canonical] = block
    return data


@_register(6)
def migrate_to_v6(data: dict, legacy_user: dict) -> dict:
    """Split provider type from provider instance (step 3.1 / contracts §7).

    Each `per_provider.<type_id>` entry becomes a default instance whose
    `instance_id` equals the provider type id, so wire values and routes that
    still speak type ids keep resolving after the upgrade. The domain selection
    moves from `selected_provider` to `selected_instance_id` without changing
    which provider type is selected.
    """
    domains = data.setdefault("domains", {})
    for domain_id, spec in DOMAINS.items():
        block = domains.get(domain_id)
        if not isinstance(block, dict):
            block = {}
            domains[domain_id] = block

        # Already on the post-3.1 shape (re-entry / partial write).
        if "instances" in block and "selected_instance_id" in block:
            block.pop("selected_provider", None)
            block.pop("per_provider", None)
            continue

        per_provider = block.get("per_provider")
        if not isinstance(per_provider, dict):
            per_provider = {}

        selected = block.get("selected_provider")
        if not (isinstance(selected, str) and selected.strip()):
            selected = spec.default_provider
        selected = normalize_selection_alias(selected, domain=domain_id)

        instances: dict = {}
        if isinstance(block.get("instances"), dict):
            # Preserve any instances already written, then fill from per_provider.
            for iid, rec in block["instances"].items():
                if isinstance(iid, str) and isinstance(rec, dict):
                    instances[iid] = _normalize_instance_record(iid, rec)

        for type_id, settings in per_provider.items():
            if not isinstance(type_id, str) or not type_id:
                continue
            canonical_type = normalize_selection_alias(type_id, domain=domain_id)
            if canonical_type in instances:
                # Settings already present win; only fill an empty settings bag.
                existing = instances[canonical_type]
                if not existing.get("settings") and isinstance(settings, dict):
                    existing["settings"] = dict(settings)
                continue
            instances[canonical_type] = {
                "type": canonical_type,
                "label": canonical_type,
                "settings": dict(settings) if isinstance(settings, dict) else {},
            }

        if selected and selected not in instances:
            instances[selected] = {
                "type": selected,
                "label": selected,
                "settings": {},
            }

        # A domain with neither selection nor per_provider still needs a default
        # instance so the store is complete after the upgrade.
        if not instances and spec.default_provider:
            default_id = spec.default_provider
            instances[default_id] = {
                "type": default_id,
                "label": default_id,
                "settings": {},
            }
            selected = default_id

        domains[domain_id] = {
            "selected_instance_id": selected,
            "instances": instances,
        }

    return data


def _normalize_instance_record(instance_id: str, rec: dict) -> dict:
    """Coerce a partial instance record into the frozen post-3.1 shape."""
    type_id = rec.get("type") if isinstance(rec.get("type"), str) and rec.get("type") else instance_id
    label = rec.get("label") if isinstance(rec.get("label"), str) and rec.get("label") else type_id
    settings = rec.get("settings") if isinstance(rec.get("settings"), dict) else {}
    return {"type": type_id, "label": label, "settings": dict(settings)}


@_register(7)
def migrate_to_v7(data: dict, legacy_user: dict) -> dict:
    """Replace inline credentials with ``{"$secret": "<ref>"}`` (step 3.4).

    Plaintext values under secret-shaped keys move into the machine-local secret
    store; ``settings.json`` keeps only the reference. Already-referenced fields
    and empty strings are left alone. Environment fallbacks are not seeded.
    """
    from scriptase.providers.secrets import extract_plaintext_from_document

    return extract_plaintext_from_document(data)


@_register(8)
def migrate_to_v8(data: dict, legacy_user: dict) -> dict:
    """Backfill domain blocks for catalog entries added after the v6 split.

    Step 7.3 adds ``review``. Any ``DomainSpec`` missing from ``settings.json``
    receives a default instance of its catalog default provider; existing
    blocks are never rewritten.

    This body is generic, but the version stamp is not: a document already at
    v8 never re-runs it, so a domain added *later* needs its own version to
    reach files written in between. That is what ``migrate_to_v9`` is.
    """
    domains = data.setdefault("domains", {})
    for domain_id, spec in DOMAINS.items():
        block = domains.get(domain_id)
        if isinstance(block, dict) and (
            block.get("selected_instance_id") or block.get("instances")
        ):
            continue
        default = spec.default_provider
        instances: dict = {}
        if default:
            instances[default] = {
                "type": default,
                "label": default,
                "settings": {},
            }
        domains[domain_id] = {
            "selected_instance_id": default,
            "instances": instances,
        }
    return data


@_register(9)
def migrate_to_v9(data: dict, legacy_user: dict) -> dict:
    """Backfill the `viral` domain block (step 16.2).

    Byte-for-byte the same work as v8 and deliberately so: every settings file
    written between 7.3 and 16.2 is stamped v8, so v8 will never run on it
    again and `viral` would stay missing — the domain would exist in the
    catalog while `settings.json` had no block, and the provider API would
    serve it with a null selection.

    Every future domain addition ships one of these one-line versions. Sharing
    the body is what keeps that cheap.
    """
    return migrate_to_v8(data, legacy_user)


@_register(10)
def migrate_to_v10(data: dict, legacy_user: dict) -> dict:
    """Move configured instances onto the prototype's provider types.

    Default instances are renamed to the remaining type id so Channels that
    stored the old type id can follow the same deterministic mapping. Named
    instances keep their id (and therefore their Channel references), but their
    type changes. Retired provider settings are discarded because settings
    schemas are provider-specific and must not be reinterpreted as credentials
    or options for a different service.

    Script and review intentionally have no provider in the prototype
    catalogue; their stale selections and instances are removed.
    """
    domains = data.setdefault("domains", {})
    if not isinstance(domains, dict):
        data["domains"] = domains = {}

    for domain_id, spec in DOMAINS.items():
        block = domains.get(domain_id)
        if not isinstance(block, dict):
            block = {}

        target = spec.default_provider
        raw_instances = block.get("instances")
        if not isinstance(raw_instances, dict):
            raw_instances = {}

        instances: dict[str, dict] = {}
        id_map: dict[str, str] = {}

        # Keep already-supported bindings first so a retired default cannot
        # overwrite a configured prototype instance at the same destination.
        if target:
            ordered = sorted(
                raw_instances.items(),
                key=lambda item: 0
                if isinstance(item[1], dict) and item[1].get("type") == target
                else 1,
            )
            for instance_id, record in ordered:
                if not isinstance(instance_id, str) or not isinstance(record, dict):
                    continue
                provider_type = record.get("type")
                if not isinstance(provider_type, str) or not provider_type:
                    provider_type = instance_id
                supported = provider_type == target
                destination = instance_id if supported or instance_id != provider_type else target
                id_map[instance_id] = destination
                if destination in instances:
                    continue
                instances[destination] = {
                    "type": target,
                    "label": (
                        record.get("label")
                        if supported and isinstance(record.get("label"), str)
                        else destination
                    ),
                    "settings": (
                        dict(record.get("settings"))
                        if supported and isinstance(record.get("settings"), dict)
                        else {}
                    ),
                }

            if target not in instances:
                instances[target] = {
                    "type": target,
                    "label": target,
                    "settings": {},
                }

        selected = block.get("selected_instance_id")
        if not isinstance(selected, str) or not selected:
            selected = None
        selected = id_map.get(selected, selected)
        if selected not in instances:
            selected = target

        domains[domain_id] = {
            "selected_instance_id": selected,
            "instances": instances,
        }

    return data


@_register(11)
def migrate_to_v11(data: dict, legacy_user: dict) -> dict:
    """Restore the `script` domain's default instance (step 7.1).

    v10 removed script providers because the prototype named none. Step 7.1
    reverses that: Auto and Idea source modes need a script provider, so the
    catalogue now includes ``gemini`` and ``random_template``, with ``gemini``
    as the default. Files already at v10 have an empty script block
    (``selected_instance_id: null, instances: {}``); the v8 body detects that
    as "needs backfill" and writes the default instance.
    """
    return migrate_to_v8(data, legacy_user)


@_register(12)
def migrate_to_v12(data: dict, legacy_user: dict) -> dict:
    """Seed the `n8n` "Script Generator" instance in the script domain.

    The n8n script provider is a passerelle to the caller's own n8n webhook.
    Adding it as a seeded instance makes it appear on the providers settings
    page alongside `gemini` out of the box. The existing default instance and
    the current selection are left untouched — this only *adds* a binding when
    one is not already present.
    """
    block = data.get("domains", {}).get("script")
    if not isinstance(block, dict):
        # An empty/absent script block is backfilled by the v8 body first, which
        # earlier hops already ran; nothing to add onto here.
        return data
    instances = block.setdefault("instances", {})
    if not isinstance(instances, dict):
        return data
    instances.setdefault("n8n", {
        "type": "n8n",
        "label": "Script Generator",
        "settings": {},
    })
    return data


def apply_migrations(data: dict, legacy_user: dict | None = None) -> tuple[dict, bool]:
    """Upgrade `data` to `SETTINGS_VERSION`.

    Args:
        data: the raw settings document as read from disk.
        legacy_user: `app-config.json["user"]`, injected rather than read here so
            the migration never imports a route's private helper (§24.3).

    Returns `(migrated_data, changed)`. `changed` is `True` only when a migration
    ran, so an already-current document is not rewritten — the migration is
    idempotent and the version stamp is the completion marker.
    """
    current_version = data.get("version")
    if not isinstance(current_version, int) or isinstance(current_version, bool):
        current_version = 1

    legacy_user = legacy_user or {}
    migrated = data
    changed = False

    for version in sorted(MIGRATIONS):
        if version <= current_version:
            continue
        migrated = MIGRATIONS[version](migrated, legacy_user)
        # Stamped per step: an interrupted write leaves the previous version on
        # disk and the next load retries from there.
        migrated["version"] = version
        changed = True

    if migrated.get("version") != SETTINGS_VERSION and changed:
        migrated["version"] = SETTINGS_VERSION

    return migrated, changed


__all__ = [
    "SETTINGS_VERSION",
    "MIGRATIONS",
    "LEGACY_SELECTION_ALIASES",
    "apply_migrations",
    "migrate_to_v2",
    "migrate_to_v3",
    "migrate_to_v7",
    "migrate_to_v4",
    "migrate_to_v5",
    "migrate_to_v6",
    "migrate_to_v8",
    "migrate_to_v9",
    "migrate_to_v10",
    "migrate_to_v11",
]
