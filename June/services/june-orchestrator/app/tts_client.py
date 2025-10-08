import httpx
import logging
from typing import Optional
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

class TTSClient:
    def __init__(self, tts_service_url: str = "http://june-tts.june-services.svc.cluster.local:8000"):
        self.base_url = tts_service_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=30.0)
    
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
        language: str = "en",
        speaker: Optional[str] = None,
        speed: float = 1.0
    ) -> Optional[bytes]:
        """
        Synthesize speech using the new TTS service
        Returns audio bytes or None if failed
        """
        try:
            payload = {
                "text": text,
                "language": language,
                "speed": speed
            }
            if speaker:
                payload["speaker"] = speaker
            
            logger.info(f"🔊 Calling TTS service: {text[:50]}...")
            response = await self.client.post(
                f"{self.base_url}/synthesize",
                json=payload
            )
            response.raise_for_status()
            
            # The response should be audio/wav content
            audio_data = response.content
            logger.info(f"✅ TTS synthesis successful, got {len(audio_data)} bytes")
            return audio_data
            
        except Exception as e:
            logger.error(f"❌ TTS synthesis failed: {e}")
            return None
    
    async def clone_voice(
        self,
        text: str,
        reference_audio_path: str,
        language: str = "en",
        speaker_name: str = "cloned_voice"
    ) -> Optional[bytes]:
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
                return audio_data
                
        except Exception as e:
            logger.error(f"❌ Voice cloning failed: {e}")
            return None
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

# Global TTS client instance
tts_client = TTSClient()
