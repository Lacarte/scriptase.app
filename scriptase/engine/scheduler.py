"""Deterministic workflow scheduling and project serialization.

The scheduler deliberately contains no Flask state.  It consumes a validated
workflow snapshot and invokes registry adapters directly, which makes ordering
and readiness independently testable.
"""

from __future__ import annotations

import heapq
import importlib
import json
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from loguru import logger

from config import OUTPUT_DIR
from scriptase.shared.io_utils import now_iso
from scriptase.shared.security import safe_join
from scriptase.providers.errors import ProviderError
from scriptase.providers.validation import sanitize_message

from .adapters import AdapterContext, AdapterError
from .adapters.common import PROJECT_ID_RE
from .approval import (
    ApprovalRequired,
    ResumeState,
    approval_summary,
    checkpoint_node_ids_from_workflow,
    create_checkpoint,
    delete_resume_state,
    resume_root as approval_resume_root,
    save_resume_state,
    approvals_root as approval_checkpoints_root,
)
from .cache import CacheLookup, NodeCache, canonical_fingerprint, fingerprint_components, output_fingerprint
from .cost_snapshot import cost_snapshot_from_result, is_provider_node_type
from .expressions import ExpressionError, resolve_configuration, validate_expressions
from .registry import get_node_type
from .models import ExecutionLog, ExecutionRecord, NodeExecutionRecord
from .persistence import generate_execution_id, save_execution
from .redaction import Redactor
from .validation import validate_resolved_configuration, validate_workflow, validation_errors


class SchedulerError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# Exceptions whose text was authored by this codebase for a human reader.
# Everything else is a plugin exception whose `str()` may embed a third-party
# response body, an absolute path, or a stack frame (contracts.md §34.4, §36 L1).
_AUTHORED_EXCEPTIONS = (SchedulerError, AdapterError, ExpressionError, ProviderError)


def safe_failure_message(exc: BaseException) -> str:
    """The message a failure is allowed to persist (contracts.md §34.4).

    `str(exc)` is copied only for exceptions this codebase raised deliberately,
    and even then it is path-stripped and secret-masked. For anything else the
    class name is the only diagnostic that survives; the full text goes to the
    log, which is redacted, and never to the execution record.
    """
    if isinstance(exc, _AUTHORED_EXCEPTIONS):
        return sanitize_message(getattr(exc, "message", None) or str(exc))
    # Log only after path/secret scrubbing — a plugin exception may embed a
    # credential or absolute path, and logs are an egress surface (step 16.4).
    logger.error(
        "[scheduler] unhandled {} in a node executor: {}",
        type(exc).__name__,
        sanitize_message(exc),
    )
    return f"The node failed with an internal {type(exc).__name__}."


def is_retryable_failure(exc: BaseException) -> bool:
    """Whether the attempt loop may try again (contracts.md §34.3, D27).

    A `retryable=False` provider error stops the loop immediately instead of
    burning all three attempts on a permanently invalid API key. Anything that
    does not declare retryability keeps today's behavior and is retried.
    """
    declared = getattr(exc, "retryable", None)
    return True if declared is None else bool(declared)


class ProjectLockedError(SchedulerError):
    def __init__(self, project_id: str):
        super().__init__(
            "PROJECT_LOCKED",
            f"Project {project_id} already has an active execution",
            details={"project_id": project_id},
        )


class CancellationRequested(SchedulerError):
    def __init__(self):
        super().__init__("CANCELLED", "Execution was cancelled")


class ProjectLock(AbstractContextManager):
    """Non-blocking in-process and cross-process lock for one project."""

    _guard = threading.Lock()
    _held: set[str] = set()

    def __init__(self, project_id: str, *, lock_root: str | None = None, execution_id: str = ""):
        if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
            raise SchedulerError("PROJECT_ID_INVALID", "A strict pp_/pm_ project ID is required")
        self.project_id = project_id
        self.execution_id = execution_id
        self.lock_root = lock_root or os.path.join(OUTPUT_DIR, "workflows", "locks")
        self.path = safe_join(self.lock_root, f"{project_id}.lock")
        self._lock_key = os.path.normcase(os.path.abspath(self.path))
        self._acquired = False

    def acquire(self) -> "ProjectLock":
        os.makedirs(self.lock_root, exist_ok=True)
        with self._guard:
            if self._lock_key in self._held:
                raise ProjectLockedError(self.project_id)
            self._held.add(self._lock_key)
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            fd = os.open(self.path, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({
                    "project_id": self.project_id,
                    "execution_id": self.execution_id,
                    "pid": os.getpid(),
                }, handle)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            with self._guard:
                self._held.discard(self._lock_key)
            raise ProjectLockedError(self.project_id) from exc
        except BaseException:
            with self._guard:
                self._held.discard(self._lock_key)
            raise
        self._acquired = True
        return self

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        finally:
            with self._guard:
                self._held.discard(self._lock_key)
            self._acquired = False

    def __enter__(self) -> "ProjectLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.release()
        return False


class ArtifactPromoter:
    """Give adapters staged paths and atomically publish them after success."""

    def __init__(self, *, output_dir: str = OUTPUT_DIR, execution_id: str = "execution"):
        self.output_dir = os.path.abspath(output_dir)
        staging_root = os.path.join(self.output_dir, "workflows", ".staging")
        os.makedirs(staging_root, exist_ok=True)
        self.staging_dir = tempfile.mkdtemp(prefix=f"{execution_id}_", dir=staging_root)
        self._pending: list[tuple[str, str]] = []

    def stage_path(self, destination: str) -> str:
        destination = self._destination(destination)
        suffix = os.path.splitext(destination)[1]
        fd, staged = tempfile.mkstemp(prefix="artifact_", suffix=suffix, dir=self.staging_dir)
        os.close(fd)
        os.unlink(staged)  # callers commonly require a path which does not exist
        self._pending.append((staged, destination))
        return staged

    def _destination(self, destination: str) -> str:
        candidate = destination if os.path.isabs(destination) else safe_join(self.output_dir, destination)
        candidate = os.path.abspath(candidate)
        try:
            inside = os.path.commonpath([self.output_dir, candidate]) == self.output_dir
        except ValueError:
            inside = False
        if not inside:
            raise SchedulerError("ARTIFACT_UNMANAGED", "Artifact destination is outside the managed output directory")
        return candidate

    def promote(self) -> None:
        for staged, destination in self._pending:
            if not os.path.isfile(staged):
                # Basename only: the staging path is absolute and this message
                # is persisted into the execution record (contracts.md §36 L8).
                raise SchedulerError(
                    "ARTIFACT_MISSING",
                    "Staged artifact was not created: "
                    f"{os.path.basename(destination)}",
                    details={"artifact": os.path.basename(destination)},
                )
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            # Copy into the destination directory first.  os.replace then
            # publishes on the destination filesystem in one atomic step.
            fd, local_stage = tempfile.mkstemp(prefix=".promote_", dir=os.path.dirname(destination))
            os.close(fd)
            try:
                shutil.copy2(staged, local_stage)
                os.replace(local_stage, destination)
            finally:
                try:
                    os.unlink(local_stage)
                except FileNotFoundError:
                    pass
        self._pending.clear()

    def cleanup(self) -> None:
        shutil.rmtree(self.staging_dir, ignore_errors=True)


@dataclass
class ScheduleResult:
    status: str
    order: list[str]
    node_statuses: dict[str, str]
    outputs: dict[str, dict[str, Any]]
    errors: dict[str, dict[str, Any]] = field(default_factory=dict)
    execution_record: dict[str, Any] | None = None


@dataclass(frozen=True)
class _NodeOutcome:
    stop: bool = False
    cancelled: bool = False
    awaiting_approval: bool = False
    approval_reason: str | None = None
    approval_stage_key: str | None = None
    approval_expires_at: str | None = None
    approval_job_id: str | None = None
    # True when the node already produced outputs that resume must restore.
    approval_has_outputs: bool = False


def _summarize(value: Any, *, depth: int = 0) -> Any:
    """Create a bounded diagnostic summary instead of persisting payload bodies."""
    if depth >= 4:
        return {"type": type(value).__name__}
    if isinstance(value, str):
        return {"chars": len(value)}
    if isinstance(value, bytes):
        return {"bytes": len(value)}
    if isinstance(value, Mapping):
        summary = {str(key): _summarize(child, depth=depth + 1) for key, child in list(value.items())[:30]}
        if len(value) > 30:
            summary["_truncated_keys"] = len(value) - 30
        return summary
    if isinstance(value, (list, tuple)):
        result = {"count": len(value)}
        if value:
            result["items"] = [_summarize(child, depth=depth + 1) for child in value[:3]]
        return result
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return {"type": type(value).__name__}


def _artifact_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, Mapping):
        candidates = value.get("artifact_refs")
        if isinstance(candidates, list):
            refs.extend(item for item in candidates if isinstance(item, str))
        for child in value.values():
            refs.extend(_artifact_refs(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            refs.extend(_artifact_refs(child))
    return list(dict.fromkeys(refs))


@dataclass(frozen=True)
class WorkflowGraph:
    nodes: dict[str, dict]
    incoming: dict[str, list[dict]]
    dependents: dict[str, list[str]]
    saved_order: dict[str, int]


def build_graph(workflow: Mapping[str, Any]) -> WorkflowGraph:
    nodes = {node["id"]: node for node in workflow.get("nodes", [])}
    incoming = {node_id: [] for node_id in nodes}
    dependents = {node_id: [] for node_id in nodes}
    for edge in workflow.get("edges", []):
        incoming[edge["target_node"]].append(edge)
        dependents[edge["source_node"]].append(edge["target_node"])
    return WorkflowGraph(
        nodes=nodes,
        incoming=incoming,
        dependents=dependents,
        saved_order={node["id"]: index for index, node in enumerate(workflow.get("nodes", []))},
    )


def deterministic_order(workflow: Mapping[str, Any]) -> list[str]:
    """Return stable topological order (saved node order, then node ID)."""
    graph = build_graph(workflow)
    remaining = {node_id: len(edges) for node_id, edges in graph.incoming.items()}
    ready = [(graph.saved_order[node_id], node_id) for node_id, count in remaining.items() if count == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        order.append(node_id)
        for target in graph.dependents[node_id]:
            remaining[target] -= 1
            if remaining[target] == 0:
                heapq.heappush(ready, (graph.saved_order[target], target))
    if len(order) != len(graph.nodes):
        raise SchedulerError("CYCLE_DETECTED", "Workflow connections must form a DAG")
    return order


def dependency_maps(workflow: Mapping[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return predecessor and reverse/dependent maps for scope calculations."""
    graph = build_graph(workflow)
    dependencies = {
        node_id: {edge["source_node"] for edge in edges}
        for node_id, edges in graph.incoming.items()
    }
    reverse_dependencies = {
        node_id: set(targets) for node_id, targets in graph.dependents.items()
    }
    return dependencies, reverse_dependencies


RUN_MODES = {
    "full",
    "node_with_deps",
    "node_isolated",
    "selected",
    "from_node",
    "retry_failed",
    "retry_failed_desc",
}


def calculate_scope(
    workflow: Mapping[str, Any],
    run_mode: str,
    target_node_ids: list[str],
) -> list[str]:
    """Calculate a stable execution subgraph for every topology-based run mode.

    Isolation has input-port semantics in addition to graph topology and is
    completed by ``execution.resolve_scope`` after this function validates its
    target.  Returned IDs always follow saved node order, never traversal order.
    """
    if run_mode not in RUN_MODES:
        raise ValueError(f"Unsupported run_mode: {run_mode}")
    saved_ids = [node["id"] for node in workflow.get("nodes", [])]
    known_ids = set(saved_ids)
    if not isinstance(target_node_ids, list):
        raise ValueError("target_node_ids must be an array of node IDs")
    if len(set(target_node_ids)) != len(target_node_ids):
        raise ValueError("target_node_ids must not contain duplicates")
    unknown = [node_id for node_id in target_node_ids if node_id not in known_ids]
    if unknown:
        raise ValueError(f"Unknown target node: {unknown[0]}")

    if run_mode == "full":
        if target_node_ids:
            raise ValueError("full mode does not accept target_node_ids")
        return saved_ids

    if run_mode == "selected":
        if not target_node_ids:
            raise ValueError("selected requires at least one existing target node")
        seeds = set(target_node_ids)
        direction = "dependencies"
    else:
        if len(target_node_ids) != 1:
            raise ValueError(f"{run_mode} requires exactly one existing target node")
        seeds = {target_node_ids[0]}
        if run_mode in {"node_with_deps"}:
            direction = "dependencies"
        elif run_mode in {"from_node", "retry_failed_desc"}:
            direction = "descendants"
        else:
            # node_isolated and retry_failed contain only their target at the
            # topology layer. Isolation may add directly-connected stubs.
            return [node_id for node_id in saved_ids if node_id in seeds]

    dependencies, descendants = dependency_maps(workflow)
    adjacency = dependencies if direction == "dependencies" else descendants
    scope = set(seeds)
    pending = list(seeds)
    while pending:
        node_id = pending.pop()
        for related_id in adjacency[node_id]:
            if related_id not in scope:
                scope.add(related_id)
                pending.append(related_id)
    return [node_id for node_id in saved_ids if node_id in scope]


def resolve_executor(node: Mapping[str, Any]) -> Callable:
    definition = get_node_type(node.get("type"))
    spec = definition.get("executor") if definition else None
    if not spec or ":" not in spec:
        raise SchedulerError("NODE_EXECUTOR_MISSING", f"No executor is registered for {node.get('type')}")
    module_name, function_name = spec.split(":", 1)
    function = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(function):
        raise SchedulerError("NODE_EXECUTOR_MISSING", f"Executor {spec} is not callable")
    return function


class WorkflowScheduler:
    _exclusive_guard = threading.Lock()
    _exclusive_adapter_locks: dict[str, threading.Lock] = {}

    def __init__(
        self,
        workflow: Mapping[str, Any],
        *,
        project_id: str,
        execution_id: str = "",
        executor_resolver: Callable[[Mapping[str, Any]], Callable] = resolve_executor,
        lock_root: str | None = None,
        output_dir: str = OUTPUT_DIR,
        on_status: Callable[[str, str], None] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        run_mode: str = "full",
        scope_node_ids: list[str] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        force: bool = False,
        sleeper: Callable[[float], None] = time.sleep,
        input_overrides: Mapping[str, Mapping[str, Any]] | None = None,
        source_artifact_ids: Mapping[str, list[str]] | None = None,
        # Step 4.2: nodes whose inputs came from sample bindings (not graph stubs).
        sample_fed_node_ids: list[str] | None = None,
        max_workers: int = 4,
        # Durable approval (step 2.6): pause after these node ids succeed.
        checkpoint_after_node_ids: list[str] | None = None,
        # Resume a previous awaiting_approval execution from persisted state.
        resume_state: ResumeState | None = None,
        # Optional pre-built execution record (resume keeps ids/timestamps).
        existing_record: ExecutionRecord | None = None,
    ):
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        self.input_overrides = {
            str(node_id): dict(ports) for node_id, ports in (input_overrides or {}).items()
        }
        self.source_artifact_ids = {
            str(node_id): list(dict.fromkeys(ids))
            for node_id, ids in (source_artifact_ids or {}).items()
        }
        self.sample_fed_node_ids = {
            str(node_id) for node_id in (sample_fed_node_ids or []) if node_id
        }
        provided_inputs = {
            (node_id, port_id)
            for node_id, ports in self.input_overrides.items()
            for port_id in ports
        }
        problems = validation_errors(validate_workflow(
            dict(workflow), require_complete=True, provided_inputs=provided_inputs
        ))
        if scope_node_ids is not None:
            problems.extend(validate_expressions(workflow, scope_node_ids=scope_node_ids))
        if problems:
            raise SchedulerError("WORKFLOW_INVALID", "Workflow has validation errors", details={"problems": problems})
        if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
            raise SchedulerError("PROJECT_ID_INVALID", "A strict pp_/pm_ project ID is required")
        self.workflow = dict(workflow)
        self.project_id = project_id
        execution_root = os.path.join(output_dir, "workflows", "executions")
        self.execution_id = execution_id or generate_execution_id(root=execution_root)
        self.executor_resolver = executor_resolver
        self.lock_root = lock_root
        self.output_dir = output_dir
        self.on_status = on_status
        self.on_event = on_event
        self.run_mode = run_mode
        self.scope_node_ids = list(scope_node_ids or [node["id"] for node in workflow.get("nodes", [])])
        self.stop_requested = stop_requested or (lambda: False)
        self.force = force
        self.sleeper = sleeper
        self.max_workers = max_workers
        self._state_lock = threading.RLock()
        self.execution_root = execution_root
        self.cache = NodeCache(
            root=os.path.join(output_dir, "workflows", "cache"),
            output_dir=output_dir,
        )
        self.redactor = Redactor(workflow)
        # Merge explicit constructor list with workflow.extensions.approval_checkpoints.
        configured = list(checkpoint_after_node_ids or [])
        for node_id in checkpoint_node_ids_from_workflow(workflow):
            if node_id not in configured:
                configured.append(node_id)
        self.checkpoint_after_node_ids = set(configured)
        self.resume_state = resume_state
        # Nodes already approved this execution — never re-pause on them.
        self._already_approved_nodes: set[str] = set()
        if resume_state is not None and resume_state.checkpoint_node_id:
            self._already_approved_nodes.add(resume_state.checkpoint_node_id)
        if existing_record is not None:
            self.record = existing_record
            if not self.record.started_at:
                self.record.started_at = now_iso()
        else:
            self.record = ExecutionRecord(
                execution_id=self.execution_id,
                workflow_id=str(workflow.get("workflow_id", "")),
                workflow_snapshot=self.redactor(workflow),
                project_id=project_id,
                run_mode=run_mode,
                scope_node_ids=self.scope_node_ids,
                started_at=now_iso(),
                nodes={node["id"]: NodeExecutionRecord() for node in workflow.get("nodes", [])},
            )

    def run(self) -> ScheduleResult:
        scope = set(self.scope_node_ids)
        scoped_workflow = {
            **self.workflow,
            "nodes": [node for node in self.workflow.get("nodes", []) if node["id"] in scope],
            "edges": [
                edge for edge in self.workflow.get("edges", [])
                if edge["source_node"] in scope and edge["target_node"] in scope
            ],
        }
        graph = build_graph(scoped_workflow)
        order = deterministic_order(scoped_workflow)
        statuses = {node_id: "idle" for node_id in graph.nodes}
        node_outputs: dict[str, dict[str, Any]] = {}
        node_output_fingerprints: dict[str, str] = {}
        errors: dict[str, dict[str, Any]] = {}
        completed: set[str] = set()
        remaining = {node_id: len(graph.incoming[node_id]) for node_id in graph.nodes}

        # Resume from a durable approval pause: restore completed work, then
        # continue only the unfinished subgraph (step 2.6).
        if self.resume_state is not None:
            self._seed_from_resume(
                graph,
                statuses,
                node_outputs,
                node_output_fingerprints,
                completed,
                remaining,
            )

        ready = [
            (graph.saved_order[node_id], node_id)
            for node_id, dependency_count in remaining.items()
            if dependency_count == 0 and node_id not in completed
        ]
        heapq.heapify(ready)
        self.record.status = "running"
        self.record.finished_at = None
        # Clear prior approval pointer once we are actively running again.
        if self.resume_state is not None:
            self.record.approval = None
        self._persist()
        self._emit({"type": "execution_status", "node_id": None, "status": "running"})

        stopped = False
        cancelled = False
        exclusive_running = False
        approval_outcome: _NodeOutcome | None = None
        approval_node_id: str | None = None

        def finish(node_id: str) -> None:
            completed.add(node_id)
            for target in graph.dependents[node_id]:
                remaining[target] -= 1
                if remaining[target] == 0 and target not in completed:
                    heapq.heappush(ready, (graph.saved_order[target], target))

        with ProjectLock(self.project_id, lock_root=self.lock_root, execution_id=self.execution_id):
            with ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix=f"workflow-{self.execution_id}",
            ) as pool:
                running: dict[Future[_NodeOutcome], str] = {}
                while ready or running:
                    if self.stop_requested():
                        cancelled = True

                    # Once a checkpoint fires, drain in-flight work but do not
                    # schedule anything new — then release the worker.
                    if approval_outcome is not None:
                        if not running:
                            break
                    else:
                        made_progress = False
                        while (
                            ready
                            and len(running) < self.max_workers
                            and not exclusive_running
                            and approval_outcome is None
                        ):
                            # Preserve the v1 stop-policy boundary at run start:
                            # establish the first root successfully before opening
                            # the pool to independent ready work.  Once a node has
                            # completed, normal branch parallelism applies.
                            if not completed and running:
                                break
                            _, node_id = ready[0]
                            node = graph.nodes[node_id]
                            incoming_edges = graph.incoming[node_id]
                            active_edges = [
                                edge for edge in incoming_edges
                                if self._edge_was_activated(edge, statuses, node_outputs)
                            ]
                            if node.get("type") == "utility.merge":
                                inactive_resolved = all(
                                    edge in active_edges
                                    or statuses.get(edge["source_node"]) in {"succeeded", "skipped"}
                                    for edge in incoming_edges
                                )
                                incoming_active = inactive_resolved and bool(active_edges)
                            else:
                                incoming_active = len(active_edges) == len(incoming_edges)

                            if cancelled or stopped or node.get("disabled") or not incoming_active:
                                heapq.heappop(ready)
                                record = deepcopy(self.record.nodes[node_id])
                                record.duration_ms = 0
                                self._status(
                                    statuses,
                                    node_id,
                                    "cancelled" if cancelled else "skipped",
                                    node_record=record,
                                )
                                finish(node_id)
                                made_progress = True
                                continue

                            parallel_safe = self._parallel_safe(node)
                            if not parallel_safe and running:
                                break

                            heapq.heappop(ready)
                            future = pool.submit(
                                self._execute_node,
                                node_id,
                                node,
                                graph,
                                statuses,
                                node_outputs,
                                node_output_fingerprints,
                                errors,
                                active_edges,
                            )
                            running[future] = node_id
                            exclusive_running = not parallel_safe
                            made_progress = True
                            if exclusive_running:
                                break

                        if not running:
                            if made_progress:
                                continue
                            break

                    done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                    for future in sorted(done, key=lambda item: graph.saved_order[running[item]]):
                        node_id = running.pop(future)
                        outcome = future.result()
                        if not self._parallel_safe(graph.nodes[node_id]):
                            exclusive_running = False
                        if outcome.awaiting_approval and approval_outcome is None:
                            approval_outcome = outcome
                            approval_node_id = node_id
                            # Node stays incomplete (awaiting_approval); do not
                            # unlock dependents until human approval + resume.
                            completed.add(node_id)
                            continue
                        stopped = stopped or outcome.stop
                        cancelled = cancelled or outcome.cancelled
                        finish(node_id)

        if approval_outcome is not None and approval_node_id is not None and not cancelled and not stopped:
            persisted = self._enter_awaiting_approval(
                approval_node_id,
                statuses,
                node_outputs,
                node_output_fingerprints,
                reason=approval_outcome.approval_reason or "policy",
                stage_key=approval_outcome.approval_stage_key,
                expires_at=approval_outcome.approval_expires_at,
                job_id=approval_outcome.approval_job_id,
                has_outputs=approval_outcome.approval_has_outputs,
            )
            executed = [node_id for node_id in order if node_id in completed]
            ordered_outputs = {
                node_id: node_outputs[node_id] for node_id in order if node_id in node_outputs
            }
            ordered_errors = {node_id: errors[node_id] for node_id in order if node_id in errors}
            return ScheduleResult(
                "awaiting_approval",
                executed,
                statuses,
                ordered_outputs,
                ordered_errors,
                persisted,
            )

        handled = any(
            self._error_policy(graph.nodes[node_id])["policy"] in {"continue_error", "skip_optional"}
            for node_id in errors
        )
        overall = "cancelled" if cancelled or self.stop_requested() else (
            "partial" if errors and handled and not stopped else ("failed" if errors else "succeeded")
        )
        self.record.status = overall
        self.record.finished_at = now_iso()
        self.record.approval = None
        # Successful terminal run no longer needs the resume snapshot.
        try:
            delete_resume_state(
                self.execution_id,
                root=approval_resume_root(self.output_dir),
            )
        except Exception:
            pass
        persisted = self._persist()
        self._emit({"type": "execution_finished", "node_id": None, "status": overall})
        executed = [node_id for node_id in order if node_id in completed]
        ordered_outputs = {node_id: node_outputs[node_id] for node_id in order if node_id in node_outputs}
        ordered_errors = {node_id: errors[node_id] for node_id in order if node_id in errors}
        return ScheduleResult(overall, executed, statuses, ordered_outputs, ordered_errors, persisted)

    @staticmethod
    def _parallel_safe(node: Mapping[str, Any]) -> bool:
        definition = get_node_type(node.get("type")) or {}
        return definition.get("capabilities", {}).get("parallel_safe", True) is not False

    @classmethod
    def _exclusive_adapter_lock(cls, node: Mapping[str, Any]) -> threading.Lock | None:
        if cls._parallel_safe(node):
            return None
        node_type = str(node.get("type", ""))
        with cls._exclusive_guard:
            return cls._exclusive_adapter_locks.setdefault(node_type, threading.Lock())

    def _execute_node(
        self,
        node_id: str,
        node: Mapping[str, Any],
        graph: WorkflowGraph,
        statuses: dict[str, str],
        node_outputs: dict[str, dict[str, Any]],
        node_output_fingerprints: dict[str, str],
        errors: dict[str, dict[str, Any]],
        active_edges: list[Mapping[str, Any]],
    ) -> _NodeOutcome:
        """Execute one ready node; dependency scheduling stays on the caller thread."""
        inputs = self._resolve_inputs(node_id, graph, node_outputs, active_edges=active_edges)
        inputs.update(self.input_overrides.get(node_id, {}))
        node_record = deepcopy(self.record.nodes[node_id])
        node_record.from_sample_data = (
            node.get("type") == "stub.input"
            or node_id in self.sample_fed_node_ids
            or any(
                self.record.nodes[edge["source_node"]].from_sample_data
                for edge in graph.incoming[node_id]
            )
        )
        # Standalone input picker (4.1): record which artifacts fed this node.
        source_ids = list(self.source_artifact_ids.get(node_id) or [])
        try:
            from scriptase.artifacts.input_sources import source_artifact_ids_from_inputs
            source_ids.extend(source_artifact_ids_from_inputs(inputs))
        except Exception:
            pass
        node_record.source_artifact_ids = list(dict.fromkeys(source_ids))
        node_record.resolved_inputs_summary = self.redactor(_summarize(inputs))
        if node_record.source_artifact_ids:
            # Surface ids in the inputs summary so clients without the new field
            # can still read provenance from the existing summary shape.
            summary = dict(node_record.resolved_inputs_summary or {})
            summary["source_artifact_ids"] = list(node_record.source_artifact_ids)
            node_record.resolved_inputs_summary = summary
        try:
            configuration = resolve_configuration(
                self._configuration(node),
                node_outputs=node_outputs,
                variables=self.workflow.get("variables", {}),
                project_id=self.project_id,
            )
        except ExpressionError as exc:
            raise SchedulerError(exc.code, exc.message, details={"node_id": node_id}) from exc
        resolved_problems = validation_errors(validate_resolved_configuration(node, configuration))
        if resolved_problems:
            raise SchedulerError(
                "EXPRESSION_TYPE_MISMATCH",
                f"Resolved configuration is invalid for node {node_id}",
                details={"node_id": node_id, "problems": resolved_problems},
            )
        incoming_fingerprints = {
            ":".join((
                edge["id"], edge["source_node"], edge["source_port"], edge["target_port"],
            )): node_output_fingerprints[edge["source_node"]]
            for edge in active_edges
        }
        pinned = node.get("type") == "stub.output" and configuration.get("pinned") is True
        components = fingerprint_components(
            node,
            configuration,
            {} if pinned else inputs,
            {} if pinned else incoming_fingerprints,
            adapter_schema_version=int(get_node_type(node["type"]).get("cache_schema_version", 1)),
        )
        fingerprint = canonical_fingerprint(components)
        node_record.fingerprint = fingerprint

        if pinned:
            result = {"value": configuration.get("payload")}
            self._validate_outputs(node, result)
            node_outputs[node_id] = result
            node_output_fingerprints[node_id] = output_fingerprint(result, {})
            node_record.outputs_summary = self.redactor(_summarize(result))
            node_record.cache = {"hit": True, "reason": "pinned_payload"}
            node_record.duration_ms = 0
            node_record.cost = cost_snapshot_from_result(
                result,
                cache_hit=True,
                configuration=configuration,
                is_provider_node=is_provider_node_type(node.get("type")),
            )
            self._status(statuses, node_id, "succeeded", node_record=node_record)
            return _NodeOutcome()

        cacheable = get_node_type(node["type"]).get("capabilities", {}).get("cacheable", True)
        lookup = self.cache.lookup(
            workflow_id=str(self.workflow.get("workflow_id", "")),
            project_id=self.project_id,
            node_id=node_id,
            fingerprint=fingerprint,
            components=components,
            force=self.force,
        ) if cacheable else CacheLookup(False, "cache_disabled")
        node_record.cache = {"hit": lookup.hit, "reason": lookup.reason}
        if lookup.hit:
            result = dict(lookup.outputs or {})
            try:
                self._validate_outputs(node, result)
            except SchedulerError:
                lookup = CacheLookup(False, "cache_corrupt")
                node_record.cache = {"hit": False, "reason": lookup.reason}
            else:
                node_outputs[node_id] = result
                node_output_fingerprints[node_id] = (
                    lookup.output_fingerprint or output_fingerprint(result, {})
                )
                node_record.outputs_summary = self.redactor(_summarize(result))
                node_record.artifact_refs = self.redactor(_artifact_refs(result))
                node_record.duration_ms = 0
                # Step 9.3: cache hits do not consume generation budget.
                node_record.cost = cost_snapshot_from_result(
                    result,
                    cache_hit=True,
                    configuration=configuration,
                    is_provider_node=is_provider_node_type(node.get("type")),
                )
                self._status(statuses, node_id, "succeeded", node_record=node_record)
                return _NodeOutcome()

        if lookup.reason not in {"no_prior_success", "forced_regeneration", "cache_disabled"}:
            self._status(statuses, node_id, "stale", node_record=node_record)
        started = time.perf_counter()
        policy = self._error_policy(node)
        max_attempts = policy["max_attempts"] if policy["policy"] == "retry" else 1
        while node_record.attempts < max_attempts:
            node_record.attempts += 1
            self._status(statuses, node_id, "running", node_record=node_record)
            promoter = ArtifactPromoter(
                output_dir=self.output_dir,
                execution_id=f"{self.execution_id}_{node_id}",
            )
            extensions = self.workflow.get("extensions")
            channel_settings = None
            if isinstance(extensions, dict):
                raw_channel = extensions.get("channel_settings")
                if isinstance(raw_channel, dict):
                    channel_settings = raw_channel
            context = AdapterContext(
                project_id=self.project_id,
                execution_id=self.execution_id,
                node_id=node_id,
                stage_artifact=promoter.stage_path,
                stop_requested=self.stop_requested,
                channel_settings=channel_settings,
            )
            failure = None
            cancelled = False
            try:
                executor = self.executor_resolver(node)
                exclusive_lock = self._exclusive_adapter_lock(node)
                if exclusive_lock is None:
                    result = executor(inputs, configuration, context)
                else:
                    with exclusive_lock:
                        result = executor(inputs, configuration, context)
                if self.stop_requested():
                    raise CancellationRequested()
                if not isinstance(result, Mapping):
                    raise SchedulerError(
                        "NODE_OUTPUT_INVALID", f"Node {node_id} returned a non-object output"
                    )
                result = dict(result)
                self._validate_outputs(node, result)
                promoter.promote()
                node_outputs[node_id] = result
                node_record.outputs_summary = self.redactor(_summarize(result))
                node_record.artifact_refs = self.redactor(_artifact_refs(result))
                # Step 9.3: durable cost/generation snapshot from provenance.
                node_record.cost = cost_snapshot_from_result(
                    result,
                    cache_hit=False,
                    configuration=configuration,
                    is_provider_node=is_provider_node_type(node.get("type")),
                )
                if self.redactor(result) != result:
                    output_fp, cache_failure = None, "sensitive_output"
                elif cacheable:
                    output_fp, cache_failure = self.cache.store(
                        workflow_id=str(self.workflow.get("workflow_id", "")),
                        project_id=self.project_id,
                        node_id=node_id,
                        fingerprint=fingerprint,
                        components=components,
                        outputs=result,
                        artifact_refs=_artifact_refs(result),
                    )
                else:
                    output_fp, cache_failure = output_fingerprint(result, {}), "cache_disabled"
                if output_fp is None:
                    node_record.cache = {"hit": False, "reason": cache_failure}
                    output_fp = output_fingerprint(result, {})
                node_output_fingerprints[node_id] = output_fp
                node_record.duration_ms = max(0, round((time.perf_counter() - started) * 1000))
                node_record.error = None
                # Configured checkpoint: hold outputs, mark awaiting_approval,
                # and release the worker (step 2.6). Resume promotes to succeeded.
                if (
                    node_id in self.checkpoint_after_node_ids
                    and node_id not in self._already_approved_nodes
                ):
                    stage_key = self._stage_key_hint(node)
                    try:
                        from scriptase.jobs.execution_modes import (
                            checkpoint_reason_for_node,
                        )

                        approval_reason = checkpoint_reason_for_node(
                            node, stage_key=stage_key
                        )
                    except Exception:
                        approval_reason = (
                            "script_approval" if stage_key == "script" else "policy"
                        )
                    self._status(
                        statuses, node_id, "awaiting_approval", node_record=node_record
                    )
                    return _NodeOutcome(
                        awaiting_approval=True,
                        approval_reason=approval_reason,
                        approval_has_outputs=True,
                        approval_job_id=self._job_id_from_workflow(),
                        approval_stage_key=stage_key,
                    )
                self._status(statuses, node_id, "succeeded", node_record=node_record)
                return _NodeOutcome()
            except CancellationRequested as exc:
                failure = exc
                cancelled = True
            except ApprovalRequired as exc:
                # Adapter requested a durable human checkpoint. Do not treat
                # this as a failure — persist and release the worker.
                node_record.duration_ms = max(0, round((time.perf_counter() - started) * 1000))
                node_record.error = {
                    "code": "APPROVAL_REQUIRED",
                    "message": exc.message,
                    "details": exc.details,
                }
                self._status(statuses, node_id, "awaiting_approval", node_record=node_record)
                return _NodeOutcome(
                    awaiting_approval=True,
                    approval_reason=exc.reason,
                    approval_stage_key=exc.stage_key or self._stage_key_hint(node),
                    approval_expires_at=exc.expires_at,
                    approval_job_id=exc.job_id or self._job_id_from_workflow(),
                    approval_has_outputs=exc.has_outputs,
                )
            except Exception as exc:  # adapters are a plugin boundary
                failure = exc
            finally:
                promoter.cleanup()

            if cancelled or getattr(failure, "code", None) == "CANCELLED":
                node_record.error = self._failure_payload(node, failure, node_record.attempts)
                node_record.duration_ms = max(0, round((time.perf_counter() - started) * 1000))
                self._status(statuses, node_id, "cancelled", node_record=node_record)
                return _NodeOutcome(cancelled=True)

            attempt_error = self._failure_payload(node, failure, node_record.attempts)
            node_record.attempt_errors.append(attempt_error)
            # A non-retryable provider error ends the loop here rather than
            # spending the remaining attempts on a failure that cannot change
            # (contracts.md §34.3, D27).
            if (
                policy["policy"] == "retry"
                and node_record.attempts < max_attempts
                and is_retryable_failure(failure)
            ):
                delay_ms = min(
                    60_000,
                    round(policy["delay_ms"] * (
                        policy["backoff_multiplier"] ** (node_record.attempts - 1)
                    )),
                )
                node_record.logs.append(self.redactor(ExecutionLog(
                    ts=now_iso(),
                    level="warning",
                    message=f"Attempt {node_record.attempts} failed; retrying in {delay_ms} ms",
                ).__dict__))
                self._commit_node_record(node_id, node_record)
                self._emit({
                    "type": "node_retry",
                    "execution_id": self.execution_id,
                    "node_id": node_id,
                    "attempt": node_record.attempts,
                    "next_attempt": node_record.attempts + 1,
                    "delay_ms": delay_ms,
                    "error": attempt_error,
                })
                if delay_ms:
                    self._sleep_before_retry(delay_ms / 1000)
                if self.stop_requested():
                    node_record.error = self._failure_payload(
                        node, CancellationRequested(), node_record.attempts
                    )
                    self._status(statuses, node_id, "cancelled", node_record=node_record)
                    return _NodeOutcome(cancelled=True)
                continue

            error = attempt_error
            errors[node_id] = error
            node_record.error = error
            node_record.logs.append(self.redactor(ExecutionLog(
                ts=now_iso(), level="error", message=error["message"]
            ).__dict__))
            node_record.duration_ms = max(0, round((time.perf_counter() - started) * 1000))
            self._commit_node_record(node_id, node_record)
            self._emit({
                "type": "node_error",
                "execution_id": self.execution_id,
                "node_id": node_id,
                "error": error,
            })
            if policy["policy"] == "continue_error":
                node_outputs[node_id] = {"error": {"ok": False}}
                node_output_fingerprints[node_id] = output_fingerprint(node_outputs[node_id], {})
                self._status(statuses, node_id, "failed", node_record=node_record)
                return _NodeOutcome()
            if policy["policy"] == "skip_optional":
                self._status(statuses, node_id, "skipped", node_record=node_record)
                return _NodeOutcome()
            self._status(statuses, node_id, "failed", node_record=node_record)
            return _NodeOutcome(stop=True)

        raise AssertionError("node attempt loop exited without a terminal outcome")

    def _status(
        self,
        statuses: dict[str, str],
        node_id: str,
        status: str,
        *,
        node_record: NodeExecutionRecord | None = None,
    ) -> None:
        # A node keeps its own event order on its worker thread.  This lock
        # makes the shared execution snapshot and the corresponding SSE event
        # one atomic transition, even when sibling branches finish together.
        with self._state_lock:
            record = node_record or deepcopy(self.record.nodes[node_id])
            statuses[node_id] = status
            record.status = status
            record.logs.append(self.redactor(ExecutionLog(
                ts=now_iso(), level="info", message=f"Node status changed to {status}"
            ).__dict__))
            self.record.nodes[node_id] = deepcopy(record)
            self._persist_unlocked()
            if self.on_status:
                self.on_status(node_id, status)
            self._emit({
                "type": "node_status",
                "execution_id": self.execution_id,
                "node_id": node_id,
                "status": status,
                "attempt": record.attempts,
                "duration_ms": record.duration_ms or 0,
                "from_sample_data": record.from_sample_data,
            })

    def _commit_node_record(self, node_id: str, node_record: NodeExecutionRecord) -> None:
        with self._state_lock:
            self.record.nodes[node_id] = deepcopy(node_record)
            self._persist_unlocked()

    def _persist(self) -> dict[str, Any]:
        with self._state_lock:
            return self._persist_unlocked()

    def _persist_unlocked(self) -> dict[str, Any]:
        return save_execution(self.record, root=self.execution_root, secrets=self.redactor.secrets)

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event:
            self.on_event(self.redactor(event))

    @staticmethod
    def _error_policy(node: Mapping[str, Any]) -> dict[str, Any]:
        supplied = node.get("on_error") or {}
        return {
            "policy": supplied.get("policy", "stop"),
            "max_attempts": supplied.get("max_attempts", 3),
            "delay_ms": supplied.get("delay_ms", 1000),
            "backoff_multiplier": supplied.get("backoff_multiplier", 2.0),
        }

    def _failure_payload(self, node: Mapping[str, Any], exc: Exception, attempt: int) -> dict[str, Any]:
        code = getattr(exc, "code", "NODE_EXECUTION_FAILED")
        if code == "CANCELLED":
            message = "Execution was cancelled"
            suggestion = "Start a new run when ready."
        else:
            message = safe_failure_message(exc)
            suggestion = getattr(exc, "recovery_suggestion", None) or (
                "Review the node inputs and settings, then retry the failed node."
            )
        return self.redactor({
            "node_id": node["id"],
            "node_name": node.get("name") or node["id"],
            "code": code,
            "message": message,
            "details": getattr(exc, "details", None),
            "attempt": attempt,
            "timestamp": now_iso(),
            "recovery_suggestion": suggestion,
        })

    def _sleep_before_retry(self, seconds: float) -> None:
        """Wait in short intervals so a stop request interrupts long backoffs."""
        remaining = seconds
        while remaining > 0 and not self.stop_requested():
            interval = min(0.1, remaining)
            self.sleeper(interval)
            remaining = max(0.0, remaining - interval)

    def _job_id_from_workflow(self) -> str | None:
        extensions = self.workflow.get("extensions")
        if isinstance(extensions, Mapping):
            job_id = extensions.get("job_id")
            if isinstance(job_id, str) and job_id.strip():
                return job_id.strip()
        return None

    @staticmethod
    def _stage_key_hint(node: Mapping[str, Any]) -> str | None:
        """Best-effort stage key for checkpoint records (Production projection)."""
        try:
            from scriptase.jobs.stage_projection import PRIMARY_STAGE_BY_TYPE
        except Exception:
            return None
        type_key = str(node.get("type") or "")
        return PRIMARY_STAGE_BY_TYPE.get(type_key)

    def _seed_from_resume(
        self,
        graph: WorkflowGraph,
        statuses: dict[str, str],
        node_outputs: dict[str, dict[str, Any]],
        node_output_fingerprints: dict[str, str],
        completed: set[str],
        remaining: dict[str, int],
    ) -> None:
        """Restore completed work from a durable approval pause."""
        state = self.resume_state
        if state is None:
            return
        checkpoint_node = state.checkpoint_node_id
        for node_id, status in state.node_statuses.items():
            if node_id not in graph.nodes:
                continue
            if node_id == checkpoint_node:
                # Promote the approved node to succeeded when it held outputs;
                # otherwise leave it idle so it re-runs.
                if state.has_outputs and node_id in state.node_outputs:
                    statuses[node_id] = "succeeded"
                    node_outputs[node_id] = deepcopy(state.node_outputs[node_id])
                    if node_id in state.node_output_fingerprints:
                        node_output_fingerprints[node_id] = state.node_output_fingerprints[node_id]
                    completed.add(node_id)
                    record = deepcopy(self.record.nodes.get(node_id) or NodeExecutionRecord())
                    record.status = "succeeded"
                    record.error = None
                    if not record.outputs_summary and node_id in node_outputs:
                        record.outputs_summary = self.redactor(_summarize(node_outputs[node_id]))
                        record.artifact_refs = self.redactor(_artifact_refs(node_outputs[node_id]))
                    self.record.nodes[node_id] = record
                else:
                    statuses[node_id] = "idle"
                continue
            if status in {"succeeded", "skipped", "failed", "cancelled"}:
                statuses[node_id] = status
                completed.add(node_id)
                if node_id in state.node_outputs:
                    node_outputs[node_id] = deepcopy(state.node_outputs[node_id])
                if node_id in state.node_output_fingerprints:
                    node_output_fingerprints[node_id] = state.node_output_fingerprints[node_id]

        # Recompute remaining dependency counts from restored statuses so the
        # ready queue only contains unfinished, dependency-satisfied nodes.
        for node_id in graph.nodes:
            if node_id in completed:
                remaining[node_id] = 0
                continue
            count = 0
            for edge in graph.incoming[node_id]:
                source = edge["source_node"]
                if source not in completed:
                    count += 1
            remaining[node_id] = count

    def _enter_awaiting_approval(
        self,
        node_id: str,
        statuses: dict[str, str],
        node_outputs: dict[str, dict[str, Any]],
        node_output_fingerprints: dict[str, str],
        *,
        reason: str,
        stage_key: str | None,
        expires_at: str | None,
        job_id: str | None,
        has_outputs: bool,
    ) -> dict[str, Any]:
        """Persist checkpoint + resume state and release the worker thread.

        ``finished_at`` stays null — awaiting_approval is non-terminal and may
        return to running after approve (contracts.md §1.5 / §11).
        """
        checkpoint = create_checkpoint(
            execution_id=self.execution_id,
            node_id=node_id,
            reason=reason or "policy",
            job_id=job_id,
            stage_key=stage_key,
            expires_at=expires_at,
            has_outputs=has_outputs,
            root=approval_checkpoints_root(self.output_dir),
        )
        # Capture every completed node's full outputs for restart-safe resume.
        # Statuses include the awaiting node itself.
        resume = ResumeState(
            execution_id=self.execution_id,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_node_id=node_id,
            workflow_snapshot=deepcopy(self.workflow),
            project_id=self.project_id,
            run_mode=self.run_mode,
            scope_node_ids=list(self.scope_node_ids),
            node_statuses={key: str(value) for key, value in statuses.items()},
            node_outputs={
                key: deepcopy(value)
                for key, value in node_outputs.items()
                if isinstance(value, Mapping)
            },
            node_output_fingerprints=dict(node_output_fingerprints),
            force=self.force,
            input_overrides=deepcopy(self.input_overrides),
            has_outputs=has_outputs,
        )
        save_resume_state(resume, root=approval_resume_root(self.output_dir))

        self.record.status = "awaiting_approval"
        self.record.finished_at = None
        self.record.approval = approval_summary(checkpoint)
        # Ensure the checkpoint node is recorded as awaiting_approval.
        if node_id in self.record.nodes:
            node_record = deepcopy(self.record.nodes[node_id])
            node_record.status = "awaiting_approval"
            self.record.nodes[node_id] = node_record
        statuses[node_id] = "awaiting_approval"
        persisted = self._persist()
        self._emit({
            "type": "execution_status",
            "node_id": None,
            "status": "awaiting_approval",
            "approval": approval_summary(checkpoint),
        })
        self._emit({
            "type": "approval_required",
            "node_id": node_id,
            "status": "awaiting_approval",
            "approval": approval_summary(checkpoint),
        })
        return persisted

    @staticmethod
    def _edge_was_activated(
        edge: Mapping[str, Any],
        statuses: Mapping[str, str],
        outputs: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        source = edge["source_node"]
        if edge["source_port"] == "error":
            return statuses.get(source) == "failed" and "error" in outputs.get(source, {})
        return statuses.get(source) == "succeeded" and edge["source_port"] in outputs.get(source, {})

    @staticmethod
    def _configuration(node: Mapping[str, Any]) -> dict[str, Any]:
        definition = get_node_type(node["type"])
        config = {
            field["name"]: field["default"]
            for field in definition.get("config_schema", [])
            if "default" in field
        }
        config.update(node.get("configuration") or {})
        return config

    @staticmethod
    def _resolve_inputs(
        node_id: str,
        graph: WorkflowGraph,
        outputs: Mapping[str, Mapping[str, Any]],
        *,
        active_edges: list[Mapping[str, Any]] | None = None,
    ) -> dict:
        resolved: dict[str, Any] = {}
        edges = graph.incoming[node_id] if active_edges is None else active_edges
        for edge in edges:
            value = outputs[edge["source_node"]][edge["source_port"]]
            target_port = edge["target_port"]
            definition = get_node_type(graph.nodes[node_id]["type"])
            port = next(item for item in definition["inputs"] if item["id"] == target_port)
            if port.get("multiple"):
                resolved.setdefault(target_port, []).append(value)
            else:
                resolved[target_port] = value
        return resolved

    @staticmethod
    def _validate_outputs(node: Mapping[str, Any], outputs: Mapping[str, Any]) -> None:
        definition = get_node_type(node["type"])
        for port in definition.get("outputs", []):
            if port["id"] == "error" or port.get("conditional"):
                continue
            if port["id"] not in outputs:
                raise SchedulerError(
                    "NODE_OUTPUT_MISSING",
                    f"Node {node['id']} did not produce output port {port['id']}",
                )


# Short alias for callers which prefer the plan's noun.
Scheduler = WorkflowScheduler
