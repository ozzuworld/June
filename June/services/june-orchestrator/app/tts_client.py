import httpx
import logging
from typing import Optional, Dict, Any
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

class TTSClient:
    def __init__(self, tts_service_url: str = "http://june-tts.june-services.svc.cluster.local:8000"):
        self.base_url = tts_service_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get_status(self) -> Dict[str, Any]:
        """Get TTS service status"""
        try:
            response = await self.client.get(f"{self.base_url}/readyz")
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
                    "status": "not_ready"
                }
        except Exception as e:
            logger.error(f"TTS status check failed: {e}")
            return {
                "available": False,
                "service": "june-tts",
                "status": "unreachable",
                "error": str(e)
            }
    
    async def synthesize_speech(
        self, 
        text: str, 
        voice: str = "Claribel Dervla",
        speed: float = 1.0,
        language: str = "en"
    ) -> Dict[str, Any]:
        """
        Synthesize speech using the TTS service
        Returns dict with audio_data or error
        """
        try:
            payload = {
                "text": text,
                "language": language,
                "speaker": voice,
                "speed": speed
            }
            
            logger.info(f"🔊 Calling TTS service: {text[:50]}... (voice: {voice})")
            response = await self.client.post(
                f"{self.base_url}/synthesize",
                json=payload
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"✅ TTS synthesis successful")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ TTS synthesis failed: {e}")
            return {
                "error": f"TTS synthesis failed: {str(e)}"
            }
    
    async def get_available_voices(self) -> Dict[str, Any]:
        """Get available voices"""
        try:
            response = await self.client.get(f"{self.base_url}/speakers")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get voices: {e}")
            return {"speakers": ["Claribel Dervla"], "total": 1}
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

# Global TTS client instance
_tts_client = None

def get_tts_client() -> TTSClient:
    """Get or create the global TTS client instance"""
    global _tts_client
    if _tts_client is None:
        _tts_client = TTSClient()
    return _tts_client
