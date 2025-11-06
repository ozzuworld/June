#!/usr/bin/env python3
"""
CosyVoice2 TTS Service - Clean Implementation
Based on official CosyVoice2 patterns from FunAudioLLM/CosyVoice
"""

import sys
import os

# Add CosyVoice paths (REQUIRED)
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

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("cosyvoice2-tts")

# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class TTSRequest(BaseModel):
    """TTS request"""
    text: str
    room_name: str = "ozzu-main"
    streaming: bool = True
    
class TTSResponse(BaseModel):
    """TTS response"""
    status: str
    message: Optional[str] = None
    duration_ms: Optional[float] = None

class HealthResponse(BaseModel):
    """Health check"""
    service: str = "cosyvoice2-tts"
    version: str = "2.0-official"
    status: str
    model: str
    device: str

# =============================================================================
# TTS ENGINE - OFFICIAL PATTERN
# =============================================================================

class TTSEngine:
    """CosyVoice2 engine following official patterns"""
    
    def __init__(self):
        self.model = None
        self.device = config.cosyvoice.device
        self.sample_rate = 22050  # CosyVoice2 native rate
        
    async def initialize(self):
        """Initialize CosyVoice2 - official pattern"""
        model_path = config.cosyvoice.model_path
        
        # Verify model exists
        if not os.path.exists(model_path):
            raise RuntimeError(f"Model not found: {model_path}")
            
        # Check for config file (REQUIRED)
        config_file = os.path.join(model_path, "cosyvoice2.yaml")
        if not os.path.exists(config_file):
            raise RuntimeError(
                f"Model config not found: {config_file}\n"
                f"This model may be incomplete or downloaded incorrectly."
            )
        
        logger.info(f"📦 Loading CosyVoice2 from {model_path}")
        
        try:
            # Official initialization pattern - SIMPLE!
            # CosyVoice2 handles tokenizer paths internally via cosyvoice2.yaml
            self.model = CosyVoice2(
                model_path,
                load_jit=config.cosyvoice.load_jit,
                load_trt=config.cosyvoice.load_trt,
                load_vllm=config.cosyvoice.load_vllm,
                fp16=config.cosyvoice.fp16 and self.device == "cuda"
            )
            
            # Get sample rate from model
            self.sample_rate = self.model.sample_rate
            
            logger.info(f"✅ CosyVoice2 loaded successfully")
            logger.info(f"   Device: {self.device}")
            logger.info(f"   Sample rate: {self.sample_rate}Hz")
            
        except Exception as e:
            logger.error(f"❌ Failed to load CosyVoice2: {e}")
            logger.error(f"   Model path: {model_path}")
            logger.error(f"   Files in model dir: {os.listdir(model_path)}")
            raise
    
    async def warmup(self):
        """Warmup with test synthesis"""
        logger.info("🔥 Warming up CosyVoice2...")
        start = time.time()
        
        try:
            # Test with zero-shot inference (most common mode)
            test_text = "Hello, this is a warmup test."
            
            for result in self.model.inference_cross_lingual(
                test_text,
                None,  # No prompt audio for warmup
                stream=False
            ):
                break  # Just need first result
            
            elapsed = (time.time() - start) * 1000
            logger.info(f"✅ Warmup complete: {elapsed:.0f}ms")
            
        except Exception as e:
            logger.warning(f"⚠️ Warmup failed: {e}")
    
    async def synthesize(self, text: str, stream: bool = True):
        """Synthesize speech using cross-lingual mode (best for general use)"""
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        logger.info(f"🎤 Synthesizing: {text[:100]}...")
        
        try:
            # Use cross_lingual mode (works without reference audio)
            for result in self.model.inference_cross_lingual(
                text,
                None,  # No reference audio needed
                stream=stream
            ):
                audio = result['tts_speech']
                
                if isinstance(audio, torch.Tensor):
                    audio = audio.detach().cpu().numpy()
                
                yield audio
                await asyncio.sleep(0)
                
        except Exception as e:
            logger.error(f"❌ Synthesis failed: {e}")
            raise

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
        """Publish audio to LiveKit"""
        logger.info(f"🎵 Streaming to {room_name}")
        
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
        
        try:
            async for audio_chunk in audio_stream:
                # Convert to int16
                audio_int16 = (audio_chunk * 32767).astype(np.int16)
                
                # Create frame
                frame = rtc.AudioFrame.create(sample_rate, 1, len(audio_int16))
                frame_data = np.frombuffer(frame.data, dtype=np.int16)
                np.copyto(frame_data, audio_int16)
                
                # Publish
                await source.capture_frame(frame)
                chunks_sent += 1
                
            logger.info(f"✅ Stream complete: {chunks_sent} chunks")
            
        finally:
            await room.local_participant.unpublish_track(publication.sid)
        
        return {"chunks_sent": chunks_sent}

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
    
    logger.info("🚀 Starting CosyVoice2 TTS Service")
    
    try:
        # Initialize engine
        engine = TTSEngine()
        await engine.initialize()
        await engine.warmup()
        
        # Initialize publisher
        publisher = LiveKitPublisher()
        await publisher.initialize(config.livekit.default_room)
        
        logger.info("✅ Service ready")
        
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        raise
    
    yield
    
    logger.info("🛑 Shutting down")

# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

app = FastAPI(
    title="CosyVoice2 TTS Service",
    version="2.0-official",
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
@app.post("/synthesize", response_model=TTSResponse)
async def synthesize(request: TTSRequest):
    """Synthesize speech and stream to LiveKit"""
    if not engine or not publisher:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    start_time = time.time()
    
    logger.info(f"🎤 TTS request: room={request.room_name}")
    logger.info(f"   Text: {request.text[:200]}...")
    
    try:
        # Generate audio
        audio_stream = engine.synthesize(request.text, request.streaming)
        
        # Publish to LiveKit
        result = await publisher.publish_audio(
            request.room_name,
            audio_stream,
            engine.sample_rate
        )
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info(f"✅ Complete: {duration_ms:.0f}ms")
        
        return TTSResponse(
            status="completed",
            message="Success",
            duration_ms=duration_ms
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
        device=config.cosyvoice.device
    )

@app.get("/")
async def root():
    """Service info"""
    return {
        "service": "cosyvoice2-tts",
        "version": "2.0-official",
        "status": "healthy"
    }

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "main_fixed:app",
        host=config.service.host,
        port=config.service.port,
        log_level="info"
    )