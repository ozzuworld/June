# June/services/june-tts/app/routers/standard_tts.py
# Standard TTS endpoint for orchestrator integration

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
import tempfile
import os
from pathlib import Path

# Import the auth if available
try:
    from shared import require_service_auth
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    require_service_auth = lambda: None

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
    # auth_data: dict = Depends(require_service_auth) if AUTH_AVAILABLE else None
):
    """Standard TTS endpoint compatible with orchestrator ExternalTTSClient"""
    
    try:
        # Validate input
        if not request.text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")
        
        if request.format.lower() != "wav":
            raise HTTPException(status_code=415, detail="Only WAV format is currently supported")
        
        # For standard TTS, we'll use a default reference voice
        # This requires having a default reference audio file
        default_reference_path = os.getenv("DEFAULT_REFERENCE_AUDIO", "")
        
        if not default_reference_path or not os.path.exists(default_reference_path):
            # Create a simple default reference if none exists
            default_reference_path = await _create_default_reference()
        
        # Read default reference as base64
        import base64
        with open(default_reference_path, "rb") as f:
            reference_b64 = base64.b64encode(f.read()).decode('utf-8')
        
        # Generate speech using the OpenVoice engine
        wav_path = await synthesize_v2_to_wav_path(
            text=request.text.strip(),
            language=request.language.lower(),
            reference_b64=reference_b64,
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
                "X-Generated-By": "June-TTS-OpenVoice"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
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
        "engine": "OpenVoice",
        "supported_formats": ["wav"],
        "supported_languages": ["EN", "ES", "FR", "ZH", "JA", "KO"],
        "features": {
            "standard_tts": True,
            "voice_cloning": True,
            "speed_control": True,
            "multi_language": True
        }
    }

async def _create_default_reference() -> str:
    """Create a default reference audio file if none exists"""
    
    # Create a simple sine wave as default reference
    # This is a fallback - ideally you'd have a proper reference voice
    
    import numpy as np
    import soundfile as sf
    
    # Generate a 2-second 440Hz tone
    sample_rate = 22050
    duration = 2.0
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    
    # Create a more voice-like waveform (multiple harmonics)
    fundamental = 220  # A3 note
    waveform = (
        0.5 * np.sin(2 * np.pi * fundamental * t) +
        0.3 * np.sin(2 * np.pi * fundamental * 2 * t) +
        0.2 * np.sin(2 * np.pi * fundamental * 3 * t)
    )
    
    # Apply envelope to make it more natural
    envelope = np.exp(-2 * t)  # Exponential decay
    waveform = waveform * envelope * 0.3  # Scale to reasonable volume
    
    # Save to temporary file
    fd, temp_path = tempfile.mkstemp(suffix=".wav", prefix="default_ref_")
    os.close(fd)
    
    sf.write(temp_path, waveform, sample_rate)
    
    return temp_path