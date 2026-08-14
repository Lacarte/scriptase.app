"""Provider Registry — domain-scoped discovery, validation, and lifecycle.

Discovery validates a whole provider package (`manifest.py`, optional `provider.py`
and `settings_schema.py`) into a private catalog snapshot and publishes it with one
atomic swap, so a request never observes a half-discovered catalog
(contracts.md §21.2 item 6). Every exclusion is local and recorded as data
(§21.4). Providers are constructed lazily through a memoized `create()` factory
and released through `shutdown()` in reverse construction order (§21.1).
"""

import importlib
import importlib.util
import itertools
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from scriptase.providers import settings_schema as schema_tools
from scriptase.providers import validation as v
from scriptase.providers.domains import DOMAIN_IDS


# Availability states (contracts.md §21.5). Cheap, synchronous, no network — the
# orthogonal axis to health, which may perform I/O. The fourth frozen state,
# `unavailable`, has no value here: a discovered-but-excluded provider is never a
# `ProviderInstance` at all, it is an entry in `excluded[]` (§21.4).
AVAILABLE = "available"
NEEDS_CONFIGURATION = "needs_configuration"
DEGRADED = "degraded"


@dataclass
class ProviderManifest:
    """Required manifest returned by every provider (contracts.md §20.1)."""
    id: str
    label: str
    domain: str
    kind: str
    version: str
    requires: list[str] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)
    open_url: str | None = None
    # v2 additions (§19.3). `aliases` retires the hand-written legacy tables;
    # `contract_version` 1 is the legacy ABC shape, 2 the 11.4 invocation contract.
    aliases: list[str] = field(default_factory=list)
    contract_version: int = 1
    # v2 metadata (§20.1, step 11.3). `description` and `docs_url` are browser-safe
    # UI hints; `environment` maps a settings key to the environment variable it
    # falls back to at read time and is *never* serialized (§22.6, §25).
    description: str | None = None
    docs_url: str | None = None
    environment: dict[str, str] = field(default_factory=dict)

    def public_dict(self) -> dict:
        """The manifest's public metadata representation (contracts.md §25).

        Round-trips through `validate_manifest`, and carries no callables, no
        module handles, no filesystem paths, and no environment-variable names.
        """
        return {
            "id": self.id,
            "label": self.label,
            "domain": self.domain,
            "kind": self.kind,
            "version": self.version,
            "contract_version": self.contract_version,
            "aliases": list(self.aliases),
            "requires": list(self.requires),
            "capabilities": dict(self.capabilities),
            "open_url": self.open_url,
            "docs_url": self.docs_url,
            "description": self.description,
        }


@dataclass
class HealthResult:
    """Result of a provider health check."""
    status: str
    latency_ms: float | None = None
    message: str | None = None
    details: dict | None = None


def _sanitize_health_details(details: Any) -> dict | None:
    """Scrub provider-authored health `details` before they leave the registry.

    Secrets are key-masked; every string value is path-stripped and size-capped
    so a hook cannot smuggle credentials or absolute paths into the API
    (contracts.md §21.5 / §36 L4, step 16.4).
    """
    if not isinstance(details, dict):
        return None
    cleaned = schema_tools.redact(details)
    return _sanitize_detail_strings(cleaned)


def _sanitize_detail_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_detail_strings(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize_detail_strings(child) for child in value]
    if isinstance(value, str):
        return v.sanitize_message(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    # Drop non-JSON values rather than leaking repr(object).
    return None


@dataclass
class ValidationIssue:
    """A validation issue with provider settings."""
    field: str
    severity: str
    message: str


@dataclass(frozen=True)
class ProviderExclusion:
    """One provider that discovery refused to register (contracts.md §21.4)."""

    id: str
    reason_code: str
    message: str

    def to_dict(self) -> dict:
        return {"id": self.id, "reason_code": self.reason_code, "message": self.message}


class ProviderConstructionError(RuntimeError):
    """`create()` could not produce a provider instance.

    11.4 folds this into the shared `ProviderError` boundary; until then it carries
    the same stable code so callers can already branch on it.
    """

    code = "PROVIDER_CREATE_FAILED"

    def __init__(self, domain: str, provider_id: str, message: str):
        super().__init__(f"{domain}/{provider_id}: {message}")
        self.domain = domain
        self.provider_id = provider_id
        self.message = message


_construction_counter = itertools.count()


class ProviderInstance:
    """A validated provider package plus its lifecycle state.

    Holds up to three modules loaded from the provider folder:
      - module: manifest.py (required, holds manifest() function)
      - provider_module: provider.py (optional, holds create/validate_settings/health_check)
      - schema_module: settings_schema.py (optional, holds settings_schema())
    """

    # Resolved in order: the v2 name first, then the legacy zero-argument factory
    # that the five shipped storyboard/animator providers still export (§21.1).
    FACTORY_NAMES = ("create", "get_provider")

    def __init__(
        self,
        provider_id: str,
        module: Any,
        manifest: ProviderManifest,
        provider_module: Any = None,
        schema_module: Any = None,
        warnings: list[str] | None = None,
    ):
        self.id = provider_id
        self.module = module
        self.provider_module = provider_module
        self.schema_module = schema_module
        self.manifest = manifest
        self.warnings: list[str] = list(warnings or [])
        self._settings_schema = None
        self._schema_loaded = False

        self._create_lock = threading.RLock()
        # Constructed provider objects keyed by configured instance id
        # (step 3.1: memoize per (type, instance_id)).
        self._instances: dict[str, Any] = {}
        self._create_errors: dict[str, str] = {}
        self._construction_seqs: dict[str, int] = {}
        # Legacy single-slot mirrors used by `constructed` / `create_error` when
        # only the default instance (instance_id == type id) has been built.
        self._instance: Any = None
        self._create_error: str | None = None
        self._construction_seq: int | None = None

        self._lease_state = threading.Condition(threading.Lock())
        self._leases = 0
        self._retired = False
        self._shutdown_done = False

    # -- metadata ----------------------------------------------------------

    def _resolve(self, attr_name: str) -> Any:
        """Find a callable named `attr_name` across the loaded modules.

        Precedence: provider_module > schema_module > module (manifest).
        """
        for mod in (self.provider_module, self.schema_module, self.module):
            if mod is not None and hasattr(mod, attr_name):
                return getattr(mod, attr_name)
        return None

    @property
    def label(self) -> str:
        return self.manifest.label

    @property
    def domain(self) -> str:
        return self.manifest.domain

    @property
    def kind(self) -> str:
        return self.manifest.kind

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def contract_version(self) -> int:
        return self.manifest.contract_version

    @property
    def aliases(self) -> list[str]:
        return list(self.manifest.aliases)

    @property
    def capabilities(self) -> dict[str, bool]:
        return self.manifest.capabilities

    @property
    def requires(self) -> list[str]:
        return self.manifest.requires

    @property
    def schema_failed(self) -> bool:
        """True when a `settings_schema.py` is present but produced no schema."""
        return self.schema_module is not None and self.settings_schema() is None

    def add_warning(self, message: str) -> None:
        """Record a browser-safe warning, de-duplicated (contracts.md §25)."""
        safe = v.sanitize_message(message)
        if safe and safe not in self.warnings:
            self.warnings.append(safe)

    def settings_schema(self) -> dict | None:
        """Lazy-load and memoize the settings schema (contracts.md §21.1)."""
        if not self._schema_loaded:
            self._schema_loaded = True
            fn = self._resolve('settings_schema')
            if fn is not None:
                try:
                    self._settings_schema = fn()
                except Exception as e:
                    logger.warning("[registry] Failed to get settings_schema for {}: {}", self.id, e)
                    self.add_warning(f"settings_schema() failed: {e}")
                    self._settings_schema = None
        return self._settings_schema

    # -- settings (contracts.md §22) ---------------------------------------

    def resolve_settings(self, settings: dict | None) -> dict:
        """Apply the manifest's environment fallbacks for provider-internal use.

        `settings[key] or os.environ[manifest.environment[key]]` (§22.6). The
        resolved value is never written back to `settings.json` and never
        returned to a caller that serializes it — only provider validation,
        health, and invocation see it.
        """
        resolved = dict(settings or {})
        for key, env_name in self.manifest.environment.items():
            if not schema_tools.is_empty(resolved.get(key)):
                continue
            from_env = os.environ.get(env_name)
            if from_env:
                resolved[key] = from_env
        return resolved

    def is_configured(self, settings: dict | None = None) -> bool:
        """Every `requires` key is non-empty after env fallback (§21.5).

        Computed from `requires`, never from key presence: the live settings file
        stores present-but-empty `api_key` values (§14.3).
        """
        resolved = self.resolve_settings(settings)
        return all(
            not schema_tools.is_empty(resolved.get(key)) for key in self.requires
        )

    def availability(
        self,
        settings: dict | None = None,
        *,
        instance_id: str | None = None,
    ) -> str:
        """Cheap, synchronous availability state (contracts.md §21.5).

        Availability is a pure function of the passed-in settings dict, so two
        configured instances of this type can disagree. Construction failure is
        tracked per instance id (step 3.1).
        """
        key = instance_id or self.id
        if self.create_callable is None or key in self._create_errors:
            return DEGRADED
        if self.schema_failed:
            return DEGRADED
        if not self.is_configured(settings):
            return NEEDS_CONFIGURATION
        return AVAILABLE

    def validate_settings(self, settings: dict | None) -> list[ValidationIssue]:
        """Validate settings against the schema, then through the provider hook.

        Never cached — the settings differ per call. Schema validation is the
        server-side half the provider cannot skip; the hook adds whatever the
        provider knows that the schema cannot express.
        """
        resolved = self.resolve_settings(settings)
        issues = [
            ValidationIssue(**issue)
            for issue in schema_tools.validate_against_schema(
                self.settings_schema(), resolved
            )
        ]

        fn = self._resolve('validate_settings')
        if fn is None:
            return issues

        try:
            raw_issues = fn(resolved)
        except Exception as e:
            # Never `str(e)`: a provider exception can contain a submitted secret
            # (§22.5). The raw exception goes only to the redacted logger.
            logger.warning("[registry] validate_settings failed for {}: {}", self.id, e)
            issues.append(ValidationIssue(
                field='root', severity='error', message='Settings validation failed'
            ))
            return issues

        seen = {(i.field, i.severity, i.message) for i in issues}
        for raw in raw_issues or []:
            issue = (
                ValidationIssue(
                    field=raw.get('field', ''),
                    severity=raw.get('severity', 'warning'),
                    message=raw.get('message', ''),
                )
                if isinstance(raw, dict)
                else raw
            )
            key = (issue.field, issue.severity, issue.message)
            if key not in seen:
                seen.add(key)
                issues.append(issue)
        return issues

    def health_check(self, settings: dict | None) -> HealthResult:
        """Check provider health. May perform I/O; runs on explicit user action."""
        fn = self._resolve('health_check')
        if fn is None:
            # A provider with no hook is `unknown`, not `ok` (§21.5, frozen
            # correction): claiming health it never reported is a lie.
            return HealthResult(status='unknown', message='No health check implemented')
        try:
            result = fn(self.resolve_settings(settings))
        except Exception as e:
            logger.warning("[registry] health_check failed for {}: {}", self.id, e)
            return HealthResult(status='fail', message=v.sanitize_message(e))
        if isinstance(result, dict):
            message = result.get('message')
            return HealthResult(
                status=result.get('status', 'unknown'),
                latency_ms=result.get('latency_ms'),
                # A *returned* message is as untrusted as a raised one: several
                # shipped hooks answer `{"status": "fail", "message": str(e)}`,
                # which can carry a URL, a path, or a response body (§36 L4).
                message=v.sanitize_message(message) if message else message,
                details=_sanitize_health_details(result.get('details')),
            )
        if isinstance(result, str):
            return HealthResult(status=result)
        if isinstance(result, HealthResult):
            return HealthResult(
                status=result.status,
                latency_ms=result.latency_ms,
                message=v.sanitize_message(result.message) if result.message else result.message,
                details=_sanitize_health_details(result.details),
            )
        return result

    # -- construction (contracts.md §21.1) ---------------------------------

    @property
    def create_callable(self) -> Any:
        """The zero-argument factory, or `None` when the provider cannot be built."""
        for name in self.FACTORY_NAMES:
            fn = self._resolve(name)
            if callable(fn):
                return fn
        return None

    @property
    def constructed(self) -> bool:
        return bool(self._instances) or self._instance is not None

    @property
    def create_error(self) -> str | None:
        if self._create_error is not None:
            return self._create_error
        return self._create_errors.get(self.id)

    @property
    def construction_seq(self) -> int | None:
        """Monotonic construction order, used to shut down in reverse."""
        if self._construction_seq is not None:
            return self._construction_seq
        if not self._construction_seqs:
            return None
        return min(self._construction_seqs.values())

    def create(self, instance_id: str | None = None) -> Any:
        """Construct the provider at most once per configured instance id.

        Memoized per `(type, instance_id)` (step 3.1). When `instance_id` is
        omitted the default instance of this type is used (`instance_id ==
        type id`). Never called at import time or during discovery, and never
        while the registry lock is held: the lock taken here belongs to this
        type package alone.
        """
        key = instance_id or self.id
        existing = self._instances.get(key)
        if existing is not None:
            return existing
        with self._create_lock:
            existing = self._instances.get(key)
            if existing is not None:
                return existing
            if self._retired:
                raise ProviderConstructionError(self.domain, self.id, "provider was retired")
            prior_error = self._create_errors.get(key)
            if prior_error is not None:
                raise ProviderConstructionError(self.domain, self.id, prior_error)
            factory = self.create_callable
            if factory is None:
                message = "no create() factory found in the provider package"
                self._create_errors[key] = message
                if key == self.id:
                    self._create_error = message
                self.add_warning(message)
                raise ProviderConstructionError(self.domain, self.id, message)
            try:
                built = factory()
            except Exception as e:
                message = v.sanitize_message(f"create() raised: {e}")
                self._create_errors[key] = message
                if key == self.id:
                    self._create_error = message
                self.add_warning(message)
                logger.error(
                    "[registry] create() failed for {}/{} instance={}: {}",
                    self.domain, self.id, key, e,
                )
                raise ProviderConstructionError(self.domain, self.id, message) from None
            if built is None:
                message = "create() returned None"
                self._create_errors[key] = message
                if key == self.id:
                    self._create_error = message
                self.add_warning(message)
                raise ProviderConstructionError(self.domain, self.id, message)
            seq = next(_construction_counter)
            self._instances[key] = built
            self._construction_seqs[key] = seq
            # Keep the legacy single-slot mirrors coherent for the default instance.
            if key == self.id:
                self._instance = built
                self._construction_seq = seq
            logger.info(
                "[registry] Constructed provider '{}' instance '{}' in {}",
                self.id, key, self.domain,
            )
            return built

    # -- invocation leases (contracts.md §21.2 item 6) ---------------------

    @contextmanager
    def lease(self):
        """Hold the provider open for one invocation.

        A snapshot swap may drop this provider while a request is still using it;
        `retire()` waits for outstanding leases before calling `shutdown()`.
        """
        with self._lease_state:
            if self._retired:
                raise ProviderConstructionError(self.domain, self.id, "provider was retired")
            self._leases += 1
        try:
            yield self
        finally:
            with self._lease_state:
                self._leases -= 1
                if self._leases <= 0:
                    self._lease_state.notify_all()

    @property
    def active_leases(self) -> int:
        with self._lease_state:
            return self._leases

    def retire(self, timeout: float = 5.0) -> None:
        """Stop new leases, wait for in-flight ones, then shut down."""
        with self._lease_state:
            self._retired = True
            if self._leases > 0:
                drained = self._lease_state.wait_for(lambda: self._leases <= 0, timeout=timeout)
                if not drained:
                    logger.warning(
                        "[registry] {}/{}: {} lease(s) still active after {}s; shutting down anyway",
                        self.domain, self.id, self._leases, timeout,
                    )
        self.shutdown()

    def shutdown(self) -> None:
        """Release every constructed instance. Best-effort and idempotent (§21.1)."""
        with self._create_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
            built = list(self._instances.items())
            if not built and self._instance is not None:
                built = [(self.id, self._instance)]
            self._instances = {}
            self._instance = None
            self._construction_seqs = {}
            self._construction_seq = None
        for key, instance in built:
            hook = getattr(instance, "shutdown", None)
            if not callable(hook):
                continue
            try:
                hook()
                logger.debug(
                    "[registry] Shut down provider '{}' instance '{}' in {}",
                    self.id, key, self.domain,
                )
            except Exception as e:
                # Never raised: one provider's teardown may not abort the rest (§21.1).
                self.add_warning(f"shutdown() failed: {e}")
                logger.error(
                    "[registry] shutdown() failed for {}/{} instance={}: {}",
                    self.domain, self.id, key, e,
                )

    # -- serialization (contracts.md §25) ----------------------------------

    def to_dict(
        self,
        settings: dict | None = None,
        *,
        instance_id: str | None = None,
    ) -> dict:
        """Browser-safe projection (contracts.md §25).

        Never exposes modules, paths, settings values, or the manifest's internal
        `environment` map. `settings` is read only to compute `availability` and
        is never echoed back. `instance_id` scopes the availability computation
        to one configured binding of this type (step 3.1).
        """
        payload = self.manifest.public_dict()
        # `provider_type` is the discovered package id; `id` remains for
        # pre-3.1 clients. They are equal for a type catalog entry.
        payload["provider_type"] = self.id
        payload.update({
            'has_settings': self.settings_schema() is not None,
            'availability': self.availability(settings, instance_id=instance_id),
            'warnings': list(self.warnings),
        })
        if instance_id:
            payload["instance_id"] = instance_id
        return payload


@dataclass(frozen=True)
class CatalogSnapshot:
    """An immutable, fully validated view of one domain's providers.

    Published by a single attribute assignment so readers see either the complete
    old catalog or the complete new one (contracts.md §21.2 item 6).
    """

    providers: dict[str, ProviderInstance] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    exclusions: tuple[ProviderExclusion, ...] = ()

    def resolve(self, provider_id: str) -> ProviderInstance | None:
        """Exact id first, then alias — a real id always wins (contracts.md §19.3)."""
        found = self.providers.get(provider_id)
        if found is not None:
            return found
        canonical = self.aliases.get(provider_id)
        return self.providers.get(canonical) if canonical else None


EMPTY_SNAPSHOT = CatalogSnapshot()


class _CatalogBuilder:
    """Accumulates a private snapshot during discovery; nothing is visible yet."""

    def __init__(self, domain: str):
        self.domain = domain
        self.providers: dict[str, ProviderInstance] = {}
        self.exclusions: list[ProviderExclusion] = []

    def exclude(self, provider_id: str, reason_code: str, message: str) -> None:
        safe = v.sanitize_message(message)
        self.exclusions.append(ProviderExclusion(provider_id, reason_code, safe))
        logger.warning("[registry] [EXCLUDED] {} ({}): {}", provider_id, reason_code, safe)

    def add(self, instance: ProviderInstance) -> bool:
        if instance.domain != self.domain:
            self.exclude(
                instance.id,
                v.MANIFEST_DOMAIN_MISMATCH,
                f"declares domain {instance.domain!r}, registered under {self.domain!r}",
            )
            return False
        if instance.id in self.providers:
            # First registration wins; the later one never replaces the incumbent.
            self.exclude(
                instance.id, v.DUPLICATE_ID, f"id already registered in domain {self.domain!r}"
            )
            return False
        self.providers[instance.id] = instance
        logger.info(
            "[registry] Registered provider '{}' ({}) in {}",
            instance.id, instance.label, self.domain,
        )
        return True

    def build(self) -> CatalogSnapshot:
        """Resolve aliases last, so a real id always beats an alias (§19.3)."""
        aliases: dict[str, str] = {}
        for provider in self.providers.values():
            for alias in provider.aliases:
                if alias in self.providers:
                    provider.add_warning(f"alias dropped (collides with provider id): {alias}")
                    continue
                incumbent = aliases.get(alias)
                if incumbent is not None:
                    # Both sides are warned; neither provider is excluded (§19.3).
                    provider.add_warning(f"alias dropped (claimed by '{incumbent}'): {alias}")
                    self.providers[incumbent].add_warning(
                        f"alias also claimed by '{provider.id}': {alias}"
                    )
                    continue
                aliases[alias] = provider.id
        return CatalogSnapshot(
            providers=dict(self.providers),
            aliases=aliases,
            exclusions=tuple(self.exclusions),
        )


class ProviderRegistry:
    """Domain-scoped provider registry with discovery."""

    # Derived from the domain catalog — never write a domain name here (§19.1).
    VALID_DOMAINS = DOMAIN_IDS

    def __init__(
        self,
        domain: str,
        valid_domains: frozenset[str] | None = None,
        capability_vocabulary: frozenset[str] | None = None,
    ):
        allowed = self.VALID_DOMAINS if valid_domains is None else valid_domains
        if domain not in allowed:
            raise ValueError(f"Invalid domain: {domain}. Must be one of {sorted(allowed)}")
        self.domain = domain
        self.capability_vocabulary = capability_vocabulary
        self._snapshot: CatalogSnapshot = EMPTY_SNAPSHOT
        self._lock = threading.RLock()
        self._discovered = False

    # -- reads (lock-free: one attribute read of an immutable snapshot) ----

    @property
    def snapshot(self) -> CatalogSnapshot:
        return self._snapshot

    def get(self, provider_id: str) -> ProviderInstance | None:
        """Get a provider by canonical id, then by alias."""
        return self._snapshot.resolve(provider_id)

    def list_providers(self) -> list[ProviderInstance]:
        """List all registered providers."""
        return list(self._snapshot.providers.values())

    def list_ids(self) -> list[str]:
        """List all provider IDs."""
        return list(self._snapshot.providers)

    def excluded(self) -> list[dict]:
        """Providers discovery refused, as data rather than only a log line (§21.4)."""
        return [e.to_dict() for e in self._snapshot.exclusions]

    def aliases(self) -> dict[str, str]:
        """`alias -> canonical id` for this domain."""
        return dict(self._snapshot.aliases)

    def __len__(self) -> int:
        return len(self._snapshot.providers)

    # -- writes ------------------------------------------------------------

    def publish(self, snapshot: CatalogSnapshot) -> list[ProviderInstance]:
        """Swap in a new snapshot atomically; return the providers it dropped."""
        with self._lock:
            previous = self._snapshot
            self._snapshot = snapshot
        return [
            provider
            for provider_id, provider in previous.providers.items()
            if snapshot.providers.get(provider_id) is not provider
        ]

    def register(
        self,
        provider_id: str,
        module: Any,
        manifest: ProviderManifest,
        provider_module: Any = None,
        schema_module: Any = None,
    ) -> None:
        """Register one provider outside of a discovery scan (copy-on-write)."""
        with self._lock:
            builder = _CatalogBuilder(self.domain)
            builder.providers.update(self._snapshot.providers)
            builder.exclusions.extend(self._snapshot.exclusions)
            builder.add(ProviderInstance(
                provider_id, module, manifest,
                provider_module=provider_module,
                schema_module=schema_module,
            ))
            self._snapshot = builder.build()

    def reset(self) -> None:
        """Drop every registration so the next discovery re-scans from disk.

        Clears in place: the per-module compatibility facades hold this object.
        """
        with self._lock:
            dropped = self.publish(EMPTY_SNAPSHOT)
            self._discovered = False
        for provider in dropped:
            provider.retire()

    def shutdown_instances(self) -> None:
        """Shut down every constructed provider in reverse construction order (§21.1)."""
        constructed = [p for p in self.list_providers() if p.construction_seq is not None]
        for provider in sorted(constructed, key=lambda p: p.construction_seq, reverse=True):
            provider.shutdown()

    # -- discovery ---------------------------------------------------------

    def discovery_scan(self, providers_base: str) -> None:
        """Scan provider folders and publish the result as one atomic swap."""
        # Marked before the scan, not after: a provider module that imports its own
        # package (e.g. `from scriptase.modules.tts.providers.base import ...`) re-enters
        # discovery, and the second scan would re-register every provider.
        self._discovered = True
        dropped = self.publish(self.build_snapshot(providers_base))
        for provider in dropped:
            provider.retire()

    def build_snapshot(self, providers_base: str) -> CatalogSnapshot:
        """Scan `providers_base` into a private snapshot without publishing it."""
        builder = _CatalogBuilder(self.domain)

        if not os.path.isdir(providers_base):
            logger.debug("[registry] Provider base not found: {}", providers_base)
            return builder.build()

        # sorted() so discovery logs, catalog responses, and "first wins" duplicate
        # resolution are deterministic (contracts.md §21.2 item 2).
        for entry in sorted(os.listdir(providers_base)):
            provider_path = os.path.join(providers_base, entry)
            if not os.path.isdir(provider_path):
                continue
            if entry.startswith('_') or entry.startswith('.'):
                continue

            manifest_file = os.path.join(provider_path, 'manifest.py')
            if not os.path.isfile(manifest_file):
                logger.debug("[registry] No manifest.py in {}, skipping", entry)
                continue

            instance = self._load_provider(builder, entry, provider_path, manifest_file)
            if instance is not None:
                builder.add(instance)

        return builder.build()

    def _load_module_from_file(self, file_path: str, module_name: str) -> Any:
        """Load a Python module from a file path. Returns module or None on failure."""
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.warning("[registry] Failed to load {}: {}", file_path, e)
            return None

    def _load_provider(
        self,
        builder: _CatalogBuilder,
        provider_id: str,
        provider_path: str,
        manifest_file: str,
    ) -> ProviderInstance | None:
        """Validate one provider package.

        Records an exclusion and returns `None` on failure; the caller adds the
        instance to the private snapshot on success.
        """
        module_prefix = f"_sts_provider_{self.domain}_{provider_id}"

        try:
            spec = importlib.util.spec_from_file_location(
                f"{module_prefix}_manifest", manifest_file
            )
            if spec is None or spec.loader is None:
                builder.exclude(
                    provider_id, v.MANIFEST_LOAD_FAILED, "could not load manifest.py (spec failed)"
                )
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            builder.exclude(
                provider_id, v.MANIFEST_LOAD_FAILED, f"{type(e).__name__} in manifest.py: {e}"
            )
            return None

        manifest_fn = getattr(module, 'manifest', None)
        if not callable(manifest_fn):
            builder.exclude(provider_id, v.MANIFEST_MISSING, "manifest() function not found")
            return None

        try:
            payload = manifest_fn()
        except Exception as e:
            builder.exclude(provider_id, v.MANIFEST_RAISED, f"manifest() raised: {e}")
            return None

        result = v.validate_manifest(
            folder_id=provider_id,
            domain=self.domain,
            payload=payload,
            manifest_cls=ProviderManifest,
            capability_vocabulary=self.capability_vocabulary,
        )
        if not result.ok:
            builder.exclude(provider_id, result.reason_code, result.message)
            return None

        instance = ProviderInstance(
            provider_id, module, result.manifest, warnings=result.warnings
        )

        provider_file = os.path.join(provider_path, 'provider.py')
        if os.path.isfile(provider_file):
            provider_module = self._load_module_from_file(
                provider_file, f"{module_prefix}_provider"
            )
            if provider_module is None:
                # Not fatal on its own: callables may live in manifest.py and
                # `_resolve` falls back across modules (§21.4 partial degradation).
                instance.add_warning("provider.py failed to load")
            instance.provider_module = provider_module

        schema_file = os.path.join(provider_path, 'settings_schema.py')
        if os.path.isfile(schema_file):
            schema_module = self._load_module_from_file(
                schema_file, f"{module_prefix}_schema"
            )
            if schema_module is None:
                instance.add_warning("settings_schema.py failed to load")
            instance.schema_module = schema_module

        if instance.create_callable is None:
            instance.add_warning("no create() factory found in the provider package")

        return instance

    def to_dict(
        self,
        selected_provider: str | None = None,
        settings_for: Any = None,
    ) -> dict:
        """Serialize registry state for API response (contracts.md §25).

        `settings_for` is an optional `(provider_id) -> dict` lookup used only to
        compute each provider's availability. Injected rather than imported so the
        registry stays independent of the settings store.
        """
        return {
            'domain': self.domain,
            'providers': [
                p.to_dict(settings_for(p.id) if settings_for is not None else None)
                for p in self.list_providers()
            ],
            'selected': selected_provider,
            'count': len(self),
            'excluded': self.excluded(),
        }
