#!/usr/bin/env python3
"""
June TTS Service - Orpheus TTS (Clean Implementation)
Based on official Orpheus-TTS examples
"""
import asyncio
import io
import logging
import os
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
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

# Orpheus settings
ORPHEUS_MODEL = os.getenv("ORPHEUS_MODEL", "canopylabs/orpheus-3b-0.1-ft")
MAX_MODEL_LEN = int(os.getenv("MAX_MODEL_LEN", "2048"))
WARMUP_ON_STARTUP = os.getenv("WARMUP_ON_STARTUP", "0") == "1"

# PostgreSQL
DB_HOST = os.getenv("DB_HOST", "100.64.0.1")
DB_PORT = int(os.getenv("DB_PORT", "30432"))
DB_NAME = os.getenv("DB_NAME", "june")
DB_USER = os.getenv("DB_USER", "keycloak")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Pokemon123!")

# Audio settings
ORPHEUS_SAMPLE_RATE = 24000  # Orpheus native
LIVEKIT_SAMPLE_RATE = 48000
LIVEKIT_FRAME_SIZE = 960  # 20ms @ 48kHz
FRAME_PERIOD_S = 0.020

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(
    title="June TTS (Orpheus)",
    version="9.0.0-clean",
    description="Clean Orpheus TTS implementation"
)

# -----------------------------------------------------------------------------
# Global state
# -----------------------------------------------------------------------------
orpheus_model = None
voice_cache = {}
livekit_room = None
livekit_audio_source = None
livekit_connected = False
db_pool = None

# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    room_name: str = Field(..., description="LiveKit room name")
    voice_id: str = Field(default="default")
    language: str = Field(default="en")
    temperature: float = Field(default=0.7, ge=0.1, le=2.0)
    repetition_penalty: float = Field(default=1.1, ge=1.0, le=2.0)

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
    return None

# -----------------------------------------------------------------------------
# Orpheus Model - OFFICIAL IMPLEMENTATION
# -----------------------------------------------------------------------------
async def load_model():
    """Load Orpheus TTS model - Official implementation"""
    global orpheus_model

    logger.info("=" * 80)
    logger.info("🚀 Loading Orpheus TTS Model (Official Implementation)")
    logger.info(f"   Model: {ORPHEUS_MODEL}")
    logger.info(f"   Max Model Length: {MAX_MODEL_LEN}")
    logger.info("=" * 80)

    try:
        from orpheus_tts import OrpheusModel

        # OFFICIAL: OrpheusModel accepts model_name and max_model_len directly
        orpheus_model = OrpheusModel(
            model_name=ORPHEUS_MODEL,
            max_model_len=MAX_MODEL_LEN
        )
        logger.info("✅ Orpheus model loaded")

        # Warmup
        if WARMUP_ON_STARTUP:
            logger.info("⏱️  Warming up...")
            warmup_chunks = list(orpheus_model.generate_speech(
                prompt="Hello world.",
                voice="zoe"
            ))
            logger.info(f"✅ Warmup complete - {len(warmup_chunks)} chunks")

        logger.info("✅ Orpheus TTS ready")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to load model: {e}", exc_info=True)
        return False

def generate_audio(text: str, voice: str = "zoe") -> bytes:
    """Generate audio using official Orpheus method"""
    logger.info(f"🎙️ Generating: '{text[:60]}...' with voice='{voice}'")

    # OFFICIAL: Use generate_speech() - returns iterator of audio chunks
    syn_tokens = orpheus_model.generate_speech(
        prompt=text,
        voice=voice  # Preset voice name
    )

    # OFFICIAL: Collect chunks and save to WAV
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wf:
        wf.setnchannels(1)  # Mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(ORPHEUS_SAMPLE_RATE)  # 24kHz

        chunk_count = 0
        for audio_chunk in syn_tokens:
            chunk_count += 1
            logger.info(f"   Chunk {chunk_count}: {len(audio_chunk)} bytes")
            wf.writeframes(audio_chunk)

    logger.info(f"✅ Generated {chunk_count} chunks")
    return buffer.getvalue()

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
        logger.info(f"✅ LiveKit connected")
        return True
    except Exception as e:
        logger.error(f"❌ LiveKit connection failed: {e}")
        return False

async def stream_audio_to_livekit(audio_data: bytes):
    """Stream audio to LiveKit"""
    if not livekit_connected or livekit_audio_source is None:
        logger.warning("LiveKit not connected")
        return

    # Load audio
    audio, sr = sf.read(io.BytesIO(audio_data))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Resample if needed
    if sr != LIVEKIT_SAMPLE_RATE:
        import torchaudio.transforms as T
        resampler = T.Resample(sr, LIVEKIT_SAMPLE_RATE)
        t = torch.from_numpy(audio).float().unsqueeze(0)
        audio = resampler(t).squeeze().numpy()

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
    logger.info("🚀 Orpheus TTS Service Starting (Clean Implementation)")

    # Load model
    success = await load_model()
    if not success:
        logger.error("❌ Failed to load model")

    # Initialize database
    await init_db_pool()

    # Connect to LiveKit
    asyncio.create_task(connect_livekit())

    logger.info("✅ Service ready")

@app.on_event("shutdown")
async def on_shutdown():
    if db_pool:
        await db_pool.close()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------
@app.get("/health")
async def health():
    gpu_memory_used = 0
    gpu_memory_total = 0
    if torch.cuda.is_available():
        gpu_memory_used = torch.cuda.memory_allocated() / 1024**3
        gpu_memory_total = torch.cuda.get_device_properties(0).total_memory / 1024**3

    return {
        "status": "ok" if orpheus_model is not None else "model_not_loaded",
        "model": ORPHEUS_MODEL,
        "livekit_connected": livekit_connected,
        "db_connected": db_pool is not None,
        "gpu_memory": {
            "used_gb": round(gpu_memory_used, 2),
            "total_gb": round(gpu_memory_total, 2),
        }
    }

@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    if orpheus_model is None:
        raise HTTPException(503, "Model not loaded")

    start_time = time.time()

    try:
        # Map voice_id to Orpheus preset voices
        # Default to "zoe" for simplicity
        voice = "zoe"
        if request.voice_id in ["tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe"]:
            voice = request.voice_id

        # Generate audio using official method
        audio_bytes = await asyncio.get_event_loop().run_in_executor(
            None,
            generate_audio,
            request.text,
            voice
        )

        # Stream to LiveKit
        await stream_audio_to_livekit(audio_bytes)

        total_ms = (time.time() - start_time) * 1000

        logger.info(f"✅ Synthesis complete in {total_ms:.0f}ms")

        return JSONResponse({
            "status": "success",
            "model": ORPHEUS_MODEL,
            "total_time_ms": round(total_ms, 2),
            "voice": voice
        })

    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@app.post("/api/voices/clone")
async def clone_voice(voice_id: str = Form(...), voice_name: str = Form(...), file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()

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
            "voice_name": voice_name
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@app.get("/api/voices")
async def list_voices():
    if not db_pool:
        return {"total": 0, "voices": []}

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT voice_id, name, created_at FROM tts_voices ORDER BY created_at DESC")
    voices = [{"voice_id": r["voice_id"], "name": r["name"], "created_at": str(r["created_at"])} for r in rows]
    return {"total": len(voices), "voices": voices}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
