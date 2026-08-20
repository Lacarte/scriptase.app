"""Manifest for the AI `n8n` scene-blueprint provider (step 13.4).

Wraps the existing n8n/OpenRouter scene-blueprint webhook path that previously
lived only as the hard-wired `_step_scenes` / `POST /api/scenes/generate` call.
The transitional 12.3 `builtin` bridge ID is retained as a permanent **input**
alias so workflows and settings that still name `builtin` keep resolving here
(contracts.md §40.3 rule 4).
"""

from scriptase.providers.registry import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="n8n",
        label="Scene Generator",
        domain="scene_director",
        kind="webhook",
        version="1.0.0",
        requires=[],
        capabilities={
            "test_connection": True,
            "chaptering": True,
            "coherence_scoring": True,
            "sfx_report": True,
            "batch": True,
            "single_scene": False,
        },
        aliases=["builtin"],
        description=(
            "AI scene planning via the configured n8n/OpenRouter webhook. "
            "Returns scenes, image prompts, coherence scoring, and sfx validation, "
            "and writes scenes/{id}/scenes.json."
        ),
        # Read-time fallback only — never copied into settings.json (§22.6).
        environment={"webhook_url": "N8N_WEBHOOK_URL"},
    )
