"""Grok Automa Animator Provider Manifest — Contract v2 (step 14.3)."""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="grok_automa",
        label="Grok (extension)",
        domain="video",
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
            # Declared by step 12.4 so the Assets page can offer the
            # storyboard-to-video hand-off without asking *which* provider it is
            # talking to (contracts.md §20.4).
            "image_to_video": True,
            "duration_control": True,
            "resolution_select": True,
        },
        # The page the user must have open for the extension to drive. It was a
        # literal in `AssetsPage.vue` and `useAssets.js` until 12.4; a provider's
        # own URL belongs in its manifest (§20.1).
        open_url="https://grok.com/imagine",
        # `midjourney` is the third legacy wire value normalized here today
        # (animator/schemas.py, contracts.md §14.4 / P12 — the unreachable
        # midjourney branch is gone; the alias still resolves to this provider).
        aliases=["grok", "midjourney"],
        description="Animator takes driven by the browser extension over a WebSocket.",
    )