#!/usr/bin/env python3
"""
June TTS Service - Chatterbox Integration with Streaming
High-performance TTS service with LiveKit integration and GPU optimization
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict, Any

import torch
import numpy as np
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# June shared services
from shared import require_service_auth, require_user_auth, extract_user_id
from livekit_token import get_livekit_token, connect_room_as_publisher

# TTS and audio processing
try:
    from kokoro import KokoroTTS
    KOKORO_AVAILABLE = True
except ImportError:
    KOKORO_AVAILABLE = False
    logging.warning("⚠️ Kokoro TTS not available - using fallback")

from livekit import rtc
import soundfile as sf

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("june-tts")

# Configuration
class Config:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.sample_rate = 24000
        self.chunk_duration = 0.2  # 200ms chunks for streaming
        self.max_text_length = 1000
        self.default_voice = "af_bella"  # Kokoro default voice
        self.enable_streaming = True
        
config = Config()

# Request/Response models
class TTSRequest(BaseModel):
    text: str = Field(..., max_length=config.max_text_length, description="Text to synthesize")
    room_name: str = Field(..., description="LiveKit room name")
    voice_id: Optional[str] = Field(None, description="Voice ID for synthesis")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    emotion_level: float = Field(0.5, ge=0.0, le=1.0, description="Emotion intensity")
    language: str = Field("en", description="Language code")
    streaming: bool = Field(True, description="Enable streaming mode")

class TTSResponse(BaseModel):
    status: str
    room_name: str
    duration_ms: Optional[float] = None
    chunks_sent: Optional[int] = None
    voice_used: Optional[str] = None

class HealthResponse(BaseModel):
    service: str = "june-tts"
    version: str = "2.0.0"
    status: str = "healthy"
    engine: str = "kokoro"
    gpu_available: bool
    device: str
    voices_available: int

# Global TTS engine and metrics
tts_engine: Optional[KokoroTTS] = None
active_rooms: Dict[str, rtc.Room] = {}
metrics = {
    "requests_processed": 0,
    "streaming_requests": 0,
    "total_audio_seconds": 0.0,
    "avg_latency_ms": 0.0,
    "gpu_utilization": 0.0
}

class StreamingTTSEngine:
    """Chatterbox/Kokoro TTS engine with streaming capabilities"""
    
    def __init__(self, device: str = "cuda"):
        self.device = device
        self.model = None
        self.sample_rate = config.sample_rate
        self.chunk_size = int(config.chunk_duration * self.sample_rate)
        
    async def initialize(self):
        """Initialize TTS model"""
        try:
            if KOKORO_AVAILABLE:
                self.model = KokoroTTS(device=self.device)
                logger.info(f"✅ Kokoro TTS initialized on {self.device}")
            else:
                # Fallback to basic TTS simulation
                logger.warning("⚠️ Using fallback TTS - install Kokoro for production")
                self.model = "fallback"
        except Exception as e:
            logger.error(f"❌ TTS initialization failed: {e}")
            raise
    
    async def synthesize_streaming(
        self, 
        text: str, 
        voice: str = None, 
        speed: float = 1.0,
        emotion_level: float = 0.5
    ) -> AsyncIterator[np.ndarray]:
        """Generate streaming audio chunks"""
        
        if not self.model:
            raise RuntimeError("TTS engine not initialized")
            
        try:
            if KOKORO_AVAILABLE and self.model != "fallback":
                # Real Kokoro TTS streaming
                voice_id = voice or config.default_voice
                
                # Configure generation parameters
                generation_config = {
                    'speed': speed,
                    'emotion': emotion_level,
                    'streaming': True
                }
                
                # Generate audio stream
                async for audio_chunk in self.model.generate_stream(
                    text=text,
                    voice=voice_id,
                    **generation_config
                ):
                    # Ensure chunk is numpy array
                    if isinstance(audio_chunk, torch.Tensor):
                        audio_chunk = audio_chunk.cpu().numpy()
                    
                    yield audio_chunk
            else:
                # Fallback: Generate silence chunks for testing
                words = text.split()
                chunk_duration = 0.2  # 200ms per chunk
                
                for i in range(0, len(words), 3):  # 3 words per chunk
                    chunk_words = ' '.join(words[i:i+3])
                    # Generate silence (replace with actual audio in production)
                    silence_samples = int(chunk_duration * self.sample_rate)
                    audio_chunk = np.zeros(silence_samples, dtype=np.float32)
                    
                    # Add some variation to simulate speech
                    audio_chunk += np.random.normal(0, 0.01, silence_samples)
                    
                    yield audio_chunk
                    await asyncio.sleep(0.05)  # Small delay between chunks
                    
        except Exception as e:
            logger.error(f"❌ TTS synthesis error: {e}")
            raise

class LiveKitAudioPublisher:
    """Publishes streaming audio to LiveKit rooms"""
    
    def __init__(self):
        self.rooms = {}
        
    async def connect_to_room(self, room_name: str) -> rtc.Room:
        """Connect to LiveKit room as TTS participant"""
        
        if room_name in self.rooms:
            return self.rooms[room_name]
            
        try:
            room = rtc.Room()
            await connect_room_as_publisher(room, "june-tts", room_name)
            
            self.rooms[room_name] = room
            logger.info(f"✅ Connected to LiveKit room: {room_name}")
            return room
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to room {room_name}: {e}")
            raise
    
    async def publish_streaming_audio(
        self, 
        room_name: str, 
        audio_stream: AsyncIterator[np.ndarray]
    ) -> Dict[str, Any]:
        """Publish streaming audio to LiveKit room"""
        
        room = await self.connect_to_room(room_name)
        chunks_sent = 0
        total_duration = 0.0
        
        try:
            # Create audio source and track
            audio_source = rtc.AudioSource(
                sample_rate=config.sample_rate, 
                num_channels=1
            )
            track = rtc.LocalAudioTrack.create_audio_track(
                "tts-audio", 
                audio_source
            )
            
            # Publish track
            publication = await room.local_participant.publish_track(
                track,
                rtc.TrackPublishOptions(
                    source=rtc.TrackSource.SOURCE_MICROPHONE
                )
            )
            
            logger.info(f"🎵 Starting audio stream to {room_name}")
            
            # Stream audio chunks
            async for audio_chunk in audio_stream:
                # Convert to AudioFrame
                frame = self._numpy_to_audio_frame(audio_chunk)
                await audio_source.capture_frame(frame)
                
                chunks_sent += 1
                total_duration += len(audio_chunk) / config.sample_rate
                
                # Log progress periodically
                if chunks_sent % 10 == 0:
                    logger.debug(f"📡 Sent {chunks_sent} chunks ({total_duration:.1f}s)")
            
            # Small delay before unpublishing
            await asyncio.sleep(0.1)
            
            # Unpublish track
            await room.local_participant.unpublish_track(publication.sid)
            
            logger.info(f"✅ Audio stream complete: {chunks_sent} chunks, {total_duration:.1f}s")
            
            return {
                "chunks_sent": chunks_sent,
                "duration_seconds": total_duration,
                "room_name": room_name
            }
            
        except Exception as e:
            logger.error(f"❌ Audio streaming error: {e}")
            raise
    
    def _numpy_to_audio_frame(self, audio_data: np.ndarray) -> rtc.AudioFrame:
        """Convert numpy array to LiveKit AudioFrame"""
        
        # Ensure correct data type and range
        if audio_data.dtype != np.int16:
            # Convert float to int16
            audio_data = (audio_data * 32767).astype(np.int16)
        
        # Create AudioFrame
        frame = rtc.AudioFrame.create(
            sample_rate=config.sample_rate,
            num_channels=1,
            samples_per_channel=len(audio_data)
        )
        
        # Copy data to frame
        frame_data = np.frombuffer(
            frame.data, 
            dtype=np.int16
        ).reshape((1, len(audio_data)))
        frame_data[0] = audio_data
        
        return frame

# Global instances
streaming_engine: Optional[StreamingTTSEngine] = None
audio_publisher: Optional[LiveKitAudioPublisher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    global streaming_engine, audio_publisher
    
    logger.info("🚀 Starting June TTS Service v2.0")
    logger.info(f"Device: {config.device}")
    logger.info(f"GPU Available: {torch.cuda.is_available()}")
    
    # Initialize TTS engine
    streaming_engine = StreamingTTSEngine(config.device)
    await streaming_engine.initialize()
    
    # Initialize audio publisher
    audio_publisher = LiveKitAudioPublisher()
    
    logger.info("✅ June TTS Service ready")
    
    yield
    
    # Cleanup
    logger.info("🛑 Shutting down June TTS Service")
    logger.info(f"📊 Final metrics: {metrics}")

# FastAPI app
app = FastAPI(
    title="June TTS Service",
    version="2.0.0",
    description="High-performance TTS service with Chatterbox/Kokoro and LiveKit streaming",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/tts/synthesize", response_model=TTSResponse)
async def synthesize_tts(
    request: TTSRequest,
    auth_data: dict = Depends(require_service_auth)
):
    """Synthesize TTS and stream to LiveKit room"""
    
    start_time = time.time()
    
    try:
        if not streaming_engine or not audio_publisher:
            raise HTTPException(
                status_code=503, 
                detail="TTS service not initialized"
            )
        
        logger.info(f"🎤 TTS request: '{request.text[:50]}...' -> {request.room_name}")
        
        # Generate streaming audio
        audio_stream = streaming_engine.synthesize_streaming(
            text=request.text,
            voice=request.voice_id,
            speed=request.speed,
            emotion_level=request.emotion_level
        )
        
        # Publish to LiveKit room
        result = await audio_publisher.publish_streaming_audio(
            room_name=request.room_name,
            audio_stream=audio_stream
        )
        
        # Update metrics
        duration_ms = (time.time() - start_time) * 1000
        metrics["requests_processed"] += 1
        metrics["streaming_requests"] += 1
        metrics["total_audio_seconds"] += result["duration_seconds"]
        
        # Update average latency
        if metrics["avg_latency_ms"] == 0:
            metrics["avg_latency_ms"] = duration_ms
        else:
            metrics["avg_latency_ms"] = (metrics["avg_latency_ms"] * 0.9 + duration_ms * 0.1)
        
        logger.info(f"✅ TTS completed: {duration_ms:.0f}ms, {result['chunks_sent']} chunks")
        
        return TTSResponse(
            status="completed",
            room_name=request.room_name,
            duration_ms=duration_ms,
            chunks_sent=result["chunks_sent"],
            voice_used=request.voice_id or config.default_voice
        )
        
    except Exception as e:
        logger.error(f"❌ TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/voices")
async def list_voices(auth_data: dict = Depends(require_service_auth)):
    """List available voices"""
    
    # Default Kokoro voices
    voices = {
        "af_bella": {"name": "Bella", "language": "en", "gender": "female"},
        "af_sarah": {"name": "Sarah", "language": "en", "gender": "female"},
        "am_adam": {"name": "Adam", "language": "en", "gender": "male"},
        "am_michael": {"name": "Michael", "language": "en", "gender": "male"},
    }
    
    return {
        "voices": voices,
        "default_voice": config.default_voice,
        "engine": "kokoro" if KOKORO_AVAILABLE else "fallback"
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Service health check"""
    
    return HealthResponse(
        gpu_available=torch.cuda.is_available(),
        device=config.device,
        voices_available=4  # Default Kokoro voices
    )

@app.get("/metrics")
async def get_metrics(auth_data: dict = Depends(require_service_auth)):
    """Get service metrics"""
    
    gpu_metrics = {}
    if torch.cuda.is_available():
        gpu_metrics = {
            "gpu_memory_used": torch.cuda.memory_allocated() / 1024**3,  # GB
            "gpu_memory_total": torch.cuda.get_device_properties(0).total_memory / 1024**3,  # GB
            "gpu_utilization": torch.cuda.utilization() if hasattr(torch.cuda, 'utilization') else 0
        }
    
    return {
        **metrics,
        **gpu_metrics,
        "active_rooms": len(audio_publisher.rooms) if audio_publisher else 0,
        "config": {
            "device": config.device,
            "sample_rate": config.sample_rate,
            "chunk_duration": config.chunk_duration,
            "streaming_enabled": config.enable_streaming
        }
    }

@app.get("/")
async def root():
    """Service information"""
    
    return {
        "service": "june-tts",
        "version": "2.0.0",
        "description": "High-performance TTS service with Chatterbox/Kokoro and LiveKit streaming",
        "engine": "kokoro" if KOKORO_AVAILABLE else "fallback",
        "gpu_available": torch.cuda.is_available(),
        "device": config.device,
        "endpoints": [
            "/api/tts/synthesize",
            "/api/voices",
            "/health",
            "/metrics"
        ]
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )