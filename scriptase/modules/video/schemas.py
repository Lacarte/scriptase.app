"""Pydantic schemas for Animator grabber routes.

Step 14.3 repaired the selection gap: `provider` defaulted every request to
`midjourney` (resolved to `grok_automa`), so the authoritative selected-provider
store was never consulted. Both fields are optional now; the route resolves
`provider_override` → `provider` → saved selection → domain default, and legacy
spellings (`grok` / `midjourney` / `kie-ai`) resolve through the registry's
aliases.
"""

from typing import Optional

from pydantic import BaseModel, Field


class ScenePrompt(BaseModel):
    prompt: str = Field(min_length=1)
    scene: int

    model_config = {"extra": "allow"}


class GrabberStartRequest(BaseModel):
    """The grabber start request. `provider` is a real optional field (step 14.3).

    It used to default to `"midjourney"`, which made every request that omitted
    a provider land on `grok_automa` via the legacy map and never read
    `domains.animator.selected_provider` (D15 / C2). Both override and legacy
    fields are optional; an absent pair falls through to the saved selection.
    """

    scenes: list[ScenePrompt] = Field(min_length=1)
    project_id: str = "default"
    # Canonical registry ID, e.g. "grok_automa" / "kie_ai".
    provider_override: Optional[str] = None
    # Legacy spelling kept for old callers; an alias resolves it.
    provider: Optional[str] = None
    provider_options: dict = Field(default_factory=dict)

    # Free-text Automa passthrough kept for wire compatibility. Not part of the
    # frozen AnimatorRequest (§32.5) and no longer consumed by any provider —
    # Midjourney is gone (P12). Accepted and dropped.
    arguments: str = Field(default="", max_length=200)
    consistency: Optional[dict] = None
    model: Optional[str] = None
    aspect_ratio: Optional[str] = None
    resolution: Optional[str] = None
    output_format: Optional[str] = None

    model_config = {"extra": "allow"}
