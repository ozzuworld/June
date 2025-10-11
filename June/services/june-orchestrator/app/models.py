"""
Pydantic Models
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ChatRequest(BaseModel):
    """Chat request model"""
    text: str
    language: str = "en"
    temperature: float = 0.7
    include_audio: bool = True


class ChatResponse(BaseModel):
    """Chat response model"""
    message: dict
    audio: Optional[dict] = None
    response_time_ms: int
    timestamp: datetime


class LiveKitTokenRequest(BaseModel):
    """LiveKit token request"""
    user_id: str
    room_name: Optional[str] = None


class LiveKitTokenResponse(BaseModel):
    """LiveKit token response"""
    token: str
    url: str
    room_name: str


class TranscriptWebhook(BaseModel):
    """STT webhook payload"""
    transcript_id: str
    user_id: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    session_id: Optional[str] = None
    timestamp: datetime