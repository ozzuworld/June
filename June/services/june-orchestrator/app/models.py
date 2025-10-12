"""Data models"""
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class SessionCreate(BaseModel):
    """Create session request"""
    user_id: str
    room_name: Optional[str] = None


class SessionResponse(BaseModel):
    """Session information"""
    session_id: str
    user_id: str
    room_id: int
    janus_room_id: int
    created_at: datetime
    status: str


class JanusEvent(BaseModel):
    """Janus event from event handler"""
    type: int
    timestamp: int
    session_id: Optional[int] = None
    handle_id: Optional[int] = None
    event: Dict[str, Any]


class AIRequest(BaseModel):
    """AI generation request"""
    session_id: str
    text: str
    language: str = "en"


class AIResponse(BaseModel):
    """AI response"""
    session_id: str
    text: str
    audio_url: Optional[str] = None
    processing_time_ms: int