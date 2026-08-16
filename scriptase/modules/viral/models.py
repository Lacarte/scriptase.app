"""Typed result shapes for the deterministic virality scorer (step 16.1).

Frozen here so step 16.2 can wrap the scorer as the default implementation of an
optional ``viral`` provider domain without changing the node contract, and 16.3
can render the breakdown from a stable schema.

Reasons carry structured codes, never prose. The scorer states *what* it
measured and the caller owns the wording, which keeps a ReviewIssue raised from
a low score free of generated free text (contracts.md §7).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Identity of the shipped implementation. Bump ``SCORER_VERSION`` whenever a
# weight, threshold, or archetype pattern changes, so a stored score is never
# silently compared against one produced by different arithmetic.
SCORER_ID = "deterministic"
SCORER_VERSION = 1

# Declaration order is the presentation order and is part of the contract.
DIMENSION_IDS = (
    "hook",
    "opening_line",
    "pacing",
    "open_loops",
    "cta",
    "balance",
)

# Weights sum to exactly 1.0; ``service`` asserts it at import.
DIMENSION_WEIGHTS: dict[str, float] = {
    "hook": 0.22,
    "opening_line": 0.22,
    "pacing": 0.20,
    "open_loops": 0.16,
    "cta": 0.10,
    "balance": 0.10,
}

ScoreBand = Literal["poor", "weak", "solid", "strong"]

# Descending floors — the first floor a score reaches wins.
SCORE_BANDS: tuple[tuple[int, ScoreBand], ...] = (
    (75, "strong"),
    (60, "solid"),
    (40, "weak"),
    (0, "poor"),
)


def band_for(score: int) -> ScoreBand:
    """Map a 0-100 score onto its band."""
    for floor, band in SCORE_BANDS:
        if score >= floor:
            return band
    return "poor"


class ScoreReason(BaseModel):
    """One structured observation behind a dimension score."""

    model_config = {"extra": "forbid"}

    code: str
    impact: Literal["positive", "negative"]
    detail: dict[str, Any] = Field(default_factory=dict)


class DimensionScore(BaseModel):
    """A single scored dimension and the reasons that produced it."""

    model_config = {"extra": "forbid"}

    id: str
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    points: float = Field(ge=0.0, le=100.0)
    reasons: list[ScoreReason] = Field(default_factory=list)


class ViralScore(BaseModel):
    """The full deterministic score for one script."""

    model_config = {"extra": "forbid"}

    scorer: str = SCORER_ID
    scorer_version: int = SCORER_VERSION
    score: int = Field(ge=0, le=100)
    band: ScoreBand
    dimensions: list[DimensionScore] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    def dimension(self, dimension_id: str) -> DimensionScore | None:
        """Look a dimension up by id."""
        return next((d for d in self.dimensions if d.id == dimension_id), None)
