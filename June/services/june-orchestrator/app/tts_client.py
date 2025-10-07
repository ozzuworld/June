import os
import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class TTSClient:
    def __init__(self):
        # Use internal Kubernetes service URL with HTTP
        self.base_url = os.getenv(
            "TTS_SERVICE_URL", 
            "http://june-tts.june-services.svc.cluster.local:8080"  # Internal HTTP
        )
        
        # Create HTTP client without SSL verification for internal calls
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            verify=False  # Disable SSL verification for internal calls
        )
        
        logger.info(f"🔊 TTS Client initialized: {self.base_url}")
    
    async def synthesize_speech(
        self, 
        text: str, 
        voice: str = "default",
        speed: float = 1.0,
        language: str = "EN"
    ) -> Dict[str, Any]:
        """Generate speech from text"""
        try:
            logger.info(f"🔊 Synthesizing: {text[:50]}... (voice: {voice}, speed: {speed}, lang: {language})")
            
            response = await self.client.post(
                "/v1/synthesize",
                json={
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "language": language
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ TTS success: {result.get('size_bytes', 0)} bytes")
                return result
            else:
                error_msg = f"TTS API error: {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                return {"error": error_msg}
        
        except Exception as e:
            error_msg = f"TTS error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}
    
    async def get_status(self) -> Dict[str, Any]:
        """Get TTS service status"""
        try:
            response = await self.client.get("/healthz")
            if response.status_code == 200:
                return {"available": True, "status": response.json()}
            else:
                return {"available": False, "error": f"Status check failed: {response.status_code}"}
        
        except Exception as e:
            return {"available": False, "error": str(e)}
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


# Singleton instance
_tts_client = None

def get_tts_client() -> TTSClient:
    """Get TTS client singleton"""
    global _tts_client
    if _tts_client is None:
        _tts_client = TTSClient()
    return _tts_client
