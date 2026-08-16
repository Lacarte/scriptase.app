"""Repair routing policy (step 8.1 / contracts.md §9 / product §12.2).

Each structured issue routes to the node responsible for fixing it. Ownership
is a **table**, not a chain of conditionals scattered through the engine:

    ReviewIssue  →  problem_key  →  owner  →  preferred node type(s)

The §12.2 ownership rows are the single source of truth. Step 8.2 reuses the
decision to re-run the smallest responsible scope; step 8.4 records
``routed_to_node_type`` from the same decision.

Disambiguation rules (still table-driven):

* ``observed.problem_key`` / ``observed.routing_problem`` wins when set.
* ``check_id`` (technical validators) maps through ``CHECK_ID_PROBLEM``.
* Otherwise ``issue_type`` maps through ``ISSUE_TYPE_DEFAULT_PROBLEM``.
* ``visual_mismatch`` defaults to Image (wrong subject/style); Scene Director
  ownership for a concept mismatch is selected by the explicit problem key
  ``visual_concept``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scriptase.review.models import ISSUE_TYPES


# ---------------------------------------------------------------------------
# Problem keys — one per §12.2 ownership row
# ---------------------------------------------------------------------------

PROBLEM_SCRIPT_CONTENT = "script_content"
PROBLEM_PRONUNCIATION_VOICE = "pronunciation_voice"
PROBLEM_ALIGNMENT = "alignment_mismatch"
PROBLEM_SCENE_BOUNDARIES = "scene_boundaries"
PROBLEM_VISUAL_CONCEPT = "visual_concept"
PROBLEM_IMAGE_SUBJECT_STYLE = "image_subject_style"
PROBLEM_MOTION = "motion_deformation"
PROBLEM_CAPTION_BRANDING = "caption_branding"
PROBLEM_RENDER_CODEC = "render_codec"

PROBLEM_KEYS: tuple[str, ...] = (
    PROBLEM_SCRIPT_CONTENT,
    PROBLEM_PRONUNCIATION_VOICE,
    PROBLEM_ALIGNMENT,
    PROBLEM_SCENE_BOUNDARIES,
    PROBLEM_VISUAL_CONCEPT,
    PROBLEM_IMAGE_SUBJECT_STYLE,
    PROBLEM_MOTION,
    PROBLEM_CAPTION_BRANDING,
    PROBLEM_RENDER_CODEC,
)

# Stable owner ids used by RoutingDecision.owner and RepairHistoryEntry later.
OWNER_SCRIPT = "script"
OWNER_TTS = "tts"
OWNER_TIMING = "timing"
OWNER_SEGMENTER = "segmenter"
OWNER_SCENE_DIRECTOR = "scene_director"
OWNER_IMAGE = "image"
OWNER_VIDEO = "video"
OWNER_COMPOSER = "composer"
OWNER_EXPORT = "export"

OWNERS: tuple[str, ...] = (
    OWNER_SCRIPT,
    OWNER_TTS,
    OWNER_TIMING,
    OWNER_SEGMENTER,
    OWNER_SCENE_DIRECTOR,
    OWNER_IMAGE,
    OWNER_VIDEO,
    OWNER_COMPOSER,
    OWNER_EXPORT,
)


@dataclass(frozen=True)
class OwnershipRow:
    """One row of the §12.2 ownership table."""

    problem_key: str
    description: str
    owner: str
    label: str
    stage_key: str
    node_types: tuple[str, ...]
    # issue_types that *default* to this row (not exclusive — see visual split).
    issue_types: tuple[str, ...] = ()


# Authoritative §12.2 table. Order matches contracts.md.
OWNERSHIP_TABLE: tuple[OwnershipRow, ...] = (
    OwnershipRow(
        problem_key=PROBLEM_SCRIPT_CONTENT,
        description="Script too long, wrong tone, weak hook",
        owner=OWNER_SCRIPT,
        label="Script",
        stage_key="script",
        node_types=("story.generate", "script.input"),
        issue_types=("script_defect",),
    ),
    OwnershipRow(
        problem_key=PROBLEM_PRONUNCIATION_VOICE,
        description="Pronunciation or voice problem",
        owner=OWNER_TTS,
        label="TTS",
        stage_key="voice",
        node_types=("tts.generate",),
        issue_types=("audio_defect",),
    ),
    OwnershipRow(
        problem_key=PROBLEM_ALIGNMENT,
        description="Words do not align with audio",
        owner=OWNER_TIMING,
        label="Timing",
        stage_key="timing",
        node_types=("timing.align",),
        issue_types=("timing_drift",),
    ),
    OwnershipRow(
        problem_key=PROBLEM_SCENE_BOUNDARIES,
        description="Poor or overlong scene boundaries",
        owner=OWNER_SEGMENTER,
        label="Segmenter",
        stage_key="segments",
        node_types=("segment.run",),
        issue_types=("segmentation_defect",),
    ),
    OwnershipRow(
        problem_key=PROBLEM_VISUAL_CONCEPT,
        description="Visual concept does not represent narration",
        owner=OWNER_SCENE_DIRECTOR,
        label="Scene Director",
        stage_key="scenes",
        node_types=("scenes.blueprint",),
        # continuity is director-level; visual_mismatch uses the image row by
        # default and opts into this row via observed.problem_key.
        issue_types=("continuity_break",),
    ),
    OwnershipRow(
        problem_key=PROBLEM_IMAGE_SUBJECT_STYLE,
        description="Wrong character, object, or style in a still",
        owner=OWNER_IMAGE,
        label="Image Generator",
        stage_key="images",
        node_types=("storyboard.generate",),
        issue_types=("visual_mismatch",),
    ),
    OwnershipRow(
        problem_key=PROBLEM_MOTION,
        description="Motion deformation, instability, poor animation",
        owner=OWNER_VIDEO,
        label="Video Generator",
        stage_key="videos",
        node_types=("animator.generate",),
        issue_types=("motion_defect",),
    ),
    OwnershipRow(
        problem_key=PROBLEM_CAPTION_BRANDING,
        description="Caption outside safe area, branding missing",
        owner=OWNER_COMPOSER,
        label="Composer",
        stage_key="composer",
        # Captions collapse into the Composer stage (stage_projection SIDE_BRANCH).
        node_types=("assemble.project", "captions.generate", "timeline.project"),
        issue_types=("policy_violation",),
    ),
    OwnershipRow(
        problem_key=PROBLEM_RENDER_CODEC,
        description="Render corruption, codec failure",
        owner=OWNER_EXPORT,
        label="Export",
        stage_key="export",
        node_types=("export.video",),
        issue_types=("technical_defect",),
    ),
)

OWNERSHIP_BY_PROBLEM: dict[str, OwnershipRow] = {
    row.problem_key: row for row in OWNERSHIP_TABLE
}

# Default issue_type → problem_key. Built from the table so the two cannot drift.
ISSUE_TYPE_DEFAULT_PROBLEM: dict[str, str] = {}
for _row in OWNERSHIP_TABLE:
    for _issue_type in _row.issue_types:
        # First declaration wins if a type ever appears twice (it should not).
        ISSUE_TYPE_DEFAULT_PROBLEM.setdefault(_issue_type, _row.problem_key)

# Technical check_id → problem_key refinements (step 7.1). Table-driven so
# adapters never grow codec/resolution if-chains.
CHECK_ID_PROBLEM: dict[str, str] = {
    # Codec / container corruption is the §12.2 Export row.
    "readable_media": PROBLEM_RENDER_CODEC,
    # Missing or wrong-shaped stills → Image (early image gate).
    "file_exists": PROBLEM_IMAGE_SUBJECT_STYLE,
    "resolution": PROBLEM_IMAGE_SUBJECT_STYLE,
    "aspect_ratio": PROBLEM_IMAGE_SUBJECT_STYLE,
    "expected_artifact_count": PROBLEM_IMAGE_SUBJECT_STYLE,
    # Clip length / frame defects → Video.
    "duration": PROBLEM_MOTION,
    "frame_count": PROBLEM_MOTION,
    # Missing audio track on a deliverable is often Export remux, but voice
    # defects are TTS; audio_presence on a final render is Export.
    "audio_presence": PROBLEM_RENDER_CODEC,
    # Step 16.3 — a script under the Channel's virality threshold is a weak
    # hook, which the §12.2 table hands to Script. Mapped explicitly rather
    # than leaning on the script_defect default so the analyzer's ownership
    # survives any future re-reading of that issue type.
    "viral_score": PROBLEM_SCRIPT_CONTENT,
}

# Preferred node type → owner (for reverse lookup / graph matching in 8.2).
NODE_TYPE_OWNER: dict[str, str] = {}
for _row in OWNERSHIP_TABLE:
    for _node_type in _row.node_types:
        NODE_TYPE_OWNER.setdefault(_node_type, _row.owner)


class UnknownRoutingProblem(ValueError):
    """Raised when a problem_key is not in the §12.2 ownership table."""

    def __init__(self, problem_key: str):
        self.problem_key = problem_key
        super().__init__(
            f"Unknown repair routing problem {problem_key!r}; "
            f"known: {', '.join(PROBLEM_KEYS)}"
        )


class UnroutableIssue(ValueError):
    """Raised when an issue cannot be mapped to any ownership row."""

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        self.details = dict(details or {})
        super().__init__(message)


@dataclass(frozen=True)
class RoutingDecision:
    """Result of routing one issue (or problem key) to its owning node class.

    ``node_types`` is the ordered preference list of registry type keys the
    Repair Router (8.2) should match against the Job graph. ``routed_to_node_type``
    is the first preference — the value RepairHistoryEntry records when no graph
    match has been resolved yet.
    """

    problem_key: str
    owner: str
    label: str
    stage_key: str
    node_types: tuple[str, ...]
    description: str
    # How the problem_key was chosen.
    source: str
    issue_type: str | None = None
    check_id: str | None = None

    @property
    def routed_to_node_type(self) -> str:
        """Primary registry type for history / default re-run target."""
        return self.node_types[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_key": self.problem_key,
            "owner": self.owner,
            "label": self.label,
            "stage_key": self.stage_key,
            "node_types": list(self.node_types),
            "routed_to_node_type": self.routed_to_node_type,
            "description": self.description,
            "source": self.source,
            "issue_type": self.issue_type,
            "check_id": self.check_id,
        }


def _decision_from_row(
    row: OwnershipRow,
    *,
    source: str,
    issue_type: str | None = None,
    check_id: str | None = None,
) -> RoutingDecision:
    return RoutingDecision(
        problem_key=row.problem_key,
        owner=row.owner,
        label=row.label,
        stage_key=row.stage_key,
        node_types=row.node_types,
        description=row.description,
        source=source,
        issue_type=issue_type,
        check_id=check_id,
    )


def route_problem(problem_key: str) -> RoutingDecision:
    """Look up the ownership row for a §12.2 problem key.

    Table-driven: one dict lookup, no conditionals.
    """
    key = str(problem_key or "").strip()
    row = OWNERSHIP_BY_PROBLEM.get(key)
    if row is None:
        raise UnknownRoutingProblem(key)
    return _decision_from_row(row, source="problem_key")


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    # Pydantic models expose model_dump / attribute access.
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        payload = dump(mode="json")
        if isinstance(payload, Mapping):
            return payload
    return {}


def _field(issue: Any, name: str, default: Any = None) -> Any:
    if isinstance(issue, Mapping):
        return issue.get(name, default)
    return getattr(issue, name, default)


def resolve_problem_key(issue: Any) -> tuple[str, str]:
    """Derive ``(problem_key, source)`` for a ReviewIssue-like object.

    Priority (first hit wins):

    1. ``observed.problem_key`` / ``observed.routing_problem``
    2. ``check_id`` via ``CHECK_ID_PROBLEM``
    3. ``issue_type`` via ``ISSUE_TYPE_DEFAULT_PROBLEM``
    """
    observed = _as_mapping(_field(issue, "observed", {}))
    explicit = observed.get("problem_key") or observed.get("routing_problem")
    if explicit is not None:
        key = str(explicit).strip()
        if key:
            if key not in OWNERSHIP_BY_PROBLEM:
                raise UnknownRoutingProblem(key)
            return key, "observed"

    check_id_raw = _field(issue, "check_id", None)
    check_id = str(check_id_raw).strip() if check_id_raw else ""
    if check_id and check_id in CHECK_ID_PROBLEM:
        return CHECK_ID_PROBLEM[check_id], "check_id"

    issue_type_raw = _field(issue, "issue_type", None)
    issue_type = str(issue_type_raw or "").strip()
    if not issue_type:
        raise UnroutableIssue(
            "issue has no issue_type and no observed.problem_key",
            details={"issue": _as_mapping(issue) or None},
        )
    problem = ISSUE_TYPE_DEFAULT_PROBLEM.get(issue_type)
    if problem is None:
        raise UnroutableIssue(
            f"No ownership mapping for issue_type {issue_type!r}",
            details={"issue_type": issue_type, "known_issue_types": list(ISSUE_TYPES)},
        )
    return problem, "issue_type"


def route_issue(issue: Any) -> RoutingDecision:
    """Route a ReviewIssue (model, draft, or mapping) to its owning node class.

    Pure policy: does not touch the store, engine, or providers. Downstream
    repair execution (8.2) resolves ``node_types`` against the Job graph.
    """
    problem_key, source = resolve_problem_key(issue)
    row = OWNERSHIP_BY_PROBLEM[problem_key]
    issue_type_raw = _field(issue, "issue_type", None)
    issue_type = str(issue_type_raw).strip() if issue_type_raw else None
    check_id_raw = _field(issue, "check_id", None)
    check_id = str(check_id_raw).strip() if check_id_raw else None
    return _decision_from_row(
        row,
        source=source,
        issue_type=issue_type or None,
        check_id=check_id or None,
    )


def ownership_rows() -> list[dict[str, Any]]:
    """Public snapshot of the §12.2 table for docs / UI / tests."""
    return [
        {
            "problem_key": row.problem_key,
            "description": row.description,
            "owner": row.owner,
            "label": row.label,
            "stage_key": row.stage_key,
            "node_types": list(row.node_types),
            "issue_types": list(row.issue_types),
        }
        for row in OWNERSHIP_TABLE
    ]


def assert_routing_table_complete() -> None:
    """Internal invariant: table covers every problem key and every issue type."""
    keys = {row.problem_key for row in OWNERSHIP_TABLE}
    if keys != set(PROBLEM_KEYS):
        raise AssertionError(
            f"OWNERSHIP_TABLE problem keys {sorted(keys)} != PROBLEM_KEYS {list(PROBLEM_KEYS)}"
        )
    owners = {row.owner for row in OWNERSHIP_TABLE}
    if owners != set(OWNERS):
        raise AssertionError(
            f"OWNERSHIP_TABLE owners {sorted(owners)} != OWNERS {list(OWNERS)}"
        )
    mapped_types = set(ISSUE_TYPE_DEFAULT_PROBLEM)
    missing = set(ISSUE_TYPES) - mapped_types
    if missing:
        raise AssertionError(
            f"issue_types without default ownership: {sorted(missing)}"
        )
    for row in OWNERSHIP_TABLE:
        if not row.node_types:
            raise AssertionError(f"{row.problem_key} has empty node_types")
        if row.owner not in OWNERS:
            raise AssertionError(f"{row.problem_key} has unknown owner {row.owner!r}")


# Fail fast at import if the table drifts.
assert_routing_table_complete()


__all__ = [
    "CHECK_ID_PROBLEM",
    "ISSUE_TYPE_DEFAULT_PROBLEM",
    "NODE_TYPE_OWNER",
    "OWNERSHIP_BY_PROBLEM",
    "OWNERSHIP_TABLE",
    "OWNERS",
    "OWNER_COMPOSER",
    "OWNER_EXPORT",
    "OWNER_IMAGE",
    "OWNER_SCENE_DIRECTOR",
    "OWNER_SCRIPT",
    "OWNER_SEGMENTER",
    "OWNER_TIMING",
    "OWNER_TTS",
    "OWNER_VIDEO",
    "PROBLEM_ALIGNMENT",
    "PROBLEM_CAPTION_BRANDING",
    "PROBLEM_IMAGE_SUBJECT_STYLE",
    "PROBLEM_KEYS",
    "PROBLEM_MOTION",
    "PROBLEM_PRONUNCIATION_VOICE",
    "PROBLEM_RENDER_CODEC",
    "PROBLEM_SCENE_BOUNDARIES",
    "PROBLEM_SCRIPT_CONTENT",
    "PROBLEM_VISUAL_CONCEPT",
    "OwnershipRow",
    "RoutingDecision",
    "UnknownRoutingProblem",
    "UnroutableIssue",
    "assert_routing_table_complete",
    "ownership_rows",
    "resolve_problem_key",
    "route_issue",
    "route_problem",
]
