"""Step 9.3: conservative asset garbage collection."""

from __future__ import annotations

import json

from flask import Flask

import scriptase.engine.routes as workflow_routes
from scriptase.engine import workflows_bp
from scriptase.engine.asset_gc import collect_orphans, main, scan_orphans
from scriptase.engine.execution import ExecutionManager


def _write(path, content=b"asset"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_gc_deletes_only_orphans_and_preserves_execution_and_pinned_roots(tmp_path):
    _write(tmp_path / "media" / "orphan.bin", b"orphan")
    _write(tmp_path / "media" / "executed.bin", b"execution")
    _write(tmp_path / "media" / "pinned.bin", b"pinned")
    _write(tmp_path / "workflows" / "runtime.bin", b"protected")
    _json(tmp_path / "workflows" / "executions" / "ex_ABC123.json", {
        "execution_id": "ex_ABC123",
        "nodes": {"node": {"artifact_refs": ["media/executed.bin"]}},
    })
    _json(tmp_path / "workflows" / "wf_ABC123.json", {
        "nodes": [{
            "type": "stub.output",
            "configuration": {
                "pinned": True,
                "payload": {"preview": "/output/media/pinned.bin"},
            },
        }],
    })

    assert [item.path for item in scan_orphans(output_dir=str(tmp_path))] == ["media/orphan.bin"]
    dry_run = collect_orphans(output_dir=str(tmp_path))
    assert dry_run["dry_run"] is True and dry_run["deleted"] == []
    assert (tmp_path / "media" / "orphan.bin").exists()

    result = collect_orphans(
        output_dir=str(tmp_path), paths=["media/orphan.bin"], dry_run=False
    )
    assert result["deleted"] == ["media/orphan.bin"]
    assert not (tmp_path / "media" / "orphan.bin").exists()
    assert (tmp_path / "media" / "executed.bin").read_bytes() == b"execution"
    assert (tmp_path / "media" / "pinned.bin").read_bytes() == b"pinned"
    assert (tmp_path / "workflows" / "runtime.bin").read_bytes() == b"protected"


def test_gc_rejects_stale_or_unlisted_paths(tmp_path):
    _write(tmp_path / "orphan.bin")
    try:
        collect_orphans(output_dir=str(tmp_path), paths=["../orphan.bin"], dry_run=False)
    except ValueError as exc:
        assert "current orphan scan" in str(exc)
    else:
        raise AssertionError("unsafe path was accepted")
    assert (tmp_path / "orphan.bin").exists()


def test_cli_is_dry_run_by_default(tmp_path, capsys):
    _write(tmp_path / "orphan.bin")
    assert main(["--output-dir", str(tmp_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert (tmp_path / "orphan.bin").exists()
    assert main(["--output-dir", str(tmp_path), "--delete"]) == 0
    assert not (tmp_path / "orphan.bin").exists()


def test_gc_api_previews_then_deletes_selected_orphans(tmp_path, monkeypatch):
    _write(tmp_path / "orphan.bin")
    manager = ExecutionManager(output_dir=str(tmp_path))
    monkeypatch.setattr(workflow_routes, "execution_manager", manager)
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    http = app.test_client()

    preview = http.get("/api/workflow/assets/orphans")
    assert preview.status_code == 200
    assert preview.get_json()["orphans"][0]["path"] == "orphan.bin"
    deleted = http.post(
        "/api/workflow/assets/gc", json={"paths": ["orphan.bin"], "dry_run": False}
    )
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] == ["orphan.bin"]
    stale = http.post(
        "/api/workflow/assets/gc", json={"paths": ["orphan.bin"], "dry_run": False}
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"]["code"] == "ASSET_GC_STALE"
