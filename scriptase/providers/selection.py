"""Capability selector and fallback-chain helpers (step 3.3).

Capabilities are declared per domain vocabulary and per provider manifest, but
until this module nothing asked *"give me a provider in this domain supporting
this capability"*. Feature-gate call sites (``capabilities.get("streaming")``)
remain valid; this selector is the ordered-candidate query used by capability
routing (step 6.2) and future fallback execution (step 8.3).

``fallback_policies`` (primary + ordered fallbacks, per stage) are persisted on
Channel and snapshotted onto Job from day one. Runtime execution of a chain is
explicitly **not** this module's job — it only shapes and orders candidates.

Ordering rules for ``select_candidates``:

1. Channel / Job ``fallback_policies[stage]`` chain — ``primary``, then
   ``fallbacks[]`` in order (deduplicated, capability-filtered).
2. Explicit ``preferred_instance_id`` (e.g. node config or channel
   ``provider_defaults``).
3. Domain ``selected_instance_id`` from the settings store.
4. Remaining configured instances of matching types (catalog type order, then
   instance id).
5. Remaining discovered types with no stored instance, as the default binding
   (``instance_id == type``), in catalog declaration order.

Only instances whose **type** grants every requested capability (or any, when
``require_all=False``) appear. A missing or false capability key is a non-match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from scriptase.channels.models import FallbackPolicy
from scriptase.providers.domains import canonical_domain


# Rank reasons — why this candidate sits at this position. Distinct from
# provenance ``selection_reason`` (contracts.md §2), which records why a run
# actually used an instance. Runtime fallback (8.3) maps chain position onto
# ``fallback_after:<instance_id>`` when it executes.
RANK_FALLBACK_PRIMARY = "fallback_primary"
RANK_FALLBACK_CHAIN = "fallback_chain"
RANK_PREFERRED = "preferred"
RANK_SETTINGS = "settings"
RANK_CATALOG = "catalog"


@dataclass(frozen=True)
class ProviderCandidate:
    """One ordered candidate from a capability query. Never executes anything."""

    domain: str
    instance_id: str
    provider_type: str
    label: str
    capabilities: dict[str, bool] = field(default_factory=dict)
    availability: str = "needs_configuration"
    rank_reason: str = RANK_CATALOG
    # Position in a policy chain when rank_reason is fallback_*; 0 = primary.
    chain_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "domain": self.domain,
            "instance_id": self.instance_id,
            "provider_type": self.provider_type,
            "label": self.label,
            "capabilities": dict(self.capabilities),
            "availability": self.availability,
            "rank_reason": self.rank_reason,
        }
        if self.chain_index is not None:
            payload["chain_index"] = self.chain_index
        return payload


def has_capabilities(
    capabilities: Mapping[str, Any] | None,
    required: Iterable[str] | None,
    *,
    require_all: bool = True,
) -> bool:
    """True when the capability map satisfies ``required``.

    An empty or omitted ``required`` matches everything (capability-free query
    = "all providers in the domain"). A missing key or a false value is a miss.
    """
    required_list = [str(item).strip() for item in (required or ()) if str(item).strip()]
    if not required_list:
        return True
    caps = capabilities if isinstance(capabilities, Mapping) else {}
    if require_all:
        return all(caps.get(name) is True for name in required_list)
    return any(caps.get(name) is True for name in required_list)


def normalize_fallback_policy(
    value: FallbackPolicy | Mapping[str, Any] | None,
) -> FallbackPolicy | None:
    """Coerce a mapping or model into a ``FallbackPolicy``, or ``None`` if empty."""
    if value is None:
        return None
    if isinstance(value, FallbackPolicy):
        policy = value
    elif isinstance(value, Mapping):
        policy = FallbackPolicy.model_validate(value)
    else:
        raise TypeError("fallback policy must be a FallbackPolicy or mapping")
    if not policy.primary and not policy.fallbacks:
        return None
    return policy


def ordered_fallback_ids(
    policy: FallbackPolicy | Mapping[str, Any] | None,
) -> list[str]:
    """Primary then ordered fallbacks, de-duplicated, no execution.

    Empty primary is skipped; empty fallback entries are already stripped by
    ``FallbackPolicy`` validation.
    """
    normalized = normalize_fallback_policy(policy)
    if normalized is None:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for instance_id in [normalized.primary, *normalized.fallbacks]:
        if not instance_id or instance_id in seen:
            continue
        seen.add(instance_id)
        ordered.append(instance_id)
    return ordered


def fallback_policy_from_snapshot(
    snapshot: Mapping[str, Any] | None,
    stage: str,
) -> FallbackPolicy | None:
    """Pull one stage's fallback policy from a Channel or Job channel_snapshot."""
    if not isinstance(snapshot, Mapping):
        return None
    stage_key = str(stage or "").strip()
    if not stage_key:
        return None
    policies = snapshot.get("fallback_policies")
    if not isinstance(policies, Mapping):
        return None
    raw = policies.get(stage_key)
    if raw is None:
        return None
    return normalize_fallback_policy(raw)


def provider_default_from_snapshot(
    snapshot: Mapping[str, Any] | None,
    domain: str,
) -> str | None:
    """Channel ``provider_defaults.<domain>`` instance id, if set."""
    if not isinstance(snapshot, Mapping):
        return None
    defaults = snapshot.get("provider_defaults")
    if not isinstance(defaults, Mapping):
        return None
    value = defaults.get(canonical_domain(domain) if domain else domain)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def select_candidates(
    domain: str,
    *,
    capabilities: Sequence[str] | None = None,
    require_all: bool = True,
    fallback_policy: FallbackPolicy | Mapping[str, Any] | None = None,
    preferred_instance_id: str | None = None,
    channel_snapshot: Mapping[str, Any] | None = None,
    stage: str | None = None,
    include_unconfigured_types: bool = True,
    available_only: bool = False,
    provider_hub: Any | None = None,
    settings_for: Any | None = None,
) -> list[ProviderCandidate]:
    """Return ordered provider instance candidates for a capability query.

    Parameters
    ----------
    domain:
        Provider domain id (or retired V2 alias).
    capabilities:
        Required capability names. Empty means every registered type matches.
    require_all:
        When True (default), every listed capability must be granted. When
        False, any one is enough.
    fallback_policy:
        Explicit primary + fallbacks for this query. When omitted and
        ``channel_snapshot`` + ``stage`` are given, the snapshot policy is used.
    preferred_instance_id:
        Instance that should rank just after the policy chain (node config,
        channel default, caller preference). When omitted and a channel
        snapshot is provided, ``provider_defaults[domain]`` is used.
    channel_snapshot:
        Job or Channel freeze used to resolve policy and defaults.
    stage:
        Stage key under ``fallback_policies`` (usually the domain id).
    include_unconfigured_types:
        When True, types with no stored instance still appear as their default
        binding (``instance_id == type``).
    available_only:
        Drop candidates whose availability is not ``available``.
    provider_hub:
        Optional hub (tests inject a private one). Defaults to the process hub.
    settings_for:
        Optional ``(domain, instance_id) -> settings dict`` for availability.
        Defaults to the canonical settings store.
    """
    from scriptase.providers import hub as hub_module
    from scriptase.providers import settings_manager
    from scriptase.providers.registry import AVAILABLE

    domain_id = canonical_domain(domain)
    hub = provider_hub if provider_hub is not None else hub_module.hub
    # Unknown domain → empty list; callers that need a 404 own that path.
    try:
        hub.spec(domain_id)
    except (ValueError, KeyError):
        return []

    required = [str(c).strip() for c in (capabilities or ()) if str(c).strip()]

    # Resolve policy: explicit arg wins, else snapshot[stage] or snapshot[domain].
    policy = normalize_fallback_policy(fallback_policy)
    if policy is None and channel_snapshot is not None:
        stage_key = (stage or domain_id).strip()
        policy = fallback_policy_from_snapshot(channel_snapshot, stage_key)

    preferred = (
        preferred_instance_id.strip()
        if isinstance(preferred_instance_id, str) and preferred_instance_id.strip()
        else None
    )
    if preferred is None and channel_snapshot is not None:
        preferred = provider_default_from_snapshot(channel_snapshot, domain_id)

    # Matching provider types (catalog order).
    providers = list(hub.list(domain_id))
    matching_types: dict[str, Any] = {}
    for provider in providers:
        if has_capabilities(provider.capabilities, required, require_all=require_all):
            matching_types[provider.id] = provider
    if not matching_types:
        return []

    # Configured instances from the settings store.
    stored_instances = settings_manager.list_instances(domain_id)
    selected_id = settings_manager.get_selected_instance_id(domain_id)

    def resolve_type(instance_id: str) -> str | None:
        rec = stored_instances.get(instance_id)
        if isinstance(rec, dict):
            type_id = rec.get("type")
            if isinstance(type_id, str) and type_id:
                return type_id
        # Default-instance convention: instance_id == type, only when that type
        # is a matching discovered package (or any matching type if unconfigured
        # types are allowed and the id equals a type id).
        if instance_id in matching_types:
            return instance_id
        return None

    def settings_for_instance(instance_id: str, type_id: str) -> dict:
        if settings_for is not None:
            return dict(settings_for(domain_id, instance_id) or {})
        rec = stored_instances.get(instance_id)
        if isinstance(rec, dict) and isinstance(rec.get("settings"), dict):
            return dict(rec["settings"])
        # Unknown id treated as empty default-instance settings.
        return {}

    def build_candidate(
        instance_id: str,
        *,
        rank_reason: str,
        chain_index: int | None = None,
    ) -> ProviderCandidate | None:
        type_id = resolve_type(instance_id)
        if type_id is None or type_id not in matching_types:
            return None
        provider = matching_types[type_id]
        stored = settings_for_instance(instance_id, type_id)
        availability = provider.availability(stored, instance_id=instance_id)
        if available_only and availability != AVAILABLE:
            return None
        label = instance_id
        rec = stored_instances.get(instance_id)
        if isinstance(rec, dict) and isinstance(rec.get("label"), str) and rec["label"]:
            label = rec["label"]
        elif provider.label:
            label = provider.label
        return ProviderCandidate(
            domain=domain_id,
            instance_id=instance_id,
            provider_type=type_id,
            label=label,
            capabilities=dict(provider.capabilities),
            availability=availability,
            rank_reason=rank_reason,
            chain_index=chain_index,
        )

    ordered: list[ProviderCandidate] = []
    seen: set[str] = set()

    def push(
        instance_id: str | None,
        *,
        rank_reason: str,
        chain_index: int | None = None,
    ) -> None:
        if not instance_id or instance_id in seen:
            return
        candidate = build_candidate(
            instance_id, rank_reason=rank_reason, chain_index=chain_index
        )
        if candidate is None:
            return
        seen.add(instance_id)
        ordered.append(candidate)

    # 1. Policy chain.
    for index, instance_id in enumerate(ordered_fallback_ids(policy)):
        push(
            instance_id,
            rank_reason=RANK_FALLBACK_PRIMARY if index == 0 else RANK_FALLBACK_CHAIN,
            chain_index=index,
        )

    # 2. Preferred / channel default.
    push(preferred, rank_reason=RANK_PREFERRED)

    # 3. Domain selection.
    push(selected_id, rank_reason=RANK_SETTINGS)

    # 4. Remaining configured instances of matching types (stable order).
    # Catalog type order first; within a type, selection already handled, then
    # sorted instance ids for determinism.
    type_order = list(matching_types.keys())
    by_type: dict[str, list[str]] = {tid: [] for tid in type_order}
    for iid, rec in stored_instances.items():
        if not isinstance(rec, dict):
            continue
        type_id = rec.get("type") if isinstance(rec.get("type"), str) else iid
        if type_id in by_type:
            by_type[type_id].append(iid)
    for type_id in type_order:
        for iid in sorted(by_type.get(type_id, [])):
            push(iid, rank_reason=RANK_CATALOG)

    # 5. Unconfigured matching types as default bindings.
    if include_unconfigured_types:
        for type_id in type_order:
            push(type_id, rank_reason=RANK_CATALOG)

    return ordered


def select_first(
    domain: str,
    *,
    capabilities: Sequence[str] | None = None,
    require_all: bool = True,
    fallback_policy: FallbackPolicy | Mapping[str, Any] | None = None,
    preferred_instance_id: str | None = None,
    channel_snapshot: Mapping[str, Any] | None = None,
    stage: str | None = None,
    available_only: bool = False,
    provider_hub: Any | None = None,
) -> ProviderCandidate | None:
    """Convenience: first candidate from ``select_candidates``, or ``None``."""
    candidates = select_candidates(
        domain,
        capabilities=capabilities,
        require_all=require_all,
        fallback_policy=fallback_policy,
        preferred_instance_id=preferred_instance_id,
        channel_snapshot=channel_snapshot,
        stage=stage,
        available_only=available_only,
        provider_hub=provider_hub,
    )
    return candidates[0] if candidates else None


__all__ = [
    "RANK_FALLBACK_PRIMARY",
    "RANK_FALLBACK_CHAIN",
    "RANK_PREFERRED",
    "RANK_SETTINGS",
    "RANK_CATALOG",
    "ProviderCandidate",
    "has_capabilities",
    "normalize_fallback_policy",
    "ordered_fallback_ids",
    "fallback_policy_from_snapshot",
    "provider_default_from_snapshot",
    "select_candidates",
    "select_first",
]
