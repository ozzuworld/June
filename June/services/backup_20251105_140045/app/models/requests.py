"""Request models for the June Orchestrator"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class STTWebhookPayload(BaseModel):
    """STT webhook payload model"""
    event: str
    room_name: str
    participant: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: str
    segments: Optional[List[Dict[str, Any]]] = []
    audio_data: Optional[bytes] = None
    transcript_id: Optional[str] = None
    partial: bool = Field(False, description="Whether this is a partial transcript")
    
    # Streaming metadata
    utterance_id: Optional[str] = None
    partial_sequence: Optional[int] = None
    is_streaming: Optional[bool] = None
    streaming_metadata: Optional[Dict[str, Any]] = None


class TTSPublishRequest(BaseModel):
    """TTS publish request model"""
    text: str
    language: str = "en"
    speaker: Optional[str] = None
    speaker_wav: Optional[str] = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
    exaggeration: float = Field(0.6, ge=0.0, le=2.0)
    cfg_weight: float = Field(0.8, ge=0.1, le=1.0)
    streaming: bool = Field(False, description="Enable streaming TTS")


class SessionCreateRequest(BaseModel):
    """Session creation request"""
    user_id: str
    room_name: Optional[str] = None


class MessageAddRequest(BaseModel):
    """Add message to session request"""
    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = None