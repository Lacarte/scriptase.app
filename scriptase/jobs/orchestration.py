"""Job orchestration over the ported workflow engine.

A Job wraps ``execution_manager.start()``; it is **not** a node and never
appears in the node registry (contracts.md §6 / product §19). Channel defaults
reach node configuration through the ported ``inherited_config()`` precedence
— explicit node config beats inherited channel config, and an empty string is
not explicit. Job status is always derived from the linked execution record so
the two cannot disagree.
"""

from __future__ import annotations

import os
import threading
from copy import deepcopy
from typing import Any, Mapping

from scriptase.artifacts.store import register_artifact
from scriptase.engine.execution import ExecutionManager, ExecutionRequestError, execution_manager
from scriptase.engine.persistence import load_execution, load_workflow
from scriptase.engine.registry import get_node_type
from scriptase.jobs.channel_settings import (
    channel_settings_from_snapshot,
    merge_node_config_with_channel,
    merge_setup_config_with_channel,
    script_text_from_source,
)
from scriptase.jobs.models import TERMINAL_STATUSES, Job
from scriptase.jobs.store import (
    JobNotFound,
    JobTerminal,
    JobValidationError,
    add_artifact_ids,
    get_job,
    update_job,
)
from scriptase.shared.io_utils import now_iso

# Execution-record status → Job status (contracts.md §6).
# ``partial`` is a successful terminal run with some skipped nodes.
# ``cancelling`` is still in flight — surface as ``running``.
_EXECUTION_TO_JOB_STATUS: dict[str, str] = {
    "queued": "queued",
    "running": "running",
    "cancelling": "running",
    "succeeded": "completed",
    "partial": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}

# Relative-path prefix → Artifact kind for harvesting engine artifact_refs.
_KIND_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("exports/", "export"),
    ("stories/", "script"),
    ("tts/", "audio"),
    ("alignments/", "alignment"),
    ("segmenters/", "segments"),
    ("scenes/", "scene_spec"),
    ("storyboard/", "image"),
    ("animator/", "video"),
    ("captions/", "captions"),
    ("musics/", "music"),
    ("projects/", "timeline"),
)

# Channel creative defaults seed only the project.setup node. Downstream
# stages receive them as the settings port and merge via inherited_config at
# adapter runtime — writing free-form channel keys into every node config
# would fail schema validation (unknown fields / option allowlists).
# project.setup also re-reads extensions.channel_settings at runtime (1.7).
_SETUP_NODE_TYPE = "project.setup"
_SCRIPT_INPUT_TYPE = "script.input"
_STORY_GENERATE_TYPE = "story.generate"


class JobOrchestrationError(RuntimeError):
    """Orchestration refused to start or sync a Job."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


def derive_job_status(execution_status: str | None) -> str:
    """Map an execution-record status onto the Job status vocabulary.

    Unknown or missing statuses stay ``queued`` so a half-written link cannot
    invent a terminal state the execution does not have.
    """
    if not execution_status:
        return "queued"
    return _EXECUTION_TO_JOB_STATUS.get(str(execution_status).strip(), "queued")


def kind_for_artifact_ref(ref: str) -> str | None:
    """Infer an Artifact kind from a managed relative ref, or None if unknown."""
    text = str(ref or "").replace("\\", "/").lstrip("/")
    if text.startswith("output/"):
        text = text[7:]
    for prefix, kind in _KIND_BY_PREFIX:
        if text.startswith(prefix):
            return kind
    return None


def prepare_workflow_for_job(
    job: Job,
    workflow: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a workflow snapshot ready for ``execution_manager.start()``.

    * Channel defaults merge into seeded node configurations via
      ``inherited_config`` (explicit wins; empty is not explicit).
    * Job source text fills ``script.input`` when that node's text is empty.
    * ``template_id`` and other non-document keys are stripped.
    * The Job's ``workflow_id`` is stamped when present so the execution
      record links back to the saved workflow.
    """
    if not isinstance(workflow, Mapping):
        raise JobOrchestrationError("WORKFLOW_INVALID", "workflow must be an object")

    document = deepcopy(dict(workflow))
    document.pop("template_id", None)

    if job.workflow_id and not document.get("workflow_id"):
        document["workflow_id"] = job.workflow_id

    channel_settings = channel_settings_from_snapshot(job.channel_snapshot)
    source_payload = (
        job.source.model_dump(mode="json")
        if hasattr(job.source, "model_dump")
        else dict(job.source or {})
    )
    script_text = script_text_from_source(source_payload)

    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        raise JobOrchestrationError("WORKFLOW_INVALID", "workflow.nodes must be an array")

    prepared_nodes: list[dict[str, Any]] = []
    for raw_node in nodes:
        if not isinstance(raw_node, Mapping):
            continue
        node = deepcopy(dict(raw_node))
        node_type = str(node.get("type") or "")
        config = dict(node.get("configuration") or {})

        if node_type == _SETUP_NODE_TYPE and channel_settings:
            # Same merge the adapter applies at runtime: empty fields + logo
            # package yield to the channel; explicit non-empty wins.
            # Schema-filter so unknown channel keys never reach validation.
            allowed = _config_field_names(_SETUP_NODE_TYPE)
            merged = merge_setup_config_with_channel(config, channel_settings)
            config = {key: value for key, value in merged.items() if key in allowed}

        if node_type == _SCRIPT_INPUT_TYPE and script_text:
            config = merge_node_config_with_channel(config, {"text": script_text})

        if node_type == _STORY_GENERATE_TYPE:
            # Only schema-known story keys; idea/topic may be free-form strings
            # on some providers via provider_options later — keep prepare strict.
            story_seed = _story_seed_from_source(source_payload, channel_settings)
            if story_seed:
                config = merge_node_config_with_channel(
                    config,
                    story_seed,
                    aliases={"style": "preset_style", "tone": "story_tone"},
                )

        node["configuration"] = config
        prepared_nodes.append(node)

    document["nodes"] = prepared_nodes

    # Carry Job identity + the flat channel settings blob so project.setup
    # (and any future readers) can re-merge at runtime. Extensions are ignored
    # by scheduler control-flow (contracts.md §1.4) and never hold secrets.
    extensions = dict(document.get("extensions") or {})
    extensions["job_id"] = job.id
    extensions["channel_id"] = job.channel_id
    extensions["execution_mode"] = job.execution_mode
    if channel_settings:
        extensions["channel_settings"] = channel_settings
    document["extensions"] = extensions

    return document


def _story_seed_from_source(
    source: Mapping[str, Any],
    channel_settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Schema-filtered defaults for story.generate from Job source + channel."""
    allowed = _config_field_names(_STORY_GENERATE_TYPE)
    seed: dict[str, Any] = {}
    for key in ("tone", "style", "story_tone", "preset_style", "story_category", "language", "duration"):
        if key in channel_settings and key in allowed:
            seed[key] = channel_settings[key]
        # Aliases: channel tone/style → story field names when those are allowed.
        if key == "story_tone" and "story_tone" in allowed and "tone" in channel_settings:
            seed.setdefault("story_tone", channel_settings["tone"])
        if key == "preset_style" and "preset_style" in allowed and "style" in channel_settings:
            seed.setdefault("preset_style", channel_settings["style"])
    return seed


def _config_field_names(node_type: str) -> set[str]:
    definition = get_node_type(node_type) or {}
    return {
        str(field.get("name"))
        for field in definition.get("config_schema") or []
        if isinstance(field, Mapping) and field.get("name")
    }


def load_job_workflow(job: Job) -> dict[str, Any]:
    """Load the saved workflow document the Job points at."""
    workflow_id = job.workflow_id
    if not workflow_id:
        raise JobOrchestrationError(
            "WORKFLOW_REQUIRED",
            "Job has no workflow_id; set one or give the Channel a default_workflow_id",
        )
    try:
        return load_workflow(workflow_id)
    except FileNotFoundError as exc:
        raise JobOrchestrationError(
            "WORKFLOW_NOT_FOUND",
            f"Workflow {workflow_id} not found",
            details={"workflow_id": workflow_id},
        ) from exc


def start_job(
    job_id: str,
    *,
    manager: ExecutionManager | None = None,
    project_id: str | None = None,
    force: bool = False,
    wait: bool = False,
    timeout: float = 120.0,
    workflow: Mapping[str, Any] | None = None,
) -> Job:
    """Start the Job's workflow through the ported execution manager.

    The Job does not become a node. It records ``execution_id`` and then
    derives status from that execution. When ``wait`` is True the call blocks
    until the run finishes (or ``timeout`` elapses) and harvests artifacts.
    """
    job = get_job(job_id)
    if job.status in TERMINAL_STATUSES:
        raise JobTerminal(job.id, job.status)
    if job.execution_id and job.status == "running":
        raise JobOrchestrationError(
            "JOB_ALREADY_RUNNING",
            f"Job {job.id} is already linked to execution {job.execution_id}",
            details={"execution_id": job.execution_id},
        )

    source_workflow = workflow if workflow is not None else load_job_workflow(job)
    prepared = prepare_workflow_for_job(job, source_workflow)

    active_manager = manager or execution_manager
    try:
        execution_id, resolved_project = active_manager.start(
            prepared,
            run_mode="full",
            target_node_ids=[],
            project_id=project_id,
            force=force,
            source="manual",
        )
    except ExecutionRequestError as exc:
        raise JobOrchestrationError(exc.code, str(exc), details=exc.details) from exc

    started_at = now_iso()
    job = update_job(
        job.id,
        status=derive_job_status("queued"),
        execution_id=execution_id,
        started_at=started_at,
        status_reason=None,
        current_stage=None,
    )

    if wait:
        _wait_for_execution(active_manager, execution_id, timeout=timeout)
        return sync_job_from_execution(job.id, manager=active_manager)

    # Async path: finalize status + artifacts when the project worker finishes.
    thread = threading.Thread(
        target=_finalize_job_async,
        args=(job.id, execution_id, active_manager),
        name=f"job-finalize-{job.id}",
        daemon=True,
    )
    thread.start()
    return job


def sync_job_from_execution(
    job_id: str,
    *,
    manager: ExecutionManager | None = None,
    execution: Mapping[str, Any] | None = None,
) -> Job:
    """Refresh Job status (and artifacts) from the linked execution record.

    Status is **always** taken from the execution record — never invented
    independently — so Job and execution cannot disagree.
    """
    job = get_job(job_id)
    execution_id = job.execution_id
    if execution is None:
        if not execution_id:
            return job
        execution = _load_execution_record(execution_id, manager=manager)
    if execution is None:
        return job

    exec_status = str(execution.get("status") or "")
    job_status = derive_job_status(exec_status)

    started_at = execution.get("started_at") or job.started_at
    finished_at = execution.get("finished_at")
    completed_at = finished_at if job_status in TERMINAL_STATUSES else job.completed_at

    # Harvest artifact refs while we have the record.
    artifact_ids = _harvest_artifacts(job, execution)

    updates: dict[str, Any] = {
        "status": job_status,
        "execution_id": execution.get("execution_id") or execution_id,
        "started_at": started_at,
        "allow_terminal": job.status in TERMINAL_STATUSES,
    }
    if job_status in TERMINAL_STATUSES:
        updates["completed_at"] = completed_at or now_iso()

    try:
        job = update_job(job.id, **updates)
    except JobTerminal:
        # Race: another finalizer already flipped the Job. Re-read and continue
        # with artifact merge under allow_terminal.
        job = get_job(job_id)

    if artifact_ids:
        job = add_artifact_ids(job.id, artifact_ids, allow_terminal=True)

    # If we transitioned into terminal from a non-terminal store state, ensure
    # completed_at is set even when update_job rejected mid-race.
    reloaded = get_job(job_id)
    if job_status in TERMINAL_STATUSES and (
        reloaded.status != job_status or not reloaded.completed_at
    ):
        reloaded = update_job(
            reloaded.id,
            status=job_status,
            completed_at=completed_at or reloaded.completed_at or now_iso(),
            allow_terminal=True,
        )
    return reloaded


def wait_for_job(
    job_id: str,
    *,
    manager: ExecutionManager | None = None,
    timeout: float = 120.0,
) -> Job:
    """Block until the Job's execution finishes, then sync status/artifacts."""
    job = get_job(job_id)
    if not job.execution_id:
        raise JobOrchestrationError("JOB_NOT_STARTED", f"Job {job_id} has no execution_id")
    active_manager = manager or execution_manager
    _wait_for_execution(active_manager, job.execution_id, timeout=timeout)
    return sync_job_from_execution(job.id, manager=active_manager)


def collect_execution_artifact_refs(execution: Mapping[str, Any]) -> list[str]:
    """Stable-order list of managed artifact refs from an execution record."""
    nodes = execution.get("nodes") if isinstance(execution.get("nodes"), Mapping) else {}
    seen: set[str] = set()
    refs: list[str] = []
    # Deterministic order: sorted node ids, then ref order within each node.
    for node_id in sorted(nodes):
        record = nodes[node_id]
        if not isinstance(record, Mapping):
            continue
        for ref in record.get("artifact_refs") or []:
            text = str(ref or "").replace("\\", "/").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            refs.append(text)
    return refs


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _wait_for_execution(
    manager: ExecutionManager,
    execution_id: str,
    *,
    timeout: float,
) -> None:
    handle = manager.active.get(execution_id)
    if handle is None:
        return
    thread = handle.thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise JobOrchestrationError(
                "JOB_TIMEOUT",
                f"Execution {execution_id} did not finish within {timeout}s",
                details={"execution_id": execution_id},
            )


def _finalize_job_async(
    job_id: str,
    execution_id: str,
    manager: ExecutionManager,
) -> None:
    try:
        _wait_for_execution(manager, execution_id, timeout=3600.0)
        sync_job_from_execution(job_id, manager=manager)
    except Exception:
        # Finalization is best-effort; a failed sync must not crash the worker.
        # The Job remains linked to the execution and can be re-synced later.
        try:
            sync_job_from_execution(job_id, manager=manager)
        except Exception:
            pass


def _load_execution_record(
    execution_id: str,
    *,
    manager: ExecutionManager | None,
) -> dict[str, Any] | None:
    # Prefer the live scheduler record when the manager still holds it.
    if manager is not None:
        handle = manager.active.get(execution_id)
        if handle is not None:
            return handle.scheduler.record.to_dict()
        try:
            return load_execution(execution_id, root=manager.execution_root)
        except FileNotFoundError:
            pass
    try:
        return load_execution(execution_id)
    except FileNotFoundError:
        return None


def _harvest_artifacts(job: Job, execution: Mapping[str, Any]) -> list[str]:
    """Register engine artifact_refs as typed Artifacts owned by this Job.

    Registration is best-effort: a missing file or unknown kind skips that
    ref rather than failing the whole Job sync. Already-known refs (same path
    already on the Job) are not re-registered.
    """
    refs = collect_execution_artifact_refs(execution)
    if not refs:
        return []

    existing = set(job.artifacts)
    # Paths already indexed for this job — avoid duplicate versions on re-sync.
    known_paths = _known_job_paths(job)

    registered_ids: list[str] = []
    provenance = execution.get("execution_id") or job.execution_id
    for ref in refs:
        kind = kind_for_artifact_ref(ref)
        if kind is None:
            continue
        normalized = ref.replace("\\", "/").lstrip("/")
        if normalized.startswith("output/"):
            normalized = normalized[7:]
        if normalized in known_paths:
            continue
        try:
            artifact = register_artifact(
                job_id=job.id,
                kind=kind,
                path=normalized,
                provenance_ref=str(provenance) if provenance else None,
                from_sample_data=False,
            )
        except Exception:
            continue
        if artifact.id not in existing:
            registered_ids.append(artifact.id)
            existing.add(artifact.id)
            known_paths.add(normalized)
    return registered_ids


def _known_job_paths(job: Job) -> set[str]:
    paths: set[str] = set()
    if not job.artifacts:
        return paths
    try:
        from scriptase.artifacts.store import get_artifact
    except ImportError:
        return paths
    for artifact_id in job.artifacts:
        try:
            artifact = get_artifact(artifact_id)
        except Exception:
            continue
        paths.add(artifact.path)
    return paths


# Guard: Job must never be registered as a node type.
def assert_job_is_not_a_node() -> None:
    """Hard check used by tests: Job is orchestration, not a registry entry."""
    for key in ("job", "job.run", "jobs.orchestrate", "scriptase.job"):
        if get_node_type(key) is not None:
            raise RuntimeError(f"Job must not appear in the node registry as {key!r}")


__all__ = [
    "JobOrchestrationError",
    "assert_job_is_not_a_node",
    "collect_execution_artifact_refs",
    "derive_job_status",
    "kind_for_artifact_ref",
    "load_job_workflow",
    "prepare_workflow_for_job",
    "start_job",
    "sync_job_from_execution",
    "wait_for_job",
]
