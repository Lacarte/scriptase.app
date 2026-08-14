"""Sync-artifact shape — the `tts` third of the §26 extensibility proof.

The shape that returns one produced file plus its measurements. Declares
`voice_list` and a `voice` setting whose options come from the provider's own
schema, which is what the `tts_voices` option source reads (step 12.2) — so
this provider's voices reach a node dropdown with no edit to the option
resolver.
"""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="fixture_artifact",
        label="Fixture Artifact Synthesizer",
        domain="tts",
        kind="local",
        version="1.4.0",
        contract_version=2,
        requires=[],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": False,
            "voice_list": True,
            "speed_control": True,
        },
        description="Deterministic offline synthesizer used by the Phase 12 gate.",
    )
