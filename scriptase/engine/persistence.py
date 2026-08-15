"""Atomic file persistence for workflow definitions."""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import string
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta

from config import TRASH_DIR, WORKFLOWS_DIR, WORKFLOW_EXECUTIONS_DIR
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

from .models import summary
from .migrations import MigrationResult, NodeMigrationError, migrate_workflow
from .redaction import redact
from .templates import full_video_template
from .validation import WORKFLOW_ID_RE, validate_workflow, validation_errors

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class WorkflowNotFound(FileNotFoundError):
    pass


class WorkflowConflict(RuntimeError):
    pass


class WorkflowValidationError(ValueError):
    def __init__(self, problems: list[dict]):
        super().__init__("Workflow has validation errors")
        self.problems = problems


class WorkflowReadOnlyError(RuntimeError):
    pass


EXECUTIONS_DIR = WORKFLOW_EXECUTIONS_DIR
QUEUE_DIR = os.path.join(os.path.dirname(EXECUTIONS_DIR), "queue")
EXECUTION_ID_RE = re.compile(r"^ex_[A-Za-z0-9]{6}$")


def _strict_id(workflow_id: str) -> str:
    if not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise ValueError("workflow_id must match wf_XXXXXX")
    return workflow_id


# ---------------------------------------------------------------------------
# Single-writer locking (step 6.2)
#
# Read-modify-write cycles (update, delete) must be serialized per workflow so
# two interleaved writers can never both pass the optimistic ``updated_at``
# check: the loser must observe the winner's write and raise WorkflowConflict.
# An in-process per-path threading.Lock serializes app threads; an exclusive
# OS lock on a ``.json.lock`` sidecar file serializes across processes.
# ---------------------------------------------------------------------------

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _lock_fd(fd: int) -> None:
    if os.name == "nt":
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # Blocking with bounded retries.
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    if os.name == "nt":
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _workflow_write_lock(workflow_id: str):
    """Hold the single-writer lock for one workflow's read-modify-write cycle."""
    lock_path = _path(workflow_id) + ".lock"
    key = os.path.normcase(os.path.abspath(lock_path))
    with _thread_lock(key):
        os.makedirs(WORKFLOWS_DIR, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            _lock_fd(fd)
            try:
                yield lock_path
            finally:
                _unlock_fd(fd)
        finally:
            os.close(fd)


def _monotonic_timestamp(previous: str | None) -> str:
    """Return now, but strictly after ``previous`` so optimistic concurrency
    tokens can never alias even when the clock has not advanced."""
    stamp = now_iso()
    if previous:
        try:
            previous_dt = datetime.fromisoformat(previous)
            if datetime.fromisoformat(stamp) <= previous_dt:
                stamp = (previous_dt + timedelta(microseconds=1)).isoformat()
        except (TypeError, ValueError):
            pass
    return stamp


def _path(workflow_id: str) -> str:
    return safe_join(WORKFLOWS_DIR, f"{_strict_id(workflow_id)}.json")


def _generate_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "wf_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(_path(candidate)):
            return candidate
    raise RuntimeError("Could not allocate a workflow id")


def _validate_or_raise(
    document: dict, *, require_complete: bool = False, allow_future_versions: bool = False
) -> list[dict]:
    problems = validate_workflow(
        document,
        require_identity=True,
        require_complete=require_complete,
        allow_future_versions=allow_future_versions,
    )
    errors = validation_errors(problems)
    if errors:
        raise WorkflowValidationError(problems)
    return problems


def create_workflow(draft: dict) -> dict:
    document = deepcopy(draft)
    document["workflow_id"] = _generate_id()
    timestamp = now_iso()
    document["created_at"] = timestamp
    document["updated_at"] = timestamp
    document.setdefault("description", "")
    document.setdefault("variables", {})
    document.setdefault("viewport", {"x": 0, "y": 0, "zoom": 1})
    document.setdefault("settings", {"on_error": "stop"})
    document.setdefault("extensions", {})
    document = redact(document)
    _validate_or_raise(document)
    safe_json_write(_path(document["workflow_id"]), document, indent=2)
    return document


def load_workflow_state(workflow_id: str) -> MigrationResult:
    path = _path(workflow_id)
    try:
        document = safe_json_read(path)
    except FileNotFoundError as exc:
        raise WorkflowNotFound(workflow_id) from exc
    document = redact(document)
    try:
        state = migrate_workflow(document)
    except NodeMigrationError as exc:
        raise WorkflowValidationError([{
            "code": "NODE_MIGRATION_FAILED",
            "message": str(exc),
            "severity": "error",
            "path": "nodes",
        }]) from exc
    findings = _validate_or_raise(state.document, allow_future_versions=state.read_only)
    validation_warnings = [item for item in findings if item.get("severity") == "warning"]
    # migrate_workflow supplies the more readable future-version warning;
    # retain unrelated validation warnings without duplicating that code.
    warnings = state.warnings + [
        item for item in validation_warnings if item.get("code") != "FUTURE_NODE_VERSION"
    ]
    return MigrationResult(state.document, state.trail, state.read_only, warnings)


def load_workflow(workflow_id: str) -> dict:
    return load_workflow_state(workflow_id).document


def list_workflows(*, limit: int = 100) -> tuple[list[dict], int]:
    os.makedirs(WORKFLOWS_DIR, exist_ok=True)
    items = []
    for filename in os.listdir(WORKFLOWS_DIR):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        workflow_id = filename[:-5]
        if not WORKFLOW_ID_RE.fullmatch(workflow_id):
            continue
        try:
            items.append(summary(load_workflow(workflow_id)))
        except (ValueError, OSError):
            continue
    items.sort(key=lambda item: (item.get("updated_at") or "", item["workflow_id"]), reverse=True)
    return items[:limit], len(items)


DEFAULT_WORKFLOW_TEMPLATE_ID = "full_video"
DEFAULT_WORKFLOW_MARKER = ".default-workflow-seeded"


def ensure_default_workflow() -> dict | None:
    """Materialise the Full Video template on a fresh install (step 12.2).

    A brand-new installation has no saved workflows, so the builder opens on a
    blank canvas and Production's workflow dropdown has nothing to offer.
    Seeding the Full Video template as a real, editable workflow gives both a
    complete, runnable starting point.

    Seeding is a once-per-installation event, recorded by a marker file: a user
    who deliberately deletes every workflow must not find one resurrected on the
    next boot. Returns the created document, or ``None`` when nothing was done.
    """
    os.makedirs(WORKFLOWS_DIR, exist_ok=True)
    marker = os.path.join(WORKFLOWS_DIR, DEFAULT_WORKFLOW_MARKER)
    if os.path.exists(marker):
        return None
    document = None
    if not list_workflows(limit=1)[0]:
        draft = full_video_template()
        draft.pop("template_id", None)  # Presentation-only key, never persisted.
        document = create_workflow(draft)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write(now_iso())
    return document


def update_workflow(workflow_id: str, draft: dict, *, expected_updated_at: str) -> dict:
    workflow_id = _strict_id(workflow_id)
    with _workflow_write_lock(workflow_id):
        # Go through the public loader so instrumentation and the established
        # single-writer tests observe the complete read inside this lock.
        current = load_workflow(workflow_id)
        current_state = migrate_workflow(current)
        if current_state.read_only:
            raise WorkflowReadOnlyError(workflow_id)
        if not expected_updated_at or current.get("updated_at") != expected_updated_at:
            raise WorkflowConflict(workflow_id)
        document = deepcopy(draft)
        document["workflow_id"] = workflow_id
        document["created_at"] = current["created_at"]
        document["updated_at"] = _monotonic_timestamp(current.get("updated_at"))
        document = redact(document)
        _validate_or_raise(document)
        safe_json_write(_path(workflow_id), document, indent=2)
        return document


def _stored_updated_at(path: str) -> str | None:
    """Best-effort ``updated_at`` read directly from the primary file.

    Never falls back to (or restores) the ``.bak`` copy: the delete path must
    not resurrect a workflow it is about to trash, and a file that no longer
    parses simply yields ``None`` so it can still be deleted.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return None
    value = document.get("updated_at") if isinstance(document, dict) else None
    return value if isinstance(value, str) else None


def _move_into_trash(source: str, destination: str) -> None:
    try:
        os.replace(source, destination)  # Atomic on the same volume.
    except OSError:
        shutil.move(source, destination)


def delete_workflow(workflow_id: str, *, expected_updated_at: str | None = None) -> None:
    """Trash a workflow atomically, even when the stored file no longer parses.

    The ``.bak`` copy moves first: if the process dies mid-delete the primary
    file is still intact, whereas the reverse order would leave a stale
    ``.bak`` from which ``safe_json_read`` would resurrect the workflow.
    """
    workflow_id = _strict_id(workflow_id)
    source = _path(workflow_id)
    backup = source + ".bak"
    with _workflow_write_lock(workflow_id) as lock_path:
        if not os.path.isfile(source) and not os.path.isfile(backup):
            raise WorkflowNotFound(workflow_id)
        if expected_updated_at:
            current = _stored_updated_at(source)
            if current is not None and current != expected_updated_at:
                raise WorkflowConflict(workflow_id)
        trash_root = safe_join(TRASH_DIR, "workflows")
        os.makedirs(trash_root, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = safe_join(trash_root, f"{workflow_id}_{stamp}.json")
        counter = 1
        while os.path.exists(destination) or os.path.exists(destination + ".bak"):
            counter += 1
            destination = safe_join(trash_root, f"{workflow_id}_{stamp}_{counter}.json")
        if os.path.isfile(backup):
            _move_into_trash(backup, destination + ".bak")
        if os.path.isfile(source):
            _move_into_trash(source, destination)
    try:
        os.unlink(lock_path)  # Best-effort sidecar cleanup after release.
    except OSError:
        pass


def import_workflow(document: dict, *, on_conflict: str = "new_id") -> tuple[dict, str | None]:
    """Import a workflow document, applying ``type_version`` migrations first.

    Step 10.1: V2 (and older) saved workflows still carry v1 node configs
    (``engine`` / ``provider``). Those fail validation against the current
    schema, so migration runs before create. Already-current documents pass
    through unchanged.
    """
    original_id = document.get("workflow_id") if isinstance(document, dict) else None
    if on_conflict not in {"new_id", "reject"}:
        raise ValueError("on_conflict must be new_id or reject")
    if original_id is not None and (
        not isinstance(original_id, str) or not WORKFLOW_ID_RE.fullmatch(original_id)
    ):
        raise WorkflowValidationError([{
            "code": "WORKFLOW_INVALID",
            "message": "Imported workflow_id must match wf_XXXXXX",
            "severity": "error",
            "path": "workflow_id",
        }])
    if on_conflict == "reject" and isinstance(original_id, str) and WORKFLOW_ID_RE.fullmatch(original_id):
        if os.path.exists(_path(original_id)):
            raise WorkflowConflict(original_id)
    try:
        state = migrate_workflow(document if isinstance(document, dict) else {})
    except NodeMigrationError as exc:
        raise WorkflowValidationError([{
            "code": "NODE_MIGRATION_FAILED",
            "message": str(exc),
            "severity": "error",
            "path": "nodes",
        }]) from exc
    if state.read_only:
        raise WorkflowValidationError([{
            "code": "UNSUPPORTED_NODE_VERSION",
            "message": "Imported workflow uses a future node version this installation cannot accept",
            "severity": "error",
            "path": "nodes",
        }])
    draft = deepcopy(state.document)
    for field in ("workflow_id", "created_at", "updated_at"):
        draft.pop(field, None)
    return create_workflow(draft), original_id


def _strict_execution_id(execution_id: str) -> str:
    if not isinstance(execution_id, str) or not EXECUTION_ID_RE.fullmatch(execution_id):
        raise ValueError("execution_id must match ex_XXXXXX")
    return execution_id


def execution_path(execution_id: str, *, root: str | None = None) -> str:
    return safe_join(root or EXECUTIONS_DIR, f"{_strict_execution_id(execution_id)}.json")


def execution_snapshot_path(execution_id: str, *, root: str | None = None) -> str:
    """Sidecar for the immutable workflow snapshot (step 10.2 incremental writes)."""
    return safe_join(
        root or EXECUTIONS_DIR,
        f"{_strict_execution_id(execution_id)}.workflow_snapshot.json",
    )


def generate_execution_id(*, root: str | None = None) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "ex_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(execution_path(candidate, root=root)):
            return candidate
    raise RuntimeError("Could not allocate an execution id")


def _execution_index(root: str | None = None):
    from .storage_index import get_storage_index, workflows_index_path
    directory = root or EXECUTIONS_DIR
    return get_storage_index(workflows_index_path(execution_root=directory))


def _queue_index(root: str | None = None):
    from .storage_index import get_storage_index, queue_index_path
    directory = root or QUEUE_DIR
    return get_storage_index(queue_index_path(queue_root=directory))


def _ensure_execution_index(directory: str) -> None:
    """Rebuild the executions index when documents exist but the table is empty."""
    from .storage_index import count_json_documents

    index = _execution_index(directory)
    file_count = count_json_documents(directory, id_prefix="ex_")
    if file_count > 0 and index.count_executions() == 0:
        index.rebuild_executions(
            directory,
            load_record=lambda execution_id: load_execution(execution_id, root=directory),
        )


def _ensure_queue_index(directory: str) -> None:
    from .storage_index import count_json_documents

    index = _queue_index(directory)
    file_count = count_json_documents(directory, id_prefix="ex_")
    if file_count > 0 and index.count_queue() == 0:
        index.rebuild_queue(
            directory,
            load_record=lambda execution_id: load_queue_record(execution_id, root=directory),
        )


def save_execution(
    record,
    *,
    root: str | None = None,
    secrets=(),
    mode: str = "full",
) -> dict:
    """Atomically persist a redacted execution record and return that exact shape.

    ``mode``:

    * ``"full"`` — write the complete document (including ``workflow_snapshot``)
      with a ``.bak`` rotation. Used at start, terminal finish, and other
      authoritative checkpoints.
    * ``"incremental"`` — write only the mutable envelope (status, nodes,
      approval, timestamps). The immutable ``workflow_snapshot`` is stored once
      in a sidecar and not rewritten on every node status transition
      (step 10.2). No ``.bak`` copy is taken for these high-frequency writes.
    """
    if mode not in {"full", "incremental"}:
        raise ValueError("mode must be 'full' or 'incremental'")
    document = record.to_dict() if hasattr(record, "to_dict") else deepcopy(record)
    document = redact(document, secrets=secrets)
    execution_id = _strict_execution_id(document.get("execution_id"))
    directory = root or EXECUTIONS_DIR
    path = execution_path(execution_id, root=directory)
    snapshot = document.get("workflow_snapshot")
    snap_path = execution_snapshot_path(execution_id, root=directory)

    if isinstance(snapshot, dict):
        # Snapshot is immutable for the life of a run — write the sidecar once.
        if not os.path.isfile(snap_path):
            safe_json_write(snap_path, snapshot, indent=2)

    if mode == "full":
        # Terminal / checkpoint form: single self-contained document so
        # direct file readers and archives keep working unchanged.
        safe_json_write(path, document, indent=2, backup=True)
    else:
        envelope = {key: value for key, value in document.items() if key != "workflow_snapshot"}
        envelope["_snapshot_ref"] = os.path.basename(snap_path)
        safe_json_write(path, envelope, indent=2, backup=False)

    try:
        _execution_index(directory).upsert_execution(document)
    except Exception:
        # Index is a performance aid; a failed upsert must never fail a run.
        # The next list_* call rebuilds from disk if the table is empty.
        pass
    return document


def load_execution(execution_id: str, *, root: str | None = None) -> dict:
    directory = root or EXECUTIONS_DIR
    document = safe_json_read(execution_path(execution_id, root=directory))
    if not isinstance(document, dict):
        return document
    needs_snapshot = (
        "workflow_snapshot" not in document
        or document.get("_snapshot_ref")
        or not isinstance(document.get("workflow_snapshot"), dict)
    )
    if needs_snapshot:
        snap_path = execution_snapshot_path(execution_id, root=directory)
        ref = document.pop("_snapshot_ref", None)
        if ref and isinstance(ref, str):
            # Managed relative name only — never honour absolute paths.
            candidate = safe_join(directory, os.path.basename(ref))
            if os.path.isfile(candidate):
                snap_path = candidate
        if os.path.isfile(snap_path):
            document["workflow_snapshot"] = safe_json_read(snap_path)
        else:
            document.pop("_snapshot_ref", None)
            document.setdefault("workflow_snapshot", {})
    else:
        document.pop("_snapshot_ref", None)
    return document


def list_executions(workflow_id: str, *, limit: int = 100, root: str | None = None) -> tuple[list[dict], int]:
    if not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise ValueError("workflow_id must match wf_XXXXXX")
    directory = root or EXECUTIONS_DIR
    os.makedirs(directory, exist_ok=True)
    try:
        _ensure_execution_index(directory)
        return _execution_index(directory).list_executions(workflow_id, limit=limit)
    except Exception:
        # Fall back to the pre-10.2 full scan if the index is unusable.
        return _list_executions_scan(workflow_id, limit=limit, directory=directory)


def _list_executions_scan(
    workflow_id: str, *, limit: int, directory: str
) -> tuple[list[dict], int]:
    items = []
    for filename in os.listdir(directory):
        execution_id = filename[:-5] if filename.endswith(".json") else ""
        if not EXECUTION_ID_RE.fullmatch(execution_id):
            continue
        try:
            record = load_execution(execution_id, root=directory)
        except (OSError, ValueError):
            continue
        if record.get("workflow_id") != workflow_id:
            continue
        items.append({
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "project_id": record.get("project_id"),
            "run_mode": record.get("run_mode"),
            "status": record.get("status"),
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
        })
    items.sort(key=lambda item: (item.get("started_at") or "", item["execution_id"]), reverse=True)
    return items[:limit], len(items)


def queue_path(execution_id: str, *, root: str | None = None) -> str:
    return safe_join(root or QUEUE_DIR, f"{_strict_execution_id(execution_id)}.json")


def save_queue_record(record, *, root: str | None = None) -> dict:
    """Atomically persist a queue record beside the execution store."""
    document = record.to_dict() if hasattr(record, "to_dict") else deepcopy(record)
    _strict_execution_id(document.get("execution_id"))
    # awaiting_approval is a durable pause (step 2.6): worker released, not terminal.
    if document.get("status") not in {
        "pending", "running", "done", "failed", "cancelled", "awaiting_approval",
    }:
        raise ValueError("Invalid queue status")
    if document.get("source") not in {"manual", "schedule", "watch", "webhook"}:
        raise ValueError("Invalid queue source")
    redacted = redact(document)
    directory = root or QUEUE_DIR
    safe_json_write(queue_path(document["execution_id"], root=directory), redacted, indent=2)
    try:
        _queue_index(directory).upsert_queue(redacted)
    except Exception:
        pass
    return redacted


def load_queue_record(execution_id: str, *, root: str | None = None) -> dict:
    return safe_json_read(queue_path(execution_id, root=root))


def list_queue_records(
    workflow_id: str, *, limit: int = 100, root: str | None = None
) -> tuple[list[dict], int]:
    if not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise ValueError("workflow_id must match wf_XXXXXX")
    directory = root or QUEUE_DIR
    os.makedirs(directory, exist_ok=True)
    try:
        _ensure_queue_index(directory)
        return _queue_index(directory).list_queue(workflow_id, limit=limit)
    except Exception:
        return _list_queue_scan(workflow_id, limit=limit, directory=directory)


def _list_queue_scan(
    workflow_id: str, *, limit: int, directory: str
) -> tuple[list[dict], int]:
    items = []
    for filename in os.listdir(directory):
        execution_id = filename[:-5] if filename.endswith(".json") else ""
        if not EXECUTION_ID_RE.fullmatch(execution_id):
            continue
        try:
            record = load_queue_record(execution_id, root=directory)
        except (OSError, ValueError):
            continue
        if record.get("workflow_id") == workflow_id:
            items.append(record)
    items.sort(
        key=lambda item: (item.get("requested_at") or "", item["execution_id"]), reverse=True
    )
    return items[:limit], len(items)

