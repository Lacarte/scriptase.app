"""SQLite secondary indexes for runs, queue, jobs, and notifications (step 10.2).

Full documents stay on disk as JSON (artifacts/media unchanged). These indexes
exist only so listing is a constant-time SQL query instead of scanning and
parsing every file. Every public save/list path goes through the existing
repository functions in ``persistence``, ``notifications``, and ``jobs.store``;
callers must not open this module for business logic.

Index files live beside their document trees:

* ``{workflows}/index.db`` — executions, queue records, notifications
* ``{jobs}/index.db`` — jobs

When an index is missing or empty while documents exist on disk, the next list
call rebuilds it from a one-time scan. Writes always update the index after the
JSON document is durable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Iterable, Mapping

from scriptase.shared.io_utils import safe_json_read

_SCHEMA_VERSION = 1

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    project_id TEXT,
    run_mode TEXT,
    status TEXT,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_executions_workflow_started
    ON executions (workflow_id, started_at DESC, execution_id DESC);

CREATE TABLE IF NOT EXISTS queue (
    execution_id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    project_id TEXT,
    status TEXT,
    source TEXT,
    requested_run_mode TEXT,
    requested_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    document_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queue_workflow_requested
    ON queue (workflow_id, requested_at DESC, execution_id DESC);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    project_id TEXT,
    outcome TEXT,
    created_at TEXT,
    seen INTEGER NOT NULL DEFAULT 0,
    document_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_workflow_created
    ON notifications (workflow_id, created_at DESC, notification_id DESC);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    status TEXT,
    created_at TEXT,
    workflow_id TEXT,
    execution_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created
    ON jobs (created_at DESC, job_id DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_channel_created
    ON jobs (channel_id, created_at DESC, job_id DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created
    ON jobs (status, created_at DESC, job_id DESC);
"""

_LOCKS_GUARD = threading.Lock()
_INDEXES: dict[str, "StorageIndex"] = {}


def get_storage_index(db_path: str) -> "StorageIndex":
    """Return a process-wide ``StorageIndex`` for ``db_path`` (created once)."""
    key = os.path.normcase(os.path.abspath(db_path))
    with _LOCKS_GUARD:
        existing = _INDEXES.get(key)
        if existing is not None:
            return existing
        index = StorageIndex(db_path)
        _INDEXES[key] = index
        return index


def reset_storage_indexes() -> None:
    """Close and drop cached index handles (tests only)."""
    with _LOCKS_GUARD:
        for index in _INDEXES.values():
            index.close()
        _INDEXES.clear()


def workflows_index_path(*, execution_root: str | None = None, output_dir: str | None = None) -> str:
    """Resolve the SQLite path that covers executions, queue, and notifications."""
    if execution_root:
        # .../workflows/executions → .../workflows/index.db
        return os.path.join(os.path.dirname(os.path.abspath(execution_root)), "index.db")
    if output_dir:
        return os.path.join(os.path.abspath(output_dir), "workflows", "index.db")
    from config import WORKFLOWS_DIR
    return os.path.join(WORKFLOWS_DIR, "index.db")


def queue_index_path(*, queue_root: str | None = None) -> str:
    if queue_root:
        return os.path.join(os.path.dirname(os.path.abspath(queue_root)), "index.db")
    return workflows_index_path()


def jobs_index_path(jobs_dir: str) -> str:
    return os.path.join(os.path.abspath(jobs_dir), "index.db")


class StorageIndex:
    """Thin, thread-safe SQLite facade for listing indexes.

    Connections are short-lived (open → work → close) so Windows temp-dir
    cleanup in tests is not blocked by a held ``index.db`` handle. A process
    lock still serializes writers on the same path.
    """

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30,
            isolation_level=None,  # autocommit
        )
        conn.row_factory = sqlite3.Row
        # DELETE journal (not WAL): fewer sidecar files and no long-lived
        # shared-memory handles that pin the db open on Windows.
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.Error:
            pass
        conn.execute("PRAGMA synchronous=NORMAL")
        if not self._initialized:
            conn.executescript(_INIT_SQL)
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(_SCHEMA_VERSION),),
                )
            self._initialized = True
        return conn

    def close(self) -> None:
        """No persistent connection to close; retained for test reset hooks."""
        self._initialized = False

    def _run(self, fn):
        with self._lock:
            conn = self._connect()
            try:
                return fn(conn)
            finally:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    # ------------------------------------------------------------------
    # Executions
    # ------------------------------------------------------------------

    def upsert_execution(self, record: Mapping[str, Any]) -> None:
        execution_id = record.get("execution_id")
        workflow_id = record.get("workflow_id")
        if not execution_id or not workflow_id:
            return
        params = (
            execution_id,
            workflow_id,
            record.get("project_id"),
            record.get("run_mode"),
            record.get("status"),
            record.get("started_at"),
            record.get("finished_at"),
        )

        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO executions (
                    execution_id, workflow_id, project_id, run_mode,
                    status, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                    workflow_id = excluded.workflow_id,
                    project_id = excluded.project_id,
                    run_mode = excluded.run_mode,
                    status = excluded.status,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at
                """,
                params,
            )

        self._run(work)

    def delete_execution(self, execution_id: str) -> None:
        self._run(
            lambda conn: conn.execute(
                "DELETE FROM executions WHERE execution_id = ?",
                (execution_id,),
            )
        )

    def count_executions(self, workflow_id: str | None = None) -> int:
        def work(conn: sqlite3.Connection) -> int:
            if workflow_id is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM executions").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM executions WHERE workflow_id = ?",
                    (workflow_id,),
                ).fetchone()
            return int(row["n"] if row else 0)

        return self._run(work)

    def list_executions(
        self, workflow_id: str, *, limit: int = 100
    ) -> tuple[list[dict[str, Any]], int]:
        def work(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
            total_row = conn.execute(
                "SELECT COUNT(*) AS n FROM executions WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            total = int(total_row["n"] if total_row else 0)
            rows = conn.execute(
                """
                SELECT execution_id, workflow_id, project_id, run_mode,
                       status, started_at, finished_at
                FROM executions
                WHERE workflow_id = ?
                ORDER BY started_at DESC, execution_id DESC
                LIMIT ?
                """,
                (workflow_id, max(0, int(limit))),
            ).fetchall()
            items = [
                {
                    "execution_id": row["execution_id"],
                    "workflow_id": row["workflow_id"],
                    "project_id": row["project_id"],
                    "run_mode": row["run_mode"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                }
                for row in rows
            ]
            return items, total

        return self._run(work)

    def rebuild_executions(self, directory: str, *, load_record) -> int:
        """Scan ``directory`` and replace the executions table contents."""
        entries: list[tuple] = []
        if os.path.isdir(directory):
            for filename in os.listdir(directory):
                if not filename.endswith(".json") or filename.endswith(".json.bak"):
                    continue
                if ".workflow_snapshot." in filename:
                    continue
                execution_id = filename[:-5]
                try:
                    record = load_record(execution_id)
                except (OSError, ValueError, TypeError, KeyError):
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("execution_id") != execution_id:
                    continue
                workflow_id = record.get("workflow_id")
                if not workflow_id:
                    continue
                entries.append((
                    execution_id,
                    workflow_id,
                    record.get("project_id"),
                    record.get("run_mode"),
                    record.get("status"),
                    record.get("started_at"),
                    record.get("finished_at"),
                ))

        def work(conn: sqlite3.Connection) -> int:
            conn.execute("DELETE FROM executions")
            if entries:
                conn.executemany(
                    """
                    INSERT INTO executions (
                        execution_id, workflow_id, project_id, run_mode,
                        status, started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    entries,
                )
            return len(entries)

        return self._run(work)

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def upsert_queue(self, record: Mapping[str, Any]) -> None:
        execution_id = record.get("execution_id")
        workflow_id = record.get("workflow_id")
        if not execution_id or not workflow_id:
            return
        document = dict(record)
        params = (
            execution_id,
            workflow_id,
            record.get("project_id"),
            record.get("status"),
            record.get("source"),
            record.get("requested_run_mode"),
            record.get("requested_at"),
            record.get("started_at"),
            record.get("finished_at"),
            json.dumps(document, ensure_ascii=False),
        )

        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO queue (
                    execution_id, workflow_id, project_id, status, source,
                    requested_run_mode, requested_at, started_at, finished_at,
                    document_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                    workflow_id = excluded.workflow_id,
                    project_id = excluded.project_id,
                    status = excluded.status,
                    source = excluded.source,
                    requested_run_mode = excluded.requested_run_mode,
                    requested_at = excluded.requested_at,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    document_json = excluded.document_json
                """,
                params,
            )

        self._run(work)

    def delete_queue(self, execution_id: str) -> None:
        self._run(
            lambda conn: conn.execute(
                "DELETE FROM queue WHERE execution_id = ?", (execution_id,)
            )
        )

    def count_queue(self, workflow_id: str | None = None) -> int:
        def work(conn: sqlite3.Connection) -> int:
            if workflow_id is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM queue").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM queue WHERE workflow_id = ?",
                    (workflow_id,),
                ).fetchone()
            return int(row["n"] if row else 0)

        return self._run(work)

    def list_queue(
        self, workflow_id: str, *, limit: int = 100
    ) -> tuple[list[dict[str, Any]], int]:
        def work(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
            total_row = conn.execute(
                "SELECT COUNT(*) AS n FROM queue WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            total = int(total_row["n"] if total_row else 0)
            rows = conn.execute(
                """
                SELECT document_json
                FROM queue
                WHERE workflow_id = ?
                ORDER BY requested_at DESC, execution_id DESC
                LIMIT ?
                """,
                (workflow_id, max(0, int(limit))),
            ).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                try:
                    items.append(json.loads(row["document_json"]))
                except (TypeError, ValueError):
                    continue
            return items, total

        return self._run(work)

    def rebuild_queue(self, directory: str, *, load_record) -> int:
        entries: list[tuple] = []
        if os.path.isdir(directory):
            for filename in os.listdir(directory):
                if not filename.endswith(".json") or filename.endswith(".json.bak"):
                    continue
                execution_id = filename[:-5]
                try:
                    record = load_record(execution_id)
                except (OSError, ValueError, TypeError, KeyError):
                    continue
                if not isinstance(record, dict) or not record.get("workflow_id"):
                    continue
                entries.append((
                    record.get("execution_id") or execution_id,
                    record.get("workflow_id"),
                    record.get("project_id"),
                    record.get("status"),
                    record.get("source"),
                    record.get("requested_run_mode"),
                    record.get("requested_at"),
                    record.get("started_at"),
                    record.get("finished_at"),
                    json.dumps(record, ensure_ascii=False),
                ))

        def work(conn: sqlite3.Connection) -> int:
            conn.execute("DELETE FROM queue")
            if entries:
                conn.executemany(
                    """
                    INSERT INTO queue (
                        execution_id, workflow_id, project_id, status, source,
                        requested_run_mode, requested_at, started_at, finished_at,
                        document_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    entries,
                )
            return len(entries)

        return self._run(work)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def upsert_notification(self, record: Mapping[str, Any]) -> None:
        notification_id = record.get("notification_id")
        workflow_id = record.get("workflow_id")
        execution_id = record.get("execution_id")
        if not notification_id or not workflow_id or not execution_id:
            return
        params = (
            notification_id,
            execution_id,
            workflow_id,
            record.get("project_id"),
            record.get("outcome"),
            record.get("created_at"),
            1 if record.get("seen") else 0,
            json.dumps(dict(record), ensure_ascii=False),
        )

        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO notifications (
                    notification_id, execution_id, workflow_id, project_id,
                    outcome, created_at, seen, document_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(notification_id) DO UPDATE SET
                    execution_id = excluded.execution_id,
                    workflow_id = excluded.workflow_id,
                    project_id = excluded.project_id,
                    outcome = excluded.outcome,
                    created_at = excluded.created_at,
                    seen = excluded.seen,
                    document_json = excluded.document_json
                """,
                params,
            )

        self._run(work)

    def list_unseen_notifications(self, workflow_id: str) -> list[dict[str, Any]]:
        """Return every unseen notification document for a workflow (no limit)."""

        def work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = conn.execute(
                """
                SELECT document_json
                FROM notifications
                WHERE workflow_id = ? AND seen = 0
                ORDER BY created_at DESC, notification_id DESC
                """,
                (workflow_id,),
            ).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                try:
                    items.append(json.loads(row["document_json"]))
                except (TypeError, ValueError):
                    continue
            return items

        return self._run(work)

    def count_notifications(self, workflow_id: str | None = None) -> int:
        def work(conn: sqlite3.Connection) -> int:
            if workflow_id is None:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM notifications"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM notifications WHERE workflow_id = ?",
                    (workflow_id,),
                ).fetchone()
            return int(row["n"] if row else 0)

        return self._run(work)

    def list_notifications(
        self, workflow_id: str, *, limit: int = 100
    ) -> tuple[list[dict[str, Any]], int, int]:
        def work(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int, int]:
            total_row = conn.execute(
                "SELECT COUNT(*) AS n FROM notifications WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            total = int(total_row["n"] if total_row else 0)
            unseen_row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM notifications
                WHERE workflow_id = ? AND seen = 0
                """,
                (workflow_id,),
            ).fetchone()
            unseen = int(unseen_row["n"] if unseen_row else 0)
            rows = conn.execute(
                """
                SELECT document_json
                FROM notifications
                WHERE workflow_id = ?
                ORDER BY created_at DESC, notification_id DESC
                LIMIT ?
                """,
                (workflow_id, max(0, int(limit))),
            ).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                try:
                    items.append(json.loads(row["document_json"]))
                except (TypeError, ValueError):
                    continue
            return items, total, unseen

        return self._run(work)

    def rebuild_notifications(self, directory: str) -> int:
        entries: list[tuple] = []
        if os.path.isdir(directory):
            for filename in os.listdir(directory):
                if not filename.endswith(".json") or filename.endswith(".json.bak"):
                    continue
                try:
                    record = safe_json_read(os.path.join(directory, filename))
                except (OSError, ValueError, TypeError):
                    continue
                if not isinstance(record, dict):
                    continue
                notification_id = record.get("notification_id")
                workflow_id = record.get("workflow_id")
                execution_id = record.get("execution_id")
                if not notification_id or not workflow_id or not execution_id:
                    continue
                entries.append((
                    notification_id,
                    execution_id,
                    workflow_id,
                    record.get("project_id"),
                    record.get("outcome"),
                    record.get("created_at"),
                    1 if record.get("seen") else 0,
                    json.dumps(record, ensure_ascii=False),
                ))

        def work(conn: sqlite3.Connection) -> int:
            conn.execute("DELETE FROM notifications")
            if entries:
                conn.executemany(
                    """
                    INSERT INTO notifications (
                        notification_id, execution_id, workflow_id, project_id,
                        outcome, created_at, seen, document_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    entries,
                )
            return len(entries)

        return self._run(work)

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def upsert_job(self, record: Mapping[str, Any]) -> None:
        job_id = record.get("id") or record.get("job_id")
        channel_id = record.get("channel_id")
        if not job_id or not channel_id:
            return
        params = (
            job_id,
            channel_id,
            record.get("status"),
            record.get("created_at"),
            record.get("workflow_id"),
            record.get("execution_id"),
        )

        def work(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, channel_id, status, created_at, workflow_id, execution_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    status = excluded.status,
                    created_at = excluded.created_at,
                    workflow_id = excluded.workflow_id,
                    execution_id = excluded.execution_id
                """,
                params,
            )

        self._run(work)

    def delete_job(self, job_id: str) -> None:
        self._run(
            lambda conn: conn.execute(
                "DELETE FROM jobs WHERE job_id = ?", (job_id,)
            )
        )

    def count_jobs(self) -> int:
        def work(conn: sqlite3.Connection) -> int:
            row = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
            return int(row["n"] if row else 0)

        return self._run(work)

    def list_job_ids(
        self,
        *,
        channel_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[str]:
        clauses: list[str] = []
        params: list[Any] = []
        if channel_id is not None:
            clauses.append("channel_id = ?")
            params.append(channel_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(0, int(limit)))

        def work(conn: sqlite3.Connection) -> list[str]:
            rows = conn.execute(
                f"""
                SELECT job_id FROM jobs
                {where}
                ORDER BY created_at DESC, job_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [row["job_id"] for row in rows]

        return self._run(work)

    def rebuild_jobs(self, directory: str, *, load_summary) -> int:
        """``load_summary(job_id) -> mapping with id/channel_id/status/created_at``."""
        entries: list[tuple] = []
        if os.path.isdir(directory):
            for filename in os.listdir(directory):
                if not filename.endswith(".json") or filename.endswith(".json.bak"):
                    continue
                if filename == "index.db":
                    continue
                job_id = filename[:-5]
                try:
                    summary = load_summary(job_id)
                except (OSError, ValueError, TypeError, KeyError):
                    continue
                if not isinstance(summary, Mapping):
                    continue
                jid = summary.get("id") or job_id
                channel_id = summary.get("channel_id")
                if not channel_id:
                    continue
                entries.append((
                    jid,
                    channel_id,
                    summary.get("status"),
                    summary.get("created_at"),
                    summary.get("workflow_id"),
                    summary.get("execution_id"),
                ))

        def work(conn: sqlite3.Connection) -> int:
            conn.execute("DELETE FROM jobs")
            if entries:
                conn.executemany(
                    """
                    INSERT INTO jobs (
                        job_id, channel_id, status, created_at, workflow_id, execution_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    entries,
                )
            return len(entries)

        return self._run(work)


def count_json_documents(directory: str, *, id_prefix: str | None = None) -> int:
    """Count primary ``.json`` documents in a directory (excludes ``.bak`` / sidecars)."""
    if not os.path.isdir(directory):
        return 0
    total = 0
    for filename in os.listdir(directory):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        if ".workflow_snapshot." in filename:
            continue
        if id_prefix and not filename.startswith(id_prefix):
            continue
        total += 1
    return total
