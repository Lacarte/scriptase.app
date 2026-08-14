"""Pydantic schemas for Scenes routes."""

from typing import Any, Optional, Union

from pydantic import BaseModel, Field


class SegmentItem(BaseModel):
    index: int
    words: Any  # list of strings or string

    model_config = {"extra": "allow"}


class SceneGenerateRequest(BaseModel):
    segments: list[Union[str, SegmentItem]] = Field(min_length=1)
    script: str = ""
    style: str = "cinematic"
    style_prompt: Optional[str] = None
    custom_style_notes: Optional[str] = None
    full_segments: Optional[list] = None
    webhook_url: Optional[str] = None
    project_id: Optional[str] = None
    parent_id: Optional[str] = None
    source_folder: Optional[str] = None
    aspect_ratio: Optional[str] = None
    # Optional scene_blueprint provider (`n8n` default; `builtin` alias accepted).
    provider_id: Optional[str] = None
    story_tone: Optional[str] = None
    model_config = {"extra": "allow"}
