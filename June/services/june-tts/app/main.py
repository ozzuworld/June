#!/usr/bin/env python3
"""
June TTS Service - Chatterbox TTS Integration
Multilingual TTS with voice cloning and emotion control
"""
import asyncio
import io
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch
import torchaudio as ta
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from livekit import rtc
from pydantic import BaseModel, Field
import asyncpg

# CRITICAL: Import chatterbox_vllm models to register custom tokenizers BEFORE vLLM multiprocessing
# vLLM uses multiprocessing spawn mode, so tokenizers must be registered at module level
try:
    import chatterbox_vllm.models.t3  # Registers EnTokenizer and MtlTokenizer
except ImportError:
    pass  # Will fail gracefully during model load if chatterbox-vllm not installed

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("june-tts-chatterbox")

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
LIVEKIT_IDENTITY = os.getenv("LIVEKIT_IDENTITY", "june-tts")
LIVEKIT_ROOM_NAME = os.getenv("LIVEKIT_ROOM", "ozzu-main")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "https://api.ozzu.world")

# Chatterbox settings
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
USE_MULTILINGUAL = os.getenv("USE_MULTILINGUAL", "1") == "1"
WARMUP_ON_STARTUP = os.getenv("WARMUP_ON_STARTUP", "1") == "1"
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "1000"))

# Phase 1 Optimization settings (legacy - now using vLLM)
USE_FP16 = os.getenv("USE_FP16", "0") == "1" and DEVICE == "cuda"  # vLLM handles precision internally
USE_TORCH_COMPILE = os.getenv("USE_TORCH_COMPILE", "0") == "1"  # Not used with vLLM
TORCH_COMPILE_MODE = os.getenv("TORCH_COMPILE_MODE", "reduce-overhead")

# vLLM Optimization settings (4-10x speedup)
VLLM_GPU_MEMORY_UTILIZATION = float(os.getenv("VLLM_GPU_MEMORY_UTILIZATION", "0.6"))
VLLM_MAX_MODEL_LEN = int(os.getenv("VLLM_MAX_MODEL_LEN", "1000"))
VLLM_ENFORCE_EAGER = os.getenv("VLLM_ENFORCE_EAGER", "1") == "1"
CHATTERBOX_CFG_SCALE = float(os.getenv("CHATTERBOX_CFG_SCALE", "0.3"))

# PostgreSQL
DB_HOST = os.getenv("DB_HOST", "100.64.0.1")
DB_PORT = int(os.getenv("DB_PORT", "30432"))
DB_NAME = os.getenv("DB_NAME", "june")
DB_USER = os.getenv("DB_USER", "keycloak")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Pokemon123!")

# Audio settings
CHATTERBOX_SAMPLE_RATE = 24000  # Chatterbox default
LIVEKIT_SAMPLE_RATE = 48000
LIVEKIT_FRAME_SIZE = 960  # 20ms @ 48kHz
FRAME_PERIOD_S = 0.020

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(
    title="June TTS (Chatterbox vLLM)",
    version="7.0.0-vllm",
    description="Chatterbox TTS with vLLM port: 4-10x faster inference with automatic batching"
)

# -----------------------------------------------------------------------------
# Global state
# -----------------------------------------------------------------------------
model = None
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
voice_cache = {}  # Maps voice_id -> file path
voice_cache_gpu = {}  # Maps voice_id -> preprocessed GPU tensors (Phase 1 optimization)

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
    language: str = Field(default="en", description="Language code for multilingual model")
    # Phase 1: Optimized defaults for speed (was 0.5/0.5/0.9)
    exaggeration: float = Field(default=0.35, ge=0.0, le=2.0, description="Emotion intensity (0.0=flat, 2.0=very expressive)")
    cfg_weight: float = Field(default=0.3, ge=0.0, le=1.0, description="Voice adherence (lower=better pacing)")
    temperature: float = Field(default=0.7, ge=0.1, le=2.0, description="Sampling temperature")

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

    # Save to temp file for Chatterbox
    temp_path = f"/tmp/voice_{voice_id}.wav"
    with open(temp_path, 'wb') as f:
        f.write(audio_bytes)

    voice_cache[voice_id] = temp_path
    current_voice_id = voice_id
    current_reference_audio_path = temp_path
    logger.info(f"✅ Voice '{voice_id}' loaded to {temp_path}")
    return temp_path

async def preload_all_voices():
    """Phase 1 Optimization: Pre-load all voices from database into cache on startup"""
    try:
        if db_pool is None:
            logger.warning("⚠️ Cannot preload voices: DB pool not initialized")
            return

        logger.info("📦 Preloading all voices from database...")
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT voice_id, audio_data FROM tts_voices")

        if not rows:
            logger.info("   No voices found in database to preload")
            return

        for row in rows:
            voice_id = row["voice_id"]
            audio_bytes = bytes(row["audio_data"])

            # Save to temp file
            temp_path = f"/tmp/voice_{voice_id}.wav"
            with open(temp_path, 'wb') as f:
                f.write(audio_bytes)

            # Cache the path
            voice_cache[voice_id] = temp_path

        logger.info(f"✅ Preloaded {len(rows)} voices into cache")

    except Exception as e:
        logger.error(f"❌ Failed to preload voices: {e}", exc_info=True)

# -----------------------------------------------------------------------------
# Chatterbox Model Management
# -----------------------------------------------------------------------------
async def load_model():
    """Load Chatterbox vLLM model on startup (4-10x faster than original)"""
    global model

    logger.info("=" * 80)
    logger.info("🚀 Loading Chatterbox TTS Model (vLLM Port - 4-10x Faster)")
    logger.info(f"   Device: {DEVICE}")
    logger.info(f"   GPU Memory Utilization: {VLLM_GPU_MEMORY_UTILIZATION}")
    logger.info(f"   Max Model Length: {VLLM_MAX_MODEL_LEN}")
    logger.info(f"   Enforce Eager: {VLLM_ENFORCE_EAGER}")
    logger.info(f"   CFG Scale: {CHATTERBOX_CFG_SCALE}")
    logger.info("=" * 80)

    try:
        # Set CFG scale via environment variable (required by vLLM port)
        os.environ["CHATTERBOX_CFG_SCALE"] = str(CHATTERBOX_CFG_SCALE)

        # Manually replicate what ChatterboxTTS.from_pretrained() is supposed to do
        # The library has a bug where it doesn't create the ./t3-model directory before
        # trying to create a symlink inside it
        logger.info("📥 Downloading Chatterbox model files from HuggingFace...")
        from huggingface_hub import hf_hub_download
        from pathlib import Path

        REPO_ID = "ResembleAI/chatterbox"
        REVISION = "1b475dffa71fb191cb6d5901215eb6f55635a9b6"

        # Download required files (same as library's from_pretrained)
        for fpath in ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"]:
            local_path = hf_hub_download(repo_id=REPO_ID, filename=fpath, revision=REVISION)

        logger.info(f"✅ Model files downloaded to HF cache")

        # Create symlink structure that vLLM expects (fixing the library bug)
        t3_cfg_path = Path(local_path).parent / "t3_cfg.safetensors"
        t3_model_dir = Path("/app/t3-model")
        t3_model_dir.mkdir(exist_ok=True)  # This is what the library forgot to do!
        model_safetensors_path = t3_model_dir / "model.safetensors"
        model_safetensors_path.unlink(missing_ok=True)
        model_safetensors_path.symlink_to(t3_cfg_path)
        logger.info(f"✅ Created symlink: {model_safetensors_path} -> {t3_cfg_path}")

        # Create config.json for vLLM (another missing piece)
        # vLLM needs this to identify the model architecture and configuration
        import json
        config_json = {
            "architectures": ["ChatterboxT3"],  # Registered custom model class
            "model_type": "llama",
            "hidden_size": 1024,  # From T3Config.n_channels
            "intermediate_size": 2752,  # Llama_520M config
            "num_attention_heads": 16,
            "num_hidden_layers": 24,
            "num_key_value_heads": 16,
            "vocab_size": 704,  # English tokenizer size
            "max_position_embeddings": 2048,
            "rms_norm_eps": 1e-5,
            "rope_theta": 10000.0,
            "torch_dtype": "float16"
        }
        config_path = t3_model_dir / "config.json"
        with open(config_path, 'w') as f:
            json.dump(config_json, f, indent=2)
        logger.info(f"✅ Created config.json: {config_path}")

        # Copy tokenizer.json to the model directory
        import shutil
        tokenizer_src = Path(local_path).parent / "tokenizer.json"
        tokenizer_dst = t3_model_dir / "tokenizer.json"
        shutil.copy2(tokenizer_src, tokenizer_dst)
        logger.info(f"✅ Copied tokenizer.json to model directory")

        from chatterbox_vllm.tts import ChatterboxTTS
        # Note: Custom tokenizers (EnTokenizer, MtlTokenizer) are registered at module level
        # to ensure they're available in vLLM's multiprocessing subprocesses

        # Now call from_local() with the HF cache directory
        logger.info("📦 Initializing vLLM engine from local model...")
        # Note: from_local() calculates gpu_memory_utilization internally based on
        # max_batch_size and max_model_len. We can't override it directly.
        # The 'compile' parameter controls enforce_eager (compile=False → enforce_eager=True)
        # Using minimal parameters to avoid API version incompatibilities
        model = ChatterboxTTS.from_local(
            str(Path(local_path).parent),  # ckpt_dir - use string path for compatibility
            target_device="cuda" if DEVICE == "cuda" else "cpu",
            max_model_len=VLLM_MAX_MODEL_LEN,
            compile=not VLLM_ENFORCE_EAGER,  # compile=False means enforce_eager=True
            max_batch_size=10,  # Default from library, affects GPU memory calculation
            # Note: variant defaults to "english" in the library, which is what we want
        )
        logger.info("✅ Chatterbox vLLM model loaded")

        global CHATTERBOX_SAMPLE_RATE
        CHATTERBOX_SAMPLE_RATE = model.sr
        logger.info(f"   Sample Rate: {CHATTERBOX_SAMPLE_RATE} Hz")

        # vLLM Optimizations are built-in
        logger.info("⚡ vLLM Optimizations Active:")
        logger.info("   - Automatic batching support")
        logger.info("   - Optimized GPU memory management")
        logger.info("   - PagedAttention for faster inference")
        logger.info("   - 4-10x speedup vs original implementation")

        # Warmup generation
        if WARMUP_ON_STARTUP:
            logger.info("⏱️  Warming up vLLM model...")
            start = time.time()
            warmup_text = "Hello world."

            # vLLM expects list of prompts
            _ = model.generate([warmup_text], exaggeration=0.5)

            elapsed = time.time() - start
            logger.info(f"✅ Warmup complete ({elapsed:.1f}s)")

        logger.info("✅ vLLM model ready for inference")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to load vLLM model: {e}", exc_info=True)
        return False

async def generate_async(
    text: str,
    audio_prompt_path: Optional[str] = None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,  # Not used in vLLM (set globally via env var)
    temperature: float = 0.9,  # Not exposed in vLLM port
    language_id: Optional[str] = None  # Limited support in vLLM
):
    """Run vLLM generate() in thread pool (4-10x faster than original)"""
    loop = asyncio.get_event_loop()

    def _generate():
        try:
            # vLLM expects list of prompts
            prompts = [text]

            kwargs = {
                "exaggeration": exaggeration,
            }

            # Voice reference audio
            if audio_prompt_path and os.path.exists(audio_prompt_path):
                kwargs["audio_prompt_path"] = audio_prompt_path

            # Note: CFG is controlled globally via CHATTERBOX_CFG_SCALE env var
            # Note: temperature not exposed in vLLM port
            # Note: language_id has limited support in vLLM port

            # Generate with vLLM (returns list of tensors)
            audios = model.generate(prompts, **kwargs)

            # Extract single audio from list
            wav = audios[0]

            return wav

        except Exception as e:
            logger.error(f"❌ vLLM generation error: {e}", exc_info=True)
            raise

    wav = await loop.run_in_executor(executor, _generate)
    return wav

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
        track = rtc.LocalAudioTrack.create_audio_track("chatterbox-audio", source)
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

    logger.info(f"✅ Streamed {frames_sent} frames")

# -----------------------------------------------------------------------------
# Lifecycle
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    logger.info("=" * 80)
    logger.info("🚀 Chatterbox TTS Service Starting (vLLM Port - 4-10x Faster)")
    logger.info("=" * 80)

    # Load vLLM model
    await load_model()

    # Initialize database
    await init_db_pool()

    # Preload all voices into cache
    await preload_all_voices()

    # Load default voice
    await load_voice_reference("default")

    # Connect to LiveKit
    asyncio.create_task(connect_livekit())

    logger.info("✅ Service ready")
    logger.info("=" * 80)
    logger.info("vLLM Optimizations Active:")
    logger.info(f"  ⚡ GPU Memory Utilization: {VLLM_GPU_MEMORY_UTILIZATION}")
    logger.info(f"  ⚡ Max Model Length: {VLLM_MAX_MODEL_LEN}")
    logger.info(f"  ⚡ CFG Scale: {CHATTERBOX_CFG_SCALE}")
    logger.info(f"  ⚡ Automatic Batching: Enabled")
    logger.info(f"  ⚡ Voice Cache: {len(voice_cache)} voices preloaded")
    logger.info(f"  ⚡ Expected Speedup: 4-10x vs original Chatterbox")
    logger.info("=" * 80)

@app.on_event("shutdown")
async def on_shutdown():
    if db_pool:
        await db_pool.close()
    executor.shutdown(wait=True)
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
        "status": "ok" if model is not None else "model_not_loaded",
        "mode": "chatterbox_vllm",
        "model_type": "vllm_port",
        "device": DEVICE,
        "sample_rate": CHATTERBOX_SAMPLE_RATE if model else None,
        "livekit_connected": livekit_connected,
        "db_connected": db_pool is not None,
        "current_voice": current_voice_id,
        "voices_cached": len(voice_cache),
        # vLLM optimization status
        "optimizations": {
            "engine": "vllm",
            "version": "7.0.0-vllm",
            "expected_speedup": "4-10x",
            "gpu_memory_utilization": VLLM_GPU_MEMORY_UTILIZATION,
            "max_model_len": VLLM_MAX_MODEL_LEN,
            "enforce_eager": VLLM_ENFORCE_EAGER,
            "cfg_scale": CHATTERBOX_CFG_SCALE,
            "automatic_batching": True,
            "optimized_defaults": {
                "exaggeration": 0.35,
                "cfg_weight": CHATTERBOX_CFG_SCALE,
            }
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
            if duration < 10:
                raise HTTPException(400, f"Audio too short ({duration:.1f}s). Minimum 10s for Chatterbox.")
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
    return {"total": len(voices), "voices": voices, "current_voice": current_voice_id, "cached_voices": list(voice_cache.keys())}

# -----------------------------------------------------------------------------
# TTS synthesis
# -----------------------------------------------------------------------------
@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    if model is None:
        raise HTTPException(503, "Model not loaded")

    start_time = time.time()

    try:
        logger.info(f"🎙️ Synthesizing: '{request.text[:60]}...'")
        logger.info(f"   Voice: {request.voice_id}, Language: {request.language}")
        logger.info(f"   Params: exaggeration={request.exaggeration}, cfg_weight={request.cfg_weight}")

        # Load voice reference if different
        voice_path = None
        if request.voice_id != current_voice_id:
            voice_path = await load_voice_reference(request.voice_id)
        else:
            voice_path = current_reference_audio_path

        # Generate audio with Chatterbox
        wav = await generate_async(
            text=request.text,
            audio_prompt_path=voice_path,
            exaggeration=request.exaggeration,
            cfg_weight=request.cfg_weight,
            temperature=request.temperature,
            language_id=request.language if USE_MULTILINGUAL else None
        )

        # Convert to WAV bytes
        buffer = io.BytesIO()
        ta.save(buffer, wav, CHATTERBOX_SAMPLE_RATE, format="wav")
        audio_bytes = buffer.getvalue()

        # Stream to LiveKit
        await stream_audio_to_livekit(audio_bytes)

        total_ms = (time.time() - start_time) * 1000
        audio_duration = len(wav[0]) / CHATTERBOX_SAMPLE_RATE
        rtf = (total_ms / 1000.0) / audio_duration  # Real-time factor

        # GPU metrics
        gpu_memory_used = 0
        if torch.cuda.is_available():
            gpu_memory_used = torch.cuda.memory_allocated() / 1024**2  # MB

        logger.info(f"✅ Generated {audio_duration:.2f}s audio in {total_ms:.0f}ms (RTF: {rtf:.2f}x)")

        return JSONResponse({
            "status": "success",
            "mode": "chatterbox_vllm",
            "model_type": "vllm_port",
            "total_time_ms": round(total_ms, 2),
            "audio_duration_seconds": round(audio_duration, 2),
            "voice_id": request.voice_id,
            "language": request.language,
            # vLLM Performance metrics
            "performance": {
                "real_time_factor": round(rtf, 3),
                "inference_speedup": round(1.0 / rtf, 2) if rtf > 0 else 0,
                "gpu_memory_used_mb": round(gpu_memory_used, 1),
                "optimizations_active": {
                    "vllm": True,
                    "automatic_batching": True,
                    "cfg_scale": CHATTERBOX_CFG_SCALE,
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
