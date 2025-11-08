#!/usr/bin/env python3
"""
June TTS Service - XTTS v2 with Detailed Streaming Diagnostics
Debug version to measure timing between chunks and identify bottlenecks
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional
import traceback
import tempfile
from collections import deque

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
REFERENCE_AUDIO_PATH = os.getenv("REFERENCE_AUDIO", "/app/references/default_voice.wav")

# XTTS v2 streaming parameters - can be adjusted via env vars for testing
STREAM_CHUNK_SIZE = int(os.getenv("STREAM_CHUNK_SIZE", "20"))  # Default 20, try 150 for smooth
LIVEKIT_FRAME_SIZE = int(os.getenv("LIVEKIT_FRAME_SIZE", "320"))  # Default 20ms, try 960 for 60ms

app = FastAPI(
    title="June TTS (XTTS v2) - Debug",
    version="2.1.0-debug",
    description="Real-time streaming TTS with detailed timing diagnostics"
)

# Global state
xtts_model = None
tts_api = None
gpt_cond_latent = None
speaker_embedding = None
livekit_room = None
livekit_audio_source = None
livekit_connected = False

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    room_name: str = Field(...)
    language: str = Field(default="en")
    stream: bool = Field(default=True)

def load_audio_with_soundfile(audio_path: str, sampling_rate: int = None):
    """Load audio using soundfile and return as 2D torch tensor (1, samples)"""
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
        logger.warning(f"Soundfile load failed, trying original: {e}")
        return original_load_audio(audiopath, sampling_rate)

xtts_module.load_audio = patched_load_audio

async def load_xtts_model():
    """Load XTTS v2 model"""
    global xtts_model, tts_api, gpt_cond_latent, speaker_embedding
    
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
            logger.info(f"Loading reference voice from {REFERENCE_AUDIO_PATH}")
            gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                audio_path=[REFERENCE_AUDIO_PATH]
            )
            logger.info("✅ Custom speaker embeddings loaded")
        else:
            logger.info("✅ Using default speaker...")
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
    """
    Stream audio with DETAILED TIMING DIAGNOSTICS
    """
    global livekit_audio_source, livekit_connected
    
    if not livekit_connected or livekit_audio_source is None:
        logger.warning("LiveKit not connected")
        return
    
    start_time = time.time()
    first_chunk_time = None
    last_chunk_time = None
    chunk_count = 0
    total_audio_duration = 0.0
    chunk_timings = []
    
    logger.info("=" * 80)
    logger.info("🎯 STREAMING DIAGNOSTICS START")
    logger.info(f"📊 Configuration: chunk_size={STREAM_CHUNK_SIZE}, frame_size={LIVEKIT_FRAME_SIZE}samples ({LIVEKIT_FRAME_SIZE/16:.1f}ms)")
    logger.info("=" * 80)
    
    try:
        for chunk in audio_chunk_generator:
            current_time = time.time()
            
            if first_chunk_time is None:
                first_chunk_time = current_time
                time_to_first_chunk = (first_chunk_time - start_time) * 1000
                logger.info(f"⚡ FIRST CHUNK: {time_to_first_chunk:.1f}ms from start")
            
            chunk_count += 1
            
            # Calculate time between chunks
            if last_chunk_time is not None:
                gap_ms = (current_time - last_chunk_time) * 1000
                chunk_timings.append(gap_ms)
                
                # Log warning if gap is too large (indicates stutter)
                if gap_ms > 100:
                    logger.warning(f"⚠️  LARGE GAP: Chunk #{chunk_count} arrived {gap_ms:.1f}ms after previous chunk")
                else:
                    logger.info(f"✅ Chunk #{chunk_count}: {gap_ms:.1f}ms gap (good)")
            
            last_chunk_time = current_time
            
            if torch.is_tensor(chunk):
                chunk = chunk.cpu().numpy()
            
            if len(chunk.shape) > 1:
                chunk = chunk.squeeze()
            
            # Calculate audio duration
            chunk_duration = len(chunk) / sample_rate
            total_audio_duration += chunk_duration
            logger.info(f"   📏 Chunk #{chunk_count} contains {chunk_duration*1000:.1f}ms of audio ({len(chunk)} samples @ {sample_rate}Hz)")
            
            # Resample to 16kHz
            if sample_rate != 16000:
                from scipy.signal import resample_poly
                chunk = resample_poly(chunk, 16000, sample_rate)
            
            # Count frames published
            frame_count = 0
            for offset in range(0, len(chunk), LIVEKIT_FRAME_SIZE):
                frame_data = chunk[offset:offset+LIVEKIT_FRAME_SIZE]
                if len(frame_data) < LIVEKIT_FRAME_SIZE:
                    frame_data = np.pad(frame_data, (0, LIVEKIT_FRAME_SIZE-len(frame_data)), 'constant')
                
                pcm_int16 = (np.clip(frame_data, -1, 1) * 32767).astype(np.int16)
                frame = rtc.AudioFrame.create(16000, 1, LIVEKIT_FRAME_SIZE)
                np.copyto(np.frombuffer(frame.data, dtype=np.int16), pcm_int16)
                await livekit_audio_source.capture_frame(frame)
                frame_count += 1
            
            logger.info(f"   📤 Published {frame_count} frames to LiveKit")
        
        total_time = (time.time() - start_time) * 1000
        
        logger.info("=" * 80)
        logger.info("📊 STREAMING DIAGNOSTICS SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total chunks: {chunk_count}")
        logger.info(f"Total audio duration: {total_audio_duration:.2f}s ({total_audio_duration*1000:.0f}ms)")
        logger.info(f"Total time elapsed: {total_time:.0f}ms")
        logger.info(f"Real-time factor: {total_time / (total_audio_duration * 1000):.2f}x")
        
        if chunk_timings:
            avg_gap = np.mean(chunk_timings)
            max_gap = np.max(chunk_timings)
            min_gap = np.min(chunk_timings)
            logger.info(f"Chunk gaps: avg={avg_gap:.1f}ms, min={min_gap:.1f}ms, max={max_gap:.1f}ms")
            
            # Identify if gaps are the problem
            if max_gap > 500:
                logger.error(f"❌ ISSUE DETECTED: Large gap of {max_gap:.1f}ms between chunks!")
                logger.error("   This will cause audible stutters. Problem is in TTS generation.")
            elif avg_gap > 200:
                logger.warning(f"⚠️  POTENTIAL ISSUE: Average gap of {avg_gap:.1f}ms is high")
                logger.warning("   Consider increasing stream_chunk_size for smoother audio")
            else:
                logger.info(f"✅ Chunk timing looks good! Gaps are acceptable.")
        
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Error streaming audio: {e}")
        logger.error(traceback.format_exc())

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Starting XTTS v2 TTS Service (Debug Mode)...")
    logger.info(f"📊 Config: STREAM_CHUNK_SIZE={STREAM_CHUNK_SIZE}, LIVEKIT_FRAME_SIZE={LIVEKIT_FRAME_SIZE}")
    model_loaded = await load_xtts_model()
    if not model_loaded:
        logger.error("Failed to load XTTS model")
        return
    asyncio.create_task(connect_livekit())
    logger.info("✅ XTTS v2 TTS Service ready")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": xtts_model is not None,
        "livekit_connected": livekit_connected,
        "gpu_available": torch.cuda.is_available(),
        "streaming_enabled": True,
        "stream_chunk_size": STREAM_CHUNK_SIZE,
        "frame_size_ms": (LIVEKIT_FRAME_SIZE / 16000) * 1000,
        "debug_mode": True
    }

@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    """Synthesize speech with detailed diagnostics"""
    start_time = time.time()
    
    try:
        if xtts_model is None:
            raise HTTPException(status_code=503, detail="Model not loaded")
        
        if gpt_cond_latent is None or speaker_embedding is None:
            raise HTTPException(status_code=503, detail="Speaker embeddings not loaded")
        
        logger.info(f"🔊 Synthesizing: '{request.text}'")
        logger.info(f"   Text length: {len(request.text)} chars")
        
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
        logger.info(f"✅ Total request time: {total_time_ms:.0f}ms")
        
        return JSONResponse({
            "status": "success",
            "total_time_ms": round(total_time_ms, 2),
            "room_name": request.room_name,
            "text_length": len(request.text),
            "language": request.language,
            "stream_chunk_size": STREAM_CHUNK_SIZE,
            "frame_size_ms": (LIVEKIT_FRAME_SIZE / 16000) * 1000,
            "debug_mode": True
        })
    
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)