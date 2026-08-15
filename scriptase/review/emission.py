"""Persist review findings as durable ReviewIssues — step 11.2.

Phase 7 built the ReviewIssue store and step 11.1 gave the `review` domain a
node, but the node only *reported*: its findings lived and died on the `issues`
port. This module is the write path. It takes the two shapes a review pass
produces — step-7.1 ``TechnicalIssue`` records and a review provider's
structured payload — and drives them through
:func:`scriptase.review.store.create_from_technical` and
:func:`scriptase.review.store.create_from_review_result`, then links the
resulting ids onto the owning Job.

Two rules the rest of Phase 11 depends on:

**Issues are Job-scoped.** ``ReviewIssue.job_id`` is what the stage projection
and the Repair Router both key on, so emission requires a real Job id. A canvas
run with no Job behind it reports on the port and writes nothing — a project id
smuggled into that field would persist findings no Job could ever find.

**Re-review reuses the open issue.** A repair cycle (step 11.3) reviews the same
scene again; creating a second document for the same defect each pass would
reset ``attempt_count`` and make ``max_repairs`` unenforceable — an unbounded
repair loop by construction. So a finding that matches an already-open issue on
(issue_type, check_id, scene, target node, target artifact) returns that issue
instead of creating a sibling. Closed issues never match: a defect that comes
back after being resolved is genuinely new.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from scriptase.review.models import (
    ReviewIssue,
    assert_structured_review_result,
    technical_to_draft,
)
from scriptase.review.store import (
    create_from_review_result,
    create_from_technical,
    list_issues,
)

# Identity of a finding, independent of the run that observed it. Severity,
# confidence, and reason are deliberately absent: the same defect re-measured
# with a slightly different confidence is still the same defect.
_IDENTITY_FIELDS = (
    "issue_type",
    "check_id",
    "scene_id",
    "target_node_id",
    "target_artifact_id",
)


def _field(item: Any, name: str) -> str:
    value = getattr(item, name, None)
    if value is None and isinstance(item, dict):
        value = item.get(name)
    return str(value or "").strip()


def issue_identity(item: Any) -> tuple[str, ...]:
    """Stable identity of a finding, shared by drafts and stored issues."""
    return tuple(_field(item, name) for name in _IDENTITY_FIELDS)


def _job_scoped(findings: Sequence[Any], job_id: str) -> list[Any]:
    """Fill the Job on findings that omit it, as ``create_from_review_result``
    does — a review provider is already invoked per Job and has no reason to
    repeat the id on every finding."""
    scoped: list[Any] = []
    for item in findings:
        if isinstance(item, dict) and not item.get("job_id"):
            scoped.append({**item, "job_id": job_id})
        else:
            scoped.append(item)
    return scoped


def _open_issue_index(job_id: str) -> dict[tuple[str, ...], ReviewIssue]:
    """Open issues already on record for this Job, keyed by identity.

    First match wins, and ``list_issues`` sorts newest-first, so a finding
    binds to the most recent open record of the same defect.
    """
    index: dict[tuple[str, ...], ReviewIssue] = {}
    for issue in list_issues(job_id=job_id, open_only=True):
        index.setdefault(issue_identity(issue), issue)
    return index


def emit_review_issues(
    job_id: str,
    *,
    technical: Sequence[Any] = (),
    semantic: Sequence[Any] = (),
    attach_to_job: bool = True,
) -> list[ReviewIssue]:
    """Persist a review pass and return every issue it now stands behind.

    ``technical`` takes ``TechnicalIssue`` records (or mappings with the same
    fields); ``semantic`` takes a review provider's structured findings, which
    are validated as structured issues before anything is written — free text
    is rejected at the boundary, not stored and filtered later.

    The return value includes reused open issues, so the caller sees the full
    set of live defects rather than only what this pass happened to create.
    """
    job_id = str(job_id or "").strip()
    if not job_id:
        raise ValueError("emit_review_issues requires the owning job_id")

    known = _open_issue_index(job_id)
    reused: list[ReviewIssue] = []

    fresh_technical: list[Any] = []
    for item in technical:
        existing = known.get(issue_identity(technical_to_draft(item, job_id=job_id)))
        if existing is None:
            fresh_technical.append(item)
        else:
            reused.append(existing)

    fresh_semantic: list[Any] = []
    semantic_drafts = (
        assert_structured_review_result(_job_scoped(semantic, job_id))
        if semantic
        else []
    )
    for draft in semantic_drafts:
        existing = known.get(issue_identity(draft))
        if existing is None:
            fresh_semantic.append(draft)
        else:
            reused.append(existing)

    created: list[ReviewIssue] = []
    if fresh_technical:
        created.extend(create_from_technical(job_id, fresh_technical))
    if fresh_semantic:
        created.extend(create_from_review_result(fresh_semantic, job_id=job_id))

    emitted = created + reused
    if attach_to_job and emitted:
        attach_issues_to_job(job_id, (issue.id for issue in emitted))
    return emitted


def attach_issues_to_job(job_id: str, issue_ids: Iterable[str]) -> None:
    """Link issue ids onto the Job so the stage projection can read them.

    Best-effort, exactly like the repair-history link: the ReviewIssue
    documents are already durable, and a missing or concurrently-deleted Job
    must not lose the finding itself.
    """
    ids = [str(issue_id).strip() for issue_id in issue_ids if str(issue_id).strip()]
    if not ids:
        return
    try:
        from scriptase.jobs.store import add_issue_ids

        add_issue_ids(job_id, ids, allow_terminal=True)
    except Exception:
        pass


__all__ = [
    "attach_issues_to_job",
    "emit_review_issues",
    "issue_identity",
]
