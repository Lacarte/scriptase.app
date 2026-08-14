"""Async multi-asset shape — the `animator` third of the §26 proof.

Discovered only when a test points `DomainSpec.providers_base` at this folder.
Declares `async_job` + `progress` + `cancel` so the platform polls rather than
waiting for a return value — never from its id.
"""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="fixture_async",
        label="Fixture Async Animator",
        domain="video",
        kind="cloud",
        version="3.0.0",
        contract_version=2,
        requires=["endpoint_url"],
        aliases=["fixture-async-animator"],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "async_job": True,
            "cancel": True,
            "progress": True,
            "image_to_video": True,
            "duration_control": True,
            "resolution_select": True,
        },
        description="Deterministic offline multi-asset animator used by the Phase 14 gate.",
    )
