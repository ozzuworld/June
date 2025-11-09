#!/usr/bin/env python3
"""
June TTS Service - XTTS v2 with Speaker Consistency Diagnostics
Debug version to track speaker embedding consistency
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional
import traceback
import tempfile
import hashlib

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from livekit import rtc
import soundfile as sf

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
REFERENCE_AUDIO_PATH = os.getenv("REFERENCE_AUDIO", "/app/references/June.wav")

# PRODUCTION OPTIMIZED SETTINGS
STREAM_CHUNK_SIZE = 150
LIVEKIT_FRAME_SIZE = 960

app = FastAPI(
    title="June TTS (XTTS v2) - Speaker Debug",
    version="2.1.1-speaker-debug",
    description="Real-time streaming TTS with speaker consistency diagnostics"
)

# Global state
xtts_model = None
tts_api = None
gpt_cond_latent = None
speaker_embedding = None
livekit_room = None
livekit_audio_source = None
livekit_connected = False

# Speaker diagnostics
speaker_embedding_hash = None
gpt_cond_hash = None

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    room_name: str = Field(...)
    language: str = Field(default="en")
    stream: bool = Field(default=True)

def compute_tensor_hash(tensor):
    """Compute hash of tensor to track if it changes"""
    if tensor is None:
        return "None"
    if torch.is_tensor(tensor):
        tensor_np = tensor.cpu().detach().numpy()
    else:
        tensor_np = np.array(tensor)
    return hashlib.md5(tensor_np.tobytes()).hexdigest()[:8]

def log_speaker_info(gpt_lat, spk_emb, context=""):
    """Log detailed speaker embedding information"""
    logger.info(f"🎤 SPEAKER DEBUG ({context}):")
    
    if gpt_lat is not None:
        gpt_hash = compute_tensor_hash(gpt_lat)
        if torch.is_tensor(gpt_lat):
            logger.info(f"   GPT Cond Latent: shape={gpt_lat.shape}, dtype={gpt_lat.dtype}, device={gpt_lat.device}")
            logger.info(f"   GPT hash: {gpt_hash}, mean={gpt_lat.mean().item():.6f}, std={gpt_lat.std().item():.6f}")
        else:
            logger.info(f"   GPT Cond Latent: {type(gpt_lat)}, hash={gpt_hash}")
    else:
        logger.warning(f"   GPT Cond Latent: None")
    
    if spk_emb is not None:
        spk_hash = compute_tensor_hash(spk_emb)
        if torch.is_tensor(spk_emb):
            logger.info(f"   Speaker Embedding: shape={spk_emb.shape}, dtype={spk_emb.dtype}, device={spk_emb.device}")
            logger.info(f"   Speaker hash: {spk_hash}, mean={spk_emb.mean().item():.6f}, std={spk_emb.std().item():.6f}")
        else:
            logger.info(f"   Speaker Embedding: {type(spk_emb)}, hash={spk_hash}")
    else:
        logger.warning(f"   Speaker Embedding: None")

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

async def load_xtts_model():
    """Load XTTS v2 model"""
    global xtts_model, tts_api, gpt_cond_latent, speaker_embedding
    global speaker_embedding_hash, gpt_cond_hash
    
    try:
        logger.info("🔊 Loading XTTS v2 model...")
        tts_api = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=torch.cuda.is_available())
        xtts_model = tts_api.synthesizer.tts_model
        
        if torch.cuda.is_available():
            xtts_model.cuda()
            logger.info("✅ XTTS v2 loaded on GPU")
        else:
            logger.warning("⚠️ XTTS v2 loaded on CPU")
        
        if os.path.exists(REFERENCE_AUDIO_PATH):
            logger.info(f"📁 Loading reference voice from {REFERENCE_AUDIO_PATH}")
            gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                audio_path=[REFERENCE_AUDIO_PATH]
            )
            logger.info("✅ Custom speaker embeddings loaded")
        else:
            logger.info("✅ Using default speaker (generating from silent audio)...")
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
                logger.info("✅ Default speaker embeddings generated")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        
        # Store initial hashes
        speaker_embedding_hash = compute_tensor_hash(speaker_embedding)
        gpt_cond_hash = compute_tensor_hash(gpt_cond_latent)
        
        logger.info("=" * 80)
        log_speaker_info(gpt_cond_latent, speaker_embedding, "INITIAL LOAD")
        logger.info(f"🔑 Initial Hashes: GPT={gpt_cond_hash}, Speaker={speaker_embedding_hash}")
        logger.info("=" * 80)
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed to load XTTS v2: {e}")
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
    """Stream audio with diagnostics"""
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
        logger.error(traceback.format_exc())

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Starting XTTS v2 TTS Service (Speaker Debug Mode)")
    logger.info(f"📊 Settings: chunk_size={STREAM_CHUNK_SIZE}, frame_size={LIVEKIT_FRAME_SIZE}")
    model_loaded = await load_xtts_model()
    if not model_loaded:
        logger.error("Failed to load XTTS model")
        return
    asyncio.create_task(connect_livekit())
    logger.info("✅ Service ready")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": xtts_model is not None,
        "livekit_connected": livekit_connected,
        "gpu_available": torch.cuda.is_available(),
        "stream_chunk_size": STREAM_CHUNK_SIZE,
        "speaker_embedding_hash": speaker_embedding_hash,
        "gpt_cond_hash": gpt_cond_hash
    }

@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    """Synthesize with speaker consistency checks"""
    global gpt_cond_latent, speaker_embedding, speaker_embedding_hash, gpt_cond_hash
    
    start_time = time.time()
    
    try:
        if xtts_model is None:
            raise HTTPException(status_code=503, detail="Model not loaded")
        
        if gpt_cond_latent is None or speaker_embedding is None:
            raise HTTPException(status_code=503, detail="Speaker embeddings not loaded")
        
        logger.info("=" * 80)
        logger.info(f"🔊 NEW SYNTHESIS REQUEST: '{request.text[:50]}...' ({len(request.text)} chars)")
        
        # Check if speaker embeddings have changed
        current_spk_hash = compute_tensor_hash(speaker_embedding)
        current_gpt_hash = compute_tensor_hash(gpt_cond_latent)
        
        if current_spk_hash != speaker_embedding_hash:
            logger.error(f"⚠️  SPEAKER EMBEDDING CHANGED!")
            logger.error(f"   Expected: {speaker_embedding_hash}, Got: {current_spk_hash}")
            log_speaker_info(gpt_cond_latent, speaker_embedding, "BEFORE SYNTHESIS")
        else:
            logger.info(f"✅ Speaker embedding consistent: {current_spk_hash}")
        
        if current_gpt_hash != gpt_cond_hash:
            logger.error(f"⚠️  GPT COND LATENT CHANGED!")
            logger.error(f"   Expected: {gpt_cond_hash}, Got: {current_gpt_hash}")
        else:
            logger.info(f"✅ GPT cond latent consistent: {current_gpt_hash}")
        
        # Verify tensors are on correct device
        if torch.cuda.is_available():
            if gpt_cond_latent.device.type != 'cuda':
                logger.warning(f"⚠️  GPT latent on {gpt_cond_latent.device}, moving to cuda")
                gpt_cond_latent = gpt_cond_latent.cuda()
            if speaker_embedding.device.type != 'cuda':
                logger.warning(f"⚠️  Speaker embedding on {speaker_embedding.device}, moving to cuda")
                speaker_embedding = speaker_embedding.cuda()
        
        audio_chunk_generator = xtts_model.inference_stream(
            text=request.text,
            language=request.language,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            stream_chunk_size=STREAM_CHUNK_SIZE,
            enable_text_splitting=True
        )
        
        await stream_audio_to_livekit(audio_chunk_generator, sample_rate=24000)
        
        # Check again after synthesis
        post_spk_hash = compute_tensor_hash(speaker_embedding)
        post_gpt_hash = compute_tensor_hash(gpt_cond_latent)
        
        if post_spk_hash != current_spk_hash:
            logger.error(f"❌ SPEAKER EMBEDDING MODIFIED DURING SYNTHESIS!")
            logger.error(f"   Before: {current_spk_hash}, After: {post_spk_hash}")
            log_speaker_info(gpt_cond_latent, speaker_embedding, "AFTER SYNTHESIS")
        
        if post_gpt_hash != current_gpt_hash:
            logger.error(f"❌ GPT COND LATENT MODIFIED DURING SYNTHESIS!")
            logger.error(f"   Before: {current_gpt_hash}, After: {post_gpt_hash}")
        
        total_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Completed in {total_time_ms:.0f}ms")
        logger.info("=" * 80)
        
        return JSONResponse({
            "status": "success",
            "total_time_ms": round(total_time_ms, 2),
            "room_name": request.room_name,
            "text_length": len(request.text),
            "language": request.language,
            "speaker_hash": post_spk_hash,
            "gpt_hash": post_gpt_hash,
            "speaker_consistent": post_spk_hash == current_spk_hash
        })
    
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)