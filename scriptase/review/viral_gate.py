"""Turn a script virality score into a routed ReviewIssue — step 16.3.

Step 16.1 built the scorer and 16.2 gave it a node. Both stop at *reporting*: a
weak hook produced a number on a port and nothing acted on it, so the run
carried on into TTS, images and video before anyone could see the script was
the problem. This module is the deciding half. It compares the score the
analyzer produced against the Channel's threshold and, when the script falls
short, writes the ReviewIssue that the step-11.3 Repair Router routes back to
Script.

Three things this module deliberately does *not* do:

**It does not score.** ``ViralScore.model_validate`` round-trips the frozen
16.1 payload and every number here comes from that document. A second copy of
the arithmetic would drift the moment ``SCORER_VERSION`` moved.

**It does not fail the run.** A low score is a finding, not an error. The
analyzer node stays advisory (``continue_error`` in the Full Video template);
what stops a Job is the checkpoint the Assisted-mode policy resolves, not an
exception thrown from here.

**It does not invent a threshold.** With no ``review_policy.thresholds``
entry the gate is off and no issue is ever written. A default bar would start
failing every Channel that has never heard of virality scoring.

The inverse of emission matters as much as emission: a script that has been
repaired and now clears the bar resolves its open issue. Without that the
Script stage would keep showing a defect that no longer exists, because
``emit_review_issues`` only ever *reuses* an open issue and has no reason to
close one.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from scriptase.review.models import ReviewIssueDraft

# The machine id this gate stamps on every issue it raises. Routed explicitly
# through ``CHECK_ID_PROBLEM`` so ownership does not depend on the
# ``script_defect`` issue-type default continuing to mean "Script".
VIRAL_CHECK_ID = "viral_score"

# Accepted threshold keys on ``review_policy.thresholds``. The block is an open
# map by contract (§4), the same way ``safe_degradation`` and
# ``max_repairs_per_scene`` already live there.
THRESHOLD_KEYS: tuple[str, ...] = ("viral_score_min", "min_viral_score")

# Deficit below the threshold → severity. ``critical`` is never produced: an
# Automatic-mode Job runs unattended by design and a soft content judgement is
# not grounds to stop it (``should_pause_for_escalation``).
_SEVERITY_BANDS: tuple[tuple[int, str], ...] = (
    (20, "high"),
    (10, "medium"),
    (0, "low"),
)

# Dimensions this far below their own weight-adjusted potential are what the
# repair instruction names. Keeps the instruction about the two or three things
# that actually cost the script points instead of listing all six.
_WEAK_DIMENSION_SCORE = 0.6
_MAX_NAMED_DIMENSIONS = 3


def viral_threshold(thresholds: Mapping[str, Any] | None) -> int | None:
    """Minimum acceptable score from a ``review_policy.thresholds`` map.

    Returns None when unset, unparseable, or out of the 0-100 range the scorer
    produces — a malformed Channel field switches the gate off rather than
    gating every script against nonsense.
    """
    if not isinstance(thresholds, Mapping):
        return None
    for key in THRESHOLD_KEYS:
        if key not in thresholds or thresholds[key] is None:
            continue
        try:
            value = int(float(thresholds[key]))
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 100:
            return value
    return None


def _review_policy(snapshot: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {}
    review = snapshot.get("review_policy")
    if not isinstance(review, Mapping):
        dump = getattr(review, "model_dump", None)
        review = dump(mode="json") if callable(dump) else None
    return review if isinstance(review, Mapping) else {}


def threshold_from_snapshot(snapshot: Mapping[str, Any] | None) -> int | None:
    """Read the threshold straight off a Channel snapshot."""
    thresholds = _review_policy(snapshot).get("thresholds")
    return viral_threshold(thresholds if isinstance(thresholds, Mapping) else None)


def threshold_for_job(job_id: str) -> int | None:
    """Threshold from the Job's Channel snapshot, or None.

    Reads the snapshot the Job froze at creation rather than the live Channel:
    a Job is judged against the policy it was created under, exactly as the
    repair budget and checkpoint list already are.
    """
    job_id = str(job_id or "").strip()
    if not job_id:
        return None
    try:
        from scriptase.jobs.store import get_job

        job = get_job(job_id)
    except Exception:
        return None
    snapshot = getattr(job, "channel_snapshot", None)
    if snapshot is None and isinstance(job, Mapping):
        snapshot = job.get("channel_snapshot")
    return threshold_from_snapshot(snapshot if isinstance(snapshot, Mapping) else None)


def _severity(deficit: int) -> str:
    for floor, severity in _SEVERITY_BANDS:
        if deficit >= floor:
            return severity
    return "low"


def _weak_dimensions(dimensions: Sequence[Any]) -> list[dict[str, Any]]:
    """Under-performing dimensions, worst first, with their reason codes."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for raw in dimensions:
        if not isinstance(raw, Mapping):
            continue
        dimension_id = str(raw.get("id") or "").strip()
        if not dimension_id:
            continue
        try:
            value = float(raw.get("score"))
        except (TypeError, ValueError):
            continue
        if value >= _WEAK_DIMENSION_SCORE:
            continue
        # Deduped, order preserved. A dimension can measure the same fault on
        # several sections — ``balance`` reports ``section_missing`` once per
        # missing section — and repeating the code adds nothing while eating
        # the instruction's 500-character budget.
        codes: list[str] = []
        for reason in raw.get("reasons") or []:
            if not isinstance(reason, Mapping):
                continue
            if str(reason.get("impact") or "") != "negative":
                continue
            code = str(reason.get("code") or "").strip()
            if code and code not in codes:
                codes.append(code)
        scored.append((value, {"id": dimension_id, "score": value, "reasons": codes}))
    # Weakest first; dimension id breaks ties so the issue text is stable for a
    # given score and the emission identity does not churn between runs.
    scored.sort(key=lambda item: (item[0], item[1]["id"]))
    return [entry for _, entry in scored[:_MAX_NAMED_DIMENSIONS]]


def _instruction(weak: Sequence[Mapping[str, Any]]) -> str:
    """Bounded repair guidance naming the dimensions that lost the points.

    Assembled from dimension ids and reason codes — the structured fields the
    scorer emitted — so nothing here is generated prose about the script
    itself (contracts §7).
    """
    if not weak:
        return "Revise the script to raise its virality score."
    parts = []
    for entry in weak:
        codes = ", ".join(entry.get("reasons") or []) or "below target"
        parts.append(f"{entry['id']} ({codes})")
    return "Revise the script to strengthen: " + "; ".join(parts) + "."


def _parse(score_document: Mapping[str, Any] | None) -> Any | None:
    """Round-trip the frozen 16.1 payload, or None when it is not one.

    A document the contract rejects is a scorer or provider bug. Callers must
    treat that as *unmeasured*, never as a pass and never as a script defect —
    it would either blame the script for someone else's bug or quietly clear a
    real finding.
    """
    from scriptase.modules.viral.models import ViralScore

    if not isinstance(score_document, Mapping) or not score_document:
        return None
    try:
        return ViralScore.model_validate(dict(score_document))
    except Exception:
        return None


def draft_for_score(
    score_document: Mapping[str, Any] | None,
    *,
    job_id: str,
    threshold: int,
    target_node_id: str | None = None,
) -> ReviewIssueDraft | None:
    """Build the ReviewIssue draft for a score below ``threshold``, or None.

    ``score_document`` is the frozen 16.1 ``ViralScore`` payload — the value
    the node publishes under ``score.viral_score``.
    """
    score = _parse(score_document)
    if score is None or score.score >= threshold:
        return None

    deficit = threshold - score.score
    weak = _weak_dimensions([d.model_dump(mode="json") for d in score.dimensions])
    return ReviewIssueDraft(
        job_id=job_id,
        target_node_id=target_node_id,
        issue_type="script_defect",
        severity=_severity(deficit),
        # The scorer is deterministic: the measurement is certain even though
        # the judgement it supports is a soft one.
        confidence=1.0,
        reason=(
            f"Virality score {score.score} is below the Channel minimum "
            f"{threshold} (band: {score.band})"
        ),
        suggested_action="re-prompt",
        repair_instruction=_instruction(weak),
        check_id=VIRAL_CHECK_ID,
        observed={
            "score": score.score,
            "band": score.band,
            "scorer": score.scorer,
            "scorer_version": score.scorer_version,
            "weak_dimensions": weak,
        },
        expected={"min_score": threshold},
    )


def _open_viral_issues(job_id: str, target_node_id: str | None) -> list[Any]:
    from scriptase.review.store import list_issues

    return [
        issue
        for issue in list_issues(job_id=job_id, open_only=True)
        if getattr(issue, "check_id", None) == VIRAL_CHECK_ID
        and (target_node_id is None or issue.target_node_id == target_node_id)
    ]


def gate_script_score(
    score_document: Mapping[str, Any] | None,
    *,
    job_id: str,
    target_node_id: str | None = None,
    threshold: int | None = None,
) -> dict[str, Any]:
    """Apply the Channel threshold to a score and persist the verdict.

    Returns ``{"threshold": int|None, "passed": bool|None, "issue_ids": [...]}``.
    ``threshold`` of None means the Channel never set one, so the gate is off
    and ``passed`` is None — "not measured" rather than "passed", which is the
    distinction the Production panel renders.
    """
    job_id = str(job_id or "").strip()
    if threshold is None:
        threshold = threshold_for_job(job_id)
    if not job_id or threshold is None:
        return {"threshold": threshold, "passed": None, "issue_ids": []}

    # A payload the frozen contract rejects is unmeasured, not passed. Treating
    # it as a pass here would silently resolve a real open finding on the
    # strength of a scorer bug.
    if _parse(score_document) is None:
        return {"threshold": threshold, "passed": None, "issue_ids": []}

    draft = draft_for_score(
        score_document,
        job_id=job_id,
        threshold=threshold,
        target_node_id=target_node_id,
    )

    if draft is None:
        # Above the bar. Close anything this gate left open for the same node
        # so a repaired script stops reporting a stale defect the moment it is
        # re-scored — `emit_review_issues` only ever reuses, never closes.
        resolved = _resolve_open(job_id, target_node_id)
        return {"threshold": threshold, "passed": True, "issue_ids": resolved}

    from scriptase.review.emission import emit_review_issues

    issues = emit_review_issues(job_id, semantic=[draft])
    return {
        "threshold": threshold,
        "passed": False,
        "issue_ids": [issue.id for issue in issues],
    }


def _resolve_open(job_id: str, target_node_id: str | None) -> list[str]:
    """Mark this gate's open issues resolved. Best-effort, like every other
    Job-linking write in the review package: the score itself is already
    durable on the execution record."""
    try:
        from scriptase.review.store import update_issue

        resolved: list[str] = []
        for issue in _open_viral_issues(job_id, target_node_id):
            update_issue(issue.id, status="resolved")
            resolved.append(issue.id)
        return resolved
    except Exception:
        return []


__all__ = [
    "THRESHOLD_KEYS",
    "VIRAL_CHECK_ID",
    "draft_for_score",
    "gate_script_score",
    "threshold_for_job",
    "threshold_from_snapshot",
    "viral_threshold",
]
