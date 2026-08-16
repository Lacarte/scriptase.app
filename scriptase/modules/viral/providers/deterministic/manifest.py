"""Deterministic virality scorer manifest — Provider Contract v2 (step 16.2).

Thin wrapper over the offline scoring module built in 16.1. It declares the
whole viral capability vocabulary because it genuinely does all of it: a total,
the per-dimension breakdown, and no network.

`requires` is empty and `environment` is empty on purpose — this provider is
always available, which is what lets the node be safe to leave in a graph.
"""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="deterministic",
        label="Deterministic scorer",
        domain="viral",
        kind="local",
        version="1.0.0",
        contract_version=2,
        requires=[],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "script_scoring": True,
            "dimension_breakdown": True,
            "offline": True,
        },
        description=(
            "Offline, deterministic virality scorer. Measures hook presence and "
            "position, opening-line strength against fifteen archetypes, pacing "
            "against the target duration, open loops, CTA presence, and section "
            "balance. Identical input always scores identically, and it costs "
            "nothing to run. LLM judges ship as sibling packages."
        ),
        environment={},
    )
