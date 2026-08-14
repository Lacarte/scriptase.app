"""The provider platform — discovery, invocation, results, and its HTTP surface.

V2's `studio/shared/providers_common/` (the platform) and `studio/providers/`
(the one blueprint over it) merge here, per the Scriptase layout. `catalog` and
`routes` are transport and are *not* imported eagerly: importing this package
must not require Flask, and no module may reach business logic through a
`routes.py`. `providers_bp` is resolved lazily by `__getattr__` below purely so
`from scriptase.providers import providers_bp` keeps working.

Modules:
  - domains: the domain catalog — the single declaration of supported domains
  - settings_schema: provider settings schema validation, secrets, and visibility
  - settings_migrations: version-to-version migrations
  - settings_manager: canonical load/save/validate for settings.json
  - validation: manifest validation, exclusion reason codes, message sanitization
  - registry: provider discovery and domain-scoped registries
  - hub: process-wide hub resolving (domain, provider_id) across all domains
  - runtime: base class for extension provider runtimes
  - errors: ProviderError, the stable code catalog, and retryability
  - invocation: ProviderInvocation, cancellation, progress, redacted logging
  - results: the ProviderResult envelope, units, provenance, egress validation
  - jobs: the one asynchronous job contract shared by both visual domains
  - media_jobs: shared multi-unit async orchestration (submit/poll/push/retry/resume)
  - boundary: the single exception boundary and the deadline helpers
  - legacy: adapters from today's dict payloads onto the v2 envelope
  - http_client: retry/backoff wrapped requests
  - file_download: normalized file download to output dirs
  - progress: status.json writer for job progress
  - selection: capability selector and fallback-chain helpers (step 3.3)
  - transports: extension WebSocket hub, webhook, direct API, callback intake
"""

from scriptase.providers.domains import (
    DOMAINS,
    DOMAIN_ALIASES,
    DOMAIN_IDS,
    DomainSpec,
    canonical_domain,
    get_domain,
)
from scriptase.providers.settings_schema import (
    REDACTION_SENTINEL,
    SENSITIVE_KEYS_RE,
    WIDGET_TYPES,
    apply_settings_patch,
    invocation_config,
    is_secret_field,
    secret_keys,
    split_settings,
    validate_against_schema,
    visible_fields,
)
from scriptase.providers.settings_migrations import (
    SETTINGS_VERSION,
    apply_migrations,
)
from scriptase.providers.settings_manager import (
    load_settings,
    save_settings,
    get_domain_settings,
    get_provider_settings,
    set_provider_settings,
    set_selected_provider,
    get_instance_settings,
    set_instance_settings,
    set_selected_instance,
    get_selected_instance_id,
    list_instances,
    resolve_instance,
    upsert_instance,
    get_general_settings,
    set_general_settings,
    merge_provider_settings,
    portable_provider_settings,
    redact_settings,
    redacted_provider_settings,
    restore_redacted_secrets,
    validate_settings,
)
from scriptase.providers.validation import (
    EXCLUSION_REASON_CODES,
    ManifestValidation,
    sanitize_message,
    validate_manifest,
)
from scriptase.providers.registry import (
    CatalogSnapshot,
    ProviderConstructionError,
    ProviderExclusion,
    ProviderRegistry,
    ProviderManifest,
    ProviderInstance,
    HealthResult,
    ValidationIssue,
)
from scriptase.providers.runtime import (
    Runtime,
    RuntimeBinding,
    call_provider_runtime,
)
from scriptase.providers.errors import (
    PROVIDER_CODES,
    ProviderCancelled,
    ProviderError,
    ProviderErrorPayload,
    is_retryable,
    workflow_code,
)
from scriptase.providers.invocation import (
    CancellationToken,
    ProgressReporter,
    ProviderInvocation,
    ProviderLogger,
    build_invocation,
    domain_deadline,
)
from scriptase.providers.results import (
    Provenance,
    ProviderResult,
    UnitResult,
    coerce_result,
    derive_status,
    normalize_ref,
    resolve_ref,
    validate_egress,
)
from scriptase.providers.jobs import (
    JobHandle,
    JobRecord,
    JobStatus,
    poll_interval,
    terminal_outcome,
    unknown_job_status,
)
from scriptase.providers.media_jobs import (
    MediaJobService,
    MediaJobStore,
    default_store,
    record_path_for,
    result_from_status,
)
from scriptase.providers.boundary import (
    Deadline,
    invoke,
    wait_until,
    wrap_exception,
)
from scriptase.providers.concurrency import (
    EXCLUSIVE_EXECUTION,
    exclusive_execution,
    exclusive_lock,
    is_exclusive,
)
from scriptase.providers.selection import (
    RANK_CATALOG,
    RANK_FALLBACK_CHAIN,
    RANK_FALLBACK_PRIMARY,
    RANK_PREFERRED,
    RANK_SETTINGS,
    ProviderCandidate,
    fallback_policy_from_snapshot,
    has_capabilities,
    normalize_fallback_policy,
    ordered_fallback_ids,
    provider_default_from_snapshot,
    select_candidates,
    select_first,
)
from scriptase.providers.hub import (
    ProviderHub,
    DomainBinding,
    ReloadReport,
    bind_domain,
    hub,
    init_providers,
)
from scriptase.providers.http_client import (
    HttpClient,
    get_http_client,
    close_http_client,
)
from scriptase.providers.file_download import (
    download_file,
    download_to_output_dir,
)
from scriptase.providers.progress import (
    ProgressWriter,
    write_status_json,
)

def __getattr__(name: str):
    """Lazily expose the HTTP surface without importing Flask at package import."""
    if name == "providers_bp":
        from scriptase.providers.routes import providers_bp

        return providers_bp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DOMAINS",
    "DOMAIN_ALIASES",
    "DOMAIN_IDS",
    "canonical_domain",
    "providers_bp",
    "EXCLUSIVE_EXECUTION",
    "DomainSpec",
    "exclusive_execution",
    "exclusive_lock",
    "get_domain",
    "is_exclusive",
    "RANK_CATALOG",
    "RANK_FALLBACK_CHAIN",
    "RANK_FALLBACK_PRIMARY",
    "RANK_PREFERRED",
    "RANK_SETTINGS",
    "ProviderCandidate",
    "fallback_policy_from_snapshot",
    "has_capabilities",
    "normalize_fallback_policy",
    "ordered_fallback_ids",
    "provider_default_from_snapshot",
    "select_candidates",
    "select_first",
    "REDACTION_SENTINEL",
    "SENSITIVE_KEYS_RE",
    "WIDGET_TYPES",
    "apply_settings_patch",
    "invocation_config",
    "is_secret_field",
    "secret_keys",
    "split_settings",
    "validate_against_schema",
    "visible_fields",
    "SETTINGS_VERSION",
    "apply_migrations",
    "load_settings",
    "save_settings",
    "get_domain_settings",
    "get_provider_settings",
    "set_provider_settings",
    "set_selected_provider",
    "get_instance_settings",
    "set_instance_settings",
    "set_selected_instance",
    "get_selected_instance_id",
    "list_instances",
    "resolve_instance",
    "upsert_instance",
    "get_general_settings",
    "set_general_settings",
    "merge_provider_settings",
    "portable_provider_settings",
    "redact_settings",
    "redacted_provider_settings",
    "restore_redacted_secrets",
    "validate_settings",
    "EXCLUSION_REASON_CODES",
    "ManifestValidation",
    "sanitize_message",
    "validate_manifest",
    "CatalogSnapshot",
    "ProviderConstructionError",
    "ProviderExclusion",
    "ProviderRegistry",
    "ProviderManifest",
    "ProviderInstance",
    "HealthResult",
    "ValidationIssue",
    "Runtime",
    "RuntimeBinding",
    "call_provider_runtime",
    "PROVIDER_CODES",
    "ProviderCancelled",
    "ProviderError",
    "ProviderErrorPayload",
    "is_retryable",
    "workflow_code",
    "CancellationToken",
    "ProgressReporter",
    "ProviderInvocation",
    "ProviderLogger",
    "build_invocation",
    "domain_deadline",
    "Provenance",
    "ProviderResult",
    "UnitResult",
    "coerce_result",
    "derive_status",
    "normalize_ref",
    "resolve_ref",
    "validate_egress",
    "JobHandle",
    "JobRecord",
    "JobStatus",
    "poll_interval",
    "terminal_outcome",
    "unknown_job_status",
    "MediaJobService",
    "MediaJobStore",
    "default_store",
    "record_path_for",
    "result_from_status",
    "Deadline",
    "invoke",
    "wait_until",
    "wrap_exception",
    "ProviderHub",
    "DomainBinding",
    "ReloadReport",
    "bind_domain",
    "hub",
    "init_providers",
    "HttpClient",
    "get_http_client",
    "close_http_client",
    "download_file",
    "download_to_output_dir",
    "ProgressWriter",
    "write_status_json",
]
