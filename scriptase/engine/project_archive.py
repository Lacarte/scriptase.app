"""Portable, integrity-checked workflow project archives (step 9.4)."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import string
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, BinaryIO, Mapping

from scriptase.shared.io_utils import now_iso, safe_json_write

from .adapters.common import PROJECT_ID_RE
from .persistence import EXECUTION_ID_RE
from .redaction import redact
from .validation import WORKFLOW_ID_RE, validate_workflow, validation_errors


ARCHIVE_SCHEMA_VERSION = 1
MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProjectArchiveError(ValueError):
    """A stable, presentation-safe archive validation error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RestoreResult:
    workflow: dict[str, Any]
    project_id: str
    original_workflow_id: str
    original_project_id: str
    executions: list[str]
    files_restored: int


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_ids(workflow_id: str, project_id: str) -> None:
    if not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise ProjectArchiveError("ARCHIVE_ID_INVALID", "workflow_id must match wf_XXXXXX")
    if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
        raise ProjectArchiveError(
            "ARCHIVE_ID_INVALID", "project_id must match pp_XXXXXX or pm_XXXXXX"
        )


def _managed_ref(value: str, output_dir: str) -> str | None:
    raw = value.strip().replace("\\", "/")
    if raw.startswith("/output/"):
        raw = raw[8:]
    elif raw.startswith("output/"):
        raw = raw[7:]
    elif os.path.isabs(value):
        try:
            raw = os.path.relpath(os.path.abspath(value), os.path.abspath(output_dir)).replace("\\", "/")
        except ValueError:
            return None
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        return None
    target = os.path.abspath(os.path.join(output_dir, *path.parts))
    try:
        if os.path.commonpath([os.path.abspath(output_dir), target]) != os.path.abspath(output_dir):
            return None
    except ValueError:
        return None
    return path.as_posix()


def _artifact_refs(value: Any, output_dir: str, *, branding_strings: bool = False) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        explicit = value.get("artifact_refs")
        if isinstance(explicit, list):
            for item in explicit:
                if isinstance(item, str):
                    ref = _managed_ref(item, output_dir)
                    if ref:
                        refs.add(ref)
        for child in value.values():
            refs.update(_artifact_refs(child, output_dir, branding_strings=branding_strings))
    elif isinstance(value, list):
        for child in value:
            refs.update(_artifact_refs(child, output_dir, branding_strings=branding_strings))
    elif branding_strings and isinstance(value, str):
        ref = _managed_ref(value, output_dir)
        if ref and PurePosixPath(ref).parts[:1] == ("branding",):
            refs.add(ref)
    return refs


def _pinned_workflow_refs(workflow: Mapping[str, Any], output_dir: str) -> set[str]:
    """Collect direct managed paths held by pinned Result Viewer payloads."""
    refs: set[str] = set()
    for node in workflow.get("nodes", []):
        if not isinstance(node, Mapping) or node.get("type") != "stub.output":
            continue
        config = node.get("configuration")
        if not isinstance(config, Mapping) or config.get("pinned") is not True:
            continue
        pending = [config.get("payload")]
        while pending:
            value = pending.pop()
            if isinstance(value, Mapping):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                ref = _managed_ref(value, output_dir)
                if ref and os.path.isfile(os.path.join(output_dir, *PurePosixPath(ref).parts)):
                    refs.add(ref)
    return refs


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise ProjectArchiveError("NOT_FOUND", "Workflow not found") from exc
    except (OSError, ValueError, RecursionError) as exc:
        raise ProjectArchiveError("ARCHIVE_SOURCE_INVALID", "Stored project data is unreadable") from exc
    if not isinstance(value, dict):
        raise ProjectArchiveError("ARCHIVE_SOURCE_INVALID", "Stored project data must be an object")
    return value


def project_summaries(workflow_id: str, *, output_dir: str) -> list[dict[str, Any]]:
    _strict_ids(workflow_id, "pm_000000")
    root = os.path.join(output_dir, "workflows", "executions")
    projects: dict[str, dict[str, Any]] = {}
    if not os.path.isdir(root):
        return []
    for entry in os.scandir(root):
        if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json"):
            continue
        if ".workflow_snapshot." in entry.name:
            continue
        try:
            record = _read_json(entry.path)
        except ProjectArchiveError:
            continue
        project_id = record.get("project_id")
        if record.get("workflow_id") != workflow_id or not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
            continue
        item = projects.setdefault(project_id, {"project_id": project_id, "execution_count": 0, "last_run_at": None})
        item["execution_count"] += 1
        started = record.get("started_at")
        if isinstance(started, str) and (item["last_run_at"] is None or started > item["last_run_at"]):
            item["last_run_at"] = started
    return sorted(projects.values(), key=lambda item: (item["last_run_at"] or "", item["project_id"]), reverse=True)


def create_archive(workflow_id: str, project_id: str, destination: BinaryIO, *, output_dir: str) -> dict[str, Any]:
    """Write one project archive and return its manifest."""
    _strict_ids(workflow_id, project_id)
    workflow = _read_json(os.path.join(output_dir, "workflows", f"{workflow_id}.json"))
    execution_root = os.path.join(output_dir, "workflows", "executions")
    executions: list[tuple[str, dict[str, Any]]] = []
    if os.path.isdir(execution_root):
        for entry in os.scandir(execution_root):
            if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json"):
                continue
            # Step 10.2 snapshot sidecars are not execution records.
            if ".workflow_snapshot." in entry.name:
                continue
            try:
                record = _read_json(entry.path)
            except ProjectArchiveError:
                continue
            # Incremental envelopes may keep the snapshot external; merge so
            # archive members stay self-contained.
            if record.get("_snapshot_ref") or not isinstance(record.get("workflow_snapshot"), dict):
                try:
                    from .persistence import load_execution
                    record = load_execution(entry.name[:-5], root=execution_root)
                except (OSError, ValueError):
                    pass
            if record.get("workflow_id") == workflow_id and record.get("project_id") == project_id:
                executions.append((entry.name, record))
    if not executions:
        raise ProjectArchiveError("PROJECT_NOT_FOUND", "No executions found for this workflow project")
    executions.sort(key=lambda pair: pair[0])

    refs = _artifact_refs(workflow, output_dir, branding_strings=True)
    refs.update(_pinned_workflow_refs(workflow, output_dir))
    for _, record in executions:
        refs.update(_artifact_refs(record, output_dir, branding_strings=True))
        snapshot = record.get("workflow_snapshot")
        if isinstance(snapshot, Mapping):
            refs.update(_pinned_workflow_refs(snapshot, output_dir))

    # Defense in depth: re-redact at the archive boundary even though save paths
    # already scrub secrets. An archive is a portable egress surface (step 16.4).
    members: dict[str, bytes] = {"workflow.json": _json_bytes(redact(workflow))}
    for filename, record in executions:
        members[f"executions/{filename}"] = _json_bytes(redact(record))
    for ref in sorted(refs):
        source = os.path.join(output_dir, *PurePosixPath(ref).parts)
        if not os.path.isfile(source) or os.path.islink(source):
            raise ProjectArchiveError("ARCHIVE_ARTIFACT_MISSING", f"Referenced artifact is missing: {ref}")
        size = os.path.getsize(source)
        if size > MAX_MEMBER_BYTES:
            raise ProjectArchiveError("ARCHIVE_TOO_LARGE", f"Artifact exceeds the per-file limit: {ref}")
        with open(source, "rb") as handle:
            members[f"artifacts/{ref}"] = handle.read()

    inventory = [
        {"path": path, "size": len(data), "sha256": _digest(data)}
        for path, data in sorted(members.items())
    ]
    total = sum(item["size"] for item in inventory)
    if len(inventory) > MAX_ARCHIVE_FILES or total > MAX_ARCHIVE_BYTES:
        raise ProjectArchiveError("ARCHIVE_TOO_LARGE", "Project archive exceeds safety limits")
    manifest = {
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "created_at": now_iso(),
        "workflow_id": workflow_id,
        "project_id": project_id,
        "execution_count": len(executions),
        "artifact_count": len(refs),
        "files": inventory,
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        for path, data in sorted(members.items()):
            archive.writestr(path, data)
    return manifest


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _rewrite(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite(child, replacements) for key, child in value.items()}
    if isinstance(value, list):
        return [_rewrite(child, replacements) for child in value]
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
    return value


def _allocate_id(pattern, prefix: str, existing) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(500):
        candidate = prefix + "_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if pattern.fullmatch(candidate) and not existing(candidate):
            return candidate
    raise ProjectArchiveError("RESTORE_CONFLICT", f"Could not allocate a new {prefix} identifier")


def restore_archive(
    source: BinaryIO,
    *,
    output_dir: str,
    project_id_mode: str = "new",
    workflow_id_mode: str = "new",
) -> RestoreResult:
    """Validate an entire archive, then restore its files without overwrites."""
    if project_id_mode not in {"new", "original"} or workflow_id_mode not in {"new", "original"}:
        raise ProjectArchiveError("BAD_REQUEST", "ID modes must be 'new' or 'original'")
    try:
        archive = zipfile.ZipFile(source, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProjectArchiveError("ARCHIVE_INVALID", "File is not a valid project archive") from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or len(names) > MAX_ARCHIVE_FILES + 1:
            raise ProjectArchiveError("ARCHIVE_INVALID", "Archive has duplicate or too many members")
        total = 0
        for info in infos:
            if not _safe_member(info.filename) or info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ProjectArchiveError("ARCHIVE_INVALID", "Archive contains an unsafe member")
            if info.file_size > MAX_MEMBER_BYTES:
                raise ProjectArchiveError("ARCHIVE_TOO_LARGE", "An archive member exceeds the size limit")
            if info.file_size and info.compress_size == 0 or (info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
                raise ProjectArchiveError("ARCHIVE_INVALID", "Archive compression ratio is unsafe")
            total += info.file_size
        if total > MAX_ARCHIVE_BYTES or "manifest.json" not in names:
            raise ProjectArchiveError("ARCHIVE_TOO_LARGE", "Project archive exceeds safety limits")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise ProjectArchiveError("ARCHIVE_INVALID", "Archive manifest is invalid") from exc
        if not isinstance(manifest, dict) or manifest.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION:
            raise ProjectArchiveError("ARCHIVE_VERSION_UNSUPPORTED", "Unsupported project archive version")
        old_workflow = manifest.get("workflow_id")
        old_project = manifest.get("project_id")
        _strict_ids(old_workflow, old_project)
        inventory = manifest.get("files")
        if not isinstance(inventory, list) or not inventory:
            raise ProjectArchiveError("ARCHIVE_INVALID", "Archive inventory is missing")
        expected: dict[str, dict[str, Any]] = {}
        payloads: dict[str, bytes] = {}
        for item in inventory:
            if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
                raise ProjectArchiveError("ARCHIVE_INVALID", "Archive inventory entry is invalid")
            path, size, checksum = item.get("path"), item.get("size"), item.get("sha256")
            if not isinstance(path, str) or not _safe_member(path) or path in expected or not isinstance(size, int) or size < 0 or not isinstance(checksum, str) or not _SHA256_RE.fullmatch(checksum):
                raise ProjectArchiveError("ARCHIVE_INVALID", "Archive inventory entry is invalid")
            expected[path] = item
        if set(names) != {"manifest.json", *expected} or "workflow.json" not in expected:
            raise ProjectArchiveError("ARCHIVE_INVALID", "Archive contents do not match its inventory")
        for path, item in expected.items():
            data = archive.read(path)
            if len(data) != item["size"] or _digest(data) != item["sha256"]:
                raise ProjectArchiveError("ARCHIVE_CORRUPT", f"Archive checksum failed: {path}")
            payloads[path] = data

    workflows_root = os.path.join(output_dir, "workflows")
    executions_root = os.path.join(workflows_root, "executions")
    workflow_exists = lambda value: os.path.exists(os.path.join(workflows_root, f"{value}.json"))
    existing_parts = {part for path in _existing_relative_files(output_dir) for part in PurePosixPath(path).parts}
    project_exists = lambda value: value in existing_parts
    new_workflow = old_workflow if workflow_id_mode == "original" else _allocate_id(WORKFLOW_ID_RE, "wf", workflow_exists)
    prefix = old_project.split("_", 1)[0]
    new_project = old_project if project_id_mode == "original" else _allocate_id(PROJECT_ID_RE, prefix, project_exists)
    if workflow_exists(new_workflow):
        raise ProjectArchiveError("RESTORE_CONFLICT", f"Workflow already exists: {new_workflow}")
    if project_id_mode == "original" and project_exists(new_project):
        raise ProjectArchiveError("RESTORE_CONFLICT", f"Project already exists: {new_project}")

    replacements = {old_workflow: new_workflow, old_project: new_project}
    try:
        workflow = json.loads(payloads["workflow.json"])
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ProjectArchiveError("ARCHIVE_INVALID", "Archived workflow is invalid") from exc
    workflow = _rewrite(workflow, replacements)
    workflow["workflow_id"] = new_workflow
    workflow["updated_at"] = now_iso()
    problems = validation_errors(validate_workflow(workflow, require_identity=True))
    if problems:
        raise ProjectArchiveError("WORKFLOW_INVALID", "Archived workflow does not validate")

    execution_documents: list[tuple[str, dict[str, Any]]] = []
    execution_replacements: dict[str, str] = {}
    reserved_execution_ids: set[str] = set()
    for path, data in sorted(payloads.items()):
        if not path.startswith("executions/"):
            continue
        try:
            record = _rewrite(json.loads(data), replacements)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise ProjectArchiveError("ARCHIVE_INVALID", f"Invalid execution record: {path}") from exc
        old_execution = record.get("execution_id")
        if not isinstance(old_execution, str) or not EXECUTION_ID_RE.fullmatch(old_execution):
            raise ProjectArchiveError("ARCHIVE_INVALID", f"Invalid execution identity: {path}")
        target_execution = old_execution
        if os.path.exists(os.path.join(executions_root, f"{target_execution}.json")) or target_execution in reserved_execution_ids:
            target_execution = _allocate_id(
                EXECUTION_ID_RE,
                "ex",
                lambda value: value in reserved_execution_ids or os.path.exists(os.path.join(executions_root, f"{value}.json")),
            )
        reserved_execution_ids.add(target_execution)
        execution_replacements[old_execution] = target_execution
        record["execution_id"] = target_execution
        record["workflow_id"] = new_workflow
        record["project_id"] = new_project
        execution_documents.append((target_execution, record))
    workflow = _rewrite(workflow, execution_replacements)
    execution_documents = [(eid, _rewrite(record, execution_replacements)) for eid, record in execution_documents]

    staged = tempfile.mkdtemp(prefix="project-restore-", dir=output_dir)
    destinations: list[tuple[str, str]] = []
    try:
        for path, data in sorted(payloads.items()):
            if not path.startswith("artifacts/"):
                continue
            ref = path[len("artifacts/"):]
            rewritten_ref = _rewrite(ref, replacements)
            if not isinstance(rewritten_ref, str) or not _safe_member(rewritten_ref):
                raise ProjectArchiveError("ARCHIVE_INVALID", "Archive contains an unsafe artifact path")
            destination = os.path.join(output_dir, *PurePosixPath(rewritten_ref).parts)
            staged_file = os.path.join(staged, *PurePosixPath(rewritten_ref).parts)
            os.makedirs(os.path.dirname(staged_file), exist_ok=True)
            with open(staged_file, "wb") as handle:
                handle.write(data)
            if os.path.exists(destination):
                with open(destination, "rb") as handle:
                    if _digest(handle.read()) != _digest(data):
                        raise ProjectArchiveError("RESTORE_CONFLICT", f"Artifact already exists: {rewritten_ref}")
                continue
            destinations.append((staged_file, destination))
        for execution_id, record in execution_documents:
            staged_file = os.path.join(staged, "workflows", "executions", f"{execution_id}.json")
            safe_json_write(staged_file, record, indent=2)
            destinations.append((staged_file, os.path.join(executions_root, f"{execution_id}.json")))
        staged_workflow = os.path.join(staged, "workflows", f"{new_workflow}.json")
        safe_json_write(staged_workflow, workflow, indent=2)
        destinations.append((staged_workflow, os.path.join(workflows_root, f"{new_workflow}.json")))

        created: list[str] = []
        try:
            for staged_file, destination in destinations:
                if os.path.exists(destination):
                    raise ProjectArchiveError("RESTORE_CONFLICT", f"Restore target already exists: {os.path.relpath(destination, output_dir)}")
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                os.replace(staged_file, destination)
                created.append(destination)
        except Exception:
            for path in reversed(created):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            raise
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    return RestoreResult(workflow, new_project, old_workflow, old_project, [eid for eid, _ in execution_documents], len(destinations))


def _existing_relative_files(output_dir: str):
    if not os.path.isdir(output_dir):
        return []
    values = []
    for root, dirs, files in os.walk(output_dir, followlinks=False):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
        for name in files:
            values.append(os.path.relpath(os.path.join(root, name), output_dir).replace("\\", "/"))
    return values
