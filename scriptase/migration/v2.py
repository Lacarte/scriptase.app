"""V2 import mapping and orchestration (step 10.1 / contracts §14).

This is the **single documented migration module** for provider-domain renames
and settings-shape aliases. Runtime tables live next to their consumers
(``providers.domains.DOMAIN_ALIASES``, ``providers.compatibility`` selection
aliases, ``providers.settings_migrations``, ``engine.config_migrations``);
this module re-exports them, documents the full mapping, and is the only API
that rewrites a V2 installation's persisted documents into Scriptase form.

What is rewritten on import
---------------------------
| Source (V2) | Target (Scriptase) | Mechanism |
|---|---|---|
| Domain block keys ``scene_blueprint`` / ``storyboard`` / ``animator`` | ``scene_director`` / ``image`` / ``video`` | settings migration v5 |
| ``selected_provider`` + ``per_provider`` | ``selected_instance_id`` + ``instances`` | settings migration v6 |
| Plaintext secrets under known keys | ``{"$secret": "<ref>"}`` | settings migration v7 |
| Selection wire aliases (``webhook``, ``grok``, ``kie-ai``, …) | canonical provider ids | ``normalize_selection_alias`` |
| Node config v1 ``engine`` / ``provider`` | ``provider_id`` (+ ``provider_options``) | ``type_version`` hops M1–M3 |
| Niche presets | starter Channels | step 1.3 (already seeded) |

What is **not** rewritten
-------------------------
- On-disk module directory names (``output/tts/``, ``output/animator/``,
  ``output/storyboard/``, …) — layout stays V2-compatible.
- Node type keys, port ids, and port types (graph contract).
- Provider package ids that were already canonical.

Security
--------
Imported settings run through the same secret extraction as a normal load.
Workflows and project zips are redacted at their persistence boundaries.
Never trust a browser-supplied absolute filesystem path for the source tree;
the API only accepts managed uploads or an explicit local path on loopback.
"""

from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Mapping

from loguru import logger

from scriptase.engine.migrations import MigrationResult, NodeMigrationError, migrate_workflow
from scriptase.engine.persistence import (
    WorkflowConflict,
    WorkflowValidationError,
    import_workflow as persist_import_workflow,
)
from scriptase.engine.redaction import redact
from scriptase.engine.validation import validate_workflow, validation_errors
from scriptase.modules.compose.project_zip_service import (
    ProjectZipError,
    ProjectZipImport,
    export_project_zip,
    import_project_zip,
)
from scriptase.providers.compatibility import (
    DOMAIN_SELECTION_ALIASES,
    LEGACY_SELECTION_ALIASES,
    normalize_selection_alias,
)
from scriptase.providers.domains import (
    DOMAIN_ALIASES as DOMAIN_ALIASES,
    DOMAINS,
    canonical_domain,
)
from scriptase.providers.settings_migrations import SETTINGS_VERSION, apply_migrations
from scriptase.shared.io_utils import safe_json_read, safe_json_write

# ---------------------------------------------------------------------------
# Documented mapping tables (the single place V2 import callers should read)
# ---------------------------------------------------------------------------

# DOMAIN_ALIASES re-exported from providers.domains (runtime table). Settings
# migration v5 rewrites persisted blocks to the canonical keys.

# Settings-shape field renames (pre-3.1 → post-3.1). Applied by migration v6.
SETTINGS_SHAPE: dict[str, str] = {
    "selected_provider": "selected_instance_id",
    "per_provider": "instances",
}

# Selection wire aliases (retired app-config / v1 node config spellings).
# Domain-aware table is authoritative; the flat map is the no-domain fallback.
SELECTION_ALIASES: dict[str, dict[str, str]] = {
    domain: dict(table) for domain, table in DOMAIN_SELECTION_ALIASES.items()
}
SELECTION_ALIASES_FLAT: dict[str, str] = dict(LEGACY_SELECTION_ALIASES)

# V2-compatible managed output directories. Import copies under these names;
# packages may rename, directory names do not.
OUTPUT_LAYOUT_DIRS: tuple[str, ...] = (
    "projects",
    "scenes",
    "animator",
    "storyboard",
    "tts",
    "alignments",
    "segmenters",
    "captions",
    "exports",
    "stories",
    "musics",
    "thumbnails",
    "branding",
    "workflows",
)

# Per-project trees keyed by project_id (plus optional source_folder for audio).
_PROJECT_SCOPED_DIRS: tuple[str, ...] = (
    "projects",
    "scenes",
    "animator",
    "storyboard",
    "segmenters",
    "captions",
    "exports",
    "stories",
    "thumbnails",
)
_SOURCE_SCOPED_DIRS: tuple[str, ...] = ("alignments", "tts")


class V2ImportError(ValueError):
    """Stable, presentation-safe V2 import error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class V2ImportReport:
    """Summary of a V2 root / bundle import."""

    settings_version: int | None = None
    settings_changed: bool = False
    workflows: list[str] = field(default_factory=list)
    workflow_migrations: list[dict[str, Any]] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    project_files: int = 0
    channels_seeded: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "settings_version": self.settings_version,
            "settings_changed": self.settings_changed,
            "workflows": list(self.workflows),
            "workflow_migrations": list(self.workflow_migrations),
            "projects": list(self.projects),
            "project_files": self.project_files,
            "channels_seeded": self.channels_seeded,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Pure migrations (rewrite documents; do not touch disk unless asked)
# ---------------------------------------------------------------------------


def migrate_settings_document(
    data: Mapping[str, Any] | dict,
    legacy_user: Mapping[str, Any] | None = None,
) -> tuple[dict, bool]:
    """Upgrade a V2 (or intermediate) settings document to current SETTINGS_VERSION.

    Applies domain renames, settings-shape aliases, selection canonicalisation,
    and secret extraction. Idempotent: an already-current document returns
    ``changed=False``.
    """
    if not isinstance(data, Mapping):
        raise V2ImportError("SETTINGS_INVALID", "Settings document must be an object")
    document = deepcopy(dict(data))
    migrated, changed = apply_migrations(document, dict(legacy_user or {}))
    # After rewrite every domain key must be canonical.
    domains = migrated.get("domains")
    if isinstance(domains, dict):
        for key in list(domains.keys()):
            if key in DOMAIN_ALIASES:
                raise V2ImportError(
                    "SETTINGS_MIGRATION_INCOMPLETE",
                    f"Domain block {key!r} was not rewritten to its canonical id",
                )
    return migrated, changed


def migrate_workflow_document(document: Mapping[str, Any] | dict) -> MigrationResult:
    """Apply hop-by-hop node ``type_version`` migrations (M1–M3 and successors).

    Does not write the source. Callers that persist the result must validate
    the migrated document first.
    """
    if not isinstance(document, Mapping):
        raise V2ImportError("WORKFLOW_INVALID", "Workflow document must be an object")
    try:
        return migrate_workflow(dict(document))
    except NodeMigrationError as exc:
        raise V2ImportError("NODE_MIGRATION_FAILED", str(exc)) from exc


def validate_migrated_workflow(document: Mapping[str, Any] | dict) -> list[dict]:
    """Return validation *errors* for a migrated workflow (empty = runnable shape)."""
    problems = validate_workflow(document, require_identity=True)
    return validation_errors(problems)


# ---------------------------------------------------------------------------
# Persist helpers
# ---------------------------------------------------------------------------


def import_settings(
    source: str | Path | Mapping[str, Any],
    *,
    dest_path: str | Path | None = None,
    legacy_user: Mapping[str, Any] | None = None,
    app_config_path: str | Path | None = None,
    write: bool = True,
) -> tuple[dict, bool]:
    """Import and rewrite a V2 settings.json into Scriptase form.

    When ``write`` is true (default) the migrated document is written to
    ``dest_path`` (or the app's settings path). Secrets are extracted by
    migration v7; the written document never retains plaintext credentials
    that the migration knows how to move.
    """
    if isinstance(source, (str, Path)):
        try:
            raw = safe_json_read(str(source))
        except FileNotFoundError as exc:
            raise V2ImportError("SETTINGS_NOT_FOUND", f"Settings file not found: {source}") from exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise V2ImportError("SETTINGS_INVALID", f"Settings file unreadable: {exc}") from exc
    else:
        raw = dict(source)

    if legacy_user is None and app_config_path is not None:
        legacy_user = _read_legacy_user(str(app_config_path))

    migrated, changed = migrate_settings_document(raw, legacy_user)

    if write:
        if dest_path is None:
            from scriptase.providers.settings_manager import SETTINGS_PATH, save_settings

            save_settings(migrated)
        else:
            path = Path(dest_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            safe_json_write(str(path), migrated, indent=2)

    return migrated, changed


def import_workflow(
    document: Mapping[str, Any] | dict,
    *,
    on_conflict: str = "new_id",
    require_complete: bool = False,
) -> tuple[dict, str | None, list[dict]]:
    """Migrate a V2 (or older) workflow, validate it, and persist.

    Returns ``(saved_document, original_id, migration_trail)``.
    """
    state = migrate_workflow_document(document)
    if state.read_only:
        raise V2ImportError(
            "UNSUPPORTED_NODE_VERSION",
            "Workflow uses a future node version this installation cannot import",
        )
    # Persist through the engine path so redaction + id allocation stay shared.
    # import_workflow (persistence) also migrates; the document is already
    # current so the second pass is a no-op.
    try:
        saved, original_id = persist_import_workflow(
            state.document, on_conflict=on_conflict
        )
    except WorkflowValidationError as exc:
        raise V2ImportError(
            "WORKFLOW_INVALID",
            "; ".join(
                f"{p.get('code')}: {p.get('message')}"
                for p in (exc.problems or [])
                if isinstance(p, dict)
            )
            or "Imported workflow failed validation",
        ) from exc
    except WorkflowConflict as exc:
        raise V2ImportError("WORKFLOW_CONFLICT", str(exc)) from exc
    except ValueError as exc:
        raise V2ImportError("WORKFLOW_INVALID", str(exc)) from exc

    # Optional completeness check for callers that will run immediately.
    if require_complete:
        errors = validation_errors(
            validate_workflow(saved, require_identity=True, require_complete=True)
        )
        if errors:
            raise V2ImportError(
                "WORKFLOW_INCOMPLETE",
                "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors),
            )

    return saved, original_id, state.trail


def import_project_tree(
    source_output_dir: str | Path,
    project_id: str,
    *,
    dest_output_dir: str | Path | None = None,
    on_conflict: str = "rename",
) -> dict[str, Any]:
    """Copy one V2 project and its media into a Scriptase output root.

    ``source_output_dir`` is a V2 (or Scriptase) ``output/`` directory.
    Layout is copied as-is — no path rewriting is required.
    """
    source_root = Path(source_output_dir)
    if not source_root.is_dir():
        raise V2ImportError("SOURCE_NOT_FOUND", f"Source output directory not found: {source_output_dir}")

    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))
    if not safe_id:
        raise V2ImportError("PROJECT_ID_INVALID", "project_id is invalid")

    dest_root = Path(dest_output_dir) if dest_output_dir is not None else Path(
        __import__("config").OUTPUT_DIR
    )

    # Resolve source_folder from scenes.json when present.
    source_folder = None
    scenes_path = source_root / "scenes" / safe_id / "scenes.json"
    if scenes_path.is_file():
        try:
            data = json.loads(scenes_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("source_folder"), str):
                source_folder = data["source_folder"]
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    dest_id = safe_id
    renamed_from = None
    if on_conflict == "rename":
        if _project_exists(dest_root, dest_id):
            suffix = 2
            while _project_exists(dest_root, f"{safe_id}-{suffix}"):
                suffix += 1
            renamed_from = dest_id
            dest_id = f"{safe_id}-{suffix}"
    elif on_conflict == "reject" and _project_exists(dest_root, dest_id):
        raise V2ImportError("PROJECT_EXISTS", f"Project {dest_id} already exists")

    files_copied = 0
    for dirname in _PROJECT_SCOPED_DIRS:
        src = source_root / dirname / safe_id
        if not src.exists():
            continue
        dst = dest_root / dirname / dest_id
        files_copied += _copy_tree(src, dst)

    if source_folder:
        for dirname in _SOURCE_SCOPED_DIRS:
            src = source_root / dirname / source_folder
            if not src.exists():
                continue
            dst = dest_root / dirname / source_folder
            files_copied += _copy_tree(src, dst)

    if files_copied == 0:
        raise V2ImportError(
            "PROJECT_NOT_FOUND",
            f"No project artifacts found for {safe_id} under {source_output_dir}",
        )

    # Rewrite project_id inside JSON manifests when renamed.
    if renamed_from:
        _rewrite_project_id(dest_root, dest_id, renamed_from)

    return {
        "project_id": dest_id,
        "renamed_from": renamed_from,
        "source_folder": source_folder or "",
        "files_copied": files_copied,
    }


def import_project_from_zip(
    source: BinaryIO | bytes,
    *,
    dest_output_dir: str | Path | None = None,
) -> ProjectZipImport:
    """Import a V2/Scriptase editor project ZIP (round-trip with export_project_zip)."""
    try:
        return import_project_zip(
            source,
            output_dir=str(dest_output_dir) if dest_output_dir is not None else None,
        )
    except ProjectZipError as exc:
        raise V2ImportError(exc.code, str(exc)) from exc


def export_project(
    project_id: str,
    *,
    output_dir: str | Path | None = None,
) -> bytes:
    """Re-export an imported project as a ZIP (no manual edits required)."""
    try:
        result = export_project_zip(
            project_id,
            output_dir=str(output_dir) if output_dir is not None else None,
        )
    except ProjectZipError as exc:
        raise V2ImportError(exc.code, str(exc)) from exc
    return result.data


def import_v2_root(
    v2_root: str | Path,
    *,
    dest_output_dir: str | Path | None = None,
    dest_settings_path: str | Path | None = None,
    import_settings_file: bool = True,
    import_workflows: bool = True,
    import_projects: bool = True,
    seed_channels: bool = True,
    project_ids: list[str] | None = None,
    on_workflow_conflict: str = "new_id",
) -> V2ImportReport:
    """Import a V2 installation root into Scriptase.

    Expected layout (paths relative to ``v2_root``)::

        settings/settings.json          # optional when import_settings_file=False
        app-config.json                 # optional legacy selection store
        output/projects|scenes|…        # V2-compatible media tree
        output/workflows/*.json         # saved workflows
        _data/niche_presets.json        # optional; Channels already seeded at 1.3

    Rewrites settings and workflows to current shapes; project media is copied
    without path changes.
    """
    root = Path(v2_root)
    if not root.is_dir():
        raise V2ImportError("SOURCE_NOT_FOUND", f"V2 root not found: {v2_root}")

    report = V2ImportReport()
    dest_output = Path(dest_output_dir) if dest_output_dir is not None else Path(
        __import__("config").OUTPUT_DIR
    )

    # ── settings ──────────────────────────────────────────────────────────
    if import_settings_file:
        settings_path = root / "settings" / "settings.json"
        if settings_path.is_file():
            app_config = root / "app-config.json"
            migrated, changed = import_settings(
                settings_path,
                dest_path=dest_settings_path,
                app_config_path=app_config if app_config.is_file() else None,
                write=True,
            )
            report.settings_version = int(migrated.get("version") or SETTINGS_VERSION)
            report.settings_changed = changed
        else:
            report.warnings.append("settings/settings.json not found; skipped")

    # ── workflows ─────────────────────────────────────────────────────────
    if import_workflows:
        wf_dir = root / "output" / "workflows"
        if wf_dir.is_dir():
            for path in sorted(wf_dir.glob("wf_*.json")):
                if path.name.endswith(".json.bak"):
                    continue
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    report.warnings.append(f"workflow {path.name}: unreadable ({exc})")
                    continue
                if not isinstance(raw, dict):
                    report.warnings.append(f"workflow {path.name}: not an object")
                    continue
                try:
                    # Persist into dest_output's workflows/ by temporarily
                    # pointing WORKFLOWS_DIR via monkeypatch-style override is
                    # awkward; write through the normal store when dest is the
                    # app default, otherwise write the migrated file ourselves.
                    if dest_output_dir is None:
                        saved, _original, trail = import_workflow(
                            raw, on_conflict=on_workflow_conflict
                        )
                        report.workflows.append(saved["workflow_id"])
                        report.workflow_migrations.extend(trail)
                    else:
                        state = migrate_workflow_document(raw)
                        if state.read_only:
                            report.warnings.append(
                                f"workflow {path.name}: future node version; skipped"
                            )
                            continue
                        document = redact(state.document)
                        errors = validation_errors(
                            validate_workflow(document, require_identity=True)
                        )
                        if errors:
                            report.warnings.append(
                                f"workflow {path.name}: validation failed after migration"
                            )
                            continue
                        dest_wf = dest_output / "workflows"
                        dest_wf.mkdir(parents=True, exist_ok=True)
                        wf_id = document.get("workflow_id")
                        if not isinstance(wf_id, str) or not wf_id.startswith("wf_"):
                            # Allocate a stable-looking id when missing.
                            import random
                            import string

                            alphabet = string.ascii_uppercase + string.digits
                            wf_id = "wf_" + "".join(
                                random.SystemRandom().choices(alphabet, k=6)
                            )
                            document["workflow_id"] = wf_id
                        target = dest_wf / f"{wf_id}.json"
                        if target.exists() and on_workflow_conflict == "new_id":
                            import random
                            import string

                            alphabet = string.ascii_uppercase + string.digits
                            for _ in range(50):
                                candidate = "wf_" + "".join(
                                    random.SystemRandom().choices(alphabet, k=6)
                                )
                                candidate_path = dest_wf / f"{candidate}.json"
                                if not candidate_path.exists():
                                    document["workflow_id"] = candidate
                                    target = candidate_path
                                    break
                        safe_json_write(str(target), document, indent=2)
                        report.workflows.append(document["workflow_id"])
                        report.workflow_migrations.extend(state.trail)
                except V2ImportError as exc:
                    report.warnings.append(f"workflow {path.name}: {exc}")
        else:
            report.warnings.append("output/workflows not found; skipped")

    # ── projects ──────────────────────────────────────────────────────────
    if import_projects:
        projects_dir = root / "output" / "projects"
        ids = project_ids
        if ids is None and projects_dir.is_dir():
            ids = sorted(
                entry.name
                for entry in projects_dir.iterdir()
                if entry.is_dir() and not entry.name.startswith(".")
            )
            # Also discover projects that only have scenes/ (no projects/ yet).
            scenes_dir = root / "output" / "scenes"
            if scenes_dir.is_dir():
                for entry in scenes_dir.iterdir():
                    if entry.is_dir() and entry.name not in ids:
                        ids.append(entry.name)
                ids = sorted(ids)

        for pid in ids or []:
            try:
                result = import_project_tree(
                    root / "output",
                    pid,
                    dest_output_dir=dest_output,
                    on_conflict="rename",
                )
                report.projects.append(result["project_id"])
                report.project_files += int(result.get("files_copied") or 0)
            except V2ImportError as exc:
                report.warnings.append(f"project {pid}: {exc}")

    # ── channels (niche presets) ──────────────────────────────────────────
    if seed_channels:
        try:
            from scriptase.channels.presets import seed_starter_channels

            seeded = seed_starter_channels()
            created = seeded.get("created") if isinstance(seeded, dict) else None
            if isinstance(created, list):
                report.channels_seeded = len(created)
            elif isinstance(created, int):
                report.channels_seeded = created
        except Exception as exc:
            report.warnings.append(f"channel seed: {exc}")

    logger.info(
        "V2 import complete: settings_v{} workflows={} projects={} warnings={}",
        report.settings_version,
        len(report.workflows),
        len(report.projects),
        len(report.warnings),
    )
    return report


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _read_legacy_user(app_config_path: str) -> dict:
    try:
        with open(app_config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    user = config.get("user") if isinstance(config, dict) else None
    return user if isinstance(user, dict) else {}


def _project_exists(output_root: Path, project_id: str) -> bool:
    return (output_root / "projects" / project_id).is_dir() or (
        output_root / "scenes" / project_id
    ).exists()


def _copy_tree(src: Path, dst: Path) -> int:
    count = 0
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 1
    if not src.is_dir():
        return 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_dir = dst if rel == "." else dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in files:
            if fname.endswith(".bak"):
                continue
            shutil.copy2(os.path.join(root, fname), target_dir / fname)
            count += 1
    return count


def _rewrite_project_id(output_root: Path, new_id: str, old_id: str) -> None:
    candidates = [
        output_root / "projects" / new_id / "initial.json",
        output_root / "projects" / new_id / "work@in@progress.json",
        output_root / "scenes" / new_id / "scenes.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("project_id") == old_id or data.get("project_id") is None:
            data["project_id"] = new_id
        if data.get("project_name") == old_id:
            data["project_name"] = new_id
        safe_json_write(str(path), data, indent=2)


def resolve_domain(domain_id: str) -> str:
    """Canonical domain id for a V2 or Scriptase spelling."""
    return canonical_domain(domain_id)


def resolve_selection(value: str, *, domain: str | None = None) -> str:
    """Canonical provider id for a retired selection / wire alias."""
    return normalize_selection_alias(value, domain=domain)


__all__ = [
    "DOMAIN_ALIASES",
    "OUTPUT_LAYOUT_DIRS",
    "SELECTION_ALIASES",
    "SELECTION_ALIASES_FLAT",
    "SETTINGS_SHAPE",
    "SETTINGS_VERSION",
    "V2ImportError",
    "V2ImportReport",
    "DOMAINS",
    "export_project",
    "import_project_from_zip",
    "import_project_tree",
    "import_settings",
    "import_v2_root",
    "import_workflow",
    "migrate_settings_document",
    "migrate_workflow_document",
    "resolve_domain",
    "resolve_selection",
    "validate_migrated_workflow",
]
