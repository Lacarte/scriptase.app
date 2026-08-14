"""ReviewIssue store — durable structured review findings (step 7.2 / §15.4).

Persistence layout: ``output/issues/{iss_id}.json`` via ``safe_json_write`` /
``safe_json_read``. Soft-delete is not required yet; re-segmentation closes or
re-targets open issues in place.

Free-form text is rejected at the schema boundary. Callers that receive a
review provider payload must pass it through
:func:`scriptase.review.models.assert_structured_review_result` (or
:func:`create_from_review_result`) before anything is persisted.

The re-target / close API used by step 1.6 re-segmentation is preserved here
so open-issue bindings and full ReviewIssue documents share one store.
"""

from __future__ import annotations

import os
import random
import string
import threading
from typing import Any, Iterable, Mapping, Sequence

from pydantic import ValidationError

from config import ISSUES_DIR, OUTPUT_DIR
from scriptase.review.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.review.models import (
    ISSUE_ID_RE,
    ISSUE_SCHEMA_VERSION,
    OPEN_STATUSES,
    TERMINAL_ISSUE_STATUSES,
    IssueStatus,
    ReviewIssue,
    ReviewIssueDraft,
    assert_structured_review_result,
    parse_draft,
    parse_issue,
    technical_to_draft,
    validation_problems,
)
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join


class IssueNotFound(FileNotFoundError):
    """Raised when an issue id does not resolve on disk."""

    def __init__(self, issue_id: str):
        super().__init__(issue_id)
        self.issue_id = issue_id
        self.code = "ISSUE_NOT_FOUND"


# Backward-compatible alias used by step 1.6 call sites.
IssueBindingNotFound = IssueNotFound


class IssueValidationError(ValueError):
    """Schema validation failed; ``problems`` carries structured details."""

    def __init__(self, problems: list[dict[str, Any]], *, code: str = "ISSUE_INVALID"):
        super().__init__("ReviewIssue document failed schema validation")
        self.problems = problems
        self.code = code


# Module-level root so tests can rebind without patching config.
# Prefer ISSUES_DIR; fall back to the step-1.6 issue_bindings path when the
# config constant is missing (defensive for partially-reloaded envs).
_DEFAULT_DIR = ISSUES_DIR if ISSUES_DIR else os.path.join(OUTPUT_DIR, "issues")
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


def _validate_document(data: dict[str, Any]) -> ReviewIssue:
    try:
        return parse_issue(data)
    except ValidationError as exc:
        raise IssueValidationError(validation_problems(exc)) from exc


def _validate_draft(data: dict[str, Any]) -> ReviewIssueDraft:
    try:
        return parse_draft(data)
    except ValidationError as exc:
        raise IssueValidationError(validation_problems(exc)) from exc


def _write(document: ReviewIssue) -> ReviewIssue:
    os.makedirs(_issues_dir, exist_ok=True)
    safe_json_write(_path(document.id), document.to_document(), indent=2)
    return document


def _load_raw(issue_id: str) -> dict[str, Any]:
    try:
        return safe_json_read(_path(issue_id))
    except FileNotFoundError as exc:
        raise IssueNotFound(issue_id) from exc


def _load(issue_id: str) -> ReviewIssue:
    raw = _load_raw(issue_id)
    migrated, changed = apply_migrations(raw)
    document = _validate_document(migrated)
    if changed:
        _write(document)
    return document


def create_review_issue(
    draft: dict[str, Any] | ReviewIssueDraft | None = None,
    **fields: Any,
) -> ReviewIssue:
    """Persist a structured ReviewIssue.

    Accepts either a draft mapping / ``ReviewIssueDraft``, or keyword fields
    matching the draft schema. Free-text-only payloads fail schema validation.
    """
    if draft is None:
        payload = dict(fields)
    elif isinstance(draft, ReviewIssueDraft):
        payload = draft.model_dump(mode="json")
        payload.update(fields)
    elif isinstance(draft, Mapping):
        payload = dict(draft)
        payload.update(fields)
    else:
        raise TypeError("draft must be a mapping or ReviewIssueDraft")

    parsed = _validate_draft(payload)
    timestamp = now_iso()
    status = parsed.status
    resolved_at = timestamp if status in TERMINAL_ISSUE_STATUSES else None

    with _GLOBAL_LOCK:
        document = ReviewIssue(
            id=_generate_id(),
            schema_version=ISSUE_SCHEMA_VERSION,
            job_id=parsed.job_id,
            scene_id=parsed.scene_id,
            target_node_id=parsed.target_node_id,
            target_artifact_id=parsed.target_artifact_id,
            issue_type=parsed.issue_type,
            severity=parsed.severity,
            confidence=parsed.confidence,
            reason=parsed.reason,
            suggested_action=parsed.suggested_action,
            repair_instruction=parsed.repair_instruction,
            attempt_count=parsed.attempt_count,
            status=status,
            check_id=parsed.check_id,
            observed=dict(parsed.observed),
            expected=dict(parsed.expected),
            created_at=timestamp,
            resolved_at=resolved_at,
        )
        return _write(document)


def create_open_issue(
    *,
    job_id: str,
    scene_id: str | None = None,
    reason: str = "",
    status: IssueStatus = "open",
    target_node_id: str | None = None,
    target_artifact_id: str | None = None,
    issue_type: str = "technical_defect",
    severity: str = "medium",
    confidence: float = 1.0,
    suggested_action: str = "regenerate",
    repair_instruction: str = "",
    check_id: str | None = None,
    observed: Mapping[str, Any] | None = None,
    expected: Mapping[str, Any] | None = None,
) -> ReviewIssue:
    """Create a durable issue; keeps the step-1.6 call signature.

    Thin bindings are expanded to full ReviewIssue documents with structured
    defaults so re-segmentation tests and production cleanup share one schema.
    """
    text_reason = (reason or "").strip() or "Open review issue."
    return create_review_issue(
        {
            "job_id": job_id,
            "scene_id": scene_id,
            "target_node_id": target_node_id,
            "target_artifact_id": target_artifact_id,
            "issue_type": issue_type,
            "severity": severity,
            "confidence": confidence,
            "reason": text_reason,
            "suggested_action": suggested_action,
            "repair_instruction": repair_instruction,
            "status": status,
            "check_id": check_id,
            "observed": dict(observed or {"source": "open_issue"}),
            "expected": dict(expected or {}),
            "attempt_count": 0,
        }
    )


def create_from_technical(
    job_id: str,
    technical_issues: Sequence[Any],
) -> list[ReviewIssue]:
    """Persist step-7.1 technical findings as ReviewIssue documents."""
    created: list[ReviewIssue] = []
    for item in technical_issues:
        draft = technical_to_draft(item, job_id=job_id)
        created.append(create_review_issue(draft))
    return created


def create_from_review_result(
    payload: Any,
    *,
    job_id: str | None = None,
) -> list[ReviewIssue]:
    """Validate a review result envelope and persist structured issues only.

    Free-form text is rejected before any write. When ``job_id`` is provided it
    fills drafts that omit the field (provider payloads often scope the job
    outside each issue).
    """
    # Inject job_id into bare issue dicts before schema validation so review
    # providers can omit it on each finding when the call is already job-scoped.
    prepared: Any = payload
    if job_id and isinstance(payload, Mapping):
        prepared = dict(payload)
        raw_issues = prepared.get("issues")
        if isinstance(raw_issues, list):
            filled = []
            for item in raw_issues:
                if isinstance(item, Mapping) and not item.get("job_id"):
                    filled.append({**dict(item), "job_id": job_id})
                else:
                    filled.append(item)
            prepared["issues"] = filled
    elif job_id and isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        filled_list = []
        for item in payload:
            if isinstance(item, Mapping) and not item.get("job_id"):
                filled_list.append({**dict(item), "job_id": job_id})
            else:
                filled_list.append(item)
        prepared = filled_list

    structured = assert_structured_review_result(prepared)
    created: list[ReviewIssue] = []
    for item in structured:
        if isinstance(item, ReviewIssue):
            data = item.to_document()
            if job_id and not data.get("job_id"):
                data["job_id"] = job_id
            try:
                existing = get_issue(item.id)
                created.append(existing)
                continue
            except IssueNotFound:
                document = _validate_document(data)
                created.append(_write(document))
                continue

        data = item.model_dump(mode="json")
        if job_id and not data.get("job_id"):
            data["job_id"] = job_id
        created.append(create_review_issue(data))
    return created


def get_issue(issue_id: str) -> ReviewIssue:
    return _load(issue_id)


def list_issues(
    *,
    job_id: str | None = None,
    scene_id: str | None = None,
    target_node_id: str | None = None,
    target_artifact_id: str | None = None,
    open_only: bool = False,
    status: str | None = None,
    limit: int = 500,
) -> list[ReviewIssue]:
    os.makedirs(_issues_dir, exist_ok=True)
    items: list[ReviewIssue] = []
    for filename in os.listdir(_issues_dir):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        issue_id = filename[:-5]
        if not ISSUE_ID_RE.fullmatch(issue_id):
            continue
        try:
            item = _load(issue_id)
        except (IssueNotFound, ValueError, OSError, IssueValidationError):
            continue
        if job_id is not None and item.job_id != job_id:
            continue
        if scene_id is not None and item.scene_id != scene_id:
            continue
        if target_node_id is not None and item.target_node_id != target_node_id:
            continue
        if target_artifact_id is not None and item.target_artifact_id != target_artifact_id:
            continue
        if open_only and not item.is_open:
            continue
        if status is not None and item.status != status:
            continue
        items.append(item)
    items.sort(key=lambda item: (item.created_at or "", item.id), reverse=True)
    return items[:limit]


def update_issue(
    issue_id: str,
    *,
    status: str | None = None,
    scene_id: str | None | object = ...,
    reason: str | None = None,
    repair_instruction: str | None = None,
    suggested_action: str | None = None,
    attempt_count: int | None = None,
    target_node_id: str | None | object = ...,
    target_artifact_id: str | None | object = ...,
) -> ReviewIssue:
    """Update mutable runtime fields on a ReviewIssue."""
    if not isinstance(issue_id, str) or not ISSUE_ID_RE.fullmatch(issue_id):
        raise ValueError("issue_id must match iss_[A-Z0-9]{6}")

    lock = _thread_lock(issue_id)
    with lock:
        current = _load(issue_id)
        payload = current.to_document()

        if status is not None:
            payload["status"] = status
            if status in TERMINAL_ISSUE_STATUSES and not payload.get("resolved_at"):
                payload["resolved_at"] = now_iso()
            if status in OPEN_STATUSES:
                payload["resolved_at"] = None

        if scene_id is not ...:
            payload["scene_id"] = scene_id
        if target_node_id is not ...:
            payload["target_node_id"] = target_node_id
        if target_artifact_id is not ...:
            payload["target_artifact_id"] = target_artifact_id
        if reason is not None:
            payload["reason"] = reason
        if repair_instruction is not None:
            payload["repair_instruction"] = repair_instruction
        if suggested_action is not None:
            payload["suggested_action"] = suggested_action
        if attempt_count is not None:
            payload["attempt_count"] = attempt_count

        document = _validate_document(payload)
        return _write(document)


def retarget_issues(
    job_id: str,
    from_scene_id: str,
    to_scene_id: str,
) -> list[ReviewIssue]:
    """Point open issues from a superseded scene at its successor."""
    updated: list[ReviewIssue] = []
    for issue in list_issues(job_id=job_id, scene_id=from_scene_id, open_only=True):
        lock = _thread_lock(issue.id)
        with lock:
            current = _load(issue.id)
            if not current.is_open or current.scene_id != from_scene_id:
                continue
            note = f"retargeted {from_scene_id}→{to_scene_id}"
            new_reason = (
                f"{current.reason}; {note}" if current.reason else note
            )
            document = current.model_copy(
                update={
                    "scene_id": to_scene_id,
                    "reason": new_reason[:500],
                }
            )
            updated.append(_write(document))
    return updated


def close_issues_for_scene(
    job_id: str,
    scene_id: str,
    *,
    reason: str = "scene_invalidated",
) -> list[ReviewIssue]:
    """Close open issues bound to a scene that no longer has a successor."""
    updated: list[ReviewIssue] = []
    timestamp = now_iso()
    for issue in list_issues(job_id=job_id, scene_id=scene_id, open_only=True):
        lock = _thread_lock(issue.id)
        with lock:
            current = _load(issue.id)
            if not current.is_open or current.scene_id != scene_id:
                continue
            new_reason = (
                f"{current.reason}; {reason}" if current.reason else reason
            )
            document = current.model_copy(
                update={
                    "status": "closed",
                    "scene_id": None,
                    "reason": new_reason[:500],
                    "resolved_at": timestamp,
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


def issues_for_nodes(
    job_id: str,
    node_ids: Iterable[str],
    *,
    open_only: bool = False,
) -> list[str]:
    """Return issue ids whose ``target_node_id`` is in ``node_ids``."""
    wanted = {str(nid).strip() for nid in node_ids if str(nid).strip()}
    if not wanted:
        return []
    ids: list[str] = []
    for issue in list_issues(job_id=job_id, open_only=open_only):
        if issue.target_node_id and issue.target_node_id in wanted:
            ids.append(issue.id)
    return ids


__all__ = [
    "ISSUE_ID_RE",
    "ISSUE_SCHEMA_VERSION",
    "OPEN_STATUSES",
    "SCHEMA_VERSION",
    "IssueBindingNotFound",
    "IssueNotFound",
    "IssueValidationError",
    "ReviewIssue",
    "assert_no_open_issue_on_dead_scenes",
    "close_issues_for_scene",
    "create_from_review_result",
    "create_from_technical",
    "create_open_issue",
    "create_review_issue",
    "get_issue",
    "issues_for_nodes",
    "list_issues",
    "retarget_issues",
    "update_issue",
]
