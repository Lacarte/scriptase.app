"""Persisted workflow and execution record models."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExecutionLog:
    ts: str
    level: str
    message: str


@dataclass
class NodeExecutionRecord:
    status: str = "idle"
    attempts: int = 0
    duration_ms: int | None = None
    fingerprint: str | None = None
    cache: dict[str, Any] | None = None
    from_sample_data: bool = False
    resolved_inputs_summary: dict[str, Any] = field(default_factory=dict)
    outputs_summary: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    # Artifact ids that supplied this node's inputs (step 4.1 standalone
    # input picker). Distinct from artifact_refs, which are outputs.
    source_artifact_ids: list[str] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    attempt_errors: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    # Step 9.3: compact accounting snapshot lifted from result provenance.
    # Stored outside outputs_summary so string decimals survive _summarize.
    # Shape: {amount?, currency?, unit_count?, unit?, provider_instance_id?,
    #         provider_id?, generations, cache_hit, invocation_id?}.
    cost: dict[str, Any] | None = None


@dataclass
class ExecutionRecord:
    execution_id: str
    workflow_id: str
    workflow_snapshot: dict[str, Any]
    project_id: str
    run_mode: str = "full"
    scope_node_ids: list[str] = field(default_factory=list)
    status: str = "running"
    started_at: str = ""
    finished_at: str | None = None
    nodes: dict[str, NodeExecutionRecord] = field(default_factory=dict)
    # Compact active-checkpoint pointer (contracts.md §11 / step 2.6).
    # Full resume payloads live in engine.approval resume files, not here.
    approval: dict[str, Any] | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueueRecord:
    """Persisted dispatch state for one workflow execution request."""

    execution_id: str
    workflow_id: str
    project_id: str
    status: str = "pending"
    source: str = "manual"
    requested_run_mode: str = "full"
    target_node_ids: list[str] = field(default_factory=list)
    requested_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def workflow_draft(*, name: str = "Untitled workflow", description: str = "") -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "description": description,
        "nodes": [],
        "edges": [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
    }


def summary(document: dict) -> dict:
    return {
        "workflow_id": document["workflow_id"],
        "name": document["name"],
        "description": document.get("description", ""),
        "node_count": len(document.get("nodes", [])),
        "edge_count": len(document.get("edges", [])),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
    }


def copy_draft(document: dict, *, name: str | None = None) -> dict:
    draft = deepcopy(document)
    for field in ("workflow_id", "created_at", "updated_at"):
        draft.pop(field, None)
    if name is not None:
        draft["name"] = name
    return draft
