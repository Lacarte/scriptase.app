"""Importable virality scoring service (step 16.1).

The public entry is :func:`score_script`. It is offline, deterministic, and free
to run, so it can execute on every script before a single paid stage does.

Step 16.2 wraps this as the default implementation of an optional ``viral``
provider domain; the node contract is the :class:`ViralScore` shape, not this
function, so an LLM judge can replace the arithmetic without a schema change.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .models import (
    DIMENSION_IDS,
    DIMENSION_WEIGHTS,
    SCORER_ID,
    SCORER_VERSION,
    DimensionScore,
    ViralScore,
    band_for,
)
from .scoring import SCORERS, ScriptDoc, build_doc

# A drifted weight table would silently rescale every stored score.
assert tuple(name for name, _ in SCORERS) == DIMENSION_IDS
assert round(sum(DIMENSION_WEIGHTS[name] for name in DIMENSION_IDS), 6) == 1.0

DEFAULT_TARGET_DURATION = 45


def score_script(
    *,
    sections: Mapping[str, str] | None = None,
    story_text: str | None = None,
    target_duration: int = DEFAULT_TARGET_DURATION,
    narrative_roles: Iterable[str] | None = None,
) -> ViralScore:
    """Score one script across the six deterministic dimensions.

    Either `sections` (the mandated Hook / Build / Climax / CTA map) or
    `story_text` is enough; supplying both scores the most. `narrative_roles`
    is the ordered Scene Director role vocabulary when scenes already exist —
    it sharpens hook position and is ignored when absent.
    """
    doc = build_doc(
        dict(sections or {}),
        story_text,
        target_duration,
        tuple(narrative_roles or ()),
    )

    dimensions: list[DimensionScore] = []
    total = 0.0
    for name, scorer in SCORERS:
        value, reasons = scorer(doc)
        weight = DIMENSION_WEIGHTS[name]
        points = round(value * weight * 100, 4)
        total += points
        dimensions.append(
            DimensionScore(id=name, score=value, weight=weight, points=points, reasons=reasons)
        )

    score = max(0, min(100, round(total)))
    return ViralScore(
        scorer=SCORER_ID,
        scorer_version=SCORER_VERSION,
        score=score,
        band=band_for(score),
        dimensions=dimensions,
        metrics=_metrics(doc),
    )


def score_story_payload(story_data: Mapping[str, Any]) -> ViralScore:
    """Score the payload the script service already produces.

    Reads `sections`, `story_text`, and the requested `metadata.duration` so
    callers do not have to unpack the story document themselves.
    """
    metadata = story_data.get("metadata") or {}
    duration = metadata.get("duration") or DEFAULT_TARGET_DURATION
    return score_script(
        sections=story_data.get("sections") or {},
        story_text=story_data.get("story_text") or "",
        target_duration=int(duration),
    )


def _metrics(doc: ScriptDoc) -> dict[str, Any]:
    """The measurements the score was computed from, for the UI breakdown."""
    return {
        "total_words": doc.total_words,
        "estimated_duration": doc.estimated_duration,
        "target_duration": doc.target_duration,
        "section_words": dict(doc.section_words),
        "section_shares": {key: doc.share(key) for key in doc.section_words},
        "sentences": len(doc.sentences),
        "opening_line": doc.opening_line,
    }
