#!/usr/bin/env python3
"""
June TTS Service - Chatterbox Integration with Streaming (Strict Mode)
Chatterbox is mandatory. If import/init fails, the service will not start.
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
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# June shared services
from shared import require_service_auth
from livekit_token import connect_room_as_publisher

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
        self.sample_rate = 24000
        self.chunk_duration = 0.2  # 200ms chunks for streaming
        self.max_text_length = 1000
        self.enable_streaming = True
        self.chunk_size = 25  # Tokens per chunk for Chatterbox streaming
        self.voices_dir = "/app/voices"
        self.warmup_text = os.getenv("WARMUP_TEXT", "")

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
    version: str = "2.0.0"
    status: str
    engine: str = "chatterbox"
    gpu_available: bool
    device: str
    streaming_enabled: bool
    chatterbox_available: bool

# Global TTS engine and metrics
chatterbox_model: Optional[ChatterboxTTS] = None
active_rooms: Dict[str, rtc.Room] = {}
metrics = {
    "requests_processed": 0,
    "streaming_requests": 0,
    "voice_cloning_requests": 0,
    "predefined_voice_requests": 0,
    "total_audio_seconds": 0.0,
    "avg_latency_ms": 0.0
}

class StreamingChatterboxEngine:
    def __init__(self, device: str = "cuda"):
        self.device = device
        self.model: Optional[ChatterboxTTS] = None
        self.sample_rate = config.sample_rate

    async def initialize(self):
        try:
            self.model = ChatterboxTTS.from_pretrained(device=self.device)
            logger.info(f"✅ Chatterbox TTS initialized on {self.device}")
        except Exception as e:
            logger.error(f"❌ Chatterbox TTS initialization failed: {e}")
            raise

    def _get_voice_config(self, voice_mode: str, predefined_voice_id: Optional[str], voice_reference: Optional[str]) -> Dict[str, Any]:
        if voice_mode == "clone" and voice_reference:
            return {"audio_prompt_path": voice_reference}
        if voice_mode == "predefined" and predefined_voice_id:
            voice_path = os.path.join(config.voices_dir, predefined_voice_id)
            if os.path.exists(voice_path):
                return {"audio_prompt_path": voice_path}
            logger.warning(f"Predefined voice not found: {voice_path}, using default")
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
        if not self.model:
            raise RuntimeError("Chatterbox TTS not initialized")
        generation_params = {
            'exaggeration': emotion_level,
            'cfg_weight': cfg_weight,
            'temperature': temperature,
            'chunk_size': config.chunk_size
        }
        if seed is not None:
            generation_params['seed'] = seed
        generation_params.update(self._get_voice_config(voice_mode, predefined_voice_id, voice_reference))
        async for audio_chunk, _ in self.model.generate_stream(text=text, **generation_params):
            if isinstance(audio_chunk, torch.Tensor):
                audio_chunk = audio_chunk.cpu().numpy()
            if speed != 1.0:
                target_length = int(len(audio_chunk) / speed)
                audio_chunk = np.interp(np.linspace(0, len(audio_chunk), target_length), np.arange(len(audio_chunk)), audio_chunk)
            yield audio_chunk

class LiveKitAudioPublisher:
    async def connect_to_room(self, room_name: str) -> rtc.Room:
        room = rtc.Room()
        await connect_room_as_publisher(room, "june-tts", room_name)
        return room

    async def publish_streaming_audio(self, room_name: str, audio_stream: AsyncIterator[np.ndarray]) -> Dict[str, Any]:
        room = await self.connect_to_room(room_name)
        audio_source = rtc.AudioSource(sample_rate=config.sample_rate, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("chatterbox-audio", audio_source)
        publication = await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        chunks_sent, total_duration = 0, 0.0
        async for audio_chunk in audio_stream:
            frame = self._numpy_to_audio_frame(audio_chunk)
            await audio_source.capture_frame(frame)
            chunks_sent += 1
            total_duration += len(audio_chunk) / config.sample_rate
        await asyncio.sleep(0.1)
        await room.local_participant.unpublish_track(publication.sid)
        return {"chunks_sent": chunks_sent, "duration_seconds": total_duration, "room_name": room_name}

    def _numpy_to_audio_frame(self, audio_data: np.ndarray) -> rtc.AudioFrame:
        if audio_data.dtype != np.int16:
            audio_data = (audio_data * 32767).astype(np.int16)
        frame = rtc.AudioFrame.create(sample_rate=config.sample_rate, num_channels=1, samples_per_channel=len(audio_data))
        frame_data = np.frombuffer(frame.data, dtype=np.int16).reshape((1, len(audio_data)))
        frame_data[0] = audio_data
        return frame

# Global instances
streaming_engine: Optional[StreamingChatterboxEngine] = None
publisher: Optional[LiveKitAudioPublisher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global streaming_engine, publisher
    logger.info("🚀 Starting June TTS Service (Strict Chatterbox mode)")
    os.makedirs(config.voices_dir, exist_ok=True)
    streaming_engine = StreamingChatterboxEngine(config.device)
    try:
        await streaming_engine.initialize()
        if config.warmup_text:
            logger.info("🔥 Running warmup generation")
            async for _ in streaming_engine.synthesize_streaming(text=config.warmup_text[:64]):
                break
    except Exception:
        logger.error("❌ Fatal: Chatterbox not usable. Exiting.")
        # Fail FastAPI startup to force container restart
        raise
    publisher = LiveKitAudioPublisher()
    yield

app = FastAPI(title="June TTS Service", version="2.0.0", description="Chatterbox TTS with LiveKit streaming (strict)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/tts/synthesize", response_model=TTSResponse)
async def synthesize_tts(request: TTSRequest, auth_data: dict = Depends(require_service_auth)):
    start_time = time.time()
    if not streaming_engine or not publisher:
        raise HTTPException(status_code=503, detail="Chatterbox not initialized")
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
    result = await publisher.publish_streaming_audio(room_name=request.room_name, audio_stream=audio_stream)
    duration_ms = (time.time() - start_time) * 1000
    metrics["requests_processed"] += 1
    metrics["streaming_requests"] += 1
    metrics["total_audio_seconds"] += result["duration_seconds"]
    if request.voice_mode == "clone":
        metrics["voice_cloning_requests"] += 1
    else:
        metrics["predefined_voice_requests"] += 1
    return TTSResponse(status="completed", room_name=request.room_name, duration_ms=duration_ms, chunks_sent=result["chunks_sent"], voice_mode=request.voice_mode, voice_cloned=(request.voice_mode == "clone"))

@app.get("/health", response_model=HealthResponse)
async def health_check():
    # In strict mode, if app is up, Chatterbox is available
    return HealthResponse(status="healthy", gpu_available=torch.cuda.is_available(), device=config.device, streaming_enabled=config.enable_streaming, chatterbox_available=True)

@app.get("/")
async def root():
    return {"service": "june-tts", "version": "2.0.0", "engine": "chatterbox", "strict_mode": True}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
