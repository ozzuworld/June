"""Response models for the June Orchestrator"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from .domain import SessionStats


class WebhookResponse(BaseModel):
    """Standard webhook response"""
    status: str
    message: Optional[str] = None
    session_id: Optional[str] = None
    ai_response: Optional[str] = None
    processing_time_ms: Optional[float] = None
    first_token_ms: Optional[float] = None
    
    # Streaming specific fields
    concurrent_tts_used: Optional[bool] = None
    streaming_mode: Optional[bool] = None
    utterance_id: Optional[str] = None
    partial_sequence: Optional[int] = None
    
    # Skill specific fields
    skill_name: Optional[str] = None
    skill_state: Optional[Dict[str, Any]] = None
    voice_cloning_used: Optional[bool] = None
    
    # Natural flow fields
    pipeline_mode: Optional[str] = None
    trigger_reason: Optional[str] = None
    waiting_for: Optional[str] = None
    reason: Optional[str] = None


class SessionResponse(BaseModel):
    """Session response model"""
    session_id: str
    user_id: str
    room_name: str
    access_token: Optional[str] = None
    created_at: str
    last_activity: str
    status: str
    message_count: int
    total_tokens: int
    livekit_url: Optional[str] = None
    skill_state: Optional[Dict[str, Any]] = None


class StreamingStatus(BaseModel):
    """Streaming pipeline status"""
    natural_streaming_pipeline: Dict[str, Any]
    natural_flow_settings: Dict[str, Any]
    active_sessions: Dict[str, Any]
    natural_pipeline_flow: Dict[str, str]
    improvements: Dict[str, Any]
    target_achieved: bool


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    service: str
    version: str
    issues: List[str]
    stats: SessionStats
    voice_registry: Dict[str, Any]
    security: Dict[str, Any]
    features: Dict[str, Any]


class ServiceInfoResponse(BaseModel):
    """Service information response"""
    service: str
    version: str
    description: str
    features: List[str]
    skills: Dict[str, Any]
    endpoints: Dict[str, str]
    stats: SessionStats
    voice_profiles: Dict[str, Any]
    voice_registry: Dict[str, Any]
    security: Dict[str, Any]
    config: Dict[str, Any]


class JellyfinTokenResponse(BaseModel):
    """Jellyfin token exchange response"""
    access_token: str
    user_id: str
    server_id: str
    username: str