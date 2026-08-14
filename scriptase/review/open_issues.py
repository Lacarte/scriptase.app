"""Open-issue store facade for scene re-segmentation (step 1.6 / 7.2).

Step 1.6 shipped a thin binding record so re-segmentation could re-target or
close open issues when scene boundaries change. Step 7.2 expanded those
bindings into the full :class:`~scriptase.review.models.ReviewIssue` schema
and store.

This module re-exports the stable re-segmentation API from
:mod:`scriptase.review.store` so existing call sites keep working. New code
should import from :mod:`scriptase.review` or :mod:`scriptase.review.store`.

Tests may rebind the on-disk root with::

    from scriptase.review import open_issues as issue_store
    issue_store._issues_dir = tempfile_path

Public functions sync that assignment into the real store before each call.
"""

from __future__ import annotations

import sys

import scriptase.review.store as _store
from scriptase.review.models import (
    ISSUE_ID_RE,
    ISSUE_SCHEMA_VERSION,
    OPEN_STATUSES,
    IssueStatus,
    ReviewIssue,
)
from scriptase.review.store import (
    IssueBindingNotFound,
    IssueNotFound,
)

# Historical name for the persisted document type.
OpenIssueBinding = ReviewIssue

# Seed; tests overwrite this attribute. Public wrappers push it into the store.
_issues_dir = _store._issues_dir


def _pull_dir() -> None:
    """If a test rebound this module's ``_issues_dir``, push it into the store."""
    mod = sys.modules[__name__]
    local = getattr(mod, "_issues_dir", None)
    if isinstance(local, str) and local and local != _store._issues_dir:
        _store._issues_dir = local


def create_open_issue(*args, **kwargs):
    _pull_dir()
    return _store.create_open_issue(*args, **kwargs)


def get_issue(*args, **kwargs):
    _pull_dir()
    return _store.get_issue(*args, **kwargs)


def list_issues(*args, **kwargs):
    _pull_dir()
    return _store.list_issues(*args, **kwargs)


def retarget_issues(*args, **kwargs):
    _pull_dir()
    return _store.retarget_issues(*args, **kwargs)


def close_issues_for_scene(*args, **kwargs):
    _pull_dir()
    return _store.close_issues_for_scene(*args, **kwargs)


def assert_no_open_issue_on_dead_scenes(*args, **kwargs):
    _pull_dir()
    return _store.assert_no_open_issue_on_dead_scenes(*args, **kwargs)


__all__ = [
    "ISSUE_ID_RE",
    "ISSUE_SCHEMA_VERSION",
    "OPEN_STATUSES",
    "IssueBindingNotFound",
    "IssueNotFound",
    "IssueStatus",
    "OpenIssueBinding",
    "ReviewIssue",
    "assert_no_open_issue_on_dead_scenes",
    "close_issues_for_scene",
    "create_open_issue",
    "get_issue",
    "list_issues",
    "retarget_issues",
]
