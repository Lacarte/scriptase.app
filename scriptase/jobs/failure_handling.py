"""Job-scoped failure presentation, targeted retry, and advisories (step 4.5)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from scriptase.engine.execution import execution_manager
from scriptase.engine.persistence import load_execution
from scriptase.jobs.models import Job
from scriptase.jobs.stage_projection import project_stages
from scriptase.review.policy import OWNERSHIP_TABLE, PROBLEM_RENDER_CODEC


_LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese",
    "ko": "Korean", "zh": "Chinese", "ar": "Arabic", "hi": "Hindi",
}
_MARKERS = {
    "en": {"the", "and", "this", "that", "with", "from", "your", "you", "is", "are"},
    "es": {"el", "la", "los", "las", "que", "por", "para", "una", "como", "pero", "del"},
    "fr": {"le", "la", "les", "des", "une", "que", "pour", "avec", "mais", "est"},
    "de": {"der", "die", "das", "und", "ist", "mit", "für", "nicht", "ein", "eine"},
    "it": {"il", "lo", "la", "gli", "che", "per", "con", "una", "non", "del"},
    "pt": {"o", "a", "os", "as", "que", "para", "uma", "com", "não", "por"},
}


def _base_language(value: Any) -> str | None:
    text = str(value or "").strip().replace("_", "-").lower()
    return text.split("-", 1)[0] if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", text) else None


def detect_script_language(text: str) -> str | None:
    """Conservative, dependency-free detection; uncertainty produces no warning."""
    sample = str(text or "")[:12000]
    if not sample.strip():
        return None
    ranges = (
        ("ja", r"[\u3040-\u30ff]"), ("ko", r"[\uac00-\ud7af]"),
        ("zh", r"[\u4e00-\u9fff]"), ("ar", r"[\u0600-\u06ff]"),
        ("ru", r"[\u0400-\u04ff]"), ("hi", r"[\u0900-\u097f]"),
    )
    for language, pattern in ranges:
        if len(re.findall(pattern, sample)) >= 3:
            return language
    words = re.findall(r"[a-zà-ÿ]+", sample.lower())
    if len(words) < 4:
        return None
    scores = {lang: sum(word in markers for word in words) for lang, markers in _MARKERS.items()}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked or ranked[0][1] < 2 or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None
    return ranked[0][0]


def job_advisories(job: Job) -> list[dict[str, Any]]:
    channel_content = job.channel_snapshot.get("content")
    channel_language = _base_language(
        channel_content.get("language") if isinstance(channel_content, Mapping) else None
    )
    script_language = _base_language(job.source.language) or detect_script_language(
        job.source.pasted_script
    )
    if not channel_language or not script_language or channel_language == script_language:
        return []
    return [{
        "code": "LANGUAGE_MISMATCH",
        "severity": "warning",
        "message": (
            f"Script language is {_LANGUAGE_NAMES.get(script_language, script_language)}, "
            f"but the Channel language is {_LANGUAGE_NAMES.get(channel_language, channel_language)}."
        ),
        "script_language": script_language,
        "channel_language": channel_language,
        "blocking": False,
    }]


def load_job_execution(job: Job) -> dict[str, Any] | None:
    if not job.execution_id:
        return None
    handle = execution_manager.active.get(job.execution_id)
    if handle is not None:
        return handle.scheduler.record.to_dict()
    try:
        return load_execution(job.execution_id)
    except (FileNotFoundError, ValueError, OSError):
        return None


def execution_failure(execution: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(execution, Mapping):
        return None
    records = execution.get("nodes")
    workflow = execution.get("workflow_snapshot")
    if not isinstance(records, Mapping) or not isinstance(workflow, Mapping):
        return None
    failed_id = next((str(node_id) for node_id, record in records.items()
                      if isinstance(record, Mapping) and record.get("status") == "failed"), None)
    if not failed_id:
        return None
    record = records.get(failed_id) or {}
    error = record.get("error") if isinstance(record.get("error"), Mapping) else {}
    node = next((item for item in workflow.get("nodes", [])
                 if isinstance(item, Mapping) and str(item.get("id")) == failed_id), {})
    stage_key = None
    stage_label = None
    try:
        for stage in project_stages(workflow, execution=execution)["stages"]:
            if failed_id in stage.get("node_ids", []):
                stage_key, stage_label = stage.get("key"), stage.get("label")
                break
    except Exception:
        pass
    return {
        "node_id": failed_id,
        "node_type": str(node.get("type") or ""),
        "stage": stage_key,
        "stage_label": stage_label or stage_key or "Unknown stage",
        "code": str(error.get("code") or "EXECUTION_FAILED"),
        "message": str(error.get("message") or "The stage failed."),
        "recovery_suggestion": str(error.get("recovery_suggestion") or "Retry the failed scope."),
    }


def failure_problem_key(node_type: str) -> str:
    for row in OWNERSHIP_TABLE:
        if node_type in row.node_types:
            return row.problem_key
    return PROBLEM_RENDER_CODEC


def enrich_job_payload(job: Job, payload: dict[str, Any], *, execution=None) -> dict[str, Any]:
    payload["advisories"] = job_advisories(job)
    failure = execution_failure(
        execution
        if execution is not None
        else load_job_execution(job) if job.status == "failed" else None
    )
    if failure:
        payload["failure"] = failure
        payload["current_stage"] = failure["stage"]
    else:
        payload["failure"] = None
    return payload


def duplicate_job(job: Job) -> Job:
    from scriptase.jobs.store import create_job
    return create_job({
        "channel_id": job.channel_id,
        "workflow_id": job.workflow_id,
        "workflow_version": job.workflow_version,
        "execution_mode": job.execution_mode,
        "source": job.source.model_dump(mode="json"),
    })


def retry_failed_job(job_id: str, *, timeout: float = 600.0) -> dict[str, Any]:
    """Translate an execution failure into a structured, smallest-scope repair."""
    from scriptase.jobs.orchestration import run_job_repair_cycles
    from scriptase.jobs.store import JobTerminal, add_issue_ids, get_job
    from scriptase.review.store import create_open_issue, list_issues

    job = get_job(job_id)
    if job.status != "failed":
        raise JobTerminal(job.id, job.status)
    execution = load_job_execution(job)
    failure = execution_failure(execution)
    if not failure:
        raise ValueError("Failed Job has no failed node execution record")
    open_issues = list_issues(job_id=job.id, open_only=True)
    issue = next((item for item in open_issues if item.target_node_id == failure["node_id"]), None)
    if issue is None:
        problem_key = failure_problem_key(failure["node_type"])
        issue = create_open_issue(
            job_id=job.id,
            target_node_id=failure["node_id"],
            reason=failure["message"],
            severity="high",
            suggested_action="regenerate",
            repair_instruction=failure["recovery_suggestion"],
            check_id="execution_failure",
            observed={"problem_key": problem_key, "error_code": failure["code"]},
            expected={"node_status": "succeeded"},
        )
        add_issue_ids(job.id, [issue.id], allow_terminal=True)
    workflow = execution.get("workflow_snapshot") if isinstance(execution, Mapping) else None
    outcome = run_job_repair_cycles(
        job.id, workflow=workflow, timeout=timeout, max_cycles=1
    )
    return {**outcome, "failure": failure, "issue_id": issue.id}


__all__ = ["detect_script_language", "duplicate_job", "enrich_job_payload", "execution_failure", "job_advisories", "retry_failed_job"]
