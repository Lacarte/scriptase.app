"""Job store — atomic create/read/update with durable channel snapshots.

Persistence layout: ``output/jobs/{job_id}.json`` via ``safe_json_write`` /
``safe_json_read``. Soft-delete moves the primary file (and its ``.bak``) into
``output/TRASH/jobs/``, matching the channel store's trash discipline.

Starting a Job freezes a non-secret Channel snapshot (provider instance
references only). Runtime fields — status, artifact ids, execution_id — update
in place so a process restart reloads the same document.
"""

from __future__ import annotations

import os
import random
import shutil
import string
import threading
from copy import deepcopy
from typing import Any, Iterable

from config import JOBS_DIR, TRASH_DIR
from scriptase.channels.store import ChannelNotFound, get_channel
from scriptase.jobs.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.jobs.models import (
    JOB_ID_RE,
    TERMINAL_STATUSES,
    BudgetSpent,
    Job,
    parse_draft,
    parse_job,
    validation_problems,
)
from scriptase.jobs.snapshot import (
    assert_snapshot_has_no_credentials,
    build_channel_snapshot,
)
from scriptase.jobs.source_modes import validate_job_source
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

from pydantic import ValidationError


class JobNotFound(FileNotFoundError):
    """Raised when a job id does not resolve on disk."""

    def __init__(self, job_id: str):
        super().__init__(job_id)
        self.job_id = job_id
        self.code = "JOB_NOT_FOUND"


class JobTerminal(RuntimeError):
    """Operation invalid for a completed / failed / cancelled job."""

    def __init__(self, job_id: str, status: str):
        super().__init__(f"Job {job_id} is terminal ({status})")
        self.job_id = job_id
        self.status = status
        self.code = "JOB_TERMINAL"


class JobValidationError(ValueError):
    """Schema validation failed; ``problems`` carries structured details."""

    def __init__(self, problems: list[dict[str, Any]]):
        super().__init__("Job document failed schema validation")
        self.problems = problems
        self.code = "JOB_INVALID"


# Module-level roots so tests can rebind without patching config.
_jobs_dir: str = JOBS_DIR
_trash_dir: str = os.path.join(TRASH_DIR, "jobs")

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _path(job_id: str) -> str:
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id must match job_[A-Z0-9]{6}")
    return safe_join(_jobs_dir, f"{job_id}.json")


def _generate_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "job_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(_path(candidate)):
            return candidate
    raise RuntimeError("Could not allocate a job id")


def _validate_document(data: dict[str, Any]) -> Job:
    try:
        return parse_job(data)
    except ValidationError as exc:
        raise JobValidationError(validation_problems(exc)) from exc


def _validate_draft(data: dict[str, Any]):
    try:
        return parse_draft(data)
    except ValidationError as exc:
        raise JobValidationError(validation_problems(exc)) from exc


def _jobs_index():
    from scriptase.engine.storage_index import get_storage_index, jobs_index_path
    return get_storage_index(jobs_index_path(_jobs_dir))


def _index_job(document: Job) -> None:
    try:
        _jobs_index().upsert_job(document.to_document())
    except Exception:
        pass


def _ensure_jobs_index() -> None:
    from scriptase.engine.storage_index import count_json_documents

    index = _jobs_index()
    file_count = count_json_documents(_jobs_dir, id_prefix="job_")
    if file_count > 0 and index.count_jobs() == 0:

        def _load_summary(job_id: str) -> dict[str, Any]:
            # Avoid get_job (which re-enters indexing / migration writes) during
            # rebuild — read and migrate the raw document only.
            raw = safe_json_read(_path(job_id))
            migrated, _changed = apply_migrations(raw)
            return {
                "id": migrated.get("id") or job_id,
                "channel_id": migrated.get("channel_id"),
                "status": migrated.get("status"),
                "created_at": migrated.get("created_at"),
                "workflow_id": migrated.get("workflow_id"),
                "execution_id": migrated.get("execution_id"),
            }

        index.rebuild_jobs(_jobs_dir, load_summary=_load_summary)


def _write(document: Job) -> Job:
    assert_snapshot_has_no_credentials(document.channel_snapshot)
    os.makedirs(_jobs_dir, exist_ok=True)
    path = _path(document.id)
    safe_json_write(path, document.to_document(), indent=2)
    _index_job(document)
    return document


def _load_raw(job_id: str) -> dict[str, Any]:
    path = _path(job_id)
    try:
        return safe_json_read(path)
    except FileNotFoundError as exc:
        raise JobNotFound(job_id) from exc


def create_job(draft: dict[str, Any]) -> Job:
    """Start a Job from a draft: load Channel, freeze snapshot, persist.

    The snapshot captures non-secret Channel configuration and provider
    instance references only. Credentials never enter the document.

    Script-stage source modes are validated here (step 2.5): Paste / Manual
    require final text; Topic / Idea require their seed field. Provider
    credentials are never required at create time.
    """
    parsed = _validate_draft(draft)

    source_payload = (
        parsed.source.model_dump(mode="json")
        if hasattr(parsed.source, "model_dump")
        else dict(parsed.source or {})
    )
    source_problems = validate_job_source(source_payload)
    if source_problems:
        raise JobValidationError(source_problems)

    try:
        channel = get_channel(parsed.channel_id)
    except ChannelNotFound as exc:
        raise JobValidationError([{
            "loc": ["channel_id"],
            "msg": f"channel not found: {parsed.channel_id}",
            "type": "value_error",
        }]) from exc

    snapshot = build_channel_snapshot(channel)
    assert_snapshot_has_no_credentials(snapshot)

    workflow_id = parsed.workflow_id or channel.default_workflow_id
    timestamp = now_iso()
    document = Job(
        id=_generate_id(),
        schema_version=SCHEMA_VERSION,
        channel_id=channel.id,
        channel_snapshot=snapshot,
        workflow_id=workflow_id,
        workflow_version=parsed.workflow_version,
        execution_mode=parsed.execution_mode,
        source=parsed.source,
        status="queued",
        status_reason=None,
        current_stage=None,
        artifacts=[],
        scenes=[],
        issues=[],
        repair_history=[],
        budget_spent=BudgetSpent(),
        execution_id=None,
        created_at=timestamp,
        started_at=None,
        completed_at=None,
    )
    return _write(document)


def get_job(job_id: str) -> Job:
    """Load, migrate, and validate a Job. Raises JobNotFound."""
    raw = _load_raw(job_id)
    migrated, changed = apply_migrations(raw)
    document = _validate_document(migrated)
    # Snapshot gate on every load — a corrupted on-disk file must not re-enter
    # the system with credentials.
    assert_snapshot_has_no_credentials(document.channel_snapshot)
    if changed:
        _write(document)
    return document


def list_jobs(
    *,
    channel_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[Job]:
    """Return jobs newest-first (by created_at, then id)."""
    os.makedirs(_jobs_dir, exist_ok=True)
    try:
        _ensure_jobs_index()
        job_ids = _jobs_index().list_job_ids(
            channel_id=channel_id, status=status, limit=limit
        )
        items: list[Job] = []
        for job_id in job_ids:
            try:
                items.append(get_job(job_id))
            except (JobNotFound, JobValidationError, ValueError, OSError):
                continue
        # Re-sort after load: index order matches created_at, but migration
        # edge cases are cheap to normalize.
        items.sort(
            key=lambda item: (item.created_at or "", item.id),
            reverse=True,
        )
        return items[:limit]
    except Exception:
        return _list_jobs_scan(channel_id=channel_id, status=status, limit=limit)


def _list_jobs_scan(
    *,
    channel_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[Job]:
    items: list[Job] = []
    for filename in os.listdir(_jobs_dir):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        job_id = filename[:-5]
        if not JOB_ID_RE.fullmatch(job_id):
            continue
        try:
            job = get_job(job_id)
        except (JobNotFound, JobValidationError, ValueError, OSError):
            continue
        if channel_id is not None and job.channel_id != channel_id:
            continue
        if status is not None and job.status != status:
            continue
        items.append(job)
    items.sort(
        key=lambda item: (item.created_at or "", item.id),
        reverse=True,
    )
    return items[:limit]


def _require_mutable(job: Job) -> None:
    if job.status in TERMINAL_STATUSES:
        raise JobTerminal(job.id, job.status)


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    status_reason: str | None | object = ...,
    current_stage: str | None | object = ...,
    artifacts: list[str] | None = None,
    scenes: list[str] | None = None,
    issues: list[str] | None = None,
    repair_history: list[str] | None = None,
    budget_spent: dict[str, Any] | BudgetSpent | None = None,
    execution_id: str | None | object = ...,
    started_at: str | None | object = ...,
    completed_at: str | None | object = ...,
    allow_terminal: bool = False,
) -> Job:
    """Update runtime fields on a Job.

    Identity fields (``channel_id``, ``channel_snapshot``, ``workflow_id``,
    ``execution_mode``, ``source``, ``created_at``) are immutable after create.

    Pass ``...`` (Ellipsis) for optional scalar fields to leave them unchanged;
    pass ``None`` to clear them. List fields default to no-op when ``None``.

    Terminal jobs reject updates unless ``allow_terminal=True`` (used for
    post-completion bookkeeping that must still be durable).
    """
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id must match job_[A-Z0-9]{6}")

    lock = _thread_lock(job_id)
    with lock:
        current = get_job(job_id)
        if not allow_terminal:
            _require_mutable(current)

        next_status = status if status is not None else current.status
        next_reason = (
            current.status_reason
            if status_reason is ...
            else status_reason
        )
        next_stage = (
            current.current_stage
            if current_stage is ...
            else current_stage
        )
        next_execution_id = (
            current.execution_id
            if execution_id is ...
            else execution_id
        )
        next_started = (
            current.started_at if started_at is ... else started_at
        )
        next_completed = (
            current.completed_at if completed_at is ... else completed_at
        )

        if budget_spent is None:
            next_budget = current.budget_spent
        elif isinstance(budget_spent, BudgetSpent):
            next_budget = budget_spent
        else:
            next_budget = BudgetSpent.model_validate(budget_spent)

        payload = {
            **current.to_document(),
            "status": next_status,
            "status_reason": next_reason,
            "current_stage": next_stage,
            "artifacts": (
                list(artifacts) if artifacts is not None else current.artifacts
            ),
            "scenes": list(scenes) if scenes is not None else current.scenes,
            "issues": list(issues) if issues is not None else current.issues,
            "repair_history": (
                list(repair_history)
                if repair_history is not None
                else current.repair_history
            ),
            "budget_spent": next_budget.model_dump(mode="json"),
            "execution_id": next_execution_id,
            "started_at": next_started,
            "completed_at": next_completed,
        }
        document = _validate_document(payload)
        return _write(document)


def add_artifact_ids(
    job_id: str,
    artifact_ids: Iterable[str],
    *,
    allow_terminal: bool = False,
) -> Job:
    """Append unique artifact ids to the Job (order-preserving)."""
    lock = _thread_lock(job_id)
    with lock:
        current = get_job(job_id)
        if not allow_terminal:
            _require_mutable(current)
        merged = list(current.artifacts)
        seen = set(merged)
        for artifact_id in artifact_ids:
            text = str(artifact_id or "").strip()
            if not text or text in seen:
                continue
            merged.append(text)
            seen.add(text)
        payload = {**current.to_document(), "artifacts": merged}
        document = _validate_document(payload)
        return _write(document)


def add_repair_history_ids(
    job_id: str,
    entry_ids: Iterable[str],
    *,
    allow_terminal: bool = False,
) -> Job:
    """Append unique RepairHistoryEntry ids to the Job (order-preserving).

    Used by step 8.4 when a repair outcome is persisted. Terminal jobs still
    accept bookkeeping when ``allow_terminal=True`` so a completed Job can
    carry its full repair sequence.
    """
    lock = _thread_lock(job_id)
    with lock:
        current = get_job(job_id)
        if not allow_terminal:
            _require_mutable(current)
        merged = list(current.repair_history)
        seen = set(merged)
        for entry_id in entry_ids:
            text = str(entry_id or "").strip()
            if not text or text in seen:
                continue
            merged.append(text)
            seen.add(text)
        payload = {**current.to_document(), "repair_history": merged}
        document = _validate_document(payload)
        return _write(document)


def delete_job(job_id: str) -> None:
    """Soft-delete: move primary (and .bak) into TRASH/jobs/."""
    if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id must match job_[A-Z0-9]{6}")

    lock = _thread_lock(job_id)
    with lock:
        path = _path(job_id)
        if not os.path.isfile(path) and not os.path.isfile(path + ".bak"):
            raise JobNotFound(job_id)

        os.makedirs(_trash_dir, exist_ok=True)
        stamp = now_iso().replace(":", "").replace("+", "_")
        dest = os.path.join(_trash_dir, f"{job_id}_{stamp}.json")
        bak_src = path + ".bak"
        bak_dest = dest + ".bak"

        if os.path.isfile(bak_src):
            try:
                os.replace(bak_src, bak_dest)
            except OSError:
                shutil.move(bak_src, bak_dest)

        if os.path.isfile(path):
            try:
                os.replace(path, dest)
            except OSError:
                shutil.move(path, dest)

        try:
            _jobs_index().delete_job(job_id)
        except Exception:
            pass


def job_summary(document: Job) -> dict[str, Any]:
    """Compact listing payload (no full snapshot)."""
    source = document.source
    source_mode = (
        source.mode if hasattr(source, "mode") else (source or {}).get("mode")
    )
    spent = document.budget_spent
    return {
        "id": document.id,
        "channel_id": document.channel_id,
        "workflow_id": document.workflow_id,
        "execution_mode": document.execution_mode,
        "source_mode": source_mode,
        "status": document.status,
        "status_reason": document.status_reason,
        "current_stage": document.current_stage,
        "artifact_count": len(document.artifacts),
        "execution_id": document.execution_id,
        "budget_spent": {
            "generations": int(spent.generations),
            "cost": float(spent.cost),
        },
        "created_at": document.created_at,
        "started_at": document.started_at,
        "completed_at": document.completed_at,
    }


def default_draft(
    *,
    channel_id: str,
    execution_mode: str = "manual",
    source: dict[str, Any] | None = None,
    workflow_id: str | None = None,
    workflow_version: int | None = None,
) -> dict[str, Any]:
    """Minimal valid create payload for callers that need a blank job draft."""
    return deepcopy({
        "channel_id": channel_id,
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "execution_mode": execution_mode,
        "source": source or {"mode": "topic", "topic": ""},
    })


__all__ = [
    "JobNotFound",
    "JobTerminal",
    "JobValidationError",
    "create_job",
    "get_job",
    "list_jobs",
    "update_job",
    "add_artifact_ids",
    "add_repair_history_ids",
    "delete_job",
    "job_summary",
    "default_draft",
]
