"""HTTP contract for implementation plan 3.1 Script CRUD."""

from __future__ import annotations

import pytest

from app import create_app
from scriptase.scripts import store as script_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(script_store, "_scripts_dir", str(tmp_path / "scripts"))
    monkeypatch.setattr(script_store, "_trash_dir", str(tmp_path / "trash"))
    app = create_app(
        discover_providers=False,
        start_triggers=False,
        reconcile=False,
        seed_default_workflow=False,
    )
    app.config["TESTING"] = True
    return app.test_client()


def test_script_api_round_trip(client):
    payload = {
        "title": "API script",
        "body": "A short API script.",
        "channel": "ch_ABC123",
        "origin": "paste",
    }
    created_response = client.post("/api/scripts", json=payload)
    assert created_response.status_code == 201
    created = created_response.get_json()["script"]
    assert created["word_count"] == 4
    assert created_response.get_json()["narration_audio"] is None

    got = client.get(f"/api/scripts/{created['id']}")
    assert got.status_code == 200
    assert got.get_json()["script"] == created

    created["title"] = "Updated API script"
    updated = client.put(f"/api/scripts/{created['id']}", json={"script": created})
    assert updated.status_code == 200
    assert updated.get_json()["script"]["version"] == 2

    listed = client.get("/api/scripts?q=updated")
    assert listed.status_code == 200
    assert listed.get_json()["total"] == 1

    deleted = client.delete(f"/api/scripts/{created['id']}?expected_version=2")
    assert deleted.status_code == 204
    assert client.get(f"/api/scripts/{created['id']}").status_code == 404
