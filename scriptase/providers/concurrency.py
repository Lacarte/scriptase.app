"""Capability-derived execution exclusivity — step 15.1 / 3.1.

Some providers cannot run two invocations at once: `kokoro` holds one ONNX
session and one G2P engine for the whole process, so two concurrent
`kokoro.create()` calls corrupt each other's state. Before this module that was
enforced by a module-level `generation_inference_lock` that callers had to know
to import — which is exactly why a second, never-acquired copy of the same lock
existed in the provider package (contracts.md B5 / K1).

Exclusivity is now **declared**, not hardcoded: a provider sets
`capabilities={"exclusive_execution": True}` in its manifest and the platform
serializes it. The lock is keyed by `(domain, provider_type, instance_id)`
(step 3.1), so two configured instances never contend with each other and a
provider that does not declare the capability pays nothing.

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

_locks: dict[tuple[str, str, str], threading.RLock] = {}
_locks_guard = threading.Lock()


def exclusive_lock(
    domain: str,
    provider_id: str,
    instance_id: str | None = None,
) -> threading.RLock:
    """The one process-wide lock for `(domain, provider_type, instance_id)`.

    Always returns the same object for the same triple, whoever asks and however
    the provider module was loaded — the property the two duplicated Kokoro
    locks did not have. When `instance_id` is omitted it defaults to the
    provider type id (the default-instance convention from step 3.1).
    """
    type_id = str(provider_id or "")
    key = (str(domain or ""), type_id, str(instance_id or type_id))
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
    domain: str,
    provider_id: str,
    *,
    instance_id: str | None = None,
    capabilities: Any = None,
) -> Iterator[None]:
    """Serialize this block iff the provider declares `exclusive_execution`.

    `capabilities` may be the manifest's capability mapping. When it is omitted
    the manifest is resolved through the hub, so a caller that only knows the
    identifiers still gets the declared behavior.
    """
    type_id = str(provider_id or "")
    resolved_instance = str(instance_id or type_id)
    if capabilities is None:
        capabilities = _capabilities_for(domain, type_id)
    if not is_exclusive(capabilities):
        yield
        return
    with exclusive_lock(domain, type_id, resolved_instance):
        yield


def _capabilities_for(domain: str, provider_id: str) -> dict:
    """Manifest capabilities for a provider type, or `{}` when unresolved.

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
