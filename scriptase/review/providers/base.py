"""Review provider base contract — step 7.3.

Providers that produce structured ``ReviewIssue`` findings implement this
interface. The only entry point is Contract v2
``invoke(request, invocation) -> ProviderResult``; there is no legacy concrete
seam because Review is new in Scriptase (no V2 adapter to bridge).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from scriptase.review.providers.contract import (
    ReviewRequest,
    ReviewResultPayload,
)


class ReviewProvider(ABC):
    """Base class for every review-domain provider."""

    @abstractmethod
    def review(
        self,
        request: ReviewRequest,
        *,
        settings: Mapping[str, Any] | None = None,
    ) -> ReviewResultPayload:
        """Inspect the subject and return structured issues only.

        Implementations must never return free-form text. The result payload
        validates each finding against the ReviewIssue draft schema.
        ``settings`` carries the resolved per-instance configuration for this
        call (never echoed into the result).
        """

    def invoke(self, request: ReviewRequest | Mapping[str, Any], invocation) -> Any:
        """v2 invocation — standardized envelope with structured issues."""
        from scriptase.providers.results import ProviderResult

        if not isinstance(request, ReviewRequest):
            if isinstance(request, Mapping):
                # Merge invocation options so Test Node / direct calls can pass
                # fields either as the request body or as per-run options.
                merged = {**dict(invocation.options or {}), **dict(request)}
                if not merged.get("job_id"):
                    merged["job_id"] = (
                        (invocation.options or {}).get("job_id")
                        or invocation.project_id
                        or "job_UNKNOWN"
                    )
                request = ReviewRequest.from_configuration(merged)
            else:
                request = ReviewRequest.model_validate(request)

        payload_model = self.review(
            request,
            settings=dict(invocation.settings or {}),
        )
        payload = payload_model.model_dump(mode="json")
        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            payload=payload,
            artifact_refs=[],
            metadata={
                "subject_kind": payload_model.subject_kind,
                "capability": payload_model.capability,
                "issue_count": payload_model.issue_count,
                "clean": payload_model.clean,
            },
        )

    def shutdown(self) -> None:
        """Release process-held resources. Idempotent; default is a no-op."""


__all__ = ["ReviewProvider"]
