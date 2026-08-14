"""Pydantic schemas for Editor routes."""

from typing import Optional

from pydantic import BaseModel, Field


class EditorSaveRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")

    model_config = {"extra": "allow"}


class ExportRequest(BaseModel):
    project_id: str = Field(min_length=1)
    scenes: list = Field(min_length=1)
    output: Optional[dict] = None
    audio: Optional[dict] = None
    bgMusic: Optional[dict] = None
    captions: Optional[dict] = None
    overlays: Optional[list] = None
    grain_overlay: Optional[dict] = None
    grainOverlay: Optional[dict] = None

    model_config = {"extra": "allow"}
