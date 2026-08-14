"""Gemini WS Storyboard Provider Manifest — Phase 6."""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="gemini_ws",
        label="Gemini (extension)",
        domain="image",
        kind="extension",
        version="2.0.0",
        contract_version=2,
        requires=[],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "async_job": True,
            "push_callbacks": True,
            "progress": True,
            # Declared, not inferred: `jobs.record_ready` runs the watermark
            # pass only for the provider that asks for it, so the branch that
            # lived in the WebSocket handler is manifest data now.
            "watermark_removal": True,
            "prompt_prefix": True,
            # The storyboard→animator hand-off `_mark_job_done` performs. It is
            # this provider's behaviour, not its transport's.
            "auto_animate": True,
        },
        # The URL the pipeline hardcoded behind `provider == "gemini"`
        # (`pipeline/routes.py:1051`). It is provider metadata (§20.1).
        open_url="https://gemini.google.com/app",
        aliases=["gemini"],
        description="Storyboard frames driven by the browser extension over a WebSocket.",
    )