"""Review and the Repair Router (Phases 7 and 8).

Deterministic technical validators run first; expensive AI review is never the
only validation layer. Review returns only structured ``ReviewIssue`` records —
free-form text is not an acceptable review output, because automation depends on
structure.

The Repair Router sends each issue back to the node responsible for fixing it
via a table-driven policy, and repairs the smallest responsible scope.

Step 1.6 shipped a thin open-issue binding store so re-segmentation can
re-target or close open issues when scene ids change. Step 7.1 adds
deterministic technical validators. Step 7.2 expands open-issue bindings into
the full ReviewIssue schema and durable store. Step 7.4 adds early quality
gates (image before video, video before final review).
"""

from scriptase.review.gates import (
    QUALITY_GATE_FAILED,
    GateUnit,
    QualityGateResult,
    enforce_image_gate_for_video,
    run_image_gate,
    run_video_gate,
    units_from_storyboard,
    units_from_video_assets,
)
from scriptase.review.models import (
    ISSUE_ID_RE,
    ISSUE_SCHEMA_VERSION,
    ISSUE_STATUSES,
    ISSUE_TYPES,
    OPEN_STATUSES,
    SEVERITIES,
    SUGGESTED_ACTIONS,
    TERMINAL_ISSUE_STATUSES,
    IssueStatus,
    IssueType,
    ReviewIssue,
    ReviewIssueDraft,
    Severity,
    SuggestedAction,
    assert_structured_review_result,
    parse_draft,
    parse_issue,
    technical_to_draft,
    validation_problems,
)
from scriptase.review.open_issues import (
    IssueBindingNotFound,
    OpenIssueBinding,
    assert_no_open_issue_on_dead_scenes,
    close_issues_for_scene,
    create_open_issue,
    retarget_issues,
)
from scriptase.review.store import (
    IssueNotFound,
    IssueValidationError,
    create_from_review_result,
    create_from_technical,
    create_review_issue,
    get_issue,
    issues_for_nodes,
    list_issues,
    update_issue,
)
from scriptase.review.technical import (
    TECHNICAL_CHECK_IDS,
    MediaProbe,
    TechnicalContext,
    TechnicalIssue,
    assert_structured_issues,
    check_aspect_ratio,
    check_audio_presence,
    check_duration,
    check_expected_artifact_count,
    check_file_exists,
    check_frame_count,
    check_readable_media,
    check_resolution,
    probe_media,
    run_technical_validators,
)

__all__ = [
    "ISSUE_ID_RE",
    "ISSUE_SCHEMA_VERSION",
    "ISSUE_STATUSES",
    "ISSUE_TYPES",
    "OPEN_STATUSES",
    "QUALITY_GATE_FAILED",
    "SEVERITIES",
    "SUGGESTED_ACTIONS",
    "TECHNICAL_CHECK_IDS",
    "TERMINAL_ISSUE_STATUSES",
    "GateUnit",
    "IssueBindingNotFound",
    "IssueNotFound",
    "IssueStatus",
    "IssueType",
    "IssueValidationError",
    "MediaProbe",
    "OpenIssueBinding",
    "QualityGateResult",
    "ReviewIssue",
    "ReviewIssueDraft",
    "Severity",
    "SuggestedAction",
    "TechnicalContext",
    "TechnicalIssue",
    "assert_no_open_issue_on_dead_scenes",
    "assert_structured_issues",
    "assert_structured_review_result",
    "check_aspect_ratio",
    "check_audio_presence",
    "check_duration",
    "check_expected_artifact_count",
    "check_file_exists",
    "check_frame_count",
    "check_readable_media",
    "check_resolution",
    "close_issues_for_scene",
    "create_from_review_result",
    "create_from_technical",
    "create_open_issue",
    "create_review_issue",
    "enforce_image_gate_for_video",
    "get_issue",
    "issues_for_nodes",
    "list_issues",
    "parse_draft",
    "parse_issue",
    "probe_media",
    "retarget_issues",
    "run_image_gate",
    "run_technical_validators",
    "run_video_gate",
    "technical_to_draft",
    "units_from_storyboard",
    "units_from_video_assets",
    "update_issue",
    "validation_problems",
]
