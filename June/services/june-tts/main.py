#!/usr/bin/env python3
"""
Optimized June TTS Service - Chatterbox TTS + LiveKit Integration
Includes torch.compile, streaming, batching, and caching optimizations
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
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from livekit import rtc
from livekit_token import connect_room_as_publisher
import numpy as np
import soundfile as sf
import httpx

from config import config
from chatterbox_engine_optimized import optimized_chatterbox_engine

# Enable detailed debug logs for LiveKit and our app
os.environ.setdefault("RUST_LOG", "livekit=debug,livekit_api=debug,livekit_ffi=debug,livekit_rtc=debug")
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("june-tts-optimized")

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

# Optimized processing pipelines
publish_queue: asyncio.Queue = None
batch_processor: Optional['BatchProcessor'] = None
request_cache: Dict[str, bytes] = {}
reference_cache: Dict[str, str] = {}

# Enhanced metrics tracking
metrics = {
    "synthesis_count": 0,
    "publish_count": 0, 
    "total_synthesis_time": 0.0,
    "total_publish_time": 0.0,
    "cache_hits": 0,
    "cache_misses": 0,
    "batch_requests": 0,
    "streaming_requests": 0,
    "optimization_gains": 0.0
}


@dataclass
class BatchRequest:
    request: 'TTSRequest'
    future: asyncio.Future
    timestamp: float
    priority: int = 0


class BatchProcessor:
    """Intelligent batch processing for TTS requests"""
    
    def __init__(self, max_batch_size: int = 4, max_wait_time: float = 0.1):
        self.max_batch_size = max_batch_size
        self.max_wait_time = max_wait_time
        self.pending_requests = deque()
        self.processing = False
        
    async def add_request(self, request: 'TTSRequest') -> bytes:
        """Add request to batch and return audio bytes"""
        future = asyncio.Future()
        batch_req = BatchRequest(request, future, time.time())
        self.pending_requests.append(batch_req)
        
        # Start processing if not already running
        if not self.processing:
            asyncio.create_task(self._process_batch())
            
        return await future
        
    async def _process_batch(self):
        """Process accumulated requests in batches"""
        if self.processing:
            return
            
        self.processing = True
        
        try:
            while self.pending_requests:
                # Collect batch
                batch = []
                start_time = time.time()
                
                # Wait for requests or timeout
                while (len(batch) < self.max_batch_size and 
                       len(self.pending_requests) > 0 and
                       (time.time() - start_time) < self.max_wait_time):
                    
                    if self.pending_requests:
                        batch.append(self.pending_requests.popleft())
                    else:
                        await asyncio.sleep(0.01)
                        
                if not batch:
                    break
                    
                # Process batch
                await self._execute_batch(batch)
                metrics["batch_requests"] += len(batch)
                
        finally:
            self.processing = False
            
    async def _execute_batch(self, batch: List[BatchRequest]):
        """Execute a batch of TTS requests"""
        # Group by similar parameters for better batching
        groups = defaultdict(list)
        for req in batch:
            key = (req.request.language, req.request.exaggeration, req.request.cfg_weight)
            groups[key].append(req)
            
        # Process each group
        for group in groups.values():
            tasks = []
            for batch_req in group:
                task = asyncio.create_task(
                    self._synthesize_single(batch_req.request)
                )
                tasks.append((batch_req, task))
                
            # Wait for all in group to complete
            for batch_req, task in tasks:
                try:
                    result = await task
                    if not batch_req.future.cancelled():
                        batch_req.future.set_result(result)
                except Exception as e:
                    if not batch_req.future.cancelled():
                        batch_req.future.set_exception(e)
    
    async def _synthesize_single(self, request: 'TTSRequest') -> bytes:
        """Synthesize single request with caching"""
        cache_key = self._get_cache_key(request)
        
        # Check cache first
        if cache_key in request_cache:
            metrics["cache_hits"] += 1
            return request_cache[cache_key]
            
        metrics["cache_misses"] += 1
        
        # Perform synthesis
        speaker_refs = await prepare_speaker_references(request.speaker_wav)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name
            
        try:
            await optimized_chatterbox_engine.synthesize_to_file(
                text=request.text,
                file_path=out_path,
                language=request.language,
                speaker_wav=speaker_refs,
                speed=request.speed,
                exaggeration=request.exaggeration,
                cfg_weight=request.cfg_weight,
                enable_streaming=getattr(request, 'streaming', False)
            )
            
            with open(out_path, "rb") as f:
                audio_bytes = f.read()
                
            # Cache result
            if len(request_cache) < 100:  # Limit cache size
                request_cache[cache_key] = audio_bytes
                
            return audio_bytes
            
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)
                
    def _get_cache_key(self, request: 'TTSRequest') -> str:
        """Generate cache key for request"""
        key_data = f"{request.text}|{request.language}|{request.exaggeration}|{request.cfg_weight}"
        if request.speaker_wav:
            wav_key = "|".join(request.speaker_wav) if isinstance(request.speaker_wav, list) else request.speaker_wav
            key_data += f"|{wav_key}"
        return hashlib.md5(key_data.encode()).hexdigest()


class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize", max_length=1500)
    language: str = Field("en", description="Language code (ISO 639-1)")
    speaker: Optional[str] = Field(None, description="(Ignored) retained for compatibility")
    speaker_wav: Optional[Union[str, List[str]]] = Field(None, description="Reference audio file(s) for voice cloning")
    speed: float = Field(1.0, description="Speech speed (compat only)", ge=0.5, le=2.0)
    exaggeration: float = Field(0.6, description="Emotion intensity 0.0-2.0", ge=0.0, le=2.0)
    cfg_weight: float = Field(0.8, description="Pacing control 0.1-1.0", ge=0.1, le=1.0)
    streaming: bool = Field(False, description="Enable streaming synthesis for lower latency")
    priority: int = Field(0, description="Request priority (higher = more urgent)")
    enable_batching: bool = Field(True, description="Enable batch processing")

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


class SynthesisResponse(BaseModel):
    status: str
    text_length: int
    audio_size: int
    synthesis_time_ms: float
    language: str
    speaker_references: int = 0
    cache_hit: bool = False
    optimization_used: str = ""
    streaming_enabled: bool = False
    batch_processed: bool = False
    message: str = ""


async def download_reference_audio(url: str) -> str:
    """Download and cache reference audio with optimization"""
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
    """Prepare speaker references with caching"""
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


async def perform_synthesis_optimized(request: Union[TTSRequest, PublishToRoomRequest]) -> bytes:
    """Optimized synthesis with batching and caching"""
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    
    # Use batch processor if enabled
    if request.enable_batching and batch_processor:
        return await batch_processor.add_request(request)
    
    # Direct processing for high-priority or non-batchable requests
    return await batch_processor._synthesize_single(request)


async def join_livekit_room():
    """Connect to LiveKit room with error handling"""
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
        logger.info("✅ TTS connected to ozzu-main room")
    except Exception as e:
        logger.exception(f"❌ Failed to connect to LiveKit: {e}")
        room_connected = False


async def publish_audio_to_room(audio_data: bytes) -> Dict[str, Any]:
    """Optimized audio publishing to LiveKit room"""
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
            # 20ms pacing
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Optimized startup and shutdown"""
    global tts_ready, publish_queue, batch_processor
    logger.info(f"🚀 Starting Optimized June TTS Service v5.0 - Chatterbox on device: {device}")
    try:
        # Initialize optimized engine
        await optimized_chatterbox_engine.initialize(enable_optimizations=True)
        
        # Warmup compiled models
        await optimized_chatterbox_engine.warmup()
        
        tts_ready = True
        
        # Initialize processing pipeline
        publish_queue = asyncio.Queue(maxsize=20)
        batch_processor = BatchProcessor(max_batch_size=4, max_wait_time=0.1)
        
        # Connect to LiveKit
        await join_livekit_room()
        
        logger.info("🎉 Optimized June TTS Service fully initialized")
        logger.info("⚡ Optimizations: %s", optimized_chatterbox_engine.get_optimization_status())
        
    except Exception as e:
        logger.exception(f"❌ TTS initialization failed: {e}")
    yield
    
    # Cleanup
    if tts_room:
        await tts_room.disconnect()


app = FastAPI(
    title="Optimized June TTS Service",
    version="5.0.0",
    description="High-performance Chatterbox TTS with torch.compile, streaming, batching, and caching",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    optimization_status = optimized_chatterbox_engine.get_optimization_status()
    return {
        "service": "june-tts-optimized",
        "version": "5.0.0",
        "engine": "chatterbox-tts-optimized",
        "features": [
            "torch.compile with CUDA graphs (2-4x speedup)",
            "Mixed precision (bfloat16)",
            "Streaming synthesis",
            "Intelligent batching",
            "Request & reference caching",
            "Performance metrics",
            "Zero-shot voice cloning",
            "23+ language support",
            "Real-time LiveKit publishing",
        ],
        "status": "running",
        "tts_ready": tts_ready,
        "device": device,
        "livekit_connected": room_connected,
        "supported_languages": sorted(SUPPORTED_LANGUAGES),
        "room": "ozzu-main" if room_connected else None,
        "optimizations": optimization_status,
    }


@app.get("/healthz")
async def health():
    return {
        "status": "healthy" if tts_ready else "initializing",
        "tts_ready": tts_ready,
        "livekit_connected": room_connected,
        "device": device,
        "queue_size": publish_queue.qsize() if publish_queue else 0,
        "cache_size": len(request_cache),
        "optimizations_active": optimized_chatterbox_engine.optimizations_enabled if tts_ready else {},
    }


@app.get("/metrics")
async def get_metrics():
    """Enhanced metrics with optimization data"""
    avg_synth = metrics["total_synthesis_time"] / metrics["synthesis_count"] if metrics["synthesis_count"] else 0
    avg_pub = metrics["total_publish_time"] / metrics["publish_count"] if metrics["publish_count"] else 0
    cache_hit_rate = metrics["cache_hits"] / (metrics["cache_hits"] + metrics["cache_misses"]) if (metrics["cache_hits"] + metrics["cache_misses"]) > 0 else 0
    
    base_metrics = {
        "synthesis_count": metrics["synthesis_count"],
        "publish_count": metrics["publish_count"],
        "avg_synthesis_time_ms": round(avg_synth, 2),
        "avg_publish_time_ms": round(avg_pub, 2),
        "cache_hits": metrics["cache_hits"],
        "cache_misses": metrics["cache_misses"],
        "cache_hit_rate": round(cache_hit_rate * 100, 1),
        "batch_requests": metrics["batch_requests"],
        "streaming_requests": metrics["streaming_requests"],
    }
    
    if tts_ready:
        base_metrics.update(optimized_chatterbox_engine.get_optimization_status())
    
    return base_metrics


@app.get("/optimization-status")
async def optimization_status():
    """Get detailed optimization status"""
    if not tts_ready:
        return {"error": "TTS not ready"}
    return optimized_chatterbox_engine.get_optimization_status()


@app.post("/configure-streaming")
async def configure_streaming(chunk_size: int = 50):
    """Configure streaming parameters"""
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS not ready")
    optimized_chatterbox_engine.configure_streaming(chunk_size)
    return {"status": "success", "chunk_size": chunk_size}


@app.post("/synthesize")
async def synthesize_audio(request: TTSRequest):
    """Synthesize audio with optimizations"""
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    
    start = time.time()
    audio_bytes = await perform_synthesis_optimized(request)
    synth_time = (time.time() - start) * 1000
    
    metrics["synthesis_count"] += 1
    metrics["total_synthesis_time"] += synth_time
    
    if request.streaming:
        metrics["streaming_requests"] += 1
    
    return Response(
        content=audio_bytes, 
        media_type="audio/wav",
        headers={
            "Content-Disposition": "attachment; filename=speech.wav",
            "X-Synthesis-Time-Ms": str(round(synth_time, 2)),
            "X-Optimization-Used": "torch-compile" if optimized_chatterbox_engine.compiled else "none"
        }
    )


@app.post("/publish-to-room")
async def publish_to_room(request: PublishToRoomRequest, background_tasks: BackgroundTasks):
    """Publish to LiveKit room with optimizations"""
    if not tts_ready:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    if not room_connected:
        raise HTTPException(status_code=503, detail="Not connected to LiveKit room")
    
    start_time = time.time()
    audio_bytes = await perform_synthesis_optimized(request)
    synth_ms = (time.time() - start_time) * 1000
    
    # Publish in background
    background_tasks.add_task(publish_audio_to_room, audio_bytes)
    
    metrics["synthesis_count"] += 1
    metrics["total_synthesis_time"] += synth_ms
    
    if request.streaming:
        metrics["streaming_requests"] += 1
    
    optimization_used = "torch-compile" if optimized_chatterbox_engine.compiled else "none"
    if request.enable_batching:
        optimization_used += "+batching"
    if request.streaming:
        optimization_used += "+streaming"
    
    return {
        "status": "success",
        "text_length": len(request.text),
        "audio_size": len(audio_bytes),
        "synthesis_time_ms": round(synth_ms, 2),
        "language": request.language,
        "speaker_references": len(request.speaker_wav) if request.speaker_wav else 0,
        "optimization_used": optimization_used,
        "streaming_enabled": request.streaming,
        "batch_processed": request.enable_batching,
        "message": "Audio being published to room (optimized)",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
