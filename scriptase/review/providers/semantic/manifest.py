"""Semantic review provider manifest — Provider Contract v2 (step 7.3).

Offline, deterministic heuristic reviewer. Declares the full review-domain
capability vocabulary so capability selection can route image / video / text /
structured subjects without platform edits.
"""

from scriptase.providers import ProviderManifest


def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="semantic",
        label="Semantic reviewer",
        domain="review",
        kind="local",
        version="1.0.0",
        contract_version=2,
        requires=[],
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            "image_review": True,
            "video_review": True,
            "text_review": True,
            "structured_output": True,
        },
        description=(
            "Offline semantic reviewer that emits structured ReviewIssue findings "
            "for text, image, video, and structured subjects. Deterministic "
            "heuristics only — no network, no credentials. AI review providers "
            "can replace this package without framework changes."
        ),
        environment={},
    )
