#!/usr/bin/env python3
"""
June TTS Service - Chatterbox Integration with Streaming (Strict Mode, Auth Disabled Temporarily)
Implements correct Chatterbox API usage: synchronous generate() with manual chunked streaming.
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
        self.model_sr: Optional[int] = None

    async def initialize(self):
        try:
            self.model = ChatterboxTTS.from_pretrained(device=self.device)
            # Chatterbox exposes sample rate via model.sr
            self.model_sr = int(getattr(self.model, "sr", 24000))
            logger.info(f"✅ Chatterbox TTS initialized on {self.device} (sr={self.model_sr})")
        except Exception as e:
            logger.error(f"❌ Chatterbox TTS initialization failed: {e}")
            raise

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
        # Build params per Chatterbox docs
        params: Dict[str, Any] = {
            "exaggeration": emotion_level,
            "cfg_weight": cfg_weight,
            "temperature": temperature,
        }
        if seed is not None:
            params["seed"] = seed
        params.update(self._voice_config(voice_mode, predefined_voice_id, voice_reference))

        # Generate full waveform synchronously
        logger.info(f"🎤 Generating with Chatterbox (mode={voice_mode})")
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

class LiveKitAudioPublisher:
    async def connect_to_room(self, room_name: str) -> rtc.Room:
        room = rtc.Room()
        from livekit_token import connect_room_as_publisher  # local import to avoid circular
        await connect_room_as_publisher(room, "june-tts", room_name)
        return room

    async def publish_streaming_audio(self, room_name: str, audio_stream: AsyncIterator[np.ndarray], sample_rate: int) -> Dict[str, Any]:
        room = await self.connect_to_room(room_name)
        audio_source = rtc.AudioSource(sample_rate=sample_rate, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("chatterbox-audio", audio_source)
        publication = await room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        chunks_sent, total_duration = 0, 0.0
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
        return {"chunks_sent": chunks_sent, "duration_seconds": total_duration, "room_name": room_name}

# Global instances
streaming_engine: Optional[StreamingChatterboxEngine] = None
publisher: Optional[LiveKitAudioPublisher] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global streaming_engine, publisher
    logger.info("🚀 Starting June TTS Service (Strict Chatterbox mode, auth disabled)")
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
        raise
    publisher = LiveKitAudioPublisher()
    yield

app = FastAPI(title="June TTS Service", version="2.0.0", description="Chatterbox TTS with LiveKit streaming (strict, auth disabled)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/tts/synthesize", response_model=TTSResponse)
async def synthesize_tts(request: TTSRequest):
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
    sr = streaming_engine.model_sr or 24000
    result = await publisher.publish_streaming_audio(room_name=request.room_name, audio_stream=audio_stream, sample_rate=sr)
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
    return HealthResponse(status="healthy", gpu_available=torch.cuda.is_available(), device=config.device, streaming_enabled=config.enable_streaming, chatterbox_available=True)

@app.get("/")
async def root():
    return {"service": "june-tts", "version": "2.0.0", "engine": "chatterbox", "strict_mode": True, "auth": "disabled"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
