#!/usr/bin/env python3
"""
June TTS Service - XTTS v2 with TRUE Streaming to LiveKit
Working version - bypasses torchcodec issue
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional
import traceback
import tempfile

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

# XTTS v2 streaming parameters
STREAM_CHUNK_SIZE = 20

app = FastAPI(
    title="June TTS (XTTS v2)",
    version="2.0.0",
    description="Real-time streaming TTS with Coqui XTTS v2 and LiveKit integration"
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

def load_audio_with_soundfile(audio_path: str):
    """
    Load audio using soundfile instead of torchaudio to avoid torchcodec issue
    Returns audio tensor and sample rate compatible with XTTS
    """
    audio, sr = sf.read(audio_path)
    # Convert to float32 and normalize
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32767.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483647.0
    
    # Ensure mono
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    
    return torch.FloatTensor(audio), sr

# Monkey-patch the load_audio function in XTTS to use soundfile
import TTS.tts.models.xtts as xtts_module
original_load_audio = xtts_module.load_audio

def patched_load_audio(audiopath, sampling_rate=None):
    """Patched version that uses soundfile instead of torchaudio"""
    try:
        audio, sr = load_audio_with_soundfile(audiopath)
        
        # Resample if needed
        if sampling_rate is not None and sr != sampling_rate:
            import torchaudio.transforms as T
            resampler = T.Resample(sr, sampling_rate)
            audio = resampler(audio)
            sr = sampling_rate
        
        return audio, sr
    except Exception as e:
        logger.warning(f"Soundfile load failed, trying original method: {e}")
        return original_load_audio(audiopath, sampling_rate)

# Apply the monkey patch
xtts_module.load_audio = patched_load_audio

async def load_xtts_model():
    """Load XTTS v2 model for streaming inference"""
    global xtts_model, tts_api, gpt_cond_latent, speaker_embedding
    
    try:
        logger.info("🔊 Loading XTTS v2 model...")
        
        # Load TTS API
        tts_api = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=torch.cuda.is_available())
        
        # Get direct access to underlying XTTS model
        xtts_model = tts_api.synthesizer.tts_model
        
        # Move to GPU if available
        if torch.cuda.is_available():
            xtts_model.cuda()
            logger.info("✅ XTTS v2 loaded on GPU")
        else:
            logger.warning("⚠️ XTTS v2 loaded on CPU (will be slow)")
        
        # Load speaker embeddings
        if os.path.exists(REFERENCE_AUDIO_PATH):
            logger.info(f"Loading reference voice from {REFERENCE_AUDIO_PATH}")
            gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                audio_path=[REFERENCE_AUDIO_PATH]
            )
            logger.info("✅ Custom speaker embeddings loaded")
        else:
            # For built-in speaker: Generate conditioning latents from silent audio
            logger.info("✅ Using built-in XTTS v2 speaker (generating from test audio)...")
            
            # Create a short silent WAV file
            sample_rate = 22050
            duration = 2.0
            silence = np.zeros(int(sample_rate * duration), dtype=np.float32)
            
            # Save to temporary file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                tmp_path = tmp_file.name
                sf.write(tmp_path, silence, sample_rate)
            
            try:
                # Generate conditioning latents (now using soundfile)
                gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                    audio_path=[tmp_path]
                )
                logger.info("✅ Default speaker embeddings generated")
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed to load XTTS v2: {e}")
        logger.error(traceback.format_exc())
        return False

async def get_livekit_token(identity: str, room_name: str) -> tuple[str, str]:
    """Get LiveKit token from orchestrator"""
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
    """Connect to LiveKit and create audio source"""
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
    TRUE streaming: Publish audio chunks to LiveKit as they're generated
    """
    global livekit_audio_source, livekit_connected
    
    if not livekit_connected or livekit_audio_source is None:
        logger.warning("LiveKit not connected")
        return
    
    first_chunk_time = None
    chunk_count = 0
    
    try:
        # Process each audio chunk as it arrives from XTTS
        for chunk in audio_chunk_generator:
            if first_chunk_time is None:
                first_chunk_time = time.time()
                logger.info(f"⚡ First audio chunk received")
            
            chunk_count += 1
            
            # Convert to numpy if needed
            if torch.is_tensor(chunk):
                chunk = chunk.cpu().numpy()
            
            # Ensure it's 1D
            if len(chunk.shape) > 1:
                chunk = chunk.squeeze()
            
            # Resample to 16kHz if needed
            if sample_rate != 16000:
                from scipy.signal import resample_poly
                chunk = resample_poly(chunk, 16000, sample_rate)
            
            # Publish in 20ms frames (320 samples at 16kHz)
            frame_size = 320
            for offset in range(0, len(chunk), frame_size):
                frame_data = chunk[offset:offset+frame_size]
                if len(frame_data) < frame_size:
                    frame_data = np.pad(frame_data, (0, frame_size-len(frame_data)), 'constant')
                
                pcm_int16 = (np.clip(frame_data, -1, 1) * 32767).astype(np.int16)
                frame = rtc.AudioFrame.create(16000, 1, frame_size)
                np.copyto(np.frombuffer(frame.data, dtype=np.int16), pcm_int16)
                await livekit_audio_source.capture_frame(frame)
        
        logger.info(f"✅ Streamed {chunk_count} chunks to LiveKit")
    except Exception as e:
        logger.error(f"❌ Error streaming audio: {e}")
        logger.error(traceback.format_exc())

@app.on_event("startup")
async def on_startup():
    """Initialize model and LiveKit on startup"""
    logger.info("🚀 Starting XTTS v2 TTS Service...")
    model_loaded = await load_xtts_model()
    if not model_loaded:
        logger.error("Failed to load XTTS model")
        return
    asyncio.create_task(connect_livekit())
    logger.info("✅ XTTS v2 TTS Service ready")

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "model_loaded": xtts_model is not None,
        "livekit_connected": livekit_connected,
        "gpu_available": torch.cuda.is_available(),
        "streaming_enabled": True
    }

@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    """
    Synthesize speech with TRUE streaming using inference_stream()
    """
    start_time = time.time()
    
    try:
        if xtts_model is None:
            raise HTTPException(status_code=503, detail="Model not loaded")
        
        if gpt_cond_latent is None or speaker_embedding is None:
            raise HTTPException(status_code=503, detail="Speaker embeddings not loaded")
        
        logger.info(f"🔊 Synthesizing (streaming): '{request.text[:50]}...'")
        
        # TRUE STREAMING: Use inference_stream() for chunk-by-chunk generation
        audio_chunk_generator = xtts_model.inference_stream(
            text=request.text,
            language=request.language,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            stream_chunk_size=STREAM_CHUNK_SIZE,
            enable_text_splitting=True
        )
        
        # Stream audio chunks to LiveKit as they're generated
        await stream_audio_to_livekit(audio_chunk_generator, sample_rate=24000)
        
        total_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Streaming synthesis completed in {total_time_ms:.0f}ms")
        
        return JSONResponse({
            "status": "success",
            "total_time_ms": round(total_time_ms, 2),
            "room_name": request.room_name,
            "text_length": len(request.text),
            "language": request.language,
            "note": "Audio streamed in real-time to LiveKit",
            "streaming": True
        })
    
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)