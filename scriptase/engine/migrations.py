"""Sequential node-configuration migrations for persisted workflows."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from importlib import import_module
from typing import Callable

from scriptase.shared.io_utils import now_iso

from .registry import get_node_type


MIGRATION_TRAIL_KEY = "type_version_migrations"
MAX_MIGRATION_TRAIL = 100


class NodeMigrationError(ValueError):
    """An old node version cannot be upgraded safely."""


@dataclass(frozen=True)
class MigrationResult:
    document: dict
    trail: list[dict]
    read_only: bool
    warnings: list[dict]


def _migration_callable(value, *, type_key: str, from_version: int) -> Callable[[dict], dict]:
    if callable(value):
        return value
    if isinstance(value, str) and ":" in value:
        module_name, function_name = value.split(":", 1)
        candidate = getattr(import_module(module_name), function_name, None)
        if callable(candidate):
            return candidate
    raise NodeMigrationError(
        f"Invalid config migration for {type_key} version {from_version}"
    )


def migrate_workflow(document: dict) -> MigrationResult:
    """Return a migrated copy, without writing the source document.

    A migration declared under version ``N`` upgrades configuration from N to
    N+1. Every hop is required, deliberately preventing an old configuration
    from being interpreted using a schema it never passed through.
    """
    migrated = deepcopy(document)
    applied: list[dict] = []
    warnings: list[dict] = []
    read_only = False

    nodes = migrated.get("nodes")
    if not isinstance(nodes, list):
        return MigrationResult(migrated, applied, read_only, warnings)

    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        type_key = node.get("type")
        definition = get_node_type(type_key)
        stored_version = node.get("type_version")
        if definition is None or isinstance(stored_version, bool) or not isinstance(stored_version, int):
            continue
        current_version = definition["type_version"]
        if stored_version > current_version:
            read_only = True
            warnings.append({
                "code": "FUTURE_NODE_VERSION",
                "message": (
                    f"{node.get('name') or type_key} uses {type_key} version {stored_version}; "
                    f"this installation supports version {current_version}."
                ),
                "severity": "warning",
                "path": f"nodes[{index}].type_version",
            })
            continue

        migrations = definition.get("migrations", {})
        while stored_version < current_version:
            migration = migrations.get(stored_version, migrations.get(str(stored_version)))
            if migration is None:
                raise NodeMigrationError(
                    f"No config migration for {type_key} version {stored_version} to {stored_version + 1}"
                )
            configuration = node.get("configuration", {})
            if not isinstance(configuration, dict):
                raise NodeMigrationError(f"Cannot migrate non-object configuration for {type_key}")
            try:
                upgraded = _migration_callable(
                    migration, type_key=type_key, from_version=stored_version
                )(deepcopy(configuration))
            except NodeMigrationError:
                raise
            except Exception as exc:
                raise NodeMigrationError(
                    f"Config migration failed for {type_key} version {stored_version}: {exc}"
                ) from exc
            if not isinstance(upgraded, dict):
                raise NodeMigrationError(
                    f"Config migration for {type_key} version {stored_version} must return an object"
                )
            next_version = stored_version + 1
            node["configuration"] = upgraded
            node["type_version"] = next_version
            applied.append({
                "node_id": node.get("id"),
                "type": type_key,
                "from_version": stored_version,
                "to_version": next_version,
                "migrated_at": now_iso(),
            })
            stored_version = next_version

    if applied:
        extensions = migrated.setdefault("extensions", {})
        if not isinstance(extensions, dict):
            raise NodeMigrationError("Workflow extensions must be an object to record migrations")
        previous = extensions.get(MIGRATION_TRAIL_KEY, [])
        if not isinstance(previous, list):
            previous = []
        extensions[MIGRATION_TRAIL_KEY] = (deepcopy(previous) + applied)[-MAX_MIGRATION_TRAIL:]

    return MigrationResult(migrated, applied, read_only, warnings)
