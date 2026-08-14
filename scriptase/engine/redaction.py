"""Recursive secret redaction for every workflow persistence/emission boundary."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable, Mapping

REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = {
    "api_key", "apikey", "access_token", "authorization", "auth_token", "bearer_token",
    "client_secret", "password", "passwd", "private_key", "refresh_token", "secret", "secret_key",
}
_SENSITIVE_SUFFIXES = ("_api_key", "_access_token", "_auth_token", "_password", "_private_key",
                       "_refresh_token", "_secret_key")
_INLINE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;&]+"),
    re.compile(r"(?i)([?&](?:api[_-]?key|token|password|secret)=)[^&#\s]+"),
)


def is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def collect_secrets(value: Any) -> set[str]:
    """Collect scalar values stored under explicitly sensitive keys."""
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if is_sensitive_key(key) and isinstance(child, (str, bytes)):
                    text = child.decode("utf-8", "ignore") if isinstance(child, bytes) else child
                    if text:
                        found.add(text)
                else:
                    visit(child)
        elif isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child)

    visit(value)
    return found


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    result = text
    for secret in sorted({str(item) for item in secrets if item}, key=len, reverse=True):
        result = result.replace(secret, REDACTED)
    for pattern in _INLINE_PATTERNS:
        if pattern.groups:
            result = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + REDACTED, result)
        else:
            result = pattern.sub(REDACTED, result)
    return result


def redact(value: Any, *, secrets: Iterable[str] = ()) -> Any:
    """Return a detached, JSON-safe-shape copy with secrets removed."""
    known = set(secrets) | collect_secrets(value)

    def scrub(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                key: REDACTED if is_sensitive_key(key) else scrub(child)
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [scrub(child) for child in item]
        if isinstance(item, tuple):
            return [scrub(child) for child in item]
        if isinstance(item, str):
            return redact_text(item, known)
        if isinstance(item, bytes):
            return redact_text(item.decode("utf-8", "replace"), known)
        return deepcopy(item)

    return scrub(value)


class Redactor:
    """Run-scoped redactor which remembers secrets found in the workflow snapshot."""

    def __init__(self, source: Any = None, *, secrets: Iterable[str] = ()):
        self.secrets = set(secrets) | collect_secrets(source)

    def __call__(self, value: Any) -> Any:
        self.secrets.update(collect_secrets(value))
        return redact(value, secrets=self.secrets)
