"""Job Pydantic models — contracts.md §6 / product §15.2.

A Job is one video-production run using a Channel and a Workflow. It is an
orchestration context, not a media node and never appears in the node registry.

``channel_snapshot`` captures non-secret Channel configuration and provider
**instance references** only. Secrets resolve from the provider instance at
runtime and never enter a Job document.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Server-generated job id: job_ + 6 uppercase alphanumerics
# (matches channel / workflow / artifact id style in contracts.md).
JOB_ID_RE = re.compile(r"^job_[A-Z0-9]{6}$")

# Schema version of the on-disk document format (migrations.py).
JOB_SCHEMA_VERSION = 1

# contracts.md §6 status vocabulary.
# ``paused`` is not a member — use ``awaiting_approval`` + ``status_reason``.
JobStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
]

JOB_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "cancelled",
)

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# contracts.md §6 execution_mode.
ExecutionMode = Literal["manual", "assisted", "automatic"]

EXECUTION_MODES: tuple[str, ...] = ("manual", "assisted", "automatic")

# contracts.md §6 source.mode (Script stage).
SourceMode = Literal["automatic", "topic", "idea", "paste", "manual"]

SOURCE_MODES: tuple[str, ...] = ("automatic", "topic", "idea", "paste", "manual")

# Common status_reason codes (free text allowed; these are conventional).
STATUS_REASON_CODES: tuple[str, ...] = (
    "approval",
    "budget",
    "user_pause",
)


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: Any) -> str | None:
    text = _strip_str(value)
    return text or None


def _string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    return [_strip_str(item) for item in value if _strip_str(item)]


# ---------------------------------------------------------------------------
# Nested blocks
# ---------------------------------------------------------------------------


class JobSource(BaseModel):
    """Script-stage input for this Job.

    ``mode`` selects which of the content fields the Script stage consumes.
    ``references`` are managed asset ids or short labels — never filesystem paths.
    """

    model_config = ConfigDict(extra="forbid")

    mode: SourceMode = "topic"
    topic: str = ""
    idea: str = ""
    pasted_script: str = ""
    references: list[str] = Field(default_factory=list)

    @field_validator("mode", mode="before")
    @classmethod
    def _mode(cls, value: Any) -> str:
        text = _strip_str(value) or "topic"
        if text not in SOURCE_MODES:
            raise ValueError(
                f"source.mode must be one of: {', '.join(SOURCE_MODES)}"
            )
        return text

    @field_validator("topic", "idea", "pasted_script", mode="before")
    @classmethod
    def _strip_fields(cls, value: Any) -> str:
        return _strip_str(value)

    @field_validator("references", mode="before")
    @classmethod
    def _references(cls, value: Any) -> list[str]:
        return _string_list(value, field_name="references")


class BudgetSpent(BaseModel):
    """Running spend counters for this Job (contracts.md §6 / §12)."""

    model_config = ConfigDict(extra="forbid")

    generations: int = Field(default=0, ge=0)
    cost: float = Field(default=0.0, ge=0.0)

    @field_validator("generations", mode="before")
    @classmethod
    def _generations(cls, value: Any) -> int:
        if value is None:
            return 0
        return int(value)

    @field_validator("cost", mode="before")
    @classmethod
    def _cost(cls, value: Any) -> float:
        if value is None:
            return 0.0
        return float(value)


# ---------------------------------------------------------------------------
# Top-level document
# ---------------------------------------------------------------------------


class Job(BaseModel):
    """Persisted Job document (contracts.md §6).

    ``schema_version`` is the on-disk format revision (migrations.py). Content
    is not versioned the way Channels are — Jobs are run records; mutable
    runtime fields (status, artifacts, …) update in place under store locks.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: int = Field(default=JOB_SCHEMA_VERSION, ge=1)

    channel_id: str
    channel_snapshot: dict[str, Any] = Field(default_factory=dict)

    workflow_id: str | None = None
    workflow_version: int | None = Field(default=None, ge=1)

    execution_mode: ExecutionMode = "manual"
    source: JobSource = Field(default_factory=JobSource)

    status: JobStatus = "queued"
    status_reason: str | None = None
    current_stage: str | None = None

    artifacts: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    repair_history: list[str] = Field(default_factory=list)

    budget_spent: BudgetSpent = Field(default_factory=BudgetSpent)
    execution_id: str | None = None

    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not JOB_ID_RE.fullmatch(value):
            raise ValueError("id must match job_[A-Z0-9]{6}")
        return value

    @field_validator("channel_id", mode="before")
    @classmethod
    def _channel_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("channel_id is required")
        return text

    @field_validator("channel_snapshot", mode="before")
    @classmethod
    def _channel_snapshot(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("channel_snapshot must be an object")
        return value

    @field_validator("workflow_id", mode="before")
    @classmethod
    def _workflow_id(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("execution_mode", mode="before")
    @classmethod
    def _execution_mode(cls, value: Any) -> str:
        text = _strip_str(value) or "manual"
        if text not in EXECUTION_MODES:
            raise ValueError(
                f"execution_mode must be one of: {', '.join(EXECUTION_MODES)}"
            )
        return text

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: Any) -> str:
        text = _strip_str(value) or "queued"
        if text not in JOB_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(JOB_STATUSES)}"
            )
        return text

    @field_validator("status_reason", "current_stage", "execution_id", mode="before")
    @classmethod
    def _optional_text(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def _optional_timestamps(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("artifacts", "scenes", "issues", "repair_history", mode="before")
    @classmethod
    def _id_lists(cls, value: Any, info) -> list[str]:
        return _string_list(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _terminal_timestamps(self) -> Job:
        # Soft consistency only: terminal jobs may carry completed_at once
        # orchestration (1.5) sets it. No hard requirement at model level.
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def to_document(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for ``safe_json_write``."""
        return self.model_dump(mode="json")


class JobDraft(BaseModel):
    """Create payload: identity and snapshot are owned by the store."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str
    workflow_id: str | None = None
    workflow_version: int | None = Field(default=None, ge=1)
    execution_mode: ExecutionMode = "manual"
    source: JobSource = Field(default_factory=JobSource)

    @field_validator("channel_id", mode="before")
    @classmethod
    def _channel_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("channel_id is required")
        return text

    @field_validator("workflow_id", mode="before")
    @classmethod
    def _workflow_id(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("execution_mode", mode="before")
    @classmethod
    def _execution_mode(cls, value: Any) -> str:
        text = _strip_str(value) or "manual"
        if text not in EXECUTION_MODES:
            raise ValueError(
                f"execution_mode must be one of: {', '.join(EXECUTION_MODES)}"
            )
        return text


def validation_problems(exc: Exception) -> list[dict[str, Any]]:
    """Turn a Pydantic ``ValidationError`` into structured problem dicts."""
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return [{
            "loc": (),
            "msg": str(exc),
            "type": "value_error",
        }]
    return [
        {
            "loc": list(err.get("loc", ())),
            "msg": err.get("msg", "validation error"),
            "type": err.get("type", "value_error"),
        }
        for err in exc.errors(include_url=False, include_context=False)
    ]


def parse_job(data: dict[str, Any]) -> Job:
    """Validate a raw dict as a full Job document."""
    return Job.model_validate(data)


def parse_draft(data: dict[str, Any]) -> JobDraft:
    """Validate a create draft (no id / snapshot / runtime fields)."""
    payload = {
        key: value
        for key, value in data.items()
        if key
        in {
            "channel_id",
            "workflow_id",
            "workflow_version",
            "execution_mode",
            "source",
        }
    }
    return JobDraft.model_validate(payload)


__all__ = [
    "JOB_ID_RE",
    "JOB_SCHEMA_VERSION",
    "JOB_STATUSES",
    "TERMINAL_STATUSES",
    "EXECUTION_MODES",
    "SOURCE_MODES",
    "STATUS_REASON_CODES",
    "JobStatus",
    "ExecutionMode",
    "SourceMode",
    "JobSource",
    "BudgetSpent",
    "Job",
    "JobDraft",
    "validation_problems",
    "parse_job",
    "parse_draft",
]
