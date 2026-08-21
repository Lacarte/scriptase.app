"""Script Studio virality endpoint and cache (implementation plan 3.4)."""

from __future__ import annotations

import pytest

from app import create_app
from scriptase.scripts import store as script_store


@pytest.fixture(autouse=True)
def _stub_llm_judge(monkeypatch):
    """Keep the virality tests offline by default: the LLM second opinion is a
    best-effort network call, so stub it to 'unavailable' unless a test opts in
    by patching it itself. Prevents every test from waiting on a real webhook."""
    from scriptase.scripts import routes as scripts_routes

    monkeypatch.setattr(
        scripts_routes, "llm_score_script_text",
        lambda script_id, text: (None, "stubbed offline in tests"),
    )


def _client(tmp_path, monkeypatch):
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


def _create(client):
    response = client.post("/api/scripts", json={
        "title": "A scored script",
        "body": "Why does silence feel so loud? But here's the thing. Remember this pause.",
        "channel_id": "ch_ABC123",
        "origin": "manual",
    })
    assert response.status_code == 201
    return response.get_json()["script"]


def test_score_is_deterministic_cached_and_requires_no_provider(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    script = _create(client)
    endpoint = f"/api/scripts/{script['id']}/virality"

    first = client.post(endpoint, json={"text": script["body"]})
    second = client.post(endpoint, json={"text": script["body"]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()["cached"] is False
    assert second.get_json()["cached"] is True
    assert first.get_json()["virality"] == second.get_json()["virality"]
    assert first.get_json()["virality"]["scorer"] == "deterministic"
    assert len(first.get_json()["virality"]["dimensions"]) == 6


def test_cached_score_round_trips_with_matching_script_text(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    script = _create(client)
    endpoint = f"/api/scripts/{script['id']}/virality"
    score = client.post(endpoint, json={"text": script["body"]}).get_json()["virality"]

    opened = client.get(f"/api/scripts/{script['id']}")
    assert opened.get_json()["virality"] == score

    changed = client.post(endpoint, json={"text": "An unsaved revision."})
    assert changed.status_code == 200
    assert client.get(f"/api/scripts/{script['id']}").get_json()["virality"] is None


def test_scoring_is_advisory_and_does_not_change_script_version(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    script = _create(client)
    response = client.post(
        f"/api/scripts/{script['id']}/virality",
        json={"text": "Unsaved text is allowed here."},
    )

    assert response.status_code == 200
    reopened = client.get(f"/api/scripts/{script['id']}").get_json()["script"]
    assert reopened["version"] == script["version"]
    assert reopened["body"] == script["body"]


def test_llm_second_opinion_is_included_and_non_fatal(tmp_path, monkeypatch):
    # The endpoint returns a structural score plus a best-effort LLM opinion.
    # When the judge is unreachable, llm_virality is null and the request still
    # succeeds on the structural score.
    from scriptase.scripts import routes as scripts_routes

    client = _client(tmp_path, monkeypatch)
    script = _create(client)

    def boom(script_id, text):
        return None, "The virality webhook is unreachable"

    # Patch where the route uses it (imported by name into the routes module).
    monkeypatch.setattr(scripts_routes, "llm_score_script_text", boom)
    resp = client.post(f"/api/scripts/{script['id']}/virality", json={"text": script["body"]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["virality"]["scorer"] == "deterministic"   # structural still there
    assert body["llm_virality"] is None
    assert "unreachable" in body["llm_error"]


def test_llm_can_be_skipped(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    script = _create(client)
    resp = client.post(
        f"/api/scripts/{script['id']}/virality",
        json={"text": script["body"], "with_llm": False},
    )
    assert resp.status_code == 200
    # No LLM keys when opted out.
    assert "llm_virality" not in resp.get_json()


def test_labeled_body_scores_its_hook_and_cta_present(tmp_path, monkeypatch):
    # Regression: a Script Studio body carries Hook:/Build:/Climax:/CTA: labels.
    # Scoring must parse them into sections first — otherwise hook/cta read as
    # missing and a perfectly good script craters to a "POOR" band.
    client = _client(tmp_path, monkeypatch)
    script = _create(client)
    body = (
        "Hook: Beware the invisible trap lurking in shame.\n\n"
        "Build: Meet Sarah, eager to impress at her new job. Each mistake stings.\n\n"
        "But here's what most don't realize. Shame hijacks your life quietly.\n\n"
        "Climax: Science shows shame is a prison of our own making.\n\n"
        "CTA: So what if breaking free is one honest conversation away?"
    )
    resp = client.post(f"/api/scripts/{script['id']}/virality", json={"text": body})
    assert resp.status_code == 200
    dims = {d["id"]: d for d in resp.get_json()["virality"]["dimensions"]}
    # The hook is clearly present and labeled — it must score above zero.
    assert dims["hook"]["score"] > 0, "labeled hook was not detected"
    assert dims["cta"]["score"] > 0, "labeled CTA was not detected"
