"""
June TTS Service - F5-TTS Implementation
State-of-the-art voice cloning and synthesis
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core import f5tts_engine as openvoice_engine
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# File size constant
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info("🚀 Starting June TTS Service (F5-TTS)")
    
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
    description="Text-to-Speech service using F5-TTS",
    version="3.0.0",
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
        "version": "3.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "June TTS Service",
        "version": "3.0.0",
        "engine": "F5-TTS",
        "supported_languages": openvoice_engine.get_supported_languages()[:10],  # Show first 10
        "total_languages": len(openvoice_engine.get_supported_languages()),
        "endpoints": {
            "health": "/healthz",
            "tts": "/v1/tts",
            "voices": "/v1/voices",
            "clone": "/v1/clone",
            "status": "/v1/status"
        }
    }


# ===== Pydantic Models =====

class TTSRequest(BaseModel):
    """Standard TTS request"""
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = Field(default="default")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    language: str = Field(default="en")
    format: str = Field(default="wav")


# ===== TTS Endpoints =====

@app.post("/v1/tts")
async def synthesize_speech(request: TTSRequest):
    """
    Standard text-to-speech synthesis using F5-TTS
    """
    try:
        # Validate language
        supported_langs = openvoice_engine.get_supported_languages()
        if request.language.lower() not in supported_langs:
            raise HTTPException(
                status_code=400,
                detail=f"Language '{request.language}' not supported. "
                       f"Supported languages: {len(supported_langs)} total"
            )
        
        # Generate audio with F5-TTS
        audio_bytes = await openvoice_engine.synthesize_tts(
            text=request.text,
            language=request.language.lower(),
            speed=request.speed
        )
        
        # Return audio
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=f5tts_speech.wav",
                "X-Voice": request.voice,
                "X-Language": request.language,
                "X-Speed": str(request.speed),
                "X-Engine": "F5-TTS"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"F5-TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")


@app.post("/v1/clone")
async def clone_voice_endpoint(
    text: str = Form(...),
    language: str = Form(default="en"),
    speed: float = Form(default=1.0),
    reference_text: str = Form(default=""),
    reference_audio: UploadFile = File(...)
):
    """
    Voice cloning endpoint using F5-TTS
    Supports reference text for improved quality
    """
    try:
        # Validate file type
        if not reference_audio.content_type or \
           not reference_audio.content_type.startswith("audio/"):
            raise HTTPException(
                status_code=400,
                detail="File must be an audio file"
            )
        
        # Read and validate file size
        content = await reference_audio.read()
        file_size = len(content)
        
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {MAX_FILE_SIZE / (1024*1024):.1f}MB"
            )
        
        if file_size < 1000:  # Less than 1KB
            raise HTTPException(
                status_code=400,
                detail="Audio file too small. Please upload a valid audio file."
            )
        
        # Validate language
        supported_langs = openvoice_engine.get_supported_languages()
        if language.lower() not in supported_langs:
            raise HTTPException(
                status_code=400,
                detail=f"Language '{language}' not supported"
            )
        
        # Generate cloned audio with F5-TTS
        audio_bytes = await openvoice_engine.clone_voice(
            text=text,
            reference_audio_bytes=content,
            language=language.lower(),
            speed=speed,
            reference_text=reference_text
        )
        
        # Return cloned audio
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f"attachment; filename=f5tts_cloned_{reference_audio.filename}",
                "X-Language": language,
                "X-Speed": str(speed),
                "X-Engine": "F5-TTS",
                "X-Cloned": "true",
                "X-Reference-Text": "provided" if reference_text.strip() else "auto"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"F5-TTS voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")


@app.get("/v1/voices")
async def list_voices(language: str = "en"):
    """
    List available voices/speakers for F5-TTS
    """
    try:
        speakers = openvoice_engine.get_available_speakers()
        
        return {
            "engine": "F5-TTS",
            "voice_cloning": speakers["message"],
            "supported_languages": len(speakers["supported_languages"]),
            "languages_sample": speakers["supported_languages"][:20],  # Show first 20
            "recommendation": speakers["reference_text"],
            "file_requirements": {
                "format": "wav, mp3, flac, m4a",
                "duration": "3-30 seconds recommended",
                "quality": "clear speech, minimal background noise",
                "size_limit": f"{MAX_FILE_SIZE / (1024*1024):.1f}MB"
            }
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
        "engine": "F5-TTS",
        "version": "3.0.0",
        "supported_languages": len(openvoice_engine.get_supported_languages()),
        "features": {
            "standard_tts": True,
            "voice_cloning": True,
            "zero_shot_cloning": True,
            "multi_language": True,
            "speed_control": True,
            "reference_text": True
        },
        "supported_formats": ["wav"],
        "limits": {
            "max_text_length": 5000,
            "max_file_size_mb": MAX_FILE_SIZE / (1024*1024),
            "speed_range": "0.5 - 2.0x"
        }
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
