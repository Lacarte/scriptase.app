"""Implementation plan 4.1: Script Studio batch Job creation."""

from __future__ import annotations

import pytest

from app import create_app
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_draft
from scriptase.jobs import store as job_store
from scriptase.jobs.store import get_job, list_jobs
from scriptase.scripts import store as script_store
from scriptase.scripts.store import create_script


@pytest.fixture
def batch_env(tmp_path, monkeypatch):
    channels = tmp_path / "channels"
    jobs = tmp_path / "jobs"
    scripts = tmp_path / "scripts"
    for path in (channels, jobs, scripts):
        path.mkdir(parents=True)
    monkeypatch.setattr(channel_store, "_channels_dir", str(channels))
    monkeypatch.setattr(channel_store, "_trash_dir", str(tmp_path / "trash" / "channels"))
    monkeypatch.setattr(job_store, "_jobs_dir", str(jobs))
    monkeypatch.setattr(job_store, "_trash_dir", str(tmp_path / "trash" / "jobs"))
    monkeypatch.setattr(script_store, "_scripts_dir", str(scripts))
    monkeypatch.setattr(script_store, "_trash_dir", str(tmp_path / "trash" / "scripts"))

    channel = create_channel(channel_draft(name="Batch Channel"))
    studio_scripts = [
        create_script({
            "title": f"Episode {index}",
            "body": f"Finished narration for episode {index}.",
            "channel_id": channel.id,
            "origin": "manual",
            "narration": {},
        })
        for index in range(5)
    ]
    app = create_app(discover_providers=False)
    app.config["TESTING"] = True
    return app.test_client(), channel, studio_scripts


def test_five_selected_scripts_become_five_queued_jobs(batch_env):
    client, channel, scripts = batch_env
    response = client.post("/api/jobs/batch", json={
        "batch": {
            "channel_id": channel.id,
            "script_ids": [script.id for script in scripts],
            "execution_mode": "assisted",
        }
    })

    assert response.status_code == 201, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["total"] == 5
    assert len(payload["jobs"]) == 5
    assert len(list_jobs()) == 5

    by_script = {script.id: script for script in scripts}
    for item in payload["jobs"]:
        assert item["status"] == "queued"
        assert item["execution_id"] is None
        assert item["execution_mode"] == "assisted"
        assert item["source"]["script_id"] in by_script
        assert item["source"]["pasted_script"] == by_script[item["source"]["script_id"]].body
        assert item["channel_snapshot"]["id"] == channel.id
        assert get_job(item["id"]).channel_snapshot == item["channel_snapshot"]


def test_invalid_selection_creates_no_partial_batch(batch_env):
    client, channel, scripts = batch_env
    response = client.post("/api/jobs/batch", json={
        "channel_id": channel.id,
        "script_ids": [scripts[0].id, "scr_MISSING"],
        "execution_mode": "manual",
    })
    assert response.status_code == 422
    assert list_jobs() == []


def test_job_list_exposes_searchable_script_and_channel_names(batch_env):
    """Step 4.4: collapsed archive entries remain findable by their names."""
    client, channel, scripts = batch_env
    created = client.post("/api/jobs", json={
        "job": {
            "channel_id": channel.id,
            "execution_mode": "manual",
            "source": {"script_id": scripts[2].id},
        }
    })
    assert created.status_code == 201

    response = client.get("/api/jobs")
    assert response.status_code == 200
    summary = response.get_json()["jobs"][0]
    assert summary["name"] == "Episode 2"
    assert summary["channel_name"] == "Batch Channel"


def test_single_job_endpoint_accepts_a_managed_studio_source(batch_env):
    client, channel, scripts = batch_env
    response = client.post("/api/jobs", json={
        "job": {
            "channel_id": channel.id,
            "execution_mode": "manual",
            "source": {"script_id": scripts[0].id},
        }
    })
    assert response.status_code == 201, response.get_data(as_text=True)
    source = response.get_json()["job"]["source"]
    assert source["script_id"] == scripts[0].id
    assert source["mode"] == "paste"
    assert source["pasted_script"] == scripts[0].body
