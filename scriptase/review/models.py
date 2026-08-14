"""ReviewIssue Pydantic model — contracts.md §9 / product §15.4.

Review returns only structured issues. Free-form text is not an acceptable
review output: automation (Repair Router, budgets, escalation) depends on
machine fields — ``issue_type``, ``severity``, ``confidence``,
``suggested_action``, and a bounded ``repair_instruction``.

``schema_version`` is the on-disk document revision (migrations.py). Step 1.6
shipped thin open-issue bindings at schema v1; this model is schema v2.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Mapping, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# Server-generated issue id: iss_ + 6 uppercase alphanumerics
# (matches job / artifact / scene id style in contracts.md).
ISSUE_ID_RE = re.compile(r"^iss_[A-Z0-9]{6}$")

# On-disk document format. v1 = thin OpenIssueBinding (step 1.6);
# v2 = full ReviewIssue (step 7.2).
ISSUE_SCHEMA_VERSION = 2

# contracts.md §9 issue_type vocabulary.
IssueType = Literal[
    "visual_mismatch",
    "continuity_break",
    "motion_defect",
    "audio_defect",
    "timing_drift",
    "segmentation_defect",
    "script_defect",
    "technical_defect",
    "policy_violation",
]

ISSUE_TYPES: tuple[str, ...] = (
    "visual_mismatch",
    "continuity_break",
    "motion_defect",
    "audio_defect",
    "timing_drift",
    "segmentation_defect",
    "script_defect",
    "technical_defect",
    "policy_violation",
)

Severity = Literal["low", "medium", "high", "critical"]

SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")

SuggestedAction = Literal["regenerate", "re-prompt", "adjust", "escalate", "accept"]

SUGGESTED_ACTIONS: tuple[str, ...] = (
    "regenerate",
    "re-prompt",
    "adjust",
    "escalate",
    "accept",
)

# contracts.md §9 status vocabulary, plus ``closed`` for re-segmentation
# cleanup when a scene is invalidated with no successor (step 1.6).
IssueStatus = Literal[
    "open",
    "repairing",
    "resolved",
    "escalated",
    "accepted",
    "closed",
]

ISSUE_STATUSES: tuple[str, ...] = (
    "open",
    "repairing",
    "resolved",
    "escalated",
    "accepted",
    "closed",
)

OPEN_STATUSES: frozenset[str] = frozenset({"open", "repairing"})

TERMINAL_ISSUE_STATUSES: frozenset[str] = frozenset(
    {"resolved", "escalated", "accepted", "closed"}
)

_REASON_MAX = 500
_INSTRUCTION_MAX = 500


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: Any) -> str | None:
    text = _strip_str(value)
    return text or None


def _bound(text: str, limit: int) -> str:
    text = _strip_str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


class ReviewIssue(BaseModel):
    """Persisted review finding (contracts.md §9).

    Free text alone is never valid: every issue carries machine
    ``issue_type``, ``severity``, ``confidence``, and ``suggested_action``.
    ``reason`` and ``repair_instruction`` are human-readable but bounded and
    always accompanied by the structured fields.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: int = Field(default=ISSUE_SCHEMA_VERSION, ge=1)

    job_id: str = Field(min_length=1, max_length=120)
    scene_id: str | None = None
    target_node_id: str | None = None
    target_artifact_id: str | None = None

    issue_type: IssueType
    severity: Severity
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    reason: str = Field(min_length=1, max_length=_REASON_MAX)
    suggested_action: SuggestedAction = "regenerate"
    repair_instruction: str = Field(default="", max_length=_INSTRUCTION_MAX)

    attempt_count: int = Field(default=0, ge=0)
    status: IssueStatus = "open"

    # Optional technical-check id when issue_type is technical_defect (step 7.1).
    check_id: str | None = None
    # Structured observation maps — required for free-text rejection gate.
    observed: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)

    created_at: str = ""
    resolved_at: str | None = None

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not ISSUE_ID_RE.fullmatch(value):
            raise ValueError("id must match iss_[A-Z0-9]{6}")
        return value

    @field_validator("job_id", mode="before")
    @classmethod
    def _job_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("job_id is required")
        return text

    @field_validator(
        "scene_id",
        "target_node_id",
        "target_artifact_id",
        "check_id",
        "resolved_at",
        mode="before",
    )
    @classmethod
    def _optional_ids(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("issue_type", mode="before")
    @classmethod
    def _issue_type(cls, value: Any) -> str:
        text = _strip_str(value)
        if text not in ISSUE_TYPES:
            raise ValueError(
                f"issue_type must be one of: {', '.join(ISSUE_TYPES)}"
            )
        return text

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: Any) -> str:
        text = _strip_str(value)
        if text not in SEVERITIES:
            raise ValueError(
                f"severity must be one of: {', '.join(SEVERITIES)}"
            )
        return text

    @field_validator("suggested_action", mode="before")
    @classmethod
    def _suggested_action(cls, value: Any) -> str:
        text = _strip_str(value) or "regenerate"
        if text not in SUGGESTED_ACTIONS:
            raise ValueError(
                f"suggested_action must be one of: {', '.join(SUGGESTED_ACTIONS)}"
            )
        return text

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: Any) -> str:
        text = _strip_str(value) or "open"
        if text not in ISSUE_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(ISSUE_STATUSES)}"
            )
        return text

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, value: Any) -> str:
        text = _bound(_strip_str(value), _REASON_MAX)
        if not text:
            raise ValueError("reason is required")
        return text

    @field_validator("repair_instruction", mode="before")
    @classmethod
    def _repair_instruction(cls, value: Any) -> str:
        return _bound(_strip_str(value) if value is not None else "", _INSTRUCTION_MAX)

    @field_validator("created_at", mode="before")
    @classmethod
    def _created_at(cls, value: Any) -> str:
        return _strip_str(value)

    @field_validator("attempt_count", mode="before")
    @classmethod
    def _attempt_count(cls, value: Any) -> int:
        if value is None or value == "":
            return 0
        try:
            count = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("attempt_count must be an integer >= 0") from exc
        if count < 0:
            raise ValueError("attempt_count must be an integer >= 0")
        return count

    @field_validator("observed", "expected", mode="before")
    @classmethod
    def _maps(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("observed/expected must be objects")
        return dict(value)

    @model_validator(mode="after")
    def _terminal_resolved_at(self) -> ReviewIssue:
        # Soft consistency: terminal statuses may carry resolved_at once the
        # store stamps it. No hard requirement at model level for legacy docs.
        return self

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ISSUE_STATUSES

    def to_document(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for ``safe_json_write``."""
        return self.model_dump(mode="json")


class ReviewIssueDraft(BaseModel):
    """Create payload: identity and timestamps are owned by the store.

    Used by technical validators and review providers to emit structured
    findings before persistence. Free-text-only drafts are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=120)
    scene_id: str | None = None
    target_node_id: str | None = None
    target_artifact_id: str | None = None

    issue_type: IssueType
    severity: Severity
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    reason: str = Field(min_length=1, max_length=_REASON_MAX)
    suggested_action: SuggestedAction = "regenerate"
    repair_instruction: str = Field(default="", max_length=_INSTRUCTION_MAX)

    attempt_count: int = Field(default=0, ge=0)
    status: IssueStatus = "open"

    check_id: str | None = None
    observed: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)

    @field_validator("job_id", mode="before")
    @classmethod
    def _job_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("job_id is required")
        return text

    @field_validator(
        "scene_id",
        "target_node_id",
        "target_artifact_id",
        "check_id",
        mode="before",
    )
    @classmethod
    def _optional_ids(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("issue_type", mode="before")
    @classmethod
    def _issue_type(cls, value: Any) -> str:
        text = _strip_str(value)
        if text not in ISSUE_TYPES:
            raise ValueError(
                f"issue_type must be one of: {', '.join(ISSUE_TYPES)}"
            )
        return text

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: Any) -> str:
        text = _strip_str(value)
        if text not in SEVERITIES:
            raise ValueError(
                f"severity must be one of: {', '.join(SEVERITIES)}"
            )
        return text

    @field_validator("suggested_action", mode="before")
    @classmethod
    def _suggested_action(cls, value: Any) -> str:
        text = _strip_str(value) or "regenerate"
        if text not in SUGGESTED_ACTIONS:
            raise ValueError(
                f"suggested_action must be one of: {', '.join(SUGGESTED_ACTIONS)}"
            )
        return text

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: Any) -> str:
        text = _strip_str(value) or "open"
        if text not in ISSUE_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(ISSUE_STATUSES)}"
            )
        return text

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, value: Any) -> str:
        text = _bound(_strip_str(value), _REASON_MAX)
        if not text:
            raise ValueError("reason is required")
        return text

    @field_validator("repair_instruction", mode="before")
    @classmethod
    def _repair_instruction(cls, value: Any) -> str:
        return _bound(_strip_str(value) if value is not None else "", _INSTRUCTION_MAX)

    @field_validator("attempt_count", mode="before")
    @classmethod
    def _attempt_count(cls, value: Any) -> int:
        if value is None or value == "":
            return 0
        try:
            count = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("attempt_count must be an integer >= 0") from exc
        if count < 0:
            raise ValueError("attempt_count must be an integer >= 0")
        return count

    @field_validator("observed", "expected", mode="before")
    @classmethod
    def _maps(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("observed/expected must be objects")
        return dict(value)


def parse_issue(data: dict[str, Any]) -> ReviewIssue:
    """Validate a full ReviewIssue document."""
    return ReviewIssue.model_validate(data)


def parse_draft(data: dict[str, Any]) -> ReviewIssueDraft:
    """Validate a create payload."""
    return ReviewIssueDraft.model_validate(data)


def validation_problems(exc: Exception) -> list[dict[str, Any]]:
    """Turn a Pydantic ``ValidationError`` into structured problem dicts."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return [
            {
                "loc": list(item.get("loc", ())),
                "msg": item.get("msg", "invalid"),
                "type": item.get("type", "value_error"),
            }
            for item in errors(include_url=False, include_context=False)
        ]
    return [{"loc": [], "msg": str(exc), "type": "value_error"}]


def assert_structured_review_result(payload: Any) -> list[ReviewIssueDraft | ReviewIssue]:
    """Validate that a review result is structured issues, never free text.

    Accepts:

    * a list of ``ReviewIssue`` / ``ReviewIssueDraft`` instances
    * a list of dicts that validate as drafts or full documents
    * a mapping with an ``issues`` list (result envelope shape for step 7.3)

    Raises ``TypeError`` for free-form strings and ``ValidationError`` when
    required structured fields are missing.
    """
    if isinstance(payload, str):
        raise TypeError(
            "review must not return free-text results; emit structured ReviewIssue records"
        )

    items: Sequence[Any]
    if isinstance(payload, Mapping):
        if "issues" not in payload:
            # A single issue object is allowed when it carries issue_type.
            if "issue_type" in payload or "id" in payload:
                items = [payload]
            else:
                raise TypeError(
                    "review result envelope must contain an 'issues' array of structured findings"
                )
        else:
            raw_issues = payload.get("issues")
            if isinstance(raw_issues, str):
                raise TypeError(
                    "review must not return free-text results; emit structured ReviewIssue records"
                )
            if not isinstance(raw_issues, Sequence) or isinstance(raw_issues, (str, bytes)):
                raise TypeError("review result 'issues' must be a list of structured findings")
            items = list(raw_issues)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        items = list(payload)
    else:
        raise TypeError(
            "review must return a list of structured ReviewIssue records "
            f"(got {type(payload)!r})"
        )

    out: list[ReviewIssueDraft | ReviewIssue] = []
    for item in items:
        if isinstance(item, str):
            raise TypeError(
                "review must not emit free-text issues; each finding needs "
                "issue_type, severity, confidence, reason, and suggested_action"
            )
        if isinstance(item, ReviewIssue):
            out.append(item)
            continue
        if isinstance(item, ReviewIssueDraft):
            out.append(item)
            continue
        if not isinstance(item, Mapping):
            raise TypeError(f"unexpected review issue type: {type(item)!r}")

        data = dict(item)
        # Full documents (have id + schema_version) vs create drafts.
        if data.get("id") and ISSUE_ID_RE.fullmatch(str(data.get("id") or "")):
            out.append(ReviewIssue.model_validate(data))
        else:
            out.append(ReviewIssueDraft.model_validate(data))
    return out


def technical_to_draft(
    technical: Any,
    *,
    job_id: str,
) -> ReviewIssueDraft:
    """Map a step-7.1 ``TechnicalIssue`` onto a ``ReviewIssueDraft``.

    Accepts a TechnicalIssue instance or a mapping with the same fields.
    """
    if hasattr(technical, "model_dump"):
        data = technical.model_dump(mode="json")
    elif isinstance(technical, Mapping):
        data = dict(technical)
    else:
        raise TypeError("technical issue must be a TechnicalIssue or mapping")

    return ReviewIssueDraft.model_validate(
        {
            "job_id": job_id,
            "scene_id": data.get("scene_id"),
            "target_node_id": data.get("target_node_id"),
            "target_artifact_id": data.get("target_artifact_id"),
            "issue_type": data.get("issue_type") or "technical_defect",
            "severity": data.get("severity") or "high",
            "confidence": data.get("confidence", 1.0),
            "reason": data.get("reason") or "Technical validation failed.",
            "suggested_action": data.get("suggested_action") or "regenerate",
            "repair_instruction": data.get("repair_instruction") or "",
            "check_id": data.get("check_id"),
            "observed": data.get("observed") or {},
            "expected": data.get("expected") or {},
            "status": "open",
            "attempt_count": 0,
        }
    )


__all__ = [
    "ISSUE_ID_RE",
    "ISSUE_SCHEMA_VERSION",
    "ISSUE_TYPES",
    "ISSUE_STATUSES",
    "OPEN_STATUSES",
    "TERMINAL_ISSUE_STATUSES",
    "SEVERITIES",
    "SUGGESTED_ACTIONS",
    "IssueType",
    "IssueStatus",
    "Severity",
    "SuggestedAction",
    "ReviewIssue",
    "ReviewIssueDraft",
    "ValidationError",
    "assert_structured_review_result",
    "parse_draft",
    "parse_issue",
    "technical_to_draft",
    "validation_problems",
]
