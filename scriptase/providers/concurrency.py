"""Capability-derived execution exclusivity — step 15.1.

Some providers cannot run two invocations at once: `kokoro` holds one ONNX
session and one G2P engine for the whole process, so two concurrent
`kokoro.create()` calls corrupt each other's state. Before this module that was
enforced by a module-level `generation_inference_lock` that callers had to know
to import — which is exactly why a second, never-acquired copy of the same lock
existed in the provider package (contracts.md B5 / K1).

Exclusivity is now **declared**, not hardcoded: a provider sets
`capabilities={"exclusive_execution": True}` in its manifest and the platform
serializes it. The lock is keyed by `(domain, provider_id)`, so two providers
never contend with each other and a provider that does not declare the
capability pays nothing.

The lock is re-entrant on purpose. A legacy route may already hold it when it
reaches a provider method that takes it again; with a plain `Lock` that is a
deadlock, and the pre-existing behavior it replaces was a single lock acquired
once per synthesis.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

EXCLUSIVE_EXECUTION = "exclusive_execution"

_locks: dict[tuple[str, str], threading.RLock] = {}
_locks_guard = threading.Lock()


def exclusive_lock(domain: str, provider_id: str) -> threading.RLock:
    """The one process-wide lock for `(domain, provider_id)`.

    Always returns the same object for the same pair, whoever asks and however
    the provider module was loaded — the property the two duplicated Kokoro
    locks did not have.
    """
    key = (str(domain or ""), str(provider_id or ""))
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def is_exclusive(capabilities: Any) -> bool:
    """True when this capability mapping declares `exclusive_execution`."""
    if isinstance(capabilities, dict):
        return bool(capabilities.get(EXCLUSIVE_EXECUTION))
    return bool(getattr(capabilities, EXCLUSIVE_EXECUTION, False))


@contextmanager
def exclusive_execution(
    domain: str, provider_id: str, *, capabilities: Any = None
) -> Iterator[None]:
    """Serialize this block iff the provider declares `exclusive_execution`.

    `capabilities` may be the manifest's capability mapping. When it is omitted
    the manifest is resolved through the hub, so a caller that only knows the two
    identifiers still gets the declared behavior.
    """
    if capabilities is None:
        capabilities = _capabilities_for(domain, provider_id)
    if not is_exclusive(capabilities):
        yield
        return
    with exclusive_lock(domain, provider_id):
        yield


def _capabilities_for(domain: str, provider_id: str) -> dict:
    """Manifest capabilities for a provider, or `{}` when it cannot be resolved.

    Resolution failure means "not exclusive" rather than an error: exclusivity is
    an optimization of correctness for one provider, and an unknown provider is
    about to fail on its own terms anyway.
    """
    from scriptase.providers.hub import hub

    try:
        instance = hub.get(domain, provider_id)
    except Exception:
        return {}
    if instance is None:
        return {}
    return dict(instance.capabilities or {})


__all__ = [
    "EXCLUSIVE_EXECUTION",
    "exclusive_execution",
    "exclusive_lock",
    "is_exclusive",
]
