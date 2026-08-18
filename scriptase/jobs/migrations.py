"""Forward-only schema migrations for Job documents.

Mirrors ``scriptase.channels.migrations``: ``MIGRATIONS`` maps a **target**
schema version to the function that upgrades data from the previous version to
it. ``apply_migrations`` runs every registered target greater than the stored
version, in ascending order, and stamps ``schema_version`` after each step.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from scriptase.jobs.models import JOB_SCHEMA_VERSION

# Freshly written Job documents carry this schema_version.
SCHEMA_VERSION = JOB_SCHEMA_VERSION

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _register(version: int):
    """Register the function that upgrades a document *to* ``version``."""

    def decorator(func: Callable[[dict[str, Any]], dict[str, Any]]):
        MIGRATIONS[version] = func
        return func

    return decorator


# No historical hops yet: SCHEMA_VERSION is 1 and documents are born at v1.
# Future schema changes register here as @_register(2), @_register(3), …
# and land in the same step that changes the model (CLAUDE.md non-negotiable).


@_register(2)
def _add_narration_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Add nullable per-script processing overrides to legacy Jobs."""
    migrated = deepcopy(data)
    source = migrated.get("source")
    if not isinstance(source, dict):
        source = {}
        migrated["source"] = source
    source.setdefault("remove_silence", None)
    source.setdefault("speed", None)
    return migrated


@_register(3)
def _add_studio_script_reference(data: dict[str, Any]) -> dict[str, Any]:
    """Add the optional managed Script Studio provenance field."""
    migrated = deepcopy(data)
    source = migrated.get("source")
    if not isinstance(source, dict):
        source = {}
        migrated["source"] = source
    source.setdefault("script_id", None)
    return migrated


def apply_migrations(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Upgrade ``data`` to ``SCHEMA_VERSION``.

    Returns ``(migrated_data, changed)``. ``changed`` is ``True`` only when a
    migration ran, so an already-current document is not rewritten.

    Missing or non-integer ``schema_version`` is treated as 0 so a pre-stamp
    document still walks every registered hop.
    """
    if not isinstance(data, dict):
        raise TypeError("job document must be an object")

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
