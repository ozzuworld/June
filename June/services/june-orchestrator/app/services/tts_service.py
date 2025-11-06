"""CosyVoice2 TTS Service Client - Enhanced

Official CosyVoice2 integration for June Orchestrator.
CosyVoice2 uses zero-shot and cross-lingual synthesis (NO SFT mode).

Reference: https://github.com/FunAudioLLM/CosyVoice
"""
import logging
import os
import httpx
from typing import Optional, Dict, Any, List

from ..config import config

logger = logging.getLogger(__name__)

# Service-to-service auth token
SERVICE_AUTH_TOKEN = os.getenv("SERVICE_AUTH_TOKEN", "")


class TTSService:
    """CosyVoice2 TTS service client
    
    This client communicates with the june-tts service which runs CosyVoice2.
    CosyVoice2 is a multilingual speech synthesis model supporting:
    - Multiple languages (Chinese, English, Japanese, Korean, Cantonese)
    - Voice cloning from short audio samples (zero-shot)
    - Cross-lingual synthesis with language tags
    - Natural language instructions for speech control (instruct2)
    
    NOTE: CosyVoice2 does NOT support SFT mode with predefined speakers.
          Use zero-shot or cross-lingual synthesis instead.
    """

    def __init__(self):
        self.base_url = config.services.tts_base_url
        self.timeout = 60.0
        logger.info(f"✅ TTS service initialized: {self.base_url}")

    def _headers(self) -> Dict[str, str]:
        """Build request headers with optional authentication"""
        headers = {"Content-Type": "application/json"}
        if SERVICE_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {SERVICE_AUTH_TOKEN}"
        return headers

    async def publish_to_room(
        self,
        room_name: str,
        text: str,
        language: str = "en",
        streaming: bool = True,
    ) -> bool:
        """
        Publish TTS audio to LiveKit room using CosyVoice2
        
        Uses zero-shot or cross-lingual synthesis (NOT SFT mode).
        CosyVoice2 does NOT support predefined speaker IDs like "英文女", "中文女".
        
        Args:
            room_name: LiveKit room name to publish audio to
            text: Text to synthesize (max 1000 chars recommended)
            language: Language code (en, zh, jp, ko, yue)
            streaming: Enable streaming synthesis for lower latency
            
        Returns:
            True if successful, False otherwise
            
        Examples:
            # English synthesis
            await tts.publish_to_room(
                room_name="room123",
                text="Hello world",
                language="en"
            )
            
            # Chinese synthesis
            await tts.publish_to_room(
                room_name="room123",
                text="你好世界",
                language="zh"
            )
        """
        try:
            # Validate input
            if not text or len(text.strip()) == 0:
                logger.warning("Empty text provided to TTS")
                return False

            # Truncate if too long (CosyVoice2 works best with shorter texts)
            if len(text) > 1000:
                logger.warning(f"Text too long ({len(text)} chars), truncating to 1000")
                text = text[:1000]

            logger.info(f"📢 TTS request for room '{room_name}': {text[:50]}...")

            # Build request payload for CosyVoice2
            payload = {
                "text": text,
                "room_name": room_name,
                "language": language,
                "stream": streaming,
            }

            logger.info(f"🎤 Language: {language}, streaming: {streaming}")

            # Send request to TTS service
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/tts/synthesize",
                    json=payload,
                    headers=self._headers(),
                )

                if response.status_code == 200:
                    result = response.json()
                    chunks = result.get('chunks_sent', 0)
                    duration = result.get('synthesis_time_ms', 0)
                    logger.info(f"✅ TTS published: {chunks} chunks, {duration:.0f}ms")
                    return True
                elif response.status_code == 503:
                    logger.error("❌ TTS service unavailable (503) - may be loading models")
                    return False
                else:
                    error_detail = response.text[:200]
                    logger.error(f"❌ TTS service error: {response.status_code} - {error_detail}")
                    return False
                    
        except httpx.TimeoutException:
            logger.error(
                f"❌ TTS timeout after {self.timeout}s - "
                "CosyVoice2 may be loading models or processing queue is full"
            )
            return False
            
        except httpx.ConnectError as e:
            logger.error(f"❌ Cannot connect to TTS service at {self.base_url}: {e}")
            return False
            
        except Exception as e:
            logger.error(f"❌ TTS error: {e}", exc_info=True)
            return False

    async def health_check(self) -> Dict[str, Any]:
        """Check if TTS service is healthy and get status
        
        Returns:
            Dictionary with health status and service info
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers=self._headers()
                )
                
                if response.status_code == 200:
                    return {
                        "healthy": True,
                        "service": "cosyvoice2",
                        "details": response.json()
                    }
                else:
                    return {
                        "healthy": False,
                        "service": "cosyvoice2",
                        "error": f"HTTP {response.status_code}"
                    }
                    
        except Exception as e:
            return {
                "healthy": False,
                "service": "cosyvoice2",
                "error": str(e)
            }

    def get_available_languages(self) -> List[str]:
        """Get list of supported languages"""
        return ["en", "zh", "jp", "ko", "yue"]

    async def get_stats(self) -> Optional[Dict[str, Any]]:
        """Get TTS service statistics
        
        Returns:
            Dictionary with service stats or None if request fails
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/stats",
                    headers=self._headers()
                )
                
                if response.status_code == 200:
                    return response.json()
                    
                logger.error(f"Failed to get stats: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return None


# Global service instance
tts_service = TTSService()
