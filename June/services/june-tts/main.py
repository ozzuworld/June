#!/usr/bin/env python3
"""
CosyVoice2 TTS Service - FIXED v2
Handles tokenizer path correctly for CosyVoice-BlankEN subdirectory
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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("tts-service")

# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class TTSRequest(BaseModel):
    """TTS synthesis request"""
    text: str = Field(..., description="Text to synthesize")
    room_name: str = Field("ozzu-main", description="LiveKit room name")
    
    # Optional fields
    mode: Optional[str] = Field("sft", description="Mode: sft, cross_lingual, zero_shot")
    voice: Optional[str] = Field(None, description="Voice (for compatibility)")
    speaker: Optional[str] = Field(None, description="Speaker name")
    speaker_id: Optional[str] = Field(None, description="Speaker ID")
    streaming: bool = Field(True, description="Enable streaming")
    speed: float = Field(1.0, description="Speech speed")
    
    def get_speaker_id(self) -> str:
        """Get effective speaker ID"""
        return self.speaker_id or self.speaker or self.voice or "中文女"

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
    version: str = "1.0.1-fixed"
    status: str
    model: str
    device: str
    gpu_available: bool
    livekit_connected: bool

# =============================================================================
# TTS ENGINE - FIXED TOKENIZER HANDLING
# =============================================================================

class TTSEngine:
    """CosyVoice2 TTS Engine with proper tokenizer path handling"""
    
    def __init__(self):
        self.model = None
        self.device = config.cosyvoice.device
        self.sample_rate = config.cosyvoice.sample_rate
        
    async def initialize(self):
        """Initialize the TTS engine with tokenizer path fix"""
        model_path = config.cosyvoice.model_path
        
        if not os.path.exists(model_path):
            raise RuntimeError(f"Model not found at {model_path}")
        
        # Check for tokenizer files
        blanken_path = os.path.join(model_path, "CosyVoice-BlankEN")
        if not os.path.exists(blanken_path):
            logger.error(f"❌ CosyVoice-BlankEN tokenizer not found at {blanken_path}")
            logger.error("   This directory should exist within the main model")
            logger.error("   Try re-downloading the model")
            raise RuntimeError("Tokenizer files missing - model download may be incomplete")
        
        # Verify tokenizer files exist
        required_tokenizer_files = ['vocab.json', 'merges.txt']
        missing_files = []
        for file in required_tokenizer_files:
            if not os.path.exists(os.path.join(blanken_path, file)):
                missing_files.append(file)
        
        if missing_files:
            logger.warning(f"⚠️ Some tokenizer files missing: {', '.join(missing_files)}")
            logger.warning("   Attempting to continue anyway...")
        else:
            logger.info(f"✅ Tokenizer files found in {blanken_path}")
        
        logger.info(f"📦 Loading CosyVoice2 from {model_path}")
        
        # Set environment variable for tokenizer path if needed
        os.environ['COSYVOICE_TOKENIZER_PATH'] = blanken_path
        
        try:
            self.model = CosyVoice2(
                model_path,
                load_jit=config.cosyvoice.load_jit,
                load_trt=config.cosyvoice.load_trt,
                load_vllm=config.cosyvoice.load_vllm,
                fp16=config.cosyvoice.fp16 and self.device == "cuda"
            )
            
            logger.info(f"✅ CosyVoice2 loaded on {self.device}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load CosyVoice2: {e}")
            logger.error(f"   Model path: {model_path}")
            logger.error(f"   BlankEN path: {blanken_path}")
            logger.error(f"   Files in model dir: {os.listdir(model_path) if os.path.exists(model_path) else 'N/A'}")
            if os.path.exists(blanken_path):
                logger.error(f"   Files in BlankEN: {os.listdir(blanken_path)}")
            raise
    
    async def warmup(self):
        """Warmup the engine"""
        logger.info("🔥 Warming up CosyVoice2...")
        start = time.time()
        
        try:
            # Get available speakers
            speakers = self.model.list_available_spks()
            if not speakers:
                logger.warning("⚠️ No speakers found, will use cross_lingual mode")
                # Warmup with cross_lingual
                for result in self.model.inference_cross_lingual(
                    "Hello warmup",
                    None,
                    stream=False
                ):
                    break
            else:
                logger.info(f"✅ Available speakers: {speakers[:5]}...")
                # Warmup with first speaker
                for result in self.model.inference_sft(
                    "Hello warmup",
                    speakers[0],
                    stream=False
                ):
                    break
            
            elapsed = (time.time() - start) * 1000
            logger.info(f"✅ Warmup complete: {elapsed:.0f}ms")
            
        except Exception as e:
            logger.warning(f"⚠️ Warmup failed: {e}")
            logger.info("   Service may still work for synthesis")
    
    async def synthesize(self, text: str, speaker_id: str = None, stream: bool = True):
        """Synthesize speech with automatic mode selection"""
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        speakers = self.model.list_available_spks()
        
        # Choose synthesis mode
        if speakers and speaker_id and speaker_id in speakers:
            # Use SFT mode with specified speaker
            logger.info(f"🎤 SFT synthesis ({speaker_id}): {text[:100]}...")
            synthesis_func = lambda: self.model.inference_sft(text, speaker_id, stream=stream)
        else:
            # Fall back to cross_lingual mode
            if speaker_id and speaker_id not in speakers:
                logger.warning(f"⚠️ Speaker '{speaker_id}' not found, using cross_lingual mode")
            else:
                logger.info(f"🎤 Cross-lingual synthesis: {text[:100]}...")
            synthesis_func = lambda: self.model.inference_cross_lingual(text, None, stream=stream)
        
        try:
            for result in synthesis_func():
                audio = result['tts_speech']
                
                if isinstance(audio, torch.Tensor):
                    audio = audio.detach().cpu().numpy()
                
                yield audio
                await asyncio.sleep(0)
                
        except Exception as e:
            logger.error(f"❌ Synthesis failed: {e}")
            raise
    
    def get_available_speakers(self) -> list:
        """Get available speakers"""
        if self.model:
            try:
                return self.model.list_available_spks()
            except:
                pass
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
    version="1.0.1-fixed",
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
    
    speaker_id = request.get_speaker_id()
    logger.info(f"🎤 TTS request: room={request.room_name}, speaker={speaker_id}")
    logger.info(f"   Text: {request.text[:200]}...")
    
    try:
        # Generate audio stream
        audio_stream = engine.synthesize(
            request.text,
            speaker_id,
            request.streaming
        )
        
        # Publish to LiveKit
        result = await publisher.publish_audio(
            request.room_name,
            audio_stream,
            engine.sample_rate
        )
        
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
    """List available speakers"""
    speakers = engine.get_available_speakers() if engine else []
    return {
        "speakers": speakers,
        "count": len(speakers),
        "supports_cross_lingual": True
    }

@app.get("/")
async def root():
    """Service info"""
    return {
        "service": "cosyvoice2-tts",
        "version": "1.0.1-fixed",
        "status": "healthy"
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