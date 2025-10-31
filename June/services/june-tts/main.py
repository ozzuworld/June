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

# Enable detailed debug logs for LiveKit and our app
os.environ.setdefault("RUST_LOG", "livekit=debug,livekit_api=debug,livekit_ffi=debug,livekit_rtc=debug")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("june-tts")

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

def process_audio_for_livekit(audio_array, source_sample_rate=24000, target_sample_rate=24000):
    """Process audio array for LiveKit with proper format conversion"""
    # Ensure float32 format
    if audio_array.dtype != np.float32:
        audio_array = audio_array.astype(np.float32)
    
    # Convert to mono if stereo
    if len(audio_array.shape) > 1:
        audio_array = audio_array.mean(axis=1)
    
    # Normalize audio to prevent clipping
    max_val = np.abs(audio_array).max()
    if max_val > 0.95:
        audio_array = audio_array * (0.95 / max_val)
    
    # Use librosa for better resampling if available, fallback to scipy
    if source_sample_rate != target_sample_rate:
        try:
            import librosa
            audio_array = librosa.resample(audio_array, orig_sr=source_sample_rate, target_sr=target_sample_rate)
        except ImportError:
            logger.warning("librosa not available, using scipy for resampling")
            from scipy import signal
            num_samples = int(len(audio_array) * target_sample_rate / source_sample_rate)
            audio_array = signal.resample(audio_array, num_samples)
    
    # Convert to int16 for LiveKit (this is crucial for audio quality)
    audio_int16 = (audio_array * 32767).astype(np.int16)
    
    return audio_int16

async def join_livekit_room():
    """Join LiveKit room as TTS participant"""
    global tts_room, audio_source, room_connected

    try:
        logger.debug("Preparing to obtain LiveKit token and connect as publisher")
        tts_room = rtc.Room()

        # Attach granular event hooks for diagnosis
        @tts_room.on("connecting")
        def on_connecting():
            logger.debug("[LiveKit] Room connecting...")

        @tts_room.on("connected")
        def on_connected():
            logger.debug("[LiveKit] Room connected")

        @tts_room.on("reconnecting")
        def on_reconnecting():
            logger.debug("[LiveKit] Room reconnecting...")

        @tts_room.on("reconnected")
        def on_reconnected():
            logger.debug("[LiveKit] Room reconnected")

        @tts_room.on("disconnected")
        def on_disconnected():
            logger.debug("[LiveKit] Room disconnected")

        @tts_room.on("participant_connected")
        def on_participant_connected(participant):
            logger.debug(f"[LiveKit] Participant connected: {participant.identity}")

        @tts_room.on("participant_disconnected")
        def on_participant_disconnected(participant):
            logger.debug(f"[LiveKit] Participant disconnected: {participant.identity}")

        @tts_room.on("track_published")
        def on_track_published(publication):
            logger.debug(f"[LiveKit] Track published: {publication.track_name}")

        @tts_room.on("track_unpublished")
        def on_track_unpublished(publication):
            logger.debug(f"[LiveKit] Track unpublished: {publication.track_name}")

        logger.info("🔊 TTS connecting to LiveKit room via orchestrator token")
        await connect_room_as_publisher(tts_room, "june-tts")
        logger.debug("[LiveKit] connect() finished")

        # Create audio source for publishing (removed unsupported queue_size_ms parameter)
        logger.debug("Creating AudioSource and LocalAudioTrack")
        audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("ai-response", audio_source)

        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE

        logger.debug("Publishing audio track ...")
        await tts_room.local_participant.publish_track(track, options)
        logger.info("🎤 TTS audio track published")

        room_connected = True
        logger.info("✅ TTS connected to ozzu-main room (token via orchestrator)")

    except Exception as e:
        logger.exception(f"❌ Failed to connect or publish to LiveKit: {e}")
        room_connected = False

async def publish_audio_to_room(audio_data: bytes):
    """Improved audio publishing with better error handling and frame processing"""
    global audio_source

    if not room_connected or not audio_source:
        logger.error("TTS not connected to room or audio_source not ready")
        return False

    try:
        logger.debug(f"Processing audio data, size: {len(audio_data)} bytes")
        
        # Load and process audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_data)
            temp_path = f.name
        
        try:
            audio_array, sample_rate = sf.read(temp_path)
            logger.debug(f"Loaded audio: sr={sample_rate}, shape={audio_array.shape}, dtype={audio_array.dtype}")
            
            # Process audio with improved method
            processed_audio = process_audio_for_livekit(audio_array, sample_rate, 24000)
            
            # Create frames with exact 20ms chunks (480 samples @ 24kHz)
            frame_samples = 480
            samples_sent = 0
            
            for i in range(0, len(processed_audio), frame_samples):
                chunk = processed_audio[i:i + frame_samples]
                
                # Pad if necessary
                if len(chunk) < frame_samples:
                    chunk = np.pad(chunk, (0, frame_samples - len(chunk)), mode='constant')
                
                # Create AudioFrame with int16 data
                frame = rtc.AudioFrame(
                    data=chunk.tobytes(),
                    sample_rate=24000,
                    num_channels=1,
                    samples_per_channel=len(chunk)
                )
                
                # Use try-catch for frame capture to handle any issues
                try:
                    await audio_source.capture_frame(frame)
                    samples_sent += len(chunk)
                    
                    # Precise timing: 20ms per frame
                    await asyncio.sleep(0.02)  # 20ms
                    
                except Exception as e:
                    logger.warning(f"Frame capture failed: {e}")
                    # Continue with next frame rather than failing completely
                    continue
            
            logger.info(f"✅ Audio published successfully: {samples_sent} samples")
            return True
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.exception(f"❌ Error publishing audio: {e}")
        return False

@asynccontextmanager
async def lifespan(app: FastAPI):
    global tts_instance
    logger.info(f"🚀 Starting June TTS Service on device: {device}")
    try:
        model_name = os.getenv("TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
        logger.debug(f"Loading TTS model: {model_name} on device {device}")
        tts_instance = TTS(model_name=model_name).to(device)
        logger.info("✅ TTS model initialized")
    except Exception as e:
        logger.exception(f"❌ TTS initialization failed: {e}")

    await join_livekit_room()
    yield

    logger.info("🛑 Shutting down TTS service")
    if tts_room and room_connected:
        await tts_room.disconnect()

app = FastAPI(
    title="June TTS Service",
    version="2.3.2",
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
        "version": "2.3.2",
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
        logger.info(f"🎤 Synthesizing: {request.text[:80]}...")
        kwargs = {
            "text": request.text, 
            "language": request.language, 
            "file_path": output_path, 
            "speed": request.speed,
            "split_sentences": True  # This can improve quality
        }
        if request.speaker_wav:
            kwargs["speaker_wav"] = request.speaker_wav
        elif request.speaker:
            kwargs["speaker"] = request.speaker
        tts_instance.tts_to_file(**kwargs)
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        os.unlink(output_path)
        return Response(content=audio_bytes, media_type="audio/wav", headers={"Content-Disposition": "attachment; filename=speech.wav"})
    except Exception as e:
        logger.exception(f"❌ Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/publish-to-room")
async def publish_to_room(request: PublishToRoomRequest, background_tasks: BackgroundTasks):
    if not tts_instance:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    if not room_connected:
        raise HTTPException(status_code=503, detail="Not connected to LiveKit room")
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            output_path = f.name
        logger.info(f"🔊 Generating response: {request.text[:100]}...")
        kwargs = {
            "text": request.text, 
            "language": request.language, 
            "file_path": output_path, 
            "speed": request.speed,
            "split_sentences": True  # This can improve quality
        }
        if request.speaker_wav:
            kwargs["speaker_wav"] = request.speaker_wav
        elif request.speaker:
            kwargs["speaker"] = request.speaker
        tts_instance.tts_to_file(**kwargs)
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        os.unlink(output_path)
        background_tasks.add_task(publish_audio_to_room, audio_bytes)
        return {"status": "success", "text_length": len(request.text), "audio_size": len(audio_bytes), "message": "Audio being published to room"}
    except Exception as e:
        logger.exception(f"❌ Publish error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/token")
async def debug_token():
    """Return current connection parameters for diagnostics"""
    base = os.getenv("ORCHESTRATOR_URL", getattr(config, "ORCHESTRATOR_URL", "http://june-orchestrator.june-services.svc.cluster.local:8080"))
    ws = os.getenv("LIVEKIT_WS_URL", getattr(config, "LIVEKIT_WS_URL", "ws://livekit-livekit-server.june-services.svc.cluster.local:80"))
    return {"orchestrator_url": base, "livekit_ws_url": ws, "device": device}

@app.get("/debug/audio-test")
async def test_audio_generation():
    """Generate a test tone to verify audio pipeline"""
    if not room_connected:
        return {"error": "Not connected to room"}
    
    # Generate a simple test tone
    duration = 2.0  # seconds
    sample_rate = 24000
    frequency = 440.0  # A4 note
    
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    tone = np.sin(2 * np.pi * frequency * t) * 0.3  # 30% volume
    tone_int16 = (tone * 32767).astype(np.int16)
    
    # Save as WAV and publish
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        sf.write(f.name, tone_int16, sample_rate)
        with open(f.name, "rb") as audio_file:
            audio_bytes = audio_file.read()
        os.unlink(f.name)
    
    success = await publish_audio_to_room(audio_bytes)
    return {"test_tone_published": success, "duration": duration, "frequency": frequency}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)