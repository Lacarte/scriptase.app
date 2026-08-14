"""Step 7.3: stable, exactly-once watch-folder triggers."""

from copy import deepcopy

from scriptase.engine.validation import validate_workflow, validation_errors
from scriptase.engine.watch_folders import WatchFolderService, watch_run_payload


def _workflow(folder, *, enabled=True):
    return {
        "schema_version": 1,
        "workflow_id": "wf_ABC123",
        "name": "Watched test",
        "description": "",
        "nodes": [{
            "id": "script",
            "type": "script.input",
            "type_version": 1,
            "name": "Script Input",
            "position": {"x": 0, "y": 0},
            "configuration": {"text": "saved fallback"},
            "disabled": False,
            "extensions": {},
        }],
        "edges": [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {
            "on_error": "stop",
            "watch_folder": {
                "enabled": enabled,
                "folder": str(folder),
                "pattern": "*.txt",
                "target_node_id": "",
                "target_port": "",
            },
        },
        "extensions": {},
        "created_at": "2026-08-05T12:00:00+00:00",
        "updated_at": "2026-08-05T12:00:00+00:00",
    }


def test_half_written_file_waits_for_stable_size_then_queues_once_and_moves(tmp_path):
    watched = tmp_path / "incoming"
    watched.mkdir()
    workflow = _workflow(watched)
    now = [0.0]
    queued = []

    def enqueue(document, content, settings):
        snapshot, overrides = watch_run_payload(document, content, settings)
        queued.append((snapshot, overrides))
        return "queued"

    service = WatchFolderService(
        workflow_loader=lambda: [workflow],
        enqueue=enqueue,
        clock=lambda: now[0],
        stable_seconds=1.0,
    )
    incoming = watched / "story.txt"
    incoming.write_text("first half", encoding="utf-8")
    assert service.tick() == []

    now[0] = 0.7
    incoming.write_text("first half and second half", encoding="utf-8")
    assert service.tick() == []  # A changed signature restarts the stable window.
    now[0] = 1.6
    assert service.tick() == []
    now[0] = 1.8
    fired = service.tick()

    assert len(fired) == 1
    assert len(queued) == 1
    assert queued[0][0]["nodes"][0]["configuration"]["text"] == "first half and second half"
    assert queued[0][1] == {}
    assert not incoming.exists()
    assert (watched / "processed" / "story.txt").read_text(encoding="utf-8") == "first half and second half"

    now[0] = 10.0
    assert service.tick() == []
    assert len(queued) == 1  # processed/ is never scanned or re-triggered.


def test_disabled_or_non_matching_files_never_trigger(tmp_path):
    watched = tmp_path / "incoming"
    watched.mkdir()
    workflow = _workflow(watched, enabled=False)
    queued = []
    service = WatchFolderService(
        workflow_loader=lambda: [workflow],
        enqueue=lambda *args: queued.append(args),
        stable_seconds=0,
    )
    (watched / "ignored.md").write_text("no", encoding="utf-8")
    (watched / "also-ignored.txt").write_text("no", encoding="utf-8")
    service.tick()
    service.tick()
    assert queued == []


def test_watch_folder_validation_and_configured_text_port(tmp_path):
    workflow = _workflow(tmp_path)
    assert validation_errors(validate_workflow(workflow, require_identity=True)) == []

    invalid = deepcopy(workflow)
    invalid["settings"]["watch_folder"]["pattern"] = "nested/*.txt"
    problems = validation_errors(validate_workflow(invalid, require_identity=True))
    assert any(item.get("path") == "settings.watch_folder.pattern" for item in problems)

    configured = deepcopy(workflow)
    configured["settings"]["watch_folder"].update({
        "target_node_id": "script",
        "target_port": "missing",
    })
    problems = validation_errors(validate_workflow(configured, require_identity=True))
    assert any(item.get("path") == "settings.watch_folder.target_port" for item in problems)

    valid_target = deepcopy(workflow)
    valid_target["nodes"].append({
        "id": "tts",
        "type": "tts.generate",
        "type_version": 2,
        "name": "Narration",
        "position": {"x": 200, "y": 0},
        "configuration": {},
        "disabled": False,
        "extensions": {},
    })
    valid_target["settings"]["watch_folder"].update({
        "target_node_id": "tts",
        "target_port": "script",
    })
    assert validation_errors(validate_workflow(valid_target, require_identity=True)) == []
    snapshot, overrides = watch_run_payload(
        valid_target, "injected text", valid_target["settings"]["watch_folder"]
    )
    assert snapshot["nodes"][0]["configuration"]["text"] == "saved fallback"
    assert overrides == {"tts": {"script": "injected text"}}
