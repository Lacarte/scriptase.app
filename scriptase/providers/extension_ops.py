"""Browser-extension ops resolved through the provider hub (step 16.1).

``app.py`` used to hard-branch on fixed wire labels for Chromium activate /
health / focus and for pipeline preflight. Those labels were both provider
aliases and response keys, so adding a third extension provider required
editing the entry point.

This module discovers every ``kind='extension'`` provider via the hub, resolves
id-or-alias the same way dispatch does, and delegates the three browser-ops
(``is_extension_connected``, ``activate_tab``, ``focus_studio_tab``) to the
runtime module the provider itself uses. Core code never names a concrete
provider id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ExtensionOps:
    """The three browser-ops every extension provider exposes on its runtime."""

    provider_id: str
    domain: str
    label: str
    is_connected: Callable[[], bool]
    activate: Callable[[], Any]
    focus: Callable[[], Any]


def _runtime_module(instance) -> Any | None:
    """Reach the module that owns the WebSocket client pool.

    Providers expose a zero-argument ``_runtime()`` (the same one ``submit`` and
    ``health_check`` use). Falling back to the constructed object itself keeps
    a future provider that puts the hooks on the instance working.
    """
    try:
        obj = instance.create()
    except Exception:
        return None
    runtime = getattr(obj, "_runtime", None)
    if callable(runtime):
        try:
            return runtime()
        except Exception:
            return None
    return obj


def _ops_from_instance(instance) -> ExtensionOps | None:
    if getattr(instance, "kind", None) != "extension":
        return None
    mod = _runtime_module(instance)
    if mod is None:
        return None
    connected = getattr(mod, "is_extension_connected", None)
    activate = getattr(mod, "activate_tab", None)
    focus = getattr(mod, "focus_studio_tab", None)
    if not all(callable(fn) for fn in (connected, activate, focus)):
        return None
    return ExtensionOps(
        provider_id=instance.id,
        domain=instance.manifest.domain,
        label=instance.manifest.label,
        is_connected=connected,
        activate=activate,
        focus=focus,
    )


def iter_extensions() -> list[ExtensionOps]:
    """Every registered extension provider that exposes browser ops."""
    from scriptase.providers.hub import hub

    found: list[ExtensionOps] = []
    for domain in hub.domains():
        for instance in hub.list(domain):
            ops = _ops_from_instance(instance)
            if ops is not None:
                found.append(ops)
    return found


def resolve_extension(name: str) -> ExtensionOps | None:
    """Resolve a canonical id or input alias to extension ops.

    Returns ``None`` when the name is empty, unknown, or names a non-extension
    provider (cloud/local providers skip the connectivity probe).

    Domain order matters for bare aliases that collide with a real id in another
    domain (e.g. the script package is named for the historical AI path while
    the storyboard extension also accepts that string as an *alias*). Only
    ``kind='extension'`` matches are returned.
    """
    key = str(name or "").strip()
    if not key:
        return None
    from scriptase.providers.hub import hub

    for domain in hub.domains():
        instance = hub.get(domain, key)
        if instance is None:
            continue
        if getattr(instance, "kind", None) != "extension":
            continue
        return _ops_from_instance(instance)
    return None


def health_snapshot() -> dict[str, dict]:
    """``{provider_id: {connected, label, domain}}`` for every extension."""
    result: dict[str, dict] = {}
    for ops in iter_extensions():
        try:
            connected = bool(ops.is_connected())
        except Exception:
            connected = False
        result[ops.provider_id] = {
            "connected": connected,
            "label": ops.label,
            "domain": ops.domain,
        }
    return result


def focus_all() -> dict[str, bool]:
    """Ask every connected extension to focus the Studio tab.

    Returns ``{provider_id: sent}``. A failure on one provider never aborts the
    rest — the same isolation rule the entry point always applied.
    """
    results: dict[str, bool] = {}
    for ops in iter_extensions():
        try:
            results[ops.provider_id] = bool(ops.focus())
        except Exception:
            results[ops.provider_id] = False
    return results


__all__ = [
    "ExtensionOps",
    "iter_extensions",
    "resolve_extension",
    "health_snapshot",
    "focus_all",
]
