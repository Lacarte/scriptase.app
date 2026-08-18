"""Implementation plan 3.1 — Script model and store acceptance tests."""

from __future__ import annotations

import os

import pytest

from scriptase.artifacts import store as artifact_store
from scriptase.artifacts.store import register_artifact
from scriptase.scripts import store as script_store
from scriptase.scripts.store import (
    ScriptConflict,
    ScriptNotFound,
    ScriptValidationError,
    create_script,
    delete_script,
    get_script,
    list_scripts,
    resolve_narration_audio,
    update_script,
)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"
    artifacts = tmp_path / "artifacts"
    output = tmp_path / "output"
    trash = tmp_path / "trash" / "scripts"
    for path in (scripts, artifacts, output):
        path.mkdir(parents=True)
    monkeypatch.setattr(script_store, "_scripts_dir", str(scripts))
    monkeypatch.setattr(script_store, "_trash_dir", str(trash))
    monkeypatch.setattr(artifact_store, "_artifacts_dir", str(artifacts))
    monkeypatch.setattr(artifact_store, "_output_dir", str(output))
    return {"scripts": scripts, "output": output, "trash": trash}


def draft(**changes):
    result = {
        "title": "A useful idea",
        "body": "One two three four five",
        "channel_id": "ch_ABC123",
        "origin": "manual",
        "narration": {},
    }
    result.update(changes)
    return result


def test_script_crud_list_and_derived_metrics(stores):
    created = create_script(draft())
    assert created.id.startswith("scr_")
    assert created.version == 1
    assert created.word_count == 5
    assert created.estimated_duration_s == 2
    assert get_script(created.id).to_document() == created.to_document()
    assert [item.id for item in list_scripts()] == [created.id]

    updated = update_script(
        created.id,
        draft(title="Renamed", body="Just two"),
        expected_version=1,
    )
    assert updated.version == 2
    assert updated.created_at == created.created_at
    assert updated.word_count == 2
    assert updated.estimated_duration_s == 1
    with pytest.raises(ScriptConflict):
        update_script(created.id, draft(), expected_version=1)

    delete_script(created.id, expected_version=2)
    with pytest.raises(ScriptNotFound):
        get_script(created.id)
    assert list_scripts() == []
    assert any(created.id in name for name in os.listdir(stores["trash"]))


def test_narration_audio_resolves_through_shared_artifact_store(stores):
    created = create_script(draft())
    relative = f"tts/{created.id}/voice.wav"
    absolute = stores["output"] / relative
    absolute.parent.mkdir(parents=True)
    absolute.write_bytes(b"RIFF-studio-audio")
    audio = register_artifact(job_id=created.id, kind="audio", path=relative)

    payload = draft(narration={
        "state": "ready",
        "voice": "Alex",
        "duration": 12.5,
        "audio_artifact_ref": audio.id,
    })
    updated = update_script(created.id, payload, expected_version=1)
    assert updated.narration.audio_artifact_id == audio.id
    assert updated.narration.duration_s == 12.5
    assert resolve_narration_audio(updated).id == audio.id


def test_ready_narration_rejects_missing_or_wrong_artifact(stores):
    with pytest.raises(ScriptValidationError):
        create_script(draft(narration={"state": "ready"}))

    created = create_script(draft())
    relative = f"stories/{created.id}.txt"
    absolute = stores["output"] / relative
    absolute.parent.mkdir(parents=True)
    absolute.write_text("not audio", encoding="utf-8")
    wrong = register_artifact(job_id=created.id, kind="script", path=relative)
    with pytest.raises(ScriptValidationError):
        update_script(created.id, draft(narration={
            "state": "ready", "audio_artifact_id": wrong.id,
        }))
