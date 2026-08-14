"""Pydantic schemas for Segmenter routes."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class AlignmentWord(BaseModel):
    word: str
    begin: float = Field(ge=0.0)
    end: float = Field(ge=0.0)

    model_config = {"extra": "allow"}


class SegmenterRunRequest(BaseModel):
    alignment: list[AlignmentWord] = Field(min_length=1)
    transcript: str = ""
    source_folder: str = ""
    project_id: str = ""
    style: str = ""
    aspect_ratio: str = ""
    config: Optional[dict] = None
    save: bool = True

    model_config = {"extra": "allow"}
