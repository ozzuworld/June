"""TTS service client with CosyVoice2 compatibility and Chatterbox integration

This client is adapted to work with the CosyVoice2 TTS service API structure.
"""
import logging
import os
import httpx
from typing import Optional, Dict, Any

from ..config import config

logger = logging.getLogger(__name__)

# Read service-to-service auth token from env or config
SERVICE_AUTH_TOKEN = os.getenv("SERVICE_AUTH_TOKEN", "")

class TTSService:
    """TTS service client compatible with CosyVoice2 /api/tts/synthesize endpoint"""

    def __init__(self):
        self.base_url = config.services.tts_base_url
        self.timeout = 60.0  # Increased timeout for model processing

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if SERVICE_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {SERVICE_AUTH_TOKEN}"
        return headers

    async def publish_to_room(
        self,
        room_name: str,
        text: str,
        language: str = "en",
        predefined_voice_id: Optional[str] = None,
        voice_reference: Optional[str] = None,
        speed: float = 1.0,
        emotion_level: float = 0.5,
        temperature: float = 0.9,
        cfg_weight: float = 0.3,
        seed: Optional[int] = None,
    ) -> bool:
        """
        Publish streaming CosyVoice2 TTS audio directly to LiveKit room via /api/tts/synthesize
        """
        try:
            if not text or len(text.strip()) == 0:
                return False

            if len(text) > 1000:
                text = text[:1000] + "..."

            logger.info(
                f"📢 Publishing CosyVoice2 TTS to room '{room_name}': {text[:50]}..."
            )

            # Map to CosyVoice2 API structure
            payload = {
                "text": text,
                "room_name": room_name,
                "streaming": True,
                "speed": speed,
            }

            # Determine synthesis mode based on available parameters
            if voice_reference:
                # Zero-shot voice cloning mode
                payload["mode"] = "zero_shot"
                payload["prompt_audio"] = voice_reference
                # Use text as prompt_text if not provided separately
                payload["prompt_text"] = "This is a reference voice for cloning."
            elif predefined_voice_id:
                # SFT mode with predefined speaker
                payload["mode"] = "sft"
                payload["speaker_id"] = predefined_voice_id
            else:
                # Default to SFT mode with default speaker
                payload["mode"] = "sft"
                payload["speaker_id"] = "中文女"  # Default CosyVoice2 speaker

            logger.info(f"🎤 CosyVoice2 mode: {payload['mode']}, speaker: {payload.get('speaker_id', 'N/A')}")

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/tts/synthesize",
                    json=payload,
                    headers=self._headers(),
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(
                        f"✅ CosyVoice2 TTS published: {result.get('chunks_sent', 0)} chunks, {result.get('duration_ms', 0):.0f}ms"
                    )
                    return True
                else:
                    logger.error(
                        f"CosyVoice2 TTS error: {response.status_code} - {response.text}"
                    )
                    return False
                    
        except httpx.TimeoutException:
            logger.error(f"CosyVoice2 TTS timeout after {self.timeout}s - model may be loading or overloaded")
            return False
        except Exception as e:
            logger.error(f"CosyVoice2 TTS publish error: {e}")
            return False

    async def list_voices(self) -> Optional[Dict[str, Any]]:
        """List available speakers from CosyVoice2"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/speakers", headers=self._headers())
                if resp.status_code == 200:
                    return resp.json()
                logger.error(f"list_voices error: {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"list_voices exception: {e}")
            return None

    async def health_check(self) -> bool:
        """Check if CosyVoice2 TTS service is healthy"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/health", headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False


# Global service instance
tts_service = TTSService()