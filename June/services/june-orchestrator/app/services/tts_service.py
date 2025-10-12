"""TTS service client"""
import logging
import httpx

from ..config import config

logger = logging.getLogger(__name__)


async def synthesize_speech(
    text: str,
    language: str = "en",
    speaker: str = "Claribel Dervla"
) -> bytes | None:
    """
    Synthesize speech using TTS service
    Returns raw audio bytes
    """
    try:
        if not text or len(text.strip()) == 0:
            return None
        
        if len(text) > 1000:
            text = text[:1000] + "..."
        
        logger.info(f"🔊 TTS synthesis: {text[:50]}...")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{config.services.tts_base_url}/synthesize-binary",
                json={
                    "text": text,
                    "speaker": speaker,
                    "speed": 1.0,
                    "language": language
                }
            )
            
            if response.status_code == 200:
                audio_bytes = response.content
                logger.info(f"✅ TTS: {len(audio_bytes)} bytes")
                return audio_bytes
            else:
                logger.error(f"TTS error: {response.status_code}")
                return None
                
    except Exception as e:
        logger.error(f"TTS service error: {e}")
        return None