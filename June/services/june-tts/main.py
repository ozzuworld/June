#!/usr/bin/env python3
"""
CosyVoice2 TTS Service - Official Implementation
Ultra-low latency streaming TTS with LiveKit integration
"""

import sys
import os

# Add CosyVoice and Matcha-TTS to path (required by CosyVoice)
sys.path.append('/opt/CosyVoice')
sys.path.append('/opt/CosyVoice/third_party/Matcha-TTS')

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict, Any

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# CosyVoice2 imports
from cosyvoice.cli.cosyvoice import CosyVoice2
from cosyvoice.utils.file_utils import load_wav

# LiveKit
from livekit import rtc

# Local imports
from config import config
from livekit_token import connect_room_as_publisher

# Logging setup
logging.basicConfig(
    level=getattr(logging, config.service.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("cosyvoice2-tts")


# Request/Response Models
class TTSRequest(BaseModel):
    """TTS synthesis request"""
    text: str = Field(..., max_length=1000, description="Text to synthesize")
    room_name: str = Field(..., description="LiveKit room name")
    
    # Voice settings
    mode: str = Field(
        "zero_shot",
        description="Synthesis mode: zero_shot, sft, instruct"
    )
    prompt_text: Optional[str] = Field(None, description="Reference text for zero-shot")
    prompt_audio: Optional[str] = Field(None, description="Reference audio path")
    speaker_id: Optional[str] = Field(None, description="Speaker ID for SFT mode")
    instruct: Optional[str] = Field(None, description="Instruction for instruct mode")
    
    # Advanced options
    streaming: bool = Field(True, description="Enable streaming output")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed")


class TTSResponse(BaseModel):
    """TTS synthesis response"""
    status: str
    room_name: str
    duration_ms: Optional[float] = None
    chunks_sent: Optional[int] = None
    mode: str


class HealthResponse(BaseModel):
    """Health check response"""
    service: str = "cosyvoice2-tts"
    version: str = "1.0.0"
    status: str
    engine: str = "cosyvoice2"
    model: str
    device: str
    gpu_available: bool
    streaming_enabled: bool
    livekit_connected: bool


# Global state
metrics = {
    "requests_processed": 0,
    "total_audio_seconds": 0.0,
    "first_chunk_latencies": [],
}


class CosyVoice2Engine:
    """CosyVoice2 TTS engine wrapper"""
    
    def __init__(self):
        self.model: Optional[CosyVoice2] = None
        self.device = config.cosyvoice.device
        self.sample_rate = config.cosyvoice.sample_rate
    
    async def initialize(self):
        """Initialize CosyVoice2 model"""
        try:
            model_path = config.cosyvoice.model_path
            
            if not os.path.exists(model_path):
                logger.error(f"❌ Model not found at {model_path}")
                logger.info("💡 Run: python download_models.py")
                raise FileNotFoundError(f"Model not found: {model_path}")
            
            logger.info(f"📦 Loading CosyVoice2 from {model_path}")
            
            # Load model with official API
            self.model = CosyVoice2(
                model_path,
                load_jit=config.cosyvoice.load_jit,
                load_trt=config.cosyvoice.load_trt,
                load_vllm=config.cosyvoice.load_vllm,
                fp16=config.cosyvoice.fp16 and self.device == "cuda"
            )
            
            logger.info(f"✅ CosyVoice2 loaded on {self.device}")
            logger.info(f"   Sample rate: {self.sample_rate}Hz")
            logger.info(f"   FP16: {config.cosyvoice.fp16 and self.device == 'cuda'}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize CosyVoice2: {e}")
            raise
    
    async def warmup(self):
        """Warmup model for optimal performance"""
        if not self.model:
            return
        
        try:
            logger.info("🔥 Warming up CosyVoice2...")
            start = time.time()
            
            # Simple warmup synthesis
            warmup_text = "Hello, this is a warmup."
            count = 0
            
            for result in self.model.inference_sft(
                warmup_text,
                '中文女',
                stream=False
            ):
                count += 1
                break  # Just one chunk
            
            elapsed = (time.time() - start) * 1000
            logger.info(f"✅ Warmup complete: {elapsed:.0f}ms")
            
        except Exception as e:
            logger.warning(f"⚠️ Warmup failed (non-critical): {e}")
    
    async def synthesize_zero_shot(
        self,
        text: str,
        prompt_text: str,
        prompt_audio_path: str,
        stream: bool = True
    ) -> AsyncIterator[np.ndarray]:
        """Zero-shot voice cloning synthesis"""
        
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        # Load reference audio
        prompt_speech = load_wav(prompt_audio_path, 16000)
        
        logger.info(f"🎤 Zero-shot synthesis: {text[:50]}...")
        first_chunk_time = time.time()
        
        for i, result in enumerate(self.model.inference_zero_shot(
            text,
            prompt_text,
            prompt_speech,
            stream=stream
        )):
            audio = result['tts_speech']
            
            # Convert to numpy if needed
            if isinstance(audio, torch.Tensor):
                audio = audio.detach().cpu().numpy()
            
            # Track first chunk latency
            if i == 0:
                latency = (time.time() - first_chunk_time) * 1000
                metrics["first_chunk_latencies"].append(latency)
                logger.info(f"⚡ First chunk: {latency:.0f}ms")
            
            yield audio
            await asyncio.sleep(0)  # Yield control
    
    async def synthesize_sft(
        self,
        text: str,
        speaker_id: str = '中文女',
        stream: bool = True
    ) -> AsyncIterator[np.ndarray]:
        """SFT mode synthesis with predefined speakers"""
        
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        logger.info(f"🎤 SFT synthesis ({speaker_id}): {text[:50]}...")
        first_chunk_time = time.time()
        
        for i, result in enumerate(self.model.inference_sft(
            text,
            speaker_id,
            stream=stream
        )):
            audio = result['tts_speech']
            
            if isinstance(audio, torch.Tensor):
                audio = audio.detach().cpu().numpy()
            
            if i == 0:
                latency = (time.time() - first_chunk_time) * 1000
                metrics["first_chunk_latencies"].append(latency)
                logger.info(f"⚡ First chunk: {latency:.0f}ms")
            
            yield audio
            await asyncio.sleep(0)
    
    async def synthesize_instruct(
        self,
        text: str,
        instruct: str,
        prompt_audio_path: str,
        stream: bool = True
    ) -> AsyncIterator[np.ndarray]:
        """Instruct mode synthesis"""
        
        if not self.model:
            raise RuntimeError("Model not initialized")
        
        prompt_speech = load_wav(prompt_audio_path, 16000)
        
        logger.info(f"🎤 Instruct synthesis: {text[:50]}...")
        first_chunk_time = time.time()
        
        for i, result in enumerate(self.model.inference_instruct2(
            text,
            instruct,
            prompt_speech,
            stream=stream
        )):
            audio = result['tts_speech']
            
            if isinstance(audio, torch.Tensor):
                audio = audio.detach().cpu().numpy()
            
            if i == 0:
                latency = (time.time() - first_chunk_time) * 1000
                metrics["first_chunk_latencies"].append(latency)
                logger.info(f"⚡ First chunk: {latency:.0f}ms")
            
            yield audio
            await asyncio.sleep(0)
    
    def get_available_speakers(self) -> list:
        """Get list of available SFT speakers"""
        if not self.model:
            return []
        return self.model.list_available_spks()


class LiveKitPublisher:
    """Persistent LiveKit room connection manager"""
    
    def __init__(self):
        self.rooms: Dict[str, rtc.Room] = {}
        self.room_locks: Dict[str, asyncio.Lock] = {}
        self.connected = False
    
    async def initialize(self, default_room: str):
        """Initialize and connect to default room"""
        try:
            await self._ensure_room_connection(default_room)
            self.connected = True
            logger.info(f"✅ LiveKit publisher ready (room: {default_room})")
        except Exception as e:
            logger.error(f"❌ LiveKit initialization failed: {e}")
            raise
    
    async def _ensure_room_connection(self, room_name: str) -> rtc.Room:
        """Ensure room connection exists"""
        
        if room_name not in self.room_locks:
            self.room_locks[room_name] = asyncio.Lock()
        
        async with self.room_locks[room_name]:
            # Check existing connection
            if room_name in self.rooms:
                room = self.rooms[room_name]
                try:
                    if room.isconnected():
                        return room
                except Exception:
                    pass
                # Reconnect if needed
                logger.info(f"🔄 Reconnecting to room {room_name}")
                del self.rooms[room_name]
            
            # Create new connection
            logger.info(f"🔗 Connecting to LiveKit room: {room_name}")
            room = rtc.Room()
            await connect_room_as_publisher(room, "cosyvoice2-tts", room_name)
            self.rooms[room_name] = room
            
            return room
    
    async def publish_audio_stream(
        self,
        room_name: str,
        audio_stream: AsyncIterator[np.ndarray],
        sample_rate: int
    ) -> Dict[str, Any]:
        """Publish streaming audio to room"""
        
        room = await self._ensure_room_connection(room_name)
        
        # Create audio source and track
        audio_source = rtc.AudioSource(
            sample_rate=sample_rate,
            num_channels=1
        )
        track = rtc.LocalAudioTrack.create_audio_track(
            "cosyvoice2-audio",
            audio_source
        )
        publication = await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        
        chunks_sent = 0
        total_duration = 0.0
        
        logger.info(f"🎵 Streaming audio to {room_name}")
        
        async for audio_chunk in audio_stream:
            # Convert float32 to int16
            if audio_chunk.dtype != np.int16:
                audio_i16 = (np.clip(audio_chunk, -1.0, 1.0) * 32767).astype(np.int16)
            else:
                audio_i16 = audio_chunk
            
            # Create and send frame
            frame = rtc.AudioFrame.create(
                sample_rate=sample_rate,
                num_channels=1,
                samples_per_channel=len(audio_i16)
            )
            frame_data = np.frombuffer(frame.data, dtype=np.int16).reshape((1, len(audio_i16)))
            frame_data[0] = audio_i16
            
            await audio_source.capture_frame(frame)
            
            chunks_sent += 1
            total_duration += len(audio_i16) / sample_rate
        
        # Cleanup
        await asyncio.sleep(0.05)
        await room.local_participant.unpublish_track(publication.sid)
        
        logger.info(f"✅ Stream complete: {chunks_sent} chunks, {total_duration:.1f}s")
        
        return {
            "chunks_sent": chunks_sent,
            "duration_seconds": total_duration
        }


# Global instances
engine: Optional[CosyVoice2Engine] = None
publisher: Optional[LiveKitPublisher] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global engine, publisher
    
    logger.info("🚀 Starting CosyVoice2 TTS Service")
    logger.info(str(config))
    
    # Initialize engine
    engine = CosyVoice2Engine()
    await engine.initialize()
    await engine.warmup()
    
    # Initialize LiveKit publisher
    publisher = LiveKitPublisher()
    await publisher.initialize(config.livekit.default_room)
    
    logger.info("✅ Service ready")
    
    yield
    
    logger.info("🛑 Shutting down")


# FastAPI app
app = FastAPI(
    title="CosyVoice2 TTS Service",
    version="1.0.0",
    description="Ultra-low latency streaming TTS with CosyVoice2",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.service.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/tts/synthesize", response_model=TTSResponse)
async def synthesize_tts(request: TTSRequest):
    """Synthesize speech and stream to LiveKit room"""
    
    if not engine or not publisher:
        raise HTTPException(status_code=503, detail="Service not ready")
    
    start_time = time.time()
    
    logger.info(f"🎤 TTS request for room {request.room_name}: {request.text[:50]}...")
    
    try:
        # Select synthesis mode
        if request.mode == "zero_shot" and request.prompt_text and request.prompt_audio:
            audio_stream = engine.synthesize_zero_shot(
                request.text,
                request.prompt_text,
                request.prompt_audio,
                request.streaming
            )
        elif request.mode == "instruct" and request.instruct and request.prompt_audio:
            audio_stream = engine.synthesize_instruct(
                request.text,
                request.instruct,
                request.prompt_audio,
                request.streaming
            )
        else:
            # Default to SFT mode
            speaker_id = request.speaker_id or '中文女'
            audio_stream = engine.synthesize_sft(
                request.text,
                speaker_id,
                request.streaming
            )
        
        # Publish to LiveKit
        result = await publisher.publish_audio_stream(
            request.room_name,
            audio_stream,
            engine.sample_rate
        )
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Update metrics
        metrics["requests_processed"] += 1
        metrics["total_audio_seconds"] += result["duration_seconds"]
        
        logger.info(f"✅ Synthesis complete: {duration_ms:.0f}ms")
        
        return TTSResponse(
            status="completed",
            room_name=request.room_name,
            duration_ms=duration_ms,
            chunks_sent=result["chunks_sent"],
            mode=request.mode
        )
        
    except Exception as e:
        logger.error(f"❌ Synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    
    return HealthResponse(
        status="healthy",
        engine="cosyvoice2",
        model=config.cosyvoice.model_name,
        device=config.cosyvoice.device,
        gpu_available=torch.cuda.is_available(),
        streaming_enabled=config.cosyvoice.streaming,
        livekit_connected=publisher.connected if publisher else False
    )


@app.get("/metrics")
async def get_metrics():
    """Get service metrics"""
    
    gpu_info = {}
    if torch.cuda.is_available():
        try:
            gpu_info = {
                "gpu_memory_used_gb": torch.cuda.memory_allocated() / 1024**3,
                "gpu_memory_total_gb": torch.cuda.get_device_properties(0).total_memory / 1024**3,
                "gpu_name": torch.cuda.get_device_name(0)
            }
        except Exception:
            pass
    
    avg_first_chunk = 0
    if metrics["first_chunk_latencies"]:
        avg_first_chunk = sum(metrics["first_chunk_latencies"]) / len(metrics["first_chunk_latencies"])
    
    return {
        **metrics,
        **gpu_info,
        "avg_first_chunk_ms": avg_first_chunk,
        "livekit_connected": publisher.connected if publisher else False
    }


@app.get("/speakers")
async def list_speakers():
    """List available SFT speakers"""
    
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    return {
        "speakers": engine.get_available_speakers()
    }


@app.get("/")
async def root():
    """Service info"""
    
    return {
        "service": "cosyvoice2-tts",
        "version": "1.0.0",
        "engine": "cosyvoice2",
        "model": config.cosyvoice.model_name,
        "features": [
            "zero_shot_voice_cloning",
            "sft_predefined_voices",
            "instruct_mode",
            "streaming",
            "livekit_integration",
            "ultra_low_latency"
        ]
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.service.host,
        port=config.service.port,
        log_level=config.service.log_level.lower()
    )