"""Settings Manager — load, save, validate, atomic writes, redaction.

Canonical source of truth for nested provider settings at settings/settings.json,
and the single authority for `domains.<domain>.selected_instance_id`
(contracts.md §7 / §24). Thread-safe with file locking.

Step 3.1 splits provider **type** (discovered package id) from provider
**instance** (user-configured binding). The store shape is:

    domains.<domain>.{
      selected_instance_id,
      instances: { <instance_id>: { type, label, settings } }
    }

Compatibility helpers that still accept a bare provider type id resolve it to
the default instance of that type (`instance_id == type`), which is exactly the
shape the v6 migration writes for every pre-3.1 selection.
"""

import json
import os
import tempfile
import threading
from typing import Any

from loguru import logger

from config import APP_CONFIG_PATH, ROOT_DIR
from scriptase.providers.domains import DOMAINS
from scriptase.providers.settings_migrations import (
    SETTINGS_VERSION,
    apply_migrations,
)
from scriptase.providers.settings_schema import (
    REDACTION_SENTINEL,
    SENSITIVE_KEYS_RE,
    apply_settings_patch,
    redact,
    split_settings,
)


SETTINGS_DIR = os.path.join(ROOT_DIR, "settings")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

_lock = threading.RLock()


def _ensure_settings_dir() -> None:
    """Ensure the settings directory exists."""
    os.makedirs(SETTINGS_DIR, exist_ok=True)


_settings_seeded = False


def _read_legacy_user_settings() -> dict:
    """Read `app-config.json["user"]` — the retired selection store (§24.3).

    Injected into the migration boundary here rather than imported from the editor
    blueprint's private helper, so migrations never depend on a route module.
    """
    try:
        with open(APP_CONFIG_PATH, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    user = config.get("user") if isinstance(config, dict) else None
    return user if isinstance(user, dict) else {}


def load_settings() -> dict:
    """Load settings from settings/settings.json, applying migrations if needed.

    On first load, seeds non-secret defaults from environment variables if
    settings.json does not exist. Returns the full settings dict with version,
    general, and domains keys.
    """
    global _settings_seeded

    _ensure_settings_dir()

    with _lock:
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.warning("[settings] settings.json not found, seeding defaults")
            data = _seed_from_env()
            save_settings(data)
            _settings_seeded = True
            return data
        except json.JSONDecodeError as e:
            logger.error("[settings] Corrupted settings.json: {}, returning defaults", e)
            return _default_settings()

    migrated, changed = apply_migrations(data, _read_legacy_user_settings())
    if changed:
        logger.info("[settings] Applied migrations, version now {}", migrated.get("version"))
        # The version stamp and the adopted values are written in one atomic
        # replace; an interrupted write leaves the old version on disk and the
        # next load retries the migration (§24.3).
        save_settings(migrated)

    return migrated


def _seed_from_env() -> dict:
    """Seed default settings from environment variables.

    Secrets are deliberately **not** seeded: an API key in the environment is a
    read-time fallback resolved from the provider manifest's `environment` map,
    never a value copied into settings.json (§22.6). Seeding also never writes a
    selection beyond the catalog default — the `INWORLD_API_KEY` selection side
    effect is removed (§14.3, §22.6).
    """
    def env(key: str, default: str = "") -> str:
        return os.environ.get(key) or default

    settings = _default_settings()

    sync_folder = env("STS_SYNC_FOLDER")
    if sync_folder:
        settings["general"]["sync_folder"] = sync_folder

    settings["general"]["auto_sync"] = env("STS_AUTO_SYNC", "true").lower() in (
        "true", "1", "yes"
    )

    logger.info("[settings] Seeded settings from environment variables")
    return settings


def save_settings(data: dict) -> None:
    """Save settings to settings/settings.json atomically.

    Uses write-to-temp-then-rename for atomicity. Plaintext credentials are
    materialised into the secret store first so ``settings.json`` never holds
    an inline secret (step 3.4 / contracts.md §7).
    """
    from scriptase.providers.secrets import extract_plaintext_from_document

    _ensure_settings_dir()
    data = extract_plaintext_from_document(dict(data) if isinstance(data, dict) else {})

    with _lock:
        temp_fd, temp_path = tempfile.mkstemp(
            dir=SETTINGS_DIR,
            prefix=".settings_",
            suffix=".tmp"
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, SETTINGS_PATH)
            logger.debug("[settings] Saved settings.json")
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise


def _default_domain_block(spec) -> dict:
    """One domain's post-3.1 defaults: the default instance, plus any seeded extras.

    A `DomainSpec` may declare `seeded_instances` — additional catalog types a
    fresh install binds beyond the default so a provider that ships without
    being the default still appears on the settings page. The provider ids live
    on the spec (§19.1), never inline here, so this stays a §26 zero-touch
    surface.
    """
    default = spec.default_provider
    instances = {}
    if default:
        instances[default] = {
            "type": default,
            "label": getattr(spec, "default_instance_label", None) or default,
            "settings": {},
        }
    for type_id, label in getattr(spec, "seeded_instances", ()) or ():
        instances.setdefault(type_id, {
            "type": type_id,
            "label": label,
            "settings": {},
        })
    return {
        "selected_instance_id": default,
        "instances": instances,
    }


def _default_settings() -> dict:
    """Return the default settings structure at the current version.

    The `domains` block is generated from the domain catalog (§19.1) so it can never
    drift from `ProviderRegistry.VALID_DOMAINS` or `validate_settings`.
    """
    return {
        "version": SETTINGS_VERSION,
        "general": {
            "default_style": "cinematic",
            "sync_folder": "",
            "auto_sync": False
        },
        "domains": {
            spec.id: _default_domain_block(spec)
            for spec in DOMAINS.values()
        }
    }


def _ensure_domain_block(settings: dict, domain: str) -> dict:
    """Return a mutable post-3.1 domain block, creating it if needed."""
    if "domains" not in settings or not isinstance(settings["domains"], dict):
        settings["domains"] = {}
    block = settings["domains"].get(domain)
    if not isinstance(block, dict):
        block = {"selected_instance_id": None, "instances": {}}
        settings["domains"][domain] = block
    if "instances" not in block or not isinstance(block["instances"], dict):
        block["instances"] = {}
    if "selected_instance_id" not in block:
        block["selected_instance_id"] = None
    return block


def get_domain_settings(domain: str) -> dict:
    """Get settings for a specific domain."""
    settings = load_settings()
    return settings.get("domains", {}).get(domain, {})


def list_instances(domain: str) -> dict[str, dict]:
    """`instance_id -> {type, label, settings}` for one domain."""
    block = get_domain_settings(domain)
    raw = block.get("instances") if isinstance(block, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        iid: dict(rec)
        for iid, rec in raw.items()
        if isinstance(iid, str) and isinstance(rec, dict)
    }


def get_instance_record(domain: str, instance_id: str) -> dict | None:
    """One configured instance record, or `None` when unknown."""
    if not instance_id:
        return None
    rec = list_instances(domain).get(instance_id)
    return dict(rec) if rec is not None else None


def get_selected_instance_id(domain: str) -> str | None:
    """The domain's selected instance id, or `None` when unset."""
    block = get_domain_settings(domain)
    if not isinstance(block, dict):
        return None
    value = block.get("selected_instance_id")
    if isinstance(value, str) and value:
        return value
    # Pre-migration documents (or callers that mutate the in-memory blob) may
    # still carry the retired key; resolve it so selection never goes silent.
    legacy = block.get("selected_provider")
    if isinstance(legacy, str) and legacy:
        return legacy
    return None


def resolve_instance(
    domain: str, instance_id: str | None = None
) -> tuple[str | None, str | None, dict]:
    """Resolve `(instance_id, provider_type, settings)` for a domain.

    When `instance_id` is omitted, the domain selection is used, falling back to
    the catalog default. When an id is supplied but not stored, it is treated as
    a default instance of that type (instance_id == type) with empty settings —
    the same shape migration writes for a selection that never received a
    settings write.
    """
    from scriptase.providers.domains import DOMAINS as domain_catalog

    spec = domain_catalog.get(domain)
    instances = list_instances(domain)

    candidate = instance_id if (isinstance(instance_id, str) and instance_id) else None
    if candidate is None:
        candidate = get_selected_instance_id(domain)
    if candidate is None and spec is not None:
        candidate = spec.default_provider

    if not candidate:
        return None, None, {}

    rec = instances.get(candidate)
    if rec is not None:
        type_id = rec.get("type") if isinstance(rec.get("type"), str) else candidate
        settings = rec.get("settings") if isinstance(rec.get("settings"), dict) else {}
        return candidate, type_id, dict(settings)

    # Unknown id → treat as a default instance of that provider type.
    return candidate, candidate, {}


def default_instance_id_for_type(domain: str, provider_type: str) -> str:
    """The instance id used for the default binding of a provider type.

    Equals the type id. Additional instances of the same type use distinct ids.
    """
    return provider_type


def find_instances_of_type(domain: str, provider_type: str) -> list[str]:
    """Instance ids whose `type` equals `provider_type`, selection first."""
    if not provider_type:
        return []
    selected = get_selected_instance_id(domain)
    found: list[str] = []
    for iid, rec in list_instances(domain).items():
        if rec.get("type") == provider_type:
            found.append(iid)
    if selected and selected in found:
        found.remove(selected)
        found.insert(0, selected)
    # A type with no stored instance still has its default id available.
    if not found:
        found.append(provider_type)
    return found


def get_instance_settings(domain: str, instance_id: str) -> dict:
    """Stored settings for one instance. Never resolves environment fallbacks."""
    _, _, settings = resolve_instance(domain, instance_id)
    return settings


def get_provider_settings(domain: str, provider_or_instance_id: str) -> dict:
    """Stored settings for an instance (or the default instance of a type).

    Accepts either an instance id or a provider type id. Type ids resolve to the
    default instance (`instance_id == type`), preserving every pre-3.1 call site
    that keyed settings on the provider package id.
    """
    return get_instance_settings(domain, provider_or_instance_id)


def set_instance_settings(
    domain: str,
    instance_id: str,
    instance_settings: dict,
    *,
    provider_type: str | None = None,
    label: str | None = None,
    schema: dict | None = None,
) -> None:
    """Write settings for one instance, creating the record when missing.

    Plaintext secret fields are replaced with ``{"$secret": ref}`` before the
    document is persisted (step 3.4).
    """
    from scriptase.providers.secrets import extract_plaintext_from_settings

    if not instance_id:
        raise ValueError("instance_id must be a non-empty string")
    settings = load_settings()
    block = _ensure_domain_block(settings, domain)
    existing = block["instances"].get(instance_id)
    type_id = provider_type
    display = label
    previous_settings: dict = {}
    if isinstance(existing, dict):
        if not type_id:
            type_id = existing.get("type") if isinstance(existing.get("type"), str) else instance_id
        if not display:
            display = existing.get("label") if isinstance(existing.get("label"), str) else type_id
        if isinstance(existing.get("settings"), dict):
            previous_settings = existing["settings"]
    else:
        type_id = type_id or instance_id
        display = display or type_id
    stored_settings = extract_plaintext_from_settings(
        dict(instance_settings or {}),
        schema=schema,
        previous=previous_settings,
    )
    block["instances"][instance_id] = {
        "type": type_id,
        "label": display,
        "settings": stored_settings,
    }
    save_settings(settings)


def set_provider_settings(domain: str, provider_id: str, provider_settings: dict) -> None:
    """Write settings for the default instance of a provider type.

    Compatibility alias: `provider_id` is used as both instance id and type.
    """
    set_instance_settings(
        domain,
        provider_id,
        provider_settings,
        provider_type=provider_id,
    )


def upsert_instance(
    domain: str,
    *,
    provider_type: str,
    instance_id: str | None = None,
    label: str | None = None,
    settings: dict | None = None,
) -> str:
    """Create or update a configured instance of `provider_type`.

    Returns the instance id. When `instance_id` is omitted a unique id is
    derived from the type (`<type>`, then `<type>_2`, …).
    """
    if not provider_type:
        raise ValueError("provider_type must be a non-empty string")
    doc = load_settings()
    block = _ensure_domain_block(doc, domain)
    instances = block["instances"]

    iid = instance_id
    if not iid:
        iid = provider_type
        if iid in instances and instances[iid].get("type") != provider_type:
            n = 2
            while f"{provider_type}_{n}" in instances:
                n += 1
            iid = f"{provider_type}_{n}"
        elif iid in instances:
            # Updating the default instance in place.
            pass
        # else: free to use type as id

    if iid in instances and instance_id is None and instances[iid].get("type") == provider_type:
        # Caller asked to create without an id but the default already exists —
        # mint a sibling so two instances of one type are expressible.
        n = 2
        while f"{provider_type}_{n}" in instances:
            n += 1
        iid = f"{provider_type}_{n}"

    from scriptase.providers.secrets import extract_plaintext_from_settings

    existing = instances.get(iid) if isinstance(instances.get(iid), dict) else {}
    display = label or existing.get("label") or provider_type
    previous = existing.get("settings") if isinstance(existing.get("settings"), dict) else {}
    if settings is not None:
        body = extract_plaintext_from_settings(
            dict(settings) if isinstance(settings, dict) else {},
            previous=previous,
        )
    else:
        body = dict(previous)
    instances[iid] = {
        "type": provider_type,
        "label": display,
        "settings": body,
    }
    save_settings(doc)
    return iid


def rename_instance(domain: str, instance_id: str, label: str) -> None:
    """Change an instance's display label without touching its identity or secrets."""
    if not instance_id:
        raise ValueError("instance_id must be a non-empty string")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label must be a non-empty string")
    doc = load_settings()
    block = _ensure_domain_block(doc, domain)
    record = block["instances"].get(instance_id)
    if not isinstance(record, dict):
        raise KeyError(instance_id)
    record["label"] = label.strip()
    save_settings(doc)


def delete_instance(domain: str, instance_id: str) -> str | None:
    """Delete one binding and return the selected replacement, if any.

    Selection moves to the first remaining binding when the deleted instance
    was selected. Instance ids are stable references, so deleting a binding
    never silently renames another one into its place.
    """
    if not instance_id:
        raise ValueError("instance_id must be a non-empty string")
    doc = load_settings()
    block = _ensure_domain_block(doc, domain)
    if instance_id not in block["instances"]:
        raise KeyError(instance_id)
    del block["instances"][instance_id]
    if block.get("selected_instance_id") == instance_id:
        block["selected_instance_id"] = next(iter(block["instances"]), None)
    replacement = block.get("selected_instance_id")
    save_settings(doc)
    return replacement if isinstance(replacement, str) and replacement else None


def set_selected_instance(domain: str, instance_id: str) -> None:
    """Set the selected instance for a domain."""
    if not instance_id:
        raise ValueError("instance_id must be a non-empty string")
    settings = load_settings()
    block = _ensure_domain_block(settings, domain)
    # Ensure the selected instance exists so a bare selection of a type id
    # (the default-instance convention) is durable.
    if instance_id not in block["instances"]:
        block["instances"][instance_id] = {
            "type": instance_id,
            "label": instance_id,
            "settings": {},
        }
    block["selected_instance_id"] = instance_id
    save_settings(settings)


def set_selected_provider(domain: str, provider_id: str) -> None:
    """Select the default instance of a provider type (compat alias)."""
    set_selected_instance(domain, provider_id)


def get_general_settings() -> dict:
    """Get general settings."""
    settings = load_settings()
    return settings.get("general", {})


def set_general_settings(general_settings: dict) -> None:
    """Set general settings."""
    settings = load_settings()
    settings["general"] = general_settings
    save_settings(settings)


def redact_settings(data: dict, schema: dict | None = None) -> dict:
    """Redact secret fields from a settings payload before it leaves the process.

    A field is secret when its key matches `SENSITIVE_KEYS_RE` or, when a provider
    settings schema is supplied, when its widget is a password input (§22.6).
    """
    return redact(data, schema)


def redacted_provider_settings(
    domain: str, provider_or_instance_id: str, schema: dict | None = None
) -> dict:
    """Get redacted settings for a specific provider instance."""
    return redact_settings(get_provider_settings(domain, provider_or_instance_id), schema)


def portable_provider_settings(
    domain: str, provider_or_instance_id: str, schema: dict | None = None
) -> dict:
    """The non-secret half of a provider instance's settings.

    Durable secrets stay in `settings.json`; only these portable options may be
    copied into a job manifest, a workflow snapshot, or an export (§22.6).
    """
    _, options = split_settings(
        schema, get_provider_settings(domain, provider_or_instance_id)
    )
    return options


def merge_provider_settings(
    domain: str,
    provider_or_instance_id: str,
    patch: dict,
    schema: dict | None = None,
) -> dict:
    """Merge a client patch over stored instance settings, honoring the sentinel.

    A secret field submitted as exactly `"***"` is the redacted value the client
    was served and leaves the stored secret untouched (§22.6).
    """
    return apply_settings_patch(
        get_provider_settings(domain, provider_or_instance_id), patch, schema
    )


def restore_redacted_secrets(stored: Any, incoming: Any) -> Any:
    """Recursively drop sentinel secrets from a whole-document settings write.

    `PUT /api/settings/v2` round-trips the entire document, so a redacted read
    would otherwise write `"***"` over every stored secret. After step 3.4 the
    stored value is typically a secret ref (not plaintext); restoring the
    sentinel re-attaches that ref, never the resolved credential.
    """
    from scriptase.providers.secrets import is_secret_ref

    if not isinstance(incoming, dict):
        return incoming
    stored = stored if isinstance(stored, dict) else {}
    result: dict = {}
    for key, value in incoming.items():
        if value == REDACTION_SENTINEL and SENSITIVE_KEYS_RE.search(key):
            if key in stored:
                result[key] = stored[key]
            continue
        # A client must never submit a raw secret-ref object it invented; only
        # the store's own refs (restored via the sentinel) are durable. An
        # incoming ref that matches the stored one is kept; any other ref is
        # dropped in favour of the stored value when present.
        if is_secret_ref(value):
            prev = stored.get(key)
            result[key] = prev if is_secret_ref(prev) or prev is not None else value
            continue
        if isinstance(value, dict):
            result[key] = restore_redacted_secrets(stored.get(key), value)
        else:
            result[key] = value
    return result


def validate_settings(data: dict) -> list[dict]:
    """Validate the settings document structure.

    Returns list of ValidationIssue dicts with 'field', 'severity', 'message'.
    """
    issues = []

    if not isinstance(data, dict):
        return [{"field": "root", "severity": "error", "message": "Settings must be a JSON object"}]

    version = data.get("version")
    if version is None:
        issues.append({"field": "version", "severity": "warning", "message": "version field missing, assuming v1"})

    domains = data.get("domains")
    if not isinstance(domains, dict):
        issues.append({"field": "domains", "severity": "error", "message": "domains must be an object"})
    else:
        for domain, block in domains.items():
            if domain not in DOMAINS:
                issues.append({
                    "field": f"domains.{domain}",
                    "severity": "warning",
                    "message": f"Unknown domain '{domain}'"
                })
            if not isinstance(block, dict):
                issues.append({
                    "field": f"domains.{domain}",
                    "severity": "error",
                    "message": "domain block must be an object",
                })
                continue
            instances = block.get("instances")
            if instances is not None and not isinstance(instances, dict):
                issues.append({
                    "field": f"domains.{domain}.instances",
                    "severity": "error",
                    "message": "instances must be an object",
                })
            elif isinstance(instances, dict):
                for iid, rec in instances.items():
                    if not isinstance(rec, dict):
                        issues.append({
                            "field": f"domains.{domain}.instances.{iid}",
                            "severity": "error",
                            "message": "instance record must be an object",
                        })
                        continue
                    if "type" in rec and not isinstance(rec.get("type"), str):
                        issues.append({
                            "field": f"domains.{domain}.instances.{iid}.type",
                            "severity": "error",
                            "message": "type must be a string",
                        })

    return issues
