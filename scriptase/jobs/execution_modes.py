"""Job execution modes — Manual, Assisted, Automatic (step 9.1 / product §8).

Architecture table (product §8):

* **Manual** — user explicitly runs or approves important stages.
* **Assisted** — pipeline runs automatically but pauses at configured
  checkpoints (Channel ``review_policy.human_checkpoints``); consumes the
  durable ``awaiting_approval`` engine state from step 2.6.
* **Automatic** — end-to-end unattended run under the automatic policy block
  (bounded retries, fallback after exhaustion, pause only on critical
  semantic issues, max repair cycles per scene, safe degradation, automatic
  export when quality gates pass).

Checkpoint configuration is stage keys (``script``, ``review``, …), raw
graph node ids, or registry type keys. Mode policy is applied when a Job
prepares its workflow snapshot so the engine never invents a second
execution path.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from scriptase.jobs.models import EXECUTION_MODES
from scriptase.jobs.stage_projection import (
    PRIMARY_STAGE_BY_TYPE,
    STAGE_KEYS,
    assign_nodes_to_stages,
)

# ---------------------------------------------------------------------------
# Automatic policy block defaults (architecture §8 table)
# ---------------------------------------------------------------------------

# Retry transient provider errors this many times (engine-level; surface here
# so Channel/Job views and docs share one vocabulary).
AUTOMATIC_PROVIDER_RETRIES = 2

# Maximum repair cycles per scene when the Channel does not set one.
AUTOMATIC_MAX_REPAIRS_PER_SCENE = 3

# When Automatic and the Channel left safe_degradation empty, still allow the
# documented video → still fallback after repair exhaustion (optional in the
# table; on by default so unattended runs do not dead-end on motion failures).
AUTOMATIC_SAFE_DEGRADATION_DEFAULTS: dict[str, str] = {
    "video": "keep_still",
    "motion": "keep_still",
}

# Manual mode: pause after these primary stages when the Channel has not
# listed explicit human_checkpoints. Export is intentionally excluded so the
# final approve of Composer (or Review) can release automatic export.
MANUAL_DEFAULT_CHECKPOINT_STAGES: tuple[str, ...] = (
    "script",
    "voice",
    "timing",
    "segments",
    "scenes",
    "images",
    "videos",
    "review",
    "composer",
)

# Aliases accepted in human_checkpoints for convenience.
_CHECKPOINT_ALIASES: dict[str, str] = {
    "script_approval": "script",
    "story": "script",
    "tts": "voice",
    "audio": "voice",
    "alignment": "timing",
    "force_alignment": "timing",
    "segmenter": "segments",
    "scene_director": "scenes",
    "scene_blueprint": "scenes",
    "storyboard": "images",
    "image": "images",
    "animator": "videos",
    "video": "videos",
    "assemble": "composer",
    "editor": "composer",
    "timeline": "composer",
}


@dataclass(frozen=True)
class ExecutionPolicy:
    """Resolved execution-mode policy for one Job run.

    ``checkpoint_node_ids`` is what the engine pauses after (step 2.6).
    ``checkpoint_refs`` is the human-facing list of stage keys / node ids the
    Channel or mode default contributed before graph resolution.
    """

    mode: str
    checkpoint_node_ids: tuple[str, ...] = ()
    checkpoint_refs: tuple[str, ...] = ()
    # Automatic policy block
    provider_retries: int = AUTOMATIC_PROVIDER_RETRIES
    fallback_after_retry_exhaustion: bool = True
    pause_only_on_critical_semantic: bool = False
    max_repairs_per_scene: int | None = None
    safe_degradation: Mapping[str, str] = field(default_factory=dict)
    auto_export_when_gates_pass: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["safe_degradation"] = dict(self.safe_degradation)
        payload["checkpoint_node_ids"] = list(self.checkpoint_node_ids)
        payload["checkpoint_refs"] = list(self.checkpoint_refs)
        return payload


def normalize_execution_mode(mode: str | None) -> str:
    text = str(mode or "").strip().lower() or "manual"
    if text not in EXECUTION_MODES:
        return "manual"
    return text


def human_checkpoints_from_snapshot(
    snapshot: Mapping[str, Any] | None,
) -> list[str]:
    """Read ``review_policy.human_checkpoints`` from a channel snapshot."""
    if not isinstance(snapshot, Mapping):
        return []
    review = snapshot.get("review_policy")
    if not isinstance(review, Mapping):
        dump = getattr(review, "model_dump", None)
        if callable(dump):
            review = dump(mode="json")
        else:
            return []
    raw = review.get("human_checkpoints") if isinstance(review, Mapping) else None
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _thresholds_from_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {}
    review = snapshot.get("review_policy")
    if not isinstance(review, Mapping):
        dump = getattr(review, "model_dump", None)
        if callable(dump):
            review = dump(mode="json")
        else:
            return {}
    if not isinstance(review, Mapping):
        return {}
    thresholds = review.get("thresholds")
    return dict(thresholds) if isinstance(thresholds, Mapping) else {}


def _safe_degradation_from_thresholds(
    thresholds: Mapping[str, Any],
) -> dict[str, str]:
    raw = thresholds.get("safe_degradation")
    if isinstance(raw, Mapping):
        return {
            str(k).strip(): str(v).strip()
            for k, v in raw.items()
            if str(k).strip() and str(v).strip()
        }
    if isinstance(raw, str) and raw.strip():
        mode = raw.strip()
        return {"video": mode, "motion": mode}
    if thresholds.get("keep_still_on_video_failure") in (True, 1, "1", "true", "yes"):
        return dict(AUTOMATIC_SAFE_DEGRADATION_DEFAULTS)
    return {}


def _optional_int(thresholds: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key not in thresholds or thresholds[key] is None:
            continue
        try:
            value = int(thresholds[key])
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def configured_checkpoint_refs(
    mode: str,
    *,
    human_checkpoints: Sequence[str] | None = None,
    workflow_checkpoints: Sequence[str] | None = None,
) -> list[str]:
    """Stage/node refs that this mode should pause on (before graph resolve).

    * automatic — none (pause only via critical / unrecoverable policy)
    * assisted — Channel ``human_checkpoints``; fall back to graph-authored
      ``extensions.approval_checkpoints`` when the Channel list is empty
    * manual — Channel list when non-empty, else the default important stages
    """
    mode = normalize_execution_mode(mode)
    configured = [str(item).strip() for item in (human_checkpoints or []) if str(item).strip()]
    authored = [
        str(item).strip() for item in (workflow_checkpoints or []) if str(item).strip()
    ]
    if mode == "automatic":
        return []
    if mode == "assisted":
        return configured if configured else authored
    # manual
    if configured:
        return configured
    return list(MANUAL_DEFAULT_CHECKPOINT_STAGES)


def workflow_authored_checkpoints(workflow: Mapping[str, Any] | None) -> list[str]:
    """Node ids listed under ``extensions.approval_checkpoints`` on a graph."""
    if not isinstance(workflow, Mapping):
        return []
    extensions = workflow.get("extensions")
    if not isinstance(extensions, Mapping):
        return []
    raw = extensions.get("approval_checkpoints")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _node_map(workflow: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for node in workflow.get("nodes") or []:
        if not isinstance(node, Mapping):
            continue
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id.strip():
            nodes[node_id] = dict(node)
    return nodes


def _primary_node_for_stage(
    stage_key: str,
    *,
    assignment: Mapping[str, list[str]],
    nodes: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """Pick the primary (non-side-branch) member of a stage to pause after."""
    members = assignment.get(stage_key) or []
    if not members:
        return None
    for node_id in members:
        node = nodes.get(node_id) or {}
        type_key = str(node.get("type") or "")
        if PRIMARY_STAGE_BY_TYPE.get(type_key) == stage_key:
            return node_id
    # Fall back to the last member (stable topo order) so a stage that only
    # has atypical types still gets a pause point.
    return members[-1] if members else None


def resolve_checkpoint_node_ids(
    workflow: Mapping[str, Any],
    checkpoint_refs: Sequence[str],
) -> list[str]:
    """Map stage keys / node ids / type keys onto graph node ids.

    Unknown refs are skipped (never invent nodes). Order follows
    ``checkpoint_refs``; duplicates collapse.
    """
    if not checkpoint_refs:
        return []
    nodes = _node_map(workflow)
    if not nodes:
        return []

    try:
        assignment = assign_nodes_to_stages(workflow)
    except Exception:
        assignment = {key: [] for key in STAGE_KEYS}

    # type_key → node ids in topo / document order
    by_type: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        type_key = str(node.get("type") or "")
        if type_key:
            by_type.setdefault(type_key, []).append(node_id)

    resolved: list[str] = []
    seen: set[str] = set()

    def _add(node_id: str | None) -> None:
        if not node_id or node_id not in nodes or node_id in seen:
            return
        seen.add(node_id)
        resolved.append(node_id)

    for raw in checkpoint_refs:
        ref = str(raw or "").strip()
        if not ref:
            continue
        # 1) Exact node id.
        if ref in nodes:
            _add(ref)
            continue
        # 2) Stage key (or alias).
        stage = _CHECKPOINT_ALIASES.get(ref, ref)
        if stage in STAGE_KEYS:
            _add(_primary_node_for_stage(stage, assignment=assignment, nodes=nodes))
            continue
        # 3) Registry type key (unique or first).
        type_matches = by_type.get(ref) or []
        if type_matches:
            _add(type_matches[0])
            continue
        # 4) PRIMARY_STAGE_BY_TYPE reverse — e.g. "story.generate"
        mapped_stage = PRIMARY_STAGE_BY_TYPE.get(ref)
        if mapped_stage:
            _add(
                _primary_node_for_stage(
                    mapped_stage, assignment=assignment, nodes=nodes
                )
            )

    return resolved


def resolve_execution_policy(
    job: Any,
    workflow: Mapping[str, Any] | None = None,
) -> ExecutionPolicy:
    """Build the effective :class:`ExecutionPolicy` for a Job (+ optional graph)."""
    if isinstance(job, Mapping):
        mode = normalize_execution_mode(job.get("execution_mode"))
        snapshot = job.get("channel_snapshot")
        snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    else:
        mode = normalize_execution_mode(getattr(job, "execution_mode", None))
        snap = getattr(job, "channel_snapshot", None)
        snapshot = snap if isinstance(snap, Mapping) else {}

    human = human_checkpoints_from_snapshot(snapshot)
    authored = workflow_authored_checkpoints(workflow)
    refs = configured_checkpoint_refs(
        mode,
        human_checkpoints=human,
        workflow_checkpoints=authored,
    )
    node_ids: list[str] = []
    if workflow is not None:
        node_ids = resolve_checkpoint_node_ids(workflow, refs)

    thresholds = _thresholds_from_snapshot(snapshot)
    channel_scene_cap = _optional_int(
        thresholds, "max_repairs_per_scene", "max_repair_cycles_per_scene"
    )
    channel_degrade = _safe_degradation_from_thresholds(thresholds)

    if mode == "automatic":
        max_per_scene = (
            channel_scene_cap
            if channel_scene_cap is not None
            else AUTOMATIC_MAX_REPAIRS_PER_SCENE
        )
        safe_deg = (
            channel_degrade
            if channel_degrade
            else dict(AUTOMATIC_SAFE_DEGRADATION_DEFAULTS)
        )
        return ExecutionPolicy(
            mode=mode,
            checkpoint_node_ids=tuple(node_ids),
            checkpoint_refs=tuple(refs),
            provider_retries=AUTOMATIC_PROVIDER_RETRIES,
            fallback_after_retry_exhaustion=True,
            pause_only_on_critical_semantic=True,
            max_repairs_per_scene=max_per_scene,
            safe_degradation=safe_deg,
            auto_export_when_gates_pass=True,
        )

    # Manual / Assisted share Channel repair thresholds as-is; checkpoints
    # differ (handled via refs/node_ids above).
    return ExecutionPolicy(
        mode=mode,
        checkpoint_node_ids=tuple(node_ids),
        checkpoint_refs=tuple(refs),
        provider_retries=AUTOMATIC_PROVIDER_RETRIES,
        fallback_after_retry_exhaustion=True,
        pause_only_on_critical_semantic=False,
        max_repairs_per_scene=channel_scene_cap,
        safe_degradation=channel_degrade,
        auto_export_when_gates_pass=mode != "manual",
    )


def apply_execution_policy_to_workflow(
    workflow: Mapping[str, Any],
    job: Any,
) -> dict[str, Any]:
    """Stamp mode policy onto a workflow document for the engine.

    Sets ``extensions.approval_checkpoints`` from the resolved policy so
    Assisted/Manual pause at exactly their configured nodes and Automatic
    carries an empty list (no human mid-pipeline pause). Also records a
    non-secret ``extensions.execution_policy`` summary for diagnostics.
    """
    document = deepcopy(dict(workflow))
    policy = resolve_execution_policy(job, document)
    extensions = dict(document.get("extensions") or {})
    # Mode is authoritative for Job runs: replace any author-time list so
    # Automatic never inherits a leftover assisted checkpoint graph.
    extensions["approval_checkpoints"] = list(policy.checkpoint_node_ids)
    extensions["execution_mode"] = policy.mode
    extensions["execution_policy"] = {
        "mode": policy.mode,
        "checkpoint_node_ids": list(policy.checkpoint_node_ids),
        "checkpoint_refs": list(policy.checkpoint_refs),
        "pause_only_on_critical_semantic": policy.pause_only_on_critical_semantic,
        "max_repairs_per_scene": policy.max_repairs_per_scene,
        "safe_degradation": dict(policy.safe_degradation),
        "auto_export_when_gates_pass": policy.auto_export_when_gates_pass,
        "provider_retries": policy.provider_retries,
        "fallback_after_retry_exhaustion": policy.fallback_after_retry_exhaustion,
    }
    document["extensions"] = extensions
    return document


def checkpoint_reason_for_node(
    node: Mapping[str, Any] | None,
    *,
    stage_key: str | None = None,
) -> str:
    """Map a paused node to a contracts.md §11 reason code."""
    stage = stage_key
    if stage is None and isinstance(node, Mapping):
        type_key = str(node.get("type") or "")
        stage = PRIMARY_STAGE_BY_TYPE.get(type_key)
    if stage == "script":
        return "script_approval"
    if stage == "review":
        return "critical_issue"
    return "policy"


def should_pause_for_escalation(
    *,
    execution_mode: str | None,
    severity: str | None,
    code: str | None = None,
) -> bool:
    """Whether an escalate decision should stop the Job for a human.

    Automatic mode pauses only on critical semantic issues (or unrecoverable
    codes that have no safe degradation path). Manual/Assisted always pause.
    """
    mode = normalize_execution_mode(execution_mode)
    if mode != "automatic":
        return True
    sev = str(severity or "").strip().lower()
    if sev == "critical":
        return True
    # Unrecoverable codes that already exhausted repair / routing.
    if code in {
        "REPAIR_LIMIT_REACHED",
        "UNROUTABLE",
        "BUDGET_EXCEEDED",
    }:
        return True
    return False


__all__ = [
    "AUTOMATIC_MAX_REPAIRS_PER_SCENE",
    "AUTOMATIC_PROVIDER_RETRIES",
    "AUTOMATIC_SAFE_DEGRADATION_DEFAULTS",
    "MANUAL_DEFAULT_CHECKPOINT_STAGES",
    "ExecutionPolicy",
    "apply_execution_policy_to_workflow",
    "checkpoint_reason_for_node",
    "configured_checkpoint_refs",
    "human_checkpoints_from_snapshot",
    "normalize_execution_mode",
    "resolve_checkpoint_node_ids",
    "resolve_execution_policy",
    "should_pause_for_escalation",
    "workflow_authored_checkpoints",
]
