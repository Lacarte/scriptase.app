"""Manifest for the offline `random_template` script provider (step 13.1).

Owns the curated sample-story catalog that previously lived in
`frontend/src/shared/data/stories.js`. Selection and anti-repeat are backend
rules; the frontend is only a thin API consumer.
"""

from scriptase.providers.registry import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="random_template",
        label="Random template",
        domain="script",
        kind="local",
        version="1.0.0",
        requires=[],
        capabilities={
            "test_connection": True,
            "structured_sections": False,
            "language_select": True,
            "offline": True,
            "single_scene": True,
            "batch": False,
        },
        description=(
            "Picks a curated sample narration from a local catalog. Offline, "
            "deterministic when seeded, and free of network or credentials."
        ),
    )
