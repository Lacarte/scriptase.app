"""Provider settings schemas — validation, secrets, and visibility (step 11.3).

Implements the frozen settings contract of contracts.md §22:

  - §22.1 the JSON-Schema subset a provider's `settings_schema()` returns
  - §22.2 the widget vocabulary, where an unrecognized `ui.type` is a warning
  - §22.3 `ui.show_if`, where a hidden field keeps its value, is never required,
    and never reaches the invocation config
  - §22.4 `ui.options` and `ui.options_source` are mutually exclusive
  - §22.5 issue shape `{field, severity, message}`, unknown saved keys preserved
    and warned, required-but-empty is an error
  - §22.6 what counts as a secret, and the `"***"` sentinel that makes a secret
    field write-only

This module is the leaf of the settings import chain: it imports nothing from the
rest of the package, so `settings_manager` and `registry` can both build on it.
"""

from __future__ import annotations

import re


# -- secrets (contracts.md §22.6) -------------------------------------------

# A field is a secret if `ui.type == "password"` or its key matches this pattern.
SENSITIVE_KEYS_RE = re.compile(
    r"(api_key|token|secret|password|auth|bearer|credential)",
    re.IGNORECASE,
)

# What a redacted secret is replaced with on the way out, and the exact value the
# client may send back to mean "leave the stored secret alone".
REDACTION_SENTINEL = "***"


# -- widget vocabulary (contracts.md §22.2) ---------------------------------

# `textarea` is frozen here even though 12.4 owns rendering it; `text` and
# `number` are the explicit spellings of the absent-`ui.type` fallback and are
# already used by shipped schemas.
WIDGET_TYPES = frozenset({
    "text",
    "number",
    "password",
    "dropdown",
    "select",
    "slider",
    "toggle",
    "textarea",
})

SEVERITIES = ("error", "warning", "info")
_SEVERITY_RANK = {severity: index for index, severity in enumerate(SEVERITIES)}

_TYPE_CHECKS = {
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
}


def _issue(field: str, severity: str, message: str) -> dict:
    return {"field": field, "severity": severity, "message": message}


def properties(schema: dict | None) -> dict:
    """The `properties` block of a schema, or `{}` for an absent/odd schema."""
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def _ui(prop: object) -> dict:
    if not isinstance(prop, dict):
        return {}
    ui = prop.get("ui")
    return ui if isinstance(ui, dict) else {}


# -- visibility (contracts.md §22.3) ----------------------------------------


def is_visible(prop: object, values: dict) -> bool:
    """Evaluate `ui.show_if`: AND across keys, OR within each list of values."""
    show_if = _ui(prop).get("show_if")
    if not isinstance(show_if, dict) or not show_if:
        return True
    for field_name, allowed in show_if.items():
        candidates = allowed if isinstance(allowed, list) else [allowed]
        if values.get(field_name) not in candidates:
            return False
    return True


def visible_fields(schema: dict | None, values: dict) -> set[str]:
    """Schema property names whose `ui.show_if` condition currently holds."""
    return {
        key for key, prop in properties(schema).items() if is_visible(prop, values)
    }


# -- secrets ----------------------------------------------------------------


def is_secret_field(key: str, prop: object = None) -> bool:
    """True when `key` is a secret by widget type or by name (§22.6)."""
    if _ui(prop).get("type") == "password":
        return True
    return bool(SENSITIVE_KEYS_RE.search(key))


def secret_keys(schema: dict | None) -> set[str]:
    """Every schema property that is a secret."""
    return {
        key for key, prop in properties(schema).items() if is_secret_field(key, prop)
    }


def split_settings(schema: dict | None, values: dict) -> tuple[dict, dict]:
    """Split stored settings into `(secrets, options)`.

    Secrets are durable and machine-local; options are portable and safe to carry
    into a workflow snapshot, an export, or a per-run config.
    """
    props = properties(schema)
    secrets: dict = {}
    options: dict = {}
    for key, value in values.items():
        target = secrets if is_secret_field(key, props.get(key)) else options
        target[key] = value
    return secrets, options


def redact(values: dict, schema: dict | None = None) -> dict:
    """Replace every secret value with the sentinel, recursing into nested dicts.

    After step 3.4, a stored secret is usually ``{"$secret": "<ref>"}``. A
    reference is not itself a credential, but the browser still receives the
    password-field sentinel so the existing write-only UI round-trip is
    unchanged. Nested non-ref dicts continue to recurse.
    """
    if not isinstance(values, dict):
        return values
    # Local import keeps this module a leaf of the settings import chain.
    from scriptase.providers.secrets import is_secret_ref

    props = properties(schema)
    redacted: dict = {}
    for key, value in values.items():
        if is_secret_field(key, props.get(key)) or is_secret_ref(value):
            redacted[key] = REDACTION_SENTINEL
        elif isinstance(value, dict):
            redacted[key] = redact(value)
        elif isinstance(value, list):
            redacted[key] = [
                redact(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            redacted[key] = value
    return redacted


def apply_settings_patch(stored: dict, patch: dict, schema: dict | None = None) -> dict:
    """Merge a client patch over stored settings, honoring the secret sentinel.

    A secret field whose submitted value is exactly `"***"` is the redacted value
    the client was served; it means "unchanged" and must never overwrite the real
    stored secret or secret reference (§22.6 / step 3.4).
    """
    from scriptase.providers.secrets import is_secret_ref

    props = properties(schema)
    merged = dict(stored)
    for key, value in (patch or {}).items():
        if value == REDACTION_SENTINEL and is_secret_field(key, props.get(key)):
            continue
        # Clients do not author secret refs; keep the stored ref on an
        # accidental round-trip of a non-redacted document.
        if is_secret_ref(value) and is_secret_field(key, props.get(key)):
            if key in stored:
                continue
        merged[key] = value
    return merged


# -- invocation config (contracts.md §22.3) ---------------------------------


def invocation_config(schema: dict | None, values: dict) -> dict:
    """The settings a provider invocation may see.

    Hidden fields keep their stored value but are not sent. Keys with no schema
    property are passed through: an unknown key is preserved, not dropped (§22.5).
    """
    props = properties(schema)
    return {
        key: value
        for key, value in values.items()
        if key not in props or is_visible(props[key], values)
    }


# -- validation (contracts.md §22.5) ----------------------------------------


def is_empty(value: object) -> bool:
    """Empty for the purposes of `required`. `False` and `0` are *not* empty.

    A well-formed secret reference counts as present (the credential is held
    out-of-band); validation that needs the plaintext must call
    ``resolve_settings`` first.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    # Local import: keep this module a leaf of the settings import chain.
    from scriptase.providers.secrets import is_secret_ref

    if is_secret_ref(value):
        return False
    if isinstance(value, (list, dict, tuple, set)):
        return not value
    return False


def _validate_ui_hints(key: str, prop: dict) -> list[dict]:
    """Schema-authoring problems. Never errors — they must not block saving."""
    issues: list[dict] = []
    ui = _ui(prop)
    widget = ui.get("type")
    if widget is not None and widget not in WIDGET_TYPES:
        issues.append(_issue(
            key, "warning", f"Unknown widget type '{widget}'; rendered as a text input"
        ))
    if ui.get("options") is not None and ui.get("options_source") is not None:
        issues.append(_issue(
            key, "warning", "Both options and options_source are set; options_source wins"
        ))
    return issues


def _validate_value(key: str, prop: dict, value: object) -> list[dict]:
    issues: list[dict] = []

    declared = prop.get("type")
    check = _TYPE_CHECKS.get(declared) if isinstance(declared, str) else None
    if check is not None and not check(value):
        return [_issue(
            key,
            "error",
            f"{prop.get('label') or key} must be of type {declared}",
        )]

    choices = prop.get("enum")
    if isinstance(choices, list) and choices and value not in choices:
        issues.append(_issue(
            key, "error", f"{prop.get('label') or key} must be one of: {', '.join(map(str, choices))}"
        ))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = prop.get("minimum")
        maximum = prop.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            issues.append(_issue(
                key, "error", f"{prop.get('label') or key} must be at least {minimum}"
            ))
        if isinstance(maximum, (int, float)) and value > maximum:
            issues.append(_issue(
                key, "error", f"{prop.get('label') or key} must be at most {maximum}"
            ))

    return issues


def validate_against_schema(schema: dict | None, values: dict) -> list[dict]:
    """Validate stored settings against a provider settings schema.

    Returns `{field, severity, message}` dicts in a deterministic order. An absent
    schema validates nothing — a provider without `settings_schema.py` is valid by
    construction.
    """
    props = properties(schema)
    if not props:
        return []

    values = values if isinstance(values, dict) else {}
    required = schema.get("required") if isinstance(schema, dict) else None
    required = set(required) if isinstance(required, list) else set()
    visible = visible_fields(schema, values)

    issues: list[dict] = []

    # Unknown saved keys are preserved and warned — dropping them would silently
    # destroy configuration on a provider downgrade (§22.5).
    for key in values:
        if key not in props:
            issues.append(_issue(
                key, "warning", f"Unknown setting '{key}' is kept but not used by this provider"
            ))

    for key, prop in props.items():
        if not isinstance(prop, dict):
            issues.append(_issue(key, "warning", "Schema property is not an object; ignored"))
            continue
        if key not in visible:
            # Hidden fields keep their value and are exempt from required (§22.3).
            continue

        issues.extend(_validate_ui_hints(key, prop))

        value = values.get(key)
        if is_empty(value):
            if key in required:
                issues.append(_issue(
                    key, "error", f"{prop.get('label') or key} is required"
                ))
            continue

        issues.extend(_validate_value(key, prop, value))

    issues.sort(key=lambda i: (i["field"], _SEVERITY_RANK.get(i["severity"], len(SEVERITIES))))
    return issues


__all__ = [
    "SENSITIVE_KEYS_RE",
    "REDACTION_SENTINEL",
    "WIDGET_TYPES",
    "SEVERITIES",
    "apply_settings_patch",
    "invocation_config",
    "is_empty",
    "is_secret_field",
    "is_visible",
    "properties",
    "redact",
    "secret_keys",
    "split_settings",
    "validate_against_schema",
    "visible_fields",
]
