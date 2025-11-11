#!/usr/bin/env python3
"""
June TTS Service - XTTS v2 with PostgreSQL Voice Storage
OPTIMIZED FOR LOW LATENCY
- Native 24 kHz XTTS output
- GPU-based 24k→48k resampling for LiveKit
- Optimal chunk sizes
- Minimal warmup
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

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("june-tts")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LIVEKIT_IDENTITY = os.getenv("LIVEKIT_IDENTITY", "june-tts")
LIVEKIT_ROOM_NAME = os.getenv("LIVEKIT_ROOM", "ozzu-main")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "https://api.ozzu.world")

# PostgreSQL
DB_HOST = os.getenv("DB_HOST", "100.64.0.1")
DB_PORT = int(os.getenv("DB_PORT", "30432"))
DB_NAME = os.getenv("DB_NAME", "june")
DB_USER = os.getenv("DB_USER", "keycloak")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Pokemon123!")

# Audio + streaming (optimized)
XTTS_SAMPLE_RATE = 24000          # XTTS native
LIVEKIT_SAMPLE_RATE = 48000       # LiveKit native
STREAM_CHUNK_SIZE = 20            # Small chunk for fast first audio
LIVEKIT_FRAME_SIZE = 960          # 20ms @ 48k

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="June TTS (XTTS v2) - Optimized",
    version="3.0.0",
    description="Low-latency streaming TTS with PostgreSQL voice storage"
)

# ---------------------------------------------------------------------------
# PyTorch 2.6 safe globals (XTTS pickles)
# ---------------------------------------------------------------------------
if hasattr(torch.serialization, "add_safe_globals"):
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

from TTS.api import TTS  # after safe-globals

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
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

# GPU resampler cache
_gpu_resampler = None

# ---------------------------------------------------------------------------
# Models / Schemas
# ---------------------------------------------------------------------------
class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    room_name: str = Field(..., description="LiveKit room name")
    language: str = Field(default="en")
    voice_id: str = Field(default="default")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def compute_tensor_hash(tensor):
    if tensor is None:
        return "None"
    if torch.is_tensor(tensor):
        arr = tensor.detach().cpu().numpy()
    else:
        arr = np.array(tensor)
    return hashlib.md5(arr.tobytes()).hexdigest()[:8]

def load_audio_with_soundfile(audio_path: str, sampling_rate: int = None):
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
    return audio_tensor.unsqueeze(0)

def load_audio_from_bytes(audio_bytes: bytes, sampling_rate: int = None):
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
    return audio_tensor.unsqueeze(0)

# Monkey-patch XTTS load_audio for robustness
import TTS.tts.models.xtts as xtts_module
_original_load_audio = xtts_module.load_audio
def _patched_load_audio(audiopath, sampling_rate=None):
    try:
        return load_audio_with_soundfile(audiopath, sampling_rate)
    except Exception as e:
        logger.warning(f"Soundfile load failed: {e}")
        return _original_load_audio(audiopath, sampling_rate)
xtts_module.load_audio = _patched_load_audio

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
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

async def get_voice_from_db(voice_id: str) -> bytes | None:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT audio_data FROM tts_voices WHERE voice_id = $1", voice_id
        )
    if row:
        logger.info(f"✅ Loaded voice '{voice_id}' from DB ({len(row['audio_data'])} bytes)")
        return bytes(row["audio_data"])
    logger.warning(f"⚠️ Voice '{voice_id}' not found in DB")
    return None

# ---------------------------------------------------------------------------
# Voice embeddings
# ---------------------------------------------------------------------------
async def load_voice_embeddings(voice_id: str = "default"):
    global gpt_cond_latent, speaker_embedding, speaker_embedding_hash, gpt_cond_hash, current_voice_id

    if voice_id == current_voice_id and gpt_cond_latent is not None:
        logger.debug(f"✅ Voice '{voice_id}' already cached")
        return True

    logger.info(f"📁 Loading voice '{voice_id}'...")
    audio_bytes = await get_voice_from_db(voice_id)

    if audio_bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(audio_bytes)
        try:
            gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                audio_path=[tmp_path]
            )
        finally:
            try: os.unlink(tmp_path)
            except FileNotFoundError: pass
        logger.info(f"✅ Embeddings generated for '{voice_id}'")
    else:
        # Fallback: 2s silence to produce "neutral" embeddings
        sample_rate = 22050
        silence = np.zeros(int(sample_rate * 2.0), dtype=np.float32)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            sf.write(tmp_path, silence, sample_rate)
        try:
            gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                audio_path=[tmp_path]
            )
        finally:
            try: os.unlink(tmp_path)
            except FileNotFoundError: pass
        logger.info("✅ Default silent embeddings generated")

    if torch.cuda.is_available():
        gpt_cond_latent = gpt_cond_latent.cuda()
        speaker_embedding = speaker_embedding.cuda()

    speaker_embedding_hash = compute_tensor_hash(speaker_embedding)
    gpt_cond_hash = compute_tensor_hash(gpt_cond_latent)
    current_voice_id = voice_id
    logger.info(f"🔑 Voice '{voice_id}' loaded: GPT={gpt_cond_hash}, Speaker={speaker_embedding_hash}")
    return True

# ---------------------------------------------------------------------------
# Model load + warmup
# ---------------------------------------------------------------------------
async def warmup_model():
    """Minimal warmup (English only by default)"""
    try:
        start = time.time()
        _ = list(xtts_model.inference_stream(
            text="Initializing speech synthesis.",
            language="en",
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            stream_chunk_size=STREAM_CHUNK_SIZE,
            enable_text_splitting=False
        ))
        logger.info(f"✅ Warmup complete in {(time.time()-start)*1000:.0f}ms")
    except Exception as e:
        logger.warning(f"⚠️ Warmup failed (non-critical): {e}")

async def load_xtts_model():
    global xtts_model, tts_api, _gpu_resampler
    logger.info("🔊 Loading XTTS v2...")
    tts_api = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=torch.cuda.is_available())
    xtts_model = tts_api.synthesizer.tts_model

    if torch.cuda.is_available():
        xtts_model.cuda()
        logger.info("✅ XTTS on GPU")
        import torchaudio.transforms as T
        _gpu_resampler = T.Resample(XTTS_SAMPLE_RATE, LIVEKIT_SAMPLE_RATE).cuda()
        logger.info("✅ GPU resampler ready (24k → 48k)")
    else:
        logger.warning("⚠️ XTTS on CPU")
        import torchaudio.transforms as T
        _gpu_resampler = T.Resample(XTTS_SAMPLE_RATE, LIVEKIT_SAMPLE_RATE)

    await load_voice_embeddings("default")
    await warmup_model()
    return True

# ---------------------------------------------------------------------------
# LiveKit
# ---------------------------------------------------------------------------
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
    """Connect using 48 kHz native source to avoid extra resampling."""
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
        logger.info(f"✅ LiveKit connected at {LIVEKIT_SAMPLE_RATE} Hz")
        return True
    except Exception as e:
        logger.error(f"❌ LiveKit connection failed: {e}")
        return False

def resample_audio_fast(chunk: np.ndarray, input_sr: int, output_sr: int) -> np.ndarray:
    """Prefer GPU torchaudio; fallback to scipy."""
    global _gpu_resampler
    if input_sr == output_sr:
        return chunk
    try:
        t = torch.from_numpy(chunk).float() if not torch.is_tensor(chunk) else chunk.float()
        if t.dim() == 1:
            t = t.unsqueeze(0)
        if torch.cuda.is_available() and _gpu_resampler is not None:
            t = t.cuda()
        if _gpu_resampler is None:
            import torchaudio.transforms as T
            _gpu_resampler = T.Resample(input_sr, output_sr)
            if torch.cuda.is_available():
                _gpu_resampler = _gpu_resampler.cuda()
        out = _gpu_resampler(t)
        return out.squeeze().detach().cpu().numpy()
    except Exception as e:
        logger.error(f"❌ GPU resampling failed, falling back: {e}")
        from scipy.signal import resample_poly
        return resample_poly(chunk, output_sr, input_sr)

async def stream_audio_to_livekit(audio_chunk_generator, sample_rate: int = XTTS_SAMPLE_RATE):
    global livekit_audio_source, livekit_connected
    if not livekit_connected or livekit_audio_source is None:
        logger.warning("LiveKit not connected")
        return

    t0 = time.time()
    first = True
    count = 0

    try:
        for chunk in audio_chunk_generator:
            if torch.is_tensor(chunk):
                chunk = chunk.detach().cpu().numpy()
            if chunk.ndim > 1:
                chunk = chunk.squeeze()

            if sample_rate != LIVEKIT_SAMPLE_RATE:
                chunk = resample_audio_fast(chunk, sample_rate, LIVEKIT_SAMPLE_RATE)

            if first:
                logger.info(f"⚡ First audio in {(time.time()-t0)*1000:.0f}ms")
                first = False

            # Frame and send @ 48kHz, 20ms (960 samples)
            for off in range(0, len(chunk), LIVEKIT_FRAME_SIZE):
                frame_data = chunk[off:off + LIVEKIT_FRAME_SIZE]
                if len(frame_data) < LIVEKIT_FRAME_SIZE:
                    frame_data = np.pad(frame_data, (0, LIVEKIT_FRAME_SIZE - len(frame_data)))
                pcm_int16 = (np.clip(frame_data, -1, 1) * 32767).astype(np.int16)
                frame = rtc.AudioFrame.create(LIVEKIT_SAMPLE_RATE, 1, LIVEKIT_FRAME_SIZE)
                np.copyto(np.frombuffer(frame.data, dtype=np.int16), pcm_int16)
                await livekit_audio_source.capture_frame(frame)

            count += 1

        logger.info(f"✅ Streamed {count} chunks")
    except Exception as e:
        logger.error(f"❌ Streaming error: {e}", exc_info=True)

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    logger.info("=" * 80)
    logger.info("🚀 Starting XTTS v2 TTS Service (OPTIMIZED)")
    logger.info(f"XTTS: {XTTS_SAMPLE_RATE} Hz | LiveKit: {LIVEKIT_SAMPLE_RATE} Hz")
    logger.info(f"Chunk size: {STREAM_CHUNK_SIZE} | Frame size: {LIVEKIT_FRAME_SIZE}")
    logger.info("=" * 80)

    await init_db_pool()
    ok = await load_xtts_model()
    if not ok:
        logger.error("Model failed to load")
        return
    asyncio.create_task(connect_livekit())
    logger.info("✅ Service ready")

@app.on_event("shutdown")
async def on_shutdown():
    if db_pool:
        await db_pool.close()
        logger.info("✅ Database pool closed")

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": xtts_model is not None,
        "livekit_connected": livekit_connected,
        "gpu_available": torch.cuda.is_available(),
        "db_connected": db_pool is not None,
        "current_voice": current_voice_id,
        "config": {
            "xtts_sample_rate": XTTS_SAMPLE_RATE,
            "livekit_sample_rate": LIVEKIT_SAMPLE_RATE,
            "stream_chunk_size": STREAM_CHUNK_SIZE,
            "livekit_frame_size": LIVEKIT_FRAME_SIZE,
            "gpu_resampler": _gpu_resampler is not None
        }
    }

# ---------------------------------------------------------------------------
# Voice management
# ---------------------------------------------------------------------------
@app.post("/api/voices/clone")
async def clone_voice(
    voice_id: str = Form(...),
    voice_name: str = Form(...),
    file: UploadFile = File(...)
):
    global db_pool, xtts_model

    try:
        if not file.filename.lower().endswith((".wav", ".mp3", ".flac")):
            raise HTTPException(400, "Only WAV, MP3, and FLAC audio files are supported")

        audio_bytes = await file.read()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(audio_bytes)
        try:
            audio, sr = sf.read(tmp_path)
            duration = len(audio) / sr
            if duration < 3:
                raise HTTPException(400, f"Audio too short ({duration:.1f}s). Minimum 3s required.")
            if duration > 60:
                raise HTTPException(400, f"Audio too long ({duration:.1f}s). Maximum 60s allowed.")

            gpt_cond, speaker_emb = xtts_model.get_conditioning_latents(audio_path=[tmp_path])
            gpt_hash = compute_tensor_hash(gpt_cond)
            speaker_hash = compute_tensor_hash(speaker_emb)
        finally:
            try: os.unlink(tmp_path)
            except FileNotFoundError: pass

        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT COUNT(*) FROM tts_voices WHERE voice_id = $1", voice_id
            )
            if exists > 0:
                raise HTTPException(409, f"Voice ID '{voice_id}' already exists.")
            await conn.execute("""
                INSERT INTO tts_voices (voice_id, name, audio_data, created_at, updated_at)
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, voice_id, voice_name, audio_bytes)

        return JSONResponse({
            "status": "success",
            "voice_id": voice_id,
            "voice_name": voice_name,
            "audio_duration_seconds": round(duration, 2),
            "audio_size_bytes": len(audio_bytes),
            "audio_size_kb": round(len(audio_bytes) / 1024, 2),
            "sample_rate": sr,
            "embeddings": {"gpt_hash": gpt_hash, "speaker_hash": speaker_hash},
            "quality_notes": {
                "duration_optimal": 6 <= duration <= 10,
                "duration_acceptable": 3 <= duration <= 60
            },
            "message": f"Voice '{voice_id}' cloned successfully."
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@app.get("/api/voices")
async def list_voices():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT voice_id, name, length(audio_data) AS size_bytes, created_at, updated_at
            FROM tts_voices
            ORDER BY created_at DESC
        """)
    voices = [{
        "voice_id": r["voice_id"],
        "name": r["name"],
        "size_bytes": r["size_bytes"],
        "size_kb": round(r["size_bytes"] / 1024, 2),
        "created_at": str(r["created_at"]),
        "updated_at": str(r["updated_at"]),
        "is_loaded": r["voice_id"] == current_voice_id
    } for r in rows]
    return {"total": len(voices), "voices": voices, "current_voice": current_voice_id}

@app.get("/api/voices/{voice_id}")
async def get_voice_info(voice_id: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT voice_id, name, length(audio_data) AS size_bytes, created_at, updated_at
            FROM tts_voices WHERE voice_id = $1
        """, voice_id)
    if not row:
        raise HTTPException(404, f"Voice '{voice_id}' not found")
    return {
        "voice_id": row["voice_id"],
        "name": row["name"],
        "size_bytes": row["size_bytes"],
        "size_kb": round(row["size_bytes"] / 1024, 2),
        "size_mb": round(row["size_bytes"] / (1024 * 1024), 2),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "is_loaded": voice_id == current_voice_id
    }

@app.delete("/api/voices/{voice_id}")
async def delete_voice(voice_id: str):
    if voice_id == current_voice_id:
        raise HTTPException(409, f"Cannot delete currently loaded voice '{voice_id}'. Load another voice first.")
    async with db_pool.acquire() as conn:
        result = await conn.execute("DELETE FROM tts_voices WHERE voice_id = $1", voice_id)
    if result == "DELETE 0":
        raise HTTPException(404, f"Voice '{voice_id}' not found")
    return {"status": "success", "message": f"Voice '{voice_id}' deleted successfully"}

# ---------------------------------------------------------------------------
# TTS synthesis
# ---------------------------------------------------------------------------
@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    global gpt_cond_latent, speaker_embedding, current_voice_id

    start_time = time.time()
    if xtts_model is None:
        raise HTTPException(503, "Model not loaded")

    if request.voice_id != current_voice_id:
        logger.info(f"🔄 Switching voice: {current_voice_id} → {request.voice_id}")
        await load_voice_embeddings(request.voice_id)

    if gpt_cond_latent is None or speaker_embedding is None:
        raise HTTPException(503, "Speaker embeddings not loaded")

    logger.info(f"🔊 Synthesizing '{request.text[:60]}...' [lang={request.language}, voice={request.voice_id}]")

    try:
        gen = xtts_model.inference_stream(
            text=request.text,
            language=request.language,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            stream_chunk_size=STREAM_CHUNK_SIZE,
            enable_text_splitting=True
        )
        await stream_audio_to_livekit(gen, sample_rate=XTTS_SAMPLE_RATE)

        total_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Completed in {total_ms:.0f} ms")
        return JSONResponse({
            "status": "success",
            "total_time_ms": round(total_ms, 2),
            "voice_id": request.voice_id,
            "language": request.language,
            "text_length": len(request.text)
        })
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}", exc_info=True)
        raise HTTPException(500, str(e))

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
