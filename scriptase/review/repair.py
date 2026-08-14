"""Targeted repair with budgets and escalation (step 8.2 / product §12.5).

Repair the **smallest responsible scope** — one issue, one scene id (when
present), one owning node type from the §12.2 table (step 8.1). Never
regenerate every scene because one failed. Never leave a repair loop unbounded.

Control surface (all required by §12.5 / contracts.md §12):

* Maximum attempts per issue (``review_policy.max_repairs``)
* Maximum generations and cost per Job (channel ``budget`` via step 3.5
  :func:`~scriptase.jobs.budget.check_budget_preflight`)
* Escalation to human review on low confidence or repeated failure
* Configured safe degradation (e.g. keep the still when video keeps failing)

This module is pure policy + durable status updates. Step 8.3 owns fallback
instance chains; step 8.4 owns ``RepairHistoryEntry`` persistence (recorded
from :func:`apply_repair_decision` for terminal decisions and from
:func:`record_repair_attempt` after a provider re-run); step 9.1 wires
Automatic mode end-to-end. The engine run body built here reuses the ported
run modes only — no second execution path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

from scriptase.channels.models import Budget, ReviewPolicy
from scriptase.jobs.budget import (
    PROVIDER_NODE_TYPES,
    BudgetExceededError,
    budget_from_job,
    check_budget_preflight,
    spent_from_job,
)
from scriptase.jobs.models import BudgetSpent, Job
from scriptase.review.models import OPEN_STATUSES, ReviewIssue
from scriptase.review.policy import (
    OWNER_VIDEO,
    PROBLEM_MOTION,
    RoutingDecision,
    UnroutableIssue,
    route_issue,
)
from scriptase.review.store import get_issue, list_issues, update_issue

# ---------------------------------------------------------------------------
# Error / status codes (contracts.md §13.3 + §6 status_reason)
# ---------------------------------------------------------------------------

REPAIR_LIMIT_REACHED = "REPAIR_LIMIT_REACHED"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
LOW_CONFIDENCE = "LOW_CONFIDENCE"
SAFE_DEGRADATION = "SAFE_DEGRADATION"
SUGGESTED_ESCALATE = "SUGGESTED_ESCALATE"
SUGGESTED_ACCEPT = "SUGGESTED_ACCEPT"
ISSUE_NOT_OPEN = "ISSUE_NOT_OPEN"
UNROUTABLE = "UNROUTABLE"

# Job.status_reason codes used when a repair cycle stops the Job.
STATUS_REASON_BUDGET = "budget"
STATUS_REASON_REPAIR_LIMIT = "repair_limit"
STATUS_REASON_ESCALATION = "critical_issue"

RepairAction = Literal[
    "repair",
    "escalate",
    "degrade",
    "accept",
    "refuse_budget",
    "skip",
]

# Owners / problem keys that can degrade to a still image when configured.
_VIDEO_DEGRADE_OWNERS = frozenset({OWNER_VIDEO})
_VIDEO_DEGRADE_PROBLEMS = frozenset({PROBLEM_MOTION})

# Default confidence below which we escalate rather than auto-repair.
DEFAULT_CONFIDENCE_FLOOR = 0.5

# Default generation units for one targeted repair of a provider node.
DEFAULT_REPAIR_GENERATIONS = 1


# ---------------------------------------------------------------------------
# Policy resolved from the Job channel snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairPolicy:
    """Resolved repair / escalation ceilings for one Job.

    Source of truth is the Job's ``channel_snapshot.review_policy`` and
    ``channel_snapshot.budget``. Unknown / missing fields use safe defaults.
    """

    max_repairs: int = 3
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR
    # When True (default), low confidence escalates instead of repairing.
    escalate_on_low_confidence: bool = True
    # Per-owner degradation mode. ``keep_still`` is the §12.5 video example.
    safe_degradation: Mapping[str, str] = field(default_factory=dict)
    # Optional scene-level cap (in addition to per-issue max_repairs).
    max_repairs_per_scene: int | None = None
    budget: Budget = field(default_factory=Budget)
    # Free-text escalation policy from the Channel (presentation / notes).
    escalation_note: str = ""

    @property
    def has_job_budget_ceiling(self) -> bool:
        return (
            self.budget.max_generations is not None
            or self.budget.max_cost is not None
        )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        payload = dump(mode="json")
        if isinstance(payload, Mapping):
            return payload
    return {}


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _parse_review_policy(snapshot: Mapping[str, Any] | None) -> ReviewPolicy:
    if not isinstance(snapshot, Mapping):
        return ReviewPolicy()
    raw = snapshot.get("review_policy")
    if raw is None:
        return ReviewPolicy()
    if isinstance(raw, ReviewPolicy):
        return raw
    if not isinstance(raw, Mapping):
        return ReviewPolicy()
    try:
        return ReviewPolicy.model_validate(raw)
    except Exception:
        return ReviewPolicy()


def _parse_budget(snapshot: Mapping[str, Any] | None) -> Budget:
    return budget_from_job({"channel_snapshot": dict(snapshot or {})})


def _float_threshold(thresholds: Mapping[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        if key in thresholds and thresholds[key] is not None:
            try:
                value = float(thresholds[key])
            except (TypeError, ValueError):
                continue
            if 0.0 <= value <= 1.0:
                return value
    return default


def _optional_int_threshold(
    thresholds: Mapping[str, Any], *keys: str
) -> int | None:
    for key in keys:
        if key in thresholds and thresholds[key] is not None:
            try:
                value = int(thresholds[key])
            except (TypeError, ValueError):
                continue
            if value >= 0:
                return value
    return None


def _bool_threshold(
    thresholds: Mapping[str, Any], *keys: str, default: bool
) -> bool:
    for key in keys:
        if key in thresholds and thresholds[key] is not None:
            value = thresholds[key]
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
    return default


def _safe_degradation_map(thresholds: Mapping[str, Any]) -> dict[str, str]:
    """Normalise ``thresholds.safe_degradation`` into owner/problem → mode."""
    raw = thresholds.get("safe_degradation")
    if raw is None:
        # Common shortcut: thresholds.keep_still_on_video_failure = true
        if _bool_threshold(
            thresholds, "keep_still_on_video_failure", default=False
        ):
            return {OWNER_VIDEO: "keep_still", PROBLEM_MOTION: "keep_still"}
        return {}
    if isinstance(raw, str):
        mode = raw.strip() or "keep_still"
        return {OWNER_VIDEO: mode, PROBLEM_MOTION: mode}
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k and v:
            out[k] = v
    return out


def resolve_repair_policy(
    job: Job | Mapping[str, Any] | None = None,
    *,
    snapshot: Mapping[str, Any] | None = None,
) -> RepairPolicy:
    """Build a :class:`RepairPolicy` from a Job or raw channel snapshot."""
    if snapshot is None:
        if isinstance(job, Job):
            snapshot = job.channel_snapshot
        elif isinstance(job, Mapping):
            snap = job.get("channel_snapshot")
            snapshot = snap if isinstance(snap, Mapping) else {}
        else:
            snapshot = {}

    review = _parse_review_policy(snapshot)
    thresholds = dict(review.thresholds or {})
    budget = _parse_budget(snapshot)

    return RepairPolicy(
        max_repairs=max(0, int(review.max_repairs)),
        confidence_floor=_float_threshold(
            thresholds,
            "confidence_floor",
            "min_confidence",
            default=DEFAULT_CONFIDENCE_FLOOR,
        ),
        escalate_on_low_confidence=_bool_threshold(
            thresholds,
            "escalate_on_low_confidence",
            default=True,
        ),
        safe_degradation=_safe_degradation_map(thresholds),
        max_repairs_per_scene=_optional_int_threshold(
            thresholds,
            "max_repairs_per_scene",
            "max_repair_cycles_per_scene",
        ),
        budget=budget,
        escalation_note=str(review.escalation or ""),
    )


# ---------------------------------------------------------------------------
# Decision model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairDecision:
    """Outcome of evaluating one issue against repair policy + Job budget.

    ``action``:

    * ``repair`` — admit a targeted re-run of the owning node (scene-scoped)
    * ``escalate`` — human review; issue becomes terminal ``escalated``
    * ``degrade`` — configured safe degradation (e.g. keep still for video)
    * ``accept`` — take the artifact as-is (suggested_action / policy)
    * ``refuse_budget`` — Job generation/cost ceiling would be breached
    * ``skip`` — issue already terminal / not open
    """

    action: RepairAction
    issue_id: str
    job_id: str
    scene_id: str | None
    routing: RoutingDecision | None
    reason: str
    code: str | None = None
    # attempt_count after this decision is applied (for repair: +1).
    attempt_count: int = 0
    attempts_remaining: int = 0
    estimated_generations: int = 0
    estimated_cost: float = 0.0
    # Registry type / graph node id the repair would re-run.
    target_node_type: str | None = None
    target_node_id: str | None = None
    # Safe-degradation mode when action == degrade.
    degradation_mode: str | None = None
    # Portable engine run body (ported modes only). None when not repairing.
    run_request: dict[str, Any] | None = None
    # Job-level status_reason to set when this decision stops further spend.
    job_status_reason: str | None = None

    @property
    def admits_work(self) -> bool:
        return self.action == "repair"

    @property
    def stops_job_spend(self) -> bool:
        return self.action == "refuse_budget" or (
            self.action == "escalate" and self.code == REPAIR_LIMIT_REACHED
            and self.job_status_reason is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "issue_id": self.issue_id,
            "job_id": self.job_id,
            "scene_id": self.scene_id,
            "routing": self.routing.to_dict() if self.routing else None,
            "reason": self.reason,
            "code": self.code,
            "attempt_count": self.attempt_count,
            "attempts_remaining": self.attempts_remaining,
            "estimated_generations": self.estimated_generations,
            "estimated_cost": self.estimated_cost,
            "target_node_type": self.target_node_type,
            "target_node_id": self.target_node_id,
            "degradation_mode": self.degradation_mode,
            "run_request": self.run_request,
            "job_status_reason": self.job_status_reason,
        }


@dataclass
class RepairPlan:
    """Ordered decisions for one repair cycle over a Job's open issues.

    When the Job budget is exhausted mid-plan, remaining open issues receive
    ``refuse_budget`` decisions so callers never keep spending.
    """

    job_id: str
    decisions: list[RepairDecision] = field(default_factory=list)
    policy: RepairPolicy | None = None
    stopped: bool = False
    stop_reason: str | None = None
    stop_code: str | None = None

    @property
    def repairs(self) -> list[RepairDecision]:
        return [d for d in self.decisions if d.action == "repair"]

    @property
    def escalations(self) -> list[RepairDecision]:
        return [d for d in self.decisions if d.action == "escalate"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "decisions": [d.to_dict() for d in self.decisions],
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
            "stop_code": self.stop_code,
            "repair_count": len(self.repairs),
            "escalation_count": len(self.escalations),
        }


class RepairLimitError(RuntimeError):
    """Issue exhausted its per-issue repair budget (``REPAIR_LIMIT_REACHED``)."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = REPAIR_LIMIT_REACHED
        self.message = message
        self.details = details


class RepairBudgetError(RuntimeError):
    """Job-level generation/cost ceiling blocks further repair spend."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = BUDGET_EXCEEDED
        self.message = message
        self.details = details


# ---------------------------------------------------------------------------
# Graph targeting — smallest responsible scope
# ---------------------------------------------------------------------------


def resolve_target_node_id(
    workflow: Mapping[str, Any] | None,
    routing: RoutingDecision,
    *,
    preferred_node_id: str | None = None,
) -> str | None:
    """Pick the graph node id the repair should re-run.

    Prefers ``preferred_node_id`` when it still matches a routed type; otherwise
    the first enabled workflow node whose type is in ``routing.node_types``.
    """
    if not isinstance(workflow, Mapping):
        return preferred_node_id

    nodes = [
        n for n in (workflow.get("nodes") or []) if isinstance(n, Mapping)
    ]
    by_id = {str(n.get("id")): n for n in nodes if n.get("id")}

    preferred = (preferred_node_id or "").strip() or None
    if preferred and preferred in by_id:
        node = by_id[preferred]
        node_type = str(node.get("type") or "")
        if node_type in routing.node_types and not node.get("disabled"):
            return preferred

    for node_type in routing.node_types:
        for node in nodes:
            if node.get("disabled"):
                continue
            if str(node.get("type") or "") == node_type:
                node_id = node.get("id")
                if isinstance(node_id, str) and node_id:
                    return node_id
    return preferred


def estimate_repair_generations(
    routing: RoutingDecision | None,
    *,
    target_node_type: str | None = None,
) -> int:
    """One generation unit when the owning node is provider-capable, else 0."""
    node_type = target_node_type or (
        routing.routed_to_node_type if routing is not None else None
    )
    if not node_type:
        return 0
    if node_type in PROVIDER_NODE_TYPES:
        return DEFAULT_REPAIR_GENERATIONS
    # Local services (timing, segmenter, compose, export) are free for the
    # generation counter — same rule as step 3.5.
    return 0


def build_repair_run_request(
    *,
    target_node_id: str,
    scene_id: str | None = None,
    workflow_id: str | None = None,
    workflow: Mapping[str, Any] | None = None,
    force: bool = True,
    repair_instruction: str = "",
    issue_id: str | None = None,
) -> dict[str, Any]:
    """Build a ported engine run body for a targeted repair.

    Uses ``retry_failed`` (same mode as Production "Regenerate") so the
    Production view and Repair Router share one execution path.
    ``scope.scene_ids`` carries stable scene identity when the issue is
    per-scene — adapters that honour unit filters use it; others re-run the
    node with the instruction attached for prompt revision.
    """
    body: dict[str, Any] = {
        "run_mode": "retry_failed",
        "target_node_ids": [target_node_id],
        "force": bool(force),
        "scope": {},
    }
    if scene_id:
        body["scope"]["scene_ids"] = [scene_id]
    if issue_id:
        body["scope"]["issue_id"] = issue_id
    if repair_instruction:
        body["scope"]["repair_instruction"] = repair_instruction
    if not body["scope"]:
        del body["scope"]

    if isinstance(workflow_id, str) and workflow_id:
        body["workflow_id"] = workflow_id
    elif isinstance(workflow, Mapping):
        body["workflow"] = dict(workflow)
    return body


# ---------------------------------------------------------------------------
# Safe degradation
# ---------------------------------------------------------------------------


def degradation_mode_for(
    routing: RoutingDecision,
    policy: RepairPolicy,
) -> str | None:
    """Return the configured degradation mode for this owner/problem, or None."""
    deg = policy.safe_degradation
    if not deg:
        return None
    for key in (routing.owner, routing.problem_key, routing.stage_key):
        mode = deg.get(key)
        if mode:
            return str(mode)
    # Implicit: video motion can degrade when any keep_still entry exists.
    if routing.owner in _VIDEO_DEGRADE_OWNERS or (
        routing.problem_key in _VIDEO_DEGRADE_PROBLEMS
    ):
        for mode in deg.values():
            if str(mode) == "keep_still":
                return "keep_still"
    return None


def can_safely_degrade(
    routing: RoutingDecision,
    policy: RepairPolicy,
) -> bool:
    mode = degradation_mode_for(routing, policy)
    if not mode:
        return False
    if mode == "keep_still":
        return (
            routing.owner in _VIDEO_DEGRADE_OWNERS
            or routing.problem_key in _VIDEO_DEGRADE_PROBLEMS
        )
    return True


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def _issue_status(issue: Any) -> str:
    return str(_field(issue, "status", "open") or "open")


def _issue_attempts(issue: Any) -> int:
    raw = _field(issue, "attempt_count", 0)
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _scene_attempt_total(
    issues: Sequence[Any],
    scene_id: str | None,
    *,
    exclude_issue_id: str | None = None,
) -> int:
    """Sum of attempt_count across issues bound to the same scene."""
    if not scene_id:
        return 0
    total = 0
    for item in issues:
        if str(_field(item, "scene_id") or "") != scene_id:
            continue
        item_id = str(_field(item, "id") or "")
        if exclude_issue_id and item_id == exclude_issue_id:
            # Count this issue's attempts separately via its own field.
            continue
        total += _issue_attempts(item)
    return total


def decide_issue_repair(
    issue: Any,
    job: Job | Mapping[str, Any],
    *,
    policy: RepairPolicy | None = None,
    workflow: Mapping[str, Any] | None = None,
    estimated_cost: float = 0.0,
    peer_issues: Sequence[Any] | None = None,
    projected_spent: BudgetSpent | None = None,
) -> RepairDecision:
    """Decide how to handle one issue without side effects.

    ``projected_spent`` lets a multi-issue planner accumulate generation/cost
    estimates so later issues see the budget impact of earlier admits.
    """
    issue_id = str(_field(issue, "id") or "")
    job_id = str(
        _field(job, "id") if not isinstance(job, Job) else job.id
    )
    scene_id_raw = _field(issue, "scene_id", None)
    scene_id = str(scene_id_raw).strip() if scene_id_raw else None
    status = _issue_status(issue)
    attempts = _issue_attempts(issue)
    confidence_raw = _field(issue, "confidence", 1.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 1.0
    suggested = str(_field(issue, "suggested_action", "regenerate") or "regenerate")

    resolved_policy = policy or resolve_repair_policy(job)
    max_repairs = resolved_policy.max_repairs
    attempts_remaining = max(0, max_repairs - attempts)

    def _base(**kwargs: Any) -> RepairDecision:
        defaults = {
            "issue_id": issue_id,
            "job_id": job_id,
            "scene_id": scene_id,
            "routing": None,
            "reason": "",
            "code": None,
            "attempt_count": attempts,
            "attempts_remaining": attempts_remaining,
            "estimated_generations": 0,
            "estimated_cost": 0.0,
            "target_node_type": None,
            "target_node_id": None,
            "degradation_mode": None,
            "run_request": None,
            "job_status_reason": None,
        }
        defaults.update(kwargs)
        return RepairDecision(**defaults)  # type: ignore[arg-type]

    # Terminal / non-open issues are never re-entered — prevents loops.
    if status not in OPEN_STATUSES:
        return _base(
            action="skip",
            reason=f"Issue status {status!r} is not open; skipping",
            code=ISSUE_NOT_OPEN,
        )

    # Explicit accept.
    if suggested == "accept":
        return _base(
            action="accept",
            reason="Reviewer suggested accepting the artifact as-is",
            code=SUGGESTED_ACCEPT,
        )

    # Route first so degradation / owner-aware decisions have context.
    try:
        routing = route_issue(issue)
    except (UnroutableIssue, ValueError) as exc:
        return _base(
            action="escalate",
            reason=f"Unroutable issue — escalate to human: {exc}",
            code=UNROUTABLE,
            job_status_reason=STATUS_REASON_ESCALATION,
        )

    target_node_type = routing.routed_to_node_type
    preferred = _field(issue, "target_node_id", None)
    target_node_id = resolve_target_node_id(
        workflow,
        routing,
        preferred_node_id=str(preferred) if preferred else None,
    )
    estimate = estimate_repair_generations(
        routing, target_node_type=target_node_type
    )

    def _with_route(**kwargs: Any) -> RepairDecision:
        payload = {
            "routing": routing,
            "target_node_type": target_node_type,
            "target_node_id": target_node_id,
        }
        payload.update(kwargs)
        return _base(**payload)

    # Explicit escalate from the reviewer.
    if suggested == "escalate":
        return _with_route(
            action="escalate",
            reason="Reviewer suggested escalation to human review",
            code=SUGGESTED_ESCALATE,
            job_status_reason=STATUS_REASON_ESCALATION,
        )

    # Low confidence → human, not blind auto-repair.
    if (
        resolved_policy.escalate_on_low_confidence
        and confidence < resolved_policy.confidence_floor
    ):
        return _with_route(
            action="escalate",
            reason=(
                f"Confidence {confidence:.2f} is below floor "
                f"{resolved_policy.confidence_floor:.2f}; escalate to human"
            ),
            code=LOW_CONFIDENCE,
            job_status_reason=STATUS_REASON_ESCALATION,
        )

    # Per-issue attempt budget exhausted.
    if attempts >= max_repairs:
        if can_safely_degrade(routing, resolved_policy):
            mode = degradation_mode_for(routing, resolved_policy) or "keep_still"
            return _with_route(
                action="degrade",
                reason=(
                    f"Repair attempts exhausted ({attempts}/{max_repairs}); "
                    f"safe degradation mode={mode!r}"
                ),
                code=SAFE_DEGRADATION,
                degradation_mode=mode,
            )
        return _with_route(
            action="escalate",
            reason=(
                f"Repair attempts exhausted ({attempts}/{max_repairs}); "
                "escalate instead of looping"
            ),
            code=REPAIR_LIMIT_REACHED,
            job_status_reason=STATUS_REASON_REPAIR_LIMIT,
        )

    # Optional per-scene attempt budget (Automatic policy table: max cycles/scene).
    scene_cap = resolved_policy.max_repairs_per_scene
    if scene_cap is not None and scene_id:
        peers = list(peer_issues or [])
        scene_total = _scene_attempt_total(
            peers, scene_id, exclude_issue_id=issue_id
        ) + attempts
        if scene_total >= scene_cap:
            if can_safely_degrade(routing, resolved_policy):
                mode = (
                    degradation_mode_for(routing, resolved_policy) or "keep_still"
                )
                return _with_route(
                    action="degrade",
                    reason=(
                        f"Scene repair budget exhausted "
                        f"({scene_total}/{scene_cap} attempts on {scene_id}); "
                        f"safe degradation mode={mode!r}"
                    ),
                    code=SAFE_DEGRADATION,
                    degradation_mode=mode,
                )
            return _with_route(
                action="escalate",
                reason=(
                    f"Scene repair budget exhausted "
                    f"({scene_total}/{scene_cap} attempts on {scene_id})"
                ),
                code=REPAIR_LIMIT_REACHED,
                job_status_reason=STATUS_REASON_REPAIR_LIMIT,
            )

    # Job generation / cost ceiling — same gate as stage starts (step 3.5).
    spent = projected_spent if projected_spent is not None else spent_from_job(job)
    job_for_check: dict[str, Any]
    if isinstance(job, Job):
        job_for_check = {
            "id": job.id,
            "channel_snapshot": job.channel_snapshot,
            "budget_spent": spent.model_dump(mode="json"),
        }
    else:
        job_for_check = {
            "id": job_id,
            "channel_snapshot": _as_mapping(job.get("channel_snapshot")),
            "budget_spent": spent.model_dump(mode="json")
            if isinstance(spent, BudgetSpent)
            else dict(spent or {}),
        }

    if estimate > 0 or estimated_cost > 0 or resolved_policy.has_job_budget_ceiling:
        try:
            check_budget_preflight(
                job_for_check,
                estimated_generations=estimate,
                estimated_cost=float(estimated_cost or 0.0),
                stage_key=routing.stage_key,
            )
        except BudgetExceededError as exc:
            return _with_route(
                action="refuse_budget",
                reason=(
                    f"Job repair budget would be exceeded; stop spending. "
                    f"{exc.message}"
                ),
                code=BUDGET_EXCEEDED,
                estimated_generations=estimate,
                estimated_cost=float(estimated_cost or 0.0),
                job_status_reason=STATUS_REASON_BUDGET,
            )

    # Admitted repair — scene-scoped re-run of the owning node.
    instruction = str(_field(issue, "repair_instruction", "") or "")
    workflow_id = None
    if isinstance(job, Job):
        workflow_id = job.workflow_id
    elif isinstance(job, Mapping):
        workflow_id = job.get("workflow_id")

    run_request = None
    if target_node_id:
        run_request = build_repair_run_request(
            target_node_id=target_node_id,
            scene_id=scene_id,
            workflow_id=str(workflow_id) if workflow_id else None,
            workflow=workflow if not workflow_id else None,
            repair_instruction=instruction,
            issue_id=issue_id or None,
        )

    next_attempts = attempts + 1
    return _with_route(
        action="repair",
        reason=(
            f"Targeted repair of scene={scene_id!r} via "
            f"{routing.owner}/{target_node_type} "
            f"(attempt {next_attempts}/{max_repairs})"
        ),
        code=None,
        attempt_count=next_attempts,
        attempts_remaining=max(0, max_repairs - next_attempts),
        estimated_generations=estimate,
        estimated_cost=float(estimated_cost or 0.0),
        run_request=run_request,
    )


def plan_job_repairs(
    job: Job | Mapping[str, Any],
    *,
    issues: Sequence[Any] | None = None,
    workflow: Mapping[str, Any] | None = None,
    policy: RepairPolicy | None = None,
    estimated_cost_per_repair: float = 0.0,
) -> RepairPlan:
    """Plan repairs for every open issue on a Job, honouring budgets.

    Issues are evaluated in stable order (scene_id, created_at, id). When a
    decision refuses further budget, the plan is marked stopped and every
    remaining open issue gets ``refuse_budget`` so callers cannot keep spending.
    """
    job_id = job.id if isinstance(job, Job) else str(_field(job, "id") or "")
    resolved_policy = policy or resolve_repair_policy(job)

    if issues is None:
        if job_id:
            try:
                issues = list_issues(job_id=job_id, open_only=True)
            except Exception:
                issues = []
        else:
            issues = []

    open_issues = [
        item
        for item in issues
        if _issue_status(item) in OPEN_STATUSES
    ]
    open_issues.sort(
        key=lambda item: (
            str(_field(item, "scene_id") or ""),
            str(_field(item, "created_at") or ""),
            str(_field(item, "id") or ""),
        )
    )

    plan = RepairPlan(job_id=job_id, policy=resolved_policy)
    spent = spent_from_job(job)
    projected = BudgetSpent(
        generations=int(spent.generations),
        cost=float(spent.cost),
    )
    stopped = False
    stop_reason: str | None = None
    stop_code: str | None = None

    for issue in open_issues:
        if stopped:
            # Do not evaluate further repairs — surface a clear refuse for each.
            try:
                routing = route_issue(issue)
            except Exception:
                routing = None
            plan.decisions.append(
                RepairDecision(
                    action="refuse_budget",
                    issue_id=str(_field(issue, "id") or ""),
                    job_id=job_id,
                    scene_id=(
                        str(_field(issue, "scene_id")).strip()
                        if _field(issue, "scene_id")
                        else None
                    ),
                    routing=routing,
                    reason=stop_reason
                    or "Job repair budget already exhausted; not spending further",
                    code=stop_code or BUDGET_EXCEEDED,
                    attempt_count=_issue_attempts(issue),
                    attempts_remaining=max(
                        0, resolved_policy.max_repairs - _issue_attempts(issue)
                    ),
                    target_node_type=(
                        routing.routed_to_node_type if routing else None
                    ),
                    job_status_reason=STATUS_REASON_BUDGET,
                )
            )
            continue

        decision = decide_issue_repair(
            issue,
            job,
            policy=resolved_policy,
            workflow=workflow,
            estimated_cost=estimated_cost_per_repair,
            peer_issues=open_issues,
            projected_spent=projected,
        )
        plan.decisions.append(decision)

        if decision.action == "repair":
            projected = BudgetSpent(
                generations=int(projected.generations)
                + int(decision.estimated_generations),
                cost=float(projected.cost) + float(decision.estimated_cost),
            )
        elif decision.action == "refuse_budget":
            stopped = True
            stop_reason = decision.reason
            stop_code = decision.code
            plan.stopped = True
            plan.stop_reason = stop_reason
            plan.stop_code = stop_code

    return plan


# ---------------------------------------------------------------------------
# Apply decisions (durable issue + job status updates)
# ---------------------------------------------------------------------------


def apply_repair_decision(
    decision: RepairDecision,
    *,
    update_job_fn: Any | None = None,
    mark_repairing: bool = True,
    record_history: bool = True,
) -> ReviewIssue | None:
    """Persist the decision onto the ReviewIssue (and optionally the Job).

    * ``repair`` → status ``repairing``, ``attempt_count`` advanced
    * ``escalate`` → status ``escalated``
    * ``degrade`` / ``accept`` → status ``accepted`` (artifact kept)
    * ``refuse_budget`` / ``skip`` → issue unchanged

    Terminal outcomes (escalate / accept / degrade) also write a
    :class:`~scriptase.review.history.RepairHistoryEntry` when
    ``record_history`` is True (step 8.4). Admitted repairs write history
    only after the attempt finishes via :func:`record_repair_attempt`.

    When ``update_job_fn`` is provided and the decision carries
    ``job_status_reason``, it is called as
    ``update_job_fn(job_id, status_reason=..., status=...)`` so the Job stops
    with a clear reason. Pass the real :func:`scriptase.jobs.store.update_job`
    from orchestration; tests may inject a stub.
    """
    if decision.action in {"refuse_budget", "skip"}:
        if (
            decision.action == "refuse_budget"
            and decision.job_status_reason
            and callable(update_job_fn)
            and decision.job_id
        ):
            _stop_job(update_job_fn, decision)
        return None

    if not decision.issue_id:
        return None

    if decision.action == "repair":
        if not mark_repairing:
            return get_issue(decision.issue_id)
        return update_issue(
            decision.issue_id,
            status="repairing",
            attempt_count=decision.attempt_count,
        )

    if decision.action == "escalate":
        try:
            current = get_issue(decision.issue_id)
            note = f"escalated: {decision.reason}"
            new_reason = (
                f"{current.reason}; {note}" if current.reason else note
            )[:500]
        except Exception:
            new_reason = f"escalated: {decision.reason}"[:500]
            current = None
        issue = update_issue(
            decision.issue_id,
            status="escalated",
            suggested_action="escalate",
            attempt_count=decision.attempt_count,
            reason=new_reason,
        )
        if record_history:
            _record_decision_history(decision, issue=current or issue)
        if decision.job_status_reason and callable(update_job_fn) and decision.job_id:
            _stop_job(update_job_fn, decision, status="awaiting_approval")
        return issue

    if decision.action in {"degrade", "accept"}:
        note = decision.reason
        try:
            current = get_issue(decision.issue_id)
            new_reason = (f"{current.reason}; {note}" if current.reason else note)[
                :500
            ]
        except Exception:
            new_reason = note[:500]
            current = None
        kwargs: dict[str, Any] = {
            "status": "accepted",
            "suggested_action": "accept",
            "reason": new_reason,
        }
        if decision.action == "degrade" and decision.degradation_mode:
            kwargs["repair_instruction"] = f"degraded:{decision.degradation_mode}"
        issue = update_issue(decision.issue_id, **kwargs)
        if record_history:
            _record_decision_history(decision, issue=current or issue)
        return issue

    return None


def _record_decision_history(
    decision: RepairDecision,
    *,
    issue: Any | None = None,
) -> None:
    """Best-effort step-8.4 history write for a terminal decision."""
    try:
        from scriptase.review.history import record_repair_outcome

        record_repair_outcome(decision, issue=issue)
    except Exception:
        pass


def record_repair_attempt(
    decision: RepairDecision,
    *,
    result: Literal["resolved", "failed", "escalated", "degraded"],
    issue: Any | None = None,
    input_artifact_ids: Sequence[str] | None = None,
    output_artifact_ids: Sequence[str] | None = None,
    provider_instance_id: str | None = None,
    prompt_revision: str | None = None,
    provenance_ref: str | None = None,
    selection_reason: str | None = None,
    instruction: str | None = None,
    reason: str | None = None,
    resolve_issue: bool = True,
) -> Any:
    """Record the outcome of an admitted repair re-run (step 8.4).

    Call after the engine finishes a targeted repair. Writes a
    ``RepairHistoryEntry``, appends it to ``Job.repair_history``, and
    optionally marks the issue resolved / re-opens it on failure.

    Returns the history entry (or None when the decision is not a repair).
    """
    from scriptase.review.history import record_repair_outcome

    if issue is None and decision.issue_id:
        try:
            issue = get_issue(decision.issue_id)
        except Exception:
            issue = None

    entry = record_repair_outcome(
        decision,
        result=result,
        issue=issue,
        input_artifact_ids=input_artifact_ids,
        output_artifact_ids=output_artifact_ids,
        provider_instance_id=provider_instance_id,
        prompt_revision=prompt_revision,
        provenance_ref=provenance_ref,
        selection_reason=selection_reason,
        instruction=instruction,
        reason=reason if reason is not None else decision.reason,
    )

    if resolve_issue and decision.issue_id:
        try:
            if result == "resolved":
                update_issue(decision.issue_id, status="resolved")
            elif result == "escalated":
                update_issue(
                    decision.issue_id,
                    status="escalated",
                    suggested_action="escalate",
                )
            elif result == "degraded":
                update_issue(
                    decision.issue_id,
                    status="accepted",
                    suggested_action="accept",
                )
            elif result == "failed":
                # Re-open so the next cycle can re-decide (escalate / retry).
                update_issue(decision.issue_id, status="open")
        except Exception:
            pass

    return entry


def _stop_job(
    update_job_fn: Any,
    decision: RepairDecision,
    *,
    status: str | None = None,
) -> None:
    """Best-effort Job status_reason stamp so the UI shows why spend stopped."""
    kwargs: dict[str, Any] = {
        "status_reason": decision.job_status_reason or STATUS_REASON_BUDGET,
    }
    if status is not None:
        kwargs["status"] = status
    try:
        update_job_fn(decision.job_id, **kwargs)
    except TypeError:
        # Some stubs only accept status_reason.
        try:
            update_job_fn(
                decision.job_id,
                status_reason=decision.job_status_reason or STATUS_REASON_BUDGET,
            )
        except Exception:
            pass
    except Exception:
        pass


def apply_repair_plan(
    plan: RepairPlan,
    *,
    update_job_fn: Any | None = None,
    mark_repairing: bool = True,
    record_history: bool = True,
) -> list[ReviewIssue]:
    """Apply every decision in a plan. Returns updated issues (may be partial)."""
    updated: list[ReviewIssue] = []
    job_stopped = False

    for decision in plan.decisions:
        # Only stamp the Job once for budget stop.
        job_fn = update_job_fn
        if decision.action == "refuse_budget":
            if job_stopped:
                job_fn = None
            else:
                job_stopped = True
        elif decision.action == "escalate" and decision.job_status_reason:
            # First escalation that wants a job pause wins.
            if job_stopped:
                # Still escalate the issue, but do not thrash job status.
                result = apply_repair_decision(
                    decision,
                    update_job_fn=None,
                    mark_repairing=mark_repairing,
                    record_history=record_history,
                )
                if result is not None:
                    updated.append(result)
                continue

        result = apply_repair_decision(
            decision,
            update_job_fn=job_fn,
            mark_repairing=mark_repairing,
            record_history=record_history,
        )
        if result is not None:
            updated.append(result)
        if decision.action == "refuse_budget" and decision.job_status_reason:
            job_stopped = True

    return updated


def process_job_repairs(
    job: Job | Mapping[str, Any],
    *,
    issues: Sequence[Any] | None = None,
    workflow: Mapping[str, Any] | None = None,
    policy: RepairPolicy | None = None,
    update_job_fn: Any | None = None,
    mark_repairing: bool = True,
    estimated_cost_per_repair: float = 0.0,
    record_history: bool = True,
) -> RepairPlan:
    """Plan and apply one repair cycle for a Job.

    Returns the plan (including run requests for admitted repairs). Does **not**
    start the engine — callers (orchestration / Automatic mode) own execution
    so tests can assert policy without provider calls. Terminal decisions write
    repair-history entries when ``record_history`` is True (step 8.4).
    """
    plan = plan_job_repairs(
        job,
        issues=issues,
        workflow=workflow,
        policy=policy,
        estimated_cost_per_repair=estimated_cost_per_repair,
    )
    apply_repair_plan(
        plan,
        update_job_fn=update_job_fn,
        mark_repairing=mark_repairing,
        record_history=record_history,
    )
    return plan


def record_repair_failure(
    issue_id: str,
    *,
    policy: RepairPolicy | None = None,
    job: Job | Mapping[str, Any] | None = None,
    workflow: Mapping[str, Any] | None = None,
) -> RepairDecision:
    """After a repair attempt fails, re-decide (escalate / degrade / retry).

    The attempt_count is assumed already advanced when the repair was admitted.
    This helper re-reads the issue and returns the next decision without
    re-applying it — call :func:`apply_repair_decision` to persist.
    """
    issue = get_issue(issue_id)
    if job is None:
        job = {
            "id": issue.job_id,
            "channel_snapshot": {},
            "budget_spent": {"generations": 0, "cost": 0.0},
        }
    return decide_issue_repair(
        issue,
        job,
        policy=policy or (resolve_repair_policy(job) if job else None),
        workflow=workflow,
    )


__all__ = [
    "BUDGET_EXCEEDED",
    "DEFAULT_CONFIDENCE_FLOOR",
    "DEFAULT_REPAIR_GENERATIONS",
    "LOW_CONFIDENCE",
    "REPAIR_LIMIT_REACHED",
    "SAFE_DEGRADATION",
    "STATUS_REASON_BUDGET",
    "STATUS_REASON_ESCALATION",
    "STATUS_REASON_REPAIR_LIMIT",
    "RepairAction",
    "RepairBudgetError",
    "RepairDecision",
    "RepairLimitError",
    "RepairPlan",
    "RepairPolicy",
    "apply_repair_decision",
    "apply_repair_plan",
    "build_repair_run_request",
    "can_safely_degrade",
    "decide_issue_repair",
    "degradation_mode_for",
    "estimate_repair_generations",
    "plan_job_repairs",
    "process_job_repairs",
    "record_repair_attempt",
    "record_repair_failure",
    "resolve_repair_policy",
    "resolve_target_node_id",
]
