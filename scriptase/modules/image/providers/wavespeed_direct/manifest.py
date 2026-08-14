"""WaveSpeed Direct Storyboard Provider Manifest — Phase 6."""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="wavespeed_direct",
        label="WaveSpeed Direct",
        domain="image",
        kind="cloud",
        version="2.0.0",
        contract_version=2,
        requires=["api_key"],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "async_job": True,
            "cancel": True,
            "progress": True,
            # Step 6.1 routing vocabulary.
            "text_to_image": True,
            "image_edit": True,
        },
        aliases=["direct"],
        description="Storyboard frames from the WaveSpeed API, called directly.",
        environment={"api_key": "WAVESPEED_API_KEY"},
    )