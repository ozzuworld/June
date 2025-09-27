# June/services/june-tts/app/routers/standard_tts.py
# Standard TTS endpoint for orchestrator integration

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
import tempfile
import os
import logging

logger = logging.getLogger(__name__)

# Import the auth if available
try:
    from shared import require_service_auth
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    def require_service_auth():
        return {"client_id": "fallback", "authenticated": True}

from app.core.openvoice_engine import synthesize_v2_to_wav_path

router = APIRouter(prefix="/v1", tags=["Standard TTS"])

class StandardTTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = Field(default="default", description="Voice ID or name")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    language: str = Field(default="EN", description="Language code (EN, ES, FR, etc.)")
    format: str = Field(default="wav", description="Output format")
    quality: str = Field(default="high", description="Audio quality")

class VoicesResponse(BaseModel):
    voices: list[dict]
    default: str = "default"

@router.post("/tts")
async def synthesize_speech(
    request: StandardTTSRequest,
    service_auth: dict = Depends(require_service_auth) if AUTH_AVAILABLE else None
):
    """Standard TTS endpoint compatible with orchestrator ExternalTTSClient"""
    
    try:
        # Validate input
        if not request.text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")
        
        if request.format.lower() != "wav":
            raise HTTPException(status_code=415, detail="Only WAV format is currently supported")
        
        # For standard TTS, we'll just use basic Melo without reference audio
        # Generate speech using the OpenVoice engine
        wav_path = await synthesize_v2_to_wav_path(
            text=request.text.strip(),
            language=request.language.lower(),
            reference_b64=None,
            reference_url=None,
            speed=request.speed,
            volume=1.0,
            pitch=0.0,
            metadata={"voice_id": request.voice, "quality": request.quality}
        )
        
        # Read the generated audio file
        with open(wav_path, "rb") as f:
            audio_data = f.read()
        
        # Clean up temporary file
        try:
            os.unlink(wav_path)
        except Exception:
            pass
        
        return Response(
            content=audio_data,
            media_type="audio/wav",
            headers={
                "Content-Length": str(len(audio_data)),
                "X-Voice-ID": request.voice,
                "X-Language": request.language,
                "X-Speed": str(request.speed),
                "X-Generated-By": "June-TTS-MeloTTS"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"TTS synthesis failed: {str(e)}"
        )

@router.get("/voices")
async def get_voices(language: str = "EN") -> VoicesResponse:
    """Get available voices for the given language"""
    
    # This would typically query your voice database
    # For now, return a basic set of available voices
    voices = [
        {
            "id": "default",
            "name": "Default Voice",
            "language": language.upper(),
            "gender": "neutral",
            "quality": "high"
        },
        {
            "id": "base",
            "name": "Base Voice",
            "language": language.upper(),
            "gender": "neutral",
            "quality": "high"
        }
    ]
    
    return VoicesResponse(
        voices=voices,
        default="default"
    )

@router.get("/status")
async def get_status():
    """Get TTS service status"""
    return {
        "service": "June TTS Standard",
        "status": "operational",
        "engine": "MeloTTS",
        "supported_formats": ["wav"],
        "supported_languages": ["EN", "ES", "FR", "ZH", "JA", "KO"],
        "features": {
            "standard_tts": True,
            "voice_cloning": False,  # Disabled without full OpenVoice
            "speed_control": True,
            "multi_language": True
        }
    }
