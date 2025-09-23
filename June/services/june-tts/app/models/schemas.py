from pydantic import BaseModel, Field, validator
from typing import Optional, List
from app.core.config import settings

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Text to convert to speech")
    language: str = Field(default="EN", description="Target language code")
    speaker_key: Optional[str] = Field(None, description="Specific speaker identifier")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    
    @validator('language')
    def validate_language(cls, v):
        supported = ['EN', 'ES', 'FR', 'ZH', 'JP', 'KR']
        if v.upper() not in supported:
            raise ValueError(f'Language must be one of: {supported}')
        return v.upper()

class CloneRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="Text to convert to speech")
    language: str = Field(default="EN", description="Target language code")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    
    @validator('language')
    def validate_language(cls, v):
        supported = ['EN', 'ES', 'FR', 'ZH', 'JP', 'KR']
        if v.upper() not in supported:
            raise ValueError(f'Language must be one of: {supported}')
        return v.upper()

class AudioResponse(BaseModel):
    success: bool
    message: str
    audio_format: str = "wav"

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
