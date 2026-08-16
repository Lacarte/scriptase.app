"""Stage projection: ordered Production stages derived from a workflow graph.

contracts.md §10 / product §3 / implementation-plan step 2.2.

The Production view never hardcodes a step array. This module projects the
authoritative node DAG into the ordered stage list the UI renders. Side
branches (captions, music, branding, validators) collapse into the stage where
they merge so the Production view stays simple while the DAG stays honest.

``-P`` never appears in a stage name; provider capability is metadata.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from scriptase.engine.registry import get_node_type
from scriptase.engine.scheduler import SchedulerError, build_graph, deterministic_order


class StageProjectionError(RuntimeError):
    """Graph could not be projected into stages (``STAGE_PROJECTION_INVALID``)."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = "STAGE_PROJECTION_INVALID"
        self.message = message
        self.details = details


# ---------------------------------------------------------------------------
# Canonical production stage catalog (contracts.md §10)
# ---------------------------------------------------------------------------

# Ordered spine. Labels are the Production view names; keys are stable ids.
STAGE_CATALOG: tuple[dict[str, Any], ...] = (
    {"key": "script", "label": "Script", "ordinal": 0},
    {"key": "voice", "label": "Voice", "ordinal": 1},
    {"key": "timing", "label": "Timing", "ordinal": 2},
    {"key": "segments", "label": "Segments", "ordinal": 3},
    {"key": "scenes", "label": "Scenes", "ordinal": 4},
    {"key": "images", "label": "Images", "ordinal": 5},
    {"key": "videos", "label": "Videos", "ordinal": 6},
    {"key": "review", "label": "Review", "ordinal": 7},
    {"key": "composer", "label": "Composer", "ordinal": 8},
    {"key": "export", "label": "Export", "ordinal": 9},
)

STAGE_BY_KEY: dict[str, dict[str, Any]] = {s["key"]: s for s in STAGE_CATALOG}
STAGE_KEYS: tuple[str, ...] = tuple(s["key"] for s in STAGE_CATALOG)

# Primary media nodes — each owns a Production stage.
PRIMARY_STAGE_BY_TYPE: dict[str, str] = {
    "script.input": "script",
    "story.generate": "script",
    # Step 16.2 — the virality score belongs to the Script stage, not a stage
    # of its own. It is a verdict *about* the script, and putting it anywhere
    # later would surface a weak hook after the expensive stages had already
    # run, which is the failure this phase exists to prevent.
    "script.analyze": "script",
    "tts.generate": "voice",
    "timing.align": "timing",
    "segment.run": "segments",
    "scenes.blueprint": "scenes",
    "storyboard.generate": "images",
    "animator.generate": "videos",
    # Phase 7 will register review node types against this key.
    "review.run": "review",
    "review.validate": "review",
    "review.semantic": "review",
    "assemble.project": "composer",
    "timeline.project": "composer",
    "export.video": "export",
}

# Side branches that always collapse into a fixed merge stage (product §13).
# Adding or removing these changes the graph without adding a Production step.
SIDE_BRANCH_STAGE_BY_TYPE: dict[str, str] = {
    "captions.generate": "composer",
    "music.select": "composer",
}

# Infrastructure / control nodes that never appear as Production stages.
# Branding/settings (project.setup) fan out via ports; they are not a step.
INFRASTRUCTURE_TYPES: frozenset[str] = frozenset({
    "trigger.manual",
    "project.setup",
    "project.existing",
    "workflow.output",
    "utility.set_value",
    "utility.condition",
    "utility.merge",
    "utility.wait",
    "stub.input",
    "stub.output",
    "sample.input",
    "result.viewer",
})

# Node execution statuses (engine models) → stage status priority (low = wins).
# A stage surfaces the most severe status among its member nodes.
_STATUS_PRIORITY: dict[str, int] = {
    "failed": 0,
    "cancelled": 1,
    "awaiting_approval": 2,
    "running": 3,
    "queued": 3,
    "waiting": 3,
    "invalid": 4,
    "stale": 5,
    "succeeded": 6,
    "skipped": 6,
    "idle": 7,
}

_DEFAULT_STAGE_STATUS = "idle"


# ---------------------------------------------------------------------------
# Provider capability
# ---------------------------------------------------------------------------


def node_type_is_provider_capable(type_key: str) -> bool:
    """True when the registry definition selects a provider.

    Provider capability is metadata, never part of the stage name (product §6).
    Detected from the config schema (``provider`` widget / ``provider_id``)
    rather than a separate capability flag — that is how every shipped
    provider-capable node is authored today.
    """
    definition = get_node_type(type_key)
    if not definition:
        return False
    capabilities = definition.get("capabilities") or {}
    if capabilities.get("provider_capable") is True:
        return True
    for field in definition.get("config_schema") or []:
        if not isinstance(field, dict):
            continue
        if field.get("type") == "provider" or field.get("name") == "provider_id":
            return True
    return False


# ---------------------------------------------------------------------------
# Graph assignment
# ---------------------------------------------------------------------------


def _node_map(workflow: Mapping[str, Any]) -> dict[str, dict]:
    nodes: dict[str, dict] = {}
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            nodes[node_id] = node
    return nodes


def _data_dependents(workflow: Mapping[str, Any]) -> dict[str, list[str]]:
    """node_id → downstream targets reached by *data* edges only.

    Control edges are ignored for merge-stage resolution so a trigger fan-out
    cannot pull side branches into an arbitrary stage.
    """
    dependents: dict[str, list[str]] = {
        node["id"]: [] for node in (workflow.get("nodes") or []) if isinstance(node, dict) and node.get("id")
    }
    for edge in workflow.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        if edge.get("edge_type", "data") == "control":
            continue
        source = edge.get("source_node")
        target = edge.get("target_node")
        if source in dependents and isinstance(target, str):
            dependents[source].append(target)
    return dependents


def _resolve_stage_for_type(type_key: str) -> str | None:
    if type_key in PRIMARY_STAGE_BY_TYPE:
        return PRIMARY_STAGE_BY_TYPE[type_key]
    if type_key in SIDE_BRANCH_STAGE_BY_TYPE:
        return SIDE_BRANCH_STAGE_BY_TYPE[type_key]
    return None


def _collapse_to_merge_stage(
    node_id: str,
    *,
    nodes: Mapping[str, dict],
    dependents: Mapping[str, list[str]],
    memo: dict[str, str | None],
    visiting: set[str],
) -> str | None:
    """Walk downstream data edges until a stage-bearing node is found."""
    if node_id in memo:
        return memo[node_id]
    if node_id in visiting:
        return None
    visiting.add(node_id)

    node = nodes.get(node_id) or {}
    type_key = str(node.get("type") or "")
    direct = _resolve_stage_for_type(type_key)
    if direct is not None:
        memo[node_id] = direct
        visiting.discard(node_id)
        return direct

    # Prefer a primary stage downstream (merge target) over another side branch.
    found: str | None = None
    for target in dependents.get(node_id, []):
        stage = _collapse_to_merge_stage(
            target,
            nodes=nodes,
            dependents=dependents,
            memo=memo,
            visiting=visiting,
        )
        if stage is None:
            continue
        # Keep the earliest spine stage if multiple merge targets exist.
        if found is None:
            found = stage
        else:
            found_ord = STAGE_BY_KEY[found]["ordinal"]
            stage_ord = STAGE_BY_KEY[stage]["ordinal"]
            if stage_ord < found_ord:
                found = stage

    memo[node_id] = found
    visiting.discard(node_id)
    return found


def assign_nodes_to_stages(workflow: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return ``{stage_key: [node_id, ...]}`` for every non-infrastructure node.

    Node order inside each stage follows the workflow's deterministic topological
    order so the projection is stable across reloads.
    """
    nodes = _node_map(workflow)
    if not nodes:
        return {key: [] for key in STAGE_KEYS}

    dependents = _data_dependents(workflow)
    memo: dict[str, str | None] = {}
    assignment: dict[str, list[str]] = {key: [] for key in STAGE_KEYS}

    try:
        order = deterministic_order(workflow)
    except SchedulerError as exc:
        raise StageProjectionError(
            exc.message or "Workflow graph could not be ordered",
            details={"scheduler_code": getattr(exc, "code", None)},
        ) from exc

    for node_id in order:
        node = nodes.get(node_id)
        if node is None:
            continue
        type_key = str(node.get("type") or "")
        if type_key in INFRASTRUCTURE_TYPES:
            continue
        # Scaffold / testing nodes stay off the Production spine.
        if type_key.startswith("scaffold_") or type_key.startswith("stub."):
            continue

        stage_key = _resolve_stage_for_type(type_key)
        if stage_key is None:
            stage_key = _collapse_to_merge_stage(
                node_id,
                nodes=nodes,
                dependents=dependents,
                memo=memo,
                visiting=set(),
            )
        if stage_key is None:
            # Unclassified node with no path to a production stage — skip.
            # (Custom utility subgraphs should not invent Production steps.)
            continue
        if stage_key not in assignment:
            raise StageProjectionError(
                f"Node {node_id!r} resolved to unknown stage {stage_key!r}",
                details={"node_id": node_id, "stage_key": stage_key},
            )
        assignment[stage_key].append(node_id)

    return assignment


# ---------------------------------------------------------------------------
# Status / artifacts / providers
# ---------------------------------------------------------------------------


def _aggregate_status(node_statuses: list[str]) -> str:
    if not node_statuses:
        return _DEFAULT_STAGE_STATUS
    best = _DEFAULT_STAGE_STATUS
    best_rank = _STATUS_PRIORITY.get(best, 99)
    for status in node_statuses:
        rank = _STATUS_PRIORITY.get(status, 50)
        if rank < best_rank:
            best = status
            best_rank = rank
    # Collapse queued/waiting into running for the Production view.
    if best in {"queued", "waiting"}:
        return "running"
    return best


def _active_provider_instance_id(
    node_ids: list[str],
    nodes: Mapping[str, dict],
) -> str | None:
    """First configured provider id among provider-capable members.

    Until step 3.1 this is the provider *type* id stored on the node; the field
    name is already the instance-id slot the contract reserves.
    """
    for node_id in node_ids:
        node = nodes.get(node_id) or {}
        type_key = str(node.get("type") or "")
        if not node_type_is_provider_capable(type_key):
            continue
        config = node.get("configuration") or {}
        if not isinstance(config, Mapping):
            continue
        provider = config.get("provider_id")
        if isinstance(provider, str) and provider.strip():
            return provider.strip()
    return None


def _collect_artifacts(
    node_ids: list[str],
    node_records: Mapping[str, Any],
) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for node_id in node_ids:
        record = node_records.get(node_id)
        if record is None:
            continue
        if hasattr(record, "artifact_refs"):
            candidates = getattr(record, "artifact_refs") or []
        elif isinstance(record, Mapping):
            candidates = record.get("artifact_refs") or []
        else:
            continue
        for ref in candidates:
            if isinstance(ref, str) and ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def _collect_score(
    node_ids: list[str],
    node_records: Mapping[str, Any],
) -> dict[str, Any] | None:
    """The script-score snapshot a member node recorded, or None (step 16.3).

    Only ``script.analyze`` writes one and it sits on the Script stage, so the
    first non-empty snapshot among the members is that stage's verdict. Read
    from the dedicated record field rather than ``outputs_summary``, which the
    scheduler's summarizer has already stripped of the band and the dimension
    breakdown.
    """
    for node_id in node_ids:
        record = node_records.get(node_id)
        if record is None:
            continue
        if hasattr(record, "score"):
            candidate = getattr(record, "score")
        elif isinstance(record, Mapping):
            candidate = record.get("score")
        else:
            continue
        if isinstance(candidate, Mapping) and candidate:
            return dict(candidate)
    return None


def _node_status(record: Any) -> str:
    if record is None:
        return "idle"
    if hasattr(record, "status"):
        return str(getattr(record, "status") or "idle")
    if isinstance(record, Mapping):
        return str(record.get("status") or "idle")
    return "idle"


# ---------------------------------------------------------------------------
# Public projection
# ---------------------------------------------------------------------------


def project_stages(
    workflow: Mapping[str, Any],
    *,
    execution: Mapping[str, Any] | None = None,
    fill_spine_gaps: bool = True,
    job_id: str | None = None,
    issue_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Project a workflow graph into a ``StageProjection`` document.

    Parameters
    ----------
    workflow:
        Workflow document (saved or draft). Must contain ``nodes`` / ``edges``.
    execution:
        Optional execution record (dict form). When provided, stage ``status``
        and ``artifacts`` derive from member nodes' execution records.
    fill_spine_gaps:
        When True (default), empty catalog stages between the first and last
        *occupied* stage are kept so the Production spine stays complete
        (Review appears between Videos and Composer even before Phase 7
        registers a review node). Side branches never open a new gap.
    job_id:
        Optional Job id. When provided, open ReviewIssue ids are attached to
        stages whose member nodes match each issue's ``target_node_id``
        (step 7.2). Issues without a target land on the Review stage when
        present, otherwise they are omitted from stage slots.
    issue_ids:
        Optional explicit issue id list (e.g. from ``Job.issues``). When set
        with ``job_id``, only these ids are considered.

    Raises
    ------
    StageProjectionError
        When the graph cannot be ordered (cycle) or resolves to no stages.
    """
    if not isinstance(workflow, Mapping):
        raise StageProjectionError("Workflow must be an object")

    nodes = _node_map(workflow)
    assignment = assign_nodes_to_stages(workflow)

    occupied = [key for key in STAGE_KEYS if assignment.get(key)]
    if not occupied:
        raise StageProjectionError(
            "Workflow has no production stages to project",
            details={"node_count": len(nodes)},
        )

    if fill_spine_gaps:
        first = STAGE_BY_KEY[occupied[0]]["ordinal"]
        last = STAGE_BY_KEY[occupied[-1]]["ordinal"]
        emit_keys = [
            key for key in STAGE_KEYS
            if first <= STAGE_BY_KEY[key]["ordinal"] <= last
        ]
    else:
        emit_keys = occupied

    node_records: Mapping[str, Any] = {}
    if execution is not None:
        raw_nodes = execution.get("nodes") if isinstance(execution, Mapping) else None
        if isinstance(raw_nodes, Mapping):
            node_records = raw_nodes

    # Optional ReviewIssue attachment (step 7.2). Failures to load the store
    # never break projection — stages keep a typed empty list.
    issues_by_node: dict[str, list[str]] = {}
    untargeted_issue_ids: list[str] = []
    if job_id:
        try:
            from scriptase.review.store import get_issue, list_issues

            if issue_ids is not None:
                loaded = []
                for iid in issue_ids:
                    try:
                        loaded.append(get_issue(str(iid)))
                    except Exception:
                        continue
            else:
                loaded = list_issues(job_id=job_id, open_only=True)
            for issue in loaded:
                if issue.target_node_id:
                    issues_by_node.setdefault(issue.target_node_id, []).append(issue.id)
                else:
                    untargeted_issue_ids.append(issue.id)
        except Exception:
            issues_by_node = {}
            untargeted_issue_ids = []

    stages: list[dict[str, Any]] = []
    for ordinal_index, key in enumerate(emit_keys):
        meta = STAGE_BY_KEY[key]
        member_ids = list(assignment.get(key) or [])
        member_types = [
            str((nodes.get(nid) or {}).get("type") or "")
            for nid in member_ids
        ]
        provider_capable = any(
            node_type_is_provider_capable(t) for t in member_types if t
        )
        statuses = [_node_status(node_records.get(nid)) for nid in member_ids]
        stage_issue_ids: list[str] = []
        for nid in member_ids:
            stage_issue_ids.extend(issues_by_node.get(nid) or [])
        # Untargeted issues surface on the Review stage when the spine has one.
        if key == "review" and untargeted_issue_ids:
            stage_issue_ids.extend(untargeted_issue_ids)
        # Preserve order, drop duplicates.
        seen_ids: set[str] = set()
        deduped_issues: list[str] = []
        for iid in stage_issue_ids:
            if iid not in seen_ids:
                seen_ids.add(iid)
                deduped_issues.append(iid)
        stage = {
            "key": key,
            "label": meta["label"],
            "ordinal": ordinal_index,
            "node_ids": member_ids,
            "status": _aggregate_status(statuses),
            "provider_capable": provider_capable,
            "active_provider_instance_id": _active_provider_instance_id(
                member_ids, nodes
            ),
            "artifacts": _collect_artifacts(member_ids, node_records),
            "issues": deduped_issues,
            # Step 16.3 — the script virality verdict, or None on every stage
            # that never ran an analyzer. Typed and always present so the
            # Production panel branches on a value rather than a missing key.
            "score": _collect_score(member_ids, node_records),
        }
        stages.append(stage)

    workflow_id = workflow.get("workflow_id")
    if workflow_id is not None and not isinstance(workflow_id, str):
        workflow_id = str(workflow_id)

    workflow_version = workflow.get("workflow_version")
    if workflow_version is None:
        # Jobs carry an optional int; workflows themselves version via
        # updated_at. Surface schema_version only when present as an int.
        schema = workflow.get("schema_version")
        workflow_version = schema if isinstance(schema, int) else None

    return {
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "stages": stages,
    }


def project_workflow_stages(
    workflow: Mapping[str, Any],
    *,
    execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Public alias used by routes and jobs package exports."""
    return project_stages(workflow, execution=execution)


def default_stage_labels() -> list[str]:
    """Labels of the canonical Production spine (for tests and docs)."""
    return [s["label"] for s in STAGE_CATALOG]


def stage_projection_summary(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Compact view for listings — no nested artifacts/issues."""
    stages = projection.get("stages") or []
    return {
        "workflow_id": projection.get("workflow_id"),
        "workflow_version": projection.get("workflow_version"),
        "stage_count": len(stages),
        "stages": [
            {
                "key": s.get("key"),
                "label": s.get("label"),
                "ordinal": s.get("ordinal"),
                "status": s.get("status"),
                "provider_capable": s.get("provider_capable"),
                "node_count": len(s.get("node_ids") or []),
            }
            for s in stages
            if isinstance(s, Mapping)
        ],
    }


def clone_catalog() -> list[dict[str, Any]]:
    """Deep copy of the stage catalog (tests / inspection)."""
    return deepcopy(list(STAGE_CATALOG))
