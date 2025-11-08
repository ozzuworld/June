#!/usr/bin/env python3
"""
XTTS v2 TTS Service - Streaming Real-Time Voice Synthesis
FastAPI server for Coqui XTTS v2 with LiveKit integration
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional
import traceback

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts
from livekit import rtc

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
LIVEKIT_IDENTITY = os.getenv("LIVEKIT_IDENTITY", "june-tts-xtts")
LIVEKIT_ROOM_NAME = os.getenv("LIVEKIT_ROOM", "ozzu-main")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "https://api.ozzu.world")
REFERENCE_AUDIO_PATH = os.getenv("REFERENCE_AUDIO", "/app/references/default_voice.wav")

app = FastAPI(
    title="June TTS (XTTS v2)",
    version="2.0.0",
    description="Real-time streaming TTS with Coqui XTTS v2 and LiveKit integration"
)

# Global model and LiveKit connection
xtts_model: Optional[Xtts] = None
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


async def load_xtts_model():
    """Load XTTS v2 model and prepare speaker embeddings"""
    global xtts_model, gpt_cond_latent, speaker_embedding
    
    try:
        logger.info("🔊 Loading XTTS v2 model...")
        
        # Initialize XTTS model
        config = XttsConfig()
        model_path = "tts_models/multilingual/multi-dataset/xtts_v2"
        xtts_model = Xtts.init_from_config(config)
        
        # Load checkpoint
        xtts_model.load_checkpoint(
            config,
            checkpoint_dir=str(Path.home() / ".local/share/tts/tts_models--multilingual--multi-dataset--xtts_v2"),
            use_deepspeed=False
        )
        
        # Move to GPU if available
        if torch.cuda.is_available():
            xtts_model.cuda()
            logger.info("✅ XTTS v2 loaded on GPU")
        else:
            logger.warning("⚠️ XTTS v2 loaded on CPU (slow)")
        
        # Load default speaker embeddings
        if os.path.exists(REFERENCE_AUDIO_PATH):
            logger.info(f"Loading reference voice from {REFERENCE_AUDIO_PATH}")
            gpt_cond_latent, speaker_embedding = xtts_model.get_conditioning_latents(
                audio_path=[REFERENCE_AUDIO_PATH]
            )
            logger.info("✅ Speaker embeddings loaded")
        else:
            logger.warning(f"⚠️ Reference audio not found at {REFERENCE_AUDIO_PATH}")
        
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
            raise RuntimeError(f"Missing livekitUrl in response: {data}")
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


async def publish_audio_streaming(audio_generator, sample_rate: int = 24000):
    """
    Publish audio chunks to LiveKit as they're generated (streaming)
    """
    global livekit_audio_source, livekit_connected
    
    if not livekit_connected or livekit_audio_source is None:
        logger.warning("LiveKit not connected")
        return
    
    frame_size = int(sample_rate * 0.02)  # 20ms frames
    
    try:
        for audio_chunk in audio_generator:
            # Convert to 16kHz if needed
            if sample_rate != 16000:
                from scipy.signal import resample_poly
                audio_chunk = resample_poly(audio_chunk, 16000, sample_rate)
            
            # Publish in 20ms frames
            for offset in range(0, len(audio_chunk), frame_size):
                frame_data = audio_chunk[offset:offset+frame_size]
                if len(frame_data) < frame_size:
                    frame_data = np.pad(frame_data, (0, frame_size-len(frame_data)), 'constant')
                
                pcm_int16 = (np.clip(frame_data, -1, 1) * 32767).astype(np.int16)
                frame = rtc.AudioFrame.create(16000, 1, frame_size)
                np.copyto(np.frombuffer(frame.data, dtype=np.int16), pcm_int16)
                await livekit_audio_source.capture_frame(frame)
        
        logger.info("✅ Streaming audio published to LiveKit")
    except Exception as e:
        logger.error(f"❌ Error publishing audio: {e}")


@app.on_event("startup")
async def on_startup():
    """Initialize model and LiveKit on startup"""
    logger.info("🚀 Starting XTTS v2 TTS Service...")
    
    # Load XTTS model
    model_loaded = await load_xtts_model()
    if not model_loaded:
        logger.error("Failed to load XTTS model")
        return
    
    # Connect to LiveKit
    asyncio.create_task(connect_livekit())
    
    logger.info("✅ XTTS v2 TTS Service ready")


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "model_loaded": xtts_model is not None,
        "livekit_connected": livekit_connected,
        "gpu_available": torch.cuda.is_available()
    }


@app.post("/api/tts/synthesize")
async def synthesize_speech(request: SynthesizeRequest):
    """
    Synthesize speech using XTTS v2 with streaming
    """
    start_time = time.time()
    
    try:
        if xtts_model is None:
            raise HTTPException(status_code=503, detail="Model not loaded")
        
        if gpt_cond_latent is None or speaker_embedding is None:
            raise HTTPException(status_code=503, detail="Speaker embeddings not loaded")
        
        logger.info(f"🔊 Synthesizing: '{request.text[:50]}...'")
        
        # Generate audio with streaming
        audio_generator = xtts_model.inference_stream(
            text=request.text,
            language=request.language,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            stream_chunk_size=20,  # Stream in 20-token chunks
            enable_text_splitting=True
        )
        
        # Publish audio chunks as they're generated
        await publish_audio_streaming(audio_generator, sample_rate=24000)
        
        total_time_ms = (time.time() - start_time) * 1000
        logger.info(f"✅ Synthesis completed in {total_time_ms:.0f}ms (streaming)")
        
        return JSONResponse({
            "status": "success",
            "total_time_ms": round(total_time_ms, 2),
            "room_name": request.room_name,
            "text_length": len(request.text),
            "language": request.language,
            "note": "Audio streamed to LiveKit in real-time"
        })
    
    except Exception as e:
        logger.error(f"❌ Synthesis error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)