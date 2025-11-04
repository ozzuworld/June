#!/usr/bin/env python3
"""
June TTS Service - CosyVoice 2 Integration for Ultra-Low Latency Streaming
Replaces Chatterbox with CosyVoice 2 for <200ms first chunk synthesis
"""

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict, Any

import torch
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# CosyVoice 2 imports
try:
    from cosyvoice.cli.cosyvoice import CosyVoice2
    from cosyvoice.utils.file_utils import load_wav
    import soundfile as sf
except Exception as e:
    logging.error(f"❌ CosyVoice 2 import failed: {e}")
    sys.exit(1)

from livekit import rtc

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("june-tts")

# Configuration
class Config:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.sample_rate = 22050  # CosyVoice 2 native sample rate
        self.chunk_duration = 0.1  # Smaller chunks for lower latency
        self.max_text_length = 1000
        self.enable_streaming = True
        self.voices_dir = "/app/voices"
        self.models_dir = os.getenv("COSYVOICE_MODELS", "/app/models/cosyvoice")
        self.model_name = "CosyVoice2-0.5B"  # Optimized model
        self.warmup_text = os.getenv("WARMUP_TEXT", "Hello world")
        self.default_room = "ozzu-main"
        # Performance settings
        self.enable_fp16 = os.getenv("TTS_FP16", "true").lower() == "true"
        self.default_speaker = os.getenv("COSYVOICE_DEFAULT_SPEAKER", "中文女")

config = Config()

# Request/Response models
class TTSRequest(BaseModel):
    text: str = Field(..., max_length=config.max_text_length)
    room_name: str
    voice_mode: str = Field("predefined", description="predefined|clone")
    predefined_voice_id: Optional[str] = None
    voice_reference: Optional[str] = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
    emotion_level: float = Field(0.5, ge=0.0, le=1.5)
    temperature: float = Field(0.9, ge=0.1, le=1.0)
    seed: Optional[int] = None
    language: str = Field("en")
    streaming: bool = True

class TTSResponse(BaseModel):
    status: str
    room_name: str
    duration_ms: Optional[float] = None
    chunks_sent: Optional[int] = None
    voice_mode: str
    voice_cloned: bool = False

class HealthResponse(BaseModel):
    service: str = "june-tts"
    version: str = "3.0.0"
    status: str
    engine: str = "cosyvoice2"
    gpu_available: bool
    device: str
    streaming_enabled: bool
    cosyvoice_available: bool
    livekit_connected: bool
    model_loaded: bool

# Global metrics
metrics = {
    "requests_processed": 0,
    "streaming_requests": 0,
    "voice_cloning_requests": 0,
    "predefined_voice_requests": 0,
    "total_audio_seconds": 0.0,
    "avg_latency_ms": 0.0,
    "first_chunk_latencies": []
}

class StreamingCosyVoiceEngine:
    def __init__(self, device: str = "cuda"):
        self.device = device
        self.model: Optional[CosyVoice2] = None
        self.model_path = os.path.join(config.models_dir, config.model_name)
        self.optimizations_applied = []

    async def initialize(self):
        try:
            # Check if model exists
            if not os.path.exists(self.model_path):
                logger.error(f"❌ CosyVoice model not found at {self.model_path}")
                logger.info("💡 Run model download: python3 download_models.py")
                raise FileNotFoundError(f"Model not found: {self.model_path}")

            # Apply CUDA optimizations
            if torch.cuda.is_available():
                logger.info("🚀 Enabling CUDA optimizations for CosyVoice 2")
                torch.backends.cudnn.benchmark = True
                torch.backends.cuda.matmul.allow_tf32 = True
                self.optimizations_applied.extend(["cudnn_benchmark", "tf32_matmul"])

            # Load CosyVoice 2 model with streaming optimizations
            logger.info(f"📦 Loading CosyVoice2-0.5B from {self.model_path}")
            
            self.model = CosyVoice2(
                model_dir=self.model_path,
                load_jit=False,  # Disable JIT for faster startup
                fp16=config.enable_fp16 and self.device == "cuda"  # Use fp16 on GPU
            )
            
            if config.enable_fp16 and self.device == "cuda":
                self.optimizations_applied.append("fp16")
            
            logger.info(f"✅ CosyVoice 2 initialized on {self.device} (sr={config.sample_rate})")
            logger.info(f"🎯 Optimizations applied: {', '.join(self.optimizations_applied)}")

        except Exception as e:
            logger.error(f"❌ CosyVoice 2 initialization failed: {e}")
            raise

    async def warmup(self):
        """Warmup CosyVoice 2 for optimal performance"""
        if not self.model or not config.warmup_text:
            return
        try:
            logger.info("🔥 Running CosyVoice 2 warmup")
            warmup_start = time.time()
            
            # Test default voice synthesis
            warmup_chunks = 0
            async for chunk in self.synthesize_streaming(text=config.warmup_text[:20]):
                warmup_chunks += 1
                if warmup_chunks >= 3:  # Just a few chunks
                    break
            
            warmup_time = (time.time() - warmup_start) * 1000
            logger.info(f"✅ CosyVoice 2 warmup complete: {warmup_time:.0f}ms, {warmup_chunks} chunks")
            
        except Exception as e:
            logger.warning(f"⚠️ Warmup failed (non-critical): {e}")

    def _prepare_voice_prompt(self, voice_mode: str, predefined_voice_id: Optional[str], 
                             voice_reference: Optional[str]) -> tuple[Optional[str], Optional[np.ndarray]]:
        """Prepare voice cloning prompt for CosyVoice 2"""
        if voice_mode == "clone" and voice_reference:
            if os.path.exists(voice_reference):
                try:
                    prompt_speech = load_wav(voice_reference, config.sample_rate)
                    return "Reference voice sample for cloning", prompt_speech
                except Exception as e:
                    logger.warning(f"⚠️ Failed to load voice reference {voice_reference}: {e}")
        
        if voice_mode == "predefined" and predefined_voice_id:
            voice_path = os.path.join(config.voices_dir, predefined_voice_id)
            if os.path.exists(voice_path):
                try:
                    prompt_speech = load_wav(voice_path, config.sample_rate)
                    return f"Predefined voice: {predefined_voice_id}", prompt_speech
                except Exception as e:
                    logger.warning(f"⚠️ Failed to load predefined voice {voice_path}: {e}")
        
        # Default: no voice prompt (use built-in speaker)
        return None, None

    def _apply_speed_adjustment(self, audio_chunk: np.ndarray, speed: float) -> np.ndarray:
        """Apply speed adjustment to audio chunk"""
        if speed == 1.0 or len(audio_chunk) == 0:
            return audio_chunk
        
        # Simple time-scale modification
        target_len = max(1, int(len(audio_chunk) / speed))
        return np.interp(
            np.linspace(0, len(audio_chunk), target_len, endpoint=False),
            np.arange(len(audio_chunk)),
            audio_chunk
        ).astype(np.float32)

    async def synthesize_streaming(
        self,
        text: str,
        voice_mode: str = "predefined",
        predefined_voice_id: Optional[str] = None,
        voice_reference: Optional[str] = None,
        speed: float = 1.0,
        emotion_level: float = 0.5,
        temperature: float = 0.9,
        seed: Optional[int] = None
    ) -> AsyncIterator[np.ndarray]:
        
        if not self.model:
            raise RuntimeError("CosyVoice 2 not initialized")
        
        logger.info(f"⚡ CosyVoice 2 streaming synthesis (mode={voice_mode})")
        first_chunk_start = time.time()
        
        # Prepare voice prompt
        prompt_text, prompt_speech = self._prepare_voice_prompt(
            voice_mode, predefined_voice_id, voice_reference
        )
        
        try:
            chunk_count = 0
            
            if prompt_speech is not None:
                # Zero-shot voice cloning with streaming
                logger.info("🎙️ Using zero-shot voice cloning")
                stream_iter = self.model.inference_zero_shot(
                    text=text,
                    prompt_text=prompt_text,
                    prompt_speech=prompt_speech,
                    stream=True,  # 🔥 Enable streaming
                    speed=speed
                )
            else:
                # Default voice with streaming
                logger.info(f"🎤 Using default speaker: {config.default_speaker}")
                stream_iter = self.model.inference_sft(
                    text=text,
                    spk_id=config.default_speaker,
                    stream=True,  # 🔥 Enable streaming
                    speed=speed
                )
            
            # Stream audio chunks as they're generated
            for chunk_data in stream_iter:
                audio_chunk = chunk_data['tts_speech']
                
                # Convert to numpy float32
                if isinstance(audio_chunk, torch.Tensor):
                    audio_chunk = audio_chunk.detach().cpu().numpy()
                
                audio_chunk = audio_chunk.astype(np.float32)
                
                # Ensure mono
                if audio_chunk.ndim > 1:
                    audio_chunk = audio_chunk.mean(axis=0)
                
                # Track first chunk latency
                if chunk_count == 0:
                    first_chunk_latency = (time.time() - first_chunk_start) * 1000
                    metrics["first_chunk_latencies"].append(first_chunk_latency)
                    logger.info(f"⚡ First chunk ready: {first_chunk_latency:.0f}ms")
                
                chunk_count += 1
                yield audio_chunk
                await asyncio.sleep(0)  # Yield control
            
            logger.info(f"✅ CosyVoice 2 streaming complete: {chunk_count} chunks")
            
        except Exception as e:
            logger.error(f"❌ CosyVoice 2 synthesis failed: {e}")
            raise

class PersistentLiveKitPublisher:
    """LiveKit publisher that maintains persistent room connections"""
    
    def __init__(self):
        self.rooms: Dict[str, rtc.Room] = {}
        self.room_locks: Dict[str, asyncio.Lock] = {}
        self.connected = False

    async def initialize(self, default_room: str = "ozzu-main"):
        """Initialize and connect to default room at startup"""
        try:
            from livekit_token import connect_room_as_publisher
            self.connect_room_as_publisher = connect_room_as_publisher
            
            # Connect to default room
            await self._ensure_room_connection(default_room)
            self.connected = True
            logger.info(f"✅ TTS LiveKit publisher ready (default room: {default_room})")
        except Exception as e:
            logger.error(f"❌ Failed to initialize LiveKit publisher: {e}")
            raise

    async def _ensure_room_connection(self, room_name: str) -> rtc.Room:
        """Ensure connection to room exists, create if needed"""
        if room_name not in self.room_locks:
            self.room_locks[room_name] = asyncio.Lock()
        
        async with self.room_locks[room_name]:
            if room_name in self.rooms:
                room = self.rooms[room_name]
                try:
                    if room.isconnected():
                        return room
                except Exception:
                    pass
                # Reconnect if disconnected
                logger.info(f"🔄 Reconnecting to room {room_name}")
                del self.rooms[room_name]
            
            # Create new connection
            logger.info(f"🔗 Connecting TTS to LiveKit room: {room_name}")
            room = rtc.Room()
            await self.connect_room_as_publisher(room, "june-tts", room_name)
            self.rooms[room_name] = room
            logger.info(f"✅ TTS connected to room: {room_name}")
            return room

    async def publish_streaming_audio(self, room_name: str, audio_stream: AsyncIterator[np.ndarray], sample_rate: int) -> Dict[str, Any]:
        """Publish audio to room using persistent connection"""
        room = await self._ensure_room_connection(room_name)
        
        # Create audio source and track
        audio_source = rtc.AudioSource(sample_rate=sample_rate, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("cosyvoice-audio", audio_source)
        publication = await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        
        chunks_sent, total_duration = 0, 0.0
        logger.info(f"🎵 Starting CosyVoice 2 stream to {room_name}")
        
        async for audio_chunk in audio_stream:
            # Convert float32 [-1,1] to int16
            if audio_chunk.dtype != np.int16:
                audio_i16 = (np.clip(audio_chunk, -1.0, 1.0) * 32767.0).astype(np.int16)
            else:
                audio_i16 = audio_chunk
            
            frame = rtc.AudioFrame.create(sample_rate=sample_rate, num_channels=1, samples_per_channel=len(audio_i16))
            frame_data = np.frombuffer(frame.data, dtype=np.int16).reshape((1, len(audio_i16)))
            frame_data[0] = audio_i16
            await audio_source.capture_frame(frame)
            chunks_sent += 1
            total_duration += len(audio_i16) / sample_rate

        await asyncio.sleep(0.05)
        await room.local_participant.unpublish_track(publication.sid)
        logger.info(f"✅ CosyVoice 2 stream complete: {chunks_sent} chunks, {total_duration:.1f}s")
        return {"chunks_sent": chunks_sent, "duration_seconds": total_duration, "room_name": room_name}

    def get_connection_status(self) -> Dict[str, Any]:
        """Get status of all room connections"""
        return {
            "connected_rooms": len(self.rooms),
            "rooms": {
                name: ("connected" if (hasattr(room, "isconnected") and room.isconnected()) else "disconnected")
                for name, room in self.rooms.items()
            },
            "publisher_ready": self.connected
        }

# Global instances
streaming_engine: Optional[StreamingCosyVoiceEngine] = None
publisher: Optional[PersistentLiveKitPublisher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global streaming_engine, publisher
    logger.info("🚀 Starting June TTS Service (CosyVoice 2 streaming mode)")
    os.makedirs(config.voices_dir, exist_ok=True)
    
    # Initialize CosyVoice 2 streaming engine
    streaming_engine = StreamingCosyVoiceEngine(config.device)
    try:
        await streaming_engine.initialize()
        
        # Run warmup for optimal first-request performance
        if config.warmup_text:
            await streaming_engine.warmup()
            
    except Exception as e:
        logger.error(f"❌ Fatal: CosyVoice 2 not usable: {e}")
        # Try downloading models if missing
        if "not found" in str(e).lower():
            logger.info("📦 Attempting to download CosyVoice 2 models...")
            try:
                from download_models import download_cosyvoice_models
                download_cosyvoice_models()
                await streaming_engine.initialize()  # Retry
            except Exception:
                logger.error("❌ Model download failed. Exiting.")
                raise
        else:
            raise
    
    # Initialize persistent LiveKit publisher
    publisher = PersistentLiveKitPublisher()
    try:
        await publisher.initialize(config.default_room)
        logger.info("✅ June TTS Service ready with CosyVoice 2 + persistent LiveKit")
    except Exception:
        logger.error("❌ Fatal: LiveKit publisher not usable. Exiting.")
        raise
    
    yield

app = FastAPI(title="June TTS Service", version="3.0.0", description="CosyVoice 2 ultra-low latency streaming TTS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/tts/synthesize", response_model=TTSResponse)
async def synthesize_tts(request: TTSRequest):
    """CosyVoice 2 ultra-low latency streaming synthesis endpoint"""
    start_time = time.time()
    if not streaming_engine or not publisher:
        raise HTTPException(status_code=503, detail="CosyVoice 2 not initialized")
    
    logger.info(f"🎤 CosyVoice 2 synthesis for room {request.room_name}: {request.text[:50]}...")
    
    audio_stream = streaming_engine.synthesize_streaming(
        text=request.text,
        voice_mode=request.voice_mode,
        predefined_voice_id=request.predefined_voice_id,
        voice_reference=request.voice_reference,
        speed=request.speed,
        emotion_level=request.emotion_level,
        temperature=request.temperature,
        seed=request.seed
    )
    
    result = await publisher.publish_streaming_audio(
        room_name=request.room_name, 
        audio_stream=audio_stream, 
        sample_rate=config.sample_rate
    )
    
    duration_ms = (time.time() - start_time) * 1000
    
    # Update metrics
    metrics["requests_processed"] += 1
    metrics["streaming_requests"] += 1
    metrics["total_audio_seconds"] += result["duration_seconds"]
    if request.voice_mode == "clone":
        metrics["voice_cloning_requests"] += 1
    else:
        metrics["predefined_voice_requests"] += 1
    
    logger.info(f"✅ CosyVoice 2 synthesis complete: {duration_ms:.0f}ms total, {result['chunks_sent']} chunks")
    
    return TTSResponse(
        status="completed", 
        room_name=request.room_name, 
        duration_ms=duration_ms, 
        chunks_sent=result["chunks_sent"], 
        voice_mode=request.voice_mode, 
        voice_cloned=(request.voice_mode == "clone")
    )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    livekit_connected = publisher.connected if publisher else False
    model_loaded = streaming_engine is not None and streaming_engine.model is not None
    
    return HealthResponse(
        status="healthy", 
        gpu_available=torch.cuda.is_available(), 
        device=config.device, 
        streaming_enabled=config.enable_streaming, 
        cosyvoice_available=True,
        livekit_connected=livekit_connected,
        model_loaded=model_loaded
    )

@app.get("/connections")
async def get_connections():
    """Get LiveKit connection status for debugging"""
    if not publisher:
        return {"error": "Publisher not initialized"}
    return publisher.get_connection_status()

@app.get("/metrics")
async def get_metrics():
    """Get CosyVoice 2 performance metrics"""
    gpu_metrics = {}
    if torch.cuda.is_available():
        try:
            gpu_metrics = {
                "gpu_memory_used_gb": torch.cuda.memory_allocated() / 1024**3,
                "gpu_memory_total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3,
                "gpu_name": torch.cuda.get_device_name(0)
            }
        except Exception:
            pass
    
    connection_status = publisher.get_connection_status() if publisher else {}
    
    # Calculate average first chunk latency
    avg_first_chunk = 0
    if metrics["first_chunk_latencies"]:
        avg_first_chunk = sum(metrics["first_chunk_latencies"]) / len(metrics["first_chunk_latencies"])
    
    return {
        **metrics,
        **gpu_metrics,
        **connection_status,
        "avg_first_chunk_ms": avg_first_chunk,
        "optimizations_applied": streaming_engine.optimizations_applied if streaming_engine else [],
        "cosyvoice_available": True
    }

@app.get("/models/download")
async def download_models_endpoint():
    """Trigger model download via API"""
    try:
        from download_models import download_cosyvoice_models
        download_cosyvoice_models()
        return {"status": "success", "message": "CosyVoice 2 models downloaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model download failed: {e}")

@app.get("/")
async def root():
    return {
        "service": "june-tts", 
        "version": "3.0.0", 
        "engine": "cosyvoice2", 
        "features": "streaming+voice_cloning+ultra_low_latency", 
        "target_latency": "<200ms_first_chunk",
        "auth": "disabled",
        "livekit": "persistent_connection"
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")