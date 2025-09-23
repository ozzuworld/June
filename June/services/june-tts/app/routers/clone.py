from fastapi import APIRouter, HTTPException, status, File, UploadFile, Form
from fastapi.responses import Response
from app.core.openvoice_engine import engine
from app.models.schemas import CloneRequest, ErrorResponse
from app.utils.file_handler import validate_audio_file
import librosa
import io

router = APIRouter(prefix="/clone", tags=["Voice Cloning"])

@router.post(
    "/voice",
    response_class=Response,
    responses={
        200: {"content": {"audio/wav": {}}},
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse}
    }
)
async def clone_voice(
    reference_audio: UploadFile = File(..., description="Reference audio file (WAV, MP3, FLAC, M4A)"),
    text: str = Form(..., min_length=1, max_length=5000),
    language: str = Form(default="EN"),
    speed: float = Form(default=1.0, ge=0.5, le=2.0)
):
    """Clone voice from reference audio and generate speech"""
    
    # Check if voice cloning is available
    if not engine.converter:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice cloning is currently unavailable. The service is running in TTS-only mode."
        )
    
    try:
        # Validate audio file
        await validate_audio_file(reference_audio)
        
        # Read reference audio
        audio_bytes = await reference_audio.read()
        
        # Generate cloned speech
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
                "X-Cloned-By": "OpenVoice-API",
                "X-Reference-File": reference_audio.filename or "unknown"
            }
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Voice cloning failed: {str(e)}"
        )

@router.post("/analyze")
async def analyze_reference(reference_audio: UploadFile = File(...)):
    """Analyze reference audio characteristics"""
    try:
        await validate_audio_file(reference_audio)
        audio_bytes = await reference_audio.read()
        
        # Basic audio analysis
        audio_io = io.BytesIO(audio_bytes)
        y, sr = librosa.load(audio_io)
        
        duration = len(y) / sr
        
        return {
            "filename": reference_audio.filename,
            "duration_seconds": round(duration, 2),
            "sample_rate": sr,
            "channels": 1 if y.ndim == 1 else y.shape[0],
            "suitable_for_cloning": duration >= 5.0 and duration <= 60.0,
            "recommendation": (
                "Good length for voice cloning" if 5.0 <= duration <= 60.0
                else "Audio should be 5-60 seconds for optimal results"
            ),
            "voice_cloning_available": engine.converter is not None
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Audio analysis failed: {str(e)}"
        )

@router.get("/status")
async def clone_status():
    """Get voice cloning status"""
    return {
        "voice_cloning_available": engine.converter is not None,
        "status": "available" if engine.converter else "disabled - TTS only mode",
        "message": "Voice cloning ready" if engine.converter else "Voice cloning disabled due to missing converter files"
    }
