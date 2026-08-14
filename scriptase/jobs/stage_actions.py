"""Step detail panel actions → existing engine run modes (step 2.4).

contracts.md §10 / product §18 / implementation-plan step 2.4.

Production step actions never introduce a second execution path. Each action
maps onto a ported run mode the canvas already uses:

  Run            → node_with_deps
  Test           → node_isolated
  Regenerate     → retry_failed   (single-node re-run; works for any status)
  Run From Here  → from_node

View Input / View Output / Provider / History / Approve are inspect or
checkpoint actions — not new run modes. Approve resumes a durable
``awaiting_approval`` pause via the engine (step 2.6).

``-P`` never appears in a stage name; provider capability is metadata only.
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.jobs.stage_projection import (
    PRIMARY_STAGE_BY_TYPE,
    SIDE_BRANCH_STAGE_BY_TYPE,
    STAGE_BY_KEY,
    StageProjectionError,
    assign_nodes_to_stages,
)

# Stable action ids the Production UI and any future API share.
STAGE_ACTIONS = (
    "run",
    "test",
    "regenerate",
    "run_from_here",
    "view_input",
    "view_output",
    "provider",
    "history",
    "approve",
)

# Actions that start an engine run through POST /api/workflow/run.
EXECUTABLE_STAGE_ACTIONS = frozenset({
    "run",
    "test",
    "regenerate",
    "run_from_here",
})

# §18 action → ported run_mode. No new modes.
ACTION_RUN_MODES: dict[str, str] = {
    "run": "node_with_deps",
    "test": "node_isolated",
    "regenerate": "retry_failed",
    "run_from_here": "from_node",
}

# Inspect / checkpoint actions — no engine start.
INSPECT_STAGE_ACTIONS = frozenset({
    "view_input",
    "view_output",
    "provider",
    "history",
    "approve",
})


class StageActionError(RuntimeError):
    """Stage action could not be resolved (``STAGE_ACTION_INVALID``)."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = "STAGE_ACTION_INVALID"
        self.message = message
        self.details = details


def is_executable_action(action: str) -> bool:
    return action in EXECUTABLE_STAGE_ACTIONS


def run_mode_for_action(action: str) -> str:
    """Return the engine run_mode for an executable stage action.

    Raises
    ------
    StageActionError
        When *action* is unknown or is an inspect/checkpoint action.
    """
    if action in INSPECT_STAGE_ACTIONS:
        raise StageActionError(
            f"Action {action!r} does not start a run",
            details={"action": action, "kind": "inspect"},
        )
    mode = ACTION_RUN_MODES.get(action)
    if mode is None:
        raise StageActionError(
            f"Unknown stage action: {action!r}",
            details={"action": action, "known": list(STAGE_ACTIONS)},
        )
    return mode


def stage_primary_target(
    stage: Mapping[str, Any],
    workflow: Mapping[str, Any],
) -> str:
    """Pick the node id a stage action targets.

    Prefer the first member whose type is a primary (non-side-branch) owner of
    that stage. Fall back to the first member id (stable topo order from the
    projection). Multi-node stages (e.g. Composer) must not target a collapsed
    side branch when a primary is present.
    """
    if not isinstance(stage, Mapping):
        raise StageActionError("stage must be an object")
    node_ids = stage.get("node_ids") or []
    if not isinstance(node_ids, list) or not node_ids:
        raise StageActionError(
            "Stage has no member nodes to target",
            details={"stage_key": stage.get("key")},
        )
    nodes_by_id: dict[str, dict] = {}
    for node in (workflow or {}).get("nodes") or []:
        if isinstance(node, Mapping) and isinstance(node.get("id"), str):
            nodes_by_id[node["id"]] = dict(node)

    stage_key = stage.get("key")
    for node_id in node_ids:
        if not isinstance(node_id, str) or not node_id:
            continue
        node = nodes_by_id.get(node_id) or {}
        type_key = str(node.get("type") or "")
        primary_stage = PRIMARY_STAGE_BY_TYPE.get(type_key)
        if primary_stage is not None and (
            stage_key is None or primary_stage == stage_key
        ):
            return node_id

    # Side-branch-only stage (unusual) or unknown types — first valid id.
    for node_id in node_ids:
        if isinstance(node_id, str) and node_id:
            return node_id
    raise StageActionError(
        "Stage has no valid target node id",
        details={"stage_key": stage.get("key"), "node_ids": node_ids},
    )


def build_stage_run_request(
    action: str,
    stage: Mapping[str, Any],
    workflow: Mapping[str, Any],
    *,
    workflow_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build the POST /api/workflow/run body a canvas-initiated run would send.

    The Production view and the Workflow canvas must produce identical requests
    for the same action + target so execution records match field by field
    (volatile ids/timestamps excluded).
    """
    run_mode = run_mode_for_action(action)
    target = stage_primary_target(stage, workflow)
    body: dict[str, Any] = {
        "run_mode": run_mode,
        "target_node_ids": [target],
        "force": bool(force),
    }
    resolved_id = workflow_id or (
        workflow.get("workflow_id") if isinstance(workflow, Mapping) else None
    )
    if isinstance(resolved_id, str) and resolved_id:
        body["workflow_id"] = resolved_id
    else:
        body["workflow"] = workflow
    return body


def resolve_stage_from_projection(
    projection: Mapping[str, Any],
    stage_key: str,
) -> dict[str, Any]:
    """Look up a stage row by key inside a StageProjection document."""
    if not isinstance(projection, Mapping):
        raise StageActionError("projection must be an object")
    stages = projection.get("stages") or []
    if not isinstance(stages, list):
        raise StageActionError("projection.stages must be an array")
    for stage in stages:
        if isinstance(stage, Mapping) and stage.get("key") == stage_key:
            return dict(stage)
    raise StageActionError(
        f"Unknown stage key: {stage_key!r}",
        details={
            "stage_key": stage_key,
            "known": [
                s.get("key") for s in stages if isinstance(s, Mapping)
            ],
        },
    )


def stage_for_key(
    workflow: Mapping[str, Any],
    stage_key: str,
) -> dict[str, Any]:
    """Build a minimal stage dict for *stage_key* from a workflow graph.

    Used by tests and callers that have not yet loaded a full projection.
    """
    if stage_key not in STAGE_BY_KEY:
        raise StageActionError(
            f"Unknown stage key: {stage_key!r}",
            details={"stage_key": stage_key, "known": list(STAGE_BY_KEY)},
        )
    try:
        assignment = assign_nodes_to_stages(workflow)
    except StageProjectionError as exc:
        raise StageActionError(exc.message, details=exc.details) from exc
    member_ids = list(assignment.get(stage_key) or [])
    meta = STAGE_BY_KEY[stage_key]
    return {
        "key": stage_key,
        "label": meta["label"],
        "ordinal": meta["ordinal"],
        "node_ids": member_ids,
        "status": "idle",
        "provider_capable": False,
        "active_provider_instance_id": None,
        "artifacts": [],
        "issues": [],
    }


def action_requires_provider(
    action: str,
    stage: Mapping[str, Any],
) -> bool:
    """True when the UI should surface provider selection for this action.

    Provider UI appears only where the stage is provider-capable *and* the
    selected mode is an executable run that needs a provider (§6, §19).
    Inspect actions and non-provider stages never require one.
    """
    if action not in EXECUTABLE_STAGE_ACTIONS:
        return False
    return bool(stage.get("provider_capable"))


def normalize_execution_record_for_compare(record: Mapping[str, Any]) -> dict[str, Any]:
    """Strip volatile fields so two equivalent runs can be compared field-wise.

    Execution ids, project ids, timestamps, durations, fingerprints, and log
    timestamps differ between otherwise identical canvas and Production starts.
    Scope, run mode, node statuses, and output shapes must match.
    """
    if not isinstance(record, Mapping):
        raise StageActionError("execution record must be an object")

    def scrub_node(node: Mapping[str, Any]) -> dict[str, Any]:
        out = {
            "status": node.get("status"),
            "attempts": node.get("attempts"),
            "from_sample_data": bool(node.get("from_sample_data")),
            "resolved_inputs_summary": node.get("resolved_inputs_summary") or {},
            "outputs_summary": node.get("outputs_summary") or {},
            "artifact_refs": list(node.get("artifact_refs") or []),
            "error": _scrub_error(node.get("error")),
            "attempt_errors": [
                _scrub_error(err) for err in (node.get("attempt_errors") or [])
                if isinstance(err, Mapping)
            ],
            "cache": _scrub_cache(node.get("cache")),
        }
        return out

    nodes_in = record.get("nodes") or {}
    nodes_out: dict[str, Any] = {}
    if isinstance(nodes_in, Mapping):
        for node_id, node in nodes_in.items():
            if isinstance(node, Mapping):
                nodes_out[str(node_id)] = scrub_node(node)

    return {
        # workflow_id is assigned when a draft is snapshotted; two otherwise
        # identical starts get distinct ids, so it is not part of parity.
        "run_mode": record.get("run_mode"),
        "scope_node_ids": list(record.get("scope_node_ids") or []),
        "status": record.get("status"),
        "nodes": nodes_out,
        "schema_version": record.get("schema_version", 1),
    }


def _scrub_error(error: Any) -> dict[str, Any] | None:
    if not isinstance(error, Mapping):
        return None
    return {
        "code": error.get("code"),
        "message": error.get("message"),
    }


def _scrub_cache(cache: Any) -> dict[str, Any] | None:
    if not isinstance(cache, Mapping):
        return None
    return {
        "hit": bool(cache.get("hit")),
        "reason": cache.get("reason"),
    }


# Side-branch type lookup kept exported for tests that assert Composer does
# not target captions when assemble is present.
def is_side_branch_type(type_key: str) -> bool:
    return type_key in SIDE_BRANCH_STAGE_BY_TYPE
