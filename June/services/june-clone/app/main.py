"""
June Voice Cloning Service - F5-TTS Implementation
Dedicated voice cloning with zero-shot capabilities
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.core import f5_engine
from app.core.config import settings
from app.models.requests import VoiceCloneRequest

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_TEXT_LENGTH = 1000

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info("🎭 Starting June Voice Cloning Service")
    
    # Warmup F5-TTS models
    try:
        f5tts_engine.warmup_models()
        logger.info("✅ F5-TTS voice cloning models loaded successfully")
    except Exception as e:
        logger.error(f"⚠️ F5-TTS warmup failed: {e}")
    
    yield
    
    logger.info("🛑 Shutting down June Voice Cloning Service")

# Create FastAPI app
app = FastAPI(
    title="June Voice Cloning Service",
    description="Zero-shot voice cloning powered by F5-TTS",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health endpoints
@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-voice-cloning",
        "version": "1.0.0",
        "engine": "F5-TTS"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "June Voice Cloning Service",
        "version": "1.0.0",
        "engine": "F5-TTS v1.1.9",
        "description": "Zero-shot voice cloning with reference audio",
        "features": {
            "voice_cloning": True,
            "zero_shot": True,
            "multilingual": True,
            "real_time": True
        },
        "endpoints": {
            "health": "/healthz",
            "clone": "/v1/clone",
            "voices": "/v1/voices",
            "status": "/v1/status"
        },
        "usage": {
            "reference_audio": "Upload 3-15 second clear speech sample",
            "reference_text": "Accurate transcription improves quality",
            "supported_formats": ["wav", "mp3", "m4a", "flac"]
        }
    }

@app.post("/v1/clone")
async def clone_voice_endpoint(
    text: str = Form(..., max_length=MAX_TEXT_LENGTH, description="Text to synthesize"),
    language: str = Form(default="en", description="Language code (en, es, fr, etc.)"),
    speed: float = Form(default=1.0, ge=0.5, le=2.0, description="Speech speed multiplier"),
    reference_text: str = Form(default="", description="Transcription of reference audio"),
    reference_audio: UploadFile = File(..., description="Reference audio file (3-15 seconds)")
):
    """
    Clone voice using reference audio sample
    
    - **text**: Text to synthesize in the cloned voice
    - **language**: Language code (en, es, fr, de, etc.)
    - **speed**: Speech speed (0.5-2.0x)
    - **reference_text**: Accurate transcription of reference audio (improves quality)
    - **reference_audio**: Clear speech sample (3-15 seconds, WAV/MP3/etc.)
    """
    try:
        # Validate file type
        if not reference_audio.content_type or not reference_audio.content_type.startswith("audio/"):
            raise HTTPException(status_code=400, detail="File must be an audio file")
        
        # Read and validate file size
        content = await reference_audio.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413, 
                detail=f"File too large. Maximum: {MAX_FILE_SIZE//1024//1024}MB"
            )
        
        if len(content) < 1000:
            raise HTTPException(status_code=400, detail="Audio file too small (minimum ~1KB)")
        
        logger.info(f"🎭 Voice cloning request: '{text[:50]}...' (lang: {language}, speed: {speed}x)")
        logger.info(f"📁 Reference audio: {reference_audio.filename} ({len(content):,} bytes)")
        
        # Generate cloned voice
        audio_bytes = await f5tts_engine.clone_voice(
            text=text,
            reference_audio_bytes=content,
            language=language,
            speed=speed,
            reference_text=reference_text or "This is reference audio for voice cloning."
        )
        
        # Generate filename
        safe_filename = f"cloned_{reference_audio.filename or 'voice'}.wav"
        
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f"attachment; filename={safe_filename}",
                "X-Service": "june-voice-cloning",
                "X-Engine": "F5-TTS",
                "X-Language": language,
                "X-Speed": str(speed),
                "X-Cloned": "true",
                "X-Audio-Length": str(len(audio_bytes))
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")

@app.get("/v1/voices")
async def get_voice_capabilities():
    """Get voice cloning capabilities and information"""
    return f5tts_engine.get_available_speakers()

@app.get("/v1/status")
async def service_status():
    """Voice cloning service status"""
    try:
        return {
            "service": "june-voice-cloning",
            "status": "operational",
            "engine": "F5-TTS v1.1.9",
            "version": "1.0.0",
            "device": "cuda" if f5tts_engine.is_gpu_available() else "cpu",
            "supported_languages": f5tts_engine.get_supported_languages(),
            "capabilities": {
                "zero_shot_cloning": True,
                "multilingual": True,
                "real_time": True,
                "high_quality": True
            },
            "limits": {
                "max_text_length": MAX_TEXT_LENGTH,
                "max_file_size_mb": MAX_FILE_SIZE // 1024 // 1024,
                "speed_range": "0.5 - 2.0x",
                "recommended_audio_length": "3-15 seconds"
            },
            "performance": {
                "typical_inference_time": "1-3 seconds",
                "gpu_accelerated": f5tts_engine.is_gpu_available()
            }
        }
    except Exception as e:
        logger.error(f"❌ Status check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
