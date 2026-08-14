"""Scene-blueprint provider base contract — step 13.4.

Providers that plan scenes and image prompts implement this interface.
Two entry points exist on purpose:

  * `generate(segments, configuration, project_id=…)` — the concrete adapter
    seam (`adapters/scenes.py`). Returns the legacy-compatible `scenes.json`
    document plus a managed `path` so the Scene Blueprint node needs no rewrite.
  * `invoke(request, invocation)` — the v2 contract (contracts.md §30/§31).
    Returns a `ProviderResult` whose `payload` validates as
    `SceneBlueprintResultPayload`.

Shipped provider: `n8n` (webhook AI path; `builtin` is a permanent input alias).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from scriptase.modules.scene_director.providers.contract import (
    SceneBlueprintRequest,
    SceneBlueprintResultPayload,
)


class SceneBlueprintProvider(ABC):
    """Base class for every scene_blueprint-domain provider."""

    @abstractmethod
    def generate(
        self,
        segments: Mapping[str, Any],
        configuration: Mapping[str, Any],
        *,
        project_id: str,
    ) -> dict:
        """Produce a scenes document and write `scenes/{project_id}/scenes.json`.

        `segments` is the segmenter-shaped dict (`{"segments": [...], "metadata"?}`).
        Return shape (adapter-compatible):
            {
              "project_id": str,
              "scenes": list[dict],
              "style_spec": dict,
              "style_prompt": str,
              "analysis": dict,
              "coherence_score": float,
              "coherence_warnings": list,
              "coherence_metrics": dict,
              "sfx_report": dict | None,
              "total_duration": float,
              "scene_blueprints": list,   # planner inputs, persisted
              "provider": str,           # canonical id (P33)
              "path": str,               # absolute, managed under OUTPUT_DIR
              …
            }
        """

    def invoke(self, request: SceneBlueprintRequest, invocation) -> Any:
        """v2 invocation. Default bridges through `generate()` so a provider
        that only implements the concrete seam still participates in the
        standardized envelope.
        """
        from scriptase.providers.results import ProviderResult, normalize_ref

        if not isinstance(request, SceneBlueprintRequest):
            request = SceneBlueprintRequest.model_validate(request)

        segment_result = {
            "segments": [seg.model_dump() for seg in request.segments],
            "metadata": {},
        }
        configuration = {
            "text": request.script,
            "script": request.script,
            "style": request.style,
            "style_prompt": request.style_notes,
            "story_tone": request.tone,
            "aspect_ratio": request.aspect_ratio,
            # Step 5.2: structured Channel visual direction (typed request input).
            "visual_direction": request.visual_direction.model_dump(mode="json"),
        }
        document = self.generate(
            segment_result, configuration, project_id=invocation.project_id
        )
        path = document.pop("path", None)
        # Coerce every scene through SceneSpec so the envelope always carries
        # the frozen §8 shape (step 5.1), including legacy scenes.json rows.
        typed = SceneBlueprintResultPayload.from_mapping(document)
        payload = typed.model_dump(mode="python")
        # Prefer the port-friendly scene dicts (plural + singular hint aliases).
        payload["scenes"] = typed.scenes_as_dicts()
        refs = [normalize_ref(path)] if path else []
        if refs:
            payload = {**payload, "document_ref": refs[0]}
        invocation.progress(ready=1, total=1, state="succeeded")
        # Planner inputs stay in metadata, not the frozen payload (§32.2).
        metadata = {}
        for key in ("scene_blueprints", "visual_bible", "custom_style_notes", "style"):
            if key in document and document[key] is not None:
                metadata[key] = document[key]
        return ProviderResult(
            payload=payload,
            artifact_refs=refs,
            metadata=metadata,
        )

    def shutdown(self) -> None:
        """Release process-held resources. Idempotent; default is a no-op."""


__all__ = ["SceneBlueprintProvider"]
