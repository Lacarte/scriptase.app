"""Durable approval checkpoints for the workflow engine (step 2.6).

Human checkpoints are an engine state that **releases the worker thread**, not a
blocked pool thread. A pause persists the resume point (completed node outputs
plus the checkpoint identity), survives process restart, and continues from
exactly where it stopped on approval — or expires by policy.

contracts.md §11 / product §8 Assisted mode / implementation-plan step 2.6.
Phase 9 consumes this primitive for Assisted/Automatic policy; this module is
the storage + decision surface only.
"""

from __future__ import annotations

import os
import random
import re
import string
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from config import OUTPUT_DIR
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

# ---------------------------------------------------------------------------
# Vocabulary (contracts.md §11)
# ---------------------------------------------------------------------------

CHECKPOINT_REASONS: tuple[str, ...] = (
    "script_approval",
    "critical_issue",
    "budget_ceiling",
    "policy",
    "approval",  # generic / Job status_reason conventional code
)

CHECKPOINT_STATUSES: tuple[str, ...] = (
    "awaiting",
    "approved",
    "rejected",
    "expired",
)

AWAITING_STATUS = "awaiting"
APPROVED_STATUS = "approved"
REJECTED_STATUS = "rejected"
EXPIRED_STATUS = "expired"

CHECKPOINT_ID_RE = re.compile(r"^ap_[A-Za-z0-9]{6}$")

# Default TTL when a caller requests expiry-by-policy without an absolute time.
DEFAULT_EXPIRY_HOURS = 72


class ApprovalError(RuntimeError):
    """Structured approval/checkpoint failure."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class ApprovalRequired(Exception):
    """Adapter/scheduler signal: pause the run for a human checkpoint.

    Raising this from a node executor (or synthesising it after a configured
    checkpoint node succeeds) is the engine primitive Phase 9 will drive.
    The scheduler must **not** hold a worker thread waiting on the human —
    it persists resume state and returns ``awaiting_approval``.
    """

    def __init__(
        self,
        reason: str = "policy",
        *,
        stage_key: str | None = None,
        expires_at: str | None = None,
        job_id: str | None = None,
        details: Any = None,
        # When True the node already produced outputs that must be kept and
        # applied on approval (pause-after-success). When False the node is
        # re-executed on resume.
        has_outputs: bool = False,
    ):
        message = f"Approval required ({reason})"
        super().__init__(message)
        self.code = "APPROVAL_REQUIRED"
        self.message = message
        self.reason = str(reason or "policy").strip() or "policy"
        self.stage_key = (str(stage_key).strip() or None) if stage_key else None
        self.expires_at = (str(expires_at).strip() or None) if expires_at else None
        self.job_id = (str(job_id).strip() or None) if job_id else None
        self.details = details
        self.has_outputs = bool(has_outputs)


@dataclass
class ApprovalCheckpoint:
    """Persisted human checkpoint (contracts.md §11)."""

    checkpoint_id: str
    execution_id: str
    node_id: str
    reason: str = "policy"
    status: str = AWAITING_STATUS
    job_id: str | None = None
    stage_key: str | None = None
    created_at: str = ""
    expires_at: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    # True → outputs already captured; approval promotes the node to succeeded.
    # False → node is re-run on resume.
    has_outputs: bool = False
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ApprovalCheckpoint":
        return cls(
            checkpoint_id=str(data.get("checkpoint_id") or ""),
            execution_id=str(data.get("execution_id") or ""),
            node_id=str(data.get("node_id") or ""),
            reason=str(data.get("reason") or "policy"),
            status=str(data.get("status") or AWAITING_STATUS),
            job_id=_optional_str(data.get("job_id")),
            stage_key=_optional_str(data.get("stage_key")),
            created_at=str(data.get("created_at") or ""),
            expires_at=_optional_str(data.get("expires_at")),
            decided_by=_optional_str(data.get("decided_by")),
            decided_at=_optional_str(data.get("decided_at")),
            has_outputs=bool(data.get("has_outputs")),
            schema_version=int(data.get("schema_version") or 1),
        )


@dataclass
class ResumeState:
    """Full node outputs needed to continue after a durable pause.

    Execution records only keep summaries (contracts.md §1.5); the bulky
    payloads live here so a process restart can resume from the same point.
    """

    execution_id: str
    checkpoint_id: str
    checkpoint_node_id: str
    workflow_snapshot: dict[str, Any]
    project_id: str
    run_mode: str
    scope_node_ids: list[str]
    node_statuses: dict[str, str]
    node_outputs: dict[str, dict[str, Any]]
    node_output_fingerprints: dict[str, str]
    force: bool = False
    input_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    has_outputs: bool = False
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResumeState":
        overrides_raw = data.get("input_overrides") or {}
        overrides: dict[str, dict[str, Any]] = {}
        if isinstance(overrides_raw, Mapping):
            for key, value in overrides_raw.items():
                if isinstance(value, Mapping):
                    overrides[str(key)] = dict(value)
        statuses_raw = data.get("node_statuses") or {}
        statuses = {
            str(k): str(v)
            for k, v in statuses_raw.items()
            if isinstance(k, str) or True
        } if isinstance(statuses_raw, Mapping) else {}
        outputs_raw = data.get("node_outputs") or {}
        outputs: dict[str, dict[str, Any]] = {}
        if isinstance(outputs_raw, Mapping):
            for key, value in outputs_raw.items():
                if isinstance(value, Mapping):
                    outputs[str(key)] = dict(value)
        fps_raw = data.get("node_output_fingerprints") or {}
        fps = {
            str(k): str(v)
            for k, v in (fps_raw.items() if isinstance(fps_raw, Mapping) else [])
        }
        return cls(
            execution_id=str(data.get("execution_id") or ""),
            checkpoint_id=str(data.get("checkpoint_id") or ""),
            checkpoint_node_id=str(data.get("checkpoint_node_id") or ""),
            workflow_snapshot=dict(data.get("workflow_snapshot") or {}),
            project_id=str(data.get("project_id") or ""),
            run_mode=str(data.get("run_mode") or "full"),
            scope_node_ids=[str(x) for x in (data.get("scope_node_ids") or [])],
            node_statuses=statuses,
            node_outputs=outputs,
            node_output_fingerprints=fps,
            force=bool(data.get("force")),
            input_overrides=overrides,
            has_outputs=bool(data.get("has_outputs")),
            schema_version=int(data.get("schema_version") or 1),
        )


# ---------------------------------------------------------------------------
# Paths / ids
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()


def approvals_root(output_dir: str | None = None) -> str:
    return os.path.join(output_dir or OUTPUT_DIR, "workflows", "approvals")


def resume_root(output_dir: str | None = None) -> str:
    return os.path.join(output_dir or OUTPUT_DIR, "workflows", "resume")


def checkpoint_path(checkpoint_id: str, *, root: str | None = None) -> str:
    if not isinstance(checkpoint_id, str) or not CHECKPOINT_ID_RE.fullmatch(checkpoint_id):
        raise ApprovalError("BAD_REQUEST", "checkpoint_id must match ap_XXXXXX")
    return safe_join(root or approvals_root(), f"{checkpoint_id}.json")


def resume_path(execution_id: str, *, root: str | None = None) -> str:
    if not isinstance(execution_id, str) or not re.fullmatch(r"^ex_[A-Za-z0-9]{6}$", execution_id):
        raise ApprovalError("BAD_REQUEST", "execution_id must match ex_XXXXXX")
    return safe_join(root or resume_root(), f"{execution_id}.json")


def generate_checkpoint_id(*, root: str | None = None) -> str:
    alphabet = string.ascii_uppercase + string.digits
    directory = root or approvals_root()
    os.makedirs(directory, exist_ok=True)
    for _ in range(200):
        candidate = "ap_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(os.path.join(directory, f"{candidate}.json")):
            return candidate
    raise RuntimeError("Could not allocate a checkpoint id")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_expired(checkpoint: ApprovalCheckpoint, *, now: str | None = None) -> bool:
    """True when the checkpoint has an expires_at in the past."""
    if not checkpoint.expires_at:
        return False
    deadline = _parse_iso(checkpoint.expires_at)
    if deadline is None:
        return False
    current = _parse_iso(now or now_iso()) or datetime.now(timezone.utc)
    return current >= deadline


# ---------------------------------------------------------------------------
# Checkpoint CRUD
# ---------------------------------------------------------------------------


def save_checkpoint(
    checkpoint: ApprovalCheckpoint,
    *,
    root: str | None = None,
) -> dict[str, Any]:
    document = checkpoint.to_dict()
    path = checkpoint_path(checkpoint.checkpoint_id, root=root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    safe_json_write(path, document, indent=2)
    return document


def load_checkpoint(
    checkpoint_id: str,
    *,
    root: str | None = None,
) -> ApprovalCheckpoint:
    path = checkpoint_path(checkpoint_id, root=root)
    try:
        data = safe_json_read(path)
    except FileNotFoundError as exc:
        raise ApprovalError(
            "CHECKPOINT_NOT_FOUND",
            f"Checkpoint {checkpoint_id} not found",
            details={"checkpoint_id": checkpoint_id},
        ) from exc
    return ApprovalCheckpoint.from_dict(data)


def find_awaiting_for_execution(
    execution_id: str,
    *,
    root: str | None = None,
) -> ApprovalCheckpoint | None:
    """Return the open awaiting checkpoint for an execution, if any."""
    directory = root or approvals_root()
    if not os.path.isdir(directory):
        return None
    matches: list[ApprovalCheckpoint] = []
    for filename in os.listdir(directory):
        if not filename.endswith(".json"):
            continue
        checkpoint_id = filename[:-5]
        if not CHECKPOINT_ID_RE.fullmatch(checkpoint_id):
            continue
        try:
            checkpoint = load_checkpoint(checkpoint_id, root=directory)
        except (ApprovalError, OSError, ValueError):
            continue
        if checkpoint.execution_id == execution_id and checkpoint.status == AWAITING_STATUS:
            matches.append(checkpoint)
    if not matches:
        return None
    matches.sort(key=lambda item: item.created_at or "", reverse=True)
    return matches[0]


def create_checkpoint(
    *,
    execution_id: str,
    node_id: str,
    reason: str = "policy",
    job_id: str | None = None,
    stage_key: str | None = None,
    expires_at: str | None = None,
    has_outputs: bool = False,
    root: str | None = None,
) -> ApprovalCheckpoint:
    """Allocate and persist a new awaiting checkpoint."""
    with _LOCK:
        checkpoint_id = generate_checkpoint_id(root=root)
        checkpoint = ApprovalCheckpoint(
            checkpoint_id=checkpoint_id,
            execution_id=execution_id,
            node_id=node_id,
            reason=str(reason or "policy"),
            status=AWAITING_STATUS,
            job_id=job_id,
            stage_key=stage_key,
            created_at=now_iso(),
            expires_at=expires_at,
            has_outputs=bool(has_outputs),
        )
        save_checkpoint(checkpoint, root=root)
        return checkpoint


def decide_checkpoint(
    checkpoint_id: str,
    *,
    decision: str,
    decided_by: str | None = None,
    root: str | None = None,
    now: str | None = None,
) -> ApprovalCheckpoint:
    """Approve, reject, or expire a checkpoint.

    ``decision`` is one of approved / rejected / expired.
    Awaiting checkpoints past ``expires_at`` auto-expire before an approve
    attempt and refuse the decision with ``APPROVAL_EXPIRED``.
    """
    if decision not in {APPROVED_STATUS, REJECTED_STATUS, EXPIRED_STATUS}:
        raise ApprovalError(
            "BAD_REQUEST",
            f"decision must be one of: {APPROVED_STATUS}, {REJECTED_STATUS}, {EXPIRED_STATUS}",
        )
    with _LOCK:
        checkpoint = load_checkpoint(checkpoint_id, root=root)
        if checkpoint.status != AWAITING_STATUS:
            raise ApprovalError(
                "CHECKPOINT_NOT_AWAITING",
                f"Checkpoint is already {checkpoint.status}",
                details={
                    "checkpoint_id": checkpoint_id,
                    "status": checkpoint.status,
                },
            )
        stamp = now or now_iso()
        if decision == APPROVED_STATUS and is_expired(checkpoint, now=stamp):
            checkpoint.status = EXPIRED_STATUS
            checkpoint.decided_at = stamp
            checkpoint.decided_by = decided_by or "policy"
            save_checkpoint(checkpoint, root=root)
            raise ApprovalError(
                "APPROVAL_EXPIRED",
                "Checkpoint expired before approval",
                details={
                    "checkpoint_id": checkpoint_id,
                    "expires_at": checkpoint.expires_at,
                },
            )
        checkpoint.status = decision
        checkpoint.decided_at = stamp
        checkpoint.decided_by = decided_by or ("policy" if decision == EXPIRED_STATUS else "user")
        save_checkpoint(checkpoint, root=root)
        return checkpoint


def expire_if_due(
    checkpoint_id: str,
    *,
    root: str | None = None,
    now: str | None = None,
) -> ApprovalCheckpoint:
    """Mark an awaiting checkpoint expired when past its deadline; else return as-is."""
    with _LOCK:
        checkpoint = load_checkpoint(checkpoint_id, root=root)
        if checkpoint.status != AWAITING_STATUS:
            return checkpoint
        stamp = now or now_iso()
        if not is_expired(checkpoint, now=stamp):
            return checkpoint
        checkpoint.status = EXPIRED_STATUS
        checkpoint.decided_at = stamp
        checkpoint.decided_by = "policy"
        save_checkpoint(checkpoint, root=root)
        return checkpoint


# ---------------------------------------------------------------------------
# Resume state
# ---------------------------------------------------------------------------


def save_resume_state(
    state: ResumeState,
    *,
    root: str | None = None,
) -> dict[str, Any]:
    document = state.to_dict()
    path = resume_path(state.execution_id, root=root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    safe_json_write(path, document, indent=2)
    return document


def load_resume_state(
    execution_id: str,
    *,
    root: str | None = None,
) -> ResumeState:
    path = resume_path(execution_id, root=root)
    try:
        data = safe_json_read(path)
    except FileNotFoundError as exc:
        raise ApprovalError(
            "RESUME_STATE_MISSING",
            f"No resume state for execution {execution_id}",
            details={"execution_id": execution_id},
        ) from exc
    return ResumeState.from_dict(data)


def delete_resume_state(
    execution_id: str,
    *,
    root: str | None = None,
) -> None:
    path = resume_path(execution_id, root=root)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def approval_summary(checkpoint: ApprovalCheckpoint) -> dict[str, Any]:
    """Compact pointer stored on the execution record (no bulky payloads)."""
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "node_id": checkpoint.node_id,
        "reason": checkpoint.reason,
        "status": checkpoint.status,
        "stage_key": checkpoint.stage_key,
        "job_id": checkpoint.job_id,
        "created_at": checkpoint.created_at,
        "expires_at": checkpoint.expires_at,
        "has_outputs": checkpoint.has_outputs,
        "decided_by": checkpoint.decided_by,
        "decided_at": checkpoint.decided_at,
    }


def checkpoint_node_ids_from_workflow(workflow: Mapping[str, Any]) -> list[str]:
    """Node ids listed under ``extensions.approval_checkpoints`` (pause after)."""
    extensions = workflow.get("extensions") if isinstance(workflow, Mapping) else None
    if not isinstance(extensions, Mapping):
        return []
    raw = extensions.get("approval_checkpoints")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


__all__ = [
    "CHECKPOINT_REASONS",
    "CHECKPOINT_STATUSES",
    "AWAITING_STATUS",
    "APPROVED_STATUS",
    "REJECTED_STATUS",
    "EXPIRED_STATUS",
    "CHECKPOINT_ID_RE",
    "DEFAULT_EXPIRY_HOURS",
    "ApprovalError",
    "ApprovalRequired",
    "ApprovalCheckpoint",
    "ResumeState",
    "approvals_root",
    "resume_root",
    "checkpoint_path",
    "resume_path",
    "generate_checkpoint_id",
    "is_expired",
    "save_checkpoint",
    "load_checkpoint",
    "find_awaiting_for_execution",
    "create_checkpoint",
    "decide_checkpoint",
    "expire_if_due",
    "save_resume_state",
    "load_resume_state",
    "delete_resume_state",
    "approval_summary",
    "checkpoint_node_ids_from_workflow",
]
