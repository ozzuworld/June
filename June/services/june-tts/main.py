#!/usr/bin/env python3
"""
June TTS Service - Clean LiveKit Integration
Joins ozzu-main room as participant, publishes AI responses
"""
import os
import torch
import logging
import tempfile
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from livekit import rtc
from livekit_token import connect_room_as_publisher
from TTS.api import TTS
import numpy as np
import soundfile as sf

from config import config

# Accept Coqui TTS license
os.environ['COQUI_TOS_AGREED'] = '1'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global TTS and LiveKit instances
tts_instance: Optional[TTS] = None
tts_room: Optional[rtc.Room] = None
audio_source: Optional[rtc.AudioSource] = None
room_connected = False
device = "cuda" if torch.cuda.is_available() else "cpu"

class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize", max_length=5000)
    language: str = Field("en", description="Language code")
    # For XTTS v2, prefer a reference wav; fallback speaker name for other models
    speaker: Optional[str] = Field(None, description="Built-in speaker name (non-XTTS)")
    speaker_wav: Optional[str] = Field(None, description="Path/URL to reference speaker wav (XTTS v2)")
    speed: float = Field(1.0, description="Speech speed", ge=0.5, le=2.0)

class PublishToRoomRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize and publish to room")
    language: str = Field("en", description="Language code")
    speaker: Optional[str] = Field(None, description="Speaker name (non-XTTS)")
    speaker_wav: Optional[str] = Field(None, description="Path/URL to reference speaker wav (XTTS v2)")
    speed: float = Field(1.0, description="Speech speed", ge=0.5, le=2.0)

async def join_livekit_room():
    """Join LiveKit room as TTS participant"""
    global tts_room, audio_source, room_connected
    
    try:
        logger.info("🔊 TTS connecting to LiveKit room via orchestrator token")
        
        # Connect to room using orchestrator-minted token
        tts_room = rtc.Room()
        await connect_room_as_publisher(tts_room, "june-tts")
        
        # Set up event handlers
        @tts_room.on("participant_connected")
        def on_participant_connected(participant):
            logger.info(f"👤 Participant joined room: {participant.identity}")
        
        @tts_room.on("participant_disconnected")
        def on_participant_disconnected(participant):
            logger.info(f"👋 Participant left room: {participant.identity}")
        
        # Create audio source for publishing
        audio_source = rtc.AudioSource(
            sample_rate=24000,  # Match TTS output
            num_channels=1
        )
        
        # Publish audio track
        track = rtc.LocalAudioTrack.create_audio_track("ai-response", audio_source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        
        await tts_room.local_participant.publish_track(track, options)
        
        room_connected = True
        logger.info("✅ TTS connected to ozzu-main room (token via orchestrator)")
        logger.info("🎤 TTS audio track published and ready")
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to LiveKit: {e}")
        room_connected = False

async def publish_audio_to_room(audio_data: bytes):
    """Publish audio data to LiveKit room"""
    global audio_source
    
    if not room_connected or not audio_source:
        logger.error("TTS not connected to room")
        return False
    
    try:
        logger.info(f"🔊 Publishing audio to room ({len(audio_data)} bytes)")
        
        # Save to temp file and read as audio array
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_data)
            temp_path = f.name
        
        try:
            # Read audio file
            audio_array, sample_rate = sf.read(temp_path)
            
            # Ensure float32 and mono
            if audio_array.dtype != np.float32:
                audio_array = audio_array.astype(np.float32)
            
            if len(audio_array.shape) > 1:
                audio_array = audio_array.mean(axis=1)
            
            # Resample if needed
            if sample_rate != 24000:
                from scipy import signal
                num_samples = int(len(audio_array) * 24000 / sample_rate)
                audio_array = signal.resample(audio_array, num_samples)
            
            # Publish in chunks (20ms frames)
            frame_samples = 480  # 20ms at 24kHz
            
            for i in range(0, len(audio_array), frame_samples):
                chunk = audio_array[i:i + frame_samples]
                
                if len(chunk) < frame_samples:
                    chunk = np.pad(chunk, (0, frame_samples - len(chunk)))
                
                frame = rtc.AudioFrame(
                    data=chunk.tobytes(),
                    sample_rate=24000,
                    num_channels=1,
                    samples_per_channel=len(chunk)
                )
                await audio_source.capture_frame(frame)
                await asyncio.sleep(len(chunk) / 24000)
            
            logger.info("✅ Audio published to room successfully")
            return True
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"❌ Error publishing audio: {e}")
        return False

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    global tts_instance
    
    logger.info(f"🚀 Starting June TTS Service on device: {device}")
    
    try:
        logger.info("Loading XTTS-v2 model...")
        model_name = os.getenv("TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
        tts_instance = TTS(model_name=model_name).to(device)
        logger.info("✅ TTS model initialized")
    except Exception as e:
        logger.error(f"❌ TTS initialization failed: {e}")
    
    await join_livekit_room()
    
    yield
    
    logger.info("🛑 Shutting down TTS service")
    if tts_room and room_connected:
        await tts_room.disconnect()

app = FastAPI(
    title="June TTS Service",
    version="2.1.0",
    description="Text-to-speech service with LiveKit room integration",
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
        "service": "june-tts",
        "version": "2.1.0",
        "status": "running",
        "tts_ready": tts_instance is not None,
        "device": device,
        "livekit_connected": room_connected,
        "room": "ozzu-main" if room_connected else None
    }

@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "tts_ready": tts_instance is not None,
        "livekit_connected": room_connected,
        "device": device
    }

@app.post("/synthesize")
async def synthesize_audio(request: TTSRequest):
    if not tts_instance:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            output_path = f.name
        
        logger.info(f"🎤 Synthesizing: {request.text[:50]}...")

        kwargs = {"text": request.text, "language": request.language, "file_path": output_path, "speed": request.speed}
        if request.speaker_wav:
            kwargs["speaker_wav"] = request.speaker_wav
        elif request.speaker:
            kwargs["speaker"] = request.speaker
        
        tts_instance.tts_to_file(**kwargs)
        
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        os.unlink(output_path)
        
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=speech.wav"}
        )
        
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/publish-to-room")
async def publish_to_room(
    request: PublishToRoomRequest,
    background_tasks: BackgroundTasks
):
    if not tts_instance:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    if not room_connected:
        raise HTTPException(status_code=503, detail="Not connected to LiveKit room")
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            output_path = f.name
        
        logger.info(f"🔊 Generating response: {request.text[:100]}...")

        kwargs = {"text": request.text, "language": request.language, "file_path": output_path, "speed": request.speed}
        if request.speaker_wav:
            kwargs["speaker_wav"] = request.speaker_wav
        elif request.speaker:
            kwargs["speaker"] = request.speaker
        
        tts_instance.tts_to_file(**kwargs)
        
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        os.unlink(output_path)
        
        background_tasks.add_task(publish_audio_to_room, audio_bytes)
        
        return {
            "status": "success",
            "text_length": len(request.text),
            "audio_size": len(audio_bytes),
            "message": "Audio being published to room"
        }
        
    except Exception as e:
        logger.error(f"❌ Publish error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/speakers")
async def get_speakers():
    return {
        "speakers": [
            "Claribel Dervla", "Daisy Studious", "Gracie Wise",
            "Andrew Chipper", "Badr Odhiambo", "Antoni Ramirez"
        ],
        "default": "Claribel Dervla"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
