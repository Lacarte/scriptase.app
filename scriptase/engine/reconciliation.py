"""Crash recovery and startup reconciliation (step 10.3).

A hard kill mid-run leaves execution/queue/job documents in non-terminal
states, project lockfiles whose owner pid is dead, and ArtifactPromoter
staging directories that nobody will clean. On the next boot this module:

1. Marks interrupted executions (``running`` / ``queued``) as ``failed``
2. Marks matching queue records as ``failed``
3. Marks Jobs that were mid-run as ``failed`` (``awaiting_approval`` stays —
   it is a durable pause that survives restart)
4. Removes stale project lockfiles (dead owner pid)
5. Removes orphaned ``workflows/.staging`` directories

``awaiting_approval`` is intentionally preserved: step 2.6 released the
worker and wrote resume state so the next process can approve and continue.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from config import OUTPUT_DIR, WORKFLOW_EXECUTIONS_DIR
from scriptase.shared.io_utils import now_iso

from .events import TERMINAL_STATUSES
from .persistence import (
    EXECUTION_ID_RE,
    EXECUTIONS_DIR,
    QUEUE_DIR,
    load_execution,
    load_queue_record,
    save_execution,
    save_queue_record,
)
from .scheduler import clear_stale_project_locks

# In-flight statuses that cannot survive a process restart.
_INTERRUPTED_EXECUTION_STATUSES = frozenset({"running", "queued"})
_INTERRUPTED_QUEUE_STATUSES = frozenset({"pending", "running"})
_INTERRUPTED_NODE_STATUSES = frozenset({"running", "queued", "waiting"})

# Durable pause — must not be collapsed into a failure on reboot.
AWAITING_APPROVAL_STATUS = "awaiting_approval"

PROCESS_INTERRUPTED_CODE = "PROCESS_INTERRUPTED"
PROCESS_INTERRUPTED_MESSAGE = (
    "The process stopped while this run was in progress."
)
PROCESS_INTERRUPTED_SUGGESTION = (
    "Start a new run, or retry the failed nodes from the last successful stage."
)
JOB_STATUS_REASON = "process_interrupted"


@dataclass
class ReconciliationReport:
    """Summary of what startup reconciliation changed."""

    executions_failed: list[str] = field(default_factory=list)
    queue_failed: list[str] = field(default_factory=list)
    jobs_failed: list[str] = field(default_factory=list)
    locks_cleared: list[str] = field(default_factory=list)
    staging_removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.executions_failed
            or self.queue_failed
            or self.jobs_failed
            or self.locks_cleared
            or self.staging_removed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "executions_failed": list(self.executions_failed),
            "queue_failed": list(self.queue_failed),
            "jobs_failed": list(self.jobs_failed),
            "locks_cleared": list(self.locks_cleared),
            "staging_removed": list(self.staging_removed),
            "changed": self.changed,
        }


def _interrupted_error(*, node_id: str | None = None, node_name: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": PROCESS_INTERRUPTED_CODE,
        "message": PROCESS_INTERRUPTED_MESSAGE,
        "recovery_suggestion": PROCESS_INTERRUPTED_SUGGESTION,
        "timestamp": now_iso(),
        "details": {"reason": "startup_reconciliation"},
    }
    if node_id:
        payload["node_id"] = node_id
    if node_name:
        payload["node_name"] = node_name
    return payload


def _iter_execution_ids(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    ids: list[str] = []
    for filename in os.listdir(directory):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        if ".workflow_snapshot." in filename:
            continue
        execution_id = filename[:-5]
        if EXECUTION_ID_RE.fullmatch(execution_id):
            ids.append(execution_id)
    return ids


def fail_interrupted_execution(
    record: dict[str, Any],
    *,
    execution_root: str | None = None,
) -> dict[str, Any]:
    """Mark a mid-run execution record as failed and persist it.

    Idempotent for already-terminal documents. Does not touch
    ``awaiting_approval``.
    """
    status = str(record.get("status") or "")
    if status in TERMINAL_STATUSES or status == AWAITING_APPROVAL_STATUS:
        return record

    finished_at = now_iso()
    nodes = record.get("nodes")
    if isinstance(nodes, dict):
        for node_id, node in list(nodes.items()):
            if not isinstance(node, dict):
                continue
            node_status = str(node.get("status") or "")
            if node_status in _INTERRUPTED_NODE_STATUSES:
                node["status"] = "failed"
                if not node.get("error"):
                    node["error"] = _interrupted_error(
                        node_id=node_id,
                        node_name=str(node.get("name") or node_id),
                    )
                attempt_errors = node.get("attempt_errors")
                if not isinstance(attempt_errors, list):
                    attempt_errors = []
                    node["attempt_errors"] = attempt_errors
                attempt_errors.append(dict(node["error"]))

    record["status"] = "failed"
    record["finished_at"] = finished_at
    # Clear a stray approval pointer so a failed interrupted run does not
    # look like a durable pause (only awaiting_approval keeps resume state).
    if isinstance(record.get("approval"), dict):
        record["approval"] = None

    return save_execution(record, root=execution_root, mode="full")


def fail_interrupted_queue_record(
    record: dict[str, Any],
    *,
    queue_root: str | None = None,
) -> dict[str, Any]:
    """Mark a pending/running queue record as failed."""
    status = str(record.get("status") or "")
    if status not in _INTERRUPTED_QUEUE_STATUSES:
        return record
    record["status"] = "failed"
    record["finished_at"] = record.get("finished_at") or now_iso()
    return save_queue_record(record, root=queue_root)


def reconcile_executions(
    *,
    execution_root: str | None = None,
    queue_root: str | None = None,
) -> tuple[list[str], list[str]]:
    """Fail every execution/queue document left mid-flight by a crash."""
    executions_dir = execution_root or EXECUTIONS_DIR
    queue_dir = queue_root or QUEUE_DIR
    failed_executions: list[str] = []
    failed_queue: list[str] = []

    for execution_id in _iter_execution_ids(executions_dir):
        try:
            record = load_execution(execution_id, root=executions_dir)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        status = str(record.get("status") or "")
        if status in TERMINAL_STATUSES or status == AWAITING_APPROVAL_STATUS:
            continue
        # running / queued / any other non-terminal status cannot stay live.
        try:
            fail_interrupted_execution(record, execution_root=executions_dir)
            failed_executions.append(execution_id)
        except Exception as exc:
            logger.warning(
                "[reconciliation] failed to repair execution {}: {}",
                execution_id,
                exc,
            )

    if os.path.isdir(queue_dir):
        for filename in os.listdir(queue_dir):
            if not filename.endswith(".json") or filename.endswith(".json.bak"):
                continue
            execution_id = filename[:-5]
            if not EXECUTION_ID_RE.fullmatch(execution_id):
                continue
            try:
                record = load_queue_record(execution_id, root=queue_dir)
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            if str(record.get("status") or "") not in _INTERRUPTED_QUEUE_STATUSES:
                continue
            try:
                fail_interrupted_queue_record(record, queue_root=queue_dir)
                failed_queue.append(execution_id)
            except Exception as exc:
                logger.warning(
                    "[reconciliation] failed to repair queue {}: {}",
                    execution_id,
                    exc,
                )

    return failed_executions, failed_queue


def reconcile_jobs() -> list[str]:
    """Fail Jobs that were mid-run when the process died.

    Rules:

    * ``running`` → ``failed`` (always)
    * ``queued`` **with** an ``execution_id`` → ``failed`` (was started)
    * ``queued`` without ``execution_id`` → leave (not yet started by the user)
    * ``awaiting_approval`` → leave (durable pause; step 2.6)
    * terminal statuses → leave
    """
    # Local import keeps the engine free of a hard jobs package cycle at
    # module import time (jobs.orchestration imports the execution manager).
    from scriptase.jobs.models import TERMINAL_STATUSES as JOB_TERMINAL
    from scriptase.jobs.store import list_jobs, update_job

    failed: list[str] = []
    try:
        candidates = list_jobs(limit=10_000)
    except Exception as exc:
        logger.warning("[reconciliation] could not list jobs: {}", exc)
        return failed

    finished_at = now_iso()
    for job in candidates:
        status = job.status
        if status in JOB_TERMINAL or status == AWAITING_APPROVAL_STATUS:
            continue
        if status == "queued" and not job.execution_id:
            continue
        if status not in {"running", "queued"}:
            continue
        try:
            update_job(
                job.id,
                status="failed",
                status_reason=JOB_STATUS_REASON,
                completed_at=finished_at,
            )
            failed.append(job.id)
        except Exception as exc:
            logger.warning(
                "[reconciliation] failed to repair job {}: {}",
                job.id,
                exc,
            )
    return failed


def clear_orphaned_staging(
    *,
    output_dir: str | None = None,
) -> list[str]:
    """Remove every directory under ``workflows/.staging``.

    Staging is only meaningful while a live process holds an
    :class:`ArtifactPromoter`. After a crash (or on a clean boot) nothing
    will promote those files, so the whole tree is safe to discard.
    """
    root = os.path.abspath(output_dir or OUTPUT_DIR)
    staging_root = os.path.join(root, "workflows", ".staging")
    if not os.path.isdir(staging_root):
        return []
    removed: list[str] = []
    for name in os.listdir(staging_root):
        path = os.path.join(staging_root, name)
        if not os.path.isdir(path):
            # Leftover files are also orphans.
            try:
                os.unlink(path)
                removed.append(name)
            except OSError as exc:
                logger.warning(
                    "[reconciliation] failed to remove staging file {}: {}",
                    path,
                    exc,
                )
            continue
        try:
            shutil.rmtree(path, ignore_errors=False)
            removed.append(name)
        except OSError as exc:
            logger.warning(
                "[reconciliation] failed to remove staging dir {}: {}",
                path,
                exc,
            )
            # Best-effort second pass so a partial tree does not linger forever.
            shutil.rmtree(path, ignore_errors=True)
            if not os.path.exists(path):
                removed.append(name)
    return removed


def default_lock_root(*, output_dir: str | None = None) -> str:
    return os.path.join(os.path.abspath(output_dir or OUTPUT_DIR), "workflows", "locks")


def reconcile_on_startup(
    *,
    output_dir: str | None = None,
    execution_root: str | None = None,
    queue_root: str | None = None,
    lock_root: str | None = None,
    reconcile_jobs_flag: bool = True,
) -> ReconciliationReport:
    """Run the full crash-recovery pass. Safe to call more than once.

    Ordered so document repairs happen before lock/staging cleanup: a later
    attempt to re-run a project can then acquire a free lock and a clean
    staging root.
    """
    root = os.path.abspath(output_dir or OUTPUT_DIR)
    executions = execution_root or (
        os.path.join(root, "workflows", "executions")
        if output_dir is not None
        else WORKFLOW_EXECUTIONS_DIR
    )
    queue = queue_root or os.path.join(os.path.dirname(executions), "queue")
    locks = lock_root or default_lock_root(output_dir=root)

    report = ReconciliationReport()
    try:
        report.executions_failed, report.queue_failed = reconcile_executions(
            execution_root=executions,
            queue_root=queue,
        )
    except Exception as exc:
        logger.exception("[reconciliation] execution/queue pass failed: {}", exc)

    if reconcile_jobs_flag:
        try:
            report.jobs_failed = reconcile_jobs()
        except Exception as exc:
            logger.exception("[reconciliation] jobs pass failed: {}", exc)

    try:
        report.locks_cleared = clear_stale_project_locks(locks)
    except Exception as exc:
        logger.exception("[reconciliation] lock cleanup failed: {}", exc)

    try:
        report.staging_removed = clear_orphaned_staging(output_dir=root)
    except Exception as exc:
        logger.exception("[reconciliation] staging cleanup failed: {}", exc)

    if report.changed:
        logger.info(
            "[reconciliation] startup repair: executions={} queue={} jobs={} "
            "locks={} staging={}",
            len(report.executions_failed),
            len(report.queue_failed),
            len(report.jobs_failed),
            len(report.locks_cleared),
            len(report.staging_removed),
        )
    else:
        logger.debug("[reconciliation] nothing to repair")
    return report


__all__ = [
    "AWAITING_APPROVAL_STATUS",
    "JOB_STATUS_REASON",
    "PROCESS_INTERRUPTED_CODE",
    "ReconciliationReport",
    "clear_orphaned_staging",
    "default_lock_root",
    "fail_interrupted_execution",
    "fail_interrupted_queue_record",
    "reconcile_executions",
    "reconcile_jobs",
    "reconcile_on_startup",
]
