"""Secret references — indirection for credentials in the settings store.

Step 3.4 / contracts.md §7: no credential is ever stored inline in
``settings.json``. Secret fields hold ``{"$secret": "<ref>"}`` and the
plaintext lives only in the machine-local secret store
(``settings/secrets.json``). Resolution is call-time only, through
``ProviderInstance.resolve_settings()``.

A reference is not itself a secret: redaction of a settings document that only
carries refs is a no-op for those values, and the browser still receives the
``***`` sentinel for password-shaped fields via the existing redaction path.
"""

from __future__ import annotations

import json
import os
import secrets as _secrets
import tempfile
import threading
from typing import Any

from loguru import logger

from config import ROOT_DIR
from scriptase.providers.settings_schema import (
    REDACTION_SENTINEL,
    is_secret_field,
    properties,
)


# Wire form frozen in contracts.md §7 / §14.
SECRET_REF_KEY = "$secret"

SECRETS_DIR = os.path.join(ROOT_DIR, "settings")
SECRETS_PATH = os.path.join(SECRETS_DIR, "secrets.json")

_lock = threading.RLock()


class SecretRefUnresolved(LookupError):
    """Raised when a ``{"$secret": ref}`` cannot be resolved at call time."""

    def __init__(self, ref: str, message: str | None = None):
        self.ref = ref
        super().__init__(message or f"Secret reference {ref!r} could not be resolved")


# -- wire form helpers -------------------------------------------------------


def is_secret_ref(value: Any) -> bool:
    """True when ``value`` is the frozen ``{"$secret": "<ref>"}`` wire form."""
    if not isinstance(value, dict) or len(value) != 1:
        return False
    ref = value.get(SECRET_REF_KEY)
    return isinstance(ref, str) and bool(ref.strip())


def make_secret_ref(ref_id: str) -> dict[str, str]:
    """Build a secret-reference object for storage in settings."""
    if not isinstance(ref_id, str) or not ref_id.strip():
        raise ValueError("secret ref id must be a non-empty string")
    return {SECRET_REF_KEY: ref_id.strip()}


def secret_ref_id(value: Any) -> str | None:
    """Extract the ref id from a secret-ref object, or ``None``."""
    if is_secret_ref(value):
        return str(value[SECRET_REF_KEY]).strip()
    return None


def new_ref_id() -> str:
    """Allocate an opaque secret reference id."""
    return f"s_{_secrets.token_hex(12)}"


# -- secret store ------------------------------------------------------------


def _default_store() -> dict:
    return {"version": 1, "secrets": {}}


def _ensure_dir() -> None:
    os.makedirs(SECRETS_DIR, exist_ok=True)


def load_secret_store() -> dict:
    """Load the secret store document. Missing/corrupt → empty store."""
    with _lock:
        try:
            with open(SECRETS_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return _default_store()
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("[secrets] Corrupted secrets.json: {}; starting empty", exc)
            return _default_store()
    if not isinstance(data, dict):
        return _default_store()
    secrets = data.get("secrets")
    if not isinstance(secrets, dict):
        data = _default_store()
    else:
        data.setdefault("version", 1)
        data["secrets"] = {
            str(k): v for k, v in secrets.items() if isinstance(k, str) and isinstance(v, str)
        }
    return data


def save_secret_store(data: dict) -> None:
    """Atomically persist the secret store."""
    _ensure_dir()
    payload = {
        "version": int(data.get("version") or 1),
        "secrets": {
            str(k): v
            for k, v in (data.get("secrets") or {}).items()
            if isinstance(k, str) and isinstance(v, str)
        },
    }
    with _lock:
        temp_fd, temp_path = tempfile.mkstemp(
            dir=SECRETS_DIR, prefix=".secrets_", suffix=".tmp"
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, SECRETS_PATH)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise


def get_secret(ref_id: str) -> str | None:
    """Return the plaintext for ``ref_id``, or ``None`` when unknown."""
    if not ref_id:
        return None
    store = load_secret_store()
    value = store.get("secrets", {}).get(ref_id)
    return value if isinstance(value, str) else None


def put_secret(ref_id: str, value: str) -> None:
    """Write or replace a secret value under ``ref_id``."""
    if not ref_id:
        raise ValueError("ref_id must be a non-empty string")
    if not isinstance(value, str):
        raise TypeError("secret value must be a string")
    with _lock:
        store = load_secret_store()
        store.setdefault("secrets", {})[ref_id] = value
        save_secret_store(store)


def delete_secret(ref_id: str) -> None:
    """Remove a secret by ref id. No-op when unknown."""
    if not ref_id:
        return
    with _lock:
        store = load_secret_store()
        secrets = store.get("secrets") or {}
        if ref_id in secrets:
            del secrets[ref_id]
            store["secrets"] = secrets
            save_secret_store(store)


def put_secret_allocating(value: str, *, existing_ref: str | None = None) -> str:
    """Store ``value`` under ``existing_ref`` or a newly allocated id; return the id."""
    ref = existing_ref if (isinstance(existing_ref, str) and existing_ref.strip()) else new_ref_id()
    put_secret(ref, value)
    return ref


# -- resolve -----------------------------------------------------------------


def resolve_secret_value(
    value: Any,
    *,
    strict: bool = False,
) -> Any:
    """Resolve one value: secret refs → plaintext; everything else unchanged.

    When ``strict`` is True and a ref cannot be resolved, raises
    :class:`SecretRefUnresolved`. Soft mode (default) yields ``""`` so
    availability / ``is_configured`` treat a broken ref as unconfigured.
    """
    ref = secret_ref_id(value)
    if ref is None:
        return value
    plaintext = get_secret(ref)
    if plaintext is None:
        if strict:
            raise SecretRefUnresolved(ref)
        return ""
    return plaintext


def resolve_secret_refs(
    settings: dict | None,
    *,
    strict: bool = False,
) -> dict:
    """Deep-copy ``settings``, replacing every secret ref with its plaintext.

    Plaintext strings (pre-migration fixtures, in-flight patches) pass through
    unchanged so validation can still see a newly submitted key before it is
    materialised into the store.
    """
    if not isinstance(settings, dict):
        return {}

    def walk(item: Any) -> Any:
        if is_secret_ref(item):
            return resolve_secret_value(item, strict=strict)
        if isinstance(item, dict):
            return {key: walk(child) for key, child in item.items()}
        if isinstance(item, list):
            return [walk(child) for child in item]
        return item

    return walk(dict(settings))


# -- extract (plaintext → refs on write) -------------------------------------


def _should_extract_key(key: str, schema: dict | None) -> bool:
    props = properties(schema) if schema is not None else {}
    prop = props.get(key) if props else None
    return is_secret_field(key, prop)


def extract_plaintext_from_settings(
    settings: dict | None,
    *,
    schema: dict | None = None,
    previous: dict | None = None,
) -> dict:
    """Replace plaintext secret values with ``{"$secret": ref}`` indirection.

    - Secret-ref values are left alone (already stored).
    - The redaction sentinel is never written (callers restore first).
    - Empty strings stay empty (cleared credentials).
    - Non-secret fields pass through unchanged.
    - When a field already held a ref in ``previous``, the same ref id is
      reused so updating a key does not orphan the prior store entry.
    """
    if not isinstance(settings, dict):
        return {}
    previous = previous if isinstance(previous, dict) else {}
    out: dict = {}
    for key, value in settings.items():
        if isinstance(value, dict) and not is_secret_ref(value):
            # Nested non-ref objects: recurse with matching previous bag.
            prev_child = previous.get(key) if isinstance(previous.get(key), dict) else None
            out[key] = extract_plaintext_from_settings(
                value, schema=None, previous=prev_child
            )
            continue

        if not _should_extract_key(key, schema):
            out[key] = value
            continue

        if is_secret_ref(value):
            out[key] = make_secret_ref(secret_ref_id(value) or "")
            continue

        if value == REDACTION_SENTINEL:
            # Caller should have restored; keep previous if present.
            prev = previous.get(key)
            out[key] = prev if prev is not None else ""
            continue

        if value is None or (isinstance(value, str) and not value.strip()):
            # Cleared credential — drop any previous ref value from the store
            # so an orphaned secret does not linger indefinitely.
            prev_ref = secret_ref_id(previous.get(key))
            if prev_ref:
                delete_secret(prev_ref)
            out[key] = "" if value is None or isinstance(value, str) else value
            continue

        if not isinstance(value, str):
            # Non-string secret-shaped field: leave as-is (schema validation
            # will flag type errors separately).
            out[key] = value
            continue

        existing_ref = secret_ref_id(previous.get(key))
        ref = put_secret_allocating(value, existing_ref=existing_ref)
        out[key] = make_secret_ref(ref)
    return out


def extract_plaintext_from_document(document: dict) -> dict:
    """Walk a full settings document and materialise every instance secret.

    Used by ``save_settings`` so whole-document PUT/PATCH paths and the v7
    migration share one extraction rule. Does not require per-provider schemas;
    secret-ness is decided by key name (and password widgets when a schema is
    later supplied at the instance-write path).
    """
    if not isinstance(document, dict):
        return document
    domains = document.get("domains")
    if not isinstance(domains, dict):
        return document

    result = dict(document)
    new_domains: dict = {}
    for domain, block in domains.items():
        if not isinstance(block, dict):
            new_domains[domain] = block
            continue
        new_block = dict(block)
        instances = block.get("instances")
        if isinstance(instances, dict):
            new_instances: dict = {}
            for iid, rec in instances.items():
                if not isinstance(rec, dict):
                    new_instances[iid] = rec
                    continue
                new_rec = dict(rec)
                settings = rec.get("settings")
                if isinstance(settings, dict):
                    new_rec["settings"] = extract_plaintext_from_settings(settings)
                new_instances[iid] = new_rec
            new_block["instances"] = new_instances
        # Pre-3.1 shape still possible mid-migration; extract there too.
        per_provider = block.get("per_provider")
        if isinstance(per_provider, dict):
            new_block["per_provider"] = {
                pid: (
                    extract_plaintext_from_settings(psettings)
                    if isinstance(psettings, dict)
                    else psettings
                )
                for pid, psettings in per_provider.items()
            }
        new_domains[domain] = new_block
    result["domains"] = new_domains
    return result


def document_contains_plaintext_secret(document: dict) -> list[str]:
    """Return dotted paths of any inline plaintext credentials still present.

    Used by the step 3.4 done-when gate and migration verification. Secret refs
    and empty strings are fine; non-empty strings under secret-shaped keys are
    not.
    """
    leaks: list[str] = []

    def visit(path: str, item: Any) -> None:
        if isinstance(item, dict):
            if is_secret_ref(item):
                return
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else key
                if is_secret_field(key) and isinstance(child, str) and child.strip():
                    if child != REDACTION_SENTINEL:
                        leaks.append(child_path)
                    continue
                visit(child_path, child)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(f"{path}[{index}]", child)

    visit("", document)
    return leaks


__all__ = [
    "SECRET_REF_KEY",
    "SECRETS_PATH",
    "SecretRefUnresolved",
    "delete_secret",
    "document_contains_plaintext_secret",
    "extract_plaintext_from_document",
    "extract_plaintext_from_settings",
    "get_secret",
    "is_secret_ref",
    "load_secret_store",
    "make_secret_ref",
    "new_ref_id",
    "put_secret",
    "put_secret_allocating",
    "resolve_secret_refs",
    "resolve_secret_value",
    "save_secret_store",
    "secret_ref_id",
]
