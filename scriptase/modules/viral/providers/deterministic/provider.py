"""Deterministic virality provider — the shipped default (step 16.2).

Owns no arithmetic of its own. Everything it knows lives in
``scriptase.modules.viral``, which 16.1 built as an importable service with no
transport and no node; this package is the adapter that makes that service
selectable through the provider platform.

Because the scorer is pure, this provider has no settings and no failure mode
worth reporting: `health_check` is always green and `validate_settings` always
returns clean. That is deliberate rather than lazy — the node exists to run on
every script before anything costs money, so a scorer that could be
mis-configured into failing would defeat the point.
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.modules.viral.providers.base import ViralProvider
from scriptase.modules.viral.providers.contract import (
    ViralRequest,
    ViralResultPayload,
)
from scriptase.modules.viral.service import score_script


class DeterministicViralProvider(ViralProvider):
    """Offline scorer over the six frozen dimensions."""

    def score(
        self,
        request: ViralRequest,
        *,
        settings: Mapping[str, Any] | None = None,
    ) -> ViralResultPayload:
        # `settings` is accepted for contract symmetry and intentionally
        # unused: a weight or threshold that an operator could tune would make
        # two stored scores incomparable without telling anyone. Those values
        # are the scorer's identity and move with SCORER_VERSION instead.
        return score_script(
            sections=request.sections,
            story_text=request.story_text,
            target_duration=request.target_duration,
            narrative_roles=request.narrative_roles,
        )


def create() -> DeterministicViralProvider:
    """Zero-arg factory required by the provider registry."""
    return DeterministicViralProvider()


def validate_settings(settings: dict) -> list[dict]:
    return []


def health_check(settings: dict) -> dict:
    return {
        "status": "ok",
        "latency_ms": 0,
        "message": "Offline deterministic scorer ready",
    }
