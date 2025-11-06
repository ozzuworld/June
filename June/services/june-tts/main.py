"""
CosyVoice2 FastAPI TTS Microservice with LiveKit Integration
Provides RESTful endpoints for text-to-speech synthesis and LiveKit streaming

IMPORTANT: This uses CosyVoice2-0.5B which does NOT support inference_sft()
           CosyVoice2 only supports: zero-shot, cross-lingual, and instruct2
"""

import sys
import io
import os
import base64
import argparse
import asyncio
from typing import Optional, Dict
from pathlib import Path
from contextlib import asynccontextmanager

import torch
import torchaudio
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn
import logging
import httpx

# Add third_party/Matcha-TTS to path
sys.path.append('third_party/Matcha-TTS')
from cosyvoice.cli.cosyvoice import CosyVoice2
from cosyvoice.utils.file_utils import load_wav

# Import LiveKit integration
from livekit_publisher import LiveKitTTSPublisher

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== Request/Response Models ==============

class TTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    room_name: str = Field(..., description="LiveKit room name")
    language: str = Field(default="en", description="Language code (en, zh, jp, ko, yue)")
    stream: bool = Field(default=True, description="Enable streaming output")

class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    livekit_connected: bool
    model_type: str
    supported_methods: list

# ============== Global State ==============

cosyvoice_model = None
livekit_publisher: Optional[LiveKitTTSPublisher] = None

# Reference audio for different languages (loaded at startup)
REFERENCE_AUDIO: Dict[str, torch.Tensor] = {}
REFERENCE_TEXT: Dict[str, str] = {}

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
    
    audio = load_wav(temp_path, target_sr)
    return audio

async def synthesize_and_publish(
    text: str,
    room_name: str,
    language: str = "en",
    stream: bool = True,
    prompt_speech: Optional[torch.Tensor] = None,
    prompt_text: str = ""
) -> dict:
    """Synthesize audio using CosyVoice2 and publish to LiveKit room
    
    CosyVoice2 uses zero-shot or cross-lingual synthesis (NOT sft!)
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    if livekit_publisher is None or not livekit_publisher.is_connected:
        raise HTTPException(status_code=503, detail="LiveKit not connected")
    
    try:
        start_time = asyncio.get_event_loop().time()
        
        # Use provided reference audio or default from loaded references
        if prompt_speech is None:
            # Try to get language-specific reference, fallback to English
            ref_key = language if language in REFERENCE_AUDIO else "en"
            if ref_key not in REFERENCE_AUDIO:
                ref_key = list(REFERENCE_AUDIO.keys())[0] if REFERENCE_AUDIO else None
            
            if ref_key:
                prompt_speech = REFERENCE_AUDIO[ref_key]
                prompt_text = REFERENCE_TEXT.get(ref_key, f"Reference for {language}")
            else:
                raise HTTPException(
                    status_code=500, 
                    detail="No reference audio available. CosyVoice2 requires reference audio."
                )
        
        logger.info(f"🎤 Synthesizing: '{text[:50]}...' [lang={language}, stream={stream}]")
        
        # Generate audio using CosyVoice2 zero-shot synthesis
        # NOTE: CosyVoice2 does NOT have inference_sft() - only zero_shot and cross_lingual
        audio_chunks = []
        
        # Use cross-lingual if text has language tags, otherwise zero-shot
        if any(tag in text for tag in ['<|zh|>', '<|en|>', '<|jp|>', '<|yue|>', '<|ko|>']):
            logger.info("   Using cross-lingual synthesis")
            for output in cosyvoice_model.inference_cross_lingual(
                text, 
                prompt_speech, 
                stream=stream
            ):
                audio_chunks.append(output['tts_speech'])
        else:
            logger.info("   Using zero-shot synthesis")
            for output in cosyvoice_model.inference_zero_shot(
                text, 
                prompt_text, 
                prompt_speech, 
                stream=stream
            ):
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
        
        logger.info(f"✅ TTS complete: {audio_duration:.2f}s audio, {synthesis_time*1000:.0f}ms synthesis")
        
        return {
            "status": "success",
            "room_name": room_name,
            "text": text,
            "language": language,
            "audio_duration_seconds": round(audio_duration, 2),
            "synthesis_time_ms": round(synthesis_time * 1000, 2),
            "publish_time_ms": round(publish_time * 1000, 2),
            "total_time_ms": round((synthesis_time + publish_time) * 1000, 2),
            "chunks_sent": len(audio_chunks)
        }
        
    except Exception as e:
        logger.error(f"❌ TTS synthesis/publish failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS failed: {str(e)}")

# ============== Lifespan Management ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    global cosyvoice_model, livekit_publisher, REFERENCE_AUDIO, REFERENCE_TEXT
    
    logger.info("=" * 80)
    logger.info("June TTS Service Starting (CosyVoice2)")
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
        logger.info("   NOTE: CosyVoice2 uses zero-shot/cross-lingual synthesis")
        logger.info("   Does NOT support inference_sft() with predefined speakers")
    except Exception as e:
        logger.error(f"❌ Failed to load model: {e}")
        raise
    
    # Load default reference audio for each language
    try:
        asset_dir = Path("./asset")
        if asset_dir.exists():
            # Try to load reference audio files from CosyVoice repo
            ref_files = {
                "en": ("zero_shot_prompt.wav", "This is an example for zero shot voice cloning"),
                "zh": ("cross_lingual_prompt.wav", "希望你以后能够做的比我还好呦"),
            }
            
            for lang, (filename, text) in ref_files.items():
                file_path = asset_dir / filename
                if file_path.exists():
                    REFERENCE_AUDIO[lang] = load_wav(str(file_path), 16000)
                    REFERENCE_TEXT[lang] = text
                    logger.info(f"   ✅ Loaded reference audio for {lang}: {filename}")
        
        # If no reference audio found, log warning
        if not REFERENCE_AUDIO:
            logger.warning("   ⚠️ No reference audio found in ./asset/ directory")
            logger.warning("   Zero-shot synthesis will require reference audio in API requests")
            logger.warning("   Download reference audio from CosyVoice repo asset/ directory")
    except Exception as e:
        logger.warning(f"⚠️ Could not load reference audio: {e}")
    
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
            
            # Get token from orchestrator
            orchestrator_url = os.getenv("ORCHESTRATOR_URL", "http://june-orchestrator.june-services.svc.cluster.local:8080")
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{orchestrator_url}/token",
                    json={
                        "roomName": livekit_publisher.default_room_name,
                        "participantName": "june-tts"
                    }
                )
                token_data = response.json()
                token = token_data["token"]
                ws_url = token_data.get("livekitUrl", os.getenv("LIVEKIT_WS_URL"))
            
            livekit_publisher.livekit_url = ws_url
            success = await livekit_publisher.connect(token=token)
            
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
    logger.info("June TTS Service Ready (CosyVoice2)")
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
        "model_type": "CosyVoice2-0.5B",
        "supported_methods": ["zero_shot", "cross_lingual", "instruct2"]
    }

@app.get("/stats")
async def get_stats():
    """Get service statistics"""
    stats = {
        "model_loaded": cosyvoice_model is not None,
        "model_type": "CosyVoice2-0.5B",
        "supported_methods": ["zero_shot", "cross_lingual", "instruct2"],
        "note": "CosyVoice2 does NOT support inference_sft - use zero_shot or cross_lingual",
        "livekit_enabled": livekit_publisher is not None,
        "reference_audio_loaded": list(REFERENCE_AUDIO.keys()),
        "available_languages": ["en", "zh", "jp", "ko", "yue"]
    }
    
    if livekit_publisher:
        stats["livekit_stats"] = livekit_publisher.get_stats()
    
    return stats

@app.post("/api/tts/synthesize")
async def synthesize_tts(request: TTSRequest):
    """
    Synthesize text and publish to LiveKit room using CosyVoice2
    
    This is the main endpoint used by the orchestrator for real-time TTS.
    Uses zero-shot or cross-lingual synthesis (NOT sft - that's v1 only).
    """
    return await synthesize_and_publish(
        text=request.text,
        room_name=request.room_name,
        language=request.language,
        stream=request.stream
    )

@app.post("/tts/zero-shot")
async def zero_shot_tts(
    text: str = Form(...),
    prompt_text: str = Form(...),
    prompt_audio: UploadFile = File(...),
    stream: bool = Form(True),
    publish_to_livekit: bool = Form(False),
    room_name: Optional[str] = Form(None)
):
    """Zero-shot voice cloning TTS using CosyVoice2
    
    Provide reference audio and its transcript for voice cloning.
    """
    if cosyvoice_model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    try:
        prompt_speech_16k = load_audio_from_upload(prompt_audio, 16000)
        
        audio_chunks = []
        for output in cosyvoice_model.inference_zero_shot(
            text, 
            prompt_text,
            prompt_speech_16k,
            stream=stream
        ):
            audio_chunks.append(output['tts_speech'])
        
        final_audio = torch.cat(audio_chunks, dim=1)
        
        # Publish to LiveKit if requested
        if publish_to_livekit and room_name and livekit_publisher:
            await livekit_publisher.publish_audio(
                final_audio,
                sample_rate=cosyvoice_model.sample_rate
            )
        
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Zero-shot TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate,
            "published_to_livekit": publish_to_livekit and room_name is not None
        }
        
    except Exception as e:
        logger.error(f"Zero-shot TTS failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/cross-lingual")
async def cross_lingual_tts(
    text: str = Form(...),
    prompt_audio: UploadFile = File(...),
    stream: bool = Form(True),
    publish_to_livekit: bool = Form(False),
    room_name: Optional[str] = Form(None)
):
    """Cross-lingual TTS using CosyVoice2
    
    Use language tags in text: <|zh|> <|en|> <|jp|> <|yue|> <|ko|>
    Example: "<|en|>Hello<|zh|>你好<|en|>World"
    """
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
        
        # Publish to LiveKit if requested
        if publish_to_livekit and room_name and livekit_publisher:
            await livekit_publisher.publish_audio(
                final_audio,
                sample_rate=cosyvoice_model.sample_rate
            )
        
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Cross-lingual TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate,
            "published_to_livekit": publish_to_livekit and room_name is not None
        }
        
    except Exception as e:
        logger.error(f"Cross-lingual TTS failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

@app.post("/tts/instruct")
async def instruct_tts(
    text: str = Form(...),
    instruct_text: str = Form(...),
    prompt_audio: UploadFile = File(...),
    stream: bool = Form(True),
    publish_to_livekit: bool = Form(False),
    room_name: Optional[str] = Form(None)
):
    """Instruct-based TTS with style control using CosyVoice2
    
    Use natural language instructions to control speech characteristics.
    Example instruct_text: "Speak in a calm and soothing voice"
    """
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
        
        # Publish to LiveKit if requested
        if publish_to_livekit and room_name and livekit_publisher:
            await livekit_publisher.publish_audio(
                final_audio,
                sample_rate=cosyvoice_model.sample_rate
            )
        
        audio_b64 = audio_to_base64(final_audio, cosyvoice_model.sample_rate)
        
        return {
            "message": "Instruct TTS completed successfully",
            "audio_base64": audio_b64,
            "sample_rate": cosyvoice_model.sample_rate,
            "duration_seconds": final_audio.shape[1] / cosyvoice_model.sample_rate,
            "published_to_livekit": publish_to_livekit and room_name is not None
        }
        
    except Exception as e:
        logger.error(f"Instruct TTS failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {str(e)}")

# ============== Main ==============

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000, help='Server port')
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
