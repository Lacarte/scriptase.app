"""Job: one video-production run, plus the stage projection of its workflow.

Populated in steps 1.4, 1.5, and 2.2. A Job wraps ``execution_manager.start()``;
it does not become a node. Job status derives from the execution record rather
than being tracked separately, so the two can never disagree (wired at 1.5).

The ordered stage list is *computed from the graph* here on the backend — a
hardcoded step array in the frontend would silently diverge the first time a
branch is added.
"""

from scriptase.jobs.models import (
    EXECUTION_MODES,
    JOB_ID_RE,
    JOB_SCHEMA_VERSION,
    JOB_STATUSES,
    SOURCE_MODES,
    STATUS_REASON_CODES,
    TERMINAL_STATUSES,
    BudgetSpent,
    Job,
    JobDraft,
    JobSource,
    parse_draft,
    parse_job,
    validation_problems,
)
from scriptase.jobs.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.jobs.snapshot import (
    assert_snapshot_has_no_credentials,
    build_channel_snapshot,
    snapshot_contains_credentials,
)
from scriptase.jobs.store import (
    JobNotFound,
    JobTerminal,
    JobValidationError,
    add_artifact_ids,
    create_job,
    default_draft,
    delete_job,
    get_job,
    job_summary,
    list_jobs,
    update_job,
)

__all__ = [
    "EXECUTION_MODES",
    "JOB_ID_RE",
    "JOB_SCHEMA_VERSION",
    "JOB_STATUSES",
    "SCHEMA_VERSION",
    "SOURCE_MODES",
    "STATUS_REASON_CODES",
    "TERMINAL_STATUSES",
    "BudgetSpent",
    "Job",
    "JobDraft",
    "JobNotFound",
    "JobSource",
    "JobTerminal",
    "JobValidationError",
    "add_artifact_ids",
    "apply_migrations",
    "assert_snapshot_has_no_credentials",
    "build_channel_snapshot",
    "create_job",
    "default_draft",
    "delete_job",
    "get_job",
    "job_summary",
    "list_jobs",
    "parse_draft",
    "parse_job",
    "snapshot_contains_credentials",
    "update_job",
    "validation_problems",
]
