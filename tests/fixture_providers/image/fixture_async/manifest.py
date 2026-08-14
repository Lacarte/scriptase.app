"""Async multi-asset shape — the `storyboard` third of the §26 proof.

The shape that submits a job, reports progress, and produces one result per
requested unit. Declares `async_job`, `progress`, and `cancel`, which is how
the platform learns it has to poll rather than wait for a return value — never
from its id.
"""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="fixture_async",
        label="Fixture Async Renderer",
        domain="image",
        kind="cloud",
        version="3.0.0",
        contract_version=2,
        requires=["endpoint_url"],
        aliases=["fixture-async-legacy"],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "async_job": True,
            "cancel": True,
            "progress": True,
            "image_edit": True,
        },
        description="Deterministic offline multi-asset renderer used by the Phase 12 gate.",
    )
