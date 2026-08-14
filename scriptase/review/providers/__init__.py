"""Review provider package — compatibility facade over the provider hub.

The registry, discovery, and lookup logic lives in ``scriptase.providers.hub``;
this module only binds the ``review`` domain (step 7.3).

Domain request/result models live in ``contract.py``; the shared ABC is
``base.ReviewProvider``. Providers live in subfolders of this package.
"""

from scriptase.providers.hub import bind_domain
from scriptase.review.providers.base import ReviewProvider
from scriptase.review.providers.contract import (
    ReviewIssueItem,
    ReviewRequest,
    ReviewResultPayload,
)

registry, discover, get_provider, list_providers, init_review_registry = bind_domain(
    "review"
)

__all__ = [
    "registry",
    "discover",
    "get_provider",
    "list_providers",
    "init_review_registry",
    "ReviewProvider",
    "ReviewRequest",
    "ReviewIssueItem",
    "ReviewResultPayload",
]
