"""Settings Manager — load, save, validate, atomic writes, redaction.

Canonical source of truth for nested provider settings at settings/settings.json,
and the single authority for `domains.<domain>.selected_provider` (contracts.md
§24). Thread-safe with file locking.

Step 11.3 moved the secret vocabulary into `settings_schema` and made environment
variables a read-time fallback rather than a seed (§22.6): nothing here copies an
API key out of the environment, and first-run seeding never writes a selection.
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
    `selected_provider` — the `INWORLD_API_KEY` selection side effect is removed
    (§14.3, §22.6).
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

    Uses write-to-temp-then-rename for atomicity.
    """
    _ensure_settings_dir()

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
            spec.id: {
                "selected_provider": spec.default_provider,
                "per_provider": {}
            }
            for spec in DOMAINS.values()
        }
    }


def get_domain_settings(domain: str) -> dict:
    """Get settings for a specific domain."""
    settings = load_settings()
    return settings.get("domains", {}).get(domain, {})


def get_provider_settings(domain: str, provider_id: str) -> dict:
    """Get stored settings for a specific provider.

    Values are returned exactly as stored — never resolved against the
    environment. Environment fallbacks are provider-internal (§22.6).
    """
    domain_settings = get_domain_settings(domain)
    return domain_settings.get("per_provider", {}).get(provider_id, {})


def set_provider_settings(domain: str, provider_id: str, provider_settings: dict) -> None:
    """Set settings for a specific provider."""
    settings = load_settings()
    if "domains" not in settings:
        settings["domains"] = {}
    if domain not in settings["domains"]:
        settings["domains"][domain] = {"selected_provider": None, "per_provider": {}}
    if "per_provider" not in settings["domains"][domain]:
        settings["domains"][domain]["per_provider"] = {}

    settings["domains"][domain]["per_provider"][provider_id] = provider_settings
    save_settings(settings)


def set_selected_provider(domain: str, provider_id: str) -> None:
    """Set the selected provider for a domain."""
    settings = load_settings()
    if "domains" not in settings:
        settings["domains"] = {}
    if domain not in settings["domains"]:
        settings["domains"][domain] = {"selected_provider": None, "per_provider": {}}

    settings["domains"][domain]["selected_provider"] = provider_id
    save_settings(settings)


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


def redacted_provider_settings(domain: str, provider_id: str, schema: dict | None = None) -> dict:
    """Get redacted settings for a specific provider."""
    return redact_settings(get_provider_settings(domain, provider_id), schema)


def portable_provider_settings(domain: str, provider_id: str, schema: dict | None = None) -> dict:
    """The non-secret half of a provider's settings.

    Durable secrets stay in `settings.json`; only these portable options may be
    copied into a job manifest, a workflow snapshot, or an export (§22.6).
    """
    _, options = split_settings(schema, get_provider_settings(domain, provider_id))
    return options


def merge_provider_settings(
    domain: str, provider_id: str, patch: dict, schema: dict | None = None
) -> dict:
    """Merge a client patch over stored provider settings, honoring the sentinel.

    A secret field submitted as exactly `"***"` is the redacted value the client
    was served and leaves the stored secret untouched (§22.6).
    """
    return apply_settings_patch(get_provider_settings(domain, provider_id), patch, schema)


def restore_redacted_secrets(stored: Any, incoming: Any) -> Any:
    """Recursively drop sentinel secrets from a whole-document settings write.

    `PUT /api/settings/v2` round-trips the entire document, so a redacted read
    would otherwise write `"***"` over every stored secret.
    """
    if not isinstance(incoming, dict):
        return incoming
    stored = stored if isinstance(stored, dict) else {}
    result: dict = {}
    for key, value in incoming.items():
        if value == REDACTION_SENTINEL and SENSITIVE_KEYS_RE.search(key):
            if key in stored:
                result[key] = stored[key]
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
        for domain in domains:
            if domain not in DOMAINS:
                issues.append({
                    "field": f"domains.{domain}",
                    "severity": "warning",
                    "message": f"Unknown domain '{domain}'"
                })

    return issues
