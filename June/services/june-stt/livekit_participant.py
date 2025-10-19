# June/services/june-stt/app.py - Complete Event-Driven Version
"""
June STT Service - Event-Driven Architecture
Joins LiveKit room as participant, transcribes audio, notifies orchestrator
"""
import os
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Header, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import config
from whisper_service import whisper_service
from livekit_participant import start_stt_participant, stt_participant

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Simple auth fallback
async def simple_auth(authorization: str = Header(None)) -> Dict[str, str]:
    return {"user_id": "fallback_user"}

# Response models
class TranscriptionResponse(BaseModel):
    transcript_id: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    processing_time_ms: int
    timestamp: datetime

class RoomStatus(BaseModel):
    connected: bool
    room_name: str
    participant_identity: str
    active_tracks: int

# App lifecycle with LiveKit initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("🚀 June STT Service v5.0.0 - Event-Driven Architecture")
    logger.info("=" * 60)
    
    # Initialize Whisper model
    try:
        await whisper_service.initialize()
        logger.info("✅ Whisper model initialized")
    except Exception as e:
        logger.error(f"❌ Whisper initialization failed: {e}")
    
    # Connect to LiveKit room as participant
    try:
        logger.info("🔌 Connecting to LiveKit room as STT participant...")
        
        # Start STT participant in background
        asyncio.create_task(start_stt_participant("ozzu-main"))
        
        # Give it a moment to connect
        await asyncio.sleep(2)
        
        if stt_participant and stt_participant.is_connected:
            logger.info("✅ STT connected to LiveKit room: ozzu-main")
            logger.info("🎤 Listening for audio tracks to transcribe...")
        else:
            logger.warning("⚠️ STT participant connection pending...")
            
    except Exception as e:
        logger.error(f"❌ LiveKit connection failed: {e}")
        logger.warning("⚠️ Service will work for direct API calls only")
    
    logger.info("=" * 60)
    logger.info("✅ Service ready")
    logger.info("=" * 60)
    
    yield
    
    # Cleanup
    logger.info("🛑 Shutting down...")
    
    if stt_participant:
        await stt_participant.disconnect()
    
    whisper_service.cleanup()
    logger.info("✅ Shutdown complete")

# FastAPI app
app = FastAPI(
    title="June STT Service - Event-Driven",
    version="5.0.0",
    description="Speech-to-text with LiveKit room participant capability",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Health & Status Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Service information"""
    return {
        "service": "June STT Service",
        "version": "5.0.0",
        "architecture": "event-driven",
        "status": "ready" if whisper_service.is_model_ready() else "initializing",
        "model": {
            "name": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "compute_type": config.WHISPER_COMPUTE_TYPE,
            "ready": whisper_service.is_model_ready()
        },
        "livekit": {
            "connected": stt_participant.is_connected if stt_participant else False,
            "room": stt_participant.room_name if stt_participant else None
        },
        "orchestrator": {
            "webhook_enabled": config.ORCHESTRATOR_ENABLED,
            "url": config.ORCHESTRATOR_URL if config.ORCHESTRATOR_ENABLED else None
        }
    }

@app.get("/healthz")
async def health():
    """Kubernetes health check"""
    return {
        "status": "healthy",
        "service": "june-stt",
        "version": "5.0.0",
        "model_ready": whisper_service.is_model_ready(),
        "livekit_connected": stt_participant.is_connected if stt_participant else False
    }

@app.get("/ready")
async def readiness():
    """Kubernetes readiness check"""
    ready = whisper_service.is_model_ready()
    
    if ready:
        return {"status": "ready"}
    else:
        raise HTTPException(status_code=503, detail="Model not ready")

@app.get("/livekit/status", response_model=RoomStatus)
async def livekit_status():
    """LiveKit connection status"""
    if not stt_participant:
        raise HTTPException(status_code=503, detail="STT participant not initialized")
    
    return RoomStatus(
        connected=stt_participant.is_connected,
        room_name=stt_participant.room_name,
        participant_identity="june-stt",
        active_tracks=len(stt_participant.active_transcriptions)
    )

# ============================================================================
# Traditional API Endpoint (for backward compatibility)
# ============================================================================

@app.post("/v1/transcribe", response_model=TranscriptionResponse)
async def transcribe_api(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    room_name: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    auth_data: dict = Depends(simple_auth)
):
    """
    Traditional transcription API endpoint
    
    This endpoint is for:
    - Direct API calls (not via LiveKit room)
    - Testing and debugging
    - Backward compatibility
    
    For real-time conversation, use LiveKit room instead.
    """
    # Validate file
    if not audio_file.content_type or not audio_file.content_type.startswith(('audio/', 'video/')):
        raise HTTPException(status_code=400, detail="File must be audio or video")
    
    max_size = config.MAX_FILE_SIZE_MB * 1024 * 1024
    if audio_file.size and audio_file.size > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {config.MAX_FILE_SIZE_MB}MB)"
        )
    
    # Wait for model
    if not whisper_service.is_model_ready():
        raise HTTPException(status_code=503, detail="Model not ready")
    
    try:
        transcript_id = str(uuid.uuid4())
        
        # Save temp file
        temp_path = f"/tmp/stt_{transcript_id}_{audio_file.filename}"
        try:
            with open(temp_path, "wb") as f:
                content = await audio_file.read()
                f.write(content)
            
            logger.info(f"🎵 Transcribing {audio_file.filename} ({len(content)} bytes)")
            
            # Transcribe
            result = await whisper_service.transcribe(temp_path, language)
            
            # Create response
            response = TranscriptionResponse(
                transcript_id=transcript_id,
                text=result["text"],
                language=result.get("language"),
                confidence=result.get("language_probability"),
                processing_time_ms=result["processing_time_ms"],
                timestamp=datetime.utcnow()
            )
            
            logger.info(f"✅ Transcription complete: {transcript_id}")
            return response
            
        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"❌ Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Debug & Management Endpoints
# ============================================================================

@app.post("/livekit/reconnect")
async def reconnect_to_room(room_name: str = "ozzu-main"):
    """
    Manually reconnect to LiveKit room
    Useful for debugging or room switching
    """
    global stt_participant
    
    try:
        # Disconnect if connected
        if stt_participant and stt_participant.is_connected:
            await stt_participant.disconnect()
        
        # Reconnect
        asyncio.create_task(start_stt_participant(room_name))
        await asyncio.sleep(2)
        
        if stt_participant and stt_participant.is_connected:
            return {
                "status": "success",
                "room_name": room_name,
                "message": "Reconnected to LiveKit room"
            }
        else:
            raise HTTPException(status_code=500, detail="Reconnection failed")
            
    except Exception as e:
        logger.error(f"❌ Reconnection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_stats():
    """Service statistics"""
    return {
        "whisper": {
            "model": config.WHISPER_MODEL,
            "device": config.WHISPER_DEVICE,
            "ready": whisper_service.is_model_ready()
        },
        "livekit": {
            "connected": stt_participant.is_connected if stt_participant else False,
            "room": stt_participant.room_name if stt_participant else None,
            "active_transcriptions": len(stt_participant.active_transcriptions) if stt_participant else 0
        },
        "config": {
            "max_file_size_mb": config.MAX_FILE_SIZE_MB,
            "orchestrator_enabled": config.ORCHESTRATOR_ENABLED
        }
    }

# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.PORT,
        log_level="info"
    )