"""Pydantic schemas for Story generation routes."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from scriptase.modules.niches.presets import (
    CATEGORIES as NICHE_CATEGORIES,
    is_known_template,
    is_valid_story_tone,
    normalize_preset_id,
    normalize_story_tone,
)
from scriptase.modules.script.prompts import STORY_CATEGORIES

SUPPORTED_LANGUAGES = ("english", "french", "spanish")
LANGUAGE_LEVELS = ("beginner", "intermediate", "advanced", "native")
VALID_STORY_CATEGORIES = tuple(dict.fromkeys([*STORY_CATEGORIES, *NICHE_CATEGORIES]))


class StoryGenerateRequest(BaseModel):
    project_name_id: Optional[str] = None
    niche_preset: Optional[str] = None
    preset_style: str = "cinematic"
    story_category: str = "motivation"
    duration: int = Field(default=45, ge=15, le=180)
    language: Literal["english", "french", "spanish"] = "english"
    language_level: Optional[str] = None
    story_tone: Optional[str] = None
    idea: Optional[str] = None
    webhook_url: Optional[str] = None
    # Optional script-provider selector (step 13.3). Absent → domain default
    # (`gemini`). Accepts the permanent `builtin` input alias of that provider.
    provider_id: Optional[str] = None

    @model_validator(mode="after")
    def _normalize_fields(self):
        self.project_name_id = (self.project_name_id or "").strip() or None
        self.niche_preset = normalize_preset_id(self.niche_preset) or None
        self.preset_style = (self.preset_style or "").strip()
        self.story_category = (self.story_category or "").strip().lower()
        self.story_tone = normalize_story_tone(self.story_tone) or None
        if self.language_level:
            self.language_level = self.language_level.strip().lower()
            if self.language_level not in LANGUAGE_LEVELS:
                self.language_level = None
        self.idea = (self.idea or "").strip() or None
        self.webhook_url = (self.webhook_url or "").strip() or None
        self.provider_id = (self.provider_id or "").strip() or None

        if not is_known_template(self.preset_style):
            raise ValueError(f"Unknown preset_style '{self.preset_style}'")
        if self.story_category not in VALID_STORY_CATEGORIES:
            raise ValueError(f"Unknown story_category '{self.story_category}'")
        if self.story_tone and not is_valid_story_tone(self.story_tone):
            raise ValueError(f"Unknown story_tone '{self.story_tone}'")
        return self

    model_config = {"extra": "allow"}
