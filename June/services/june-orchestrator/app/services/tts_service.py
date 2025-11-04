"""TTS service client with Chatterbox integration and voice mode support (recommended API)

This client calls the canonical TTS endpoint /api/tts/synthesize directly and includes service auth.
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
    """TTS service client using the canonical /api/tts/synthesize endpoint"""

    def __init__(self):
        self.base_url = config.services.tts_base_url
        self.timeout = 30.0

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
        Publish streaming Chatterbox TTS audio directly to LiveKit room via /api/tts/synthesize
        """
        try:
            if not text or len(text.strip()) == 0:
                return False

            if len(text) > 1000:
                text = text[:1000] + "..."

            # Determine voice mode
            voice_mode = "clone" if voice_reference else "predefined"
            logger.info(
                f"📢 Publishing Chatterbox TTS ({voice_mode}) to room '{room_name}': {text[:50]}..."
            )

            payload = {
                "text": text,
                "room_name": room_name,
                "voice_mode": voice_mode,
                "language": language,
                "speed": speed,
                "emotion_level": emotion_level,
                "temperature": temperature,
                "cfg_weight": cfg_weight,
                "streaming": True,
            }

            if predefined_voice_id and voice_mode == "predefined":
                payload["predefined_voice_id"] = predefined_voice_id
            if voice_reference and voice_mode == "clone":
                payload["voice_reference"] = voice_reference
            if seed is not None:
                payload["seed"] = seed

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/tts/synthesize",
                    json=payload,
                    headers=self._headers(),
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(
                        f"✅ Chatterbox TTS published: {result.get('chunks_sent', 0)} chunks, {result.get('duration_ms', 0):.0f}ms"
                    )
                    return True
                else:
                    logger.error(
                        f"Chatterbox TTS error: {response.status_code} - {response.text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Chatterbox TTS publish error: {e}")
            return False

    async def list_voices(self) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/api/voices", headers=self._headers())
                if resp.status_code == 200:
                    return resp.json()
                logger.error(f"list_voices error: {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"list_voices exception: {e}")
            return None

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/health", headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False


# Global service instance
tts_service = TTSService()
