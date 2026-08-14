"""Pre-flight budget admission control (step 3.5 / contracts.md §12).

Budget is checked **before** provider work starts. Post-hoc reporting is not
enforcement — that half lands in step 9.3. Repair (8.2) and stage actions
reuse :func:`check_budget_preflight` so every admission path shares one gate.

Ceilings come from the Job's channel snapshot (``budget.max_generations`` /
``budget.max_cost``). ``None`` on either axis means unlimited for that axis.
Spend is the Job's running ``budget_spent`` counters.
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.channels.models import Budget
from scriptase.jobs.models import BudgetSpent, Job
from scriptase.jobs.stage_projection import (
    PRIMARY_STAGE_BY_TYPE,
    STAGE_KEYS,
    assign_nodes_to_stages,
)

# Node types that call a provider and therefore consume generation budget.
# Local-only services (music, captions, timing, segmenter, compose, export)
# are free for the generation counter; cost estimates may still apply later.
PROVIDER_NODE_TYPES: frozenset[str] = frozenset({
    "story.generate",
    "tts.generate",
    "scenes.blueprint",
    "storyboard.generate",
    "animator.generate",
    "review.run",
    "review.semantic",
})


class BudgetExceededError(RuntimeError):
    """Pre-flight check refused the work (``BUDGET_EXCEEDED``)."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = "BUDGET_EXCEEDED"
        self.message = message
        self.details = details


def budget_from_snapshot(snapshot: Mapping[str, Any] | None) -> Budget:
    """Parse the Channel budget block out of a Job channel snapshot."""
    if not isinstance(snapshot, Mapping):
        return Budget()
    raw = snapshot.get("budget")
    if raw is None:
        return Budget()
    if isinstance(raw, Budget):
        return raw
    if not isinstance(raw, Mapping):
        return Budget()
    try:
        return Budget.model_validate(raw)
    except Exception:
        return Budget()


def budget_from_job(job: Job | Mapping[str, Any]) -> Budget:
    """Resolve the ceiling that applies to this Job."""
    if isinstance(job, Job):
        return budget_from_snapshot(job.channel_snapshot)
    if isinstance(job, Mapping):
        return budget_from_snapshot(job.get("channel_snapshot"))
    return Budget()


def spent_from_job(job: Job | Mapping[str, Any]) -> BudgetSpent:
    if isinstance(job, Job):
        return job.budget_spent
    if isinstance(job, Mapping):
        raw = job.get("budget_spent") or {}
        try:
            return BudgetSpent.model_validate(raw)
        except Exception:
            return BudgetSpent()
    return BudgetSpent()


def has_ceiling(budget: Budget) -> bool:
    """True when at least one axis is limited."""
    return budget.max_generations is not None or budget.max_cost is not None


def check_budget_preflight(
    job: Job | Mapping[str, Any],
    *,
    estimated_generations: int = 1,
    estimated_cost: float = 0.0,
    stage_key: str | None = None,
) -> None:
    """Refuse work that would exceed the Job's Channel budget ceiling.

    Raises
    ------
    BudgetExceededError
        With ``code == "BUDGET_EXCEEDED"`` when spent + estimate exceeds a
        configured ceiling. No ceiling (both axes ``None``) always admits.
    """
    if estimated_generations < 0:
        raise ValueError("estimated_generations must be >= 0")
    if estimated_cost < 0:
        raise ValueError("estimated_cost must be >= 0")

    budget = budget_from_job(job)
    if not has_ceiling(budget):
        return

    spent = spent_from_job(job)
    job_id = job.id if isinstance(job, Job) else str(
        (job or {}).get("id") or ""  # type: ignore[union-attr]
    )

    if budget.max_generations is not None:
        projected = int(spent.generations) + int(estimated_generations)
        if projected > int(budget.max_generations):
            raise BudgetExceededError(
                (
                    f"Budget exceeded: generations {projected} would exceed "
                    f"ceiling {budget.max_generations}"
                ),
                details={
                    "job_id": job_id or None,
                    "stage_key": stage_key,
                    "axis": "generations",
                    "spent": int(spent.generations),
                    "estimated": int(estimated_generations),
                    "ceiling": int(budget.max_generations),
                    "currency": budget.currency,
                },
            )

    if budget.max_cost is not None:
        projected_cost = float(spent.cost) + float(estimated_cost)
        if projected_cost > float(budget.max_cost):
            raise BudgetExceededError(
                (
                    f"Budget exceeded: cost {projected_cost} would exceed "
                    f"ceiling {budget.max_cost} {budget.currency}"
                ),
                details={
                    "job_id": job_id or None,
                    "stage_key": stage_key,
                    "axis": "cost",
                    "spent": float(spent.cost),
                    "estimated": float(estimated_cost),
                    "ceiling": float(budget.max_cost),
                    "currency": budget.currency,
                },
            )


def is_provider_node(node: Mapping[str, Any]) -> bool:
    """True when the node type is known to call a provider."""
    node_type = str(node.get("type") or "")
    if node.get("disabled"):
        return False
    return node_type in PROVIDER_NODE_TYPES


def count_provider_nodes(
    workflow: Mapping[str, Any] | None,
    *,
    node_ids: list[str] | set[str] | None = None,
) -> int:
    """Count enabled provider-capable nodes, optionally restricted to a set."""
    if not isinstance(workflow, Mapping):
        return 0
    allowed = set(node_ids) if node_ids is not None else None
    count = 0
    for node in workflow.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        if allowed is not None and node.get("id") not in allowed:
            continue
        if is_provider_node(node):
            count += 1
    return count


def estimate_stage_generations(
    workflow: Mapping[str, Any] | None,
    stage_key: str,
) -> int:
    """Estimate generation units for one Production stage.

    Each provider-capable primary node in the stage costs one generation unit.
    Side branches and local services do not consume the generation counter.
    """
    if not isinstance(workflow, Mapping) or not stage_key:
        return 0
    try:
        assignment = assign_nodes_to_stages(workflow)
    except Exception:
        # Fall back: count provider nodes whose primary type maps to the stage.
        count = 0
        for node in workflow.get("nodes") or []:
            if not isinstance(node, Mapping) or not is_provider_node(node):
                continue
            if PRIMARY_STAGE_BY_TYPE.get(str(node.get("type") or "")) == stage_key:
                count += 1
        return count

    members = assignment.get(stage_key) or []
    count = 0
    nodes_by_id = {
        n.get("id"): n
        for n in (workflow.get("nodes") or [])
        if isinstance(n, Mapping)
    }
    for node_id in members:
        node = nodes_by_id.get(node_id)
        if node is not None and is_provider_node(node):
            count += 1
    return count


def next_provider_stage(
    workflow: Mapping[str, Any] | None,
    *,
    completed_stages: set[str] | None = None,
) -> tuple[str | None, int]:
    """Return ``(stage_key, estimated_generations)`` for the next billed stage.

    Walks the Production spine and returns the first stage that still has
    provider work and is not in *completed_stages*. When nothing remains,
    returns ``(None, 0)``.
    """
    if not isinstance(workflow, Mapping):
        return None, 0
    done = completed_stages or set()
    for key in STAGE_KEYS:
        if key in done:
            continue
        estimate = estimate_stage_generations(workflow, key)
        if estimate > 0:
            return key, estimate
    return None, 0


def check_job_next_stage_budget(
    job: Job | Mapping[str, Any],
    workflow: Mapping[str, Any] | None = None,
    *,
    completed_stages: set[str] | None = None,
    estimated_cost: float = 0.0,
) -> tuple[str | None, int]:
    """Pre-flight the Job's next provider stage. Returns ``(stage_key, estimate)``.

    When the workflow has no remaining provider stages the check is a no-op
    (estimate 0). Raises :class:`BudgetExceededError` when the next stage
    would push the Job over its ceiling.
    """
    stage_key, estimate = next_provider_stage(
        workflow, completed_stages=completed_stages
    )
    # Full-run start with no projectable stages still needs a unit of admission
    # when the job has a generation ceiling and any work is about to run.
    if stage_key is None:
        fallback = count_provider_nodes(workflow)
        if fallback > 0:
            estimate = fallback
            stage_key = None
        else:
            # No provider work → free; still refuse if already over a cost ceiling
            # and a positive cost estimate was supplied.
            estimate = 0

    if estimate > 0 or estimated_cost > 0:
        check_budget_preflight(
            job,
            estimated_generations=max(0, estimate),
            estimated_cost=estimated_cost,
            stage_key=stage_key,
        )
    elif has_ceiling(budget_from_job(job)):
        # Already over ceiling with zero new estimate still blocks.
        check_budget_preflight(
            job,
            estimated_generations=0,
            estimated_cost=0.0,
            stage_key=stage_key,
        )
    return stage_key, estimate


__all__ = [
    "BudgetExceededError",
    "PROVIDER_NODE_TYPES",
    "budget_from_job",
    "budget_from_snapshot",
    "check_budget_preflight",
    "check_job_next_stage_budget",
    "count_provider_nodes",
    "estimate_stage_generations",
    "has_ceiling",
    "is_provider_node",
    "next_provider_stage",
    "spent_from_job",
]
