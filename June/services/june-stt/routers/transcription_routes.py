"""Transcription API routes for June STT"""
import tempfile
import logging
from typing import Optional

from fastapi import APIRouter, File, UploadFile, Form, HTTPException

from whisper_service import whisper_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["transcription"])

@router.post("/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    model: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    response_format: Optional[str] = Form("json"),
):
    """OpenAI-compatible transcription endpoint with SOTA optimization"""
    if not whisper_service.is_model_ready():
        raise HTTPException(
            status_code=503, 
            detail="SOTA Whisper + Aggressive Silero VAD not ready"
        )
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp.flush()
            result = await whisper_service.transcribe(tmp.name, language=language)
        
        return _format_transcription_response(result, response_format, language)
        
    except Exception as e:
        logger.error(f"SOTA OpenAI API transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _format_transcription_response(result: dict, response_format: str, language: Optional[str]):
    """Format transcription response based on requested format"""
    text = result.get("text", "")
    
    if response_format == "text":
        return text
    elif response_format == "verbose_json":
        return {
            "task": "transcribe",
            "language": result.get("language", language or "en"),
            "text": text,
            "segments": result.get("segments", []),
            "method": result.get("method", "sota_enhanced"),
            "optimization": "sota_competitive",
        }
    else:
        return {"text": text}
