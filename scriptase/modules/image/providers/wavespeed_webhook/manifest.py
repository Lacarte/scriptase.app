"""WaveSpeed Webhook Storyboard Provider Manifest — Phase 6."""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="wavespeed_webhook",
        label="Webhook / WaveSpeed",
        domain="image",
        kind="cloud",
        version="2.0.0",
        contract_version=2,
        requires=["webhook_url"],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "async_job": True,
            "cancel": True,
            "progress": True,
            # Step 6.1 routing: prompt → storyboard frames via webhook.
            "text_to_image": True,
        },
        aliases=["webhook"],
        description="Storyboard frames via a user-supplied n8n webhook.",
        environment={"webhook_url": "N8N_STORYBOARD_WEBHOOK_URL"},
    )