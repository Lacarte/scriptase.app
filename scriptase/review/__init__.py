"""Review and the Repair Router (Phases 7 and 8).

Deterministic technical validators run first; expensive AI review is never the
only validation layer. Review returns only structured ``ReviewIssue`` records —
free-form text is not an acceptable review output, because automation depends on
structure.

The Repair Router sends each issue back to the node responsible for fixing it
via a table-driven policy, and repairs the smallest responsible scope.

Step 1.6 ships a thin :mod:`scriptase.review.open_issues` binding store so
re-segmentation can re-target or close open issues when scene ids change.
Step 7.2 expands those bindings into the full ReviewIssue schema.
"""

from scriptase.review.open_issues import (
    ISSUE_ID_RE,
    ISSUE_SCHEMA_VERSION,
    OPEN_STATUSES,
    IssueBindingNotFound,
    OpenIssueBinding,
    assert_no_open_issue_on_dead_scenes,
    close_issues_for_scene,
    create_open_issue,
    get_issue,
    list_issues,
    retarget_issues,
)

__all__ = [
    "ISSUE_ID_RE",
    "ISSUE_SCHEMA_VERSION",
    "OPEN_STATUSES",
    "IssueBindingNotFound",
    "OpenIssueBinding",
    "assert_no_open_issue_on_dead_scenes",
    "close_issues_for_scene",
    "create_open_issue",
    "get_issue",
    "list_issues",
    "retarget_issues",
]
