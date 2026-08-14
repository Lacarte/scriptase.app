"""Review domain request and result models (step 7.3 / contracts.md §9).

Every review provider — the offline ``semantic`` heuristic and any future AI
plugin — accepts and returns these shapes. The result payload's ``issues``
array is the only sanctioned review output: free-form text is rejected by
``assert_structured_review_result`` before anything is persisted.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, Field, field_validator, model_validator

from scriptase.review.models import (
    ISSUE_TYPES,
    SEVERITIES,
    SUGGESTED_ACTIONS,
    assert_structured_review_result,
)

SubjectKind = Literal["image", "video", "text", "structured"]

SUBJECT_KINDS: tuple[str, ...] = ("image", "video", "text", "structured")

# Capability each subject_kind requires of the provider.
SUBJECT_CAPABILITY: dict[str, str] = {
    "image": "image_review",
    "video": "video_review",
    "text": "text_review",
    "structured": "structured_output",
}

_REASON_MAX = 500
_TEXT_MAX = 50_000


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: Any) -> str | None:
    text = _strip_str(value)
    return text or None


class ReviewRequest(BaseModel):
    """Frozen review request. Unknown keys are rejected (not silently ignored)."""

    job_id: str = Field(min_length=1, max_length=120)
    subject_kind: SubjectKind = "text"

    scene_id: str | None = None
    target_node_id: str | None = None
    target_artifact_id: str | None = None

    # Content under review (which fields matter depends on subject_kind).
    text: str = ""
    # Managed relative artifact ref — never an absolute filesystem path.
    artifact_ref: str = ""
    caption: str = ""
    image_prompt: str = ""

    # Expected / target context for semantic comparison.
    expected_subject: str = ""
    expected_style: str = ""
    expected_text: str = ""
    expected_duration_s: float | None = None
    duration_s: float | None = None

    # structured_output subject
    structured: dict[str, Any] = Field(default_factory=dict)
    required_keys: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("job_id", mode="before")
    @classmethod
    def _job_id(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("job_id is required")
        return text

    @field_validator("subject_kind", mode="before")
    @classmethod
    def _subject_kind(cls, value: Any) -> str:
        text = _strip_str(value) or "text"
        if text not in SUBJECT_KINDS:
            raise ValueError(
                f"subject_kind must be one of: {', '.join(SUBJECT_KINDS)}"
            )
        return text

    @field_validator(
        "scene_id",
        "target_node_id",
        "target_artifact_id",
        mode="before",
    )
    @classmethod
    def _optional_ids(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator(
        "text",
        "artifact_ref",
        "caption",
        "image_prompt",
        "expected_subject",
        "expected_style",
        "expected_text",
        mode="before",
    )
    @classmethod
    def _strip_text_fields(cls, value: Any) -> str:
        text = _strip_str(value)
        if len(text) > _TEXT_MAX:
            return text[:_TEXT_MAX]
        return text

    @field_validator("artifact_ref", mode="after")
    @classmethod
    def _relative_ref_only(cls, value: str) -> str:
        # Absolute / UNC paths must never enter a review request (contracts.md).
        if not value:
            return value
        if value.startswith(("/", "\\")) or (
            len(value) >= 3 and value[1] == ":" and value[0].isalpha()
        ):
            raise ValueError("artifact_ref must be a managed relative reference")
        if "\\" in value:
            return value.replace("\\", "/")
        return value

    @field_validator("structured", mode="before")
    @classmethod
    def _structured(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("structured must be an object")
        return dict(value)

    @field_validator("required_keys", mode="before")
    @classmethod
    def _required_keys(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
            raise ValueError("required_keys must be a list of strings")
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("duration_s", "expected_duration_s", mode="before")
    @classmethod
    def _optional_float(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("duration fields must be numbers") from exc

    @classmethod
    def from_configuration(cls, configuration: Mapping[str, Any] | None) -> "ReviewRequest":
        """Map adapter / node configuration keys onto the frozen request."""
        data = dict(configuration or {})
        return cls(
            job_id=data.get("job_id") or data.get("project_id") or "job_UNKNOWN",
            subject_kind=data.get("subject_kind") or data.get("kind") or "text",
            scene_id=data.get("scene_id"),
            target_node_id=data.get("target_node_id") or data.get("node_id"),
            target_artifact_id=data.get("target_artifact_id") or data.get("artifact_id"),
            text=data.get("text") or data.get("script_text") or data.get("content") or "",
            artifact_ref=data.get("artifact_ref") or data.get("ref") or "",
            caption=data.get("caption") or "",
            image_prompt=data.get("image_prompt") or data.get("prompt") or "",
            expected_subject=data.get("expected_subject") or data.get("subject") or "",
            expected_style=data.get("expected_style") or data.get("style") or "",
            expected_text=data.get("expected_text") or "",
            expected_duration_s=data.get("expected_duration_s"),
            duration_s=data.get("duration_s") or data.get("duration"),
            structured=data.get("structured") or data.get("payload") or {},
            required_keys=data.get("required_keys") or [],
        )

    @property
    def required_capability(self) -> str:
        return SUBJECT_CAPABILITY[self.subject_kind]


class ReviewIssueItem(BaseModel):
    """One structured finding inside a review result payload.

    Mirrors ``ReviewIssueDraft`` fields the provider is allowed to emit.
    Identity and timestamps are owned by the store at persist time.
    """

    model_config = {"extra": "forbid"}

    job_id: str = Field(min_length=1, max_length=120)
    scene_id: str | None = None
    target_node_id: str | None = None
    target_artifact_id: str | None = None

    issue_type: str
    severity: str = "medium"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

    reason: str = Field(min_length=1, max_length=_REASON_MAX)
    suggested_action: str = "regenerate"
    repair_instruction: str = Field(default="", max_length=_REASON_MAX)

    observed: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)

    @field_validator("issue_type", mode="before")
    @classmethod
    def _issue_type(cls, value: Any) -> str:
        text = _strip_str(value)
        if text not in ISSUE_TYPES:
            raise ValueError(f"issue_type must be one of: {', '.join(ISSUE_TYPES)}")
        return text

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: Any) -> str:
        text = _strip_str(value) or "medium"
        if text not in SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(SEVERITIES)}")
        return text

    @field_validator("suggested_action", mode="before")
    @classmethod
    def _action(cls, value: Any) -> str:
        text = _strip_str(value) or "regenerate"
        if text not in SUGGESTED_ACTIONS:
            raise ValueError(
                f"suggested_action must be one of: {', '.join(SUGGESTED_ACTIONS)}"
            )
        return text

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("reason is required")
        return text[:_REASON_MAX]

    @field_validator("repair_instruction", mode="before")
    @classmethod
    def _instruction(cls, value: Any) -> str:
        return _strip_str(value)[:_REASON_MAX]

    @field_validator("observed", "expected", mode="before")
    @classmethod
    def _maps(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("observed/expected must be objects")
        return dict(value)

    def to_draft_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ReviewResultPayload(BaseModel):
    """Frozen review result — structured issues only (never free text)."""

    issues: list[dict[str, Any]] = Field(default_factory=list)
    subject_kind: SubjectKind = "text"
    capability: str = "text_review"
    issue_count: int = 0
    clean: bool = True

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _sync_counts_and_structure(self) -> "ReviewResultPayload":
        # Reject free-text issues at the domain boundary.
        structured = assert_structured_review_result({"issues": self.issues})
        # Re-serialize validated drafts so payload is always schema-clean.
        cleaned: list[dict[str, Any]] = []
        for item in structured:
            if hasattr(item, "model_dump"):
                data = item.model_dump(mode="json")
            else:
                data = dict(item)
            # Drop store-only fields providers must not invent.
            data.pop("id", None)
            data.pop("schema_version", None)
            data.pop("created_at", None)
            data.pop("resolved_at", None)
            cleaned.append(data)
        object.__setattr__(self, "issues", cleaned)
        object.__setattr__(self, "issue_count", len(cleaned))
        object.__setattr__(self, "clean", len(cleaned) == 0)
        return self

    @classmethod
    def from_issues(
        cls,
        issues: Sequence[Mapping[str, Any] | ReviewIssueItem],
        *,
        subject_kind: str = "text",
        capability: str | None = None,
    ) -> "ReviewResultPayload":
        items: list[dict[str, Any]] = []
        for issue in issues:
            if isinstance(issue, ReviewIssueItem):
                items.append(issue.to_draft_dict())
            elif isinstance(issue, Mapping):
                items.append(dict(issue))
            else:
                raise TypeError(
                    "review issues must be structured mappings, never free text"
                )
        cap = capability or SUBJECT_CAPABILITY.get(subject_kind, "text_review")
        return cls(
            issues=items,
            subject_kind=subject_kind,  # type: ignore[arg-type]
            capability=cap,
        )


__all__ = [
    "SUBJECT_KINDS",
    "SUBJECT_CAPABILITY",
    "SubjectKind",
    "ReviewRequest",
    "ReviewIssueItem",
    "ReviewResultPayload",
]
