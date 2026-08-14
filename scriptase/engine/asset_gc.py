"""Conservative garbage collection for managed files under ``output/``.

The scanner is intentionally the only authority used by the CLI and HTTP API.
It never follows symlinks, never considers workflow control data or trash, and
revalidates every requested path immediately before deletion.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from config import OUTPUT_DIR


DEFAULT_PROTECTED_PATHS = ("workflows", "TRASH")


@dataclass(frozen=True)
class OrphanArtifact:
    path: str
    size: int
    modified_at: float


def _relative_ref(value: str, output_dir: str) -> str | None:
    """Normalize a managed reference without accepting path traversal."""
    raw = value.strip().replace("\\", "/")
    if raw.startswith("/output/"):
        raw = raw[len("/output/"):]
    elif raw.startswith("output/"):
        raw = raw[len("output/"):]
    elif os.path.isabs(value):
        try:
            raw = os.path.relpath(os.path.abspath(value), os.path.abspath(output_dir)).replace("\\", "/")
        except ValueError:
            return None
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        return None
    candidate = os.path.abspath(os.path.join(output_dir, *path.parts))
    try:
        if os.path.commonpath([os.path.abspath(output_dir), candidate]) != os.path.abspath(output_dir):
            return None
    except ValueError:
        return None
    return path.as_posix()


def _explicit_artifact_refs(value: Any, output_dir: str) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        candidates = value.get("artifact_refs")
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, str):
                    normalized = _relative_ref(candidate, output_dir)
                    if normalized:
                        refs.add(normalized)
        for child in value.values():
            refs.update(_explicit_artifact_refs(child, output_dir))
    elif isinstance(value, list):
        for child in value:
            refs.update(_explicit_artifact_refs(child, output_dir))
    return refs


def _pinned_payload_refs(value: Any, output_dir: str) -> set[str]:
    """Pinned payloads may contain either artifact_refs or direct managed URLs."""
    refs = _explicit_artifact_refs(value, output_dir)
    if isinstance(value, Mapping):
        for child in value.values():
            refs.update(_pinned_payload_refs(child, output_dir))
    elif isinstance(value, list):
        for child in value:
            refs.update(_pinned_payload_refs(child, output_dir))
    elif isinstance(value, str):
        normalized = _relative_ref(value, output_dir)
        if normalized and os.path.isfile(os.path.join(output_dir, *PurePosixPath(normalized).parts)):
            refs.add(normalized)
    return refs


def _json_documents(directory: str) -> Iterable[tuple[dict[str, Any], str]]:
    if not os.path.isdir(directory):
        return
    for entry in os.scandir(directory):
        if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".json"):
            continue
        # Step 10.2: workflow snapshot sidecars are merged via load_execution.
        if ".workflow_snapshot." in entry.name:
            continue
        try:
            with open(entry.path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            yield value, entry.name


def referenced_artifacts(*, output_dir: str = OUTPUT_DIR) -> set[str]:
    """Return roots held by execution records and pinned viewer payloads."""
    output_dir = os.path.abspath(output_dir)
    workflow_root = os.path.join(output_dir, "workflows")
    execution_root = os.path.join(workflow_root, "executions")
    documents: list[dict[str, Any]] = []
    for document, name in _json_documents(execution_root):
        # Incremental envelopes need the snapshot merged for pinned refs.
        if document.get("_snapshot_ref") or not isinstance(document.get("workflow_snapshot"), dict):
            if isinstance(document.get("execution_id"), str) or name.endswith(".json"):
                try:
                    from .persistence import load_execution
                    execution_id = document.get("execution_id") or name[:-5]
                    document = load_execution(execution_id, root=execution_root)
                except (OSError, ValueError, TypeError):
                    pass
        documents.append(document)
    for document, _name in _json_documents(workflow_root):
        documents.append(document)
    refs: set[str] = set()
    for document in documents:
        # Execution records are authoritative for every emitted artifact.
        if isinstance(document.get("execution_id"), str):
            refs.update(_explicit_artifact_refs(document, output_dir))
        snapshots = [document, document.get("workflow_snapshot")]
        for snapshot in snapshots:
            if not isinstance(snapshot, Mapping):
                continue
            for node in snapshot.get("nodes", []):
                if not isinstance(node, Mapping) or node.get("type") != "stub.output":
                    continue
                config = node.get("configuration")
                if isinstance(config, Mapping) and config.get("pinned") is True:
                    refs.update(_pinned_payload_refs(config.get("payload"), output_dir))
    return refs


def _protected(path: PurePosixPath, protected_paths: tuple[str, ...]) -> bool:
    for prefix in protected_paths:
        protected = PurePosixPath(prefix.replace("\\", "/").strip("/"))
        if protected.parts and path.parts[:len(protected.parts)] == protected.parts:
            return True
    return False


def scan_orphans(
    *, output_dir: str = OUTPUT_DIR, protected_paths: Iterable[str] = DEFAULT_PROTECTED_PATHS
) -> list[OrphanArtifact]:
    output_dir = os.path.abspath(output_dir)
    protected = tuple(protected_paths)
    referenced = referenced_artifacts(output_dir=output_dir)
    orphans: list[OrphanArtifact] = []
    if not os.path.isdir(output_dir):
        return orphans
    for root, dirs, files in os.walk(output_dir, topdown=True, followlinks=False):
        relative_root = os.path.relpath(root, output_dir)
        root_parts = () if relative_root == "." else PurePosixPath(relative_root.replace("\\", "/")).parts
        dirs[:] = [
            name for name in dirs
            if not os.path.islink(os.path.join(root, name))
            and not _protected(PurePosixPath(*root_parts, name), protected)
        ]
        for name in files:
            absolute = os.path.join(root, name)
            if os.path.islink(absolute):
                continue
            relative = PurePosixPath(*root_parts, name)
            ref = relative.as_posix()
            if _protected(relative, protected) or ref in referenced:
                continue
            try:
                stat = os.stat(absolute, follow_symlinks=False)
            except OSError:
                continue
            orphans.append(OrphanArtifact(ref, stat.st_size, stat.st_mtime))
    return sorted(orphans, key=lambda item: item.path)


def collect_orphans(
    *, output_dir: str = OUTPUT_DIR, paths: Iterable[str] | None = None,
    dry_run: bool = True, protected_paths: Iterable[str] = DEFAULT_PROTECTED_PATHS,
) -> dict[str, Any]:
    """Report or delete requested files that are still present in a fresh orphan scan."""
    scanned = scan_orphans(output_dir=output_dir, protected_paths=protected_paths)
    by_path = {item.path: item for item in scanned}
    requested = sorted(set(paths)) if paths is not None else sorted(by_path)
    invalid = [path for path in requested if not isinstance(path, str) or path not in by_path]
    if invalid:
        raise ValueError("Only paths from the current orphan scan may be collected")
    selected = [by_path[path] for path in requested]
    deleted: list[str] = []
    failures: list[dict[str, str]] = []
    if not dry_run:
        root = os.path.abspath(output_dir)
        for item in selected:
            absolute = os.path.abspath(os.path.join(root, *PurePosixPath(item.path).parts))
            try:
                if os.path.commonpath([root, absolute]) != root or os.path.islink(absolute):
                    raise OSError("unsafe artifact path")
                os.remove(absolute)
                deleted.append(item.path)
            except OSError as exc:
                failures.append({"path": item.path, "message": str(exc)})
    return {
        "dry_run": dry_run,
        "orphans": [asdict(item) for item in selected],
        "count": len(selected),
        "bytes": sum(item.size for item in selected),
        "deleted": deleted,
        "failures": failures,
        "protected_paths": list(protected_paths),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find and optionally delete orphaned output assets.")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="managed output directory")
    parser.add_argument("--delete", action="store_true", help="delete current orphans (default: dry run)")
    parser.add_argument("--json", action="store_true", help="print the machine-readable report")
    args = parser.parse_args(argv)
    report = collect_orphans(output_dir=args.output_dir, dry_run=not args.delete)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        mode = "DRY RUN" if report["dry_run"] else "DELETED"
        print(f"{mode}: {report['count']} orphan(s), {report['bytes']} byte(s)")
        for item in report["orphans"]:
            print(f"  {item['path']} ({item['size']} bytes)")
        for failure in report["failures"]:
            print(f"  FAILED {failure['path']}: {failure['message']}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
