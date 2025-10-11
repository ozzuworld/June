"""
STT Service Integration
"""
import logging
import os
import tempfile
from typing import Optional
import httpx

from ..config import config

logger = logging.getLogger(__name__)


async def transcribe_audio(
    audio_bytes: bytes,
    session_id: str,
    user_id: str,
    language: Optional[str] = None
) -> Optional[str]:
    """
    Send audio to STT service for transcription
    
    Args:
        audio_bytes: Raw audio data (WAV format)
        session_id: Session identifier
        user_id: User identifier
        language: Optional language code
        
    Returns:
        Transcribed text or None if failed
    """
    try:
        stt_url = config.services.stt_base_url
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name
        
        try:
            # Send to STT service
            async with httpx.AsyncClient(timeout=15.0) as client:
                with open(temp_path, "rb") as audio_file:
                    files = {"audio_file": ("audio.wav", audio_file, "audio/wav")}
                    data = {"language": language or "en"}
                    headers = {
                        "Authorization": f"Bearer {config.services.stt_service_token or 'fallback_token'}",
                        "User-Agent": "june-orchestrator/11.0.0"
                    }
                    
                    response = await client.post(
                        f"{stt_url}/v1/transcribe",
                        files=files,
                        data=data,
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        transcript = result.get("text", "").strip()
                        logger.info(f"✅ STT: {transcript[:50]}...")
                        return transcript
                    else:
                        logger.error(f"STT service error: {response.status_code}")
                        return None
                        
        finally:
            # Cleanup temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"STT service error: {e}")
        return None