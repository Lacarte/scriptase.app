"""Provider hub — one process-wide registry of registries (contracts.md §27).

The hub owns exactly one `ProviderRegistry` per catalog domain and resolves
`(domain, provider_id)` across all of them. The per-module
`scriptase/modules/<module>/providers/__init__.py` files are thin compatibility facades built
by `bind_domain()` — they no longer own a registry of their own.

Step 11.2 adds the lazily memoized `create()` factory, real `shutdown()` of
constructed providers, alias resolution, manifest-driven runtime binding, and the
guarded reload that keeps the last good catalog after an invalid edit.
"""

# `ProviderHub.list` shadows the builtin inside the class body, so annotations
# must stay lazy.
from __future__ import annotations

import atexit
import threading
from dataclasses import dataclass, field
from typing import Callable

from loguru import logger

from scriptase.providers.domains import DOMAINS, DomainSpec, get_domain
from scriptase.providers.registry import (
    CatalogSnapshot,
    ProviderInstance,
    ProviderRegistry,
)
from scriptase.providers.runtime import call_provider_runtime


# `extension` is the only kind whose register_runtime() is called at boot
# (contracts.md §20.2). `push_callbacks` is the capability that declares the same
# behavior; a provider that claims it without being an extension is warned about
# rather than silently given a WebSocket runtime.
RUNTIME_KIND = "extension"
RUNTIME_CAPABILITY = "push_callbacks"


@dataclass
class ReloadReport:
    """Outcome of one guarded catalog reload."""

    swapped: list[str] = field(default_factory=list)
    retained: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"swapped": self.swapped, "retained": self.retained}


class ProviderHub:
    """Process-wide hub over the domain catalog."""

    def __init__(self, catalog: dict[str, DomainSpec] | None = None):
        self._catalog = catalog if catalog is not None else DOMAINS
        self._registries: dict[str, ProviderRegistry] = {}
        self._lock = threading.RLock()
        self._runtime_target = None
        # `(domain, provider_id)` pairs whose `register_runtime()` already ran. A
        # WebSocket route may only be registered once per process, so binding has
        # to survive a repeated startup call and a catalog reload that rebuilds
        # the `ProviderInstance` objects (step 11.5).
        self._runtime_bound: set[tuple[str, str]] = set()

    # -- catalog -----------------------------------------------------------

    def domains(self) -> list[str]:
        """Domain ids in catalog declaration order (contracts.md §21.2)."""
        return list(self._catalog)

    def spec(self, domain: str) -> DomainSpec:
        """Return the `DomainSpec` for `domain`, or raise `ValueError`."""
        try:
            return self._catalog[domain]
        except KeyError:
            return get_domain(domain)

    def registry(self, domain: str) -> ProviderRegistry:
        """Return the one registry for `domain`, creating it on first use."""
        with self._lock:
            existing = self._registries.get(domain)
            if existing is not None:
                return existing
            spec = self.spec(domain)  # validates the domain against the catalog
            created = ProviderRegistry(
                domain=domain,
                valid_domains=frozenset(self._catalog),
                capability_vocabulary=spec.capability_vocabulary,
                catalog_provider_ids=spec.catalog_provider_ids,
                contract_provider_ids=spec.contract_provider_ids,
            )
            self._registries[domain] = created
            return created

    # -- discovery ---------------------------------------------------------

    def discover(self, domain: str) -> ProviderRegistry:
        """Scan `domain`'s provider folder once. Idempotent."""
        registry = self.registry(domain)
        if registry._discovered:
            return registry
        registry.discovery_scan(self.spec(domain).providers_base)
        return registry

    def discover_all(self) -> None:
        """Discover every catalog domain, in declaration order."""
        for domain in self.domains():
            self.discover(domain)

    def bind_runtimes(self, app, sock) -> None:
        """Bind the WebSocket runtime of every discovered `extension` provider.

        Runs after all domains are discovered so a runtime can rely on the full
        catalog being present (contracts.md §21.2 item 4). Selection is driven by
        the manifest, never by a provider id, and a failed bind is recorded on the
        provider rather than aborting startup.
        """
        if app is None or sock is None:
            return
        self._runtime_target = (app, sock)
        for domain in self.domains():
            for provider in self.registry(domain).list_providers():
                self._bind_runtime(provider, app, sock)

    def _bind_runtime(self, provider: ProviderInstance, app, sock) -> None:
        if provider.kind != RUNTIME_KIND:
            if provider.capabilities.get(RUNTIME_CAPABILITY):
                provider.add_warning(
                    f"declares {RUNTIME_CAPABILITY} but kind is {provider.kind!r}; "
                    "no runtime was bound"
                )
            return
        key = (provider.domain, provider.id)
        with self._lock:
            already_bound = key in self._runtime_bound
            self._runtime_bound.add(key)
        if already_bound:
            # Exactly once per process (step 11.5): `register_runtime()` claims a
            # WebSocket route, and a second claim on the same path is an error
            # rather than a no-op. The guard is keyed on `(domain, id)` because a
            # reload rebuilds the `ProviderInstance` objects.
            logger.debug("[providers] runtime for {}/{} already bound", *key)
            return
        runtime_module = provider.provider_module or provider.module
        binding = call_provider_runtime(provider.id, runtime_module, app, sock)
        if binding.error:
            provider.add_warning(binding.error)

    # -- lookup ------------------------------------------------------------

    def get(self, domain: str, provider_id: str) -> ProviderInstance | None:
        """Resolve one provider by canonical id, then by manifest alias (§19.3).

        Unknown domains return `None` rather than raising. Discovery is triggered
        on first lookup, so a caller that never went through application startup
        still sees the full catalog.
        """
        if domain not in self._catalog:
            return None
        return self.discover(domain).get(provider_id)

    def list(self, domain: str) -> list[ProviderInstance]:
        """List the providers registered for `domain` (empty for unknown domains)."""
        if domain not in self._catalog:
            return []
        return self.discover(domain).list_providers()

    def create(
        self,
        domain: str,
        provider_id: str,
        instance_id: str | None = None,
    ):
        """Construct — or return the memoized — provider object.

        Memoized per `(type, instance_id)` (step 3.1). When `instance_id` is
        omitted the default instance of the type is used (`instance_id ==
        provider_id`). Raises `ProviderConstructionError` when the provider
        cannot be built and returns `None` only when no such provider type is
        registered. The construction lock lives on the type package, so provider
        code never runs under the hub lock (contracts.md §21.1).
        """
        provider = self.get(domain, provider_id)
        if provider is None:
            return None
        return provider.create(instance_id=instance_id or provider_id)

    def catalog(
        self,
        selected: dict[str, str | None] | None = None,
        settings_for: Callable[[str, str], dict] | None = None,
    ) -> dict:
        """Serialize every domain for API responses.

        Args:
            selected: optional `domain -> selected_instance_id` mapping.
            settings_for: optional `(domain, provider_type_or_instance_id) -> dict`
                lookup used to compute availability. Defaults to the canonical
                settings store; pass an explicit callable to serialize against
                other settings.
        """
        selected = selected or {}
        if settings_for is None:
            from scriptase.providers import settings_manager

            # One read for the whole catalog, not one per provider.
            stored = settings_manager.load_settings().get("domains", {})

            def settings_for(domain: str, provider_id: str) -> dict:
                block = stored.get(domain) or {}
                instances = block.get("instances") or {}
                # Prefer the selected instance of this type, else the default
                # instance id (type id), else any stored instance of that type.
                selected_id = block.get("selected_instance_id")
                if (
                    isinstance(selected_id, str)
                    and selected_id in instances
                    and instances[selected_id].get("type") == provider_id
                ):
                    rec = instances[selected_id]
                    return dict(rec.get("settings") or {})
                if provider_id in instances:
                    rec = instances[provider_id]
                    return dict(rec.get("settings") or {})
                for rec in instances.values():
                    if isinstance(rec, dict) and rec.get("type") == provider_id:
                        return dict(rec.get("settings") or {})
                # Pre-migration / in-memory test blobs may still use per_provider.
                per_provider = block.get("per_provider") or {}
                return dict(per_provider.get(provider_id) or {})

        return {
            domain: self.discover(domain).to_dict(
                selected_provider=selected.get(domain),
                settings_for=lambda provider_id, d=domain: settings_for(d, provider_id),
            )
            for domain in self.domains()
        }

    # -- guarded reload (contracts.md §21.2 item 6) ------------------------

    def reload(self, domains: list[str] | None = None) -> ReloadReport:
        """Re-scan provider folders and swap in only fully valid catalogs.

        Each candidate snapshot is built privately and published only if it does
        not *regress*: a provider that is registered today must not come back
        excluded. An invalid edit therefore leaves the last good catalog serving
        requests, while adding or removing a provider folder still takes effect.
        """
        report = ReloadReport()
        for domain in domains or self.domains():
            registry = self.registry(domain)
            try:
                candidate = registry.build_snapshot(self.spec(domain).providers_base)
            except Exception as e:
                logger.error("[providers] {}: reload scan failed, keeping last good: {}", domain, e)
                report.retained[domain] = ["scan failed"]
                continue

            regressions = self._regressions(registry.snapshot, candidate)
            if regressions:
                logger.warning(
                    "[providers] {}: reload rejected, keeping last good catalog ({})",
                    domain, ", ".join(regressions),
                )
                report.retained[domain] = regressions
                continue

            registry._discovered = True
            dropped = registry.publish(candidate)
            self._rebind_new_runtimes(candidate)
            for provider in dropped:
                provider.retire()
            report.swapped.append(domain)
        return report

    @staticmethod
    def _regressions(live: CatalogSnapshot, candidate: CatalogSnapshot) -> list[str]:
        """Providers that are registered now but excluded in the candidate snapshot.

        Pre-existing exclusions do not block a swap — otherwise one permanently
        broken folder on disk would freeze the catalog forever.
        """
        excluded_now = {e.id for e in candidate.exclusions}
        return sorted(
            f"{provider_id} would be excluded"
            for provider_id in live.providers
            if provider_id in excluded_now
        )

    def _rebind_new_runtimes(self, snapshot: CatalogSnapshot) -> None:
        """Bind runtimes for providers that appeared after startup."""
        if self._runtime_target is None:
            return
        app, sock = self._runtime_target
        for provider in snapshot.providers.values():
            self._bind_runtime(provider, app, sock)

    # -- teardown ----------------------------------------------------------

    def shutdown(self) -> None:
        """Shut down every constructed provider, then clear every registry.

        Registry objects are kept and cleared in place, because the per-module
        `providers/__init__.py` facades hold references to them.
        """
        with self._lock:
            registries = list(self._registries.values())
            # A fresh process (or a test that rebuilds the app) must be able to
            # bind runtimes again after teardown.
            self._runtime_bound.clear()
            self._runtime_target = None
        for registry in registries:
            registry.shutdown_instances()
            registry.reset()


hub = ProviderHub()
_teardown_armed = False


def init_providers(app=None, sock=None) -> ProviderHub:
    """Application startup entry point: discover all domains, then bind runtimes.

    Also arms the process-exit teardown, so `shutdown()` is a live code path rather
    than the never-called hook it was before 11.2 (contracts.md §21.1).
    """
    global _teardown_armed
    if not _teardown_armed:
        atexit.register(hub.shutdown)
        _teardown_armed = True

    hub.discover_all()
    for domain in hub.domains():
        registry = hub.registry(domain)
        logger.info(
            "[providers] {}: {} registered, ids={}", domain, len(registry), registry.list_ids()
        )
        for exclusion in registry.excluded():
            logger.warning(
                "[providers] {}: excluded {} ({})",
                domain, exclusion["id"], exclusion["reason_code"],
            )
    hub.bind_runtimes(app, sock)
    return hub


@dataclass(frozen=True)
class DomainBinding:
    """The public surface of a `scriptase/modules/<module>/providers/__init__.py`.

    Unpacks in the historical order:
    `registry, discover, get_provider, list_providers, init_registry`.
    """

    registry: ProviderRegistry
    discover: Callable[[], ProviderRegistry]
    get_provider: Callable[[str], ProviderInstance | None]
    list_providers: Callable[[], list[ProviderInstance]]
    init_registry: Callable[..., ProviderRegistry]

    def __iter__(self):
        return iter(
            (
                self.registry,
                self.discover,
                self.get_provider,
                self.list_providers,
                self.init_registry,
            )
        )


def bind_domain(domain: str, discover_now: bool = True) -> DomainBinding:
    """Build the compatibility facade for one domain's provider package.

    Replaces the three structurally identical 57-line `providers/__init__.py`
    copies (contracts.md §14.6, §27).
    """
    registry = hub.registry(domain)

    def discover() -> ProviderRegistry:
        return hub.discover(domain)

    def get_provider(provider_id: str) -> ProviderInstance | None:
        return hub.get(domain, provider_id)

    def list_providers() -> list[ProviderInstance]:
        return hub.list(domain)

    def init_registry(app=None, sock=None) -> ProviderRegistry:
        discover()
        logger.info(
            "[providers] {}: {} registered, ids={}", domain, len(registry), registry.list_ids()
        )
        if app is not None and sock is not None:
            for provider in registry.list_providers():
                hub._bind_runtime(provider, app, sock)
        return registry

    if discover_now:
        discover()

    return DomainBinding(registry, discover, get_provider, list_providers, init_registry)


__all__ = [
    "ProviderHub",
    "ReloadReport",
    "hub",
    "init_providers",
    "DomainBinding",
    "bind_domain",
]
