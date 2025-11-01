"""TTS service client with voice cloning support"""
import logging
import httpx
from typing import Optional, Dict, Any

from ..config import config

logger = logging.getLogger(__name__)


class TTSService:
    """Enhanced TTS service client with voice cloning capabilities"""
    
    def __init__(self):
        self.base_url = config.services.tts_base_url
        self.timeout = 30.0
    
    async def synthesize_speech(
        self,
        text: str,
        language: str = "en",
        speaker: str = None,
        speed: float = 1.0
    ) -> Optional[bytes]:
        """
        Synthesize speech using built-in speakers
        Returns raw audio bytes
        """
        # Use configured default speaker if none provided
        if speaker is None:
            speaker = config.ai.default_speaker
            
        try:
            if not text or len(text.strip()) == 0:
                return None
            
            if len(text) > 1000:
                text = text[:1000] + "..."
            
            logger.info(f"🔊 TTS synthesis (built-in): {text[:50]}...")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/synthesize-binary",
                    json={
                        "text": text,
                        "speaker": speaker,
                        "speed": speed,
                        "language": language
                    }
                )
                
                if response.status_code == 200:
                    audio_bytes = response.content
                    logger.info(f"✅ TTS: {len(audio_bytes)} bytes")
                    return audio_bytes
                else:
                    logger.error(f"TTS error: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"TTS service error: {e}")
            return None
    
    async def synthesize_with_voice_clone(
        self,
        text: str,
        voice_id: str,
        language: str = "en",
        speed: float = 1.0
    ) -> Optional[bytes]:
        """
        Synthesize speech using a cloned voice
        
        Args:
            text: Text to synthesize
            voice_id: ID of cloned voice from /clone-voice endpoint
            language: Target language (supports cross-language synthesis)
            speed: Speech speed multiplier
            
        Returns:
            Audio bytes or None if failed
        """
        try:
            if not text or len(text.strip()) == 0:
                return None
            
            if len(text) > 1000:
                text = text[:1000] + "..."
            
            logger.info(f"🎭 TTS voice cloning: {text[:50]}... (voice_id: {voice_id})")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/synthesize-clone",
                    json={
                        "text": text,
                        "voice_id": voice_id,
                        "language": language,
                        "speed": speed
                    }
                )
                
                if response.status_code == 200:
                    audio_bytes = response.content
                    logger.info(f"✅ Voice cloned TTS: {len(audio_bytes)} bytes")
                    return audio_bytes
                else:
                    logger.error(f"Voice cloning TTS error: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Voice cloning TTS error: {e}")
            return None
    
    async def publish_to_room(
        self,
        room_name: str,
        text: str,
        language: str = "en",
        speaker: Optional[str] = None,
        voice_id: Optional[str] = None,
        speed: float = 1.0
    ) -> bool:
        """
        Publish TTS audio directly to LiveKit room
        
        Args:
            room_name: LiveKit room name
            text: Text to synthesize
            language: Target language
            speaker: Built-in speaker name (if not using voice_id)
            voice_id: Custom voice ID (if not using speaker)
            speed: Speech speed multiplier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not text or len(text.strip()) == 0:
                return False
            
            if len(text) > 1000:
                text = text[:1000] + "..."
            
            synthesis_type = "cloned" if voice_id else "built-in"
            logger.info(f"📢 Publishing {synthesis_type} TTS to room '{room_name}': {text[:50]}...")
            
            payload = {
                "room_name": room_name,
                "text": text,
                "language": language,
                "speed": speed
            }
            
            # Add voice selection - use configured default if none provided
            if voice_id:
                payload["voice_id"] = voice_id
            else:
                payload["speaker"] = speaker or config.ai.default_speaker
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/publish-to-room",
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"✅ Published to room: {result.get('audio_size', 0)} bytes")
                    return True
                else:
                    logger.error(f"Room publishing error: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Room publishing error: {e}")
            return False
    
    async def list_voices(self) -> Optional[Dict[str, Any]]:
        """
        Get list of available voices (built-in and custom)
        
        Returns:
            Dictionary with voice information or None if failed
        """
        try:
            logger.info("📋 Fetching available voices")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/voices")
                
                if response.status_code == 200:
                    voices = response.json()
                    logger.info(f"✅ Found {voices.get('summary', {}).get('total_voices', 0)} voices")
                    return voices
                else:
                    logger.error(f"Voice listing error: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Voice listing error: {e}")
            return None
    
    async def get_voice_info(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific voice
        
        Args:
            voice_id: Voice ID to get information for
            
        Returns:
            Voice information dictionary or None if failed
        """
        try:
            logger.info(f"ℹ️ Fetching voice info for: {voice_id}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/voices/{voice_id}")
                
                if response.status_code == 200:
                    voice_info = response.json()
                    logger.info(f"✅ Voice info: {voice_info.get('name', 'Unknown')}")
                    return voice_info
                else:
                    logger.error(f"Voice info error: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Voice info error: {e}")
            return None
    
    async def health_check(self) -> bool:
        """
        Check TTS service health and capabilities
        
        Returns:
            True if service is healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/healthz")
                
                if response.status_code == 200:
                    health = response.json()
                    logger.info(f"✅ TTS service healthy: {health.get('features', [])}")
                    return health.get('tts_ready', False)
                else:
                    logger.error(f"TTS health check failed: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"TTS health check error: {e}")
            return False


# Global TTS service instance
tts_service = TTSService()


# Legacy function for backward compatibility
async def synthesize_speech(
    text: str,
    language: str = "en",
    speaker: str = None
) -> Optional[bytes]:
    """
    Legacy function for backward compatibility
    Use tts_service.synthesize_speech() for new implementations
    """
    # Use configured default speaker if none provided
    if speaker is None:
        speaker = config.ai.default_speaker
        
    return await tts_service.synthesize_speech(text, language, speaker)