"""Re-segmentation rule — contracts.md §4.

When the segmenter reruns, each resulting speech scene either:

1. **rebinds** to an existing scene id when its span is materially unchanged
   (artifacts and open issues carry over), or
2. **supersedes** one or more prior scenes (prior artifacts marked superseded;
   open issues re-targeted to the successor), or
3. is **new** (no inherited artifacts or issues).

Rebind threshold (defaults; configurable on the segmenter service):
  * temporal IoU of ``[start, end]`` ≥ ``REBIND_IOU_THRESHOLD`` (0.6)
  * longer span ≤ ``REBIND_MAX_SPAN_RATIO`` × shorter (1.5)

Ties go to the highest IoU; a prior scene rebinds to at most one successor.
No open issue or artifact may remain bound to a scene id that no longer resolves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from scriptase.scenes.models import Scene
from scriptase.scenes.store import (
    active_scenes_for_job,
    create_scene,
    mark_superseded,
    update_scene_span,
)

# contracts.md §4 / §14 — change only with a migration note.
REBIND_IOU_THRESHOLD = 0.6
REBIND_MAX_SPAN_RATIO = 1.5


@dataclass(frozen=True)
class ResegmentConfig:
    """Configurable rebind thresholds (segmenter service defaults)."""

    iou_threshold: float = REBIND_IOU_THRESHOLD
    max_span_ratio: float = REBIND_MAX_SPAN_RATIO


@dataclass(frozen=True)
class SegmentCandidate:
    """One speech segment produced by the segmenter algorithm."""

    start: float
    end: float
    segment_words: str = ""
    duration: float | None = None
    # Optional passthrough (index, break_reason, …) — not identity.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def span_duration(self) -> float:
        if self.duration is not None:
            return float(self.duration)
        return max(0.0, float(self.end) - float(self.start))


@dataclass
class ResegmentDecision:
    """What happened to one candidate relative to prior scenes."""

    action: str  # "rebind" | "supersede" | "new"
    scene: Scene
    prior_ids: list[str] = field(default_factory=list)
    candidate_index: int = 0


@dataclass
class ResegmentResult:
    """Outcome of applying the re-segmentation rule for one job."""

    job_id: str
    scenes: list[Scene]
    decisions: list[ResegmentDecision]
    invalidated_ids: list[str]  # priors with no successor
    # prior_id → successor_id (rebind keeps same id; supersede maps old → new)
    id_map: dict[str, str]
    config: ResegmentConfig


def temporal_iou(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    """Intersection-over-union of two closed time intervals."""
    a0, a1 = float(start_a), float(end_a)
    b0, b1 = float(start_b), float(end_b)
    if a1 < a0 or b1 < b0:
        return 0.0
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    if inter <= 0.0:
        return 0.0
    union = (a1 - a0) + (b1 - b0) - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def span_ratio(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    """Longer span / shorter span (≥ 1 when both have positive length)."""
    len_a = max(0.0, float(end_a) - float(start_a))
    len_b = max(0.0, float(end_b) - float(start_b))
    if len_a <= 0.0 and len_b <= 0.0:
        return 1.0
    if len_a <= 0.0 or len_b <= 0.0:
        return float("inf")
    return max(len_a, len_b) / min(len_a, len_b)


def is_rebind_eligible(
    prior: Scene,
    candidate: SegmentCandidate,
    *,
    config: ResegmentConfig | None = None,
) -> bool:
    """True when the candidate may rebind to ``prior`` under the threshold rule."""
    cfg = config or ResegmentConfig()
    iou = temporal_iou(prior.start, prior.end, candidate.start, candidate.end)
    if iou < cfg.iou_threshold:
        return False
    ratio = span_ratio(prior.start, prior.end, candidate.start, candidate.end)
    return ratio <= cfg.max_span_ratio


def candidate_from_segment(segment: Mapping[str, Any]) -> SegmentCandidate | None:
    """Build a candidate from a segmenter segment dict; skip fillers."""
    if segment.get("is_filler"):
        return None
    try:
        start = float(segment["start"])
        end = float(segment["end"])
    except (KeyError, TypeError, ValueError):
        return None
    words = segment.get("words") or segment.get("segment_words") or ""
    duration = segment.get("duration")
    try:
        dur = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        dur = None
    meta = {
        key: segment[key]
        for key in ("index", "break_reason", "word_count", "is_filler")
        if key in segment
    }
    return SegmentCandidate(
        start=start,
        end=end,
        segment_words=str(words),
        duration=dur,
        meta=meta,
    )


def candidates_from_segments(
    segments: Sequence[Mapping[str, Any]],
) -> list[SegmentCandidate]:
    """Speech segments only, in input order."""
    out: list[SegmentCandidate] = []
    for seg in segments or ():
        if not isinstance(seg, Mapping):
            continue
        cand = candidate_from_segment(seg)
        if cand is not None:
            out.append(cand)
    return out


def _match_rebinds(
    priors: list[Scene],
    candidates: list[SegmentCandidate],
    config: ResegmentConfig,
) -> dict[int, int]:
    """Return candidate_index → prior_index for rebind pairs (greedy max IoU)."""
    pairs: list[tuple[float, int, int]] = []
    for ci, cand in enumerate(candidates):
        for pi, prior in enumerate(priors):
            if not is_rebind_eligible(prior, cand, config=config):
                continue
            iou = temporal_iou(prior.start, prior.end, cand.start, cand.end)
            pairs.append((iou, ci, pi))
    # Highest IoU first; stable tie-break by candidate then prior index.
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))

    assigned_candidates: set[int] = set()
    assigned_priors: set[int] = set()
    mapping: dict[int, int] = {}
    for _iou, ci, pi in pairs:
        if ci in assigned_candidates or pi in assigned_priors:
            continue
        mapping[ci] = pi
        assigned_candidates.add(ci)
        assigned_priors.add(pi)
    return mapping


def _best_overlap_candidate(
    prior: Scene,
    candidates: list[SegmentCandidate],
    *,
    skip_candidate_indices: set[int],
) -> int | None:
    """Index of the candidate with highest IoU > 0, or None."""
    best_i: int | None = None
    best_iou = 0.0
    for ci, cand in enumerate(candidates):
        if ci in skip_candidate_indices:
            continue
        iou = temporal_iou(prior.start, prior.end, cand.start, cand.end)
        if iou > best_iou:
            best_iou = iou
            best_i = ci
    return best_i if best_iou > 0.0 else None


def apply_resegmentation(
    job_id: str,
    candidates: Sequence[SegmentCandidate] | Sequence[Mapping[str, Any]],
    *,
    config: ResegmentConfig | None = None,
    prior_scenes: Sequence[Scene] | None = None,
    persist: bool = True,
    apply_bindings: bool = True,
) -> ResegmentResult:
    """Apply the re-segmentation rule and optionally persist + clean bindings.

    When ``prior_scenes`` is None, loads active scenes for ``job_id`` from the
    scene store. When ``persist`` is False, still allocates logical decisions
    but only writes when creating/updating via the store helpers is required
    for real ids — callers that need pure dry-run should pass empty priors and
    handle persistence themselves. For normal use leave ``persist=True``.

    When ``apply_bindings`` is True, retires artifacts and re-targets open
    issues so nothing stays bound to a scene that no longer resolves.
    """
    cfg = config or ResegmentConfig()
    job_id = str(job_id).strip()
    if not job_id:
        raise ValueError("job_id is required")

    # Normalize candidates.
    if candidates and isinstance(candidates[0], SegmentCandidate):
        cands = list(candidates)  # type: ignore[arg-type]
    else:
        cands = candidates_from_segments(candidates)  # type: ignore[arg-type]

    if prior_scenes is None:
        priors = active_scenes_for_job(job_id) if persist else []
    else:
        priors = [p for p in prior_scenes if p.superseded_by is None]

    rebind_map = _match_rebinds(priors, cands, cfg)  # cand → prior idx
    rebind_prior_indices = set(rebind_map.values())
    rebind_cand_indices = set(rebind_map.keys())

    # Prior → candidate that will supersede it (non-rebind, IoU > 0).
    supersede_owners: dict[int, list[int]] = {}  # cand idx → [prior idx, …]
    unmatched_prior_indices: list[int] = []
    for pi, prior in enumerate(priors):
        if pi in rebind_prior_indices:
            continue
        owner = _best_overlap_candidate(
            prior, cands, skip_candidate_indices=rebind_cand_indices
        )
        if owner is None:
            unmatched_prior_indices.append(pi)
        else:
            supersede_owners.setdefault(owner, []).append(pi)

    decisions: list[ResegmentDecision] = []
    scenes: list[Scene] = []
    id_map: dict[str, str] = {}
    # Track newly created scene ids per candidate for supersede pointers.
    scene_for_candidate: dict[int, Scene] = {}

    for ci, cand in enumerate(cands):
        ordinal = ci
        if ci in rebind_map:
            prior = priors[rebind_map[ci]]
            if persist:
                scene = update_scene_span(
                    prior.id,
                    ordinal=ordinal,
                    start=cand.start,
                    end=cand.end,
                    duration=cand.span_duration,
                    segment_words=cand.segment_words,
                )
            else:
                scene = prior.model_copy(
                    update={
                        "ordinal": ordinal,
                        "start": cand.start,
                        "end": cand.end,
                        "duration": cand.span_duration,
                        "segment_words": cand.segment_words,
                    }
                )
            id_map[prior.id] = scene.id
            decision = ResegmentDecision(
                action="rebind",
                scene=scene,
                prior_ids=[prior.id],
                candidate_index=ci,
            )
        else:
            if persist:
                scene = create_scene(
                    job_id=job_id,
                    ordinal=ordinal,
                    start=cand.start,
                    end=cand.end,
                    duration=cand.span_duration,
                    segment_words=cand.segment_words,
                )
            else:
                # Dry-run placeholder id — not persisted.
                from scriptase.scenes.models import SCENE_SCHEMA_VERSION

                scene = Scene(
                    id=f"scn_DRY{ci:03d}" if ci < 1000 else f"scn_D{ci:05d}"[:10],
                    schema_version=SCENE_SCHEMA_VERSION,
                    job_id=job_id,
                    ordinal=ordinal,
                    start=cand.start,
                    end=cand.end,
                    duration=cand.span_duration,
                    segment_words=cand.segment_words,
                )
            prior_ids: list[str] = []
            for pi in supersede_owners.get(ci, []):
                prior = priors[pi]
                prior_ids.append(prior.id)
                if persist:
                    mark_superseded(prior.id, scene.id)
                id_map[prior.id] = scene.id
            action = "supersede" if prior_ids else "new"
            decision = ResegmentDecision(
                action=action,
                scene=scene,
                prior_ids=prior_ids,
                candidate_index=ci,
            )
        scene_for_candidate[ci] = decision.scene
        decisions.append(decision)
        scenes.append(decision.scene)

    invalidated_ids: list[str] = []
    for pi in unmatched_prior_indices:
        prior = priors[pi]
        invalidated_ids.append(prior.id)
        if persist:
            # Self-tombstone: no temporal successor; scene no longer resolves.
            mark_superseded(prior.id, prior.id)

    if persist and apply_bindings:
        _apply_binding_cleanup(
            job_id=job_id,
            decisions=decisions,
            invalidated_ids=invalidated_ids,
            active_scene_ids=[s.id for s in scenes],
        )

    return ResegmentResult(
        job_id=job_id,
        scenes=scenes,
        decisions=decisions,
        invalidated_ids=invalidated_ids,
        id_map=id_map,
        config=cfg,
    )


def _apply_binding_cleanup(
    *,
    job_id: str,
    decisions: list[ResegmentDecision],
    invalidated_ids: list[str],
    active_scene_ids: list[str],
) -> None:
    """Retire artifacts and re-target/close open issues for dead scene ids."""
    from scriptase.artifacts.store import retire_artifacts_for_scene
    from scriptase.review.open_issues import (
        close_issues_for_scene,
        retarget_issues,
    )

    # Superseded priors: artifacts retired; issues re-targeted to successor.
    for decision in decisions:
        if decision.action != "supersede":
            continue
        for prior_id in decision.prior_ids:
            retire_artifacts_for_scene(job_id, prior_id)
            retarget_issues(job_id, prior_id, decision.scene.id)

    # Fully invalidated priors: artifacts retired; open issues closed.
    for prior_id in invalidated_ids:
        retire_artifacts_for_scene(job_id, prior_id)
        close_issues_for_scene(job_id, prior_id, reason="scene_invalidated")

    # Safety net: nothing open remains bound to a non-resolving scene.
    from scriptase.review.open_issues import assert_no_open_issue_on_dead_scenes
    from scriptase.artifacts.store import assert_no_active_artifact_on_dead_scenes

    assert_no_open_issue_on_dead_scenes(job_id, active_scene_ids)
    assert_no_active_artifact_on_dead_scenes(job_id, active_scene_ids)


def stamp_segments_with_scene_ids(
    segments: list[dict[str, Any]],
    scenes: Sequence[Scene],
) -> list[dict[str, Any]]:
    """Attach ``scene_id`` / ``ordinal`` onto speech segments; leave fillers alone.

    Speech segments receive ids in order (matching ``scenes`` ordinals). Filler
    segments keep their structure and gain no scene identity.
    """
    speech_iter = iter(scenes)
    stamped: list[dict[str, Any]] = []
    for seg in segments:
        item = dict(seg)
        if item.get("is_filler"):
            stamped.append(item)
            continue
        try:
            scene = next(speech_iter)
        except StopIteration:
            stamped.append(item)
            continue
        item["scene_id"] = scene.id
        item["ordinal"] = scene.ordinal
        # Keep array index for presentation; identity is scene_id.
        item["index"] = scene.ordinal
        stamped.append(item)
    return stamped


__all__ = [
    "REBIND_IOU_THRESHOLD",
    "REBIND_MAX_SPAN_RATIO",
    "ResegmentConfig",
    "SegmentCandidate",
    "ResegmentDecision",
    "ResegmentResult",
    "apply_resegmentation",
    "candidate_from_segment",
    "candidates_from_segments",
    "is_rebind_eligible",
    "span_ratio",
    "stamp_segments_with_scene_ids",
    "temporal_iou",
]
