"""
CosyVoice2 FastAPI TTS Microservice with LiveKit Integration
Provides RESTful endpoints for text-to-speech synthesis and LiveKit streaming
"""

import sys
import io
import os
import base64
import argparse
import asyncio
from typing import Optional, List
from pathlib import Path
from contextlib import asynccontextmanager

import torch
import torchaudio
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn
import logging

# Add third_party/Matcha-TTS to path
sys.path.append('third_party/Matcha-TTS')
from cosyvoice.cli.cosyvoice import CosyVoice2
from cosyvoice.utils.file_utils import load_wav

# Import LiveKit integration
from livekit_publisher import LiveKitTTSPublisher

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== Request/Response Models ==============

class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    stream: bool = Field(default=False, description="Enable streaming output")
    publish_to_livekit: bool = Field(default=False, description="Publish to LiveKit room")
    room_name: Optional[str] = Field(None, description="LiveKit room name (if publishing)")

class SFTRequest(TTSRequest):
    speaker: str = Field("中文女", description="Speaker name from available SFT speakers")

class LiveKitPublishRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    room_name: str = Field(..., description="LiveKit room name")
    speaker: str = Field("英文女", description="Speaker name")
    language: str = Field("en", description="Language code")

class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    livekit_connected: bool
    available_speakers: List[str]

# ============== Global State ==============

cosyvoice_model = None
livekit_publisher: Optional[LiveKitTTSPublisher] = None

# ============== Helper Functions ==============

def audio_to_base64(audio_tensor: torch.Tensor, sample_rate: int) -> str:
    """Convert audio tensor to base64 encoded WAV"""
    buffer = io.BytesIO()
    torchaudio.save(buffer, audio_tensor, sample_rate, format="wav")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')

def load_audio_from_upload(audio_file: UploadFile, target_sr: int = 16000) -> torch.Tensor:
    """Load audio from uploaded file"""
    temp_path = f"/tmp/{audio_file.filename}"
    with open(temp_path, "wb") as f:
        f.write(audio_file.file.read())
    
    audio, sr = torchaudio.load(temp_path)
    if sr != target_sr:
        resampler = torchaudio.transforms.Resample(sr, target_sr)
        audio = resampler(audio)
    
    return audio

async def synthesize_and_publish(
    text: str,
    room_name: str,
    speaker: str = "英文女",
    stream: bool = False
) -> dict:
    """Synthesize audio and publish to LiveKit room"""
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    if livekit_publisher is None or not livekit_publisher.is_connected:
        raise HTTPException(status_code=503, detail="LiveKit not connected")
    
    try:
        start_time = asyncio.get_event_loop().time()
        
        # Generate audio using SFT mode
        audio_chunks = []
        for output in cosyvoice_model.inference_sft(text, speaker, stream=stream):
            audio_chunks.append(output['tts_speech'])
        
        # Concatenate chunks
        final_audio = torch.cat(audio_chunks, dim=1)
        
        synthesis_time = asyncio.get_event_loop().time() - start_time
        
        # Publish to LiveKit
        publish_start = asyncio.get_event_loop().time()
        success = await livekit_publisher.publish_audio(
            final_audio,
            sample_rate=cosyvoice_model.sample_rate
        )
        publish_time = asyncio.get_event_loop().time() - publish_start
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to publish to LiveKit")
        
        audio_duration = final_audio.shape[1] / cosyvoice_model.sample_rate
        
        return {
            "status": "success",
            "room_name": room_name,
            "text": text,
            "speaker": speaker,
            "audio_duration_seconds": round(audio_duration, 2),
            "synthesis_time_ms": round(synthesis_time * 1000, 2),
            "publish_time_ms": round(publish_time * 1000, 2),
            "total_time_ms": round((synthesis_time + publish_time) * 1000, 2),
            "chunks_sent": len(audio_chunks)
        }
        
    except Exception as e:
        logger.error(f"TTS synthesis/publish failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS failed: {str(e)}")

# ============== Lifespan Management ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    global cosyvoice_model, livekit_publisher
    
    logger.info("=" * 80)
    logger.info("June TTS Service Starting")
    logger.info("=" * 80)
    
    # Load CosyVoice2 model
    try:
        model_dir = os.getenv("MODEL_DIR", "pretrained_models/CosyVoice2-0.5B")
        logger.info(f"Loading CosyVoice2 model from {model_dir}...")
        
        cosyvoice_model = CosyVoice2(
            model_dir,
            load_jit=False,
            load_trt=False,
            load_vllm=False,
            fp16=True
        )
        logger.info("✅ CosyVoice2 model loaded")
        logger.info(f"   Available speakers: {cosyvoice_model.list_available_spks()}")
    except Exception as e:
        logger.error(f"❌ Failed to load model: {e}")
        raise
    
    # Initialize LiveKit publisher
    livekit_enabled = os.getenv("LIVEKIT_ENABLED", "true").lower() == "true"
    
    if livekit_enabled:
        try:
            logger.info("Initializing LiveKit publisher...")
            
            livekit_publisher = LiveKitTTSPublisher(
                livekit_url=os.getenv("LIVEKIT_WS_URL", "wss://livekit.ozzu.world"),
                api_key=os.getenv("LIVEKIT_API_KEY", "devkey"),
                api_secret=os.getenv("LIVEKIT_API_SECRET", "secret"),
                room_name=os.getenv("LIVEKIT_ROOM_NAME", "ozzu-main"),
                participant_name="june-tts"
            )
            
            # Connect to LiveKit
            success = await livekit_publisher.connect()
            
            if success:
                logger.info("✅ LiveKit connected")
            else:
                logger.warning("⚠️ LiveKit connection failed, running in API-only mode")
                livekit_publisher = None
                
        except Exception as e:
            logger.error(f"❌ LiveKit initialization failed: {e}")
            livekit_publisher = None
    else:
        logger.info("LiveKit disabled, running in API-only mode")
    
    logger.info("=" * 80)
    logger.info("June TTS Service Ready")
    logger.info("=" * 80)
    
    yield
    
    # Shutdown
    logger.info("Shutting down June TTS Service...")
    
    if livekit_publisher:
        await livekit_publisher.disconnect()
    
    logger.info("Shutdown complete")

# ============== Initialize FastAPI App ==============

app = FastAPI(
    title="June TTS API",
    description="Multi-lingual Text-to-Speech API using CosyVoice2-0.5B with LiveKit streaming",
    version="2.0.0",
    lifespan=lifespan
)

# ============== API Endpoints ==============

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy" if cosyvoice_model is not None else "model_not_loaded",
        "model_loaded": cosyvoice_model is not None,
        "livekit_connected": livekit_publisher is not None and livekit_publisher.is_connected,
        "available_speakers": cosyvoice_model.list_available_spks() if cosyvoice_model else []
    }

@app.get("/speakers")
async def list_speakers():
    """List available SFT speakers"""
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    return {
        "speakers": cosyvoice_model.list_available_spks(),
        "count": len(cosyvoice_model.list_available_spks())
    }

@app.get("/stats")
async def get_stats():
    """Get service statistics"""
    stats = {
        "model_loaded": cosyvoice_model is not None,
        "livekit_enabled": livekit_publisher is not None,
    }
    
    if livekit_publisher:
        stats["livekit_stats"] = livekit_publisher.get_stats()
    
    return stats

@app.post("/api/tts/synthesize")
async def synthesize_tts(request: LiveKitPublishRequest):
    """
    Synthesize text and publish to LiveKit room
    
    This is the main endpoint used by the orchestrator for real-time TTS
    """
    return await synthesize_and_publish(
        text=request.text,
        room_name=request.room_name,
        speaker=request.speaker,
        stream=True
    )

@app.post("/tts/sft")
async def sft_tts(
    text: str = Form(...),
    speaker: str = Form("英文女"),
    stream: bool = Form(False),
    publish_to_livekit: bool = Form(False),
    room_name: Optional[str] = Form(None)
):
    """
    Supervised Fine-Tuned (SFT) TTS with preset speakers
    
    - Use pre-trained speaker voices
    - Optionally publish to LiveKit room
    - Get list of available speakers from /speakers endpoint
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Generate audio
        audio_chunks = []
        for output in cosyvoice_model.inference_sft(text, speaker, stream=stream):
            audio_chunks.append(output['tts_speech'])
        
        final_audio = torch.cat(audio_chunks, dim=1)
        
        # Publish to LiveKit if requested
        if publish_to_livekit and room_name:
            if livekit_publisher and livekit_publisher.is_connected:
                await livekit_publisher.publish_audio(
                    final_audio,
                    sample_rate=cosyvoice_model.sample_rate
                )
        
        # Convert to base64 for response
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "SFT TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate,
            "published_to_livekit": publish_to_livekit and room_name is not None
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/zero-shot")
async def zero_shot_tts(
    text: str = Form(...),
    prompt_text: str = Form(...),
    prompt_audio: UploadFile = File(...),
    zero_shot_spk_id: Optional[str] = Form(None),
    stream: bool = Form(False)
):
    """Zero-shot voice cloning TTS"""
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        # Load prompt audio
        if not zero_shot_spk_id:
            prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        else:
            prompt_speech_16k = torch.tensor([])
        
        # Generate audio
        audio_chunks = []
        for output in cosyvoice_model.inference_zero_shot(
            text, 
            prompt_text if not zero_shot_spk_id else '',
            prompt_speech_16k if not zero_shot_spk_id else '',
            zero_shot_spk_id=zero_shot_spk_id,
            stream=stream
        ):
            audio_chunks.append(output['tts_speech'])
        
        final_audio = torch.cat(audio_chunks, dim=1)
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Zero-shot TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/cross-lingual")
async def cross_lingual_tts(
    text: str = Form(...),
    prompt_audio: UploadFile = File(...),
    stream: bool = Form(False)
):
    """Cross-lingual TTS"""
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        
        audio_chunks = []
        for output in cosyvoice_model.inference_cross_lingual(
            text,
            prompt_speech_16k,
            stream=stream
        ):
            audio_chunks.append(output['tts_speech'])
        
        final_audio = torch.cat(audio_chunks, dim=1)
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Cross-lingual TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/instruct")
async def instruct_tts(
    text: str = Form(...),
    instruct_text: str = Form(...),
    prompt_audio: UploadFile = File(...),
    stream: bool = Form(False)
):
    """Instruct-based TTS with style control"""
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        
        audio_chunks = []
        for output in cosyvoice_model.inference_instruct2(
            text,
            instruct_text,
            prompt_speech_16k,
            stream=stream
        ):
            audio_chunks.append(output['tts_speech'])
        
        final_audio = torch.cat(audio_chunks, dim=1)
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Instruct TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

# ============== Main ==============

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=50000, help='Server port')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Server host')
    parser.add_argument('--model_dir', type=str, 
                       default='pretrained_models/CosyVoice2-0.5B',
                       help='Path to model directory')
    
    args = parser.parse_args()
    
    # Set model directory in environment
    os.environ["MODEL_DIR"] = args.model_dir
    
    uvicorn.run(
        app, 
        host=args.host, 
        port=args.port,
        log_level="info"
    )