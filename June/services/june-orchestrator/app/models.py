"""Data models"""
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime


class SessionCreate(BaseModel):
    """Create session request"""
    user_id: str
    room_name: Optional[str] = None


class SessionResponse(BaseModel):
    """Session information with LiveKit integration"""
    session_id: str
    user_id: str
    room_name: str
    livekit_room_sid: Optional[str] = None
    access_token: Optional[str] = None
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


class ParticipantInfo(BaseModel):
    """Participant information"""
    identity: str
    name: str
    sid: str
    state: str
    joined_at: int
    metadata: Optional[str] = None


class RoomInfo(BaseModel):
    """Room information"""
    room_name: str
    room_sid: str
    creation_time: int
    max_participants: int
    num_participants: int
    metadata: Optional[str] = None
    participants: List[ParticipantInfo] = []


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