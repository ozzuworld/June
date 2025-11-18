#!/usr/bin/env python3
"""
June TTS Service - XTTS v2 (Coqui TTS)
Clean implementation with voice cloning and streaming support
"""
import asyncio
import io
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Tuple

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
logger = logging.getLogger("june-tts-xtts")

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# Accept Coqui TOS automatically (required for non-interactive Docker environment)
os.environ["COQUI_TOS_AGREED"] = "1"

LIVEKIT_IDENTITY = os.getenv("LIVEKIT_IDENTITY", "june-tts")
LIVEKIT_ROOM_NAME = os.getenv("LIVEKIT_ROOM", "ozzu-main")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "https://api.ozzu.world")

# XTTS v2 settings
XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
WARMUP_ON_STARTUP = os.getenv("WARMUP_ON_STARTUP", "0") == "1"
USE_DEEPSPEED = os.getenv("USE_DEEPSPEED", "0") == "1"

# PostgreSQL
DB_HOST = os.getenv("DB_HOST", "100.64.0.1")
DB_PORT = int(os.getenv("DB_PORT", "30432"))
DB_NAME = os.getenv("DB_NAME", "june")
DB_USER = os.getenv("DB_USER", "keycloak")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Pokemon123!")

# Audio settings
XTTS_SAMPLE_RATE = 24000  # XTTS native
LIVEKIT_SAMPLE_RATE = 48000
LIVEKIT_FRAME_SIZE = 960  # 20ms @ 48kHz
FRAME_PERIOD_S = 0.020

# XTTS v2 supported languages
SUPPORTED_LANGUAGES = [
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru",
    "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi"
]

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(
    title="June TTS (XTTS v2)",
    version="10.0.0-xtts",
    description="XTTS v2 implementation with voice cloning and streaming"
)

# -----------------------------------------------------------------------------
# Global state
# -----------------------------------------------------------------------------
tts_model = None
voice_cache: Dict[str, Tuple[torch.Tensor, torch.Tensor]] = {}  # voice_id -> (gpt_cond_latent, speaker_embedding)
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
    temperature: float = Field(default=0.65, ge=0.1, le=1.0)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    enable_text_splitting: bool = Field(default=True)

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
# XTTS v2 Model
# -----------------------------------------------------------------------------
async def ensure_default_speaker():
    """Ensure we have a default speaker reference for XTTS v2"""
    default_speaker_path = "/app/voices/default_speaker.wav"

    if os.path.exists(default_speaker_path):
        logger.info(f"✅ Default speaker already exists: {default_speaker_path}")
        return default_speaker_path

    logger.info("📥 Setting up default speaker from database...")

    try:
        # Try to load "default" voice from PostgreSQL database
        voice_audio = await get_voice_from_db("default")

        if voice_audio:
            # Save to default speaker path
            with open(default_speaker_path, 'wb') as f:
                f.write(voice_audio)
            logger.info(f"✅ Loaded 'default' voice from database as default speaker")
            return default_speaker_path
        else:
            logger.warning("⚠️  'default' voice not found in database")
            logger.info("📥 Downloading fallback default speaker from XTTS repository...")

            # Fallback: Download a sample speaker from XTTS repository
            import httpx
            sample_url = "https://github.com/coqui-ai/TTS/raw/dev/tests/data/ljspeech/wavs/LJ001-0001.wav"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(sample_url)
                if response.status_code == 200:
                    with open(default_speaker_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"✅ Downloaded fallback speaker to {default_speaker_path}")
                    return default_speaker_path
                else:
                    logger.error(f"Failed to download fallback speaker: HTTP {response.status_code}")
                    return None

    except Exception as e:
        logger.error(f"❌ Failed to setup default speaker: {e}")
        return None

async def load_model():
    """Load XTTS v2 model"""
    global tts_model

    logger.info("=" * 80)
    logger.info("🚀 Loading XTTS v2 Model (Coqui TTS)")
    logger.info(f"   Model: {XTTS_MODEL}")
    logger.info(f"   GPU: {torch.cuda.is_available()}")
    logger.info(f"   DeepSpeed: {USE_DEEPSPEED}")
    logger.info("=" * 80)

    try:
        from TTS.api import TTS

        # Ensure we have a default speaker reference
        default_speaker = await ensure_default_speaker()
        if not default_speaker:
            logger.warning("⚠️  No default speaker available - users must clone voices")

        # Initialize XTTS v2
        tts_model = TTS(XTTS_MODEL, gpu=torch.cuda.is_available())
        logger.info("✅ XTTS v2 model loaded")

        # Warmup
        if WARMUP_ON_STARTUP and default_speaker:
            logger.info("⏱️  Warming up...")
            warmup_output = tts_model.tts(
                text="Hello world.",
                speaker_wav=default_speaker,
                language="en"
            )
            logger.info(f"✅ Warmup complete")

        logger.info("✅ XTTS v2 ready")
        logger.info(f"🌍 Supported languages: {', '.join(SUPPORTED_LANGUAGES)}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to load model: {e}", exc_info=True)
        return False

async def get_voice_conditioning(voice_id: str) -> Optional[Tuple[torch.Tensor, torch.Tensor]]:
    """
    Get or create cached voice conditioning latents
    Returns (gpt_cond_latent, speaker_embedding) tuple
    """
    # Check cache first
    if voice_id in voice_cache:
        logger.info(f"✅ Using cached conditioning for voice '{voice_id}'")
        return voice_cache[voice_id]

    # Load voice audio from database
    voice_audio = await get_voice_from_db(voice_id)
    if not voice_audio:
        logger.warning(f"Voice '{voice_id}' not found in database")
        return None

    try:
        # Save to temporary file (XTTS needs file path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(voice_audio)
            tmp_path = tmp.name

        # Get conditioning latents using XTTS v2 model
        logger.info(f"🎙️ Computing conditioning latents for voice '{voice_id}'")

        # XTTS v2 uses the model's internal method
        from TTS.tts.models.xtts import Xtts
        if hasattr(tts_model, 'synthesizer') and hasattr(tts_model.synthesizer.tts_model, 'get_conditioning_latents'):
            gpt_cond_latent, speaker_embedding = tts_model.synthesizer.tts_model.get_conditioning_latents(
                audio_path=[tmp_path]
            )

            # Cache the conditioning
            voice_cache[voice_id] = (gpt_cond_latent, speaker_embedding)
            logger.info(f"✅ Cached conditioning for voice '{voice_id}'")

            # Clean up temp file
            os.unlink(tmp_path)

            return (gpt_cond_latent, speaker_embedding)
        else:
            # Fallback: return the file path for direct use
            logger.warning(f"Using fallback voice conditioning method")
            return tmp_path

    except Exception as e:
        logger.error(f"❌ Failed to get voice conditioning: {e}", exc_info=True)
        return None

def generate_audio(
    text: str,
    voice_id: str = "default",
    language: str = "en",
    temperature: float = 0.65,
    speed: float = 1.0,
    enable_text_splitting: bool = True
) -> bytes:
    """Generate audio using XTTS v2"""
    logger.info(f"🎙️ Generating: '{text[:60]}...' with voice='{voice_id}', language='{language}'")

    try:
        # Get voice reference - XTTS v2 requires a speaker for all synthesis
        speaker_wav = None
        cleanup_speaker_file = False

        if voice_id == "default":
            # Use default speaker downloaded during startup
            default_speaker_path = "/app/voices/default_speaker.wav"
            if os.path.exists(default_speaker_path):
                speaker_wav = default_speaker_path
                logger.info("Using default speaker")
            else:
                raise RuntimeError(
                    "Default speaker not available. Please clone a voice first using /api/voices/clone"
                )
        else:
            # Use custom voice from database
            voice_audio = asyncio.run(get_voice_from_db(voice_id))
            if voice_audio:
                # Save to temp file
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(voice_audio)
                    speaker_wav = tmp.name
                    cleanup_speaker_file = True
                logger.info(f"Using custom voice: {voice_id}")
            else:
                logger.warning(f"Voice '{voice_id}' not found, falling back to default")
                default_speaker_path = "/app/voices/default_speaker.wav"
                if os.path.exists(default_speaker_path):
                    speaker_wav = default_speaker_path
                else:
                    raise RuntimeError(f"Voice '{voice_id}' not found and no default speaker available")

        # Generate using XTTS v2
        wav = tts_model.tts(
            text=text,
            speaker_wav=speaker_wav,
            language=language
        )

        # Clean up temp file if it was created for custom voice
        if cleanup_speaker_file and os.path.exists(speaker_wav):
            os.unlink(speaker_wav)

        # Convert to bytes (WAV format)
        buffer = io.BytesIO()
        sf.write(buffer, wav, XTTS_SAMPLE_RATE, format='WAV')
        buffer.seek(0)

        logger.info(f"✅ Generated audio: {len(wav)} samples")
        return buffer.getvalue()

    except Exception as e:
        logger.error(f"❌ Audio generation failed: {e}", exc_info=True)
        raise

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
        track = rtc.LocalAudioTrack.create_audio_track("xtts-audio", source)
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
    logger.info("🚀 XTTS v2 TTS Service Starting")

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
        "status": "ok" if tts_model is not None else "model_not_loaded",
        "model": XTTS_MODEL,
        "model_type": "xtts_v2",
        "supported_languages": SUPPORTED_LANGUAGES,
        "livekit_connected": livekit_connected,
        "db_connected": db_pool is not None,
        "cached_voices": len(voice_cache),
        "gpu_memory": {
            "used_gb": round(gpu_memory_used, 2),
            "total_gb": round(gpu_memory_total, 2),
        }
    }

@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    if tts_model is None:
        raise HTTPException(503, "Model not loaded")

    # Validate language
    if request.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"Language '{request.language}' not supported. Supported: {SUPPORTED_LANGUAGES}")

    start_time = time.time()

    try:
        # Generate audio using XTTS v2
        audio_bytes = await asyncio.get_event_loop().run_in_executor(
            None,
            generate_audio,
            request.text,
            request.voice_id,
            request.language,
            request.temperature,
            request.speed,
            request.enable_text_splitting
        )

        # Stream to LiveKit
        await stream_audio_to_livekit(audio_bytes)

        total_ms = (time.time() - start_time) * 1000

        logger.info(f"✅ Synthesis complete in {total_ms:.0f}ms")

        return JSONResponse({
            "status": "success",
            "model": XTTS_MODEL,
            "model_type": "xtts_v2",
            "total_time_ms": round(total_ms, 2),
            "voice": request.voice_id,
            "language": request.language
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

        # Clear cache for this voice if it exists
        if voice_id in voice_cache:
            del voice_cache[voice_id]

        return JSONResponse({
            "status": "success",
            "voice_id": voice_id,
            "voice_name": voice_name,
            "message": "Voice cloned successfully. XTTS v2 will use this for synthesis."
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

@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: str):
    if not db_pool:
        raise HTTPException(503, "Database not available")

    async with db_pool.acquire() as conn:
        result = await conn.execute("DELETE FROM tts_voices WHERE voice_id = $1", voice_id)

    # Clear from cache
    if voice_id in voice_cache:
        del voice_cache[voice_id]

    if result == "DELETE 0":
        raise HTTPException(404, f"Voice '{voice_id}' not found")

    return JSONResponse({
        "status": "success",
        "message": f"Voice '{voice_id}' deleted"
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
