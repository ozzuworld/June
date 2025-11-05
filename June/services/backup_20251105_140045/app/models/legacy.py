"""Legacy models for backward compatibility - Phase 1"""
from pydantic import BaseModel
from typing import Optional, Dict, Any


class SessionCreate(BaseModel):
    """Create session request"""
    user_id: str
    room_name: Optional[str] = None


class SessionResponse(BaseModel):
    """Session information with LiveKit connection details"""
    session_id: str
    user_id: str
    room_name: str
    access_token: str
    livekit_url: str
    created_at: str  # ISO format datetime
    status: str


class LiveKitWebhook(BaseModel):
    """LiveKit webhook event"""
    event: str
    room: Optional[Dict[str, Any]] = None
    participant: Optional[Dict[str, Any]] = None
    track: Optional[Dict[str, Any]] = None
    created_at: int
    id: str


class GuestTokenRequest(BaseModel):
    """Request for guest access token"""
    session_id: str
    guest_name: str


class GuestTokenResponse(BaseModel):
    """Guest access token response"""
    access_token: str
    room_name: str
    livekit_ws_url: str
    guest_name: str


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