#!/usr/bin/env python3
"""
June TTS Service - Chatterbox Integration with Safe Performance Optimizations
Applies CUDA + dtype optimizations with graceful error handling, skips torch.compile
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

# Strict Chatterbox import (no fallback)
try:
    from chatterbox.tts import ChatterboxTTS
except Exception as e:
    logging.error(f"❌ Chatterbox import failed: {e}")
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
        self.sample_rate_override = None  # use model.sr by default
        self.chunk_duration = 0.2  # seconds
        self.max_text_length = 1000
        self.enable_streaming = True
        self.voices_dir = "/app/voices"
        self.warmup_text = os.getenv("WARMUP_TEXT", "Hello, this is a warmup test.")
        self.default_room = "ozzu-main"  # Default room to stay connected to
        # Performance optimization flags
        self.enable_cuda_opts = os.getenv("TTS_CUDA_OPTS", "true").lower() == "true"
        self.use_bfloat16 = os.getenv("TTS_USE_BF16", "auto").lower()  # auto, true, false

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
    cfg_weight: float = Field(0.3, ge=0.0, le=1.0)
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
    version: str = "2.1.0"
    status: str
    engine: str = "chatterbox"
    gpu_available: bool
    device: str
    streaming_enabled: bool
    chatterbox_available: bool
    livekit_connected: bool
    optimizations: Dict[str, Any]

# Global metrics
metrics = {
    "requests_processed": 0,
    "streaming_requests": 0,
    "voice_cloning_requests": 0,
    "predefined_voice_requests": 0,
    "total_audio_seconds": 0.0,
    "avg_latency_ms": 0.0,
    "optimization_errors": []
}

class SafeOptimizedChatterboxEngine:
    def __init__(self, device: str = "cuda"):
        self.device = device
        self.model: Optional[ChatterboxTTS] = None
        self.model_sr: Optional[int] = None
        self.optimizations_applied = []

    async def initialize(self):
        try:
            # Apply CUDA optimizations safely
            if torch.cuda.is_available() and config.enable_cuda_opts:
                try:
                    logger.info("🚀 Enabling CUDA optimizations")
                    torch.backends.cudnn.benchmark = True
                    torch.backends.cuda.matmul.allow_tf32 = True
                    self.optimizations_applied.extend(["cudnn_benchmark", "tf32_matmul"])
                    logger.info("✅ CUDA fast math enabled")
                except Exception as e:
                    logger.warning(f"⚠️ CUDA optimizations failed: {e}")
                    metrics["optimization_errors"].append(f"cuda_opts: {e}")

            # Load base model
            logger.info(f"📦 Loading Chatterbox TTS on {self.device}")
            self.model = ChatterboxTTS.from_pretrained(device=self.device)
            self.model_sr = int(getattr(self.model, "sr", 24000))

            # Apply dtype optimization safely
            if config.enable_cuda_opts:
                try:
                    target_dtype = self._get_optimal_dtype()
                    if target_dtype:
                        logger.info(f"🎯 Converting model to {target_dtype}")
                        if hasattr(self.model, 't3') and hasattr(self.model.t3, 'to'):
                            self.model.t3.to(dtype=target_dtype)
                            self.optimizations_applied.append(f"dtype_{target_dtype}")
                            logger.info(f"✅ Model converted to {target_dtype}")
                        else:
                            logger.warning("⚠️ Model structure doesn't support dtype conversion")
                except Exception as e:
                    logger.warning(f"⚠️ Dtype optimization failed: {e}")
                    metrics["optimization_errors"].append(f"dtype: {e}")

            # Skip torch.compile due to compatibility issues
            logger.info("⏭️ Skipping torch.compile (compatibility issues with Chatterbox)")

            logger.info(f"✅ Chatterbox TTS initialized on {self.device} (sr={self.model_sr})")
            logger.info(f"🎯 Safe optimizations applied: {', '.join(self.optimizations_applied) or 'none'}")

        except Exception as e:
            logger.error(f"❌ Chatterbox TTS initialization failed: {e}")
            raise

    def _get_optimal_dtype(self) -> Optional[torch.dtype]:
        """Determine best dtype for current GPU"""
        if not torch.cuda.is_available():
            return None
        
        if config.use_bfloat16 == "false":
            return None
        elif config.use_bfloat16 == "true":
            return torch.bfloat16
        elif config.use_bfloat16 == "auto":
            # Auto-detect based on GPU capability
            try:
                gpu_name = torch.cuda.get_device_name(0).lower()
                # RTX 30xx+ and A100+ support bfloat16 efficiently
                if any(x in gpu_name for x in ["rtx 30", "rtx 40", "rtx 50", "a100", "h100", "v100"]):
                    logger.info(f"🎯 GPU {gpu_name} supports bfloat16")
                    return torch.bfloat16
                else:
                    logger.info(f"🎯 GPU {gpu_name} using float16 fallback")
                    return torch.float16
            except Exception as e:
                logger.warning(f"⚠️ GPU detection failed: {e}, using float16")
                return torch.float16
        return None

    async def warmup(self):
        """Lightweight warmup generation"""
        if not self.model or not config.warmup_text:
            return
        try:
            logger.info("🔥 Running lightweight warmup")
            warmup_start = time.time()
            # Very short warmup text
            warmup_text = config.warmup_text[:16]  # Just a few words
            async for chunk in self.synthesize_streaming(text=warmup_text):
                break  # Just need first chunk
            warmup_time = (time.time() - warmup_start) * 1000
            logger.info(f"✅ Warmup complete: {warmup_time:.0f}ms")
        except Exception as e:
            logger.warning(f"⚠️ Warmup failed (non-critical): {e}")

    def _voice_config(self, voice_mode: str, predefined_voice_id: Optional[str], voice_reference: Optional[str]) -> Dict[str, Any]:
        if voice_mode == "clone" and voice_reference:
            return {"audio_prompt_path": voice_reference}
        if voice_mode == "predefined" and predefined_voice_id:
            voice_path = os.path.join(config.voices_dir, predefined_voice_id)
            if os.path.exists(voice_path):
                return {"audio_prompt_path": voice_path}
            logger.warning(f"Predefined voice not found: {voice_path}, using default")
        return {}

    def _time_scale(self, wav_np: np.ndarray, speed: float) -> np.ndarray:
        if speed == 1.0:
            return wav_np
        # Simple resampling for time-scale change
        target_len = max(1, int(len(wav_np) / speed))
        return np.interp(
            np.linspace(0, len(wav_np), target_len, endpoint=False),
            np.arange(len(wav_np)),
            wav_np
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
        cfg_weight: float = 0.3,
        seed: Optional[int] = None
    ) -> AsyncIterator[np.ndarray]:
        if not self.model:
            raise RuntimeError("Chatterbox TTS not initialized")
        
        # Try streaming API first (if chatterbox-streaming fork is available)
        if hasattr(self.model, 'generate_stream'):
            logger.info("⚡ Using streaming API (generate_stream)")
            params: Dict[str, Any] = {
                "exaggeration": emotion_level,
                "cfg_weight": cfg_weight,
                "temperature": temperature,
            }
            if seed is not None:
                params["seed"] = seed
            params.update(self._voice_config(voice_mode, predefined_voice_id, voice_reference))
            
            async for audio_chunk, _ in self.model.generate_stream(text=text, **params):
                if isinstance(audio_chunk, torch.Tensor):
                    audio_chunk = audio_chunk.detach().cpu().numpy().astype(np.float32)
                if audio_chunk.ndim > 1:
                    audio_chunk = audio_chunk.squeeze()
                if speed != 1.0:
                    audio_chunk = self._time_scale(audio_chunk, speed)
                yield audio_chunk
                await asyncio.sleep(0)
        else:
            # Fallback to synchronous + chunking
            logger.info("🎤 Using synchronous API with chunking (generate)")
            params: Dict[str, Any] = {
                "exaggeration": emotion_level,
                "cfg_weight": cfg_weight,
                "temperature": temperature,
            }
            if seed is not None:
                params["seed"] = seed
            params.update(self._voice_config(voice_mode, predefined_voice_id, voice_reference))

            # Generate full waveform synchronously
            wav = self.model.generate(text, **params)
            # Convert torch.Tensor to numpy float32 mono
            if isinstance(wav, torch.Tensor):
                wav = wav.detach().cpu()
            wav_np = wav.squeeze().numpy().astype(np.float32)
            if wav_np.ndim > 1:
                wav_np = wav_np.mean(axis=0).astype(np.float32)

            # Apply speed time-scaling if needed
            wav_np = self._time_scale(wav_np, speed)

            sr = self.model_sr or 24000
            chunk_len = max(1, int(config.chunk_duration * sr))
            total_samples = len(wav_np)
            for start in range(0, total_samples, chunk_len):
                chunk = wav_np[start:start + chunk_len]
                if chunk.size == 0:
                    break
                yield chunk
                await asyncio.sleep(0)  # yield control to event loop

class PersistentLiveKitPublisher:
    """LiveKit publisher that maintains persistent room connections like STT service"""
    
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
                # Correct Python SDK connectivity check
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
        track = rtc.LocalAudioTrack.create_audio_track("chatterbox-audio", audio_source)
        publication = await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        
        chunks_sent, total_duration = 0, 0.0
        logger.info(f"🎵 Starting optimized Chatterbox stream to {room_name}")
        
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
        logger.info(f"✅ Optimized stream complete: {chunks_sent} chunks, {total_duration:.1f}s")
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
streaming_engine: Optional[SafeOptimizedChatterboxEngine] = None
publisher: Optional[PersistentLiveKitPublisher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global streaming_engine, publisher
    logger.info("🚀 Starting June TTS Service (Safe-optimized Chatterbox, persistent LiveKit)")
    os.makedirs(config.voices_dir, exist_ok=True)
    
    # Initialize safe optimized Chatterbox engine
    streaming_engine = SafeOptimizedChatterboxEngine(config.device)
    try:
        await streaming_engine.initialize()
        
        # Run lightweight warmup
        if config.warmup_text:
            await streaming_engine.warmup()
            
    except Exception:
        logger.error("❌ Fatal: Chatterbox not usable. Exiting.")
        raise
    
    # Initialize persistent LiveKit publisher
    publisher = PersistentLiveKitPublisher()
    try:
        await publisher.initialize(config.default_room)
        logger.info("✅ June TTS Service ready with safe-optimized Chatterbox + persistent LiveKit")
    except Exception:
        logger.error("❌ Fatal: LiveKit publisher not usable. Exiting.")
        raise
    
    yield

app = FastAPI(title="June TTS Service", version="2.1.0", description="Safe-optimized Chatterbox TTS with persistent LiveKit streaming", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/tts/synthesize", response_model=TTSResponse)
async def synthesize_tts(request: TTSRequest):
    """Main safe-optimized Chatterbox TTS synthesis endpoint (auth disabled temporarily)"""
    start_time = time.time()
    if not streaming_engine or not publisher:
        raise HTTPException(status_code=503, detail="Chatterbox not initialized")
    
    logger.info(f"🎤 Safe-optimized TTS synthesis for room {request.room_name}: {request.text[:50]}...")
    
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
    sr = streaming_engine.model_sr or 24000
    result = await publisher.publish_streaming_audio(room_name=request.room_name, audio_stream=audio_stream, sample_rate=sr)
    duration_ms = (time.time() - start_time) * 1000
    
    # Update metrics
    metrics["requests_processed"] += 1
    metrics["streaming_requests"] += 1
    metrics["total_audio_seconds"] += result["duration_seconds"]
    if request.voice_mode == "clone":
        metrics["voice_cloning_requests"] += 1
    else:
        metrics["predefined_voice_requests"] += 1
    
    logger.info(f"✅ Safe-optimized TTS complete: {duration_ms:.0f}ms total, {result['chunks_sent']} chunks")
    
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
    optimizations = {
        "cuda_opts_enabled": config.enable_cuda_opts,
        "applied": streaming_engine.optimizations_applied if streaming_engine else [],
        "errors": metrics["optimization_errors"]
    }
    return HealthResponse(
        status="healthy", 
        gpu_available=torch.cuda.is_available(), 
        device=config.device, 
        streaming_enabled=config.enable_streaming, 
        chatterbox_available=True,
        livekit_connected=livekit_connected,
        optimizations=optimizations
    )

@app.get("/connections")
async def get_connections():
    """Get LiveKit connection status for debugging"""
    if not publisher:
        return {"error": "Publisher not initialized"}
    return publisher.get_connection_status()

@app.get("/metrics")
async def get_metrics():
    """Get service metrics"""
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
    
    return {
        **metrics,
        **gpu_metrics,
        **connection_status,
        "optimizations_applied": streaming_engine.optimizations_applied if streaming_engine else [],
        "chatterbox_available": True
    }

@app.get("/")
async def root():
    return {
        "service": "june-tts", 
        "version": "2.1.0", 
        "engine": "chatterbox", 
        "optimizations": "safe_cuda+bfloat16", 
        "auth": "disabled",
        "livekit": "persistent_connection"
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")