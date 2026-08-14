"""Job: one video-production run, plus the stage projection of its workflow.

Populated in steps 1.4, 1.5, and 2.2. A Job wraps ``execution_manager.start()``;
it does not become a node. Job status derives from the execution record rather
than being tracked separately, so the two can never disagree (wired at 1.5).

The ordered stage list is *computed from the graph* here on the backend — a
hardcoded step array in the frontend would silently diverge the first time a
branch is added.
"""

from scriptase.jobs.channel_settings import (
    channel_settings_from_snapshot,
    merge_node_config_with_channel,
    merge_setup_config_with_channel,
    resolve_channel_settings,
    script_text_from_source,
    setup_seed_from_channel_settings,
)
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
from scriptase.jobs.orchestration import (
    JobOrchestrationError,
    assert_job_is_not_a_node,
    collect_execution_artifact_refs,
    derive_job_status,
    kind_for_artifact_ref,
    load_job_workflow,
    prepare_workflow_for_job,
    start_job,
    sync_job_from_execution,
    wait_for_job,
)
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
from scriptase.jobs.stage_projection import (
    STAGE_CATALOG,
    STAGE_KEYS,
    StageProjectionError,
    assign_nodes_to_stages,
    default_stage_labels,
    project_stages,
    project_workflow_stages,
    stage_projection_summary,
)


# Lazy blueprint export so importing this package never pulls Flask routes.
def __getattr__(name: str):
    if name == "jobs_bp":
        from scriptase.jobs.routes import jobs_bp

        return jobs_bp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    "JobOrchestrationError",
    "JobSource",
    "JobTerminal",
    "JobValidationError",
    "STAGE_CATALOG",
    "STAGE_KEYS",
    "StageProjectionError",
    "add_artifact_ids",
    "apply_migrations",
    "assert_job_is_not_a_node",
    "assert_snapshot_has_no_credentials",
    "assign_nodes_to_stages",
    "build_channel_snapshot",
    "channel_settings_from_snapshot",
    "collect_execution_artifact_refs",
    "create_job",
    "default_draft",
    "default_stage_labels",
    "delete_job",
    "derive_job_status",
    "get_job",
    "job_summary",
    "jobs_bp",
    "kind_for_artifact_ref",
    "list_jobs",
    "load_job_workflow",
    "merge_node_config_with_channel",
    "merge_setup_config_with_channel",
    "parse_draft",
    "parse_job",
    "project_stages",
    "project_workflow_stages",
    "resolve_channel_settings",
    "setup_seed_from_channel_settings",
    "prepare_workflow_for_job",
    "script_text_from_source",
    "snapshot_contains_credentials",
    "stage_projection_summary",
    "start_job",
    "sync_job_from_execution",
    "update_job",
    "validation_problems",
    "wait_for_job",
]
