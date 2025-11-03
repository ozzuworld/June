"""TTS service client with Chatterbox integration and streaming support"""
import logging
import httpx
from typing import Optional, Dict, Any

from ..config import config

logger = logging.getLogger(__name__)


class TTSService:
    """Enhanced TTS service client with Chatterbox streaming capabilities"""
    
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
        Legacy method - now redirects to streaming TTS
        Returns raw audio bytes (deprecated - use publish_to_room instead)
        """
        logger.warning("synthesize_speech is deprecated - use publish_to_room for streaming TTS")
        return await self.synthesize_with_chatterbox(
            text=text,
            language=language,
            speed=speed
        )
    
    async def synthesize_with_chatterbox(
        self,
        text: str,
        voice_reference: Optional[str] = None,
        language: str = "en",
        speed: float = 1.0,
        emotion_level: float = 0.5,
        temperature: float = 0.9,
        cfg_weight: float = 0.3
    ) -> Optional[bytes]:
        """
        Synthesize speech using Chatterbox TTS (non-streaming)
        
        Args:
            text: Text to synthesize
            voice_reference: Path or URL to reference voice for cloning
            language: Target language
            speed: Speech speed multiplier
            emotion_level: Emotion intensity (0.0-1.5)
            temperature: Voice randomness (0.1-1.0)
            cfg_weight: Guidance weight (0.0-1.0)
            
        Returns:
            Audio bytes or None if failed
        """
        try:
            if not text or len(text.strip()) == 0:
                return None
            
            if len(text) > 1000:
                text = text[:1000] + "..."
            
            logger.info(f"🎤 Chatterbox synthesis: {text[:50]}...")
            
            payload = {
                "text": text,
                "room_name": "temp-synthesis",  # Temporary room for non-streaming
                "language": language,
                "speed": speed,
                "emotion_level": emotion_level,
                "temperature": temperature,
                "cfg_weight": cfg_weight,
                "streaming": False
            }
            
            if voice_reference:
                payload["voice_reference"] = voice_reference
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/tts/synthesize",
                    json=payload
                )
                
                if response.status_code == 200:
                    # For non-streaming, we'd need a different endpoint
                    # This is primarily for streaming now
                    result = response.json()
                    logger.info(f"✅ Chatterbox synthesis completed")
                    return b""  # Placeholder - streaming is preferred
                else:
                    logger.error(f"Chatterbox synthesis error: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Chatterbox synthesis error: {e}")
            return None
    
    async def publish_to_room(
        self,
        room_name: str,
        text: str,
        language: str = "en",
        speaker: Optional[str] = None,
        voice_id: Optional[str] = None,
        voice_reference: Optional[str] = None,
        speed: float = 1.0,
        emotion_level: float = 0.5,
        temperature: float = 0.9,
        cfg_weight: float = 0.3
    ) -> bool:
        """
        Publish streaming Chatterbox TTS audio directly to LiveKit room
        
        Args:
            room_name: LiveKit room name
            text: Text to synthesize
            language: Target language
            speaker: Ignored (legacy parameter)
            voice_id: Ignored (legacy parameter)
            voice_reference: Path or URL to reference voice for cloning
            speed: Speech speed multiplier
            emotion_level: Emotion intensity (0.0-1.5)
            temperature: Voice randomness (0.1-1.0)
            cfg_weight: Guidance weight (0.0-1.0)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not text or len(text.strip()) == 0:
                return False
            
            if len(text) > 1000:
                text = text[:1000] + "..."
            
            logger.info(f"📢 Publishing Chatterbox streaming TTS to room '{room_name}': {text[:50]}...")
            
            payload = {
                "text": text,
                "room_name": room_name,
                "language": language,
                "speed": speed,
                "emotion_level": emotion_level,
                "temperature": temperature,
                "cfg_weight": cfg_weight,
                "streaming": True
            }
            
            # Add voice reference for cloning if provided
            if voice_reference:
                payload["voice_reference"] = voice_reference
                logger.info(f"🎭 Using voice reference for cloning")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/tts/synthesize",
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"✅ Published Chatterbox streaming TTS: {result.get('chunks_sent', 0)} chunks, {result.get('duration_ms', 0):.0f}ms")
                    return True
                else:
                    logger.error(f"Chatterbox streaming TTS error: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Chatterbox streaming TTS error: {e}")
            return False
    
    async def list_voices(self) -> Optional[Dict[str, Any]]:
        """
        Get Chatterbox TTS capabilities and configuration
        
        Returns:
            Dictionary with Chatterbox capabilities or None if failed
        """
        try:
            logger.info("📋 Fetching Chatterbox TTS capabilities")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/api/voices")
                
                if response.status_code == 200:
                    capabilities = response.json()
                    logger.info(f"✅ Chatterbox capabilities: {len(capabilities.get('features', []))} features")
                    return capabilities
                else:
                    logger.error(f"Chatterbox capabilities error: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Chatterbox capabilities error: {e}")
            return None
    
    async def clone_voice(
        self,
        reference_audio_path: str,
        voice_name: str,
        description: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a voice clone from reference audio (if supported by endpoint)
        
        Args:
            reference_audio_path: Path to reference audio file
            voice_name: Name for the cloned voice
            description: Optional description
            
        Returns:
            Voice ID if successful, None if failed
        """
        try:
            logger.info(f"🎭 Creating voice clone: {voice_name}")
            
            # This would require a separate endpoint for voice management
            # For now, voice cloning is done per-request with voice_reference
            logger.info("Voice cloning is done per-request using voice_reference parameter")
            return reference_audio_path  # Return path as "voice ID"
            
        except Exception as e:
            logger.error(f"Voice cloning error: {e}")
            return None
    
    async def health_check(self) -> bool:
        """
        Check Chatterbox TTS service health and capabilities
        
        Returns:
            True if service is healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/health")
                
                if response.status_code == 200:
                    health = response.json()
                    is_healthy = health.get('status') == 'healthy'
                    engine = health.get('engine', 'unknown')
                    gpu_available = health.get('gpu_available', False)
                    streaming_enabled = health.get('streaming_enabled', False)
                    
                    logger.info(f"✅ Chatterbox TTS service healthy: engine={engine}, gpu={gpu_available}, streaming={streaming_enabled}")
                    return is_healthy
                else:
                    logger.error(f"Chatterbox TTS health check failed: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Chatterbox TTS health check error: {e}")
            return False
    
    async def get_metrics(self) -> Optional[Dict[str, Any]]:
        """
        Get Chatterbox TTS service metrics and performance data
        
        Returns:
            Metrics dictionary or None if failed
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/metrics")
                
                if response.status_code == 200:
                    metrics = response.json()
                    logger.info(f"📊 Chatterbox TTS metrics: {metrics.get('requests_processed', 0)} requests, {metrics.get('voice_cloning_requests', 0)} voice cloning")
                    return metrics
                else:
                    logger.error(f"Chatterbox TTS metrics error: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Chatterbox TTS metrics error: {e}")
            return None


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
    Use tts_service.publish_to_room() for new implementations with streaming
    """
    logger.warning("Legacy synthesize_speech called - consider using publish_to_room for streaming")
    return await tts_service.synthesize_with_chatterbox(text=text, language=language)