"""Channel-driven trigger enqueue: create Jobs rather than raw executions.

Step 9.2. Schedule, watch-folder, and webhook fires (and Channel content
cadence) create a Job, start it through the Job orchestrator, and stamp the
queue/execution ``source`` as ``schedule`` / ``watch`` / ``webhook``.

Workflow-level triggers resolve ``channel_id`` from the firing schedule entry,
``settings.watch_folder.channel_id``, ``settings.webhook.channel_id``, or a
workflow-wide ``settings.channel_id``. When no channel is bound, the legacy
raw-execution path is retained so pre-9.2 workflow schedules still fire.
"""

from __future__ import annotations

from typing import Any, Mapping

from scriptase.channels.models import ChannelProfile
from scriptase.channels.store import ChannelNotFound, get_channel
from scriptase.engine.execution import ExecutionManager, execution_manager
from scriptase.engine.watch_folders import watch_run_payload
from scriptase.jobs.models import Job
from scriptase.jobs.orchestration import JobOrchestrationError, start_job
from scriptase.jobs.store import JobValidationError, create_job, default_draft

TRIGGER_SOURCES = frozenset({"schedule", "watch", "webhook"})


class TriggerEnqueueError(RuntimeError):
    """A trigger refused to create or start a Job."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def _strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_trigger_channel_id(
    workflow: Mapping[str, Any],
    *,
    schedule: Mapping[str, Any] | None = None,
    settings_block: Mapping[str, Any] | None = None,
) -> str | None:
    """Resolve the Channel a workflow trigger should create a Job for."""
    if schedule and isinstance(schedule, Mapping):
        channel_id = _strip(schedule.get("channel_id"))
        if channel_id:
            return channel_id
    if settings_block and isinstance(settings_block, Mapping):
        channel_id = _strip(settings_block.get("channel_id"))
        if channel_id:
            return channel_id
    settings = workflow.get("settings") if isinstance(workflow, Mapping) else None
    if isinstance(settings, Mapping):
        channel_id = _strip(settings.get("channel_id"))
        if channel_id:
            return channel_id
    return None


def cadence_source_payload(channel: ChannelProfile | Mapping[str, Any]) -> dict[str, Any]:
    """Build a Job ``source`` dict from a Channel's content cadence (or defaults)."""
    if isinstance(channel, ChannelProfile):
        cadence = channel.cadence
        source = cadence.source.model_dump(mode="json") if cadence else {}
        content = channel.content
        niche = content.niche if content else ""
        name = channel.name
    else:
        cadence = channel.get("cadence") if isinstance(channel, Mapping) else None
        if isinstance(cadence, Mapping):
            raw_source = cadence.get("source")
            source = dict(raw_source) if isinstance(raw_source, Mapping) else {}
        else:
            source = {}
        content = channel.get("content") if isinstance(channel, Mapping) else {}
        niche = ""
        if isinstance(content, Mapping):
            niche = _strip(content.get("niche"))
        name = _strip(channel.get("name")) if isinstance(channel, Mapping) else ""

    mode = _strip(source.get("mode")) or "topic"
    payload = {
        "mode": mode,
        "topic": _strip(source.get("topic")),
        "idea": _strip(source.get("idea")),
        "pasted_script": _strip(source.get("pasted_script")),
        "references": list(source.get("references") or []),
    }
    # Unattended topic/automatic runs need a non-empty seed when the Channel
    # cadence left topic blank — fall back to niche / name so create_job
    # validation can pass for schedule fires.
    if mode in {"topic", "automatic"} and not payload["topic"] and not payload["idea"]:
        payload["topic"] = niche or name or "Scheduled run"
    if mode == "idea" and not payload["idea"] and not payload["topic"]:
        payload["idea"] = niche or name or "Scheduled run"
    return payload


def create_triggered_job(
    *,
    channel_id: str,
    trigger_source: str,
    execution_mode: str | None = None,
    source: Mapping[str, Any] | None = None,
    workflow_id: str | None = None,
) -> Job:
    """Create a queued Job for a trigger fire (does not start execution)."""
    if trigger_source not in TRIGGER_SOURCES:
        raise TriggerEnqueueError(
            "BAD_REQUEST",
            f"trigger source must be one of: {', '.join(sorted(TRIGGER_SOURCES))}",
        )
    try:
        channel = get_channel(channel_id)
    except ChannelNotFound as exc:
        raise TriggerEnqueueError(
            "CHANNEL_NOT_FOUND",
            f"channel not found: {channel_id}",
            details={"channel_id": channel_id},
        ) from exc

    if execution_mode is None:
        cadence = channel.cadence
        execution_mode = cadence.execution_mode if cadence else "automatic"
    if not execution_mode:
        execution_mode = "automatic"

    source_payload = dict(source) if source else cadence_source_payload(channel)
    draft = default_draft(
        channel_id=channel.id,
        execution_mode=execution_mode,
        source=source_payload,
        workflow_id=workflow_id or channel.default_workflow_id,
    )
    try:
        return create_job(draft)
    except JobValidationError as exc:
        raise TriggerEnqueueError(
            "JOB_INVALID",
            "Triggered Job draft failed validation",
            details=exc.problems,
        ) from exc


def start_triggered_job(
    job: Job | str,
    *,
    trigger_source: str,
    manager: ExecutionManager | None = None,
    workflow: Mapping[str, Any] | None = None,
    input_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    wait: bool = False,
    timeout: float = 120.0,
    force: bool = False,
    project_id: str | None = None,
) -> Job:
    """Start a Job created by a trigger, stamping the queue source."""
    if trigger_source not in TRIGGER_SOURCES:
        raise TriggerEnqueueError(
            "BAD_REQUEST",
            f"trigger source must be one of: {', '.join(sorted(TRIGGER_SOURCES))}",
        )
    job_id = job.id if isinstance(job, Job) else str(job)
    try:
        return start_job(
            job_id,
            manager=manager,
            workflow=workflow,
            project_id=project_id,
            force=force,
            wait=wait,
            timeout=timeout,
            source=trigger_source,
            input_overrides=input_overrides,
        )
    except JobOrchestrationError as exc:
        raise TriggerEnqueueError(exc.code, str(exc), details=exc.details) from exc


def create_and_start_triggered_job(
    *,
    channel_id: str,
    trigger_source: str,
    execution_mode: str | None = None,
    source: Mapping[str, Any] | None = None,
    workflow_id: str | None = None,
    workflow: Mapping[str, Any] | None = None,
    input_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    manager: ExecutionManager | None = None,
    wait: bool = False,
    timeout: float = 120.0,
    force: bool = False,
    project_id: str | None = None,
) -> Job:
    """Create a Job for a trigger and start it unattended."""
    job = create_triggered_job(
        channel_id=channel_id,
        trigger_source=trigger_source,
        execution_mode=execution_mode,
        source=source,
        workflow_id=workflow_id
        or (workflow.get("workflow_id") if isinstance(workflow, Mapping) else None),
    )
    return start_triggered_job(
        job,
        trigger_source=trigger_source,
        manager=manager,
        workflow=workflow,
        input_overrides=input_overrides,
        wait=wait,
        timeout=timeout,
        force=force,
        project_id=project_id,
    )


def enqueue_scheduled_workflow(
    workflow: Mapping[str, Any],
    schedule: Mapping[str, Any] | None = None,
    *,
    manager: ExecutionManager | None = None,
) -> Any:
    """Default schedule enqueue: Job when channel-bound, else raw execution."""
    channel_id = resolve_trigger_channel_id(workflow, schedule=schedule)
    if not channel_id:
        active = manager or execution_manager
        return active.start(
            workflow, run_mode="full", target_node_ids=[], source="schedule"
        )
    job = create_and_start_triggered_job(
        channel_id=channel_id,
        trigger_source="schedule",
        workflow_id=_strip(workflow.get("workflow_id")),
        workflow=workflow,
        manager=manager,
    )
    return {
        "job_id": job.id,
        "execution_id": job.execution_id,
        "status": job.status,
        "source": "schedule",
    }


def enqueue_watch_workflow(
    workflow: Mapping[str, Any],
    content: str,
    settings: Mapping[str, Any],
    *,
    manager: ExecutionManager | None = None,
) -> Any:
    """Default watch-folder enqueue: Job when channel-bound, else raw execution."""
    channel_id = resolve_trigger_channel_id(workflow, settings_block=settings)
    snapshot, overrides = watch_run_payload(workflow, content, settings)
    if not channel_id:
        active = manager or execution_manager
        return active.start(
            snapshot,
            run_mode="full",
            target_node_ids=[],
            source="watch",
            input_overrides=overrides,
        )
    # Prefer paste-mode Job source so prepare_workflow_for_job seeds script.input.
    source = {
        "mode": "paste",
        "pasted_script": content,
        "topic": "",
        "idea": "",
        "references": [],
    }
    job = create_and_start_triggered_job(
        channel_id=channel_id,
        trigger_source="watch",
        source=source,
        workflow_id=_strip(workflow.get("workflow_id")),
        workflow=snapshot,
        input_overrides=overrides or None,
        manager=manager,
    )
    return {
        "job_id": job.id,
        "execution_id": job.execution_id,
        "status": job.status,
        "source": "watch",
    }


def enqueue_webhook_workflow(
    workflow: Mapping[str, Any],
    overrides: Mapping[str, Mapping[str, Any]],
    *,
    manager: ExecutionManager | None = None,
) -> Any:
    """Default webhook enqueue: Job when channel-bound, else raw execution."""
    settings = (workflow.get("settings") or {}).get("webhook") or {}
    channel_id = resolve_trigger_channel_id(workflow, settings_block=settings)
    if not channel_id:
        active = manager or execution_manager
        return active.start(
            workflow,
            run_mode="full",
            target_node_ids=[],
            source="webhook",
            input_overrides=overrides,
        )
    # Webhook payloads map onto ports; use automatic source seed from cadence
    # when the channel has one, else a minimal automatic source.
    try:
        channel = get_channel(channel_id)
        source = cadence_source_payload(channel)
        execution_mode = channel.cadence.execution_mode if channel.cadence else "automatic"
    except ChannelNotFound:
        source = {"mode": "automatic", "topic": "Webhook run"}
        execution_mode = "automatic"
    job = create_and_start_triggered_job(
        channel_id=channel_id,
        trigger_source="webhook",
        execution_mode=execution_mode,
        source=source,
        workflow_id=_strip(workflow.get("workflow_id")),
        workflow=workflow,
        input_overrides=overrides,
        manager=manager,
    )
    return {
        "job_id": job.id,
        "execution_id": job.execution_id,
        "status": job.status,
        "source": "webhook",
        "project_id": None,
    }


def create_job_from_channel_cadence(
    channel: ChannelProfile | Mapping[str, Any],
    *,
    manager: ExecutionManager | None = None,
    workflow: Mapping[str, Any] | None = None,
    wait: bool = False,
    timeout: float = 120.0,
    force: bool = False,
    project_id: str | None = None,
) -> Job:
    """Create and start a Job for one Channel cadence fire."""
    if isinstance(channel, ChannelProfile):
        channel_id = channel.id
        workflow_id = channel.default_workflow_id
        execution_mode = channel.cadence.execution_mode
        source = cadence_source_payload(channel)
    else:
        channel_id = _strip(channel.get("id"))
        workflow_id = _strip(channel.get("default_workflow_id")) or None
        cadence = channel.get("cadence") if isinstance(channel.get("cadence"), Mapping) else {}
        execution_mode = _strip(cadence.get("execution_mode")) or "automatic"
        source = cadence_source_payload(channel)

    if not channel_id:
        raise TriggerEnqueueError("CHANNEL_REQUIRED", "Channel cadence fire needs a channel id")
    if not workflow_id and workflow is None:
        raise TriggerEnqueueError(
            "WORKFLOW_REQUIRED",
            "Channel cadence requires default_workflow_id (or an explicit workflow)",
            details={"channel_id": channel_id},
        )

    return create_and_start_triggered_job(
        channel_id=channel_id,
        trigger_source="schedule",
        execution_mode=execution_mode,
        source=source,
        workflow_id=workflow_id,
        workflow=workflow,
        manager=manager,
        wait=wait,
        timeout=timeout,
        force=force,
        project_id=project_id,
    )


__all__ = [
    "TRIGGER_SOURCES",
    "TriggerEnqueueError",
    "resolve_trigger_channel_id",
    "cadence_source_payload",
    "create_triggered_job",
    "start_triggered_job",
    "create_and_start_triggered_job",
    "enqueue_scheduled_workflow",
    "enqueue_watch_workflow",
    "enqueue_webhook_workflow",
    "create_job_from_channel_cadence",
]
