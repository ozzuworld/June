"""
Simplified TTS client for June Orchestrator
"""
import logging
from typing import Dict, Any, Optional
import httpx

from app.config import get_config

logger = logging.getLogger(__name__)


class TTSClient:
    """Simple TTS client with error handling"""
    
    def __init__(self):
        config = get_config()
        self.base_url = config["tts_base_url"]
        self.timeout = httpx.Timeout(30.0, connect=5.0)
    
    async def synthesize_speech(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        language: str = "EN"
    ) -> Dict[str, Any]:
        """
        Synthesize speech from text
        
        Returns:
            Dict with audio_data (bytes), content_type, size_bytes, etc.
            Or dict with error key if failed
        """
        try:
            payload = {
                "text": text,
                "voice": voice,
                "speed": speed,
                "language": language,
                "format": "wav"
            }
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.debug(f"🔊 Requesting TTS: {text[:50]}...")
                
                response = await client.post(
                    f"{self.base_url}/v1/tts",
                    json=payload
                )
                
                if response.status_code == 200:
                    audio_data = response.content
                    
                    return {
                        "audio_data": audio_data,
                        "content_type": response.headers.get("content-type", "audio/wav"),
                        "size_bytes": len(audio_data),
                        "voice": voice,
                        "speed": speed,
                        "language": language
                    }
                else:
                    error_msg = f"TTS failed with status {response.status_code}"
                    logger.error(f"❌ {error_msg}")
                    return {"error": error_msg}
        
        except httpx.TimeoutException:
            error_msg = "TTS request timed out"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}
        
        except Exception as e:
            error_msg = f"TTS error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}
    
    async def get_status(self) -> Dict[str, Any]:
        """Check TTS service status"""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(f"{self.base_url}/healthz")
                
                if response.status_code == 200:
                    return {
                        "available": True,
                        "url": self.base_url,
                        "status": "healthy"
                    }
                else:
                    return {
                        "available": False,
                        "url": self.base_url,
                        "error": f"Status check failed: {response.status_code}"
                    }
        
        except Exception as e:
            logger.warning(f"⚠️ TTS status check failed: {e}")
            return {
                "available": False,
                "url": self.base_url,
                "error": str(e)
            }


# Singleton instance
_tts_client: Optional[TTSClient] = None


def get_tts_client() -> TTSClient:
    """Get global TTS client instance"""
    global _tts_client
    if _tts_client is None:
        _tts_client = TTSClient()
    return _tts_client