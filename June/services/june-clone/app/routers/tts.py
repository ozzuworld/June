"""
Routers for the text‑to‑speech endpoints.

This module exposes a single POST endpoint that accepts text and returns
speech audio encoded as WAV. A simple GET endpoint lists the supported base
voices (currently just the default speaker of the MeloTTS model).
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from ..core import openvoice_engine

router = APIRouter(prefix="/tts", tags=["TTS"])


class TtsRequest(BaseModel):
    text: str
    language: str = "EN"
    speed: float = 1.0


@router.post("/voice", response_class=Response)
async def synthesize(request: TtsRequest) -> Response:
    """
    Generate speech from text.

    This endpoint produces a WAV file in the response body. The returned
    `Content-Disposition` header suggests a filename to help browsers
    download the audio.
    """
    if not request.text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Text cannot be empty")
    if not (0.5 <= request.speed <= 2.0):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Speed must be between 0.5 and 2.0")
    try:
        audio_bytes = await openvoice_engine.synthesize_tts(
            text=request.text,
            language=request.language.upper(),
            speed=request.speed,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": "attachment; filename=tts.wav",
            "X-Generated-By": "june-tts",
        },
    )


@router.get("/voices")
async def list_voices() -> dict:
    """
    Return a list of available base voices.

    OpenVoice V2 supports multi‑lingual generation, but the tone colour
    conversion does not include accent or emotion【212231721036567†L296-L305】. For
    simplicity this API exposes only the default speaker (id 0). Clients can
    specify `language` when calling `/tts/voice`.
    """
    voices = [
        {
            "id": "0",
            "display_name": "Default Speaker",
            "language": "multi-lingual",
            "meta": {},
        }
    ]
    return {"voices": voices}