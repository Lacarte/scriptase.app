"""Manifest validation and exclusion records — step 11.2.

Implements the frozen validation order of contracts.md §20.3, the ten exclusion
reason codes of §21.4, and the message-sanitization rule of §25 (200 characters,
path-stripped, redacted).

Validation is pure: it never imports a provider, never touches the filesystem, and
never raises. `validate_manifest()` returns either a validated `ProviderManifest`
plus warnings, or an exclusion reason code plus a message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from scriptase.providers.settings_schema import SENSITIVE_KEYS_RE


# -- exclusion reason codes (contracts.md §21.4, frozen) --------------------

MANIFEST_LOAD_FAILED = "MANIFEST_LOAD_FAILED"
MANIFEST_MISSING = "MANIFEST_MISSING"
MANIFEST_RAISED = "MANIFEST_RAISED"
MANIFEST_INVALID_TYPE = "MANIFEST_INVALID_TYPE"
MANIFEST_FIELDS_MISSING = "MANIFEST_FIELDS_MISSING"
MANIFEST_ID_MISMATCH = "MANIFEST_ID_MISMATCH"
MANIFEST_DOMAIN_MISMATCH = "MANIFEST_DOMAIN_MISMATCH"
MANIFEST_FIELDS_INVALID = "MANIFEST_FIELDS_INVALID"
MANIFEST_UNSUPPORTED_CONTRACT = "MANIFEST_UNSUPPORTED_CONTRACT"
DUPLICATE_ID = "DUPLICATE_ID"

EXCLUSION_REASON_CODES = frozenset({
    MANIFEST_LOAD_FAILED,
    MANIFEST_MISSING,
    MANIFEST_RAISED,
    MANIFEST_INVALID_TYPE,
    MANIFEST_FIELDS_MISSING,
    MANIFEST_ID_MISMATCH,
    MANIFEST_DOMAIN_MISMATCH,
    MANIFEST_FIELDS_INVALID,
    MANIFEST_UNSUPPORTED_CONTRACT,
    DUPLICATE_ID,
})


# -- field rules (contracts.md §19.3, §20.1, §20.2) -------------------------

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
# Hyphens are legal in aliases but not in canonical ids: `kie-ai` is a shipped
# legacy wire value (§19.3).
ALIAS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)

KINDS = frozenset({"local", "cloud", "extension", "webhook"})

# Environment-variable names are internal metadata, never public settings keys.
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")

# A description is rendered as text in the provider modal; control characters have
# no legitimate place in it and would survive JSON encoding.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

REQUIRED_FIELDS = ("id", "label", "domain", "kind", "version", "capabilities")

# `1` is the legacy ABC shape every shipped manifest implies; `2` is the v2
# invocation contract implemented in 11.4 (§19.3).
SUPPORTED_CONTRACT_VERSIONS = frozenset({1, 2})

LABEL_MAX = 80
DESCRIPTION_MAX = 500
URL_MAX = 2048

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

MESSAGE_MAX = 200


# -- message sanitization (contracts.md §25) --------------------------------

# Two or more path segments, not preceded by `/`, `\`, `:` or a word character —
# the lookbehind keeps `https://host/a/b` intact while still catching `C:\a\b\c`
# and `/home/user/thing.py`.
_PATHISH_RE = re.compile(r"(?<![:/\\\w])((?:[A-Za-z]:)?(?:[\\/][^\s'\"()\\/]+){2,}[\\/]?)")
_SECRETISH_RE = re.compile(
    r"(?i)\b(" + SENSITIVE_KEYS_RE.pattern.strip("()") + r")\b\s*[:=]\s*\S+"
)
_SYNTHETIC_MODULE_RE = re.compile(r"_sts_provider_[A-Za-z0-9_]+")


def _basename(path: str) -> str:
    """Last segment of a path, for either separator, on either platform."""
    return path.rstrip("\\/").replace("\\", "/").rsplit("/", 1)[-1] or "<path>"


def sanitize_message(text: object) -> str:
    """Make an arbitrary exception string safe to ship to the browser.

    `redact_settings` only reaches structured dicts; an exception string can carry
    a secret or an absolute path anywhere inside it, so this strips paths to their
    basename, masks `key=value` pairs whose key looks sensitive, drops synthetic
    module names, and truncates to 200 characters (§21.4, §25).
    """
    message = " ".join(str(text or "").split())
    message = _SECRETISH_RE.sub(lambda m: f"{m.group(1)}=***", message)
    message = _SYNTHETIC_MODULE_RE.sub("<provider module>", message)
    message = _PATHISH_RE.sub(lambda m: _basename(m.group(0)), message)
    if len(message) > MESSAGE_MAX:
        message = message[: MESSAGE_MAX - 1].rstrip() + "\u2026"
    return message


# -- validation result ------------------------------------------------------


@dataclass
class ManifestValidation:
    """Outcome of validating one manifest payload.

    Exactly one of `manifest` / `reason_code` is set.
    """

    manifest: object | None = None
    warnings: list[str] = field(default_factory=list)
    reason_code: str | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.reason_code is None


def _fail(reason_code: str, message: str) -> ManifestValidation:
    return ManifestValidation(reason_code=reason_code, message=sanitize_message(message))


def _validate_url(value: str, field_name: str) -> str | None:
    """Return an error message, or `None` when the URL is safe to ship."""
    if len(value) > URL_MAX:
        return f"{field_name} exceeds {URL_MAX} characters"
    parsed = urlparse(value)
    if parsed.scheme == "https":
        return None
    # http is tolerated only for loopback development URLs; anything else (and in
    # particular javascript: / data:) must never reach window.open (§20.1).
    if parsed.scheme == "http" and (parsed.hostname or "") in _LOOPBACK_HOSTS:
        return None
    return f"{field_name} must be an absolute https URL"


def validate_manifest(
    folder_id: str,
    domain: str,
    payload: object,
    manifest_cls: type,
    capability_vocabulary: frozenset[str] | None = None,
) -> ManifestValidation:
    """Run the frozen §20.3 checks in order against a `manifest()` return value.

    Args:
        folder_id: the provider folder name, which the manifest id must equal.
        domain: the owning registry's domain.
        payload: whatever `manifest()` returned.
        manifest_cls: `ProviderManifest` (injected to keep this module import-light).
        capability_vocabulary: the domain's closed capability set, or `None` to skip.
    """
    warnings: list[str] = []

    # 3. ProviderManifest, or a dict coercible to one.
    if isinstance(payload, manifest_cls):
        data = dict(payload.__dict__)
    elif isinstance(payload, dict):
        data = dict(payload)
    else:
        return _fail(
            MANIFEST_INVALID_TYPE,
            f"manifest() returned {type(payload).__name__}, expected ProviderManifest or dict",
        )

    # Unknown top-level keys are ignored and warned rather than raising TypeError,
    # so a provider written against a newer build still loads here (§20.3, D6).
    known = set(getattr(manifest_cls, "__dataclass_fields__", {}))
    for key in sorted(set(data) - known):
        warnings.append(f"unknown manifest field: {key}")
        data.pop(key)

    # 4. Required fields present and correctly typed. An empty capabilities dict
    #    is valid, so this is a presence/type check, not a truthiness check.
    missing = []
    for name in REQUIRED_FIELDS:
        value = data.get(name)
        if value is None:
            missing.append(name)
        elif name == "capabilities":
            if not isinstance(value, dict):
                return _fail(MANIFEST_FIELDS_INVALID, "capabilities must be an object")
        elif not isinstance(value, str) or not value.strip():
            missing.append(name)
    if missing:
        return _fail(MANIFEST_FIELDS_MISSING, f"missing required fields: {sorted(missing)}")

    # 5. id == folder name.
    if data["id"] != folder_id:
        return _fail(
            MANIFEST_ID_MISMATCH, f"manifest.id {data['id']!r} != folder name {folder_id!r}"
        )

    # 6. domain matches the owning registry.
    if data["domain"] != domain:
        return _fail(
            MANIFEST_DOMAIN_MISMATCH,
            f"declares domain {data['domain']!r}, registered under {domain!r}",
        )

    # 7. Identity and field shapes (§19.3, §20.1, §20.2).
    if not ID_RE.match(data["id"]):
        return _fail(MANIFEST_FIELDS_INVALID, f"id {data['id']!r} does not match {ID_RE.pattern}")

    label = data["label"]
    if len(label) > LABEL_MAX:
        return _fail(MANIFEST_FIELDS_INVALID, f"label exceeds {LABEL_MAX} characters")

    if data["kind"] not in KINDS:
        # Never coerced to `cloud`: a future lifecycle class could need different
        # isolation or runtime hooks (§20.3).
        return _fail(
            MANIFEST_FIELDS_INVALID,
            f"unknown kind {data['kind']!r}, expected one of {sorted(KINDS)}",
        )

    if not SEMVER_RE.match(data["version"]):
        return _fail(MANIFEST_FIELDS_INVALID, f"version {data['version']!r} is not semver")

    capabilities = {}
    for key, value in data["capabilities"].items():
        if not isinstance(key, str):
            return _fail(MANIFEST_FIELDS_INVALID, "capability names must be strings")
        if not isinstance(value, bool):
            return _fail(MANIFEST_FIELDS_INVALID, f"capability {key!r} must be a boolean")
        if capability_vocabulary is not None and key not in capability_vocabulary:
            warnings.append(f"unknown capability: {key}")
            continue
        capabilities[key] = value
    data["capabilities"] = capabilities

    requires = data.get("requires") or []
    if not isinstance(requires, list) or not all(isinstance(k, str) and k for k in requires):
        return _fail(MANIFEST_FIELDS_INVALID, "requires must be a list of setting key names")
    data["requires"] = list(requires)

    aliases: list[str] = []
    raw_aliases = data.get("aliases") or []
    if not isinstance(raw_aliases, list):
        return _fail(MANIFEST_FIELDS_INVALID, "aliases must be a list")
    for alias in raw_aliases:
        if not isinstance(alias, str) or not ALIAS_RE.match(alias):
            return _fail(MANIFEST_FIELDS_INVALID, f"alias {alias!r} does not match {ALIAS_RE.pattern}")
        if alias == data["id"]:
            warnings.append(f"alias dropped (same as id): {alias}")
            continue
        if alias in aliases:
            continue
        aliases.append(alias)
    data["aliases"] = aliases

    for url_field in ("open_url", "docs_url"):
        url = data.get(url_field)
        if url is None:
            continue
        if not isinstance(url, str):
            return _fail(MANIFEST_FIELDS_INVALID, f"{url_field} must be a string")
        problem = _validate_url(url, url_field)
        if problem:
            return _fail(MANIFEST_FIELDS_INVALID, problem)

    description = data.get("description")
    if description is not None:
        if not isinstance(description, str):
            return _fail(MANIFEST_FIELDS_INVALID, "description must be a string")
        if len(description) > DESCRIPTION_MAX:
            return _fail(
                MANIFEST_FIELDS_INVALID, f"description exceeds {DESCRIPTION_MAX} characters"
            )
        if _CONTROL_CHARS_RE.search(description):
            return _fail(MANIFEST_FIELDS_INVALID, "description contains control characters")

    # `environment` maps a settings key to the environment variable it falls back
    # to. Only names are declared here; a value never enters the manifest (§22.6).
    environment = data.get("environment")
    if environment is None:
        environment = {}
    if not isinstance(environment, dict):
        return _fail(MANIFEST_FIELDS_INVALID, "environment must be an object")
    for setting_key, env_name in environment.items():
        if not isinstance(setting_key, str) or not setting_key:
            return _fail(MANIFEST_FIELDS_INVALID, "environment keys must be setting names")
        if not isinstance(env_name, str) or not ENV_NAME_RE.match(env_name):
            return _fail(
                MANIFEST_FIELDS_INVALID,
                f"environment[{setting_key!r}] must match {ENV_NAME_RE.pattern}",
            )
    data["environment"] = dict(environment)

    # 8. contract_version supported by this build.
    contract_version = data.get("contract_version", 1)
    if isinstance(contract_version, bool) or not isinstance(contract_version, int):
        return _fail(MANIFEST_FIELDS_INVALID, "contract_version must be an integer")
    if contract_version < 1:
        return _fail(MANIFEST_FIELDS_INVALID, "contract_version must be positive")
    if contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        return _fail(
            MANIFEST_UNSUPPORTED_CONTRACT,
            f"contract_version {contract_version} is newer than this build supports",
        )
    data["contract_version"] = contract_version

    try:
        manifest = manifest_cls(**data)
    except Exception as exc:  # defensive: every field above is already checked
        return _fail(MANIFEST_FIELDS_INVALID, f"could not build manifest: {exc}")

    return ManifestValidation(manifest=manifest, warnings=warnings)


__all__ = [
    "EXCLUSION_REASON_CODES",
    "MANIFEST_LOAD_FAILED",
    "MANIFEST_MISSING",
    "MANIFEST_RAISED",
    "MANIFEST_INVALID_TYPE",
    "MANIFEST_FIELDS_MISSING",
    "MANIFEST_ID_MISMATCH",
    "MANIFEST_DOMAIN_MISMATCH",
    "MANIFEST_FIELDS_INVALID",
    "MANIFEST_UNSUPPORTED_CONTRACT",
    "DUPLICATE_ID",
    "ID_RE",
    "ALIAS_RE",
    "SEMVER_RE",
    "ENV_NAME_RE",
    "KINDS",
    "DESCRIPTION_MAX",
    "SUPPORTED_CONTRACT_VERSIONS",
    "ManifestValidation",
    "sanitize_message",
    "validate_manifest",
]
