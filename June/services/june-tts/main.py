#!/usr/bin/env python3
"""
June TTS Service - Chatterbox TTS + LiveKit Integration + STREAMING
Replaces XTTS v2 engine with Chatterbox while preserving API and LiveKit pipeline.
Adds streaming TTS support for sub-second time-to-first-audio.
"""
import os
import torch
import logging
import tempfile
import asyncio
import time
import hashlib
from contextlib import asynccontextmanager
from typing import Optional, List, Union, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from livekit import rtc
from livekit_token import connect_room_as_publisher
import numpy as np
import soundfile as sf
import httpx

# robust feature flags: config attr -> env var -> default

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

from config import config as _cfg
STREAMING_ENABLED = getattr(_cfg, "TTS_STREAMING_ENABLED", _bool_env("TTS_STREAMING_ENABLED", True))

from config import config
from chatterbox_engine import chatterbox_engine
from streaming_tts import initialize_streaming_tts, stream_tts_to_room, get_streaming_tts_metrics

# Enable detailed debug logs for LiveKit and our app
os.environ.setdefault("RUST_LOG", "livekit=debug,livekit_api=debug,livekit_ffi=debug,livekit_rtc=debug")
logging.basicConfig(
    level=getattr(config, "LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("june-tts")

device = "cuda" if torch.cuda.is_available() else "cpu"

# Expanded languages (Chatterbox supports 23+)
SUPPORTED_LANGUAGES = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru",
    "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi",
    "da", "el", "fi", "he", "ms", "no", "sv", "sw"
}

# Global state
tts_ready = False
tts_room: Optional[rtc.Room] = None
audio_source: Optional[rtc.AudioSource] = None
room_connected = False

# Publishing pipeline
publish_queue: asyncio.Queue = None
reference_cache: Dict[str, str] = {}

# Enhanced metrics tracking
metrics = {
    "synthesis_count": 0, "publish_count": 0, "total_synthesis_time": 0.0, "total_publish_time": 0.0,
    "cache_hits": 0, "cache_misses": 0, "streaming_requests": 0, "regular_requests": 0
}

class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize", max_length=1500)
    language: str = Field("en", description="Language code (ISO 639-1)")
    speaker: Optional[str] = Field(None, description="(Ignored) retained for compatibility")
    speaker_wav: Optional[Union[str, List[str]]] = Field(None, description="Reference audio file(s) for voice cloning")
    speed: float = Field(1.0, description="Speech speed (compat only)", ge=0.5, le=2.0)
    exaggeration: float = Field(0.6, description="Emotion intensity 0.0-2.0", ge=0.0, le=2.0)
    cfg_weight: float = Field(0.8, description="Pacing control 0.1-1.0", ge=0.1, le=1.0)
    streaming: bool = Field(False, description="Enable streaming synthesis for lower latency")

    @field_validator('language')
    @classmethod  
    def validate_language(cls, v):
        if v not in SUPPORTED_LANGUAGES:
            logger.warning(f"Unsupported language '{v}', defaulting to 'en'.")
            return "en"
        return v

    @field_validator('speaker_wav')
    @classmethod
    def normalize_speaker_wav(cls, v):
        if isinstance(v, str):
            if ',' in v:
                return [s.strip() for s in v.split(',') if s.strip()]
            return [v]
        return v

class PublishToRoomRequest(TTSRequest):
    pass

class StreamingTTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize and stream", max_length=1500)
    language: str = Field("en", description="Language code")
    speaker_wav: Optional[List[str]] = Field(None, description="Reference audio files")
    exaggeration: float = Field(0.6, ge=0.0, le=2.0)
    cfg_weight: float = Field(0.8, ge=0.1, le=1.0)

class SynthesisResponse(BaseModel):
    status: str
    text_length: int
    audio_size: int
    synthesis_time_ms: float
    language: str
    speaker_references: int = 0
    cache_hit: bool = False
    streaming_used: bool = False
    first_audio_ms: float = 0.0
    message: str = ""

async def download_reference_audio(url: str) -> str:
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    if url_hash in reference_cache and os.path.exists(reference_cache[url_hash]):
        metrics["cache_hits"] += 1
        return reference_cache[url_hash]
    metrics["cache_misses"] += 1
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(r.content)
            tmp = f.name
    try:
        audio, sr = sf.read(tmp)
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)
        if sr != 24000:
            try:
                import librosa
                audio = librosa.resample(audio, orig_sr=sr, target_sr=24000)
            except Exception:
                from scipy import signal
                num = int(len(audio) * 24000 / sr)
                audio = signal.resample(audio, num)
        sf.write(tmp, audio, 24000)
        reference_cache[url_hash] = tmp
        return tmp
    except Exception as e:
        os.unlink(tmp)
        raise HTTPException(status_code=422, detail=f"Invalid reference audio: {e}")

async def prepare_speaker_references(speaker_wav: Optional[List[str]]) -> Optional[List[str]]:
    if not speaker_wav:
        return None
    prepared = []
    for ref in speaker_wav:
        if ref.startswith(("http://", "https://")):
            prepared.append(await download_reference_audio(ref))
        else:
            if not os.path.exists(ref):
                raise HTTPException(status_code=422, detail=f"Reference file not found: {ref}")
            prepared.append(ref)
    return prepared

async def perform_synthesis(request: Union[TTSRequest, PublishToRoomRequest]) -> bytes:
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS model not ready")

    speaker_refs = await prepare_speaker_references(request.speaker_wav)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_path = f.name
    try:
        await chatterbox_engine.synthesize_to_file(
            text=request.text,
            file_path=out_path,
            language=request.language,
            speaker_wav=speaker_refs,
            speed=request.speed,
            exaggeration=request.exaggeration,
            cfg_weight=request.cfg_weight,
        )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)

async def join_livekit_room():
    global tts_room, audio_source, room_connected
    try:
        tts_room = rtc.Room()
        logger.info("🔊 TTS connecting to LiveKit room via orchestrator token")
        await connect_room_as_publisher(tts_room, "june-tts")
        audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("ai-response", audio_source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        await tts_room.local_participant.publish_track(track, options)
        room_connected = True
        if STREAMING_ENABLED:
            initialize_streaming_tts(audio_source)
        logger.info("✅ TTS connected to ozzu-main room")
        if STREAMING_ENABLED:
            logger.info("⚡ Streaming TTS ready for concurrent processing")
    except Exception as e:
        logger.exception(f"❌ Failed to connect to LiveKit: {e}")
        room_connected = False

async def publish_audio_to_room(audio_data: bytes) -> Dict[str, Any]:
    global audio_source
    if not room_connected or not audio_source:
        return {"success": False, "error": "Not connected to room"}
    start = time.time()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_data)
        tmp = f.name
    try:
        audio, sr = sf.read(tmp)
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)
        if sr != 24000:
            try:
                import librosa
                audio = librosa.resample(audio, orig_sr=sr, target_sr=24000)
            except Exception:
                from scipy import signal
                num = int(len(audio) * 24000 / sr)
                audio = signal.resample(audio, num)
        audio = (audio * 32767).astype(np.int16)
        frame_samples = 480
        frames_sent = 0
        total_frames = len(audio) // frame_samples
        t0 = time.time()
        for i in range(0, len(audio), frame_samples):
            chunk = audio[i:i+frame_samples]
            if len(chunk) < frame_samples:
                chunk = np.pad(chunk, (0, frame_samples - len(chunk)))
            frame = rtc.AudioFrame(
                data=chunk.tobytes(), sample_rate=24000, num_channels=1, samples_per_channel=len(chunk)
            )
            await audio_source.capture_frame(frame)
            frames_sent += 1
            expected = t0 + frames_sent * 0.02
            sleep = expected - time.time()
            if sleep > 0:
                await asyncio.sleep(sleep)
        pub_ms = (time.time() - start) * 1000
        metrics["publish_count"] += 1
        metrics["total_publish_time"] += pub_ms
        return {"success": True, "frames_sent": frames_sent, "total_frames": total_frames, "publish_time_ms": pub_ms}
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

async def warmup_model():
    if not tts_ready:
        return
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        await chatterbox_engine.synthesize_to_file(
            text="Warmup test.", file_path=path, language="en", speaker_wav=None, exaggeration=0.5, cfg_weight=0.8
        )
        if os.path.exists(path):
            os.unlink(path)
        logger.info("✅ TTS model warmed up")
    except Exception as e:
        logger.warning(f"⚠️ Model warmup failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global tts_ready, publish_queue
    logger.info(f"🚀 Starting June TTS Service v5.0 - Chatterbox + Streaming on device: {device}")
    logger.info(f"⚡ Streaming TTS: {STREAMING_ENABLED}")
    try:
        await chatterbox_engine.initialize()
        tts_ready = True
        await warmup_model()
        publish_queue = asyncio.Queue(maxsize=10)
        asyncio.create_task(synthesis_worker())
        await join_livekit_room()
        logger.info("🎉 June TTS Service fully initialized (Chatterbox + Streaming)")
    except Exception as e:
        logger.exception(f"❌ TTS initialization failed: {e}")
    yield

app = FastAPI(
    title="June TTS Service + Streaming",
    version="5.0.0",
    description="Chatterbox TTS with LiveKit room integration + Streaming support for sub-second latency",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def synthesis_worker():
    while True:
        try:
            task = await publish_queue.get()
            if task is None:
                break
            request, fut = task
            try:
                start = time.time()
                audio = await asyncio.wait_for(perform_synthesis(request), timeout=30.0)
                synth_ms = (time.time() - start) * 1000
                metrics["synthesis_count"] += 1
                metrics["total_synthesis_time"] += synth_ms
                metrics["regular_requests"] += 1
                if not fut.cancelled():
                    fut.set_result((audio, synth_ms))
            except Exception as e:
                if not fut.cancelled():
                    fut.set_exception(e)
            finally:
                publish_queue.task_done()
        except Exception:
            await asyncio.sleep(0.5)

@app.get("/")
async def root():
    streaming_stats = get_streaming_tts_metrics() if STREAMING_ENABLED else {}
    return {
        "service": "june-tts",
        "version": "5.0.0",
        "engine": "chatterbox-tts",
        "features": [
            "Zero-shot voice cloning",
            "Emotion control (exaggeration)",
            "Pacing control (cfg_weight)",
            "23+ language support",
            "Real-time LiveKit publishing",
            "Reference audio caching",
            "Synthesis timeout protection",
            "Performance metrics",
            "Streaming TTS support" if STREAMING_ENABLED else "Standard TTS",
        ],
        "status": "running",
        "tts_ready": tts_ready,
        "device": device,
        "livekit_connected": room_connected,
        "supported_languages": sorted(SUPPORTED_LANGUAGES),
        "room": "ozzu-main" if room_connected else None,
        "streaming": {"enabled": STREAMING_ENABLED, "metrics": streaming_stats},
    }

@app.get("/healthz")
async def health():
    return {
        "status": "healthy" if tts_ready else "initializing",
        "tts_ready": tts_ready,
        "livekit_connected": room_connected,
        "device": device,
        "queue_size": publish_queue.qsize() if publish_queue else 0,
        "streaming_enabled": STREAMING_ENABLED,
        "features": {
            "regular_synthesis": True,
            "streaming_synthesis": STREAMING_ENABLED,
            "concurrent_processing": True,
        },
    }

@app.get("/metrics")
async def get_metrics():
    avg_synth = metrics["total_synthesis_time"] / metrics["synthesis_count"] if metrics["synthesis_count"] else 0
    avg_pub = metrics["total_publish_time"] / metrics["publish_count"] if metrics["publish_count"] else 0
    base_metrics = {
        "synthesis_count": metrics["synthesis_count"],
        "publish_count": metrics["publish_count"],
        "avg_synthesis_time_ms": round(avg_synth, 2),
        "avg_publish_time_ms": round(avg_pub, 2),
        "cache_hits": metrics["cache_hits"],
        "cache_misses": metrics["cache_misses"],
        "regular_requests": metrics["regular_requests"],
        "streaming_requests": metrics["streaming_requests"],
    }
    if STREAMING_ENABLED:
        base_metrics["streaming_tts"] = get_streaming_tts_metrics()
    return base_metrics

@app.post("/synthesize")
async def synthesize_audio(request: TTSRequest):
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    start = time.time()
    if request.streaming and STREAMING_ENABLED:
        metrics["streaming_requests"] += 1
        speaker_refs = await prepare_speaker_references(request.speaker_wav)
        result = await stream_tts_to_room(
            text=request.text,
            language=request.language,
            speaker_wav=speaker_refs,
            exaggeration=request.exaggeration,
            cfg_weight=request.cfg_weight,
            chatterbox_engine=chatterbox_engine,
        )
        return {
            "status": "streaming",
            "method": result.get("method", "streaming"),
            "first_audio_ms": result.get("first_audio_ms", 0),
            "chunks_generated": result.get("chunks_sent", 0),
            "message": "Audio streamed to room",
        }
    else:
        metrics["regular_requests"] += 1
        audio_bytes = await perform_synthesis(request)
        synth_time = (time.time() - start) * 1000
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=speech.wav",
                "X-Synthesis-Time-Ms": str(round(synth_time, 2)),
                "X-Method": "regular",
            },
        )

@app.post("/publish-to-room")
async def publish_to_room(request: PublishToRoomRequest, background_tasks: BackgroundTasks):
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    if not room_connected:
        raise HTTPException(status_code=503, detail="Not connected to LiveKit room")
    start_time = time.time()
    if request.streaming and STREAMING_ENABLED:
        metrics["streaming_requests"] += 1
        speaker_refs = await prepare_speaker_references(request.speaker_wav)
        result = await stream_tts_to_room(
            text=request.text,
            language=request.language,
            speaker_wav=speaker_refs,
            exaggeration=request.exaggeration,
            cfg_weight=request.cfg_weight,
            chatterbox_engine=chatterbox_engine,
        )
        return {
            "status": "streaming_success",
            "text_length": len(request.text),
            "method": result.get("method", "streaming"),
            "first_audio_ms": result.get("first_audio_ms", 0),
            "total_time_ms": result.get("total_time_ms", 0),
            "chunks_sent": result.get("chunks_sent", 0),
            "language": request.language,
            "speaker_references": len(request.speaker_wav) if request.speaker_wav else 0,
            "streaming_enabled": True,
            "message": "Audio streamed to room in chunks",
        }
    else:
        metrics["regular_requests"] += 1
        fut = asyncio.Future()
        await publish_queue.put((request, fut))
        audio_bytes, synth_ms = await fut
        background_tasks.add_task(publish_audio_to_room, audio_bytes)
        return {
            "status": "success",
            "text_length": len(request.text),
            "audio_size": len(audio_bytes),
            "synthesis_time_ms": round(synth_ms, 2),
            "language": request.language,
            "speaker_references": len(request.speaker_wav) if request.speaker_wav else 0,
            "streaming_enabled": False,
            "message": "Audio being published to room",
        }

@app.post("/stream-to-room")
async def stream_to_room_endpoint(request: StreamingTTSRequest):
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    if not room_connected:
        raise HTTPException(status_code=503, detail="Not connected to LiveKit room")
    if not STREAMING_ENABLED:
        raise HTTPException(status_code=501, detail="Streaming TTS not enabled")
    logger.info(f"⚡ Streaming TTS request: '{request.text[:50]}...'")
    speaker_refs = await prepare_speaker_references(request.speaker_wav)
    metrics["streaming_requests"] += 1
    result = await stream_tts_to_room(
        text=request.text,
        language=request.language,
        speaker_wav=speaker_refs,
        exaggeration=request.exaggeration,
        cfg_weight=request.cfg_weight,
        chatterbox_engine=chatterbox_engine,
    )
    return {
        "status": "streaming_complete",
        "text_length": len(request.text),
        "method": result.get("method", "streaming"),
        "chunks_sent": result.get("chunks_sent", 0),
        "first_audio_ms": result.get("first_audio_ms", 0),
        "total_time_ms": result.get("total_time_ms", 0),
        "streaming_mode": True,
    }

@app.get("/streaming/status")
async def streaming_status():
    return {
        "streaming_enabled": STREAMING_ENABLED,
        "chunk_size_ms": 200,
        "sample_rate": 24000,
        "metrics": get_streaming_tts_metrics() if STREAMING_ENABLED else {},
        "capabilities": {
            "concurrent_processing": True,
            "chunked_audio_streaming": STREAMING_ENABLED,
            "first_audio_optimization": STREAMING_ENABLED,
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
