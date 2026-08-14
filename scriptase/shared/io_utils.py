"""Shared I/O utilities: JSON read/write, timestamps, thread-safe job stores."""

import json
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime

from loguru import logger


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Return current local time as ISO 8601 string with timezone."""
    return datetime.now().astimezone().isoformat()


# ---------------------------------------------------------------------------
# Thread-safe job store (replaces per-module _jobs dict + _jobs_lock pattern)
# ---------------------------------------------------------------------------

class JobStore:
    """A thread-safe dict wrapper for in-memory job tracking."""

    def __init__(self):
        self._jobs: dict = {}
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            return self._jobs.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._jobs[key] = value

    def pop(self, key, default=None):
        with self._lock:
            return self._jobs.pop(key, default)

    def values(self):
        with self._lock:
            return list(self._jobs.values())

    def items(self):
        with self._lock:
            return list(self._jobs.items())

    def __contains__(self, key):
        with self._lock:
            return key in self._jobs


_REPLACE_ATTEMPTS = 10
_REPLACE_DELAY = 0.02


def _replace_with_retry(tmp_path: str, path: str) -> None:
    """``os.replace``, retried past transient Windows sharing violations.

    ``os.replace`` needs delete access to the destination.  Windows refuses it
    with WinError 5/32 while *any* other handle is open on that file — a
    concurrent reader, an antivirus scanner, or the search indexer are all
    enough.  The condition clears within milliseconds, so a bounded retry turns
    a spurious failure back into the atomic write callers expect.  Elsewhere a
    ``PermissionError`` is a real permission problem, so it propagates at once.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            if os.name != "nt" or attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_DELAY * (attempt + 1))


def safe_json_write(
    path: str,
    data: dict,
    *,
    indent: int | None = None,
    ensure_ascii: bool = False,
    backup: bool = True,
) -> None:
    """Write JSON atomically: tmp file → flush/fsync → rename over target.

    On Windows ``os.rename`` fails if the target exists, so we fall back to
    ``shutil.move`` after removing the old file.  A ``.bak`` copy of the
    previous version is kept so ``safe_json_read`` can recover from
    corruption unless ``backup=False`` (used for high-frequency incremental
    execution envelope writes in step 10.2).

    Raises ``OSError`` on failure (caller should handle).
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    # 1. Write to a temp file in the SAME directory (same filesystem → rename is atomic on POSIX)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp", prefix=".save_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            os.fsync(f.fileno())

        # 2. Rotate current file → .bak (keep one backup)
        if backup and os.path.isfile(path):
            bak_path = path + ".bak"
            try:
                shutil.copy2(path, bak_path)
            except OSError:
                pass  # non-fatal — best-effort backup

        # 3. Atomic rename (POSIX) / replace (Windows)
        #    os.replace is atomic on both POSIX and modern Windows (NTFS).
        _replace_with_retry(tmp_path, path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def safe_json_read(path: str) -> dict:
    """Read JSON with automatic .bak fallback on corruption.

    Returns the parsed dict.  Raises ``FileNotFoundError`` if neither the
    main file nor the backup exist, or ``json.JSONDecodeError`` if both are
    corrupt.
    """
    # Try primary file
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Primary JSON corrupt ({}), trying .bak: {}", path, e)

    # Try backup
    bak_path = path + ".bak"
    if os.path.isfile(bak_path):
        try:
            with open(bak_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Restore backup → primary so next read is clean
            try:
                shutil.copy2(bak_path, path)
                logger.info("Restored {} from backup", path)
            except OSError:
                pass
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Backup also corrupt ({}): {}", bak_path, e)
            raise json.JSONDecodeError(
                f"Both primary and backup corrupt for {path}", "", 0
            ) from e

    # Neither exists
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No such file: {path}")

    # Primary exists but was corrupt and no backup
    raise json.JSONDecodeError(f"Corrupted JSON: {path}", "", 0)


def move_to_unique_path(src_path: str, dest_dir: str, dest_name: str | None = None) -> str:
    """Move a file or directory into ``dest_dir`` without clobbering an existing entry."""
    os.makedirs(dest_dir, exist_ok=True)
    target_name = dest_name or os.path.basename(src_path)
    candidate = os.path.join(dest_dir, target_name)
    if not os.path.exists(candidate):
        shutil.move(src_path, candidate)
        return candidate

    stem, suffix = os.path.splitext(target_name)
    counter = 2
    while True:
        candidate = os.path.join(dest_dir, f"{stem}-{counter}{suffix}")
        if not os.path.exists(candidate):
            shutil.move(src_path, candidate)
            return candidate
        counter += 1
