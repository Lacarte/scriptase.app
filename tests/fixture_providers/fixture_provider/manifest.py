"""The reference v2 provider — contracts.md §46.3.

Hand-written, never recorded, and deliberately absent from every hardcoded list
in the codebase. It is the load-bearing fixture for §26's zero-touch assertion:
discovery, the standard runtime, the result envelope, and the error boundary are
all proved against a provider nobody wrote a special case for.

It is registered into a domain by pointing a `DomainSpec.providers_base` at
`tests/fixture_providers/`, so it never appears in the shipped catalog.
"""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="fixture_provider",
        label="Fixture Provider",
        domain="tts",
        kind="local",
        version="1.0.0",
        # The first manifest in the repo to declare the 11.4 invocation
        # contract; the seven shipped providers stay at 1 until 14.x/15.x
        # rewrites their bodies (contracts.md §19.3).
        contract_version=2,
        description="Deterministic in-repo provider used by the contract tests.",
        requires=["api_key"],
        environment={"api_key": "STS_FIXTURE_PROVIDER_KEY"},
        aliases=["fixture-legacy"],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "async_job": True,
            "cancel": True,
            "progress": True,
        },
    )
