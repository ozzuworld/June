"""
Request/Response models for Voice Cloning Service
"""

from typing import Optional
from pydantic import BaseModel, Field

class VoiceCloneRequest(BaseModel):
    """Voice cloning request model"""
    text: str = Field(..., min_length=1, max_length=1000, description="Text to synthesize")
    language: str = Field(default="en", description="Language code")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    reference_text: str = Field(default="", description="Transcription of reference audio")

class VoiceCloneResponse(BaseModel):
    """Voice cloning response model"""
    success: bool
    audio_data: Optional[bytes] = None
    content_type: str = "audio/wav"
    size_bytes: int = 0
    language: str
    speed: float
    cloned: bool = True
    error: Optional[str] = None

class ServiceStatus(BaseModel):
    """Service status model"""
    service: str = "june-voice-cloning"
    status: str
    engine: str
    version: str
    device: str
    capabilities: dict
    limits: dict
    performance: dict
