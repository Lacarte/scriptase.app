"""Manifest for the `n8n` script provider.

Sends a flat, channel-shaped payload (niche_preset, preset_style,
story_category, story_tone, language, duration, template_brief,
template_sections) to a configurable n8n webhook that runs the caller's own
script-generation workflow, then parses the returned script into the standard
story document. Unlike `gemini`, this provider builds no prompt itself — the
n8n workflow owns the prompting — so the request carries the Channel's brief
and section outline verbatim.
"""

from scriptase.providers.registry import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="n8n",
        label="Script Generator (not in use)",
        domain="script",
        kind="webhook",
        version="1.0.0",
        requires=[],
        capabilities={
            "test_connection": True,
            "structured_sections": True,
            "language_select": True,
            "offline": False,
            "single_scene": False,
            "batch": False,
        },
        description=(
            "Script generation via a configurable n8n webhook. Sends the "
            "Channel's niche, style, tone, duration, and template outline, and "
            "writes stories/{id}/story.json from the returned script."
        ),
        # Read-time fallback only — never copied into settings.json (§22.6).
        environment={"webhook_url": "N8N_STORY_WEBHOOK_URL"},
    )
