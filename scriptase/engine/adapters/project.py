from __future__ import annotations

import os

from config import BRANDING_DIR, PROJECTS_DIR
from scriptase.shared.io_utils import safe_json_read
from scriptase.shared.security import safe_join

from .common import AdapterError, outputs, project_id, with_artifacts


def setup(inputs, config, context):
    settings = dict(config or {})
    logo = settings.get("logo")
    if settings.get("logo_enabled"):
        if not isinstance(logo, dict) or not (logo.get("ref") or logo.get("path")):
            raise AdapterError("LOGO_REQUIRED", "Logo is enabled but no managed logo was selected")
        ref = str(logo.get("ref") or logo.get("path")).replace("\\", "/").lstrip("/")
        if ref.startswith("output/"):
            ref = ref[7:]
        if not ref.startswith("branding/"):
            raise AdapterError("ARTIFACT_UNMANAGED", "Logo must be a managed branding asset")
        logo_path = safe_join(BRANDING_DIR, ref.split("/", 1)[1])
        if not os.path.isfile(logo_path):
            raise AdapterError("ARTIFACT_MISSING", "The selected logo no longer exists")
        settings["logo"] = {**logo, "ref": ref, "path": ref}
        settings["artifact_refs"] = [ref]
    else:
        settings["artifact_refs"] = []
    return outputs(settings=settings)


def script_input(inputs, config, context):
    text = str((config or {}).get("text") or "")
    if not 1 <= len(text) <= 10_000:
        raise AdapterError("SCRIPT_INVALID", "Script must contain 1 to 10,000 characters")
    return outputs(script=text)


def existing(inputs, config, context):
    pid = project_id({"project_id": (config or {}).get("project_id")})
    project_dir = safe_join(PROJECTS_DIR, pid)
    wip = os.path.join(project_dir, "work@in@progress.json")
    initial = os.path.join(project_dir, "initial.json")
    path = wip if os.path.isfile(wip) else initial
    if not os.path.isfile(path):
        raise AdapterError("PROJECT_NOT_FOUND", f"Project {pid} does not exist")
    data = safe_json_read(path)
    payload = with_artifacts({"project_id": pid, "assembled_data": data, "source": "wip" if path == wip else "initial"}, path)
    return outputs(project_id={"project_id": pid}, project=payload)
