"""Manifest for the app-prompt script provider (id `script_n8n`, step 13.2).

Wraps the n8n story webhook path that previously lived only as the hard-wired
`scriptase.modules.script.service.generate_story` call: the APP builds the
system/user prompt and the n8n webhook relays it to the LLM. The label is
"Story Generator" and the transport badge is n8n.

The canonical id was `gemini` until the rename; `gemini` is retained as a
permanent **input** alias (alongside the 12.3 `builtin` bridge id) so old
workflows, settings, V2 imports, and the frozen §41.3 migration anchors that
still name `gemini` keep resolving here (contracts.md §40.3 rule 4).
"""

from scriptase.providers.registry import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="script_n8n",
        label="Story Generator",
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
        aliases=["gemini", "builtin"],
        description=(
            "AI story generation via the configured n8n/Gemini webhook. "
            "Returns hook/build/climax/CTA sections and writes stories/{id}/story.json."
        ),
        # Read-time fallback only — never copied into settings.json (§22.6).
        environment={"webhook_url": "N8N_STORY_WEBHOOK_URL"},
    )
