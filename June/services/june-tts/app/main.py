"""
June TTS Service - CORRECTED Main Application
OpenVoice V2 Implementation
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import f5tts_engine as openvoice_engine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info("🚀 Starting June TTS Service (OpenVoice V2)")
    
    # Warmup models at startup
    try:
        openvoice_engine.warmup_models()
        logger.info("✅ Models loaded successfully")
    except Exception as e:
        logger.error(f"⚠️ Model warmup failed: {e}")
        logger.warning("Service will start but models will load on first request")
    
    yield
    
    logger.info("🛑 Shutting down June TTS Service")


# Create FastAPI app
app = FastAPI(
    title="June TTS Service",
    description="Text-to-Speech service using OpenVoice V2",
    version="2.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Health Check Endpoints =====

@app.get("/healthz")
async def health_check():
    """Health check endpoint for Kubernetes"""
    return {
        "status": "healthy",
        "service": "june-tts",
        "version": "2.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "June TTS Service",
        "version": "2.0.0",
        "engine": "OpenVoice V2",
        "supported_languages": openvoice_engine.get_supported_languages(),
        "endpoints": {
            "health": "/healthz",
            "tts": "/v1/tts",
            "voices": "/v1/voices",
            "clone": "/v1/clone"
        }
    }


# ===== TTS Endpoints =====

from fastapi import HTTPException, File, UploadFile, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field


class TTSRequest(BaseModel):
    """Standard TTS request"""
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = Field(default="default")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    language: str = Field(default="EN")
    format: str = Field(default="wav")


@app.post("/v1/tts")
async def synthesize_speech(request: TTSRequest):
    """
    Standard text-to-speech synthesis
    Uses base MeloTTS without voice cloning
    """
    try:
        # Validate language
        if request.language.upper() not in openvoice_engine.get_supported_languages():
            raise HTTPException(
                status_code=400,
                detail=f"Language '{request.language}' not supported. "
                       f"Supported: {openvoice_engine.get_supported_languages()}"
            )
        
        # Generate audio
        audio_bytes = await openvoice_engine.synthesize_tts(
            text=request.text,
            language=request.language.upper(),
            speed=request.speed,
            speaker_id=0
        )
        
        # Return audio
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=speech.wav",
                "X-Voice": request.voice,
                "X-Language": request.language,
                "X-Speed": str(request.speed)
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

@app.post("/v1/clone")
async def clone_voice_endpoint(
    text: str = Form(...),
    language: str = Form(default="en"),
    speed: float = Form(default=1.0),
    reference_text: str = Form(default=""),  # New: F5-TTS specific
    reference_audio: UploadFile = File(...)
):
    """
    Enhanced voice cloning with F5-TTS
    Supports reference text for better quality
    """
    try:
        # Validate file
        if not reference_audio.content_type or \
           not reference_audio.content_type.startswith("audio/"):
            raise HTTPException(
                status_code=400,
                detail="File must be an audio file"
            )
        
        # Read reference audio
        reference_bytes = await reference_audio.read()
        
        # Generate cloned audio with F5-TTS
        audio_bytes = await openvoice_engine.clone_voice(
            text=text,
            reference_audio_bytes=reference_bytes,
            language=language.lower(),
            speed=speed,
            reference_text=reference_text  # F5-TTS enhancement
        )
        
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f"attachment; filename=f5tts_cloned_{reference_audio.filename}",
                "X-Language": language,
                "X-Speed": str(speed),
                "X-Engine": "F5-TTS",
                "X-Cloned": "true"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"F5-TTS voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")


@app.get("/v1/voices")
async def list_voices(language: str = "EN"):
    """
    List available voices/speakers
    """
    try:
        speakers = openvoice_engine.get_available_speakers(language.upper())
        
        return {
            "language": speakers["language"],
            "speakers": speakers["speakers"],
            "supported_languages": openvoice_engine.get_supported_languages()
        }
    
    except Exception as e:
        logger.error(f"Failed to list voices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/status")
async def service_status():
    """
    Service status and capabilities
    """
    return {
        "service": "june-tts",
        "status": "operational",
        "engine": "OpenVoice V2 + MeloTTS",
        "version": "2.0.0",
        "supported_languages": openvoice_engine.get_supported_languages(),
        "features": {
            "standard_tts": True,
            "voice_cloning": True,
            "multi_language": True,
            "speed_control": True
        },
        "supported_formats": ["wav"]
    }


# Entry point for uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        log_level="info"
    )