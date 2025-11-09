#!/usr/bin/env python3
"""
June TTS Service - XTTS v2 with PostgreSQL Voice Storage
Fetches reference audio from PostgreSQL database
"""
import asyncio
import logging
import os
import time
import tempfile
import hashlib
import io

import numpy as np
import torch
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from livekit import rtc
import soundfile as sf
import asyncpg

# COMPREHENSIVE PATCH: Add all TTS classes to PyTorch 2.6 safe globals
if hasattr(torch.serialization, 'add_safe_globals'):
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.configs.shared_configs import BaseDatasetConfig
    from TTS.tts.models.xtts import XttsArgs, XttsAudioConfig
    from TTS.config.shared_configs import BaseAudioConfig
    
    torch.serialization.add_safe_globals([
        XttsConfig,
        BaseDatasetConfig,
        XttsArgs,
        XttsAudioConfig,
        BaseAudioConfig
    ])

from TTS.api import TTS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
LIVEKIT_IDENTITY = os.getenv("LIVEKIT_IDENTITY", "june-tts")
LIVEKIT_ROOM_NAME = os.getenv("LIVEKIT_ROOM", "ozzu-main")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "https://api.ozzu.world")

# PostgreSQL Configuration
DB_HOST = os.getenv("DB_HOST", "100.64.0.1")
DB_PORT = int(os.getenv("DB_PORT", "30432"))
DB_NAME = os.getenv("DB_NAME", "june")
DB_USER = os.getenv("DB_USER", "keycloak")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Pokemon123!")

# PRODUCTION OPTIMIZED SETTINGS
STREAM_CHUNK_SIZE = 150
LIVEKIT_FRAME_SIZE = 960

app = FastAPI(
    title="June TTS (XTTS v2) - PostgreSQL Voice",
    version="2.4.0",
    description="Real-time streaming TTS with PostgreSQL voice storage and voice cloning"
)

# Global state
xtts_model = None
tts_api = None
gpt_cond_latent = None
speaker_embedding = None
livekit_room = None
livekit_audio_source = None
livekit_connected = False
db_pool = None

# Speaker diagnostics
speaker_embedding_hash = None
gpt_cond_hash = None
current_voice_id = None

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    room_name: str = Field(...)
    language: str = Field(default="en")
    voice_id: str = Field(default="default")

def compute_tensor_hash(tensor):
    """Compute hash of tensor to track if it changes"""
    if tensor is None:
        return "None"
    if torch.is_tensor(tensor):
        tensor_np = tensor.cpu().detach().numpy()
    else:
        tensor_np = np.array(tensor)
    return hashlib.md5(tensor_np.tobytes()).hexdigest()[:8]

def load_audio_with_soundfile(audio_path: str, sampling_rate: int = None):
    """Load audio using soundfile and return as 2D torch tensor"""
    audio, sr = sf.read(audio_path)
    
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32767.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483647.0
    else:
        audio = audio.astype(np.float32)
    
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    
    audio_tensor = torch.FloatTensor(audio)
    
    if sampling_rate is not None and sr != sampling_rate:
        import torchaudio.transforms as T
        resampler = T.Resample(sr, sampling_rate)
        audio_tensor = resampler(audio_tensor)
    
    audio_tensor = audio_tensor.unsqueeze(0)
    return audio_tensor

def load_audio_from_bytes(audio_bytes: bytes, sampling_rate: int = None):
    """Load audio from bytes and return as 2D torch tensor"""
    audio, sr = sf.read(io.BytesIO(audio_bytes))
    
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32767.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483647.0
    else:
        audio = audio.astype(np.float32)
    
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    
    audio_tensor = torch.FloatTensor(audio)
    
    if sampling_rate is not None and sr != sampling_rate:
        import torchaudio.transforms as T
        resampler = T.Resample(sr, sampling_rate)
        audio_tensor = resampler(audio_tensor)
    
    audio_tensor = audio_tensor.unsqueeze(0)
    return audio_tensor

# Monkey-patch load_audio
import TTS.tts.models.xtts as xtts_module
original_load_audio = xtts_module.load_audio

def patched_load_audio(audiopath, sampling_rate=None):
    try:
        return load_audio_with_soundfile(audiopath, sampling_rate)
    except Exception as e:
        logger.warning(f"Soundfile load failed: {e}")
        return original_load_audio(audiopath, sampling_rate)

xtts_module.load_audio = patched_load_audio

async def init_db_pool():
    """Initialize PostgreSQL connection pool"""
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            min_size=2,
            max_size=10
        )
        logger.info("✅ PostgreSQL connection pool created")
        
        # Create voices table if not exists
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
        logger.error(f"❌ Failed to initialize database: {e}")
        raise

async def get_voice_from_db(voice_id: str) -> bytes:
    """Fetch voice audio from PostgreSQL"""
    global db_pool
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT audio_data FROM tts_voices WHERE voice_id = $1",
                voice_id
            )
            if row:
                logger.info(f"✅ Loaded voice '{voice_id}' from database ({len(row['audio_data'])} bytes)")
                return bytes(row['audio_data'])
            else:
                logger.warning(f"⚠️ Voice '{voice_id}' not found in database")
                return None
    except Exception as e:
        logger.error(f"❌ Failed to fetch voice from database: {e}")
        return None

async def load_voice_embeddings(voice_id: str = "default"):
    """Load voice embeddings from PostgreSQL or use default"""
    global gpt_cond_latent, speaker_embedding, speaker_embedding_hash, gpt_cond_hash, current_voice_id
    
    if voice_id == current_voice_id and gpt_cond_latent is not None:
        logger.info(f"✅ Voice '{voice_id}' already loaded, skipping")
        return True
    
    logger.info(f"📁 Loading voice '{voice_id}'...")
    
    # Try to fetch from database
    audio_bytes = await get_voice_from_db(voice_id)
    
    if audio_bytes:
        # Save to temp file for XTTS
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(audio_bytes)
        
        try:
            gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                audio_path=[tmp_path]
            )
            logger.info(f"✅ Voice '{voice_id}' embeddings generated")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    else:
        # Fallback to default silent voice
        logger.info("⚠️ Using default silent voice")
        sample_rate = 22050
        duration = 2.0
        silence = np.zeros(int(sample_rate * duration), dtype=np.float32)
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            sf.write(tmp_path, silence, sample_rate)
        
        try:
            gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                audio_path=[tmp_path]
            )
            logger.info("✅ Default embeddings generated")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    # Move to GPU if available
    if torch.cuda.is_available():
        gpt_cond_latent = gpt_cond_latent.cuda()
        speaker_embedding = speaker_embedding.cuda()
    
    # Update hashes
    speaker_embedding_hash = compute_tensor_hash(speaker_embedding)
    gpt_cond_hash = compute_tensor_hash(gpt_cond_latent)
    current_voice_id = voice_id
    
    logger.info(f"🔑 Voice '{voice_id}' loaded: GPT={gpt_cond_hash}, Speaker={speaker_embedding_hash}")
    return True

async def warmup_model():
    """Warm up the model with dummy inferences for multiple languages to eliminate cold starts"""
    global xtts_model, gpt_cond_latent, speaker_embedding
    
    # Languages to warm up - prioritize most commonly used ones
    # Add or remove languages based on your usage patterns
    warmup_languages = [
        ("en", "Initializing speech synthesis."),
        ("ja", "音声合成を初期化しています。"),
        ("es", "Inicializando síntesis de voz."),
        ("fr", "Initialisation de la synthèse vocale."),
        ("de", "Sprachsynthese wird initialisiert."),
        ("zh-cn", "正在初始化语音合成。"),
    ]
    
    try:
        overall_start = time.time()
        successful_warmups = 0
        
        for lang_code, warmup_text in warmup_languages:
            try:
                lang_start = time.time()
                
                # Run dummy inference for this language
                _ = list(xtts_model.inference_stream(
                    text=warmup_text,
                    language=lang_code,
                    gpt_cond_latent=gpt_cond_latent,
                    speaker_embedding=speaker_embedding,
                    stream_chunk_size=20,
                    enable_text_splitting=False
                ))
                
                lang_time = (time.time() - lang_start) * 1000
                logger.info(f"✅ Warmed up {lang_code}: {lang_time:.0f}ms")
                successful_warmups += 1
                
            except Exception as e:
                logger.warning(f"⚠️ Warmup failed for {lang_code}: {e}")
        
        total_time = (time.time() - overall_start) * 1000
        logger.info(f"✅ Multi-language warmup completed: {successful_warmups}/{len(warmup_languages)} languages in {total_time:.0f}ms")
        
    except Exception as e:
        logger.warning(f"⚠️ Warmup failed (non-critical): {e}")

async def load_xtts_model():
    """Load XTTS v2 model"""
    global xtts_model, tts_api
    
    try:
        logger.info("🔊 Loading XTTS v2 model...")
        tts_api = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=torch.cuda.is_available())
        xtts_model = tts_api.synthesizer.tts_model
        
        if torch.cuda.is_available():
            xtts_model.cuda()
            logger.info("✅ XTTS v2 loaded on GPU")
        else:
            logger.warning("⚠️ XTTS v2 loaded on CPU")
        
        # Load default voice
        await load_voice_embeddings("default")
        
        # Warm up model for multiple languages to eliminate first-request latency
        logger.info("🔥 Warming up XTTS model for multiple languages...")
        await warmup_model()
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed to load XTTS v2: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

async def get_livekit_token(identity: str, room_name: str) -> tuple[str, str]:
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
            raise RuntimeError(f"Missing livekitUrl: {data}")
        return ws_url, token

async def connect_livekit():
    global livekit_room, livekit_audio_source, livekit_connected
    try:
        ws_url, token = await get_livekit_token(LIVEKIT_IDENTITY, LIVEKIT_ROOM_NAME)
        room = rtc.Room()
        await room.connect(ws_url, token)
        source = rtc.AudioSource(16000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("xtts-audio", source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        await room.local_participant.publish_track(track, options)
        livekit_room = room
        livekit_audio_source = source
        livekit_connected = True
        logger.info(f"✅ LiveKit connected as {LIVEKIT_IDENTITY}")
        return True
    except Exception as e:
        logger.error(f"❌ LiveKit connection failed: {e}")
        return False

async def stream_audio_to_livekit(audio_chunk_generator, sample_rate: int = 24000):
    """Stream audio to LiveKit"""
    global livekit_audio_source, livekit_connected
    
    if not livekit_connected or livekit_audio_source is None:
        logger.warning("LiveKit not connected")
        return
    
    start_time = time.time()
    first_chunk_time = None
    chunk_count = 0
    
    try:
        for chunk in audio_chunk_generator:
            current_time = time.time()
            
            if first_chunk_time is None:
                first_chunk_time = current_time
                logger.info(f"⚡ First chunk: {(first_chunk_time - start_time) * 1000:.0f}ms")
            
            chunk_count += 1
            
            if torch.is_tensor(chunk):
                chunk = chunk.cpu().numpy()
            
            if len(chunk.shape) > 1:
                chunk = chunk.squeeze()
            
            if sample_rate != 16000:
                from scipy.signal import resample_poly
                chunk = resample_poly(chunk, 16000, sample_rate)
            
            for offset in range(0, len(chunk), LIVEKIT_FRAME_SIZE):
                frame_data = chunk[offset:offset+LIVEKIT_FRAME_SIZE]
                if len(frame_data) < LIVEKIT_FRAME_SIZE:
                    frame_data = np.pad(frame_data, (0, LIVEKIT_FRAME_SIZE-len(frame_data)), 'constant')
                
                pcm_int16 = (np.clip(frame_data, -1, 1) * 32767).astype(np.int16)
                frame = rtc.AudioFrame.create(16000, 1, LIVEKIT_FRAME_SIZE)
                np.copyto(np.frombuffer(frame.data, dtype=np.int16), pcm_int16)
                await livekit_audio_source.capture_frame(frame)
        
        logger.info(f"✅ Streamed {chunk_count} chunks")
        
    except Exception as e:
        logger.error(f"❌ Error streaming: {e}")
        import traceback
        logger.error(traceback.format_exc())

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Starting XTTS v2 TTS Service (PostgreSQL Voice Storage)")
    logger.info(f"📊 Settings: chunk_size={STREAM_CHUNK_SIZE}, frame_size={LIVEKIT_FRAME_SIZE}")
    
    await init_db_pool()
    
    model_loaded = await load_xtts_model()
    if not model_loaded:
        logger.error("Failed to load XTTS model")
        return
    
    asyncio.create_task(connect_livekit())
    logger.info("✅ Service ready")

@app.on_event("shutdown")
async def on_shutdown():
    if db_pool:
        await db_pool.close()
        logger.info("✅ Database pool closed")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": xtts_model is not None,
        "livekit_connected": livekit_connected,
        "gpu_available": torch.cuda.is_available(),
        "db_connected": db_pool is not None,
        "current_voice": current_voice_id
    }

# ============================================================================
# VOICE MANAGEMENT ENDPOINTS
# ============================================================================

@app.post("/api/voices/clone")
async def clone_voice(
    voice_id: str = Form(...),
    voice_name: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Clone a voice from uploaded audio and store it in the database
    
    Requirements:
    - Audio: 6-30 seconds recommended (3-60s accepted)
    - Format: WAV, MP3, or FLAC
    - Sample rate: 22kHz minimum recommended
    - Quality: Clean speech, no background noise
    
    Returns voice_id and embedding information
    """
    global db_pool, xtts_model
    
    try:
        # Validate file type
        if not file.filename.endswith(('.wav', '.mp3', '.flac')):
            raise HTTPException(
                status_code=400,
                detail="Only WAV, MP3, and FLAC audio files are supported"
            )
        
        # Read audio file
        audio_bytes = await file.read()
        
        # Validate audio duration
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(audio_bytes)
        
        try:
            # Load audio to check duration
            audio, sr = sf.read(tmp_path)
            duration = len(audio) / sr
            
            logger.info(f"Audio duration: {duration:.2f}s, sample rate: {sr}Hz")
            
            # Validate duration
            if duration < 3:
                raise HTTPException(
                    status_code=400,
                    detail=f"Audio too short ({duration:.1f}s). Minimum 3 seconds required."
                )
            
            if duration > 60:
                raise HTTPException(
                    status_code=400,
                    detail=f"Audio too long ({duration:.1f}s). Maximum 60 seconds allowed."
                )
            
            # Warn if not optimal
            if duration < 6:
                logger.warning(f"Audio duration {duration:.1f}s is below optimal (6-10s recommended)")
            elif duration > 30:
                logger.warning(f"Audio duration {duration:.1f}s is above optimal (6-10s recommended)")
            
            # Generate embeddings
            logger.info(f"Generating embeddings for voice '{voice_id}'...")
            gpt_cond, speaker_emb = xtts_model.get_conditioning_latents(
                audio_path=[tmp_path]
            )
            
            # Compute hashes for verification
            gpt_hash = compute_tensor_hash(gpt_cond)
            speaker_hash = compute_tensor_hash(speaker_emb)
            
            logger.info(f"Embeddings generated: GPT={gpt_hash}, Speaker={speaker_hash}")
            
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        
        # Store in database
        async with db_pool.acquire() as conn:
            # Check if voice_id already exists
            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM tts_voices WHERE voice_id = $1",
                voice_id
            )
            
            if existing > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"Voice ID '{voice_id}' already exists. Use a different ID or delete the existing one first."
                )
            
            # Insert new voice
            await conn.execute("""
                INSERT INTO tts_voices (voice_id, name, audio_data, created_at, updated_at)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, voice_id, voice_name, audio_bytes)
        
        logger.info(f"✅ Voice '{voice_id}' cloned and saved ({len(audio_bytes)} bytes)")
        
        return JSONResponse({
            "status": "success",
            "voice_id": voice_id,
            "voice_name": voice_name,
            "audio_duration_seconds": round(duration, 2),
            "audio_size_bytes": len(audio_bytes),
            "audio_size_kb": round(len(audio_bytes) / 1024, 2),
            "sample_rate": sr,
            "embeddings": {
                "gpt_hash": gpt_hash,
                "speaker_hash": speaker_hash
            },
            "quality_notes": {
                "duration_optimal": 6 <= duration <= 10,
                "duration_acceptable": 3 <= duration <= 60
            },
            "message": f"Voice '{voice_id}' cloned successfully. You can now use this voice_id for synthesis."
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/voices/upload")
async def upload_voice(voice_id: str, file: UploadFile = File(...)):
    """
    Upload a voice audio file to PostgreSQL (legacy endpoint)
    Use /api/voices/clone for better validation and feedback
    """
    global db_pool
    
    try:
        audio_bytes = await file.read()
        
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO tts_voices (voice_id, name, audio_data)
                VALUES ($1, $2, $3)
                ON CONFLICT (voice_id) DO UPDATE
                SET audio_data = $3, updated_at = CURRENT_TIMESTAMP
            """, voice_id, voice_id, audio_bytes)
        
        logger.info(f"✅ Voice '{voice_id}' uploaded ({len(audio_bytes)} bytes)")
        return {"status": "success", "voice_id": voice_id, "size": len(audio_bytes)}
        
    except Exception as e:
        logger.error(f"❌ Failed to upload voice: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/voices")
async def list_voices():
    """List all available voices in the database"""
    global db_pool
    
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT voice_id, name, 
                       length(audio_data) as size_bytes,
                       created_at, updated_at 
                FROM tts_voices
                ORDER BY created_at DESC
            """)
            
            voices = [{
                "voice_id": row['voice_id'],
                "name": row['name'],
                "size_bytes": row['size_bytes'],
                "size_kb": round(row['size_bytes'] / 1024, 2),
                "created_at": str(row['created_at']),
                "updated_at": str(row['updated_at'])
            } for row in rows]
        
        return {
            "total": len(voices),
            "voices": voices
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to list voices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/voices/{voice_id}")
async def get_voice_info(voice_id: str):
    """Get detailed information about a specific voice"""
    global db_pool
    
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT voice_id, name, 
                       length(audio_data) as size_bytes,
                       created_at, updated_at
                FROM tts_voices 
                WHERE voice_id = $1
            """, voice_id)
            
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"Voice '{voice_id}' not found"
                )
        
        return {
            "voice_id": row['voice_id'],
            "name": row['name'],
            "size_bytes": row['size_bytes'],
            "size_kb": round(row['size_bytes'] / 1024, 2),
            "size_mb": round(row['size_bytes'] / (1024 * 1024), 2),
            "created_at": str(row['created_at']),
            "updated_at": str(row['updated_at']),
            "is_loaded": voice_id == current_voice_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get voice info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Delete a voice from the database"""
    global db_pool, current_voice_id
    
    try:
        # Prevent deleting currently loaded voice
        if voice_id == current_voice_id:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete currently loaded voice '{voice_id}'. Load a different voice first."
            )
        
        async with db_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM tts_voices WHERE voice_id = $1",
                voice_id
            )
            
            if result == "DELETE 0":
                raise HTTPException(
                    status_code=404,
                    detail=f"Voice '{voice_id}' not found"
                )
        
        logger.info(f"✅ Voice '{voice_id}' deleted")
        return {
            "status": "success",
            "message": f"Voice '{voice_id}' deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to delete voice: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# TTS SYNTHESIS ENDPOINT
# ============================================================================

@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    """Synthesize speech with specified voice and language"""
    global gpt_cond_latent, speaker_embedding
    
    start_time = time.time()
    
    try:
        if xtts_model is None:
            raise HTTPException(status_code=503, detail="Model not loaded")
        
        # Load requested voice if different from current
        await load_voice_embeddings(request.voice_id)
        
        if gpt_cond_latent is None or speaker_embedding is None:
            raise HTTPException(status_code=503, detail="Speaker embeddings not loaded")
        
        logger.info(f"🔊 Synthesizing: '{request.text[:50]}...' [lang={request.language}, voice={request.voice_id}]")
        
        audio_chunk_generator = xtts_model.inference_stream(
            text=request.text,
            language=request.language,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            stream_chunk_size=STREAM_CHUNK_SIZE,
            enable_text_splitting=True
        )
        
        await stream_audio_to_livekit(audio_chunk_generator, sample_rate=24000)
        
        total_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Completed in {total_time_ms:.0f}ms")
        
        return JSONResponse({
            "status": "success",
            "total_time_ms": round(total_time_ms, 2),
            "voice_id": request.voice_id,
            "language": request.language,
            "text_length": len(request.text)
        })
    
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
