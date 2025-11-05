#!/usr/bin/env python3
"""
CosyVoice2 TTS Service - Clean and Fixed
Ultra-low latency streaming TTS with LiveKit integration
"""

import sys
import os
sys.path.append('/opt/CosyVoice')
sys.path.append('/opt/CosyVoice/third_party/Matcha-TTS')

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from cosyvoice.cli.cosyvoice import CosyVoice2
from livekit import rtc
from config import config
from livekit_token import connect_room_as_publisher

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger("tts-service")

# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class TTSRequest(BaseModel):
    """TTS synthesis request - compatible with orchestrator"""
    text: str = Field(..., description="Text to synthesize")
    room_name: str = Field("ozzu-main", description="LiveKit room name")
    mode: str = Field("sft", description="Synthesis mode (ignored for CosyVoice2)")
    
    # All possible speaker field names for compatibility
    voice: Optional[str] = Field(None, description="Voice/speaker (legacy)")
    speaker: Optional[str] = Field(None, description="Speaker (legacy)")
    speaker_id: Optional[str] = Field(None, description="Speaker ID (legacy)")
    
    # Optional fields
    streaming: bool = Field(True, description="Enable streaming")
    speed: float = Field(1.0, description="Speech speed")
    prompt_audio: Optional[str] = Field(None, description="Reference audio for zero-shot")
    prompt_text: Optional[str] = Field(None, description="Reference text for zero-shot")
    instruct: Optional[str] = Field(None, description="Instruction for instruct mode")
    
    def get_speaker_id(self) -> str:
        """Get effective speaker ID from any field for logging only"""
        return self.speaker_id or self.speaker or self.voice or ""

class TTSResponse(BaseModel):
    """TTS response"""
    status: str
    message: Optional[str] = None
    room_name: Optional[str] = None
    duration_ms: Optional[float] = None
    chunks_sent: Optional[int] = None

class HealthResponse(BaseModel):
    """Health check response"""
    service: str = "cosyvoice2-tts"
    version: str = "1.1.0"
    status: str
    model: str
    device: str
    gpu_available: bool
    livekit_connected: bool

# =============================================================================
# TTS ENGINE
# =============================================================================

class TTSEngine:
    """CosyVoice2 TTS Engine using cross-lingual path (no SFT speakers)."""
    
    def __init__(self):
        self.model = None
        self.device = config.cosyvoice.device
        self.sample_rate = config.cosyvoice.sample_rate
        # Optional registry for reusable zero-shot speakers (disabled by default)
        self.zero_shot_registry = {}
        
    async def initialize(self):
        """Initialize the TTS engine"""
        model_path = config.cosyvoice.model_path
        
        if not os.path.exists(model_path):
            raise RuntimeError(f"Model not found at {model_path}")
        
        logger.info(f"📦 Loading CosyVoice2 from {model_path}")
        
        self.model = CosyVoice2(
            model_path,
            load_jit=config.cosyvoice.load_jit,
            load_trt=config.cosyvoice.load_trt,
            load_vllm=config.cosyvoice.load_vllm,
            fp16=config.cosyvoice.fp16 and self.device == "cuda"
        )
        
        logger.info(f"✅ CosyVoice2 loaded on {self.device}")
    
    async def warmup(self):
        """Warmup the engine"""
        logger.info("🔥 Warming up CosyVoice2 via cross_lingual...")
        start = time.time()
        try:
            for result in self.model.inference_cross_lingual("Hello warmup", None, stream=False):
                break
        except Exception as e:
            logger.warning(f"Warmup cross_lingual failed: {e}")
        elapsed = (time.time() - start) * 1000
        logger.info(f"✅ Warmup complete: {elapsed:.0f}ms")
    
    async def synthesize(self, text: str, stream: bool = True):
        """Synthesize speech using CosyVoice2 cross_lingual (no per-request cloning)."""
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        logger.info(f"🎤 Synthesis (cross_lingual): {text[:100]}...")
        
        try:
            for result in self.model.inference_cross_lingual(text, None, stream=stream):
                audio = result['tts_speech']
                
                if isinstance(audio, torch.Tensor):
                    audio = audio.detach().cpu().numpy()
                
                yield audio
                await asyncio.sleep(0)
                
        except Exception as e:
            logger.error(f"❌ Synthesis failed: {e}")
            raise
    
    def get_speakers(self) -> list:
        """Return empty list; CosyVoice2 cross_lingual has no predefined SFT speakers."""
        return []

# =============================================================================
# LIVEKIT PUBLISHER
# =============================================================================

class LiveKitPublisher:
    """LiveKit audio publisher"""
    
    def __init__(self):
        self.rooms = {}
        self.connected = False
    
    async def initialize(self, default_room: str):
        """Initialize publisher"""
        self.connected = True
        logger.info(f"✅ LiveKit publisher ready")
    
    async def get_room(self, room_name: str) -> rtc.Room:
        """Get or create room connection"""
        if room_name not in self.rooms:
            room = rtc.Room()
            await connect_room_as_publisher(room, "cosyvoice2-tts", room_name)
            self.rooms[room_name] = room
            logger.info(f"✅ Connected to room: {room_name}")
        return self.rooms[room_name]
    
    async def publish_audio(self, room_name: str, audio_stream, sample_rate: int):
        """Publish audio stream to LiveKit room"""
        logger.info(f"🎵 Streaming audio to {room_name}")
        
        room = await self.get_room(room_name)
        
        # Create audio source
        source = rtc.AudioSource(sample_rate, 1)
        track = rtc.LocalAudioTrack.create_audio_track("tts-audio", source)
        
        # Publish track
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        publication = await room.local_participant.publish_track(track, options)
        
        logger.info(f"✅ Track published: {publication.sid}")
        
        chunks_sent = 0
        total_duration = 0.0
        
        try:
            async for audio_chunk in audio_stream:
                # Convert to int16
                audio_int16 = (audio_chunk * 32767).astype(np.int16)
                
                # Create audio frame
                frame = rtc.AudioFrame.create(sample_rate, 1, len(audio_int16))
                frame_data = np.frombuffer(frame.data, dtype=np.int16)
                np.copyto(frame_data, audio_int16)
                
                # Publish frame
                await source.capture_frame(frame)
                
                chunks_sent += 1
                total_duration += len(audio_chunk) / sample_rate
                
            logger.info(f"✅ Stream complete: {chunks_sent} chunks, {total_duration:.1f}s")
            
        finally:
            # Unpublish track
            await room.local_participant.unpublish_track(publication.sid)
        
        return {
            "chunks_sent": chunks_sent,
            "duration_seconds": total_duration
        }

# Global instances
engine: Optional[TTSEngine] = None
publisher: Optional[LiveKitPublisher] = None

# =============================================================================
# APPLICATION LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    global engine, publisher
    
    logger.info("🚀 Starting TTS Service")
    
    # Initialize engine
    engine = TTSEngine()
    await engine.initialize()
    await engine.warmup()
    
    # Initialize publisher
    publisher = LiveKitPublisher()
    await publisher.initialize(config.livekit.default_room)
    
    logger.info("✅ Service ready")
    
    yield
    
    logger.info("🛑 Shutting down")

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="CosyVoice2 TTS Service",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.service.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.post("/api/tts/synthesize", response_model=TTSResponse)
async def synthesize(request: TTSRequest):
    """Synthesize speech and stream to LiveKit (CosyVoice2 cross_lingual)."""
    if not engine or not publisher:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    start_time = time.time()
    resolved_speaker = request.get_speaker_id()
    
    logger.info(f"🎤 TTS request: room={request.room_name}, mode={request.mode}")
    logger.info(f"   Speaker fields: speaker_id={request.speaker_id}, speaker={request.speaker}, voice={request.voice}")
    logger.info(f"   (CosyVoice2) Ignoring speaker fields; using cross_lingual path.")
    logger.info(f"   Text: {request.text[:200]}...")
    
    try:
        # Generate audio stream (cross_lingual)
        audio_stream = engine.synthesize(request.text, request.streaming)
        
        # Publish to LiveKit
        result = await publisher.publish_audio(request.room_name, audio_stream, engine.sample_rate)
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(f"✅ Complete: {duration_ms:.0f}ms, {result['chunks_sent']} chunks")
        
        return TTSResponse(
            status="completed",
            message="Success",
            room_name=request.room_name,
            duration_ms=duration_ms,
            chunks_sent=result["chunks_sent"]
        )
        
    except Exception as e:
        logger.error(f"❌ Synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
@app.get("/healthz")
async def health_check():
    """Health check"""
    return HealthResponse(
        status="healthy",
        model=config.cosyvoice.model_name,
        device=config.cosyvoice.device,
        gpu_available=torch.cuda.is_available(),
        livekit_connected=publisher.connected if publisher else False
    )

@app.get("/speakers")
async def list_speakers():
    """List available speakers (none for CosyVoice2 cross_lingual)."""
    return {"speakers": engine.get_speakers() if engine else []}

@app.get("/")
async def root():
    """Service info"""
    return {
        "service": "cosyvoice2-tts",
        "version": "1.1.0",
        "status": "healthy"
    }

@app.get("/debug")
async def debug_info():
    """Debug information"""
    if not engine:
        return {"error": "Engine not initialized"}
    
    return {
        "engine_initialized": engine is not None,
        "model_loaded": engine.model is not None if engine else False,
        "available_speakers": engine.get_speakers() if engine else [],
        "speaker_count": len(engine.get_speakers()) if engine else 0,
        "device": engine.device if engine else "unknown",
        "sample_rate": engine.sample_rate if engine else 0,
        "model_path": config.cosyvoice.model_path,
        "livekit_connected": publisher.connected if publisher else False
    }

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.service.host,
        port=config.service.port,
        log_level="info"
    )
