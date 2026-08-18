"""Step 3.3 — Studio narration generation and immutable regeneration."""

from __future__ import annotations

import os
import wave
from copy import deepcopy

import pytest

from app import create_app
from scriptase.artifacts import store as artifact_store
from scriptase.channels import store as channel_store
from scriptase.scripts import narration as narration_service
from scriptase.scripts import store as script_store
from scriptase.scripts.narration import generate_narration


def _wav(path: str, seconds: float = 0.1) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\0\0" * int(8000 * seconds))


@pytest.fixture
def studio_stores(tmp_path, monkeypatch):
    output = tmp_path / "output"
    for path in (output / "scripts", output / "channels", output / "artifacts", output / "tts"):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(script_store, "_scripts_dir", str(output / "scripts"))
    monkeypatch.setattr(script_store, "_trash_dir", str(output / "trash" / "scripts"))
    monkeypatch.setattr(channel_store, "_channels_dir", str(output / "channels"))
    monkeypatch.setattr(artifact_store, "_artifacts_dir", str(output / "artifacts"))
    monkeypatch.setattr(artifact_store, "_output_dir", str(output))
    monkeypatch.setattr(narration_service, "_tts_dir", str(output / "tts"))
    monkeypatch.setattr(narration_service, "_output_dir", str(output))
    channel = channel_store.create_channel({
        "name": "Narrated",
        "content": {"language": "english"},
        "audio_defaults": {
            "voice": "Alex", "remove_silence": True, "speed": 1.1,
        },
    })
    script = script_store.create_script({
        "title": "A take", "body": "A short but complete narration.",
        "channel_id": channel.id, "origin": "manual", "narration": {},
    })
    return output, script


def test_generation_resolves_inheritance_and_registers_audio(studio_stores, monkeypatch):
    output, script = studio_stores
    calls = []

    def fake_synthesize(config, **kwargs):
        calls.append(deepcopy(config))
        path = os.path.join(kwargs["output_dir"], kwargs["basename"] + ".wav")
        _wav(path)
        return {
            "wav_path": path, "voice": config["voice"], "duration_seconds": 2.5,
            "job_meta": {"invocation_id": "inv_test"},
        }

    monkeypatch.setattr(narration_service.dispatch, "synthesize", fake_synthesize)
    ready, artifact = generate_narration(script.id, expected_version=script.version)

    assert calls[0]["voice"] == "Alex"
    assert calls[0]["remove_silence"] is True
    assert calls[0]["speed"] == 1.1
    assert ready.narration.state == "ready"
    assert ready.narration.remove_silence is None
    assert ready.narration.speed is None
    assert ready.narration.audio_artifact_id == artifact.id
    assert artifact.path == f"tts/{script.id}/narration_v1.wav"


def test_regeneration_supersedes_without_erasing_previous_take(studio_stores, monkeypatch):
    output, script = studio_stores

    def fake_synthesize(config, **kwargs):
        path = os.path.join(kwargs["output_dir"], kwargs["basename"] + ".wav")
        _wav(path)
        return {"wav_path": path, "voice": config["voice"], "duration_seconds": 1.0}

    monkeypatch.setattr(narration_service.dispatch, "synthesize", fake_synthesize)
    first, old_artifact = generate_narration(script.id)
    second, new_artifact = generate_narration(
        script.id, voice="Ashley", remove_silence=False, speed=1.25,
        expected_version=first.version,
    )

    old = artifact_store.get_artifact(old_artifact.id)
    assert old.superseded_by == new_artifact.id
    assert os.path.isfile(output / old.path)
    assert os.path.isfile(output / new_artifact.path)
    assert second.narration.audio_artifact_id == new_artifact.id
    assert second.narration.remove_silence is False
    assert second.narration.speed == 1.25


def test_audio_endpoint_serves_only_artifacts_owned_by_script(studio_stores, monkeypatch):
    output, script = studio_stores
    path = output / "tts" / script.id / "narration_v1.wav"
    _wav(str(path))
    artifact = artifact_store.register_artifact(
        job_id=script.id, kind="audio", path=f"tts/{script.id}/narration_v1.wav"
    )
    ready = script_store.update_script(script.id, {
        "title": script.title, "body": script.body, "channel_id": script.channel_id,
        "origin": script.origin,
        "narration": {"state": "ready", "audio_artifact_id": artifact.id},
    })
    app = create_app(
        discover_providers=False, start_triggers=False, reconcile=False,
        seed_default_workflow=False,
    )
    app.config["TESTING"] = True
    client = app.test_client()

    response = client.get(f"/api/scripts/{script.id}/narration/audio")
    assert response.status_code == 200
    assert response.mimetype in {"audio/x-wav", "audio/wav"}

    other = script_store.create_script({
        "title": "Other", "body": "Other", "channel_id": ready.channel_id,
        "origin": "manual", "narration": {},
    })
    denied = client.get(
        f"/api/scripts/{other.id}/narration/audio?artifact_id={artifact.id}"
    )
    assert denied.status_code == 404
