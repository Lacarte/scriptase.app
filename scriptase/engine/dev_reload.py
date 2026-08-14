"""Opt-in hot reload for workflow node definitions, adapters, and provider packages.

This module is dormant unless STS_WORKFLOW_DEV_RELOAD is truthy. It watches only
developer-kit files — workflow node definitions and adapters, plus the
`manifest.py` / `provider.py` / `settings_schema.py` of every provider folder named
by the domain catalog. Flask itself and unrelated application modules are never
watched. Provider changes go through `hub.reload()`, which keeps the last good
catalog when an edit is invalid (step 11.2).
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Event, Lock, Thread

from loguru import logger

from .options import invalidate_discovery_cache


DEV_RELOAD_ENV = "STS_WORKFLOW_DEV_RELOAD"
_TRUTHY = {"1", "true", "yes", "on"}


def dev_reload_enabled(environ=None):
    values = os.environ if environ is None else environ
    return values.get(DEV_RELOAD_ENV, "").strip().lower() in _TRUTHY


class WorkflowDevReloader:
    """Poll developer-kit sources and publish successful reload signals."""

    def __init__(self, root=None, *, interval=0.5, enabled=None):
        self.root = Path(root or Path(__file__).resolve().parent)
        self.interval = interval
        self.enabled = dev_reload_enabled() if enabled is None else bool(enabled)
        self._snapshot = {}
        self._subscribers = set()
        self._subscriber_lock = Lock()
        self._reload_lock = Lock()
        self._stop = Event()
        self._thread = None
        self.generation = 0

    def watched_files(self):
        yield self.root / "registry.py"
        yield from sorted((self.root / "node_definitions").glob("*.json"))
        yield from sorted((self.root / "adapters").rglob("*.py"))
        yield from self.watched_provider_files()

    def watched_provider_files(self):
        """Provider package sources, from the domain catalog rather than a list."""
        from scriptase.providers.domains import DOMAINS

        for spec in DOMAINS.values():
            base = Path(spec.providers_base)
            for name in ("manifest.py", "provider.py", "settings_schema.py"):
                yield from sorted(base.glob(f"*/{name}"))

    def _provider_roots(self):
        from scriptase.providers.domains import DOMAINS

        return {Path(spec.providers_base).resolve(): spec.id for spec in DOMAINS.values()}

    def snapshot(self):
        result = {}
        for path in self.watched_files():
            try:
                stat = path.stat()
                result[path.resolve()] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
        return result

    def start(self):
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return False
        self._snapshot = self.snapshot()
        self._stop.clear()
        self._thread = Thread(target=self._run, name="workflow-dev-reload", daemon=True)
        self._thread.start()
        logger.info("Workflow node hot reload enabled")
        return True

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.interval * 3))

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def scan_once(self):
        """Reload one observed change batch; useful for deterministic tests."""
        if not self.enabled:
            return False
        current = self.snapshot()
        changed = sorted(
            set(current).symmetric_difference(self._snapshot)
            | {path for path in set(current) & set(self._snapshot) if current[path] != self._snapshot[path]}
        )
        if not changed:
            return False
        # Record the observation even on failure. A subsequent save produces a
        # new signature and retries, without logging the same invalid edit on
        # every poll.
        self._snapshot = current
        try:
            self._reload(changed)
        except Exception:
            logger.exception("Workflow developer hot reload failed")
            return False
        self.generation += 1
        self._publish({"generation": self.generation, "files": [path.name for path in changed]})
        logger.success("Workflow node catalog hot-reloaded (generation {})", self.generation)
        return True

    def subscribe(self):
        channel = Queue(maxsize=8)
        with self._subscriber_lock:
            self._subscribers.add(channel)
        return channel

    def unsubscribe(self, channel):
        with self._subscriber_lock:
            self._subscribers.discard(channel)

    def _publish(self, event):
        with self._subscriber_lock:
            channels = list(self._subscribers)
        for channel in channels:
            try:
                channel.put_nowait(event)
            except Exception:
                # A slow browser needs only the newest signal; its refetch is
                # a full registry replacement rather than a delta.
                try:
                    channel.get_nowait()
                    channel.put_nowait(event)
                except Exception:
                    pass

    def _reload(self, changed):
        with self._reload_lock:
            import scriptase.engine.registry as registry

            # Timestamp-based .pyc validation has one-second granularity on
            # some Python/filesystem combinations. Remove only the cache for
            # an observed source edit so a same-size rapid save cannot reload
            # stale bytecode.
            for path in changed:
                if path.suffix != ".py" or not path.exists():
                    continue
                try:
                    Path(importlib.util.cache_from_source(str(path))).unlink(missing_ok=True)
                except (NotImplementedError, OSError):
                    pass

            registry_changed = any(
                path.name == "registry.py" or path.suffix == ".json" for path in changed
            )
            if any(path.name == "registry.py" for path in changed):
                registry = importlib.reload(registry)
            elif registry_changed:
                registry.reload_generated_node_types(self.root / "node_definitions")

            importlib.invalidate_caches()
            adapters_root = (self.root / "adapters").resolve()
            for path in changed:
                try:
                    relative = path.resolve().relative_to(adapters_root)
                except ValueError:
                    continue
                if path.suffix != ".py" or path.name == "__init__.py":
                    continue
                module_name = "scriptase.engine.adapters." + ".".join(relative.with_suffix("").parts)
                module = sys.modules.get(module_name)
                if module is not None:
                    importlib.reload(module)

            self._reload_providers(changed)

    def _reload_providers(self, changed):
        """Re-scan the domains whose provider sources changed.

        The hub publishes a candidate catalog only when it is fully valid, so an
        invalid edit leaves the last good catalog serving requests.
        """
        roots = self._provider_roots()
        domains = []
        for path in changed:
            resolved = path.resolve()
            for root, domain in roots.items():
                if root in resolved.parents and domain not in domains:
                    domains.append(domain)
        if not domains:
            return

        from scriptase.providers.hub import hub

        report = hub.reload(domains)
        for domain, reasons in report.retained.items():
            logger.warning(
                "Provider catalog for {} kept at its last good version: {}",
                domain, ", ".join(reasons),
            )
        if report.swapped:
            # A `cache="discovery"` option source now answers with a different
            # provider list (§23.4); keeping the old answer would hide the
            # provider the developer just added.
            invalidate_discovery_cache()
            logger.success("Provider catalog hot-reloaded for {}", ", ".join(report.swapped))

    def _run(self):
        while not self._stop.wait(self.interval):
            self.scan_once()


_reloader = WorkflowDevReloader()


def start_dev_reloader():
    return _reloader.start()


def dev_reloader():
    return _reloader


def next_reload_event(channel, timeout=15):
    try:
        return channel.get(timeout=timeout)
    except Empty:
        return None
