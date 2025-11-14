#!/usr/bin/env python3
"""
June TTS Service - Fish Speech HTTP API Wrapper
Simplified version that uses Fish Speech's built-in API server
"""
import asyncio
import logging
import os
import time
import tempfile
import io
from typing import Optional
from pathlib import Path

import numpy as np
import torch
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from livekit import rtc
import soundfile as sf
import asyncpg

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("june-tts-fish-speech")

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
LIVEKIT_IDENTITY = os.getenv("LIVEKIT_IDENTITY", "june-tts")
LIVEKIT_ROOM_NAME = os.getenv("LIVEKIT_ROOM", "ozzu-main")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "https://api.ozzu.world")

# Fish Speech API (running locally)
FISH_SPEECH_API = "http://127.0.0.1:9880"

# PostgreSQL
DB_HOST = os.getenv("DB_HOST", "100.64.0.1")
DB_PORT = int(os.getenv("DB_PORT", "30432"))
DB_NAME = os.getenv("DB_NAME", "june")
DB_USER = os.getenv("DB_USER", "keycloak")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Pokemon123!")

# Audio settings
FISH_SPEECH_SAMPLE_RATE = 44100
LIVEKIT_SAMPLE_RATE = 48000
LIVEKIT_FRAME_SIZE = 960  # 20ms @ 48kHz
FRAME_PERIOD_S = 0.020

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(
    title="June TTS (Fish Speech API Wrapper)",
    version="5.0.0",
    description="Fish Speech TTS with LiveKit streaming"
)

# -----------------------------------------------------------------------------
# Global state
# -----------------------------------------------------------------------------
livekit_room = None
livekit_audio_source = None
livekit_connected = False

db_pool = None

current_voice_id: Optional[str] = None
current_reference_audio: Optional[bytes] = None

_gpu_resampler = None

# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    room_name: str = Field(..., description="LiveKit room name")
    language: str = Field(default="en")
    voice_id: str = Field(default="default")
    temperature: float = Field(default=0.7, ge=0.1, le=1.0)
    top_p: float = Field(default=0.7, ge=0.1, le=1.0)
    repetition_penalty: float = Field(default=1.2, ge=1.0, le=2.0)

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
async def init_db_pool():
    global db_pool
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

async def get_voice_from_db(voice_id: str) -> Optional[bytes]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT audio_data FROM tts_voices WHERE voice_id = $1", voice_id
        )
    if row:
        logger.info(f"✅ Loaded voice '{voice_id}' from DB")
        return bytes(row["audio_data"])
    logger.warning(f"⚠️ Voice '{voice_id}' not found in DB")
    return None

async def load_voice_reference(voice_id: str = "default"):
    global current_voice_id, current_reference_audio

    if voice_id == current_voice_id and current_reference_audio is not None:
        return True

    logger.info(f"📁 Loading voice reference '{voice_id}'...")
    audio_bytes = await get_voice_from_db(voice_id)

    if audio_bytes:
        current_reference_audio = audio_bytes
        current_voice_id = voice_id
        logger.info(f"✅ Voice '{voice_id}' loaded")
        return True
    else:
        default_ref = Path("/app/references/June.wav")
        if default_ref.exists():
            with open(default_ref, 'rb') as f:
                current_reference_audio = f.read()
            current_voice_id = voice_id
            logger.info(f"✅ Using default reference audio")
            return True
        else:
            logger.warning(f"⚠️ No reference audio for '{voice_id}'")
            current_reference_audio = None
            return False

# -----------------------------------------------------------------------------
# Fish Speech API Client
# -----------------------------------------------------------------------------
async def synthesize_with_fish_speech_api(
    text: str,
    reference_audio: Optional[bytes] = None,
) -> bytes:
    """Call Fish Speech HTTP API for synthesis"""

    # Save reference audio to temp file if provided
    reference_path = None
    if reference_audio:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            reference_path = tmp.name
            tmp.write(reference_audio)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Prepare request
            files = {}
            if reference_path:
                with open(reference_path, 'rb') as f:
                    files['reference_audio'] = f.read()

            data = {
                'text': text,
                'streaming': 'false'  # Get full audio at once
            }

            # Call Fish Speech API
            response = await client.post(
                f"{FISH_SPEECH_API}/v1/tts",
                files=files if files else None,
                data=data
            )

            if response.status_code == 200:
                return response.content
            else:
                raise RuntimeError(f"Fish Speech API error: {response.status_code}")

    finally:
        if reference_path and os.path.exists(reference_path):
            try:
                os.unlink(reference_path)
            except:
                pass

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
        track = rtc.LocalAudioTrack.create_audio_track("fish-speech-audio", source)
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
    if _gpu_resampler is None:
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

    logger.info(f"✅ Streamed {frames_sent} frames")

# -----------------------------------------------------------------------------
# Lifecycle
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    logger.info("=" * 80)
    logger.info("🚀 Fish Speech TTS Service (API Wrapper)")
    logger.info("=" * 80)

    # Wait for Fish Speech API to be ready
    for i in range(30):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{FISH_SPEECH_API}/health", timeout=2.0)
                if response.status_code == 200:
                    logger.info("✅ Fish Speech API is ready")
                    break
        except:
            if i == 29:
                logger.error("❌ Fish Speech API not available")
                return
            await asyncio.sleep(1)

    await init_db_pool()
    await load_voice_reference("default")
    asyncio.create_task(connect_livekit())
    logger.info("✅ Service ready")

@app.on_event("shutdown")
async def on_shutdown():
    if db_pool:
        await db_pool.close()

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "fish_speech_api_wrapper",
        "livekit_connected": livekit_connected,
        "db_connected": db_pool is not None,
        "current_voice": current_voice_id
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
                raise HTTPException(400, f"Audio too short ({duration:.1f}s). Minimum 3s.")
            if duration > 60:
                raise HTTPException(400, f"Audio too long ({duration:.1f}s). Maximum 60s.")
        finally:
            try:
                os.unlink(tmp_path)
            except:
                pass

        async with db_pool.acquire() as conn:
            exists = await conn.fetchval("SELECT COUNT(*) FROM tts_voices WHERE voice_id = $1", voice_id)
            if exists > 0:
                raise HTTPException(409, f"Voice ID '{voice_id}' already exists")
            await conn.execute(
                "INSERT INTO tts_voices (voice_id, name, audio_data) VALUES ($1, $2, $3)",
                voice_id, voice_name, audio_bytes
            )

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
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT voice_id, name, created_at FROM tts_voices ORDER BY created_at DESC")
    voices = [{"voice_id": r["voice_id"], "name": r["name"], "created_at": str(r["created_at"])} for r in rows]
    return {"total": len(voices), "voices": voices, "current_voice": current_voice_id}

# -----------------------------------------------------------------------------
# TTS synthesis
# -----------------------------------------------------------------------------
@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    global current_voice_id, current_reference_audio

    start_time = time.time()

    if request.voice_id != current_voice_id:
        await load_voice_reference(request.voice_id)

    logger.info(f"🎙️ Synthesizing: '{request.text[:60]}...'")

    try:
        # Call Fish Speech API
        audio_data = await synthesize_with_fish_speech_api(
            text=request.text,
            reference_audio=current_reference_audio
        )

        # Stream to LiveKit
        await stream_audio_to_livekit(audio_data)

        total_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Completed in {total_ms:.0f}ms")

        return JSONResponse({
            "status": "success",
            "mode": "fish_speech",
            "total_time_ms": round(total_ms, 2),
            "voice_id": request.voice_id
        })
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}", exc_info=True)
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
