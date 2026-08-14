"""Script provider base contract — steps 13.1 / 13.2.

Providers that produce a typed script/story document implement this interface.
Two entry points exist on purpose:

  * `generate(configuration, project_id=…)` — the concrete adapter seam
    (`adapters/story.py`). Returns the legacy-compatible document dict plus a
    managed `path` so the Story Generator node needs no rewrite to run a new
    provider.
  * `invoke(request, invocation)` — the v2 contract (contracts.md §30/§31).
    Returns a `ProviderResult` whose `payload` validates as
    `ScriptResultPayload`.

Shipped providers: `random_template` (offline catalog) and `gemini` (AI webhook).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from scriptase.modules.script.providers.contract import ScriptRequest, ScriptResultPayload


class ScriptProvider(ABC):
    """Base class for every script-domain provider."""

    @abstractmethod
    def generate(self, configuration: Mapping[str, Any], *, project_id: str) -> dict:
        """Produce a story document and write `stories/{project_id}/story.json`.

        Return shape (adapter-compatible):
            {
              "project_id": str,
              "story_text": str,
              "sections": dict[str, str],
              "metadata": dict,
              "pipeline_ref": dict,
              "path": str,  # absolute, managed under OUTPUT_DIR
            }
        """

    def invoke(self, request: ScriptRequest, invocation) -> Any:
        """v2 invocation. Default bridges through `generate()` so a provider
        that only implements the concrete seam still participates in the
        standardized envelope.
        """
        from scriptase.providers.results import ProviderResult, normalize_ref

        if not isinstance(request, ScriptRequest):
            request = ScriptRequest.model_validate(request)

        configuration = {
            "idea": request.idea,
            "story_category": request.category,
            "preset_style": request.style,
            "story_tone": request.tone,
            "language": request.language,
            "language_level": request.language_level,
            "duration": request.target_duration_s,
            "niche_preset": request.niche_preset,
            "seed": request.seed,
        }
        document = self.generate(configuration, project_id=invocation.project_id)
        path = document.pop("path", None)
        payload = ScriptResultPayload.from_mapping(document).model_dump()
        refs = [normalize_ref(path)] if path else []
        if refs:
            payload_with_ref = {**payload, "document_ref": refs[0]}
        else:
            payload_with_ref = payload
        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            payload=payload_with_ref,
            artifact_refs=refs,
            metadata={
                key: value
                for key, value in (document.get("metadata") or {}).items()
                if key
                not in {
                    "word_count",
                    "estimated_duration",
                    "language",
                    "provider",
                }
            },
        )

    def shutdown(self) -> None:
        """Release process-held resources. Idempotent; default is a no-op."""


__all__ = ["ScriptProvider"]
