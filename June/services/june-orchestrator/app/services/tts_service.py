"""
TTS Service Integration
"""
import logging
from typing import Optional
import httpx

from ..config import config

logger = logging.getLogger(__name__)


async def synthesize_binary(
    text: str,
    user_id: str = "default",
    language: str = "en",
    speaker: str = "Claribel Dervla",
    speed: float = 1.0
) -> Optional[bytes]:
    """
    Synthesize speech using TTS service
    
    Returns raw audio bytes (WAV format)
    """
    try:
        if not text or len(text.strip()) == 0:
            return None
        
        # Truncate very long text
        if len(text) > 1000:
            text = text[:1000] + "..."
        
        logger.info(f"🔊 TTS synthesis: {text[:50]}...")
        
        tts_url = config.services.tts_base_url
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{tts_url}/synthesize-binary",
                json={
                    "text": text,
                    "speaker": speaker,
                    "speed": speed,
                    "language": language
                }
            )
            
            if response.status_code == 200:
                audio_bytes = response.content
                logger.info(f"✅ TTS synthesis: {len(audio_bytes)} bytes")
                return audio_bytes
            else:
                logger.error(f"TTS service error: {response.status_code}")
                return None
                
    except Exception as e:
        logger.error(f"TTS synthesis error: {e}")
        return None