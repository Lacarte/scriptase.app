"""Forward-only schema migrations for Artifact index documents.

Mirrors ``scriptase.channels.migrations``: ``MIGRATIONS`` maps a **target**
schema version to the function that upgrades data from the previous version to
it. ``apply_migrations`` runs every registered target greater than the stored
version, in ascending order, and stamps ``schema_version`` after each step.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from scriptase.artifacts.models import ARTIFACT_SCHEMA_VERSION

# Freshly written Artifact documents carry this schema_version.
SCHEMA_VERSION = ARTIFACT_SCHEMA_VERSION

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _register(version: int):
    """Register the function that upgrades a document *to* ``version``."""

    def decorator(func: Callable[[dict[str, Any]], dict[str, Any]]):
        MIGRATIONS[version] = func
        return func

    return decorator


# Schema v1 documents predate the generation snapshot (step 4.3). Hop to v2
# adds generation=null so side-by-side comparison has a stable field without
# inventing provider/seed/prompt data for older records.


@_register(2)
def _to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Add optional generation snapshot; leave null when unknown."""
    if "generation" not in data:
        data["generation"] = None
    return data


def apply_migrations(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Upgrade ``data`` to ``SCHEMA_VERSION``.

    Returns ``(migrated_data, changed)``. ``changed`` is ``True`` only when a
    migration ran, so an already-current document is not rewritten.

    Missing or non-integer ``schema_version`` is treated as 0 so a pre-stamp
    document still walks every registered hop.
    """
    if not isinstance(data, dict):
        raise TypeError("artifact document must be an object")

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
