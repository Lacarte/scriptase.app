"""Viral provider base contract — step 16.2.

Providers that score a script's virality implement this interface. The only
entry point is Contract v2 ``invoke(request, invocation) -> ProviderResult``;
there is no legacy concrete seam because virality scoring is new in Scriptase
(V2 never had any).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from scriptase.modules.viral.providers.contract import (
    ViralRequest,
    ViralResultPayload,
)


class ViralProvider(ABC):
    """Base class for every viral-domain provider."""

    @abstractmethod
    def score(
        self,
        request: ViralRequest,
        *,
        settings: Mapping[str, Any] | None = None,
    ) -> ViralResultPayload:
        """Score the script and return the frozen 16.1 result shape.

        Implementations own the arithmetic and nothing else: the dimension ids,
        the weights, and the band floors are the contract, so a judge that
        disagrees with the deterministic scorer still fills in the same
        breakdown. ``settings`` carries the resolved per-instance configuration
        for this call and is never echoed into the result.
        """

    def invoke(self, request: ViralRequest | Mapping[str, Any], invocation) -> Any:
        """v2 invocation — standardized envelope around one typed score."""
        from scriptase.providers.results import ProviderResult

        if not isinstance(request, ViralRequest):
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
                request = ViralRequest.from_configuration(merged)
            else:
                request = ViralRequest.model_validate(request)

        payload_model = self.score(
            request,
            settings=dict(invocation.settings or {}),
        )
        payload = payload_model.model_dump(mode="json")
        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            payload=payload,
            artifact_refs=[],
            metadata={
                "scorer": payload_model.scorer,
                "scorer_version": payload_model.scorer_version,
                "score": payload_model.score,
                "band": payload_model.band,
            },
        )

    def shutdown(self) -> None:
        """Release process-held resources. Idempotent; default is a no-op."""


__all__ = ["ViralProvider"]
