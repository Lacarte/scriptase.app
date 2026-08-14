"""Sync-document shape — the `script` half of the §26 extensibility proof.

One of the three shape fixtures step 12.5 adds beside the §46.3 reference
provider. Each covers one execution shape the platform has to support:

    script/fixture_document      sync document   (this package)
    tts/fixture_artifact         sync artifact
    storyboard/fixture_async     async multi-asset

Nothing outside this folder and `tests/` knows this provider exists — that is
the assertion, and `test_provider_extensibility.py` enforces it mechanically.
It is registered by pointing a `DomainSpec.providers_base` at
`tests/fixture_providers/script/`, so it never reaches the shipped catalog.

`requires=["api_key"]` is deliberate: it makes the provider start life as
`needs_configuration`, so the gate can walk the whole catalog → settings →
available chain instead of asserting a provider that was ready from birth.
"""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="fixture_document",
        label="Fixture Document Generator",
        domain="script",
        kind="cloud",
        version="2.1.0",
        contract_version=2,
        requires=["api_key"],
        aliases=["fixture-doc"],
        environment={"api_key": "STS_FIXTURE_DOCUMENT_KEY"},
        capabilities={
            "test_connection": True,
            "structured_sections": True,
            "language_select": True,
            "offline": True,
        },
        description="Deterministic offline script provider used by the Phase 12 gate.",
        docs_url="https://example.invalid/fixture-document",
    )
