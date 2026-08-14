"""Pydantic schemas for TTS routes."""

from typing import Optional

from pydantic import BaseModel, Field


class BlendConfig(BaseModel):
    voice_a: str = ""
    voice_b: str = ""
    ratio: float = Field(default=0.5, ge=0.0, le=1.0)
    method: str = "slerp"

    model_config = {"extra": "allow"}


class TtsGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    voice: str = "af_bella"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    model: str = "kokoro"
    # Empty means "whichever provider is selected" (§24.1). Naming one is still
    # accepted, which is how the TTS page keeps addressing a specific provider.
    provider: str = ""
    max_silence_ms: int = Field(default=500, ge=200, le=1000)
    blend: Optional[BlendConfig] = None
    skip_clean: bool = False

    model_config = {"extra": "allow"}


class VoiceSegment(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    voice: str = ""
    speed: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    blend: Optional[BlendConfig] = None

    model_config = {"extra": "allow"}


class TtsMultivoiceRequest(BaseModel):
    segments: list[VoiceSegment] = Field(min_length=1)
    gap_ms: int = Field(default=80, ge=0, le=2000)
    prompt: str = ""
    speed: float = Field(default=1.0, ge=0.5, le=2.0)

    model_config = {"extra": "allow"}
