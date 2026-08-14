"""Step 9.4: portable project archive and restore."""

from __future__ import annotations

import io
import json
import os
import zipfile

from flask import Flask

import scriptase.engine.persistence as persistence
import scriptase.engine.routes as workflow_routes
from scriptase.engine import workflows_bp
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.project_archive import ProjectArchiveError, create_archive, restore_archive
from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.engine.validation import validate_workflow, validation_errors


def _workflow():
    return {
        "schema_version": 1,
        "workflow_id": "wf_ABC123",
        "name": "Archived project",
        "description": "",
        "nodes": [{
            "id": "n_script", "type": "script.input", "type_version": 1,
            "name": "Script", "position": {"x": 0, "y": 0},
            "configuration": {"text": "portable"}, "disabled": False,
        }],
        "edges": [], "variables": {}, "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {"logo": "branding/logo.png"},
        "created_at": "2026-08-05T12:00:00+00:00",
        "updated_at": "2026-08-05T12:00:00+00:00",
    }


def _record():
    return {
        "schema_version": 1, "execution_id": "ex_ABC123",
        "workflow_id": "wf_ABC123", "workflow_snapshot": _workflow(),
        "project_id": "pm_ABC123", "run_mode": "full", "status": "succeeded",
        "started_at": "2026-08-05T12:01:00+00:00", "finished_at": "2026-08-05T12:01:01+00:00",
        "nodes": {"n_script": {"artifact_refs": ["projects/pm_ABC123/media.bin"]}},
    }


def _seed(root):
    (root / "workflows" / "executions").mkdir(parents=True)
    (root / "projects" / "pm_ABC123").mkdir(parents=True)
    (root / "branding").mkdir()
    (root / "workflows" / "wf_ABC123.json").write_text(json.dumps(_workflow()), encoding="utf-8")
    (root / "workflows" / "executions" / "ex_ABC123.json").write_text(json.dumps(_record()), encoding="utf-8")
    (root / "projects" / "pm_ABC123" / "media.bin").write_bytes(b"\x00portable-media\xff")
    (root / "branding" / "logo.png").write_bytes(b"portable-logo")


def test_archive_delete_restore_round_trip_rewrites_ids_and_runs(tmp_path):
    _seed(tmp_path)
    archive = io.BytesIO()
    manifest = create_archive("wf_ABC123", "pm_ABC123", archive, output_dir=str(tmp_path))
    assert manifest["execution_count"] == 1
    assert manifest["artifact_count"] == 2

    expected_media = (tmp_path / "projects" / "pm_ABC123" / "media.bin").read_bytes()
    expected_logo = (tmp_path / "branding" / "logo.png").read_bytes()
    for path in [tmp_path / "workflows" / "wf_ABC123.json",
                 tmp_path / "workflows" / "executions" / "ex_ABC123.json",
                 tmp_path / "projects" / "pm_ABC123" / "media.bin",
                 tmp_path / "branding" / "logo.png"]:
        path.unlink()

    archive.seek(0)
    result = restore_archive(
        archive, output_dir=str(tmp_path), project_id_mode="new", workflow_id_mode="new"
    )
    assert result.project_id != "pm_ABC123"
    assert result.workflow["workflow_id"] != "wf_ABC123"
    assert not validation_errors(validate_workflow(result.workflow, require_identity=True))
    restored_record = json.loads(
        (tmp_path / "workflows" / "executions" / "ex_ABC123.json").read_text(encoding="utf-8")
    )
    assert restored_record["project_id"] == result.project_id
    assert restored_record["workflow_id"] == result.workflow["workflow_id"]
    assert result.project_id in restored_record["nodes"]["n_script"]["artifact_refs"][0]
    assert (tmp_path / "projects" / result.project_id / "media.bin").read_bytes() == expected_media
    assert (tmp_path / "branding" / "logo.png").read_bytes() == expected_logo

    calls = []
    scheduler = WorkflowScheduler(
        result.workflow, project_id=result.project_id,
        output_dir=str(tmp_path), lock_root=str(tmp_path / "locks"),
        executor_resolver=lambda node: lambda inputs, config, context: calls.append(node["id"]) or {
            "control": {"ok": True}, "script": config["text"]
        },
    )
    assert scheduler.run().status == "succeeded"
    assert calls == ["n_script"]


def test_restore_rejects_traversal_and_checksum_tampering(tmp_path):
    _seed(tmp_path)
    source = io.BytesIO()
    create_archive("wf_ABC123", "pm_ABC123", source, output_dir=str(tmp_path))
    source.seek(0)
    tampered = io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(tampered, "w") as changed:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename == "workflow.json":
                data += b" "
            changed.writestr(info.filename, data)
        changed.writestr("../escape", b"bad")
    tampered.seek(0)
    try:
        restore_archive(tampered, output_dir=str(tmp_path))
    except ProjectArchiveError as exc:
        assert exc.code == "ARCHIVE_INVALID"
    else:
        raise AssertionError("unsafe archive was accepted")
    assert not (tmp_path.parent / "escape").exists()


def test_restore_can_recreate_original_ids_after_project_is_removed(tmp_path):
    _seed(tmp_path)
    archive = io.BytesIO()
    create_archive("wf_ABC123", "pm_ABC123", archive, output_dir=str(tmp_path))
    for path in [tmp_path / "workflows" / "wf_ABC123.json",
                 tmp_path / "workflows" / "executions" / "ex_ABC123.json",
                 tmp_path / "projects" / "pm_ABC123" / "media.bin",
                 tmp_path / "branding" / "logo.png"]:
        path.unlink()
    archive.seek(0)
    result = restore_archive(
        archive, output_dir=str(tmp_path), project_id_mode="original", workflow_id_mode="original"
    )
    assert result.workflow["workflow_id"] == "wf_ABC123"
    assert result.project_id == "pm_ABC123"
    assert (tmp_path / "projects" / "pm_ABC123" / "media.bin").read_bytes() == b"\x00portable-media\xff"


def test_archive_includes_direct_managed_refs_from_pinned_viewers(tmp_path):
    _seed(tmp_path)
    pinned = tmp_path / "projects" / "pm_ABC123" / "pinned.bin"
    pinned.write_bytes(b"pinned")
    workflow_path = tmp_path / "workflows" / "wf_ABC123.json"
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    workflow["nodes"].append({
        "id": "n_viewer", "type": "stub.output", "type_version": 1, "name": "Viewer",
        "position": {"x": 200, "y": 0}, "disabled": False,
        "configuration": {
            "port_type": "generic_json", "pinned": True,
            "payload": {"preview": "/output/projects/pm_ABC123/pinned.bin"},
        },
    })
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
    archive = io.BytesIO()
    create_archive("wf_ABC123", "pm_ABC123", archive, output_dir=str(tmp_path))
    archive.seek(0)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.read("artifacts/projects/pm_ABC123/pinned.bin") == b"pinned"


def test_archive_http_export_and_restore(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setattr(persistence, "WORKFLOWS_DIR", str(tmp_path / "workflows"))
    manager = ExecutionManager(output_dir=str(tmp_path))
    monkeypatch.setattr(workflow_routes, "execution_manager", manager)
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    http = app.test_client()

    projects = http.get("/api/workflows/wf_ABC123/projects")
    assert projects.status_code == 200
    assert projects.get_json()["projects"][0]["project_id"] == "pm_ABC123"
    exported = http.get("/api/workflows/wf_ABC123/projects/pm_ABC123/archive")
    assert exported.status_code == 200
    assert "wf_ABC123_pm_ABC123.sts-project.zip" in exported.headers["Content-Disposition"]

    restored = http.post(
        "/api/workflow/projects/restore",
        data={
            "file": (io.BytesIO(exported.data), "backup.sts-project.zip"),
            "project_id_mode": "new", "workflow_id_mode": "new",
        },
        content_type="multipart/form-data",
    )
    assert restored.status_code == 201
    payload = restored.get_json()
    assert payload["project_id"] != "pm_ABC123"
    assert payload["workflow"]["workflow_id"] != "wf_ABC123"
    assert os.path.isfile(tmp_path / "workflows" / f"{payload['workflow']['workflow_id']}.json")
