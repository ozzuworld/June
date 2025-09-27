from fastapi import APIRouter, HTTPException, status, File, UploadFile, Form
from fastapi.responses import Response
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clone", tags=["Voice Cloning"])

# Import with error handling
try:
    from app.core.openvoice_engine import engine
    ENGINE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"OpenVoice engine not available: {e}")
    ENGINE_AVAILABLE = False
    engine = None

class ErrorResponse(BaseModel):
    detail: str
    error_code: str = "unknown"

async def validate_audio_file(file: UploadFile):
    """Basic audio file validation"""
    if not file.filename:
        raise ValueError("Filename is required")
    
    # Check file extension
    allowed_extensions = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
    extension = "." + file.filename.split('.')[-1].lower()
    if extension not in allowed_extensions:
        raise ValueError(f"Unsupported format. Allowed: {', '.join(allowed_extensions)}")
    
    # Check file size (20MB limit)
    if file.size and file.size > 20 * 1024 * 1024:
        raise ValueError("File too large. Maximum size: 20MB")
    
    return True

@router.post("/voice", response_class=Response)
async def clone_voice(
    reference_audio: UploadFile = File(...),
    text: str = Form(..., min_length=1, max_length=5000),
    language: str = Form(default="EN"),
    speed: float = Form(default=1.0, ge=0.5, le=2.0)
):
    """Clone voice from reference audio and generate speech"""
    
    # Check if engine is available
    if not ENGINE_AVAILABLE or not engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice cloning service is currently unavailable."
        )
    
    try:
        # Validate audio file
        await validate_audio_file(reference_audio)
        
        # Read reference audio
        audio_bytes = await reference_audio.read()
        
        # Generate cloned speech (or fallback to basic TTS)
        cloned_audio = await engine.clone_voice(
            text=text,
            reference_audio_bytes=audio_bytes,
            language=language.upper(),
            speed=speed
        )
        
        return Response(
            content=cloned_audio,
            media_type="audio/wav",
            headers={
                "Content-Disposition": f"attachment; filename=cloned_{reference_audio.filename}",
                "X-Generated-By": "June-TTS"
            }
        )
        
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Voice cloning failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/status")
async def clone_status():
    """Get voice cloning status"""
    converter_available = ENGINE_AVAILABLE and engine and engine.converter is not None
    
    return {
        "voice_cloning_available": converter_available,
        "engine_loaded": ENGINE_AVAILABLE,
        "converter_loaded": converter_available,
        "status": "available" if converter_available else "basic TTS mode",
        "message": (
            "Voice cloning ready" if converter_available 
            else "Basic TTS available - voice cloning models not loaded"
        )
    }
