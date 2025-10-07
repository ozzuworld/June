import os
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class VoiceCloningClient:
    def __init__(self):
        # Voice cloning service URL
        self.clone_url = os.getenv(
            "VOICE_CLONE_SERVICE_URL", 
            "http://june-clone.june-services.svc.cluster.local:8000"
        )
        
        # Traditional TTS service URL (placeholder for future)
        self.tts_url = os.getenv(
            "TTS_SERVICE_URL",
            "http://june-tts.june-services.svc.cluster.local:8000"  # Keep for legacy
        )
        
        self.client = httpx.AsyncClient(timeout=120.0, verify=False)
        logger.info(f"🎭 Voice Cloning Client initialized: {self.clone_url}")
    
    async def clone_voice(
        self, 
        text: str,
        reference_audio: bytes,
        reference_text: str = "",
        language: str = "en",
        speed: float = 1.0
    ) -> Dict[str, Any]:
        """Clone voice using reference audio"""
        try:
            logger.info(f"🎭 Voice cloning: {text[:50]}... (lang: {language}, speed: {speed})")
            
            files = {
                "reference_audio": ("reference.wav", reference_audio, "audio/wav")
            }
            
            data = {
                "text": text,
                "language": language,
                "speed": speed,
                "reference_text": reference_text or "This is reference audio for voice cloning."
            }
            
            response = await self.client.post(
                f"{self.clone_url}/v1/clone",
                files=files,
                data=data
            )
            
            if response.status_code == 200:
                audio_bytes = response.content
                return {
                    "audio_data": audio_bytes,
                    "content_type": "audio/wav",
                    "size_bytes": len(audio_bytes),
                    "cloned": True,
                    "language": language,
                    "speed": speed
                }
            else:
                error_msg = f"Voice cloning error: {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                return {"error": error_msg}
        
        except Exception as e:
            error_msg = f"Voice cloning error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {"error": error_msg}
    
    async def synthesize_speech(
        self, 
        text: str, 
        voice: str = "default",
        speed: float = 1.0,
        language: str = "en",
        reference_audio: Optional[bytes] = None,
        reference_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Enhanced synthesis: voice cloning if reference audio provided,
        fallback to traditional TTS if implemented
        """
        
        # If reference audio provided, use voice cloning
        if reference_audio:
            return await self.clone_voice(
                text=text,
                reference_audio=reference_audio,
                reference_text=reference_text or "",
                language=language,
                speed=speed
            )
        
        # For now, return error for traditional TTS (will implement later)
        return {
            "error": "Traditional TTS not implemented. Please provide reference_audio for voice cloning."
        }
    
    async def get_status(self) -> Dict[str, Any]:
        """Get voice cloning service status"""
        try:
            response = await self.client.get(f"{self.clone_url}/healthz")
            if response.status_code == 200:
                return {"available": True, "status": response.json(), "service": "voice-cloning"}
            else:
                return {"available": False, "error": f"Status check failed: {response.status_code}"}
        
        except Exception as e:
            return {"available": False, "error": str(e)}
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

# Singleton instance
_voice_client = None

def get_voice_client() -> VoiceCloningClient:
    """Get voice cloning client singleton"""
    global _voice_client
    if _voice_client is None:
        _voice_client = VoiceCloningClient()
    return _voice_client

# Backward compatibility aliases
TTSClient = VoiceCloningClient
get_tts_client = get_voice_client
