"""LLM virality judge manifest — Provider Contract v2 (sibling of `deterministic`).

A second opinion on a script's virality from an LLM, running behind an
n8n/OpenRouter webhook. It fills in the same frozen `ViralScore` shape as the
deterministic scorer — the same six dimensions and band floors — so the two are
directly comparable side by side. Unlike the deterministic scorer it is *not*
offline: it costs a model call and can fail, so `offline` is False and the
webhook URL is declared in `environment` (read-time fallback only, §22.6).
"""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="llm_judge",
        label="LLM Judge",
        domain="viral",
        kind="webhook",
        version="1.0.0",
        contract_version=2,
        requires=[],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "script_scoring": True,
            "dimension_breakdown": True,
            # The defining difference from `deterministic`: this one is online.
            "offline": False,
        },
        description=(
            "LLM virality judge. Sends the script to an n8n/OpenRouter webhook "
            "and asks a model to score the same six dimensions the deterministic "
            "scorer measures, returning a 0-100 total and a per-dimension "
            "breakdown. A semantic second opinion — non-deterministic and paid — "
            "meant to sit beside the offline scorer, not replace it."
        ),
        # Read-time fallback only — never copied into settings.json (§22.6).
        environment={"webhook_url": "N8N_VIRALITY_WEBHOOK_URL"},
    )
