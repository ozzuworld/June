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
    
    async def health_check(self) -> bool:
        """Check if TTS service is healthy and ready"""
        try:
            response = await self.client.get(f"{self.base_url}/readyz")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"TTS health check failed: {e}")
            return False
    
    async def get_supported_languages(self) -> dict:
        """Get supported languages from TTS service"""
        try:
            response = await self.client.get(f"{self.base_url}/languages")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get supported languages: {e}")
            return {"supported_languages": {"en": "English"}, "total": 1}
    
    async def synthesize_speech(
        self, 
        text: str, 
        voice: str = "default",
        speed: float = 1.0,
        language: str = "en"
    ) -> Dict[str, Any]:
        """
        Synthesize speech using the new TTS service
        Returns dict with audio_data or error
        """
        try:
            # Map orchestrator language codes to TTS service format
            lang_map = {
                "EN": "en", "en": "en",
                "ES": "es", "es": "es", 
                "FR": "fr", "fr": "fr",
                "DE": "de", "de": "de",
                "IT": "it", "it": "it",
                "PT": "pt", "pt": "pt"
            }
            tts_language = lang_map.get(language, "en")
            
            payload = {
                "text": text,
                "language": tts_language,
                "speed": speed
            }
            # Note: june-tts doesn't use "speaker" param for basic synthesis
            
            logger.info(f"🔊 Calling TTS service: {text[:50]}... (lang: {tts_language})")
            response = await self.client.post(
                f"{self.base_url}/synthesize",
                json=payload
            )
            response.raise_for_status()
            
            # The response should be audio/wav content
            audio_data = response.content
            logger.info(f"✅ TTS synthesis successful, got {len(audio_data)} bytes")
            
            return {
                "audio_data": audio_data,
                "content_type": "audio/wav",
                "size_bytes": len(audio_data),
                "voice": voice,
                "speed": speed,
                "language": language
            }
            
        except Exception as e:
            logger.error(f"❌ TTS synthesis failed: {e}")
            return {
                "error": f"TTS synthesis failed: {str(e)}"
            }
    
    async def clone_voice(
        self,
        text: str,
        reference_audio_path: str,
        language: str = "en",
        speaker_name: str = "cloned_voice"
    ) -> Dict[str, Any]:
        """
        Clone voice using reference audio
        """
        try:
            with open(reference_audio_path, "rb") as audio_file:
                files = {"reference_audio": audio_file}
                data = {
                    "text": text,
                    "language": language,
                    "speaker_name": speaker_name
                }
                
                response = await self.client.post(
                    f"{self.base_url}/clone-voice",
                    data=data,
                    files=files
                )
                response.raise_for_status()
                
                audio_data = response.content
                logger.info(f"✅ Voice cloning successful, got {len(audio_data)} bytes")
                
                return {
                    "audio_data": audio_data,
                    "content_type": "audio/wav",
                    "size_bytes": len(audio_data),
                    "voice": speaker_name,
                    "speed": 1.0,
                    "language": language
                }
                
        except Exception as e:
            logger.error(f"❌ Voice cloning failed: {e}")
            return {
                "error": f"Voice cloning failed: {str(e)}"
            }
    
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

# For backward compatibility
tts_client = get_tts_client()
