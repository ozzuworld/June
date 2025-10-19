#!/usr/bin/env python3
"""
June STT Service - Clean LiveKit Integration
Joins ozzu-main room as participant, transcribes audio in real-time
"""
import os
import asyncio
import logging
import tempfile
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from livekit import rtc, api
import httpx

from config import config
from whisper_service import whisper_service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global LiveKit room participant
stt_room: Optional[rtc.Room] = None
room_connected = False

class TranscriptionResponse(BaseModel):
    transcript_id: str
    text: str
    language: Optional[str] = None
    processing_time_ms: int
    timestamp: datetime

async def join_livekit_room():
    """Join LiveKit room as STT participant"""
    global stt_room, room_connected
    
    try:
        logger.info("🔌 STT connecting to LiveKit room: ozzu-main")
        
        # Generate access token
        token = api.AccessToken(
            api_key=config.LIVEKIT_API_KEY,
            api_secret=config.LIVEKIT_API_SECRET
        )
        token.with_identity("june-stt")
        token.with_name("STT Service")
        token.with_grants(
            api.VideoGrants(
                room_join=True,
                room="ozzu-main",
                can_subscribe=True,    # Listen to audio
                can_publish=False,     # Don't publish audio
                can_publish_data=True  # Can send data messages
            )
        )
        
        access_token = token.to_jwt()
        
        # Connect to room
        stt_room = rtc.Room()
        
        # Set up event handlers BEFORE connecting
        @stt_room.on("track_subscribed")
        async def on_track_subscribed(track: rtc.Track, publication, participant):
            logger.info(f"🎤 New audio track from {participant.identity}: {track.kind}")
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                await process_audio_track(track, participant.identity)
        
        @stt_room.on("participant_connected")
        def on_participant_connected(participant):
            logger.info(f"👤 Participant joined: {participant.identity}")
        
        @stt_room.on("participant_disconnected")
        def on_participant_disconnected(participant):
            logger.info(f"👋 Participant left: {participant.identity}")
        
        # Connect to room
        await stt_room.connect(config.LIVEKIT_WS_URL, access_token)
        room_connected = True
        
        logger.info("✅ STT connected to ozzu-main room")
        logger.info("🎤 Listening for audio tracks to transcribe...")
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to LiveKit: {e}")
        room_connected = False

async def process_audio_track(track: rtc.AudioTrack, participant_identity: str):
    """Process incoming audio track for transcription"""
    try:
        logger.info(f"🎵 Processing audio from {participant_identity}")
        
        audio_stream = rtc.AudioStream(track)
        audio_buffer = []
        
        # Collect audio frames for a few seconds
        async for frame in audio_stream:
            audio_buffer.append(frame.data)
            
            # Process every 3 seconds of audio
            if len(audio_buffer) >= 72:  # ~3 seconds at 24kHz
                await transcribe_audio_buffer(audio_buffer, participant_identity)
                audio_buffer = []
                
    except Exception as e:
        logger.error(f"❌ Audio processing error: {e}")

async def transcribe_audio_buffer(audio_buffer: list, participant_identity: str):
    """Transcribe collected audio buffer"""
    try:
        if not whisper_service.is_model_ready():
            logger.warning("Whisper model not ready, skipping transcription")
            return
        
        # Save audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            # Combine audio frames (simplified - you may need proper audio processing)
            combined_audio = b''.join(audio_buffer)
            f.write(combined_audio)
            temp_path = f.name
        
        try:
            # Transcribe
            result = await whisper_service.transcribe(temp_path)
            
            if result["text"].strip():
                logger.info(f"📝 Transcribed from {participant_identity}: {result['text'][:100]}...")
                
                # Send to orchestrator
                await notify_orchestrator({
                    "user_id": participant_identity,
                    "text": result["text"],
                    "language": result.get("language"),
                    "room_name": "ozzu-main",
                    "timestamp": datetime.utcnow().isoformat()
                })
        
        finally:
            # Cleanup temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"❌ Transcription error: {e}")

async def notify_orchestrator(transcript_data: dict):
    """Send transcript to orchestrator webhook"""
    try:
        if not config.ORCHESTRATOR_URL:
            return
            
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config.ORCHESTRATOR_URL}/api/webhooks/transcript",
                json=transcript_data,
                headers={"Authorization": f"Bearer {config.ORCHESTRATOR_API_KEY}"}
            )
            
            if response.status_code == 200:
                logger.info("✅ Transcript sent to orchestrator")
            else:
                logger.warning(f"⚠️ Orchestrator webhook failed: {response.status_code}")
                
    except Exception as e:
        logger.warning(f"⚠️ Failed to notify orchestrator: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    logger.info("🚀 Starting June STT Service with LiveKit Integration")
    
    # Initialize Whisper model
    try:
        await whisper_service.initialize()
        logger.info("✅ Whisper model initialized")
    except Exception as e:
        logger.error(f"❌ Whisper initialization failed: {e}")
    
    # Connect to LiveKit room
    await join_livekit_room()
    
    yield
    
    # Cleanup on shutdown
    logger.info("🛑 Shutting down STT service")
    if stt_room and room_connected:
        await stt_room.disconnect()
    whisper_service.cleanup()

# FastAPI app
app = FastAPI(
    title="June STT Service",
    version="2.0.0",
    description="Speech-to-text service with LiveKit room integration",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "service": "june-stt",
        "version": "2.0.0",
        "status": "running",
        "whisper_ready": whisper_service.is_model_ready(),
        "livekit_connected": room_connected,
        "room": "ozzu-main" if room_connected else None
    }

@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "whisper_ready": whisper_service.is_model_ready(),
        "livekit_connected": room_connected
    }

# Direct API endpoint for testing
@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_direct(audio_file: UploadFile = File(...)):
    """Direct transcription endpoint for testing (bypasses LiveKit)"""
    if not whisper_service.is_model_ready():
        raise HTTPException(status_code=503, detail="Whisper model not ready")
    
    # Validate file
    if not audio_file.content_type or not audio_file.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="File must be audio")
    
    # Save temp file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        content = await audio_file.read()
        f.write(content)
        temp_path = f.name
    
    try:
        # Transcribe
        result = await whisper_service.transcribe(temp_path)
        
        return TranscriptionResponse(
            transcript_id="direct-api",
            text=result["text"],
            language=result.get("language"),
            processing_time_ms=result["processing_time_ms"],
            timestamp=datetime.utcnow()
        )
    
    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)