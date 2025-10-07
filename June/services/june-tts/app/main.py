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

from app.core import f5tts_engine
from app.core.config import settings

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
    logger.info("🚀 Starting June TTS Service (F5-TTS)")
    
    # Warmup models at startup
    try:
        f5tts_engine.warmup_models()
        logger.info("✅ F5-TTS models loaded successfully")
    except Exception as e:
        logger.error(f"⚠️ F5-TTS warmup failed: {e}")
        # Don't crash the service, let it start anyway
    
    yield
    
    logger.info("🛑 Shutting down June TTS Service")

# Create FastAPI app
app = FastAPI(
    title="June TTS Service",
    description="State-of-the-art Text-to-Speech with F5-TTS voice cloning",
    version="4.0.0",
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

# Pydantic models
class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    voice: str = Field(default="default")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    language: str = Field(default="en")
    format: str = Field(default="wav")

# Health endpoints
@app.get("/healthz")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "june-tts",
        "version": "4.0.0",
        "engine": "F5-TTS"
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "June TTS Service",
        "version": "4.0.0",
        "engine": "F5-TTS v1.1.9",
        "features": {
            "voice_cloning": True,
            "multilingual": True,
            "zero_shot": True,
            "real_time": True
        },
        "endpoints": {
            "health": "/healthz",
            "tts": "/v1/tts",
            "clone": "/v1/clone",
            "voices": "/v1/voices",
            "status": "/v1/status"
        }
    }

# TTS endpoints
@app.post("/v1/tts")
async def text_to_speech(request: TTSRequest):
    """Standard text-to-speech synthesis"""
    try:
        logger.info(f"🔊 TTS request: {request.text[:50]}...")
        
        audio_bytes = await f5tts_engine.synthesize_tts(
            text=request.text,
            language=request.language,
            speed=request.speed
        )
        
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=f5tts_speech.wav",
                "X-Engine": "F5-TTS",
                "X-Language": request.language,
                "X-Speed": str(request.speed)
            }
        )
    
    except Exception as e:
        logger.error(f"❌ TTS synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")

@app.post("/v1/clone")
async def clone_voice_endpoint(
    text: str = Form(..., max_length=MAX_TEXT_LENGTH),
    language: str = Form(default="en"),
    speed: float = Form(default=1.0, ge=0.5, le=2.0),
    reference_text: str = Form(default=""),
    reference_audio: UploadFile = File(...)
):
    """Voice cloning endpoint"""
    try:
        # Validate file
        if not reference_audio.content_type or not reference_audio.content_type.startswith("audio/"):
            raise HTTPException(status_code=400, detail="File must be an audio file")
        
        # Read file
        content = await reference_audio.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"File too large. Max: {MAX_FILE_SIZE//1024//1024}MB")
        
        if len(content) < 1000:
            raise HTTPException(status_code=400, detail="Audio file too small")
        
        logger.info(f"🎭 Voice cloning request: {text[:50]}...")
        
        # Generate cloned audio
        audio_bytes = await f5tts_engine.clone_voice(
            text=text,
            reference_audio_bytes=content,
            language=language,
            speed=speed,
            reference_text=reference_text
        )
        
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f"attachment; filename=f5tts_cloned_{reference_audio.filename}",
                "X-Engine": "F5-TTS",
                "X-Language": language,
                "X-Speed": str(speed),
                "X-Cloned": "true"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice cloning failed: {e}")
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {str(e)}")

@app.get("/v1/voices")
async def list_voices():
    """Get voice capabilities"""
    return f5tts_engine.get_available_speakers()

@app.get("/v1/status")
async def service_status():
    """Service status"""
    return {
        "service": "june-tts",
        "status": "operational",
        "engine": "F5-TTS v1.1.9",
        "version": "4.0.0",
        "device": f5tts_engine._device or "unknown",
        "supported_languages": len(f5tts_engine.get_supported_languages()),
        "features": {
            "voice_cloning": True,
            "zero_shot": True,
            "multilingual": True,
            "real_time": True
        },
        "limits": {
            "max_text_length": MAX_TEXT_LENGTH,
            "max_file_size_mb": MAX_FILE_SIZE // 1024 // 1024,
            "speed_range": "0.5 - 2.0x"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
