"""Step 10.2 — Indexed storage for runs, queue, jobs, and notifications.

Done when:
* listing five hundred executions is constant-query rather than a full scan
* a twenty-node run performs an order of magnitude fewer full-document writes
* the entire engine suite passes unchanged (behaviour behind existing interfaces)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from scriptase.engine.models import ExecutionRecord, NodeExecutionRecord, QueueRecord
from scriptase.engine.notifications import (
    dispatch_run_notification,
    list_notifications,
    mark_notifications_seen,
)
from scriptase.engine.persistence import (
    list_executions,
    list_queue_records,
    load_execution,
    save_execution,
    save_queue_record,
)
from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.engine.storage_index import (
    count_json_documents,
    get_storage_index,
    reset_storage_indexes,
    workflows_index_path,
)
from scriptase.shared.io_utils import safe_json_write


@pytest.fixture(autouse=True)
def _clean_indexes():
    reset_storage_indexes()
    yield
    reset_storage_indexes()


def _execution_id(index: int) -> str:
    """Return a unique ``ex_XXXXXX`` id for ``index`` (0..36^6)."""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    n = index
    body = []
    for _ in range(6):
        body.append(chars[n % 36])
        n //= 36
    return "ex_" + "".join(reversed(body))


def _minimal_workflow(workflow_id: str = "wf_ABC123", *, node_count: int = 1) -> dict:
    # Independent trigger.manual nodes — no edges — so a 20-node run is a
    # pure fan-out that still hits the per-node status-transition write path.
    nodes = [
        {
            "id": f"n_{index:02d}",
            "type": "trigger.manual",
            "type_version": 1,
            "name": f"Node {index}",
            "position": {"x": index * 40, "y": 0},
            "configuration": {},
            "disabled": False,
        }
        for index in range(node_count)
    ]
    return {
        "schema_version": 1,
        "workflow_id": workflow_id,
        "name": "Indexed storage",
        "description": "x" * 500,
        "nodes": nodes,
        "edges": [],
        "variables": {"pad": "y" * 500},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
        "created_at": "2026-08-04T12:00:00Z",
        "updated_at": "2026-08-04T12:00:00Z",
    }


def test_list_executions_is_index_backed_not_full_scan(tmp_path):
    execution_root = tmp_path / "workflows" / "executions"
    execution_root.mkdir(parents=True)
    workflow_id = "wf_IDX001"
    snapshot = _minimal_workflow(workflow_id)

    ids = []
    for index in range(500):
        execution_id = _execution_id(index)
        ids.append(execution_id)
        save_execution(
            ExecutionRecord(
                execution_id=execution_id,
                workflow_id=workflow_id,
                workflow_snapshot=snapshot,
                project_id="pm_ABC123",
                status="succeeded",
                started_at=f"2026-01-01T00:00:{index % 60:02d}.{index:03d}Z",
                finished_at=f"2026-01-01T00:01:{index % 60:02d}.{index:03d}Z",
                nodes={"n_00": NodeExecutionRecord(status="succeeded")},
            ),
            root=str(execution_root),
            mode="full",
        )

    opens: list[str] = []
    real_open = open

    def tracking_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str.endswith(".json") and "executions" in path_str.replace("\\", "/"):
            opens.append(path_str)
        return real_open(path, *args, **kwargs)

    with mock.patch("builtins.open", tracking_open):
        items, total = list_executions(workflow_id, limit=50, root=str(execution_root))

    assert total == 500
    assert len(items) == 50
    # Constant-query: SQLite only — no per-document JSON reads.
    assert len(opens) == 0
    assert all(item["workflow_id"] == workflow_id for item in items)
    assert items[0]["execution_id"] in ids


def test_list_executions_rebuilds_index_from_preexisting_files(tmp_path):
    execution_root = tmp_path / "workflows" / "executions"
    execution_root.mkdir(parents=True)
    workflow_id = "wf_RBLD01"
    path = execution_root / "ex_RBLD01.json"
    safe_json_write(
        str(path),
        {
            "execution_id": "ex_RBLD01",
            "workflow_id": workflow_id,
            "workflow_snapshot": _minimal_workflow(workflow_id),
            "project_id": "pm_ABC123",
            "run_mode": "full",
            "status": "succeeded",
            "started_at": "2026-08-04T12:00:00Z",
            "finished_at": "2026-08-04T12:00:01Z",
            "nodes": {},
            "schema_version": 1,
        },
        indent=2,
    )
    db_path = workflows_index_path(execution_root=str(execution_root))
    if os.path.isfile(db_path):
        os.unlink(db_path)
    reset_storage_indexes()

    items, total = list_executions(workflow_id, root=str(execution_root))
    assert total == 1
    assert items[0]["execution_id"] == "ex_RBLD01"
    assert get_storage_index(db_path).count_executions(workflow_id) == 1


def test_twenty_node_run_uses_mostly_incremental_writes(tmp_path):
    workflow = _minimal_workflow("wf_WRITES", node_count=20)
    full_modes: list[str] = []
    incremental_modes: list[str] = []

    real_save = save_execution

    def counting_save(record, *, root=None, secrets=(), mode="full"):
        if mode == "full":
            full_modes.append(mode)
        else:
            incremental_modes.append(mode)
        return real_save(record, root=root, secrets=secrets, mode=mode)

    def resolver(_node):
        def execute(_inputs, _config, _context):
            return {"control": {"ok": True}}
        return execute

    with mock.patch("scriptase.engine.scheduler.save_execution", counting_save):
        result = WorkflowScheduler(
            workflow,
            project_id="pm_ABC123",
            execution_id="ex_WRITE1",
            output_dir=str(tmp_path),
            lock_root=str(tmp_path / "locks"),
            executor_resolver=resolver,
        ).run()

    assert result.status == "succeeded"
    # Pre-10.2: ~3 full writes per node × 20 ≈ 60. Require an order of magnitude fewer fulls.
    assert len(full_modes) <= 10, f"expected ≤10 full writes, got {len(full_modes)}"
    assert len(incremental_modes) >= 20, (
        f"expected many incremental node writes, got {len(incremental_modes)}"
    )

    record = load_execution("ex_WRITE1", root=str(tmp_path / "workflows" / "executions"))
    assert record["status"] == "succeeded"
    assert isinstance(record.get("workflow_snapshot"), dict)
    assert len(record["nodes"]) == 20
    assert (tmp_path / "workflows" / "executions" / "ex_WRITE1.workflow_snapshot.json").is_file()


def test_incremental_load_merges_snapshot_sidecar(tmp_path):
    root = str(tmp_path / "workflows" / "executions")
    os.makedirs(root, exist_ok=True)
    snapshot = _minimal_workflow("wf_MERGE1")
    record = ExecutionRecord(
        execution_id="ex_MERGE1",
        workflow_id="wf_MERGE1",
        workflow_snapshot=snapshot,
        project_id="pm_ABC123",
        status="running",
        started_at="2026-08-04T12:00:00Z",
        nodes={"n_00": NodeExecutionRecord(status="running")},
    )
    save_execution(record, root=root, mode="full")
    record.nodes["n_00"] = NodeExecutionRecord(status="succeeded", attempts=1)
    save_execution(record, root=root, mode="incremental")

    raw = json.loads((Path(root) / "ex_MERGE1.json").read_text(encoding="utf-8"))
    assert raw.get("_snapshot_ref")
    assert "workflow_snapshot" not in raw

    loaded = load_execution("ex_MERGE1", root=root)
    assert loaded["nodes"]["n_00"]["status"] == "succeeded"
    assert loaded["workflow_snapshot"]["workflow_id"] == "wf_MERGE1"
    assert "_snapshot_ref" not in loaded


def test_queue_and_notifications_list_via_index(tmp_path):
    queue_root = tmp_path / "workflows" / "queue"
    queue_root.mkdir(parents=True)
    workflow_id = "wf_QNOT01"

    for index in range(30):
        save_queue_record(
            QueueRecord(
                execution_id=_execution_id(index),
                workflow_id=workflow_id,
                project_id="pm_ABC123",
                status="done",
                source="manual",
                requested_at=f"2026-08-04T12:00:{index:02d}Z",
                finished_at=f"2026-08-04T12:01:{index:02d}Z",
            ),
            root=str(queue_root),
        )

    items, total = list_queue_records(workflow_id, limit=10, root=str(queue_root))
    assert total == 30
    assert len(items) == 10
    assert all(item["workflow_id"] == workflow_id for item in items)

    for index in range(5):
        execution_id = f"ex_NT{index:04d}"
        dispatch_run_notification(
            {
                "workflow_id": workflow_id,
                "name": "Notify",
                "settings": {
                    "notifications": {
                        "on_completion": True,
                        "on_failure": False,
                        "windows_toast": False,
                        "webhook": {"enabled": False, "url": ""},
                    }
                },
            },
            {
                "execution_id": execution_id,
                "workflow_id": workflow_id,
                "project_id": "pm_ABC123",
                "status": "succeeded",
                "finished_at": f"2026-08-04T13:00:0{index}Z",
            },
            output_dir=str(tmp_path),
        )

    records, n_total, unseen = list_notifications(workflow_id, output_dir=str(tmp_path), limit=10)
    assert n_total == unseen == 5
    assert len(records) == 5
    changed = mark_notifications_seen(workflow_id, output_dir=str(tmp_path))
    assert changed == 5
    _records, _total, unseen_after = list_notifications(workflow_id, output_dir=str(tmp_path))
    assert unseen_after == 0


def test_jobs_list_uses_index(tmp_path):
    from scriptase.channels import store as channel_store
    from scriptase.channels.store import create_channel, default_draft as channel_default_draft
    from scriptase.jobs import store as job_store
    from scriptase.jobs.store import create_job, list_jobs

    old_channels = channel_store._channels_dir
    old_channel_trash = channel_store._trash_dir
    old_jobs = job_store._jobs_dir
    old_job_trash = job_store._trash_dir
    try:
        channel_store._channels_dir = str(tmp_path / "channels")
        channel_store._trash_dir = str(tmp_path / "trash" / "channels")
        job_store._jobs_dir = str(tmp_path / "jobs")
        job_store._trash_dir = str(tmp_path / "trash" / "jobs")
        os.makedirs(channel_store._channels_dir, exist_ok=True)
        os.makedirs(job_store._jobs_dir, exist_ok=True)

        draft = channel_default_draft(name="Index Channel")
        draft["content"] = {
            "niche": "stoicism",
            "language": "en",
            "tone": "educational",
            "duration_target": 60,
        }
        channel = create_channel(draft)

        for index in range(20):
            create_job({
                "channel_id": channel.id,
                "execution_mode": "manual",
                "source": {"mode": "topic", "topic": f"topic-{index}"},
            })

        listed = list_jobs(channel_id=channel.id, limit=10)
        assert len(listed) == 10
        assert all(job.channel_id == channel.id for job in listed)
        assert (tmp_path / "jobs" / "index.db").is_file()
    finally:
        channel_store._channels_dir = old_channels
        channel_store._trash_dir = old_channel_trash
        job_store._jobs_dir = old_jobs
        job_store._trash_dir = old_job_trash


def test_count_json_documents_skips_snapshot_sidecars(tmp_path):
    root = tmp_path / "executions"
    root.mkdir()
    (root / "ex_AAAAAA.json").write_text("{}", encoding="utf-8")
    (root / "ex_AAAAAA.workflow_snapshot.json").write_text("{}", encoding="utf-8")
    (root / "ex_AAAAAA.json.bak").write_text("{}", encoding="utf-8")
    assert count_json_documents(str(root), id_prefix="ex_") == 1
