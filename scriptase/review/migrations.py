"""Forward-only schema migrations for ReviewIssue documents.

Mirrors ``scriptase.jobs.migrations``: ``MIGRATIONS`` maps a **target**
schema version to the function that upgrades data from the previous version to
it. ``apply_migrations`` runs every registered target greater than the stored
version, in ascending order, and stamps ``schema_version`` after each step.

Step 1.6 wrote thin open-issue bindings (schema v1). Step 7.2 expands them to
the full ReviewIssue document (schema v2).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from scriptase.review.models import ISSUE_SCHEMA_VERSION

# Freshly written ReviewIssue documents carry this schema_version.
SCHEMA_VERSION = ISSUE_SCHEMA_VERSION

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _register(version: int):
    """Register the function that upgrades a document *to* ``version``."""

    def decorator(func: Callable[[dict[str, Any]], dict[str, Any]]):
        MIGRATIONS[version] = func
        return func

    return decorator


def _strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


@_register(2)
def _to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Expand thin open-issue bindings into the full ReviewIssue shape.

    v1 fields: id, schema_version, job_id, scene_id, status, reason,
    created_at, updated_at.

    v2 adds: target_node_id, target_artifact_id, issue_type, severity,
    confidence, suggested_action, repair_instruction, attempt_count,
    check_id, observed, expected, resolved_at. Drops updated_at.
    """
    reason = _strip(data.get("reason")) or "Open issue binding (migrated)."
    status = _strip(data.get("status")) or "open"

    if "issue_type" not in data or not _strip(data.get("issue_type")):
        data["issue_type"] = "technical_defect"
    if "severity" not in data or not _strip(data.get("severity")):
        data["severity"] = "medium"
    if "confidence" not in data or data.get("confidence") is None:
        data["confidence"] = 1.0
    if "suggested_action" not in data or not _strip(data.get("suggested_action")):
        data["suggested_action"] = "regenerate"
    if "repair_instruction" not in data:
        data["repair_instruction"] = ""
    if "attempt_count" not in data or data.get("attempt_count") is None:
        data["attempt_count"] = 0
    if "target_node_id" not in data:
        data["target_node_id"] = None
    if "target_artifact_id" not in data:
        data["target_artifact_id"] = None
    if "check_id" not in data:
        data["check_id"] = None
    if "observed" not in data or not isinstance(data.get("observed"), dict):
        data["observed"] = {"migrated_from": "open_issue_binding_v1"}
    if "expected" not in data or not isinstance(data.get("expected"), dict):
        data["expected"] = {}
    if not _strip(data.get("reason")):
        data["reason"] = reason

    # Terminal statuses get resolved_at from updated_at when present.
    terminal = {"resolved", "escalated", "accepted", "closed"}
    if "resolved_at" not in data or data.get("resolved_at") in (None, ""):
        if status in terminal:
            data["resolved_at"] = _strip(data.get("updated_at")) or _strip(
                data.get("created_at")
            ) or None
        else:
            data["resolved_at"] = None

    # Drop the v1 bookkeeping field; contract uses created_at / resolved_at.
    data.pop("updated_at", None)

    return data


def apply_migrations(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Upgrade ``data`` to ``SCHEMA_VERSION``.

    Returns ``(migrated_data, changed)``. ``changed`` is ``True`` only when a
    migration ran, so an already-current document is not rewritten.

    Missing or non-integer ``schema_version`` is treated as 0 so a pre-stamp
    document still walks every registered hop.
    """
    if not isinstance(data, dict):
        raise TypeError("review issue document must be an object")

    current = data.get("schema_version")
    if not isinstance(current, int) or isinstance(current, bool):
        current = 0

    migrated = deepcopy(data)
    changed = False

    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        migrated = MIGRATIONS[version](migrated)
        migrated["schema_version"] = version
        changed = True
        current = version

    if migrated.get("schema_version") != SCHEMA_VERSION:
        if current < SCHEMA_VERSION and not MIGRATIONS:
            migrated["schema_version"] = SCHEMA_VERSION
            changed = True
        elif changed:
            migrated["schema_version"] = SCHEMA_VERSION

    return migrated, changed


__all__ = [
    "SCHEMA_VERSION",
    "MIGRATIONS",
    "apply_migrations",
]
