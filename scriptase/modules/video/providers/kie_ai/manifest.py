"""Kie AI Animator Provider Manifest — Contract v2 (step 14.3)."""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="kie_ai",
        label="Kie AI",
        domain="video",
        kind="cloud",
        version="2.0.0",
        contract_version=2,
        requires=["api_key"],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "async_job": True,
            "progress": True,
            "resolution_select": True,
        },
        aliases=["kie-ai"],
        description="Image generation through the Kie AI API.",
        environment={"api_key": "KIE_AI_API_KEY", "model": "KIE_AI_MODEL"},
    )