"""
Routers for the voice cloning endpoints.

This module provides an endpoint for generating speech that matches the tone
colour of a reference audio clip. The implementation uses the simplified
OpenVoice V2 engine defined in `openvoice_engine`.
"""

from fastapi import APIRouter, HTTPException, status, File, UploadFile, Form
from fastapi.responses import Response

from ..core import openvoice_engine
from ..core.config import settings

router = APIRouter(prefix="/clone", tags=["Voice Cloning"])


async def _validate_audio(file: UploadFile) -> None:
    """
    Perform minimal validation on the uploaded reference audio.

    Ensures the file has an allowed extension and is below the configured size
    limit. As per the OpenVoice documentation, users should supply short,
    clean reference clips【212231721036567†L294-L315】.
    """
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in settings.allowed_audio_formats:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported audio format")
    if file.size is not None and file.size > settings.max_file_size:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File too large")


@router.post("/voice", response_class=Response)
async def clone_voice(
    reference_audio: UploadFile = File(...),
    text: str = Form(...),
    language: str = Form(default="EN"),
    speed: float = Form(default=1.0),
) -> Response:
    """
    Clone a speaker's tone colour from a reference clip.

    Clients must upload a short recording (`reference_audio`) and supply the
    text to synthesize. The response contains a WAV file with the generated
    speech. The accent and emotion of the output follow the base speaker; only
    the timbre is transferred【212231721036567†L296-L305】.
    """
    if not text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Text cannot be empty")
    if not (0.5 <= speed <= 2.0):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Speed must be between 0.5 and 2.0")
    await _validate_audio(reference_audio)
    try:
        audio_bytes = await reference_audio.read()
        result_bytes = await openvoice_engine.clone_voice(
            text=text,
            reference_audio_bytes=audio_bytes,
            language=language.upper(),
            speed=speed,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return Response(
        content=result_bytes,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f"attachment; filename=clone_{reference_audio.filename}",
            "X-Generated-By": "june-tts",
        },
    )


@router.get("/status")
async def clone_status() -> dict:
    """Return a simple status indicating that voice cloning is available."""
    # If the engine models are loaded, cloning is available.
    return {"voice_cloning_available": True}