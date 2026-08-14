"""Editor project ZIP export / import (service layer).

Business logic extracted from ``archive_routes`` so V2 import (step 10.1) and
HTTP transport can share one path without importing from a routes module.

Layout is V2-compatible on purpose: ``projects/``, ``scenes/``, ``animator/``,
``alignments/``, ``tts/`` under the managed output root. Directory *names* do
not rename with packages.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO

from loguru import logger

from config import ALIGN_DIR, ANIMATOR_DIR, OUTPUT_DIR, PROJECTS_DIR, SCENES_DIR, TTS_DIR
from scriptase.modules.compose.schemas import EditorSaveRequest
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.shared.security import safe_join, sanitize_folder_name, sanitize_project_id


class ProjectZipError(ValueError):
    """Stable, presentation-safe project ZIP error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProjectZipExport:
    """Bytes + manifest for one exported editor project."""

    project_id: str
    data: bytes
    manifest: dict
    filename: str


@dataclass(frozen=True)
class ProjectZipImport:
    project_id: str
    imported_files: int
    source_folder: str
    renamed_from: str | None = None


def _roots(*, output_dir: str | None = None) -> dict[str, str]:
    root = os.path.abspath(output_dir or OUTPUT_DIR)
    return {
        "output": root,
        "projects": os.path.join(root, "projects") if output_dir else PROJECTS_DIR,
        "scenes": os.path.join(root, "scenes") if output_dir else SCENES_DIR,
        "animator": os.path.join(root, "animator") if output_dir else ANIMATOR_DIR,
        "align": os.path.join(root, "alignments") if output_dir else ALIGN_DIR,
        "tts": os.path.join(root, "tts") if output_dir else TTS_DIR,
    }


def _project_dir(project_id: str, roots: dict[str, str]) -> str:
    return os.path.join(roots["projects"], project_id)


def _initial_path(project_id: str, roots: dict[str, str]) -> str:
    return os.path.join(_project_dir(project_id, roots), "initial.json")


def _wip_path(project_id: str, roots: dict[str, str]) -> str:
    return os.path.join(_project_dir(project_id, roots), "work@in@progress.json")


def _get_source_folder(project_id: str, roots: dict[str, str]) -> str | None:
    scenes_path = os.path.join(roots["scenes"], project_id, "scenes.json")
    try:
        with open(scenes_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        logger.debug("Could not read source_folder from {}: {}", scenes_path, error)
        return None
    value = data.get("source_folder") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def coerce_imported_editor_project(
    raw_bytes: bytes, project_id: str, renamed_from: str | None = None
) -> dict:
    """Validate and normalize imported editor project payload before saving."""
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectZipError("PROJECT_JSON_INVALID", f"Invalid project.json payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProjectZipError("PROJECT_JSON_INVALID", "Invalid project.json payload: expected JSON object")

    payload["project_id"] = project_id
    project_name = str(payload.get("project_name", "") or "").strip()
    if not project_name or (renamed_from and project_name == renamed_from):
        payload["project_name"] = project_id

    EditorSaveRequest.model_validate(payload)
    return payload


def export_project_zip(
    project_id: str,
    *,
    output_dir: str | None = None,
) -> ProjectZipExport:
    """Bundle a complete editor project into ZIP bytes."""
    roots = _roots(output_dir=output_dir)
    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))
    if not safe_id:
        raise ProjectZipError("PROJECT_ID_INVALID", "project_id is invalid")

    wip_file = _wip_path(safe_id, roots)
    initial_file = _initial_path(safe_id, roots)
    editor_path = wip_file if os.path.isfile(wip_file) else initial_file
    scenes_path = os.path.join(roots["scenes"], safe_id, "scenes.json")
    if not os.path.isfile(editor_path) and not os.path.isfile(scenes_path):
        raise ProjectZipError("PROJECT_NOT_FOUND", "Project not found")

    source_folder = _get_source_folder(safe_id, roots)
    manifest: dict = {
        "project_id": safe_id,
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_folder": source_folder or "",
        "files": [],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        prefix = f"{safe_id}/"

        if os.path.isfile(editor_path):
            zf.write(editor_path, f"{prefix}project.json")
            manifest["files"].append("project.json")

        if os.path.isfile(scenes_path):
            zf.write(scenes_path, f"{prefix}scenes.json")
            manifest["files"].append("scenes.json")

        assets_dir = os.path.join(roots["animator"], safe_id)
        if os.path.isdir(assets_dir):
            for root, _dirs, files in os.walk(assets_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, assets_dir).replace("\\", "/")
                    zf.write(fpath, f"{prefix}assets/{rel}")
                    manifest["files"].append(f"assets/{rel}")

        if source_folder:
            align_dir = os.path.join(roots["align"], source_folder)
            if os.path.isdir(align_dir):
                try:
                    for fname in os.listdir(align_dir):
                        fpath = os.path.join(align_dir, fname)
                        if os.path.isfile(fpath):
                            zf.write(fpath, f"{prefix}audio/{fname}")
                            manifest["files"].append(f"audio/{fname}")
                except OSError:
                    pass

            tts_dir = os.path.join(roots["tts"], source_folder)
            if os.path.isdir(tts_dir):
                try:
                    for fname in os.listdir(tts_dir):
                        fpath = os.path.join(tts_dir, fname)
                        if os.path.isfile(fpath):
                            zf.write(fpath, f"{prefix}tts/{fname}")
                            manifest["files"].append(f"tts/{fname}")
                except OSError:
                    pass

        zf.writestr(f"{prefix}manifest.json", json.dumps(manifest, indent=2))

    data = buf.getvalue()
    logger.info(
        "Project ZIP exported: {} ({} files, {:.1f} MB)",
        safe_id,
        len(manifest["files"]),
        len(data) / 1024 / 1024,
    )
    return ProjectZipExport(
        project_id=safe_id,
        data=data,
        manifest=manifest,
        filename=f"{safe_id}.zip",
    )


def import_project_zip(
    source: BinaryIO | bytes,
    *,
    output_dir: str | None = None,
) -> ProjectZipImport:
    """Import an editor project ZIP into the managed output tree."""
    roots = _roots(output_dir=output_dir)
    raw = source if isinstance(source, (bytes, bytearray)) else source.read()
    try:
        zio = io.BytesIO(raw)
        with zipfile.ZipFile(zio, "r") as zf:
            names = zf.namelist()
            if not names:
                raise ProjectZipError("ARCHIVE_EMPTY", "ZIP is empty")

            project_id = None
            manifest = None
            for name in names:
                if name.endswith("manifest.json"):
                    try:
                        manifest = json.loads(zf.read(name))
                    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                        raise ProjectZipError(
                            "MANIFEST_INVALID", "manifest.json is not valid JSON"
                        ) from exc
                    if isinstance(manifest, dict):
                        project_id = manifest.get("project_id")
                    break
            if not project_id:
                project_id = names[0].split("/")[0]

            safe_id = sanitize_project_id(str(project_id) if project_id is not None else "")
            if not safe_id:
                raise ProjectZipError(
                    "PROJECT_ID_INVALID", "Cannot determine project ID from ZIP"
                )

            has_scenes = any(n.endswith("scenes.json") for n in names)
            has_project = any(n.endswith("project.json") for n in names)
            if not has_scenes and not has_project:
                raise ProjectZipError(
                    "ARCHIVE_INVALID",
                    "Invalid project ZIP: missing scenes.json and project.json",
                )

            original_id = safe_id
            renamed_from = None
            scenes_dir_check = os.path.join(roots["scenes"], safe_id)
            editor_dir_check = _project_dir(safe_id, roots)
            if os.path.exists(scenes_dir_check) or os.path.isdir(editor_dir_check):
                suffix = 2
                while True:
                    candidate = f"{original_id}-{suffix}"
                    if not os.path.exists(os.path.join(roots["scenes"], candidate)) and not os.path.isdir(
                        _project_dir(candidate, roots)
                    ):
                        renamed_from = safe_id
                        safe_id = candidate
                        break
                    suffix += 1
                logger.info("Project {} already exists, renamed to {}", original_id, safe_id)

            source_folder = sanitize_folder_name(
                (manifest or {}).get("source_folder", "") if isinstance(manifest, dict) else ""
            )
            # Prefer original archive prefix so members extract even when the id was renamed.
            prefix = f"{original_id}/"
            imported: list[str] = []

            for name in names:
                if name.endswith("/"):
                    continue
                rel = name[len(prefix) :] if name.startswith(prefix) else name
                member = zf.read(name)

                if rel == "project.json":
                    os.makedirs(_project_dir(safe_id, roots), exist_ok=True)
                    project_payload = coerce_imported_editor_project(
                        member, safe_id, renamed_from=renamed_from
                    )
                    safe_json_write(_initial_path(safe_id, roots), project_payload, indent=2)
                    imported.append(rel)
                elif rel == "scenes.json":
                    dest_dir = os.path.join(roots["scenes"], safe_id)
                    os.makedirs(dest_dir, exist_ok=True)
                    with open(os.path.join(dest_dir, "scenes.json"), "wb") as handle:
                        handle.write(member)
                    imported.append(rel)
                elif rel.startswith("assets/"):
                    sub = rel[len("assets/") :]
                    try:
                        dest = safe_join(os.path.join(roots["animator"], safe_id), sub)
                    except ValueError as exc:
                        raise ProjectZipError("ARCHIVE_PATH_INVALID", "Invalid ZIP path in assets") from exc
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as handle:
                        handle.write(member)
                    imported.append(rel)
                elif rel.startswith("audio/") and source_folder:
                    sub = rel[len("audio/") :]
                    try:
                        dest = safe_join(os.path.join(roots["align"], source_folder), sub)
                    except ValueError as exc:
                        raise ProjectZipError("ARCHIVE_PATH_INVALID", "Invalid ZIP path in audio") from exc
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as handle:
                        handle.write(member)
                    imported.append(rel)
                elif rel.startswith("tts/") and source_folder:
                    sub = rel[len("tts/") :]
                    try:
                        dest = safe_join(os.path.join(roots["tts"], source_folder), sub)
                    except ValueError as exc:
                        raise ProjectZipError("ARCHIVE_PATH_INVALID", "Invalid ZIP path in tts") from exc
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as handle:
                        handle.write(member)
                    imported.append(rel)

            if renamed_from:
                scenes_json_path = os.path.join(roots["scenes"], safe_id, "scenes.json")
                if os.path.exists(scenes_json_path):
                    try:
                        sdata = safe_json_read(scenes_json_path)
                        if isinstance(sdata, dict):
                            sdata["project_id"] = safe_id
                            safe_json_write(scenes_json_path, sdata, indent=2)
                    except Exception as error:
                        logger.debug(
                            "Could not update imported scenes.json {}: {}",
                            scenes_json_path,
                            error,
                        )
                editor_json_path = _initial_path(safe_id, roots)
                if os.path.exists(editor_json_path):
                    try:
                        edata = safe_json_read(editor_json_path)
                        if isinstance(edata, dict):
                            edata["project_id"] = safe_id
                            project_name = str(edata.get("project_name", "") or "").strip()
                            if not project_name or project_name == renamed_from:
                                edata["project_name"] = safe_id
                            EditorSaveRequest.model_validate(edata)
                            safe_json_write(editor_json_path, edata, indent=2)
                    except Exception as error:
                        logger.debug(
                            "Could not update imported editor manifest {}: {}",
                            editor_json_path,
                            error,
                        )

            logger.info(
                "Project ZIP imported: {} ({} files){}",
                safe_id,
                len(imported),
                f" (renamed from {renamed_from})" if renamed_from else "",
            )
            return ProjectZipImport(
                project_id=safe_id,
                imported_files=len(imported),
                source_folder=source_folder or "",
                renamed_from=renamed_from,
            )
    except zipfile.BadZipFile as exc:
        raise ProjectZipError("ARCHIVE_INVALID", "Invalid ZIP file") from exc


__all__ = [
    "ProjectZipError",
    "ProjectZipExport",
    "ProjectZipImport",
    "coerce_imported_editor_project",
    "export_project_zip",
    "import_project_zip",
]
