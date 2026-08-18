"""Step 4.5 — failure presentation, targeted retry, and advisories."""

from types import SimpleNamespace

from scriptase.jobs.failure_handling import (
    detect_script_language,
    execution_failure,
    job_advisories,
    retry_failed_job,
)
from scriptase.jobs.models import Job


def _job(*, language=None, text=""):
    return Job.model_validate({
        "id": "job_FAIL01",
        "channel_id": "ch_TEST01",
        "channel_snapshot": {"content": {"language": "en"}},
        "source": {"mode": "paste", "pasted_script": text, "language": language},
        "created_at": "2026-08-18T00:00:00Z",
    })


def test_language_mismatch_is_non_blocking_and_visible_before_run():
    job = _job(language="es", text="Por qué buscamos el silencio")
    advisory = job_advisories(job)[0]
    assert job.status == "queued"
    assert advisory == {
        "code": "LANGUAGE_MISMATCH",
        "severity": "warning",
        "message": "Script language is Spanish, but the Channel language is English.",
        "script_language": "es",
        "channel_language": "en",
        "blocking": False,
    }


def test_detection_warns_only_when_confident():
    assert detect_script_language("Por qué buscamos el silencio y la verdad para una vida mejor") == "es"
    assert detect_script_language("A short title") is None


def test_failure_envelope_names_stage_and_keeps_structured_error():
    workflow = {
        "workflow_id": "wf_TEST01",
        "nodes": [{"id": "n_video", "type": "animator.generate", "configuration": {}}],
        "edges": [],
    }
    execution = {
        "workflow_snapshot": workflow,
        "nodes": {
            "n_video": {
                "status": "failed",
                "error": {
                    "code": "ANIMATOR_FAILED",
                    "message": "Video generation failed.",
                    "recovery_suggestion": "Retry this scene.",
                },
            }
        },
    }
    assert execution_failure(execution) == {
        "node_id": "n_video",
        "node_type": "animator.generate",
        "stage": "videos",
        "stage_label": "Videos",
        "code": "ANIMATOR_FAILED",
        "message": "Video generation failed.",
        "recovery_suggestion": "Retry this scene.",
    }


def test_retry_translates_failure_to_structured_repair_router_issue(monkeypatch):
    from scriptase.jobs import failure_handling
    from scriptase.jobs import orchestration, store
    from scriptase.review import store as review_store

    job = _job(text="A script with enough ordinary English words for this test")
    job = job.model_copy(update={"status": "failed", "execution_id": "ex_TEST01"})
    workflow = {
        "workflow_id": "wf_TEST01",
        "nodes": [{"id": "n_video", "type": "animator.generate", "configuration": {}}],
        "edges": [],
    }
    execution = {
        "workflow_snapshot": workflow,
        "nodes": {"n_video": {"status": "failed", "error": {"code": "ANIMATOR_FAILED", "message": "Video failed."}}},
    }
    captured = {}
    monkeypatch.setattr(store, "get_job", lambda _job_id: job)
    monkeypatch.setattr(failure_handling, "load_job_execution", lambda _job: execution)
    monkeypatch.setattr(review_store, "list_issues", lambda **_kwargs: [])

    def create_issue(**fields):
        captured["issue"] = fields
        return SimpleNamespace(id="iss_TEST01", target_node_id=fields["target_node_id"])

    monkeypatch.setattr(review_store, "create_open_issue", create_issue)
    monkeypatch.setattr(store, "add_issue_ids", lambda *args, **kwargs: captured.setdefault("attached", args[1]))

    def run_cycles(job_id, **kwargs):
        captured["router"] = {"job_id": job_id, **kwargs}
        return {"job": job, "cycles": [], "stop_reason": "clean"}

    monkeypatch.setattr(orchestration, "run_job_repair_cycles", run_cycles)
    result = retry_failed_job(job.id)

    assert captured["issue"]["target_node_id"] == "n_video"
    assert captured["issue"]["observed"] == {
        "problem_key": "motion_deformation",
        "error_code": "ANIMATOR_FAILED",
    }
    assert captured["router"]["max_cycles"] == 1
    assert captured["router"]["workflow"] is workflow
    assert result["issue_id"] == "iss_TEST01"
