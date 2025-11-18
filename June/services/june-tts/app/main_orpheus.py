#!/usr/bin/env python3
"""
June TTS Service - Orpheus Multilingual TTS Integration
Ultra-low latency multilingual TTS with streaming support
"""
import asyncio
import io
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, AsyncGenerator

import numpy as np
import soundfile as sf
import torch
import torchaudio as ta
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from livekit import rtc
from pydantic import BaseModel, Field
import asyncpg

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("june-tts-orpheus")

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
LIVEKIT_IDENTITY = os.getenv("LIVEKIT_IDENTITY", "june-tts")
LIVEKIT_ROOM_NAME = os.getenv("LIVEKIT_ROOM", "ozzu-main")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "https://api.ozzu.world")

# Device settings
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WARMUP_ON_STARTUP = os.getenv("WARMUP_ON_STARTUP", "1") == "1"
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "1000"))

# Orpheus model settings
ORPHEUS_MODEL = os.getenv("ORPHEUS_MODEL", "canopylabs/orpheus-3b-0.1-ft")
ORPHEUS_VARIANT = os.getenv("ORPHEUS_VARIANT", "english")  # or "multilingual"

# vLLM settings for Orpheus
VLLM_GPU_MEMORY_UTILIZATION = float(os.getenv("VLLM_GPU_MEMORY_UTILIZATION", "0.7"))
VLLM_MAX_MODEL_LEN = int(os.getenv("VLLM_MAX_MODEL_LEN", "2048"))
VLLM_QUANTIZATION = os.getenv("VLLM_QUANTIZATION", "fp8")

# Orpheus streaming settings
ORPHEUS_CHUNK_SIZE = int(os.getenv("ORPHEUS_CHUNK_SIZE", "210"))  # SNAC tokens per chunk
ORPHEUS_FADE_MS = int(os.getenv("ORPHEUS_FADE_MS", "5"))  # Fade transition duration

# PostgreSQL
DB_HOST = os.getenv("DB_HOST", "100.64.0.1")
DB_PORT = int(os.getenv("DB_PORT", "30432"))
DB_NAME = os.getenv("DB_NAME", "june")
DB_USER = os.getenv("DB_USER", "keycloak")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Pokemon123!")

# Audio settings
ORPHEUS_SAMPLE_RATE = 24000  # Orpheus native sample rate
LIVEKIT_SAMPLE_RATE = 48000
LIVEKIT_FRAME_SIZE = 960  # 20ms @ 48kHz
FRAME_PERIOD_S = 0.020

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(
    title="June TTS (Orpheus Multilingual)",
    version="8.0.0-orpheus",
    description="Orpheus Multilingual TTS: Ultra-low latency streaming TTS with LLM backbone"
)

# -----------------------------------------------------------------------------
# Global state
# -----------------------------------------------------------------------------
orpheus_model = None  # OrpheusModel instance (handles both LLM and audio decoding internally)
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
voice_cache = {}  # Maps voice_id -> file path

livekit_room = None
livekit_audio_source = None
livekit_connected = False

db_pool = None

current_voice_id: Optional[str] = None
current_reference_audio_path: Optional[str] = None

_gpu_resampler = None

# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    room_name: str = Field(..., description="LiveKit room name")
    voice_id: str = Field(default="default")
    language: str = Field(default="en", description="Language code (en, es, fr, de, it, pt, zh)")
    temperature: float = Field(default=0.7, ge=0.1, le=2.0, description="Sampling temperature")
    repetition_penalty: float = Field(default=1.1, ge=1.0, le=2.0, description="Repetition penalty")
    stream: bool = Field(default=False, description="Enable streaming response")

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
async def init_db_pool():
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            host=DB_HOST, port=DB_PORT, database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, min_size=2, max_size=10
        )
        logger.info("✅ PostgreSQL connection pool created")

        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tts_voices (
                    id SERIAL PRIMARY KEY,
                    voice_id VARCHAR(100) UNIQUE NOT NULL,
                    name VARCHAR(255),
                    audio_data BYTEA NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        logger.info("✅ Voices table ready")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        # Continue without DB - will use default voice only

async def get_voice_from_db(voice_id: str) -> Optional[bytes]:
    if db_pool is None:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT audio_data FROM tts_voices WHERE voice_id = $1", voice_id
        )
    if row:
        logger.info(f"✅ Loaded voice '{voice_id}' from DB")
        return bytes(row["audio_data"])
    logger.warning(f"⚠️ Voice '{voice_id}' not found in DB")
    return None

async def load_voice_reference(voice_id: str = "default") -> Optional[str]:
    """Load voice reference and return path to temp file"""
    global current_voice_id, current_reference_audio_path

    # Check cache
    if voice_id in voice_cache:
        current_voice_id = voice_id
        current_reference_audio_path = voice_cache[voice_id]
        return current_reference_audio_path

    logger.info(f"📁 Loading voice reference '{voice_id}'...")

    # Try database
    audio_bytes = await get_voice_from_db(voice_id)

    if not audio_bytes:
        # Try default reference file
        default_ref = Path("/app/references/June.wav")
        if default_ref.exists():
            voice_cache[voice_id] = str(default_ref)
            current_voice_id = voice_id
            current_reference_audio_path = str(default_ref)
            logger.info(f"✅ Using default reference audio")
            return current_reference_audio_path
        else:
            logger.warning(f"⚠️ No reference audio for '{voice_id}'")
            return None

    # Save to temp file
    temp_path = f"/tmp/voice_{voice_id}.wav"
    with open(temp_path, 'wb') as f:
        f.write(audio_bytes)

    voice_cache[voice_id] = temp_path
    current_voice_id = voice_id
    current_reference_audio_path = temp_path
    logger.info(f"✅ Voice '{voice_id}' loaded to {temp_path}")
    return temp_path

# -----------------------------------------------------------------------------
# Orpheus Model Management
# -----------------------------------------------------------------------------
async def load_model():
    """Load Orpheus TTS model with vLLM backend"""
    global orpheus_model, snac_decoder

    logger.info("=" * 80)
    logger.info("🚀 Loading Orpheus Multilingual TTS Model")
    logger.info(f"   Model: {ORPHEUS_MODEL}")
    logger.info(f"   Variant: {ORPHEUS_VARIANT}")
    logger.info(f"   Device: {DEVICE}")
    logger.info(f"   GPU Memory Utilization: {VLLM_GPU_MEMORY_UTILIZATION}")
    logger.info(f"   Max Model Length: {VLLM_MAX_MODEL_LEN}")
    logger.info(f"   Quantization: {VLLM_QUANTIZATION}")
    logger.info("=" * 80)

    try:
        # Load Orpheus model
        logger.info("📥 Loading Orpheus LLM model...")

        from orpheus_tts import OrpheusModel
        from vllm import AsyncEngineArgs, AsyncLLMEngine

        # Monkey-patch OrpheusModel._setup_engine to inject vLLM configuration
        # This is necessary because OrpheusModel.__init__ doesn't expose these parameters
        # See: https://github.com/canopyai/Orpheus-TTS/issues/13
        def custom_setup_engine(self):
            engine_args = AsyncEngineArgs(
                model=self.model_name,
                dtype=self.dtype,
                max_model_len=VLLM_MAX_MODEL_LEN,
                gpu_memory_utilization=VLLM_GPU_MEMORY_UTILIZATION,
                quantization=VLLM_QUANTIZATION,
            )
            return AsyncLLMEngine.from_engine_args(engine_args)

        # Apply the monkey patch before instantiation
        OrpheusModel._setup_engine = custom_setup_engine

        # Create OrpheusModel instance (now uses our custom _setup_engine)
        orpheus_model = OrpheusModel(model_name=ORPHEUS_MODEL)
        logger.info("✅ Orpheus model loaded")

        # Note: SNAC decoding is handled internally by orpheus_tts package
        # The generate_speech() method returns ready-to-use audio chunks

        logger.info("⚡ Orpheus TTS Features:")
        logger.info("   - Ultra-low latency (100-200ms)")
        logger.info("   - Real-time streaming support")
        logger.info("   - Zero-shot voice cloning")
        logger.info("   - Multilingual support (7 languages)")
        logger.info("   - LLM-native architecture (Llama-3b)")

        # Warmup generation
        if WARMUP_ON_STARTUP:
            logger.info("⏱️  Warming up Orpheus model...")
            start = time.time()
            warmup_text = "Hello world."

            # Generate warmup audio (consume the iterator)
            warmup_chunks = list(orpheus_model.generate_speech(
                prompt=warmup_text,
                voice=None,
                temperature=0.7,
                repetition_penalty=1.1,
                max_tokens=500
            ))

            elapsed = time.time() - start
            logger.info(f"✅ Warmup complete ({elapsed:.1f}s) - Generated {len(warmup_chunks)} chunks")

        logger.info("✅ Orpheus TTS ready for inference")
        return True

    except ImportError as e:
        logger.error(f"❌ Import error: {e}")
        logger.error("   Make sure 'orpheus-speech' is installed")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to load Orpheus model: {e}", exc_info=True)
        return False

def apply_fade(audio: torch.Tensor, fade_ms: int = 5) -> torch.Tensor:
    """Apply fade in/out to prevent clicks between chunks"""
    if fade_ms <= 0:
        return audio

    fade_samples = int(ORPHEUS_SAMPLE_RATE * fade_ms / 1000)
    if fade_samples >= len(audio):
        return audio

    # Create fade windows
    fade_in = torch.linspace(0, 1, fade_samples, device=audio.device)
    fade_out = torch.linspace(1, 0, fade_samples, device=audio.device)

    # Apply fades
    audio[:fade_samples] *= fade_in
    audio[-fade_samples:] *= fade_out

    return audio

async def generate_async(
    text: str,
    voice_path: Optional[str] = None,
    temperature: float = 0.7,
    repetition_penalty: float = 1.1,
) -> bytes:
    """Generate audio with Orpheus (non-streaming, returns complete WAV bytes)"""
    loop = asyncio.get_event_loop()

    def _generate():
        try:
            # Generate with Orpheus - returns iterator of audio chunks
            audio_chunks = orpheus_model.generate_speech(
                prompt=text,
                voice=voice_path,  # Can be file path or None for default
                temperature=temperature,
                repetition_penalty=repetition_penalty,
                max_tokens=2000,
                top_p=0.9
            )

            # Collect all chunks and combine into single audio bytes
            all_chunks = []
            for chunk in audio_chunks:
                all_chunks.append(chunk)

            # Concatenate all audio chunks
            complete_audio = b''.join(all_chunks)
            return complete_audio

        except Exception as e:
            logger.error(f"❌ Orpheus generation error: {e}", exc_info=True)
            raise

    audio_bytes = await loop.run_in_executor(executor, _generate)
    return audio_bytes

async def generate_stream(
    text: str,
    voice_path: Optional[str] = None,
    temperature: float = 0.7,
    repetition_penalty: float = 1.1,
) -> AsyncGenerator[bytes, None]:
    """Generate audio with Orpheus (streaming) - yields audio byte chunks"""
    loop = asyncio.get_event_loop()

    logger.info("🎙️ Generating with Orpheus (streaming mode)...")

    def _get_generator():
        # Returns the generator from Orpheus
        return orpheus_model.generate_speech(
            prompt=text,
            voice=voice_path,
            temperature=temperature,
            repetition_penalty=repetition_penalty,
            max_tokens=2000,
            top_p=0.9
        )

    # Get the generator in executor
    audio_generator = await loop.run_in_executor(executor, _get_generator)

    # Yield chunks as they come
    for chunk in audio_generator:
        yield chunk

# -----------------------------------------------------------------------------
# LiveKit
# -----------------------------------------------------------------------------
async def get_livekit_token(identity: str, room_name: str):
    import httpx
    url = f"{ORCHESTRATOR_URL}/token"
    payload = {"roomName": room_name, "participantName": identity}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        ws_url = data.get("livekitUrl") or data.get("ws_url")
        token = data["token"]
        if not ws_url:
            raise RuntimeError(f"Missing livekitUrl")
        return ws_url, token

async def connect_livekit():
    global livekit_room, livekit_audio_source, livekit_connected
    try:
        ws_url, token = await get_livekit_token(LIVEKIT_IDENTITY, LIVEKIT_ROOM_NAME)
        room = rtc.Room()
        await room.connect(ws_url, token)

        source = rtc.AudioSource(LIVEKIT_SAMPLE_RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track("orpheus-audio", source)
        opts = rtc.TrackPublishOptions()
        opts.source = rtc.TrackSource.SOURCE_MICROPHONE
        await room.local_participant.publish_track(track, opts)

        livekit_room = room
        livekit_audio_source = source
        livekit_connected = True
        logger.info(f"✅ LiveKit connected at {LIVEKIT_SAMPLE_RATE} Hz")
        return True
    except Exception as e:
        logger.error(f"❌ LiveKit connection failed: {e}")
        return False

def resample_audio_fast(audio: np.ndarray, input_sr: int, output_sr: int) -> np.ndarray:
    global _gpu_resampler
    if input_sr == output_sr:
        return audio

    import torchaudio.transforms as T
    if _gpu_resampler is None or _gpu_resampler.orig_freq != input_sr or _gpu_resampler.new_freq != output_sr:
        _gpu_resampler = T.Resample(input_sr, output_sr)
        if torch.cuda.is_available():
            _gpu_resampler = _gpu_resampler.cuda()

    t = torch.from_numpy(audio).float()
    if t.dim() == 1:
        t = t.unsqueeze(0)
    if torch.cuda.is_available():
        t = t.cuda()

    out = _gpu_resampler(t)
    return out.squeeze().detach().cpu().numpy()

async def stream_audio_to_livekit(audio_data: bytes):
    """Stream audio to LiveKit"""
    global livekit_audio_source, livekit_connected

    if not livekit_connected or livekit_audio_source is None:
        logger.warning("LiveKit not connected")
        return

    # Load audio
    audio, sr = sf.read(io.BytesIO(audio_data))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Resample if needed
    if sr != LIVEKIT_SAMPLE_RATE:
        audio = resample_audio_fast(audio.astype(np.float32), sr, LIVEKIT_SAMPLE_RATE)
    else:
        audio = audio.astype(np.float32)

    # Stream in frames
    frames_sent = 0
    next_deadline = time.perf_counter()

    for i in range(0, len(audio), LIVEKIT_FRAME_SIZE):
        frame_data = audio[i:i+LIVEKIT_FRAME_SIZE]

        # Pad if needed
        if len(frame_data) < LIVEKIT_FRAME_SIZE:
            frame_data = np.pad(frame_data, (0, LIVEKIT_FRAME_SIZE - len(frame_data)))

        # Convert to int16
        pcm_int16 = (np.clip(frame_data, -1.0, 1.0) * 32767).astype(np.int16)

        # Send frame
        frame = rtc.AudioFrame.create(LIVEKIT_SAMPLE_RATE, 1, LIVEKIT_FRAME_SIZE)
        np.copyto(np.frombuffer(frame.data, dtype=np.int16), pcm_int16)
        await livekit_audio_source.capture_frame(frame)

        frames_sent += 1

        # Pace frames
        next_deadline += FRAME_PERIOD_S
        now = time.perf_counter()
        delay = next_deadline - now
        if delay > 0:
            await asyncio.sleep(delay)

    logger.info(f"✅ Streamed {frames_sent} frames to LiveKit")

# -----------------------------------------------------------------------------
# Lifecycle
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    logger.info("=" * 80)
    logger.info("🚀 Orpheus TTS Service Starting")
    logger.info("=" * 80)

    # Load Orpheus model
    success = await load_model()
    if not success:
        logger.error("❌ Failed to load Orpheus model - service may not work correctly")

    # Initialize database
    await init_db_pool()

    # Load default voice
    await load_voice_reference("default")

    # Connect to LiveKit
    asyncio.create_task(connect_livekit())

    logger.info("✅ Service ready")
    logger.info("=" * 80)
    logger.info("Orpheus TTS Optimizations Active:")
    logger.info(f"  ⚡ Model: {ORPHEUS_MODEL}")
    logger.info(f"  ⚡ GPU Memory Utilization: {VLLM_GPU_MEMORY_UTILIZATION}")
    logger.info(f"  ⚡ Max Model Length: {VLLM_MAX_MODEL_LEN}")
    logger.info(f"  ⚡ Quantization: {VLLM_QUANTIZATION}")
    logger.info(f"  ⚡ Streaming: Enabled")
    logger.info(f"  ⚡ Expected Latency: 100-200ms")
    logger.info("=" * 80)

@app.on_event("shutdown")
async def on_shutdown():
    if db_pool:
        await db_pool.close()
    executor.shutdown(wait=True)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/health")
async def health():
    gpu_memory_used = 0
    gpu_memory_total = 0
    if torch.cuda.is_available():
        gpu_memory_used = torch.cuda.memory_allocated() / 1024**3  # GB
        gpu_memory_total = torch.cuda.get_device_properties(0).total_memory / 1024**3  # GB

    return {
        "status": "ok" if orpheus_model is not None else "model_not_loaded",
        "mode": "orpheus_tts",
        "model": ORPHEUS_MODEL,
        "variant": ORPHEUS_VARIANT,
        "device": DEVICE,
        "sample_rate": ORPHEUS_SAMPLE_RATE,
        "streaming_enabled": True,
        "livekit_connected": livekit_connected,
        "db_connected": db_pool is not None,
        "current_voice": current_voice_id,
        "voices_cached": len(voice_cache),
        "optimizations": {
            "engine": "orpheus_vllm",
            "version": "8.0.0-orpheus",
            "expected_latency_ms": "100-200",
            "gpu_memory_utilization": VLLM_GPU_MEMORY_UTILIZATION,
            "max_model_len": VLLM_MAX_MODEL_LEN,
            "quantization": VLLM_QUANTIZATION,
            "streaming": True,
            "zero_shot_cloning": True
        },
        "gpu_memory": {
            "used_gb": round(gpu_memory_used, 2),
            "total_gb": round(gpu_memory_total, 2),
            "utilization_pct": round(gpu_memory_used / gpu_memory_total * 100, 1) if gpu_memory_total > 0 else 0
        }
    }

# -----------------------------------------------------------------------------
# Voice management
# -----------------------------------------------------------------------------
@app.post("/api/voices/clone")
async def clone_voice(voice_id: str = Form(...), voice_name: str = Form(...), file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(audio_bytes)
        try:
            audio, sr = sf.read(tmp_path)
            duration = len(audio) / sr
            if duration < 3:
                raise HTTPException(400, f"Audio too short ({duration:.1f}s). Minimum 3s for Orpheus.")
            if duration > 60:
                raise HTTPException(400, f"Audio too long ({duration:.1f}s). Maximum 60s.")
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass

        if db_pool:
            async with db_pool.acquire() as conn:
                exists = await conn.fetchval("SELECT COUNT(*) FROM tts_voices WHERE voice_id = $1", voice_id)
                if exists > 0:
                    raise HTTPException(409, f"Voice ID '{voice_id}' already exists")
                await conn.execute(
                    "INSERT INTO tts_voices (voice_id, name, audio_data) VALUES ($1, $2, $3)",
                    voice_id, voice_name, audio_bytes
                )
        else:
            raise HTTPException(503, "Database not available")

        return JSONResponse({
            "status": "success",
            "voice_id": voice_id,
            "voice_name": voice_name,
            "audio_duration_seconds": round(duration, 2)
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@app.get("/api/voices")
async def list_voices():
    if not db_pool:
        return {"total": 0, "voices": [], "current_voice": current_voice_id, "cached_voices": list(voice_cache.keys())}

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT voice_id, name, created_at FROM tts_voices ORDER BY created_at DESC")
    voices = [{"voice_id": r["voice_id"], "name": r["name"], "created_at": str(r["created_at"])} for r in rows]
    return {"total": len(voices), "voices": voices, "current_voice": current_voice_id, "cached_voices": list(voice_cache.keys())}

# -----------------------------------------------------------------------------
# TTS synthesis
# -----------------------------------------------------------------------------
@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    if orpheus_model is None:
        raise HTTPException(503, "Orpheus model not loaded")

    start_time = time.time()

    try:
        logger.info(f"🎙️ Synthesizing: '{request.text[:60]}...'")
        logger.info(f"   Voice: {request.voice_id}, Language: {request.language}")
        logger.info(f"   Params: temperature={request.temperature}, repetition_penalty={request.repetition_penalty}")

        # Load voice reference if different
        voice_path = None
        if request.voice_id != current_voice_id:
            voice_path = await load_voice_reference(request.voice_id)
        else:
            voice_path = current_reference_audio_path

        # Generate audio with Orpheus (returns raw PCM bytes)
        raw_audio_bytes = await generate_async(
            text=request.text,
            voice_path=voice_path,
            temperature=request.temperature,
            repetition_penalty=request.repetition_penalty
        )

        # Convert raw PCM to WAV format
        import wave
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(ORPHEUS_SAMPLE_RATE)  # 24kHz
            wf.writeframes(raw_audio_bytes)

        audio_bytes = buffer.getvalue()

        # Stream to LiveKit
        await stream_audio_to_livekit(audio_bytes)

        total_ms = (time.time() - start_time) * 1000
        # Calculate duration from raw PCM bytes (2 bytes per sample for 16-bit)
        audio_duration = len(raw_audio_bytes) / (2 * ORPHEUS_SAMPLE_RATE)
        rtf = (total_ms / 1000.0) / audio_duration if audio_duration > 0 else 0  # Real-time factor

        # GPU metrics
        gpu_memory_used = 0
        if torch.cuda.is_available():
            gpu_memory_used = torch.cuda.memory_allocated() / 1024**2  # MB

        logger.info(f"✅ Generated {audio_duration:.2f}s audio in {total_ms:.0f}ms (RTF: {rtf:.2f}x)")

        return JSONResponse({
            "status": "success",
            "mode": "orpheus_tts",
            "model": ORPHEUS_MODEL,
            "total_time_ms": round(total_ms, 2),
            "audio_duration_seconds": round(audio_duration, 2),
            "voice_id": request.voice_id,
            "language": request.language,
            "performance": {
                "real_time_factor": round(rtf, 3),
                "inference_speedup": round(1.0 / rtf, 2) if rtf > 0 else 0,
                "gpu_memory_used_mb": round(gpu_memory_used, 1),
                "optimizations_active": {
                    "orpheus_vllm": True,
                    "streaming_capable": True,
                    "quantization": VLLM_QUANTIZATION,
                    "gpu_memory_utilization": VLLM_GPU_MEMORY_UTILIZATION
                }
            }
        })
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}", exc_info=True)
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
