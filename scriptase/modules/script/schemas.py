"""Pydantic schemas for Story generation routes."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from scriptase.channels.presets import (
    CATEGORIES as NICHE_CATEGORIES,
    category_from_niche,
    is_known_template,
    is_valid_story_tone,
    normalize_language,
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
    # Accept any string here and normalize below (ISO codes -> full names), so a
    # Channel storing "en" is not a validation failure.
    language: str = "english"
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
        self.preset_style = (self.preset_style or "").strip() or "cinematic"
        self.story_category = (self.story_category or "").strip().lower()
        # A Channel stores its language as an ISO code ("en"); the story engine
        # speaks full names. Normalize instead of rejecting.
        self.language = normalize_language(self.language)
        if self.language not in SUPPORTED_LANGUAGES:
            self.language = "english"
        self.story_tone = normalize_story_tone(self.story_tone) or None
        if self.language_level:
            self.language_level = self.language_level.strip().lower()
            if self.language_level not in LANGUAGE_LEVELS:
                self.language_level = None
        self.idea = (self.idea or "").strip() or None
        self.webhook_url = (self.webhook_url or "").strip() or None
        self.provider_id = (self.provider_id or "").strip() or None

        # A Channel's `niche` (e.g. "dark_psychology") is a niche tag, not a
        # story category. When it arrives here as story_category, resolve it to
        # the real category ("psychology") rather than failing the request.
        if self.story_category not in VALID_STORY_CATEGORIES:
            resolved = category_from_niche(self.story_category) or category_from_niche(self.niche_preset)
            self.story_category = resolved or "motivation"

        if not is_known_template(self.preset_style):
            # Unknown visual style is recoverable — fall back, don't 400.
            self.preset_style = "cinematic"
        if self.story_tone and not is_valid_story_tone(self.story_tone):
            self.story_tone = None
        return self

    model_config = {"extra": "allow"}
