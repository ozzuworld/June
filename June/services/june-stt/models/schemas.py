"""Pydantic schemas for June STT API"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class TranscriptionRequest(BaseModel):
    """Request schema for transcription endpoint"""
    model: Optional[str] = None
    language: Optional[str] = None
    response_format: Optional[str] = "json"

class TranscriptionResponse(BaseModel):
    """Response schema for transcription endpoint"""
    text: str
    language: Optional[str] = None
    segments: Optional[List[Dict[str, Any]]] = None
    method: Optional[str] = None
    optimization: Optional[str] = None

class PartialTranscriptEvent(BaseModel):
    """Schema for partial transcript events"""
    transcript_id: str
    user_id: str
    participant: str
    event: str = "partial_transcript"
    text: str
    language: Optional[str] = None
    timestamp: datetime
    room_name: str
    partial: bool = True
    utterance_id: Optional[str] = None
    partial_sequence: int = 0
    is_streaming: bool = True
    sota_optimized: bool = False
    streaming_metadata: Optional[Dict[str, Any]] = None

class FinalTranscriptEvent(BaseModel):
    """Schema for final transcript events"""
    transcript_id: str
    user_id: str
    participant: str
    event: str = "transcript"
    text: str
    language: Optional[str] = None
    timestamp: datetime
    room_name: str
    partial: bool = False

class HealthResponse(BaseModel):
    """Schema for health check response"""
    status: str
    version: str
    optimization: str
    components: Dict[str, Any]
    features: Dict[str, Any]
    sota_performance: Dict[str, Any]

class PerformanceStats(BaseModel):
    """Schema for performance statistics"""
    uptime_seconds: float
    total_partials: int
    total_finals: int
    ultra_fast_partials: int
    ultra_fast_rate: str
    avg_partial_processing_ms: float
    avg_final_processing_ms: float
    min_partial_processing_ms: float
    max_partial_processing_ms: float
    partials_per_minute: float

class UtteranceStats(BaseModel):
    """Schema for utterance statistics"""
    total_participants: int
    active_utterances: int
    ultra_fast_triggered: int
    sota_optimized: int
    optimization_rate: str

class RoomStats(BaseModel):
    """Schema for room statistics"""
    connected: bool
    livekit_enabled: bool
    active_audio_buffers: int
    total_participants: int
    excluded_participants: List[str]

class OrchestratorStats(BaseModel):
    """Schema for orchestrator statistics"""
    available: bool
    partial_transcripts_sent: int
    url_configured: bool
