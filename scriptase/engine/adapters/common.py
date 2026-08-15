from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from config import OUTPUT_DIR

PROJECT_ID_RE = re.compile(r"^p[pm]_[A-Za-z0-9]{6}$")
CONTROL = {"ok": True}


class AdapterError(RuntimeError):
    """Structured node failure consumed by the workflow scheduler."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class AdapterContext:
    project_id: str
    execution_id: str = ""
    node_id: str = ""
    progress: Callable[[str], None] | None = None
    stop_requested: Callable[[], bool] | None = None
    authorize_existing_replace: bool = False
    # Adapters which create a new artifact may ask the scheduler for a path
    # that is invisible to readers until the node succeeds.  Existing
    # adapters remain compatible while they are migrated to staged writes.
    stage_artifact: Callable[[str], str] | None = None
    # Flat channel defaults from Job orchestration (extensions.channel_settings).
    # project.setup reads these at runtime; other adapters keep using the
    # settings port. Never carries credentials.
    channel_settings: Mapping[str, Any] | None = None
    # The owning Job (extensions.job_id, stamped by prepare_workflow_for_job).
    # Empty for a canvas run that no Job started. `project_id` is not a
    # substitute: ReviewIssues and Jobs are keyed by this id, so writing a
    # project id here would persist findings no Job could ever find.
    job_id: str = ""


def context_value(context: AdapterContext | Mapping[str, Any], name: str, default=None):
    if isinstance(context, Mapping):
        return context.get(name, default)
    return getattr(context, name, default)


def project_id(context, inputs: Mapping[str, Any] | None = None) -> str:
    value = context_value(context, "project_id", "")
    if not value and inputs:
        candidate = inputs.get("project_id")
        value = candidate.get("project_id") if isinstance(candidate, Mapping) else candidate
    if not isinstance(value, str) or not PROJECT_ID_RE.fullmatch(value):
        raise AdapterError("PROJECT_ID_INVALID", "A strict pp_/pm_ project ID is required")
    return value


def inherited_config(config: Mapping[str, Any] | None, settings: Any, aliases=None) -> dict:
    """Apply incoming settings as defaults; explicit node configuration wins.

    Verified live (step 6.1): schema defaults are empty strings, so an unset
    node field must not mask a configured project setting — empty is not
    explicit. A config value only overrides a non-empty inherited value when
    it is itself non-empty.
    """
    inherited = dict(settings) if isinstance(settings, Mapping) else {}
    aliases = aliases or {}
    for source, target in aliases.items():
        if source in inherited and target not in inherited:
            inherited[target] = inherited[source]
    for key, value in dict(config or {}).items():
        if value in (None, "") and inherited.get(key) not in (None, ""):
            continue
        inherited[key] = value
    return inherited


def provider_id(domain: str, config: Mapping[str, Any] | None) -> str:
    """The provider instance this node runs on: its saved `provider_id`, else default.

    After step 3.2 the saved value is an **instance** id (equal to the type id
    for the default binding). The fallback is deliberately a *read*, never a
    write (contracts.md §41.3 M4): `setdefault` would change the fingerprinted
    configuration and invalidate the cache the fallback exists to preserve. It
    is what keeps a `story.generate` or `scenes.blueprint` saved before step
    12.3 running the same service it always did.
    """
    from scriptase.providers.domains import DOMAINS

    value = (config or {}).get("provider_id")
    if isinstance(value, str) and value:
        return value
    return DOMAINS[domain].default_provider


def resolve_fallback_chain_for_context(
    domain: str,
    primary_instance_id: str,
    context: Any = None,
    config: Mapping[str, Any] | None = None,
    *,
    stage: str | None = None,
) -> list[str]:
    """Ordered instance chain for step 8.3 fallback execution.

    Prefers an explicit ``fallback_policy`` on node config, then the Job's
    channel settings blob (``fallback_policies[stage]``), then a bare primary.
    """
    from scriptase.providers.fallback import resolve_execution_chain

    policy = None
    if isinstance(config, Mapping):
        raw = config.get("fallback_policy")
        if raw is not None:
            policy = raw

    channel_settings: Mapping[str, Any] | None = None
    try:
        from scriptase.jobs.channel_settings import resolve_channel_settings

        channel_settings = resolve_channel_settings(context)
    except Exception:
        channel_settings = None
    if not channel_settings and isinstance(config, Mapping):
        nested = config.get("fallback_policies")
        if isinstance(nested, Mapping):
            channel_settings = {"fallback_policies": nested}

    return resolve_execution_chain(
        domain,
        primary_instance_id=primary_instance_id,
        fallback_policy=policy,
        channel_settings=channel_settings,
        stage=stage or domain,
    )


def resolve_provider_binding(domain: str, selected: str) -> tuple[str, str]:
    """Resolve a node selection to `(instance_id, provider_type)`.

    Accepts an instance id, a type id, or a type alias. Unknown ids are treated
    as the default instance of that type (`instance_id == selected`) so a
    workflow saved before any settings write still resolves.
    """
    from scriptase.providers import settings_manager
    from scriptase.providers.hub import hub

    stored = settings_manager.get_instance_record(domain, selected)
    if stored is not None:
        type_id = stored.get("type") if isinstance(stored.get("type"), str) else selected
        package = hub.get(domain, type_id)
        if package is not None:
            return selected, package.id
        return selected, type_id

    package = hub.get(domain, selected)
    if package is not None:
        return package.id, package.id
    return selected, selected


def resolve_provider(domain: str, provider: str):
    """Construct the selected provider instance, or fail with a stable adapter error.

    Execution does *not* fail open. Save-time validation tolerates a provider
    that is not installed so a workflow stays inspectable (§23.3), but running
    a node against a provider that cannot be built has no safe interpretation:
    silently substituting another one would produce an artifact nobody asked
    for.

    Step 3.2: `provider` may be an instance id; construction is memoized per
    `(type, instance_id)`.
    """
    from scriptase.providers.hub import hub
    from scriptase.providers.registry import ProviderConstructionError

    instance_id, type_id = resolve_provider_binding(domain, provider)
    try:
        instance = hub.create(domain, type_id, instance_id=instance_id)
    except ProviderConstructionError as exc:
        raise AdapterError(
            exc.code, f"The {domain} provider '{provider}' could not be started"
        ) from exc
    if instance is None:
        raise AdapterError(
            "PROVIDER_UNAVAILABLE",
            f"No {domain} provider named '{provider}' is registered",
        )
    return instance


def _provider_properties(domain: str, provider: str) -> dict:
    """The selected provider type's settings-schema properties, or `{}`."""
    from scriptase.providers.hub import hub

    from scriptase.providers.settings_schema import properties

    _iid, type_id = resolve_provider_binding(domain, provider)
    package = hub.get(domain, type_id)
    return properties(package.settings_schema() if package is not None else None)


def provider_run_options(domain: str, provider: str, config: Mapping[str, Any] | None) -> dict:
    """Merge a node's `provider_options` over the instance's saved settings.

    `{**saved, **per_run}` — "request wins", the order §40.2 freezes for every
    provider, and exactly the order the legacy services already apply.

    Only the *portable* half of the saved settings is read, so a credential can
    never reach a job manifest written under `output/` (§22.6). An unknown key
    is dropped rather than forwarded — "accept, warn, drop before dispatch"
    (§40.2); save-time validation already warned about it.

    Schema defaults are deliberately **not** layered in. A key the operator
    never set must stay absent so the downstream service applies its own
    default; materializing every declared default here would rewrite recorded
    artifacts such as `tts.json`'s `resolved_settings_redacted` for no gain.
    Use `provider_option()` where a resolved value is actually needed.
    """
    props = _provider_properties(domain, provider)
    resolved = dict(_portable_settings(domain, provider))
    patch = (config or {}).get("provider_options")
    for key, value in dict(patch if isinstance(patch, Mapping) else {}).items():
        # With no schema there is nothing to check the key against, so the
        # patch passes through whole rather than being silently emptied.
        if not props or key in props:
            resolved[key] = value
    from scriptase.providers.settings_schema import invocation_config

    return invocation_config({"properties": props} if props else None, resolved)


def _portable_settings(domain: str, provider: str) -> dict:
    from scriptase.providers import settings_manager

    return settings_manager.portable_provider_settings(domain, provider)


def provider_option(domain: str, provider: str, options: Mapping[str, Any], key: str):
    """One option's effective value: the merged one, else the schema's default.

    This is what replaced the per-provider literals the adapters used to carry
    (`"480p"`, `"6s"`, `"video"`). The vocabulary and the defaults of a
    provider's options now live only in that provider's settings schema, so a
    new provider changes them without an edit here (contracts.md §26).
    """
    if key in options:
        return options[key]
    prop = _provider_properties(domain, provider).get(key)
    return prop.get("default") if isinstance(prop, dict) else None


def artifact_ref(path: str) -> str:
    absolute = os.path.abspath(path)
    root = os.path.abspath(OUTPUT_DIR)
    try:
        if os.path.commonpath([root, absolute]) != root:
            raise ValueError
    except ValueError as exc:
        raise AdapterError("ARTIFACT_UNMANAGED", "Artifact is outside the managed output directory") from exc
    return os.path.relpath(absolute, root).replace("\\", "/")


def with_artifacts(payload: Mapping[str, Any], *paths: str) -> dict:
    result = dict(payload)
    refs = list(result.get("artifact_refs") or [])
    for path in paths:
        if path:
            ref = artifact_ref(path)
            if ref not in refs:
                refs.append(ref)
    result["artifact_refs"] = refs
    return result


def outputs(**ports) -> dict:
    return {"control": CONTROL, **ports}
