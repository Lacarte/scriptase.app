"""Asynchronous workflow execution orchestration for the HTTP API."""

from __future__ import annotations

import os
import random
import string
import threading
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from config import OUTPUT_DIR, generate_project_id
from scriptase.shared.io_utils import JobStore, now_iso

from .adapters.common import PROJECT_ID_RE
from .events import EventBroker, ExecutionEventBuffer, TERMINAL_STATUSES
from .models import QueueRecord
from .notifications import dispatch_run_notification
from .persistence import (
    generate_execution_id,
    list_queue_records,
    load_execution,
    save_execution,
    save_queue_record,
)
from .registry import get_node_type
from .sample_data import validate_stub_payload
from .scheduler import WorkflowScheduler, calculate_scope, resolve_executor
from .validation import validate_workflow, validation_errors


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


def resolve_scope(workflow: Mapping[str, Any], run_mode: str, target_node_ids: list[str]) -> list[str]:
    nodes = {node["id"]: node for node in workflow.get("nodes", [])}
    try:
        scope = calculate_scope(workflow, run_mode, target_node_ids)
    except ValueError as exc:
        raise ExecutionRequestError("BAD_REQUEST", str(exc)) from exc
    if run_mode != "node_isolated":
        return scope

    target = target_node_ids[0]
    # Isolation deliberately ignores normal upstream nodes. Required inputs
    # must instead be supplied by directly connected Sample Input nodes.
    incoming = [edge for edge in workflow.get("edges", []) if edge["target_node"] == target]
    stub_ids = {
        edge["source_node"] for edge in incoming
        if nodes[edge["source_node"]].get("type") == "stub.input"
    }
    definition = get_node_type(nodes[target]["type"])
    for port in definition.get("inputs", []):
        if not port.get("required"):
            continue
        sources = [edge["source_node"] for edge in incoming if edge["target_port"] == port["id"]]
        if not sources or any(source not in stub_ids for source in sources):
            raise ExecutionRequestError(
                "MISSING_REQUIRED_INPUT",
                f"Isolated node {target} requires Sample Input data for port {port['id']}",
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
    ):
        self.output_dir = output_dir
        self.execution_root = os.path.join(output_dir, "workflows", "executions")
        self.queue_root = os.path.join(output_dir, "workflows", "queue")
        self.active = JobStore()
        self.events = EventBroker(max_events=max_events)
        self.executor_resolver = executor_resolver
        self._queue_lock = threading.Lock()
        self._project_queues: dict[str, deque[ActiveExecution]] = {}
        self._project_workers: dict[str, threading.Thread] = {}

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
    ) -> tuple[str, str]:
        if source not in {"manual", "schedule", "watch", "webhook"}:
            raise ExecutionRequestError("BAD_REQUEST", "Unsupported run source")
        overrides = self._validate_input_overrides(workflow, input_overrides or {})
        snapshot = prepare_snapshot(workflow, input_overrides=overrides)
        scope = resolve_scope(snapshot, run_mode, target_node_ids)
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
        )
        scheduler.record.status = "queued"
        save_execution(scheduler.record, root=self.execution_root, secrets=scheduler.redactor.secrets)
        stream.emit({"type": "execution_status", "node_id": None, "status": "queued"})
        save_queue_record(queue_record, root=self.queue_root)
        handle = ActiveExecution(
            scheduler=scheduler, stop_event=stop_event, queue_record=queue_record
        )
        self.active.set(execution_id, handle)
        with self._queue_lock:
            queue = self._project_queues.setdefault(resolved_project, deque())
            queue.append(handle)
            worker = self._project_workers.get(resolved_project)
            if worker is None or not worker.is_alive():
                worker = threading.Thread(
                    target=self._drain_project,
                    args=(resolved_project,),
                    name=f"workflow-queue-{resolved_project}",
                    daemon=True,
                )
                self._project_workers[resolved_project] = worker
                handle.thread = worker
                worker.start()
            else:
                handle.thread = worker
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
                problems = validate_stub_payload(port_type, value) if port else []
                if not port or port_type == "control" or problems:
                    raise ExecutionRequestError(
                        "BAD_REQUEST", f"Input override {node_id}.{port_id} is not valid {port_type or 'data'}",
                        details={"problems": problems} if problems else None,
                    )
                result[str(node_id)][str(port_id)] = value
        return result

    def _drain_project(self, project_id: str) -> None:
        """Drain one project's FIFO without occupying workers for other projects."""
        while True:
            with self._queue_lock:
                queue = self._project_queues.get(project_id)
                if not queue:
                    self._project_queues.pop(project_id, None)
                    self._project_workers.pop(project_id, None)
                    return
                handle = queue.popleft()
                if handle.queue_record.status == "cancelled":
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
            handle.thread = threading.current_thread()
            self._run(handle, self.events.create(handle.scheduler.execution_id))

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
