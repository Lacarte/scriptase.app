"""Pydantic schemas for Storyboard routes."""

from typing import Optional

from pydantic import BaseModel, Field


class StoryboardScene(BaseModel):
    scene: int
    prompt: str = Field(min_length=1)

    model_config = {"extra": "allow"}


class StoryboardGenerateRequest(BaseModel):
    """The bulk generate request. `provider` is a real field again (step 14.2).

    It used to be a read-only `@property` returning `provider_override or
    "webhook"`, which — with `extra: allow` — meant a posted `provider` value
    landed in the model's extras and was shadowed by the property on every
    read. The Storyboard page and the pipeline both send that field, so both
    were silently unable to choose a provider through this route. It is
    declared here so the value arrives, and the route normalizes the legacy
    spellings (`gemini` / `webhook` / `direct`) through the registry's aliases
    before dispatch (§40.3).
    """

    project_id: str
    scenes: list[StoryboardScene] = Field(min_length=1)
    aspect_ratio: str = "9:16"
    webhook_url: Optional[str] = None
    # Canonical registry ID, e.g. "gemini_ws" / "wavespeed_webhook".
    provider_override: Optional[str] = None
    # Legacy spelling kept for old callers; an alias resolves it.
    provider: Optional[str] = None
    provider_options: dict = Field(default_factory=dict)  # Optional per-run settings
    style: Optional[str] = None
    image_model: Optional[str] = None
    auto_type: Optional[bool] = None

    model_config = {"extra": "allow"}


class StoryboardGrabOneRequest(BaseModel):
    project_id: str
    scene: int
    prompt: str = Field(min_length=1)
    aspect_ratio: str = "9:16"
    webhook_url: Optional[str] = None
    provider: Optional[str] = None
    provider_override: Optional[str] = None
    provider_options: dict = Field(default_factory=dict)
    style: Optional[str] = None
    image_model: Optional[str] = None
    auto_type: Optional[bool] = None

    model_config = {"extra": "allow"}
