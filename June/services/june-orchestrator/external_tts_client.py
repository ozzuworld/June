# external_tts_client.py - Client for external OpenVoice TTS service
import httpx
import logging
import base64
from typing import Optional

logger = logging.getLogger(__name__)

class ExternalTTSClient:
    """Client for external OpenVoice TTS service with IDP authentication"""
    
    def __init__(self, base_url: str, auth_client):
        self.base_url = base_url.rstrip('/')
        self.auth_client = auth_client  # Use existing IDP auth client
        
    async def synthesize_speech(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        language: str = "EN"
    ) -> bytes:
        """Call external OpenVoice TTS service"""
        try:
            logger.info(f"🎵 Calling external TTS: '{text[:50]}...'")
            
            # Use IDP authentication
            response = await self.auth_client.make_authenticated_request(
                "POST",
                f"{self.base_url}/v1/tts",
                json={
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "language": language
                },
                timeout=30.0
            )
            
            response.raise_for_status()
            
            audio_data = response.content
            logger.info(f"✅ External TTS success: {len(audio_data)} bytes")
            
            return audio_data
            
        except Exception as e:
            logger.error(f"❌ External TTS failed: {e}")
            raise RuntimeError(f"External TTS service failed: {str(e)}")
    
    async def clone_voice(
        self,
        text: str,
        reference_audio_bytes: bytes,
        language: str = "EN"
    ) -> bytes:
        """Call external voice cloning service"""
        try:
            logger.info(f"🎤 Voice cloning request: '{text[:50]}...'")
            
            # Encode audio for transmission
            audio_b64 = base64.b64encode(reference_audio_bytes).decode('utf-8')
            
            response = await self.auth_client.make_authenticated_request(
                "POST",
                f"{self.base_url}/v1/clone",
                json={
                    "text": text,
                    "reference_audio": audio_b64,
                    "language": language
                },
                timeout=60.0  # Voice cloning takes longer
            )
            
            response.raise_for_status()
            
            audio_data = response.content
            logger.info(f"✅ Voice cloning success: {len(audio_data)} bytes")
            
            return audio_data
            
        except Exception as e:
            logger.error(f"❌ Voice cloning failed: {e}")
            raise RuntimeError(f"Voice cloning service failed: {str(e)}")
