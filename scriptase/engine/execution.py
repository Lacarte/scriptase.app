"""Asynchronous workflow execution orchestration for the HTTP API.

Step 3.5 replaces V2's unbounded per-project drain threads with a single
bounded global work pool. Per-project FIFO ordering is preserved: at most one
execution runs per project at a time, and a project's pending runs start in
submission order. The global ceiling (``max_global_workers``) caps how many
projects may execute concurrently.
"""

from __future__ import annotations

import os
import random
import string
import threading
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from config import GLOBAL_WORK_POOL_SIZE, OUTPUT_DIR, generate_project_id
from scriptase.shared.io_utils import JobStore, now_iso

from .adapters.common import PROJECT_ID_RE
from .approval import (
    APPROVED_STATUS,
    EXPIRED_STATUS,
    REJECTED_STATUS,
    ApprovalCheckpoint,
    ApprovalError,
    approval_summary,
    approvals_root,
    decide_checkpoint,
    delete_resume_state,
    expire_if_due,
    find_awaiting_for_execution,
    load_checkpoint,
    load_resume_state,
    resume_root,
)
from .events import EventBroker, ExecutionEventBuffer, TERMINAL_STATUSES
from .models import ExecutionRecord, NodeExecutionRecord, QueueRecord
from .notifications import dispatch_run_notification
from .persistence import (
    generate_execution_id,
    list_queue_records,
    load_execution,
    save_execution,
    save_queue_record,
)
from .registry import get_node_type
from .sample_data import validate_port_payload
from .scheduler import WorkflowScheduler, calculate_scope, resolve_executor
from .validation import validate_workflow, validation_errors

# Non-terminal durable pause — must never be treated as a finished run.
AWAITING_APPROVAL_STATUS = "awaiting_approval"


class ExecutionRequestError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass
class ActiveExecution:
    scheduler: WorkflowScheduler
    stop_event: threading.Event
    queue_record: QueueRecord
    thread: threading.Thread | None = None


def _transient_workflow_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "wf_" + "".join(random.SystemRandom().choices(alphabet, k=6))


def prepare_snapshot(
    document: Mapping[str, Any],
    *,
    input_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshot = deepcopy(dict(document))
    if "workflow_id" not in snapshot:
        snapshot["workflow_id"] = _transient_workflow_id()
    timestamp = now_iso()
    snapshot.setdefault("created_at", timestamp)
    snapshot.setdefault("updated_at", timestamp)
    provided_inputs = {
        (str(node_id), str(port_id))
        for node_id, ports in (input_overrides or {}).items()
        for port_id in ports
    }
    problems = validation_errors(validate_workflow(
        snapshot,
        require_identity=True,
        require_complete=True,
        provided_inputs=provided_inputs,
    ))
    if problems:
        raise ExecutionRequestError(
            "WORKFLOW_INVALID", "Workflow has validation errors", details={"problems": problems}
        )
    return snapshot


def resolve_scope(
    workflow: Mapping[str, Any],
    run_mode: str,
    target_node_ids: list[str],
    *,
    provided_inputs: set[tuple[str, str]] | None = None,
) -> list[str]:
    nodes = {node["id"]: node for node in workflow.get("nodes", [])}
    try:
        scope = calculate_scope(workflow, run_mode, target_node_ids)
    except ValueError as exc:
        raise ExecutionRequestError("BAD_REQUEST", str(exc)) from exc
    if run_mode != "node_isolated":
        return scope

    target = target_node_ids[0]
    # Isolation deliberately ignores normal upstream nodes. Required inputs
    # must be supplied by directly connected Sample Input stubs **or** by
    # input_overrides / input_bindings from the artifact input picker (4.1).
    incoming = [edge for edge in workflow.get("edges", []) if edge["target_node"] == target]
    stub_ids = {
        edge["source_node"] for edge in incoming
        if nodes[edge["source_node"]].get("type") == "stub.input"
    }
    overrides = provided_inputs or set()
    definition = get_node_type(nodes[target]["type"])
    for port in definition.get("inputs", []):
        if not port.get("required"):
            continue
        port_id = port["id"]
        if (target, port_id) in overrides:
            continue
        sources = [edge["source_node"] for edge in incoming if edge["target_port"] == port_id]
        if not sources or any(source not in stub_ids for source in sources):
            raise ExecutionRequestError(
                "MISSING_REQUIRED_INPUT",
                f"Isolated node {target} requires Sample Input data or an input "
                f"binding for port {port_id}",
            )
    scope = stub_ids | {target}
    return [node_id for node_id in nodes if node_id in scope]


def resolve_project_id(workflow: Mapping[str, Any], requested: str | None) -> str:
    if requested is not None and (not isinstance(requested, str) or not PROJECT_ID_RE.fullmatch(requested)):
        raise ExecutionRequestError("BAD_REQUEST", "project_id must match pp_/pm_XXXXXX")
    existing = [
        (node.get("configuration") or {}).get("project_id")
        for node in workflow.get("nodes", [])
        if node.get("type") == "project.existing" and not node.get("disabled")
    ]
    existing = [value for value in existing if value]
    if len(set(existing)) > 1:
        raise ExecutionRequestError("WORKFLOW_INVALID", "Enabled existing-project nodes disagree")
    if existing and requested and existing[0] != requested:
        raise ExecutionRequestError("WORKFLOW_INVALID", "Requested project_id disagrees with project.existing")
    return requested or (existing[0] if existing else generate_project_id("pm"))


class ExecutionManager:
    def __init__(
        self,
        *,
        output_dir: str = OUTPUT_DIR,
        max_events: int = 1000,
        executor_resolver=resolve_executor,
        max_global_workers: int | None = None,
    ):
        self.output_dir = output_dir
        self.execution_root = os.path.join(output_dir, "workflows", "executions")
        self.queue_root = os.path.join(output_dir, "workflows", "queue")
        self.active = JobStore()
        self.events = EventBroker(max_events=max_events)
        self.executor_resolver = executor_resolver
        workers = (
            GLOBAL_WORK_POOL_SIZE
            if max_global_workers is None
            else int(max_global_workers)
        )
        if isinstance(max_global_workers, bool) or workers < 1:
            raise ValueError("max_global_workers must be a positive integer")
        self.max_global_workers = workers
        # Admission lock for the global pool + per-project FIFOs.
        self._queue_lock = threading.Lock()
        # project_id → pending handles in submission order.
        self._project_queues: dict[str, deque[ActiveExecution]] = {}
        # Projects that currently occupy a pool slot (one execution each).
        self._running_projects: set[str] = set()
        # Fair rotation of projects waiting for a free pool slot.
        self._ready_projects: deque[str] = deque()
        self._running_count = 0

    @property
    def running_count(self) -> int:
        """Number of executions currently occupying a global pool slot."""
        with self._queue_lock:
            return self._running_count

    def start(
        self,
        workflow: Mapping[str, Any],
        *,
        run_mode: str,
        target_node_ids: list[str],
        project_id: str | None = None,
        force: bool = False,
        source: str = "manual",
        input_overrides: Mapping[str, Mapping[str, Any]] | None = None,
        input_bindings: Mapping[str, Mapping[str, Any]] | None = None,
        source_artifact_ids: Mapping[str, list[str]] | None = None,
        current_job_id: str | None = None,
        checkpoint_after_node_ids: list[str] | None = None,
    ) -> tuple[str, str]:
        if source not in {"manual", "schedule", "watch", "webhook"}:
            raise ExecutionRequestError("BAD_REQUEST", "Unsupported run source")
        overrides = dict(input_overrides or {})
        recorded_sources: dict[str, list[str]] = {
            str(node_id): list(ids)
            for node_id, ids in (source_artifact_ids or {}).items()
        }
        if input_bindings:
            try:
                from scriptase.artifacts.input_sources import (
                    InputSourceError,
                    port_types_for_workflow,
                    resolve_input_bindings,
                )
            except ImportError as exc:  # pragma: no cover
                raise ExecutionRequestError(
                    "BAD_REQUEST", "Input bindings are unavailable"
                ) from exc
            try:
                bound_overrides, bound_sources = resolve_input_bindings(
                    input_bindings,
                    current_job_id=current_job_id,
                    port_types=port_types_for_workflow(workflow),
                )
            except InputSourceError as exc:
                status_code = "BAD_REQUEST"
                if exc.code in {
                    "ARTIFACT_NOT_FOUND",
                    "ARTIFACT_MISSING",
                    "ARTIFACT_SUPERSEDED",
                    "ARTIFACT_INVALID",
                    "SAMPLE_FIXTURE_MISSING",
                    "RUN_DEPS",
                }:
                    status_code = exc.code
                raise ExecutionRequestError(
                    status_code, exc.message, details=exc.details or None
                ) from exc
            # Explicit overrides win over bindings on the same port.
            for node_id, ports in bound_overrides.items():
                merged = dict(ports)
                merged.update(overrides.get(node_id) or {})
                overrides[node_id] = merged
            for node_id, ids in bound_sources.items():
                existing = list(recorded_sources.get(node_id) or [])
                existing.extend(ids)
                recorded_sources[node_id] = list(dict.fromkeys(existing))

        overrides = self._validate_input_overrides(workflow, overrides)
        snapshot = prepare_snapshot(workflow, input_overrides=overrides)
        provided = {
            (str(node_id), str(port_id))
            for node_id, ports in overrides.items()
            for port_id in ports
        }
        scope = resolve_scope(
            snapshot, run_mode, target_node_ids, provided_inputs=provided
        )
        resolved_project = resolve_project_id(snapshot, project_id)
        execution_id = generate_execution_id(root=self.execution_root)
        stream = self.events.create(execution_id)
        stop_event = threading.Event()
        queue_record = QueueRecord(
            execution_id=execution_id,
            workflow_id=snapshot["workflow_id"],
            project_id=resolved_project,
            source=source,
            requested_run_mode=run_mode,
            target_node_ids=list(target_node_ids),
            requested_at=now_iso(),
        )

        def emit(event: dict[str, Any]) -> None:
            # Persist the queue transition before publishing the terminal SSE;
            # clients may refresh the queue as soon as they receive it.
            if event.get("node_id") is None and event.get("status") in TERMINAL_STATUSES:
                status = event["status"]
                queue_record.status = (
                    "done" if status in {"succeeded", "partial"}
                    else "cancelled" if status == "cancelled"
                    else "failed"
                )
                queue_record.finished_at = now_iso()
                save_queue_record(queue_record, root=self.queue_root)
            elif (
                event.get("node_id") is None
                and event.get("status") == AWAITING_APPROVAL_STATUS
            ):
                queue_record.status = AWAITING_APPROVAL_STATUS
                queue_record.finished_at = None
                save_queue_record(queue_record, root=self.queue_root)
            stream.emit(event)

        scheduler = WorkflowScheduler(
            snapshot,
            project_id=resolved_project,
            execution_id=execution_id,
            output_dir=self.output_dir,
            run_mode=run_mode,
            scope_node_ids=scope,
            stop_requested=stop_event.is_set,
            on_event=emit,
            executor_resolver=self.executor_resolver,
            force=force,
            input_overrides=overrides,
            source_artifact_ids=recorded_sources,
            checkpoint_after_node_ids=checkpoint_after_node_ids,
        )
        scheduler.record.status = "queued"
        save_execution(scheduler.record, root=self.execution_root, secrets=scheduler.redactor.secrets)
        stream.emit({"type": "execution_status", "node_id": None, "status": "queued"})
        save_queue_record(queue_record, root=self.queue_root)
        handle = ActiveExecution(
            scheduler=scheduler, stop_event=stop_event, queue_record=queue_record
        )
        self.active.set(execution_id, handle)
        self._enqueue(resolved_project, handle)
        return execution_id, resolved_project

    @staticmethod
    def _validate_input_overrides(
        workflow: Mapping[str, Any],
        supplied: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(supplied, Mapping):
            raise ExecutionRequestError("BAD_REQUEST", "input_overrides must be an object")
        nodes = {node.get("id"): node for node in workflow.get("nodes", []) if isinstance(node, Mapping)}
        result: dict[str, dict[str, Any]] = {}
        for node_id, ports in supplied.items():
            node = nodes.get(node_id)
            if node is None or node.get("disabled"):
                raise ExecutionRequestError("BAD_REQUEST", f"Input override node is unavailable: {node_id}")
            if not isinstance(ports, Mapping):
                raise ExecutionRequestError("BAD_REQUEST", "Input override ports must be an object")
            definition = get_node_type(node.get("type")) or {}
            known = {port.get("id"): port for port in definition.get("inputs", [])}
            result[str(node_id)] = {}
            for port_id, value in ports.items():
                port = known.get(port_id)
                port_type = port.get("type") if port else None
                if port_type == "dynamic":
                    port_type = (node.get("configuration") or {}).get("port_type")
                # Overrides may carry managed artifact paths (4.1) as well as
                # fixture refs; use the managed-aware structural validator.
                problems = validate_port_payload(port_type, value) if port else []
                if not port or port_type == "control" or problems:
                    raise ExecutionRequestError(
                        "BAD_REQUEST", f"Input override {node_id}.{port_id} is not valid {port_type or 'data'}",
                        details={"problems": problems} if problems else None,
                    )
                result[str(node_id)][str(port_id)] = value
        return result

    # ------------------------------------------------------------------
    # Global work pool (step 3.5)
    # ------------------------------------------------------------------

    def _enqueue(self, project_id: str, handle: ActiveExecution) -> None:
        """Append to the project's FIFO and try to admit work into the pool."""
        with self._queue_lock:
            queue = self._project_queues.setdefault(project_id, deque())
            queue.append(handle)
            self._mark_ready_locked(project_id)
            self._dispatch_locked()

    def _mark_ready_locked(self, project_id: str) -> None:
        """Queue *project_id* for a pool slot if it has pending work and is idle."""
        if project_id in self._running_projects:
            return
        if project_id in self._ready_projects:
            return
        queue = self._project_queues.get(project_id)
        if not queue:
            return
        # Only ready if at least one non-cancelled handle is waiting.
        if not any(h.queue_record.status == "pending" for h in queue):
            return
        self._ready_projects.append(project_id)

    def _dispatch_locked(self) -> None:
        """Fill free pool slots from the ready-project rotation (FIFO per project)."""
        while self._running_count < self.max_global_workers and self._ready_projects:
            project_id = self._ready_projects.popleft()
            if project_id in self._running_projects:
                continue
            queue = self._project_queues.get(project_id)
            if not queue:
                self._project_queues.pop(project_id, None)
                continue

            handle: ActiveExecution | None = None
            while queue:
                candidate = queue.popleft()
                if candidate.queue_record.status == "cancelled":
                    continue
                if candidate.queue_record.status != "pending":
                    continue
                handle = candidate
                break
            if not queue:
                self._project_queues.pop(project_id, None)
            if handle is None:
                continue

            handle.queue_record.status = "running"
            handle.queue_record.started_at = now_iso()
            handle.scheduler.record.status = "running"
            handle.scheduler.record.started_at = handle.queue_record.started_at
            save_queue_record(handle.queue_record, root=self.queue_root)
            save_execution(
                handle.scheduler.record,
                root=self.execution_root,
                secrets=handle.scheduler.redactor.secrets,
            )

            self._running_projects.add(project_id)
            self._running_count += 1
            worker = threading.Thread(
                target=self._pool_worker,
                args=(project_id, handle),
                name=f"workflow-pool-{handle.scheduler.execution_id}",
                daemon=True,
            )
            handle.thread = worker
            worker.start()

    def _pool_worker(self, project_id: str, handle: ActiveExecution) -> None:
        """Run one admitted execution, then free the slot and dispatch more."""
        try:
            handle.thread = threading.current_thread()
            self._run(handle, self.events.create(handle.scheduler.execution_id))
        finally:
            with self._queue_lock:
                self._running_projects.discard(project_id)
                self._running_count = max(0, self._running_count - 1)
                # Re-arm this project if more pending work remains, then fill slots.
                self._mark_ready_locked(project_id)
                self._dispatch_locked()

    def _run(self, handle: ActiveExecution, stream: ExecutionEventBuffer) -> None:
        try:
            handle.scheduler.run()
        except Exception as exc:  # lock acquisition and scheduler setup boundary
            record = handle.scheduler.record
            status = "cancelled" if handle.stop_event.is_set() else "failed"
            record.status = status
            record.finished_at = now_iso()
            save_execution(record, root=self.execution_root, secrets=handle.scheduler.redactor.secrets)
            handle.queue_record.status = "cancelled" if status == "cancelled" else "failed"
            handle.queue_record.finished_at = record.finished_at
            save_queue_record(handle.queue_record, root=self.queue_root)
            stream.emit({
                "type": "execution_finished",
                "node_id": None,
                "status": status,
                "error": {
                    "code": getattr(exc, "code", "NODE_EXECUTION_FAILED"),
                    "message": str(exc),
                },
            })
        finally:
            status = handle.scheduler.record.status
            if status == AWAITING_APPROVAL_STATUS:
                # Durable pause: release the worker, leave finished_at null,
                # and do not dispatch a terminal notification.
                handle.queue_record.status = AWAITING_APPROVAL_STATUS
                handle.queue_record.finished_at = None
                save_queue_record(handle.queue_record, root=self.queue_root)
                return
            handle.queue_record.status = (
                "done" if status in {"succeeded", "partial"}
                else "cancelled" if status == "cancelled"
                else "failed"
            )
            handle.queue_record.finished_at = handle.scheduler.record.finished_at or now_iso()
            save_queue_record(handle.queue_record, root=self.queue_root)
            try:
                dispatch_run_notification(
                    handle.scheduler.workflow,
                    handle.scheduler.record.to_dict(),
                    output_dir=self.output_dir,
                )
            except Exception:
                # Notification persistence/delivery is best effort and cannot
                # retroactively turn a completed workflow into a failed run.
                pass

    def stop(self, execution_id: str) -> str:
        record = load_execution(execution_id, root=self.execution_root)
        if record.get("status") in TERMINAL_STATUSES:
            raise ExecutionRequestError("EXECUTION_TERMINAL", "Execution is already terminal")
        # Cancelling a durable pause is a terminal decision, not a live stop.
        if record.get("status") == AWAITING_APPROVAL_STATUS:
            return self._cancel_awaiting_approval(execution_id, record)
        handle = self.active.get(execution_id)
        if handle is None:
            raise ExecutionRequestError("EXECUTION_NOT_ACTIVE", "Execution is not active")
        with self._queue_lock:
            if handle.queue_record.status == "pending":
                self._cancel_pending_locked(handle)
                return "cancelled"
        handle.stop_event.set()
        self.events.create(execution_id).emit({
            "type": "execution_status", "node_id": None, "status": "cancelling"
        })
        return "cancelling"

    def approve(
        self,
        execution_id: str,
        *,
        decided_by: str | None = None,
        checkpoint_id: str | None = None,
    ) -> str:
        """Approve a durable checkpoint and resume the same execution.

        Survives process restart: loads resume state from disk, re-queues the
        project worker, and continues from the exact pause point.
        """
        return self._decide_and_resume(
            execution_id,
            decision=APPROVED_STATUS,
            decided_by=decided_by,
            checkpoint_id=checkpoint_id,
        )

    def reject(
        self,
        execution_id: str,
        *,
        decided_by: str | None = None,
        checkpoint_id: str | None = None,
    ) -> str:
        """Reject a durable checkpoint and mark the execution failed."""
        record = load_execution(execution_id, root=self.execution_root)
        if record.get("status") in TERMINAL_STATUSES:
            raise ExecutionRequestError("EXECUTION_TERMINAL", "Execution is already terminal")
        if record.get("status") != AWAITING_APPROVAL_STATUS:
            raise ExecutionRequestError(
                "EXECUTION_NOT_AWAITING",
                "Execution is not awaiting approval",
            )
        checkpoint = self._resolve_checkpoint(execution_id, record, checkpoint_id)
        try:
            decide_checkpoint(
                checkpoint.checkpoint_id,
                decision=REJECTED_STATUS,
                decided_by=decided_by,
                root=approvals_root(self.output_dir),
            )
        except ApprovalError as exc:
            raise ExecutionRequestError(exc.code, exc.message, details=exc.details) from exc
        timestamp = now_iso()
        record["status"] = "failed"
        record["finished_at"] = timestamp
        approval = dict(record.get("approval") or {})
        approval["status"] = REJECTED_STATUS
        approval["decided_by"] = decided_by or "user"
        approval["decided_at"] = timestamp
        record["approval"] = approval
        node_id = approval.get("node_id") or checkpoint.node_id
        nodes = record.get("nodes") if isinstance(record.get("nodes"), dict) else {}
        if node_id and node_id in nodes and isinstance(nodes[node_id], dict):
            nodes[node_id]["status"] = "failed"
            nodes[node_id]["error"] = {
                "code": "APPROVAL_REJECTED",
                "message": "Checkpoint was rejected",
            }
        save_execution(record, root=self.execution_root)
        # Drop any stale in-memory handle so subsequent loads read disk.
        self.active.pop(execution_id, None)
        try:
            delete_resume_state(execution_id, root=resume_root(self.output_dir))
        except Exception:
            pass
        self.events.create(execution_id).emit({
            "type": "execution_finished",
            "node_id": None,
            "status": "failed",
            "approval": approval,
        })
        return "failed"

    def _decide_and_resume(
        self,
        execution_id: str,
        *,
        decision: str,
        decided_by: str | None,
        checkpoint_id: str | None,
    ) -> str:
        record = load_execution(execution_id, root=self.execution_root)
        if record.get("status") in TERMINAL_STATUSES:
            raise ExecutionRequestError("EXECUTION_TERMINAL", "Execution is already terminal")
        if record.get("status") != AWAITING_APPROVAL_STATUS:
            raise ExecutionRequestError(
                "EXECUTION_NOT_AWAITING",
                "Execution is not awaiting approval",
            )
        checkpoint = self._resolve_checkpoint(execution_id, record, checkpoint_id)
        # Honour expiry policy before approving.
        try:
            refreshed = expire_if_due(
                checkpoint.checkpoint_id,
                root=approvals_root(self.output_dir),
            )
            if refreshed.status == EXPIRED_STATUS:
                self._mark_execution_expired(execution_id, record, refreshed)
                raise ExecutionRequestError(
                    "APPROVAL_EXPIRED",
                    "Checkpoint expired before approval",
                    details={"checkpoint_id": refreshed.checkpoint_id},
                )
            decide_checkpoint(
                checkpoint.checkpoint_id,
                decision=decision,
                decided_by=decided_by,
                root=approvals_root(self.output_dir),
            )
        except ApprovalError as exc:
            if exc.code == "APPROVAL_EXPIRED":
                self._mark_execution_expired(execution_id, record, checkpoint)
            raise ExecutionRequestError(exc.code, exc.message, details=exc.details) from exc

        if decision != APPROVED_STATUS:
            return decision

        try:
            resume_state = load_resume_state(
                execution_id, root=resume_root(self.output_dir)
            )
        except ApprovalError as exc:
            raise ExecutionRequestError(exc.code, exc.message, details=exc.details) from exc

        # Rebuild an ExecutionRecord so resume keeps the same execution_id.
        existing = self._record_from_document(record)
        approval = dict(record.get("approval") or {})
        approval["status"] = APPROVED_STATUS
        approval["decided_by"] = decided_by or "user"
        approval["decided_at"] = now_iso()
        existing.approval = approval
        existing.status = "queued"
        existing.finished_at = None

        snapshot = deepcopy(resume_state.workflow_snapshot)
        # Drop the approved node from extensions so the scheduler does not
        # pause on it again after resume promotes it to succeeded.
        extensions = snapshot.get("extensions")
        if isinstance(extensions, dict):
            raw_checkpoints = extensions.get("approval_checkpoints")
            if isinstance(raw_checkpoints, list):
                extensions = dict(extensions)
                extensions["approval_checkpoints"] = [
                    node_id
                    for node_id in raw_checkpoints
                    if str(node_id) != resume_state.checkpoint_node_id
                ]
                snapshot["extensions"] = extensions

        stop_event = threading.Event()
        queue_record = QueueRecord(
            execution_id=execution_id,
            workflow_id=str(snapshot.get("workflow_id") or existing.workflow_id),
            project_id=resume_state.project_id or existing.project_id,
            source="manual",
            requested_run_mode=resume_state.run_mode or existing.run_mode,
            target_node_ids=[],
            requested_at=now_iso(),
            status="pending",
        )
        stream = self.events.create(execution_id)

        def emit(event: dict[str, Any]) -> None:
            if event.get("node_id") is None and event.get("status") in TERMINAL_STATUSES:
                status = event["status"]
                queue_record.status = (
                    "done" if status in {"succeeded", "partial"}
                    else "cancelled" if status == "cancelled"
                    else "failed"
                )
                queue_record.finished_at = now_iso()
                save_queue_record(queue_record, root=self.queue_root)
            elif (
                event.get("node_id") is None
                and event.get("status") == AWAITING_APPROVAL_STATUS
            ):
                queue_record.status = AWAITING_APPROVAL_STATUS
                queue_record.finished_at = None
                save_queue_record(queue_record, root=self.queue_root)
            stream.emit(event)

        scheduler = WorkflowScheduler(
            snapshot,
            project_id=resume_state.project_id,
            execution_id=execution_id,
            output_dir=self.output_dir,
            run_mode=resume_state.run_mode,
            scope_node_ids=list(resume_state.scope_node_ids),
            stop_requested=stop_event.is_set,
            on_event=emit,
            executor_resolver=self.executor_resolver,
            force=resume_state.force,
            input_overrides=resume_state.input_overrides,
            resume_state=resume_state,
            existing_record=existing,
        )
        save_execution(scheduler.record, root=self.execution_root, secrets=scheduler.redactor.secrets)
        save_queue_record(queue_record, root=self.queue_root)
        stream.emit({
            "type": "execution_status",
            "node_id": None,
            "status": "queued",
            "approval": approval,
        })

        handle = ActiveExecution(
            scheduler=scheduler, stop_event=stop_event, queue_record=queue_record
        )
        self.active.set(execution_id, handle)
        self._enqueue(resume_state.project_id, handle)
        return "resuming"

    def _resolve_checkpoint(
        self,
        execution_id: str,
        record: Mapping[str, Any],
        checkpoint_id: str | None,
    ) -> ApprovalCheckpoint:
        if checkpoint_id:
            try:
                return load_checkpoint(
                    checkpoint_id, root=approvals_root(self.output_dir)
                )
            except ApprovalError as exc:
                raise ExecutionRequestError(exc.code, exc.message, details=exc.details) from exc
        approval = record.get("approval") if isinstance(record.get("approval"), Mapping) else {}
        linked = approval.get("checkpoint_id") if isinstance(approval, Mapping) else None
        if linked:
            try:
                return load_checkpoint(str(linked), root=approvals_root(self.output_dir))
            except ApprovalError as exc:
                raise ExecutionRequestError(exc.code, exc.message, details=exc.details) from exc
        found = find_awaiting_for_execution(
            execution_id, root=approvals_root(self.output_dir)
        )
        if found is None:
            raise ExecutionRequestError(
                "CHECKPOINT_NOT_FOUND",
                "No awaiting checkpoint for this execution",
            )
        return found

    def _mark_execution_expired(
        self,
        execution_id: str,
        record: dict[str, Any],
        checkpoint: ApprovalCheckpoint,
    ) -> None:
        timestamp = now_iso()
        record["status"] = "failed"
        record["finished_at"] = timestamp
        approval = approval_summary(checkpoint)
        approval["status"] = EXPIRED_STATUS
        approval["decided_at"] = timestamp
        approval["decided_by"] = checkpoint.decided_by or "policy"
        record["approval"] = approval
        node_id = checkpoint.node_id
        nodes = record.get("nodes") if isinstance(record.get("nodes"), dict) else {}
        if node_id and node_id in nodes and isinstance(nodes[node_id], dict):
            nodes[node_id]["status"] = "failed"
            nodes[node_id]["error"] = {
                "code": "APPROVAL_EXPIRED",
                "message": "Checkpoint expired before approval",
            }
        save_execution(record, root=self.execution_root)
        self.active.pop(execution_id, None)
        try:
            delete_resume_state(execution_id, root=resume_root(self.output_dir))
        except Exception:
            pass
        self.events.create(execution_id).emit({
            "type": "execution_finished",
            "node_id": None,
            "status": "failed",
            "approval": approval,
        })

    def _cancel_awaiting_approval(
        self,
        execution_id: str,
        record: dict[str, Any],
    ) -> str:
        timestamp = now_iso()
        approval = dict(record.get("approval") or {})
        checkpoint_id = approval.get("checkpoint_id")
        if checkpoint_id:
            try:
                decide_checkpoint(
                    str(checkpoint_id),
                    decision=REJECTED_STATUS,
                    decided_by="cancel",
                    root=approvals_root(self.output_dir),
                )
            except ApprovalError:
                pass
        record["status"] = "cancelled"
        record["finished_at"] = timestamp
        approval["status"] = REJECTED_STATUS
        approval["decided_by"] = "cancel"
        approval["decided_at"] = timestamp
        record["approval"] = approval
        node_id = approval.get("node_id")
        nodes = record.get("nodes") if isinstance(record.get("nodes"), dict) else {}
        if node_id and node_id in nodes and isinstance(nodes[node_id], dict):
            nodes[node_id]["status"] = "cancelled"
        save_execution(record, root=self.execution_root)
        self.active.pop(execution_id, None)
        try:
            delete_resume_state(execution_id, root=resume_root(self.output_dir))
        except Exception:
            pass
        self.events.create(execution_id).emit({
            "type": "execution_finished",
            "node_id": None,
            "status": "cancelled",
        })
        return "cancelled"

    @staticmethod
    def _record_from_document(document: Mapping[str, Any]) -> ExecutionRecord:
        nodes_raw = document.get("nodes") if isinstance(document.get("nodes"), Mapping) else {}
        nodes: dict[str, NodeExecutionRecord] = {}
        for node_id, raw in nodes_raw.items():
            if not isinstance(raw, Mapping):
                nodes[str(node_id)] = NodeExecutionRecord()
                continue
            nodes[str(node_id)] = NodeExecutionRecord(
                status=str(raw.get("status") or "idle"),
                attempts=int(raw.get("attempts") or 0),
                duration_ms=raw.get("duration_ms"),
                fingerprint=raw.get("fingerprint"),
                cache=dict(raw["cache"]) if isinstance(raw.get("cache"), Mapping) else None,
                from_sample_data=bool(raw.get("from_sample_data")),
                resolved_inputs_summary=dict(raw.get("resolved_inputs_summary") or {}),
                outputs_summary=dict(raw.get("outputs_summary") or {}),
                artifact_refs=list(raw.get("artifact_refs") or []),
                source_artifact_ids=list(raw.get("source_artifact_ids") or []),
                logs=list(raw.get("logs") or []),
                attempt_errors=list(raw.get("attempt_errors") or []),
                error=dict(raw["error"]) if isinstance(raw.get("error"), Mapping) else None,
            )
        return ExecutionRecord(
            execution_id=str(document.get("execution_id") or ""),
            workflow_id=str(document.get("workflow_id") or ""),
            workflow_snapshot=dict(document.get("workflow_snapshot") or {}),
            project_id=str(document.get("project_id") or ""),
            run_mode=str(document.get("run_mode") or "full"),
            scope_node_ids=list(document.get("scope_node_ids") or []),
            status=str(document.get("status") or "running"),
            started_at=str(document.get("started_at") or ""),
            finished_at=document.get("finished_at"),
            nodes=nodes,
            approval=dict(document["approval"]) if isinstance(document.get("approval"), Mapping) else None,
            schema_version=int(document.get("schema_version") or 1),
        )

    def _cancel_pending_locked(self, handle: ActiveExecution) -> None:
        timestamp = now_iso()
        handle.stop_event.set()
        handle.queue_record.status = "cancelled"
        handle.queue_record.finished_at = timestamp
        handle.scheduler.record.status = "cancelled"
        handle.scheduler.record.finished_at = timestamp
        for node_id in handle.scheduler.scope_node_ids:
            handle.scheduler.record.nodes[node_id].status = "cancelled"
        save_queue_record(handle.queue_record, root=self.queue_root)
        save_execution(
            handle.scheduler.record,
            root=self.execution_root,
            secrets=handle.scheduler.redactor.secrets,
        )
        self.events.create(handle.scheduler.execution_id).emit({
            "type": "execution_finished", "node_id": None, "status": "cancelled"
        })

    def cancel_pending(self, execution_id: str) -> str:
        handle = self.active.get(execution_id)
        if handle is None:
            try:
                record = load_execution(execution_id, root=self.execution_root)
            except FileNotFoundError:
                raise
            if record.get("status") in TERMINAL_STATUSES:
                raise ExecutionRequestError("EXECUTION_TERMINAL", "Execution is already terminal")
            raise ExecutionRequestError("EXECUTION_NOT_ACTIVE", "Execution is not active")
        with self._queue_lock:
            if handle.queue_record.status != "pending":
                raise ExecutionRequestError("QUEUE_NOT_PENDING", "Only pending runs can be cancelled")
            self._cancel_pending_locked(handle)
        return "cancelled"

    def list_queue(self, workflow_id: str, *, limit: int = 100) -> tuple[list[dict], int]:
        return list_queue_records(workflow_id, limit=limit, root=self.queue_root)


execution_manager = ExecutionManager()
