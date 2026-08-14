"""Minimal open-issue bindings for scene re-segmentation (step 1.6).

Full ``ReviewIssue`` schema and store land at step 7.2. Until then, re-segmentation
still needs something durable to re-target or close when scene boundaries change
— otherwise the done-when for 1.6 cannot be proven.

This module stores a thin binding record (``iss_`` id, job, scene, status).
Step 7.2 migrates these fields into the full ReviewIssue document; the
re-target / close API stays the same.
"""

from __future__ import annotations

import os
import random
import re
import string
import threading
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import OUTPUT_DIR
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

ISSUE_ID_RE = re.compile(r"^iss_[A-Z0-9]{6}$")
ISSUE_SCHEMA_VERSION = 1

IssueStatus = Literal["open", "repairing", "resolved", "escalated", "accepted", "closed"]

OPEN_STATUSES: frozenset[str] = frozenset({"open", "repairing"})

# Default root: output/issue_bindings/ — rebindable for tests.
_DEFAULT_DIR = os.path.join(OUTPUT_DIR, "issue_bindings")
_issues_dir: str = _DEFAULT_DIR

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: Any) -> str | None:
    text = _strip_str(value)
    return text or None


class OpenIssueBinding(BaseModel):
    """Thin issue record used by re-segmentation until ReviewIssue lands."""

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: int = Field(default=ISSUE_SCHEMA_VERSION, ge=1)
    job_id: str = Field(min_length=1, max_length=120)
    scene_id: str | None = None
    status: IssueStatus = "open"
    reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not ISSUE_ID_RE.fullmatch(value):
            raise ValueError("id must match iss_[A-Z0-9]{6}")
        return value

    @field_validator("job_id", mode="before")
    @classmethod
    def _job_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("job_id is required")
        return text

    @field_validator("scene_id", mode="before")
    @classmethod
    def _scene_id(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: Any) -> str:
        text = _strip_str(value) or "open"
        allowed = ("open", "repairing", "resolved", "escalated", "accepted", "closed")
        if text not in allowed:
            raise ValueError(f"status must be one of: {', '.join(allowed)}")
        return text

    @field_validator("reason", "created_at", "updated_at", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return _strip_str(value)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def to_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class IssueBindingNotFound(FileNotFoundError):
    def __init__(self, issue_id: str):
        super().__init__(issue_id)
        self.issue_id = issue_id
        self.code = "ISSUE_NOT_FOUND"


def _path(issue_id: str) -> str:
    if not isinstance(issue_id, str) or not ISSUE_ID_RE.fullmatch(issue_id):
        raise ValueError("issue_id must match iss_[A-Z0-9]{6}")
    return safe_join(_issues_dir, f"{issue_id}.json")


def _generate_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "iss_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(_path(candidate)):
            return candidate
    raise RuntimeError("Could not allocate an issue id")


def _write(document: OpenIssueBinding) -> OpenIssueBinding:
    os.makedirs(_issues_dir, exist_ok=True)
    safe_json_write(_path(document.id), document.to_document(), indent=2)
    return document


def _load(issue_id: str) -> OpenIssueBinding:
    try:
        raw = safe_json_read(_path(issue_id))
    except FileNotFoundError as exc:
        raise IssueBindingNotFound(issue_id) from exc
    return OpenIssueBinding.model_validate(raw)


def create_open_issue(
    *,
    job_id: str,
    scene_id: str | None = None,
    reason: str = "",
    status: IssueStatus = "open",
) -> OpenIssueBinding:
    """Create a durable open-issue binding for tests and re-segmentation."""
    timestamp = now_iso()
    with _GLOBAL_LOCK:
        document = OpenIssueBinding(
            id=_generate_id(),
            schema_version=ISSUE_SCHEMA_VERSION,
            job_id=job_id.strip(),
            scene_id=scene_id,
            status=status,
            reason=reason or "",
            created_at=timestamp,
            updated_at=timestamp,
        )
        return _write(document)


def get_issue(issue_id: str) -> OpenIssueBinding:
    return _load(issue_id)


def list_issues(
    *,
    job_id: str | None = None,
    scene_id: str | None = None,
    open_only: bool = False,
    limit: int = 500,
) -> list[OpenIssueBinding]:
    os.makedirs(_issues_dir, exist_ok=True)
    items: list[OpenIssueBinding] = []
    for filename in os.listdir(_issues_dir):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        issue_id = filename[:-5]
        if not ISSUE_ID_RE.fullmatch(issue_id):
            continue
        try:
            item = _load(issue_id)
        except (IssueBindingNotFound, ValueError, OSError):
            continue
        if job_id is not None and item.job_id != job_id:
            continue
        if scene_id is not None and item.scene_id != scene_id:
            continue
        if open_only and not item.is_open:
            continue
        items.append(item)
    items.sort(key=lambda item: (item.created_at or "", item.id), reverse=True)
    return items[:limit]


def retarget_issues(job_id: str, from_scene_id: str, to_scene_id: str) -> list[OpenIssueBinding]:
    """Point open issues from a superseded scene at its successor."""
    updated: list[OpenIssueBinding] = []
    for issue in list_issues(job_id=job_id, scene_id=from_scene_id, open_only=True):
        lock = _thread_lock(issue.id)
        with lock:
            current = _load(issue.id)
            if not current.is_open or current.scene_id != from_scene_id:
                continue
            document = current.model_copy(
                update={
                    "scene_id": to_scene_id,
                    "updated_at": now_iso(),
                    "reason": (
                        f"{current.reason}; retargeted {from_scene_id}→{to_scene_id}"
                        if current.reason
                        else f"retargeted {from_scene_id}→{to_scene_id}"
                    ),
                }
            )
            updated.append(_write(document))
    return updated


def close_issues_for_scene(
    job_id: str,
    scene_id: str,
    *,
    reason: str = "scene_invalidated",
) -> list[OpenIssueBinding]:
    """Close open issues bound to a scene that no longer has a successor."""
    updated: list[OpenIssueBinding] = []
    for issue in list_issues(job_id=job_id, scene_id=scene_id, open_only=True):
        lock = _thread_lock(issue.id)
        with lock:
            current = _load(issue.id)
            if not current.is_open or current.scene_id != scene_id:
                continue
            document = current.model_copy(
                update={
                    "status": "closed",
                    "scene_id": None,
                    "updated_at": now_iso(),
                    "reason": (
                        f"{current.reason}; {reason}" if current.reason else reason
                    ),
                }
            )
            updated.append(_write(document))
    return updated


def assert_no_open_issue_on_dead_scenes(
    job_id: str,
    active_scene_ids: list[str] | set[str],
) -> None:
    """Raise if any open issue still names a scene outside the active set."""
    active = set(active_scene_ids)
    offenders: list[str] = []
    for issue in list_issues(job_id=job_id, open_only=True):
        if issue.scene_id is None:
            continue
        if issue.scene_id not in active:
            offenders.append(f"{issue.id}:{issue.scene_id}")
    if offenders:
        raise RuntimeError(
            "open issues bound to scenes that no longer resolve: "
            + ", ".join(offenders)
        )


__all__ = [
    "ISSUE_ID_RE",
    "ISSUE_SCHEMA_VERSION",
    "OPEN_STATUSES",
    "IssueBindingNotFound",
    "IssueStatus",
    "OpenIssueBinding",
    "assert_no_open_issue_on_dead_scenes",
    "close_issues_for_scene",
    "create_open_issue",
    "get_issue",
    "list_issues",
    "retarget_issues",
]
