from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from app.core.openvoice_engine import engine
from app.models.schemas import TTSRequest, ErrorResponse
import asyncio

router = APIRouter(prefix="/tts", tags=["Text-to-Speech"])

@router.post(
    "/generate",
    response_class=Response,
    responses={
        200: {"content": {"audio/wav": {}}},
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    }
)
async def generate_speech(request: TTSRequest):
    """Generate speech from text using OpenVoice TTS"""
    try:
        audio_data = await engine.text_to_speech(
            text=request.text,
            language=request.language,
            speaker_key=request.speaker_key,
            speed=request.speed
        )
        
        return Response(
            content=audio_data,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=generated_speech.wav",
                "X-Generated-By": "OpenVoice-API"
            }
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request parameters: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Speech generation failed: {str(e)}"
        )

@router.get("/voices/{language}")
async def list_voices(language: str):
    """List available voices for a language"""
    try:
        model = await engine.get_tts_model(language.upper())
        speaker_ids = model.hps.data.spk2id
        
        return {
            "language": language.upper(),
            "voices": list(speaker_ids.keys()) if speaker_ids else [],
            "total": len(speaker_ids) if speaker_ids else 0
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to list voices for {language}: {str(e)}"
        )

@router.get("/status")
async def engine_status():
    """Get engine status"""
    return {
        "status": "ready" if engine.converter else "initializing",
        "device": engine.device,
        "loaded_models": list(engine.tts_models.keys()),
        "max_concurrent_requests": engine._semaphore._value
    }
