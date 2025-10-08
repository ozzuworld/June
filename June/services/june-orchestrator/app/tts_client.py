import logging
import httpx
from typing import Optional

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

async def synthesize_speech(text: str, voice: str = "Claribel Dervla", speed: float = 1.0) -> Optional[str]:
    """Call TTS service directly and return base64 audio data"""
    
    if not settings.tts_base_url:
        logger.warning("⚠️ TTS service URL not configured")
        return None
    
    try:
        logger.info(f"🔊 Calling TTS service: {text[:50]}... (voice: {voice})")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.tts_base_url}/synthesize",
                json={
                    "text": text,
                    "speaker": voice,
                    "speed": speed,
                    "language": "en"
                }
            )
            response.raise_for_status()
            
            result = response.json()
            
            if "audio_data" in result:
                logger.info("✅ TTS synthesis successful")
                return result["audio_data"]
            else:
                logger.warning(f"⚠️ TTS response missing audio_data: {result}")
                return None
            
    except httpx.TimeoutException:
        logger.error("❌ TTS service timeout")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ TTS service HTTP error: {e.response.status_code}")
        return None
    except Exception as e:
        logger.error(f"❌ TTS synthesis failed: {e}")
        return None

async def get_tts_status() -> dict:
    """Check TTS service status"""
    if not settings.tts_base_url:
        return {"available": False, "error": "TTS URL not configured"}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.tts_base_url}/readyz")
            
            if response.status_code == 200:
                return {
                    "available": True,
                    "service": "june-tts",
                    "status": "ready"
                }
            else:
                return {
                    "available": False,
                    "service": "june-tts",
                    "status": f"not_ready_{response.status_code}"
                }
                
    except Exception as e:
        return {
            "available": False,
            "service": "june-tts",
            "error": str(e)
        }

async def get_available_voices() -> list:
    """Get list of available TTS voices"""
    if not settings.tts_base_url:
        return ["Claribel Dervla"]  # Default fallback
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.tts_base_url}/speakers")
            response.raise_for_status()
            
            result = response.json()
            return result.get("speakers", ["Claribel Dervla"])
            
    except Exception as e:
        logger.error(f"Failed to get TTS voices: {e}")
        return ["Claribel Dervla"]