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
            "http://june-tts.june-services.svc.cluster.local:8000"  # Note: port 8000, not 8080
        )
        
        # Create HTTP client without SSL verification for internal calls
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            verify=False
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
            
            # FIXED: Use /synthesize instead of /v1/synthesize
            response = await self.client.post(
                "/synthesize",  # Correct endpoint
                json={
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "language": language
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # The TTS service returns audio as base64 in 'audio_base64' field
                if 'audio_base64' in result:
                    # Convert base64 back to bytes for consistency
                    import base64
                    audio_bytes = base64.b64decode(result['audio_base64'])
                    
                    return {
                        "audio_data": audio_bytes,
                        "content_type": result.get("content_type", "audio/wav"),
                        "size_bytes": len(audio_bytes),
                        "voice": result.get("voice", voice),
                        "speed": result.get("speed", speed),
                        "language": result.get("language", language)
                    }
                else:
                    logger.error(f"❌ TTS response missing audio_base64 field: {result}")
                    return {"error": "Invalid TTS response format"}
            
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
