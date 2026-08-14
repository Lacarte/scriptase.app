"""Step 10.3 — crash recovery and startup reconciliation.

Done when: a hard kill mid-run leaves no permanently-running execution, no
stale lock, and no orphaned staging directory after the next boot.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scriptase.engine.persistence import (
    load_execution,
    load_queue_record,
    save_execution,
    save_queue_record,
)
from scriptase.engine.reconciliation import (
    JOB_STATUS_REASON,
    PROCESS_INTERRUPTED_CODE,
    clear_orphaned_staging,
    reconcile_on_startup,
)
from scriptase.engine.scheduler import (
    ProjectLock,
    ProjectLockedError,
    clear_stale_project_locks,
    is_pid_alive,
    is_project_lock_stale,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _execution_doc(
    execution_id: str = "ex_ABC123",
    *,
    status: str = "running",
    nodes: dict | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "execution_id": execution_id,
        "workflow_id": "wf_ABC123",
        "workflow_snapshot": {
            "schema_version": 1,
            "workflow_id": "wf_ABC123",
            "name": "Crash recovery fixture",
            "nodes": [],
            "edges": [],
        },
        "project_id": "pm_ABC123",
        "run_mode": "full",
        "scope_node_ids": [],
        "status": status,
        "started_at": "2026-08-14T12:00:00+00:00",
        "finished_at": None,
        "nodes": nodes
        if nodes is not None
        else {
            "n_tts": {
                "status": "running",
                "attempts": 1,
                "duration_ms": None,
                "error": None,
                "logs": [],
                "attempt_errors": [],
                "artifact_refs": [],
                "resolved_inputs_summary": {},
                "outputs_summary": {},
            },
            "n_done": {
                "status": "succeeded",
                "attempts": 1,
                "duration_ms": 10,
                "error": None,
                "logs": [],
                "attempt_errors": [],
                "artifact_refs": [],
                "resolved_inputs_summary": {},
                "outputs_summary": {},
            },
        },
        "approval": None,
    }


def _queue_doc(
    execution_id: str = "ex_ABC123",
    *,
    status: str = "running",
) -> dict:
    return {
        "execution_id": execution_id,
        "workflow_id": "wf_ABC123",
        "project_id": "pm_ABC123",
        "status": status,
        "source": "manual",
        "requested_run_mode": "full",
        "target_node_ids": [],
        "requested_at": "2026-08-14T12:00:00+00:00",
        "started_at": "2026-08-14T12:00:01+00:00",
        "finished_at": None,
        "schema_version": 1,
    }


def _write_lock(path: Path, *, pid: int, project_id: str = "pm_ABC123") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "project_id": project_id,
            "execution_id": "ex_DEAD01",
            "pid": pid,
        }),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Process liveness + ProjectLock reclaim
# ---------------------------------------------------------------------------


def test_is_pid_alive_for_current_process():
    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_for_impossible_pid():
    # PIDs this large are not allocated on any common OS; treat as dead.
    assert is_pid_alive(2_147_483_647) is False
    assert is_pid_alive(0) is False
    assert is_pid_alive(-1) is False
    assert is_pid_alive(None) is False
    assert is_pid_alive("not-a-pid") is False


def test_stale_lock_is_reclaimed_on_acquire(tmp_path):
    root = tmp_path / "locks"
    lock_path = root / "pm_ABC123.lock"
    _write_lock(lock_path, pid=2_147_483_647)
    assert is_project_lock_stale(str(lock_path)) is True

    with ProjectLock("pm_ABC123", lock_root=str(root), execution_id="ex_NEW001"):
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        assert payload["pid"] == os.getpid()
        assert payload["execution_id"] == "ex_NEW001"


def test_live_lock_still_blocks(tmp_path):
    root = tmp_path / "locks"
    with ProjectLock("pm_ABC123", lock_root=str(root), execution_id="ex_LIVE01"):
        with pytest.raises(ProjectLockedError) as error:
            ProjectLock("pm_ABC123", lock_root=str(root), execution_id="ex_OTHER").acquire()
        assert error.value.code == "PROJECT_LOCKED"


def test_clear_stale_project_locks_only_removes_dead(tmp_path):
    root = tmp_path / "locks"
    dead = root / "pm_DEAD01.lock"
    live = root / "pm_LIVE01.lock"
    _write_lock(dead, pid=2_147_483_647, project_id="pm_DEAD01")
    _write_lock(live, pid=os.getpid(), project_id="pm_LIVE01")

    cleared = clear_stale_project_locks(str(root))
    assert cleared == ["pm_DEAD01"]
    assert not dead.exists()
    assert live.exists()


# ---------------------------------------------------------------------------
# Execution / queue / staging reconciliation
# ---------------------------------------------------------------------------


def test_reconcile_fails_running_execution_and_queue(tmp_path):
    output = tmp_path / "output"
    executions = output / "workflows" / "executions"
    queue = output / "workflows" / "queue"
    executions.mkdir(parents=True)
    queue.mkdir(parents=True)

    save_execution(_execution_doc("ex_RUN001", status="running"), root=str(executions))
    save_queue_record(_queue_doc("ex_RUN001", status="running"), root=str(queue))
    # Terminal control: must stay untouched.
    save_execution(
        {
            **_execution_doc("ex_OK0001", status="succeeded"),
            "finished_at": "2026-08-14T12:05:00+00:00",
            "nodes": {
                "n_done": {
                    "status": "succeeded",
                    "attempts": 1,
                    "error": None,
                    "logs": [],
                    "attempt_errors": [],
                    "artifact_refs": [],
                    "resolved_inputs_summary": {},
                    "outputs_summary": {},
                }
            },
        },
        root=str(executions),
    )

    report = reconcile_on_startup(
        output_dir=str(output),
        execution_root=str(executions),
        queue_root=str(queue),
        lock_root=str(output / "workflows" / "locks"),
        reconcile_jobs_flag=False,
    )

    assert "ex_RUN001" in report.executions_failed
    assert "ex_RUN001" in report.queue_failed
    assert "ex_OK0001" not in report.executions_failed

    repaired = load_execution("ex_RUN001", root=str(executions))
    assert repaired["status"] == "failed"
    assert repaired["finished_at"]
    assert repaired["nodes"]["n_tts"]["status"] == "failed"
    assert repaired["nodes"]["n_tts"]["error"]["code"] == PROCESS_INTERRUPTED_CODE
    # Successful nodes keep their status — only in-flight ones flip.
    assert repaired["nodes"]["n_done"]["status"] == "succeeded"

    q = load_queue_record("ex_RUN001", root=str(queue))
    assert q["status"] == "failed"
    assert q["finished_at"]

    # Terminal control unchanged.
    ok = load_execution("ex_OK0001", root=str(executions))
    assert ok["status"] == "succeeded"


def test_reconcile_preserves_awaiting_approval(tmp_path):
    output = tmp_path / "output"
    executions = output / "workflows" / "executions"
    queue = output / "workflows" / "queue"
    executions.mkdir(parents=True)
    queue.mkdir(parents=True)

    save_execution(
        _execution_doc(
            "ex_WAIT01",
            status="awaiting_approval",
            nodes={
                "n_gate": {
                    "status": "awaiting_approval",
                    "attempts": 1,
                    "error": None,
                    "logs": [],
                    "attempt_errors": [],
                    "artifact_refs": [],
                    "resolved_inputs_summary": {},
                    "outputs_summary": {},
                }
            },
        ),
        root=str(executions),
    )
    save_queue_record(
        _queue_doc("ex_WAIT01", status="awaiting_approval"),
        root=str(queue),
    )

    report = reconcile_on_startup(
        output_dir=str(output),
        execution_root=str(executions),
        queue_root=str(queue),
        lock_root=str(output / "workflows" / "locks"),
        reconcile_jobs_flag=False,
    )
    assert report.executions_failed == []
    assert report.queue_failed == []
    assert load_execution("ex_WAIT01", root=str(executions))["status"] == "awaiting_approval"
    assert load_queue_record("ex_WAIT01", root=str(queue))["status"] == "awaiting_approval"


def test_reconcile_clears_stale_locks_and_staging(tmp_path):
    output = tmp_path / "output"
    locks = output / "workflows" / "locks"
    staging = output / "workflows" / ".staging"
    locks.mkdir(parents=True)
    orphan = staging / "ex_DEAD01_xyz"
    orphan.mkdir(parents=True)
    (orphan / "artifact.bin").write_bytes(b"orphan")
    _write_lock(locks / "pm_STALE1.lock", pid=2_147_483_647, project_id="pm_STALE1")

    report = reconcile_on_startup(
        output_dir=str(output),
        execution_root=str(output / "workflows" / "executions"),
        queue_root=str(output / "workflows" / "queue"),
        lock_root=str(locks),
        reconcile_jobs_flag=False,
    )
    assert "pm_STALE1" in report.locks_cleared
    assert any(name.startswith("ex_DEAD01") for name in report.staging_removed)
    assert not (locks / "pm_STALE1.lock").exists()
    assert not orphan.exists()


def test_clear_orphaned_staging_is_idempotent(tmp_path):
    output = tmp_path / "output"
    staging = output / "workflows" / ".staging" / "ex_ABC123_tmp"
    staging.mkdir(parents=True)
    first = clear_orphaned_staging(output_dir=str(output))
    second = clear_orphaned_staging(output_dir=str(output))
    assert first
    assert second == []


def test_reconcile_is_idempotent_on_already_failed(tmp_path):
    output = tmp_path / "output"
    executions = output / "workflows" / "executions"
    queue = output / "workflows" / "queue"
    executions.mkdir(parents=True)
    queue.mkdir(parents=True)
    save_execution(_execution_doc("ex_RUN002", status="running"), root=str(executions))
    save_queue_record(_queue_doc("ex_RUN002", status="pending"), root=str(queue))

    first = reconcile_on_startup(
        output_dir=str(output),
        execution_root=str(executions),
        queue_root=str(queue),
        lock_root=str(output / "workflows" / "locks"),
        reconcile_jobs_flag=False,
    )
    second = reconcile_on_startup(
        output_dir=str(output),
        execution_root=str(executions),
        queue_root=str(queue),
        lock_root=str(output / "workflows" / "locks"),
        reconcile_jobs_flag=False,
    )
    assert "ex_RUN002" in first.executions_failed
    assert second.executions_failed == []
    assert second.queue_failed == []


# ---------------------------------------------------------------------------
# Job reconciliation
# ---------------------------------------------------------------------------


def test_reconcile_jobs_fails_running_and_started_queued(tmp_path, monkeypatch):
    from scriptase.jobs import store as job_store
    from scriptase.jobs.models import BudgetSpent, Job
    from scriptase.jobs.store import get_job

    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(job_store, "_jobs_dir", str(jobs_dir))
    monkeypatch.setattr(job_store, "_trash_dir", str(tmp_path / "trash" / "jobs"))

    def _job(
        job_id: str,
        *,
        status: str,
        execution_id: str | None,
    ) -> Job:
        return Job(
            id=job_id,
            schema_version=1,
            channel_id="ch_ABC123",
            channel_snapshot={
                "channel_id": "ch_ABC123",
                "name": "Fixture",
                "version": 1,
                "content": {},
                "visual_direction": {},
                "audio": {},
                "provider_instances": {},
            },
            workflow_id="wf_ABC123",
            workflow_version=None,
            execution_mode="automatic",
            source={"mode": "topic", "topic": "recovery"},
            status=status,
            status_reason=None,
            current_stage=None,
            artifacts=[],
            scenes=[],
            issues=[],
            repair_history=[],
            budget_spent=BudgetSpent(),
            execution_id=execution_id,
            created_at="2026-08-14T12:00:00+00:00",
            started_at="2026-08-14T12:00:01+00:00" if execution_id else None,
            completed_at=None,
        )

    # Bypass create_job (needs a real Channel) and write documents directly.
    for document in (
        _job("job_RUN001", status="running", execution_id="ex_RUN001"),
        _job("job_QED001", status="queued", execution_id="ex_QED001"),
        _job("job_IDLE01", status="queued", execution_id=None),
        _job("job_WAIT01", status="awaiting_approval", execution_id="ex_WAIT01"),
        _job("job_DONE01", status="completed", execution_id="ex_DONE01"),
    ):
        if document.status == "completed":
            document = document.model_copy(
                update={"completed_at": "2026-08-14T12:10:00+00:00"}
            )
        job_store._write(document)

    report = reconcile_on_startup(
        output_dir=str(tmp_path / "output"),
        execution_root=str(tmp_path / "empty_ex"),
        queue_root=str(tmp_path / "empty_q"),
        lock_root=str(tmp_path / "empty_locks"),
        reconcile_jobs_flag=True,
    )
    assert set(report.jobs_failed) == {"job_RUN001", "job_QED001"}

    assert get_job("job_RUN001").status == "failed"
    assert get_job("job_RUN001").status_reason == JOB_STATUS_REASON
    assert get_job("job_QED001").status == "failed"
    # Idle queued (never started) and durable pause stay put.
    assert get_job("job_IDLE01").status == "queued"
    assert get_job("job_WAIT01").status == "awaiting_approval"
    assert get_job("job_DONE01").status == "completed"


# ---------------------------------------------------------------------------
# App factory wiring
# ---------------------------------------------------------------------------


def test_create_app_runs_reconciliation_when_enabled(tmp_path, monkeypatch):
    from app import create_app

    called = {}

    def fake_reconcile():
        called["yes"] = True
        return {"changed": False}

    monkeypatch.setattr("app.run_startup_reconciliation", fake_reconcile)
    # Force-on regardless of conftest's SCRIPTASE_DISABLE_RECONCILE.
    create_app(discover_providers=False, start_triggers=False, reconcile=True)
    assert called.get("yes") is True


def test_create_app_skips_reconciliation_when_disabled(monkeypatch):
    from app import create_app

    called = {}

    def fake_reconcile():
        called["yes"] = True
        return {"changed": False}

    monkeypatch.setattr("app.run_startup_reconciliation", fake_reconcile)
    create_app(discover_providers=False, start_triggers=False, reconcile=False)
    assert "yes" not in called


def test_hard_kill_simulation_end_to_end(tmp_path):
    """A mid-run kill leaves running records + lock + staging; boot clears all three."""
    output = tmp_path / "output"
    executions = output / "workflows" / "executions"
    queue = output / "workflows" / "queue"
    locks = output / "workflows" / "locks"
    staging = output / "workflows" / ".staging" / "ex_KILL01_abc"
    executions.mkdir(parents=True)
    queue.mkdir(parents=True)
    locks.mkdir(parents=True)
    staging.mkdir(parents=True)
    (staging / "partial.bin").write_bytes(b"half")

    save_execution(_execution_doc("ex_KILL01", status="running"), root=str(executions))
    save_queue_record(_queue_doc("ex_KILL01", status="running"), root=str(queue))
    _write_lock(locks / "pm_ABC123.lock", pid=2_147_483_647)

    # Simulate the next process boot.
    report = reconcile_on_startup(
        output_dir=str(output),
        execution_root=str(executions),
        queue_root=str(queue),
        lock_root=str(locks),
        reconcile_jobs_flag=False,
    )

    assert load_execution("ex_KILL01", root=str(executions))["status"] == "failed"
    assert load_queue_record("ex_KILL01", root=str(queue))["status"] == "failed"
    assert not (locks / "pm_ABC123.lock").exists()
    assert not staging.exists()
    # A new lock can be taken immediately after boot.
    with ProjectLock("pm_ABC123", lock_root=str(locks), execution_id="ex_RETRY1"):
        pass
    assert report.changed is True
