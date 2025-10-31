#!/usr/bin/env python3
"""
June TTS Service - XTTS v2 Compliant LiveKit Integration
Enhanced with multi-reference voice cloning, language validation,
and robust real-time publishing pipeline.
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
from urllib.parse import urlparse
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from livekit import rtc
from livekit_token import connect_room_as_publisher
from TTS.api import TTS
import numpy as np
import soundfile as sf
import httpx

from config import config

# Accept Coqui TTS license
os.environ['COQUI_TOS_AGREED'] = '1'

# Enable detailed debug logs for LiveKit and our app
os.environ.setdefault("RUST_LOG", "livekit=debug,livekit_api=debug,livekit_ffi=debug,livekit_rtc=debug")
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("june-tts")

# XTTS v2 supported languages (17 languages as per official docs)
SUPPORTED_LANGUAGES = {
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", 
    "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi"
}

# Global TTS and LiveKit instances
tts_instance: Optional[TTS] = None
tts_room: Optional[rtc.Room] = None
audio_source: Optional[rtc.AudioSource] = None
room_connected = False
device = "cuda" if torch.cuda.is_available() else "cpu"

# Publishing pipeline
publish_queue: asyncio.Queue = None
reference_cache: Dict[str, str] = {}  # URL/path -> local temp file cache

# Metrics tracking
metrics = {
    "synthesis_count": 0,
    "publish_count": 0,
    "total_synthesis_time": 0.0,
    "total_publish_time": 0.0,
    "cache_hits": 0,
    "cache_misses": 0
}

class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize", max_length=1500)  # Reduced for real-time
    language: str = Field("en", description="Language code (ISO 639-1)")
    speaker: Optional[str] = Field(None, description="Built-in speaker name (fallback)")
    speaker_wav: Optional[Union[str, List[str]]] = Field(
        None, 
        description="Reference audio file(s) for voice cloning. Can be single path/URL or list for better quality"
    )
    speed: float = Field(1.0, description="Speech speed", ge=0.5, le=2.0)
    
    @field_validator('language')
    @classmethod
    def validate_language(cls, v):
        if v not in SUPPORTED_LANGUAGES:
            logger.warning(f"Unsupported language '{v}', defaulting to 'en'. Supported: {sorted(SUPPORTED_LANGUAGES)}")
            return "en"
        return v
    
    @field_validator('speaker_wav')
    @classmethod
    def normalize_speaker_wav(cls, v):
        if isinstance(v, str):
            # Handle comma-separated string
            if ',' in v:
                return [s.strip() for s in v.split(',') if s.strip()]
            return [v]
        return v

class PublishToRoomRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize and publish to room", max_length=1500)
    language: str = Field("en", description="Language code (ISO 639-1)")
    speaker: Optional[str] = Field(None, description="Built-in speaker name (fallback)")
    speaker_wav: Optional[Union[str, List[str]]] = Field(
        None,
        description="Reference audio file(s) for voice cloning. Can be single path/URL or list for better quality"
    )
    speed: float = Field(1.0, description="Speech speed", ge=0.5, le=2.0)
    
    @field_validator('language')
    @classmethod
    def validate_language(cls, v):
        if v not in SUPPORTED_LANGUAGES:
            logger.warning(f"Unsupported language '{v}', defaulting to 'en'. Supported: {sorted(SUPPORTED_LANGUAGES)}")
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

class SynthesisResponse(BaseModel):
    status: str
    text_length: int
    audio_size: int
    synthesis_time_ms: float
    language: str
    speaker_references: int = 0
    cache_hit: bool = False
    message: str = ""

async def download_reference_audio(url: str) -> str:
    """Download and cache reference audio from URL"""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    
    if url_hash in reference_cache:
        if os.path.exists(reference_cache[url_hash]):
            metrics["cache_hits"] += 1
            return reference_cache[url_hash]
    
    metrics["cache_misses"] += 1
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            # Create temp file
            suffix = '.wav' if url.lower().endswith('.wav') else '.mp3'
            temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            temp_file.write(response.content)
            temp_file.close()
            
            # Validate and normalize audio
            try:
                audio, sr = sf.read(temp_file.name)
                if len(audio.shape) > 1:
                    audio = audio.mean(axis=1)  # Convert to mono
                
                # Resample to 24kHz if needed
                if sr != 24000:
                    try:
                        import librosa
                        audio = librosa.resample(audio, orig_sr=sr, target_sr=24000)
                    except ImportError:
                        from scipy import signal
                        num_samples = int(len(audio) * 24000 / sr)
                        audio = signal.resample(audio, num_samples)
                
                # Save normalized version
                sf.write(temp_file.name, audio, 24000)
                
                reference_cache[url_hash] = temp_file.name
                return temp_file.name
                
            except Exception as e:
                logger.warning(f"Failed to normalize reference audio from {url}: {e}")
                os.unlink(temp_file.name)
                raise HTTPException(status_code=422, detail=f"Invalid reference audio format: {e}")
                
    except Exception as e:
        logger.error(f"Failed to download reference audio from {url}: {e}")
        raise HTTPException(status_code=422, detail=f"Failed to download reference audio: {e}")

async def prepare_speaker_references(speaker_wav: Optional[List[str]]) -> Optional[List[str]]:
    """Download and validate speaker reference files"""
    if not speaker_wav:
        return None
    
    prepared_refs = []
    for ref in speaker_wav:
        if ref.startswith(('http://', 'https://')):
            # Download remote file
            local_path = await download_reference_audio(ref)
            prepared_refs.append(local_path)
        else:
            # Validate local file
            if not os.path.exists(ref):
                raise HTTPException(status_code=422, detail=f"Reference audio file not found: {ref}")
            
            # Validate audio format
            try:
                audio, sr = sf.read(ref)
                if len(audio) < sr * 2:  # Less than 2 seconds
                    logger.warning(f"Reference audio {ref} is shorter than recommended 6 seconds")
                prepared_refs.append(ref)
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Invalid reference audio {ref}: {e}")
    
    return prepared_refs

def process_audio_for_livekit(audio_array, source_sample_rate=24000, target_sample_rate=24000):
    """Process audio array for LiveKit with proper format conversion"""
    # Ensure float32 format
    if audio_array.dtype != np.float32:
        audio_array = audio_array.astype(np.float32)
    
    # Convert to mono if stereo
    if len(audio_array.shape) > 1:
        audio_array = audio_array.mean(axis=1)
    
    # Normalize audio to prevent clipping
    max_val = np.abs(audio_array).max()
    if max_val > 0.95:
        audio_array = audio_array * (0.95 / max_val)
    
    # Use librosa for better resampling if available, fallback to scipy
    if source_sample_rate != target_sample_rate:
        try:
            import librosa
            audio_array = librosa.resample(audio_array, orig_sr=source_sample_rate, target_sr=target_sample_rate)
        except ImportError:
            logger.warning("librosa not available, using scipy for resampling")
            from scipy import signal
            num_samples = int(len(audio_array) * target_sample_rate / source_sample_rate)
            audio_array = signal.resample(audio_array, num_samples)
    
    # Convert to int16 for LiveKit
    audio_int16 = (audio_array * 32767).astype(np.int16)
    
    return audio_int16

async def synthesis_worker():
    """Background worker for TTS synthesis with timeout protection"""
    while True:
        try:
            task = await publish_queue.get()
            if task is None:  # Shutdown signal
                break
                
            request, response_future = task
            
            try:
                # Synthesis with timeout
                start_time = time.time()
                result = await asyncio.wait_for(
                    perform_synthesis(request),
                    timeout=10.0  # 10 second synthesis timeout
                )
                synthesis_time = (time.time() - start_time) * 1000
                
                # Update metrics
                metrics["synthesis_count"] += 1
                metrics["total_synthesis_time"] += synthesis_time
                
                # Set result
                if not response_future.cancelled():
                    response_future.set_result((result, synthesis_time))
                    
            except asyncio.TimeoutError:
                logger.error(f"Synthesis timeout for text: {request.text[:50]}...")
                if not response_future.cancelled():
                    response_future.set_exception(HTTPException(status_code=504, detail="Synthesis timeout"))
            except Exception as e:
                logger.exception(f"Synthesis error: {e}")
                if not response_future.cancelled():
                    response_future.set_exception(e)
                    
            publish_queue.task_done()
            
        except Exception as e:
            logger.exception(f"Synthesis worker error: {e}")
            await asyncio.sleep(1)

async def perform_synthesis(request: Union[TTSRequest, PublishToRoomRequest]) -> bytes:
    """Perform TTS synthesis with XTTS v2"""
    global tts_instance
    
    if not tts_instance:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    
    # Prepare speaker references
    speaker_refs = await prepare_speaker_references(request.speaker_wav)
    
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        output_path = f.name
    
    try:
        logger.info(f"🎤 Synthesizing ({request.language}): {request.text[:80]}...")
        
        kwargs = {
            "text": request.text,
            "language": request.language,
            "file_path": output_path,
            "speed": request.speed,
            "split_sentences": True  # Improves quality and enables streaming
        }
        
        # Use multiple references for better cloning
        if speaker_refs:
            if len(speaker_refs) == 1:
                kwargs["speaker_wav"] = speaker_refs[0]
            else:
                kwargs["speaker_wav"] = speaker_refs  # Pass list for multi-reference
        elif request.speaker:
            kwargs["speaker"] = request.speaker
        
        # Run synthesis in thread to avoid blocking event loop
        await asyncio.to_thread(tts_instance.tts_to_file, **kwargs)
        
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
            
        return audio_bytes
        
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)

async def join_livekit_room():
    """Join LiveKit room as TTS participant"""
    global tts_room, audio_source, room_connected

    try:
        logger.debug("Preparing to obtain LiveKit token and connect as publisher")
        tts_room = rtc.Room()

        # Event handlers
        @tts_room.on("connecting")
        def on_connecting():
            logger.debug("[LiveKit] Room connecting...")

        @tts_room.on("connected")
        def on_connected():
            logger.debug("[LiveKit] Room connected")

        @tts_room.on("reconnecting")
        def on_reconnecting():
            logger.debug("[LiveKit] Room reconnecting...")

        @tts_room.on("reconnected")
        def on_reconnected():
            logger.debug("[LiveKit] Room reconnected")

        @tts_room.on("disconnected")
        def on_disconnected():
            logger.debug("[LiveKit] Room disconnected")
            global room_connected
            room_connected = False

        @tts_room.on("participant_connected")
        def on_participant_connected(participant):
            logger.debug(f"[LiveKit] Participant connected: {participant.identity}")

        @tts_room.on("participant_disconnected")
        def on_participant_disconnected(participant):
            logger.debug(f"[LiveKit] Participant disconnected: {participant.identity}")

        logger.info("🔊 TTS connecting to LiveKit room via orchestrator token")
        await connect_room_as_publisher(tts_room, "june-tts")
        
        # Create audio source
        audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("ai-response", audio_source)

        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE

        await tts_room.local_participant.publish_track(track, options)
        logger.info("🎤 TTS audio track published")

        room_connected = True
        logger.info("✅ TTS connected to ozzu-main room")

    except Exception as e:
        logger.exception(f"❌ Failed to connect to LiveKit: {e}")
        room_connected = False

async def publish_audio_to_room(audio_data: bytes) -> Dict[str, Any]:
    """Enhanced audio publishing with metrics and monotonic timing"""
    global audio_source

    if not room_connected or not audio_source:
        logger.error("TTS not connected to room or audio_source not ready")
        return {"success": False, "error": "Not connected to room"}

    start_time = time.time()
    
    try:
        # Load and process audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_data)
            temp_path = f.name
        
        try:
            audio_array, sample_rate = sf.read(temp_path)
            processed_audio = process_audio_for_livekit(audio_array, sample_rate, 24000)
            
            # Create frames with exact 20ms chunks (480 samples @ 24kHz)
            frame_samples = 480
            total_frames = len(processed_audio) // frame_samples
            frames_sent = 0
            
            # Monotonic timing for consistent playback
            frame_start_time = time.time()
            
            for i in range(0, len(processed_audio), frame_samples):
                chunk = processed_audio[i:i + frame_samples]
                
                # Pad if necessary
                if len(chunk) < frame_samples:
                    chunk = np.pad(chunk, (0, frame_samples - len(chunk)), mode='constant')
                
                # Create AudioFrame
                frame = rtc.AudioFrame(
                    data=chunk.tobytes(),
                    sample_rate=24000,
                    num_channels=1,
                    samples_per_channel=len(chunk)
                )
                
                try:
                    await audio_source.capture_frame(frame)
                    frames_sent += 1
                    
                    # Monotonic 20ms timing
                    expected_time = frame_start_time + (frames_sent * 0.02)
                    current_time = time.time()
                    sleep_time = expected_time - current_time
                    
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                    elif sleep_time < -0.1:  # More than 100ms behind
                        logger.warning(f"Publishing falling behind by {-sleep_time*1000:.1f}ms")
                    
                except Exception as e:
                    logger.warning(f"Frame capture failed: {e}")
                    continue
            
            publish_time = (time.time() - start_time) * 1000
            
            # Update metrics
            metrics["publish_count"] += 1
            metrics["total_publish_time"] += publish_time
            
            logger.info(f"✅ Published {frames_sent}/{total_frames} frames in {publish_time:.1f}ms")
            
            return {
                "success": True,
                "frames_sent": frames_sent,
                "total_frames": total_frames,
                "publish_time_ms": publish_time,
                "audio_duration_ms": len(processed_audio) / 24 * 1000
            }
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        publish_time = (time.time() - start_time) * 1000
        logger.exception(f"❌ Error publishing audio: {e}")
        return {"success": False, "error": str(e), "publish_time_ms": publish_time}

async def warmup_model():
    """Warmup TTS model to reduce first-request latency"""
    global tts_instance
    
    if not tts_instance:
        return
    
    logger.info("🔥 Warming up TTS model...")
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            warmup_path = f.name
        
        # Short warmup synthesis with a built-in speaker to avoid the error
        await asyncio.to_thread(
            tts_instance.tts_to_file,
            text="Warmup test.",
            language="en",
            file_path=warmup_path,
            speaker="Claribel Dervla",  # Use built-in speaker for warmup
            split_sentences=True
        )
        
        if os.path.exists(warmup_path):
            os.unlink(warmup_path)
            
        logger.info("✅ TTS model warmed up")
        
    except Exception as e:
        logger.warning(f"⚠️ Model warmup failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global tts_instance, publish_queue
    
    logger.info(f"🚀 Starting June TTS Service v3.0 - XTTS v2 Compliant on device: {device}")
    
    try:
        # Initialize TTS model
        model_name = os.getenv("TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
        logger.info(f"Loading TTS model: {model_name}")
        tts_instance = TTS(model_name=model_name).to(device)
        logger.info("✅ TTS model initialized")
        
        # Warmup model
        await warmup_model()
        
        # Initialize publishing queue and worker
        publish_queue = asyncio.Queue(maxsize=10)
        synthesis_task = asyncio.create_task(synthesis_worker())
        
        # Connect to LiveKit
        await join_livekit_room()
        
        logger.info("🎉 June TTS Service fully initialized")
        logger.info(f"📊 Supported languages: {sorted(SUPPORTED_LANGUAGES)}")
        
    except Exception as e:
        logger.exception(f"❌ TTS initialization failed: {e}")

    yield

    logger.info("🛑 Shutting down TTS service")
    
    # Shutdown synthesis worker
    if publish_queue:
        await publish_queue.put(None)
        synthesis_task.cancel()
    
    # Disconnect from LiveKit
    if tts_room and room_connected:
        await tts_room.disconnect()
    
    # Cleanup reference cache
    for temp_file in reference_cache.values():
        if os.path.exists(temp_file):
            os.unlink(temp_file)

app = FastAPI(
    title="June TTS Service",
    version="3.0.0",
    description="XTTS v2 compliant text-to-speech service with LiveKit room integration",
    lifespan=lifespan
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
    return {
        "service": "june-tts",
        "version": "3.0.0",
        "description": "XTTS v2 compliant TTS service",
        "features": [
            "Multi-reference voice cloning",
            "17 language support",
            "Real-time LiveKit publishing",
            "Reference audio caching",
            "Synthesis timeout protection",
            "Performance metrics"
        ],
        "status": "running",
        "tts_ready": tts_instance is not None,
        "device": device,
        "livekit_connected": room_connected,
        "supported_languages": sorted(SUPPORTED_LANGUAGES),
        "room": "ozzu-main" if room_connected else None
    }

@app.get("/healthz")
async def health():
    return {
        "status": "healthy",
        "tts_ready": tts_instance is not None,
        "livekit_connected": room_connected,
        "device": device,
        "queue_size": publish_queue.qsize() if publish_queue else 0
    }

@app.get("/metrics")
async def get_metrics():
    """Get service performance metrics"""
    avg_synthesis_time = (
        metrics["total_synthesis_time"] / metrics["synthesis_count"]
        if metrics["synthesis_count"] > 0 else 0
    )
    avg_publish_time = (
        metrics["total_publish_time"] / metrics["publish_count"]
        if metrics["publish_count"] > 0 else 0
    )
    
    return {
        "synthesis_count": metrics["synthesis_count"],
        "publish_count": metrics["publish_count"],
        "avg_synthesis_time_ms": round(avg_synthesis_time, 2),
        "avg_publish_time_ms": round(avg_publish_time, 2),
        "cache_hits": metrics["cache_hits"],
        "cache_misses": metrics["cache_misses"],
        "cache_hit_rate": (
            metrics["cache_hits"] / (metrics["cache_hits"] + metrics["cache_misses"])
            if (metrics["cache_hits"] + metrics["cache_misses"]) > 0 else 0
        ),
        "reference_cache_size": len(reference_cache),
        "queue_size": publish_queue.qsize() if publish_queue else 0
    }

@app.post("/synthesize", response_model=SynthesisResponse)
async def synthesize_audio(request: TTSRequest):
    """Synthesize audio with XTTS v2"""
    if not tts_instance:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    
    start_time = time.time()
    
    try:
        audio_bytes = await perform_synthesis(request)
        synthesis_time = (time.time() - start_time) * 1000
        
        # Update metrics
        metrics["synthesis_count"] += 1
        metrics["total_synthesis_time"] += synthesis_time
        
        # Return raw audio
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=speech.wav"}
        )
        
    except Exception as e:
        logger.exception(f"❌ Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/publish-to-room", response_model=SynthesisResponse)
async def publish_to_room(request: PublishToRoomRequest, background_tasks: BackgroundTasks):
    """Synthesize and publish audio to LiveKit room"""
    if not tts_instance:
        raise HTTPException(status_code=503, detail="TTS model not ready")
    if not room_connected:
        raise HTTPException(status_code=503, detail="Not connected to LiveKit room")
    
    start_time = time.time()
    
    try:
        # Queue synthesis task
        response_future = asyncio.Future()
        await publish_queue.put((request, response_future))
        
        # Wait for synthesis
        audio_bytes, synthesis_time = await response_future
        
        # Publish in background
        background_tasks.add_task(publish_audio_to_room, audio_bytes)
        
        speaker_refs = len(request.speaker_wav) if request.speaker_wav else 0
        
        return SynthesisResponse(
            status="success",
            text_length=len(request.text),
            audio_size=len(audio_bytes),
            synthesis_time_ms=round(synthesis_time, 2),
            language=request.language,
            speaker_references=speaker_refs,
            message="Audio being published to room"
        )
        
    except Exception as e:
        logger.exception(f"❌ Publish error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/token")
async def debug_token():
    """Return current connection parameters for diagnostics"""
    return {
        "orchestrator_url": config.ORCHESTRATOR_URL,
        "livekit_ws_url": config.LIVEKIT_WS_URL,
        "device": device,
        "model": os.getenv("TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
    }

@app.get("/debug/audio-test")
async def test_audio_generation():
    """Generate a test tone to verify audio pipeline"""
    if not room_connected:
        return {"error": "Not connected to room"}
    
    # Generate test tone
    duration = 2.0
    sample_rate = 24000
    frequency = 440.0
    
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    tone = np.sin(2 * np.pi * frequency * t) * 0.3
    tone_int16 = (tone * 32767).astype(np.int16)
    
    # Save and publish
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        sf.write(f.name, tone_int16, sample_rate)
        with open(f.name, "rb") as audio_file:
            audio_bytes = audio_file.read()
        os.unlink(f.name)
    
    result = await publish_audio_to_room(audio_bytes)
    
    return {
        "test_tone_published": result["success"],
        "duration": duration,
        "frequency": frequency,
        "result": result
    }

@app.get("/languages")
async def get_supported_languages():
    """Get list of supported languages"""
    return {
        "supported_languages": sorted(SUPPORTED_LANGUAGES),
        "count": len(SUPPORTED_LANGUAGES),
        "default": "en"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)