"""Viral — deterministic virality scoring for a script, before anything costs money.

Greenfield in step 16.1. V2 never had scoring logic; what carried over is the
taxonomy — the mandated Hook / Build / Climax / CTA sections, the fifteen hook
archetypes behind ``_ANGLE_STARTERS``, and the Scene Director ``narrative_role``
vocabulary.

Six measurable dimensions: hook presence and position, opening-line strength
against the archetypes, pacing and word rate against the target duration, open
loops, CTA presence, and section balance. Offline, deterministic, unit-testable,
and free — identical input always scores identically.

This package holds no transport and no node. Step 16.2 registers the
``script.analyze`` node against an optional ``viral`` provider domain that
defaults to this scorer; step 16.3 surfaces the breakdown on the Script stage
and raises a ReviewIssue below the Channel threshold.
"""

from .models import (
    DIMENSION_IDS,
    DIMENSION_WEIGHTS,
    SCORER_ID,
    SCORER_VERSION,
    DimensionScore,
    ScoreReason,
    ViralScore,
    band_for,
)
from .service import score_script, score_story_payload

__all__ = [
    "DIMENSION_IDS",
    "DIMENSION_WEIGHTS",
    "SCORER_ID",
    "SCORER_VERSION",
    "DimensionScore",
    "ScoreReason",
    "ViralScore",
    "band_for",
    "score_script",
    "score_story_payload",
]
