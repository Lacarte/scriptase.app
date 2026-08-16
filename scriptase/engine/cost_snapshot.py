"""Compact cost/provenance snapshot for node execution records (step 9.3).

``outputs_summary`` runs through ``_summarize``, which turns string decimals
into ``{chars: N}``. Accounting therefore stores a dedicated ``cost`` field on
``NodeExecutionRecord`` that preserves reported amounts and identity fields.

This module is engine-side only (no Job imports) so the scheduler can stamp
snapshots at node success without a jobs→engine cycle.
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.providers.results import extract_cost

from .adapters.common import PROVIDER_OVERRIDE_KEY

# Mirrors scriptase.jobs.budget.PROVIDER_NODE_TYPES so the engine never imports
# the jobs package. Keep both sets in sync when adding provider-capable nodes.
PROVIDER_NODE_TYPES: frozenset[str] = frozenset({
    "story.generate",
    "tts.generate",
    "scenes.blueprint",
    "storyboard.generate",
    "animator.generate",
    "review.run",
    "review.semantic",
})


def is_provider_node_type(node_type: str | None) -> bool:
    return str(node_type or "") in PROVIDER_NODE_TYPES


def _first_provenance(value: Any, *, depth: int = 0) -> Mapping[str, Any] | None:
    """Find the first nested ``provenance`` mapping in a node result tree."""
    if depth > 6 or value is None:
        return None
    if isinstance(value, Mapping):
        prov = value.get("provenance")
        if isinstance(prov, Mapping) and (
            prov.get("invocation_id")
            or prov.get("provider_id")
            or prov.get("provider_instance_id")
            or prov.get("cost") is not None
        ):
            return prov
        for child in value.values():
            found = _first_provenance(child, depth=depth + 1)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value[:20]:
            found = _first_provenance(child, depth=depth + 1)
            if found is not None:
                return found
    return None


def _provider_instance_from_config(configuration: Mapping[str, Any] | None) -> str:
    if not isinstance(configuration, Mapping):
        return ""
    for key in (
        # Step 13.2: a request-pinned instance outranks the saved one here for
        # the same reason it does at dispatch — it is what actually ran.
        PROVIDER_OVERRIDE_KEY,
        "provider_instance_id",
        "provider_id",
        "tts_provider_override",
        "engine",
    ):
        value = configuration.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def cost_snapshot_from_result(
    result: Mapping[str, Any] | None,
    *,
    cache_hit: bool = False,
    configuration: Mapping[str, Any] | None = None,
    is_provider_node: bool = False,
) -> dict[str, Any] | None:
    """Build the durable cost snapshot for a succeeded node.

    Returns ``None`` when the node is not provider-capable and no provenance
    was present (local services do not consume generation budget).

    Cache hits still record a zero-generation snapshot when provenance is
    present so reports can show the hit; they do not increment spend.
    """
    provenance = _first_provenance(result) if isinstance(result, Mapping) else None

    provider_instance_id = ""
    provider_id = ""
    invocation_id = ""
    selection_reason = ""
    cost_block: dict[str, Any] | None = None

    if isinstance(provenance, Mapping):
        provider_instance_id = str(
            provenance.get("provider_instance_id") or ""
        ).strip()
        provider_id = str(provenance.get("provider_id") or "").strip()
        invocation_id = str(provenance.get("invocation_id") or "").strip()
        selection_reason = str(provenance.get("selection_reason") or "").strip()
        raw_cost = provenance.get("cost")
        if isinstance(raw_cost, Mapping):
            cost_block = extract_cost(cost=raw_cost)
        # Provenance may carry cache_hit more accurately than the lookup flag.
        if provenance.get("cache_hit") is True:
            cache_hit = True

    if not provider_instance_id:
        provider_instance_id = _provider_instance_from_config(configuration)
    # Step 13.2: a provider that stamped no provenance still has to say which
    # instance produced the result and why, or two back-to-back test runs are
    # indistinguishable in the record.
    if not selection_reason and isinstance(configuration, Mapping):
        override = configuration.get(PROVIDER_OVERRIDE_KEY)
        if isinstance(override, str) and override.strip():
            selection_reason = "request"

    # Top-level cost on the result (adapters that surface it without provenance).
    if cost_block is None and isinstance(result, Mapping):
        if isinstance(result.get("cost"), Mapping):
            cost_block = extract_cost(cost=result.get("cost"))  # type: ignore[arg-type]
        meta = result.get("metadata")
        if cost_block is None and isinstance(meta, Mapping):
            cost_block = extract_cost(metadata=meta)

    if not is_provider_node and cost_block is None and not provenance:
        return None

    generations = 0 if cache_hit else (1 if is_provider_node or provenance else 0)

    snapshot: dict[str, Any] = {
        "generations": int(generations),
        "cache_hit": bool(cache_hit),
    }
    if provider_instance_id:
        snapshot["provider_instance_id"] = provider_instance_id
    if provider_id:
        snapshot["provider_id"] = provider_id
    if invocation_id:
        snapshot["invocation_id"] = invocation_id
    if selection_reason:
        snapshot["selection_reason"] = selection_reason
    if cost_block is not None:
        snapshot["amount"] = cost_block["amount"]
        snapshot["currency"] = cost_block["currency"]
        if cost_block.get("unit_count") is not None:
            snapshot["unit_count"] = cost_block["unit_count"]
        if cost_block.get("unit"):
            snapshot["unit"] = cost_block["unit"]

    return snapshot


__all__ = [
    "PROVIDER_NODE_TYPES",
    "cost_snapshot_from_result",
    "is_provider_node_type",
]
