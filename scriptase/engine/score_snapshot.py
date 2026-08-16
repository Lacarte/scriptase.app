"""Durable script-score snapshot for node execution records (step 16.3).

Same problem as step 9.3's ``cost``, same answer. ``outputs_summary`` runs every
node result through ``_summarize``, which replaces strings with ``{chars: N}``
and flattens anything past depth 4 to ``{type: "list"}``. A ``script.analyze``
result survives that as an integer and nothing else: the band becomes a
character count and the whole dimension breakdown disappears. The Production
Script panel needs both, so the verdict is stamped onto its own
``NodeExecutionRecord`` field where the summarizer cannot reach it.

Engine-side only — no jobs or review imports — so the scheduler can stamp a
snapshot at node success without an engine→jobs cycle.
"""

from __future__ import annotations

from typing import Any, Mapping

# The one node type that produces a script score. Kept as a literal rather than
# imported from the registry so this module stays free of registry import order.
SCORE_NODE_TYPE = "script.analyze"

# Bounded: 6 dimensions, each with a handful of reasons. A script that somehow
# produced more would be a scorer bug, and truncating here beats writing an
# unbounded blob into every execution record.
_MAX_DIMENSIONS = 12
_MAX_REASONS = 12


def _reason(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    code = str(raw.get("code") or "").strip()
    if not code:
        return None
    impact = str(raw.get("impact") or "").strip() or "negative"
    detail = raw.get("detail")
    return {
        "code": code,
        "impact": impact,
        "detail": dict(detail) if isinstance(detail, Mapping) else {},
    }


def _dimension(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    dimension_id = str(raw.get("id") or "").strip()
    if not dimension_id:
        return None
    reasons: list[dict[str, Any]] = []
    for item in (raw.get("reasons") or [])[:_MAX_REASONS]:
        reason = _reason(item)
        if reason is not None:
            reasons.append(reason)
    return {
        "id": dimension_id,
        "score": raw.get("score"),
        "weight": raw.get("weight"),
        "points": raw.get("points"),
        "reasons": reasons,
    }


def score_snapshot_from_result(
    result: Mapping[str, Any] | None,
    *,
    node_type: str | None = None,
) -> dict[str, Any] | None:
    """Build the durable score snapshot for a succeeded ``script.analyze`` node.

    Returns ``None`` for every other node type, and for a result that carries
    no score — a scorer that failed to produce one must leave the field empty
    rather than record a zero the panel would render as a verdict.
    """
    if str(node_type or "") != SCORE_NODE_TYPE:
        return None
    if not isinstance(result, Mapping):
        return None
    payload = result.get("score")
    if not isinstance(payload, Mapping):
        return None

    viral = payload.get("viral_score")
    viral = viral if isinstance(viral, Mapping) else {}

    raw_score = payload.get("score")
    if raw_score is None:
        raw_score = viral.get("score")
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
        return None

    band = str(payload.get("band") or viral.get("band") or "").strip()
    dimensions: list[dict[str, Any]] = []
    for item in (viral.get("dimensions") or [])[:_MAX_DIMENSIONS]:
        dimension = _dimension(item)
        if dimension is not None:
            dimensions.append(dimension)

    snapshot: dict[str, Any] = {
        "score": int(raw_score),
        "band": band,
        "scorer": str(viral.get("scorer") or "").strip(),
        "scorer_version": viral.get("scorer_version"),
        "provider_id": str(payload.get("provider_id") or "").strip(),
        "target_duration": payload.get("target_duration"),
        "dimensions": dimensions,
    }

    # Present only when a Job with a configured Channel threshold gated the
    # run (step 16.3). A canvas run leaves them out rather than implying the
    # score was measured against a bar nobody set.
    threshold = payload.get("threshold")
    if isinstance(threshold, (int, float)) and not isinstance(threshold, bool):
        snapshot["threshold"] = int(threshold)
        snapshot["passed"] = bool(payload.get("passed"))
    issue_ids = payload.get("issue_ids")
    if isinstance(issue_ids, list) and issue_ids:
        snapshot["issue_ids"] = [str(item) for item in issue_ids if str(item).strip()]

    return snapshot


__all__ = ["SCORE_NODE_TYPE", "score_snapshot_from_result"]
