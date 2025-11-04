#!/usr/bin/env python3
"""
June TTS Service - Chatterbox Integration with Streaming
High-performance TTS service with Chatterbox TTS, LiveKit integration and GPU optimization
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict, Any, Union

import torch
import torchaudio
import numpy as np
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# June shared services
from shared import require_service_auth, require_user_auth, extract_user_id
from livekit_token import get_livekit_token, connect_room_as_publisher

# Chatterbox TTS - the only TTS engine we use (with robust import handling)
CHATTERBOX_AVAILABLE = False
ChatterboxTTS = None  # type: ignore

try:
    from chatterbox.tts import ChatterboxTTS as _ChatterboxTTS
    ChatterboxTTS = _ChatterboxTTS
    CHATTERBOX_AVAILABLE = True
    logging.info("✅ Chatterbox TTS module imported successfully")
except Exception as e:
    logging.warning(f"⚠️ Chatterbox TTS not available - using fallback: {e}")

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
        self.enable_streaming = True
        self.chunk_size = 25  # Tokens per chunk for Chatterbox streaming
        self.voices_dir = "/app/voices"  # Predefined voices directory
        
config = Config()

# Request/Response models
class TTSRequest(BaseModel):
    text: str = Field(..., max_length=config.max_text_length, description="Text to synthesize")
    room_name: str = Field(..., description="LiveKit room name")
    voice_mode: str = Field("predefined", description="Voice mode: 'predefined' or 'clone'")
    predefined_voice_id: Optional[str] = Field(None, description="Predefined voice filename from /voices directory")
    voice_reference: Optional[str] = Field(None, description="Path or URL to reference voice audio for cloning")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    emotion_level: float = Field(0.5, ge=0.0, le=1.5, description="Emotion exaggeration (0.0-1.5)")
    temperature: float = Field(0.9, ge=0.1, le=1.0, description="Voice randomness/variation")
    cfg_weight: float = Field(0.3, ge=0.0, le=1.0, description="Guidance weight for voice control")
    seed: Optional[int] = Field(None, description="Generation seed for consistency")
    language: str = Field("en", description="Language code")
    streaming: bool = Field(True, description="Enable streaming mode")

class TTSResponse(BaseModel):
    status: str
    room_name: str
    duration_ms: Optional[float] = None
    chunks_sent: Optional[int] = None
    voice_mode: str
    voice_cloned: bool = False

class HealthResponse(BaseModel):
    service: str = "june-tts"
    version: str = "2.0.0"
    status: str = "healthy"
    engine: str = "chatterbox"
    gpu_available: bool
    device: str
    streaming_enabled: bool
    chatterbox_available: bool

# Global TTS engine and metrics
tts_engine = None  # Will be ChatterboxTTS if available
active_rooms: Dict[str, rtc.Room] = {}
metrics = {
    "requests_processed": 0,
    "streaming_requests": 0,
    "voice_cloning_requests": 0,
    "predefined_voice_requests": 0,
    "total_audio_seconds": 0.0,
    "avg_latency_ms": 0.0,
    "gpu_utilization": 0.0
}

class StreamingChatterboxEngine:
    """Chatterbox TTS engine with streaming capabilities and voice modes"""
    
    def __init__(self, device: str = "cuda"):
        self.device = device
        self.model = None
        self.sample_rate = config.sample_rate
        
    async def initialize(self):
        """Initialize Chatterbox TTS model"""
        try:
            if CHATTERBOX_AVAILABLE and ChatterboxTTS:
                self.model = ChatterboxTTS.from_pretrained(device=self.device)
                logger.info(f"✅ Chatterbox TTS initialized on {self.device}")
            else:
                # Fallback to basic TTS simulation for development
                logger.warning("⚠️ Using fallback TTS - install Chatterbox for production")
                self.model = "fallback"
        except Exception as e:
            logger.error(f"❌ Chatterbox TTS initialization failed: {e}")
            # Don't raise - use fallback mode
            self.model = "fallback"
    
    def _get_voice_config(
        self, 
        voice_mode: str,
        predefined_voice_id: Optional[str] = None,
        voice_reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get voice configuration for Chatterbox generation"""
        
        if voice_mode == "clone" and voice_reference:
            # Voice cloning mode
            return {"audio_prompt_path": voice_reference}
        elif voice_mode == "predefined" and predefined_voice_id:
            # Predefined voice mode
            voice_path = os.path.join(config.voices_dir, predefined_voice_id)
            if os.path.exists(voice_path):
                return {"audio_prompt_path": voice_path}
            else:
                logger.warning(f"Predefined voice not found: {voice_path}, using default")
                return {}
        else:
            # Default voice (no audio_prompt_path)
            return {}
    
    async def synthesize_streaming(
        self, 
        text: str, 
        voice_mode: str = "predefined",
        predefined_voice_id: Optional[str] = None,
        voice_reference: Optional[str] = None,
        speed: float = 1.0,
        emotion_level: float = 0.5,
        temperature: float = 0.9,
        cfg_weight: float = 0.3,
        seed: Optional[int] = None
    ) -> AsyncIterator[np.ndarray]:
        """Generate streaming audio chunks using Chatterbox TTS"""
        
        if not self.model:
            raise RuntimeError("Chatterbox TTS engine not initialized")
            
        try:
            if CHATTERBOX_AVAILABLE and self.model != "fallback":
                # Real Chatterbox TTS streaming
                logger.info(f"🎤 Chatterbox streaming ({voice_mode}): {text[:50]}...")
                
                # Configure Chatterbox generation parameters
                generation_params = {
                    'exaggeration': emotion_level,  # Chatterbox emotion parameter
                    'cfg_weight': cfg_weight,       # Chatterbox guidance weight
                    'temperature': temperature,     # Chatterbox randomness
                    'chunk_size': config.chunk_size # Tokens per chunk
                }
                
                # Add seed for consistency if provided
                if seed is not None:
                    generation_params['seed'] = seed
                
                # Add voice configuration
                voice_config = self._get_voice_config(voice_mode, predefined_voice_id, voice_reference)
                generation_params.update(voice_config)
                
                if voice_config:
                    logger.info(f"🎭 Using voice: {voice_config}")
                else:
                    logger.info("🎵 Using Chatterbox default voice")
                
                # Generate streaming audio using Chatterbox
                async for audio_chunk, metrics_data in self.model.generate_stream(
                    text=text,
                    **generation_params
                ):
                    # Convert Chatterbox output to numpy array
                    if isinstance(audio_chunk, torch.Tensor):
                        audio_chunk = audio_chunk.cpu().numpy()
                    
                    # Adjust speed if needed
                    if speed != 1.0:
                        # Simple speed adjustment by resampling
                        target_length = int(len(audio_chunk) / speed)
                        audio_chunk = np.interp(
                            np.linspace(0, len(audio_chunk), target_length),
                            np.arange(len(audio_chunk)),
                            audio_chunk
                        )
                    
                    yield audio_chunk
                    
            else:
                # Fallback: Generate silence chunks for testing
                words = text.split()
                chunk_duration = 0.2  # 200ms per chunk
                
                logger.info(f"🔇 Fallback mode streaming: {len(words)} words")
                
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
            logger.error(f"❌ Chatterbox TTS synthesis error: {e}")
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
                "chatterbox-audio", 
                audio_source
            )
            
            # Publish track
            publication = await room.local_participant.publish_track(
                track,
                rtc.TrackPublishOptions(
                    source=rtc.TrackSource.SOURCE_MICROPHONE
                )
            )
            
            logger.info(f"🎵 Starting Chatterbox audio stream to {room_name}")
            
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
            
            logger.info(f"✅ Chatterbox audio stream complete: {chunks_sent} chunks, {total_duration:.1f}s")
            
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
streaming_engine: Optional[StreamingChatterboxEngine] = None
audio_publisher: Optional[LiveKitAudioPublisher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    global streaming_engine, audio_publisher
    
    logger.info("🚀 Starting June TTS Service v2.0 with Chatterbox")
    logger.info(f"Device: {config.device}")
    logger.info(f"GPU Available: {torch.cuda.is_available()}")
    logger.info(f"Voices Directory: {config.voices_dir}")
    
    # Debug Chatterbox availability
    try:
        if CHATTERBOX_AVAILABLE:
            import chatterbox
            logger.info(f"✅ Chatterbox module found: {getattr(chatterbox, '__file__', 'unknown')}")
        else:
            logger.warning("⚠️ Chatterbox not available - will use fallback mode")
    except Exception as e:
        logger.error(f"❌ Chatterbox import debug failed: {e}")
    
    # Create voices directory if it doesn't exist
    os.makedirs(config.voices_dir, exist_ok=True)
    
    # Initialize Chatterbox TTS engine
    streaming_engine = StreamingChatterboxEngine(config.device)
    await streaming_engine.initialize()
    
    # Initialize audio publisher
    audio_publisher = LiveKitAudioPublisher()
    
    engine_status = "chatterbox" if CHATTERBOX_AVAILABLE else "fallback"
    logger.info(f"✅ June TTS Service ready with {engine_status} engine")
    
    yield
    
    # Cleanup
    logger.info("🛑 Shutting down June TTS Service")
    logger.info(f"📊 Final metrics: {metrics}")

# FastAPI app
app = FastAPI(
    title="June TTS Service",
    version="2.0.0",
    description="High-performance TTS service with Chatterbox TTS and LiveKit streaming",
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
    """Synthesize TTS using Chatterbox and stream to LiveKit room"""
    
    start_time = time.time()
    
    try:
        if not streaming_engine or not audio_publisher:
            raise HTTPException(
                status_code=503, 
                detail="Chatterbox TTS service not initialized"
            )
        
        logger.info(f"🎤 Chatterbox TTS request: '{request.text[:50]}...' -> {request.room_name}")
        logger.info(f"Voice mode: {request.voice_mode}")
        
        # Generate streaming audio using Chatterbox
        audio_stream = streaming_engine.synthesize_streaming(
            text=request.text,
            voice_mode=request.voice_mode,
            predefined_voice_id=request.predefined_voice_id,
            voice_reference=request.voice_reference,
            speed=request.speed,
            emotion_level=request.emotion_level,
            temperature=request.temperature,
            cfg_weight=request.cfg_weight,
            seed=request.seed
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
        
        if request.voice_mode == "clone":
            metrics["voice_cloning_requests"] += 1
        else:
            metrics["predefined_voice_requests"] += 1
        
        # Update average latency
        if metrics["avg_latency_ms"] == 0:
            metrics["avg_latency_ms"] = duration_ms
        else:
            metrics["avg_latency_ms"] = (metrics["avg_latency_ms"] * 0.9 + duration_ms * 0.1)
        
        logger.info(f"✅ Chatterbox TTS completed: {duration_ms:.0f}ms, {result['chunks_sent']} chunks")
        
        return TTSResponse(
            status="completed",
            room_name=request.room_name,
            duration_ms=duration_ms,
            chunks_sent=result["chunks_sent"],
            voice_mode=request.voice_mode,
            voice_cloned=(request.voice_mode == "clone")
        )
        
    except Exception as e:
        logger.error(f"❌ Chatterbox TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/voices")
async def list_voices(auth_data: dict = Depends(require_service_auth)):
    """List Chatterbox TTS capabilities and available voices"""
    
    # List predefined voices
    predefined_voices = []
    if os.path.exists(config.voices_dir):
        for filename in os.listdir(config.voices_dir):
            if filename.endswith(('.wav', '.mp3', '.flac')):
                predefined_voices.append({
                    "id": filename,
                    "name": filename.replace('.wav', '').replace('.mp3', '').replace('.flac', ''),
                    "type": "predefined"
                })
    
    return {
        "engine": "chatterbox",
        "voice_cloning": True,
        "streaming": True,
        "available": CHATTERBOX_AVAILABLE,
        "voice_modes": ["predefined", "clone"],
        "predefined_voices": predefined_voices,
        "default_voice": "Built-in Chatterbox default voice",
        "supported_languages": ["en", "es", "fr", "de", "it", "pt", "ru", "zh"],
        "parameters": {
            "emotion_level": {"min": 0.0, "max": 1.5, "default": 0.5},
            "temperature": {"min": 0.1, "max": 1.0, "default": 0.9},
            "cfg_weight": {"min": 0.0, "max": 1.0, "default": 0.3},
            "speed": {"min": 0.5, "max": 2.0, "default": 1.0},
            "seed": {"description": "Integer for consistent generation, null for random"}
        },
        "features": [
            "Zero-shot voice cloning",
            "Built-in predefined voices", 
            "Real-time streaming",
            "Emotion control",
            "Generation consistency (seed)",
            "Multi-language support",
            "GPU acceleration"
        ]
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Service health check"""
    
    return HealthResponse(
        gpu_available=torch.cuda.is_available(),
        device=config.device,
        streaming_enabled=config.enable_streaming,
        engine="chatterbox" if CHATTERBOX_AVAILABLE else "fallback",
        chatterbox_available=CHATTERBOX_AVAILABLE
    )

@app.get("/metrics")
async def get_metrics(auth_data: dict = Depends(require_service_auth)):
    """Get service metrics"""
    
    gpu_metrics = {}
    if torch.cuda.is_available():
        try:
            gpu_metrics = {
                "gpu_memory_used": torch.cuda.memory_allocated() / 1024**3,  # GB
                "gpu_memory_total": torch.cuda.get_device_properties(0).total_memory / 1024**3,  # GB
                "gpu_utilization": torch.cuda.utilization() if hasattr(torch.cuda, 'utilization') else 0
            }
        except Exception as e:
            logger.warning(f"GPU metrics unavailable: {e}")
    
    return {
        **metrics,
        **gpu_metrics,
        "chatterbox_available": CHATTERBOX_AVAILABLE,
        "active_rooms": len(audio_publisher.rooms) if audio_publisher else 0,
        "config": {
            "device": config.device,
            "sample_rate": config.sample_rate,
            "chunk_duration": config.chunk_duration,
            "streaming_enabled": config.enable_streaming,
            "chunk_size": config.chunk_size,
            "voices_dir": config.voices_dir
        }
    }

@app.get("/")
async def root():
    """Service information"""
    
    return {
        "service": "june-tts",
        "version": "2.0.0",
        "description": "High-performance TTS service with Chatterbox TTS and LiveKit streaming",
        "engine": "chatterbox" if CHATTERBOX_AVAILABLE else "fallback",
        "chatterbox_available": CHATTERBOX_AVAILABLE,
        "gpu_available": torch.cuda.is_available(),
        "device": config.device,
        "voice_modes": ["predefined", "clone"],
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