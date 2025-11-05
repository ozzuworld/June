"""CosyVoice2 TTS Service Client

Official CosyVoice2 integration for June Orchestrator.
Supports three synthesis modes: SFT (predefined speakers), Zero-Shot (voice cloning), and Instruct.
"""
import logging
import os
import httpx
from typing import Optional, Dict, Any

from ..config import config

logger = logging.getLogger(__name__)

# Service-to-service auth token
SERVICE_AUTH_TOKEN = os.getenv("SERVICE_AUTH_TOKEN", "")

# CosyVoice2 default speakers (SFT mode)
DEFAULT_SPEAKERS = {
    "zh_female": "中文女",
    "zh_male": "中文男",
    "en_female": "英文女",
    "en_male": "英文男",
    "jp_male": "日语男",
    "yue_female": "粤语女",
    "ko_female": "韩语女"
}


class TTSService:
    """CosyVoice2 TTS service client"""

    def __init__(self):
        self.base_url = config.services.tts_base_url
        self.timeout = 60.0
        logger.info(f"✅ TTS service initialized: {self.base_url}")

    def _headers(self) -> Dict[str, str]:
        """Build request headers"""
        headers = {"Content-Type": "application/json"}
        if SERVICE_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {SERVICE_AUTH_TOKEN}"
        return headers

    async def publish_to_room(
        self,
        room_name: str,
        text: str,
        language: str = "en",
        speaker_id: Optional[str] = None,
        prompt_audio: Optional[str] = None,
        prompt_text: Optional[str] = None,
        instruct: Optional[str] = None,
        speed: float = 1.0,
        streaming: bool = True,
    ) -> bool:
        """
        Publish TTS audio to LiveKit room using CosyVoice2
        
        Args:
            room_name: LiveKit room name
            text: Text to synthesize
            language: Language code (en, zh, jp, ko, yue)
            speaker_id: SFT mode speaker ID (e.g., "中文女", "英文男")
            prompt_audio: Path to reference audio for zero-shot voice cloning
            prompt_text: Transcript of prompt_audio for zero-shot
            instruct: Natural language instruction for instruct mode
            speed: Speech speed (0.5-2.0)
            streaming: Enable streaming synthesis
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Validate input
            if not text or len(text.strip()) == 0:
                logger.warning("Empty text provided")
                return False

            # Truncate if too long
            if len(text) > 1000:
                logger.warning(f"Text too long ({len(text)} chars), truncating to 1000")
                text = text[:1000]

            logger.info(f"📢 TTS request for room '{room_name}': {text[:50]}...")

            # Build request payload based on mode
            payload = {
                "text": text,
                "room_name": room_name,
                "streaming": streaming,
                "speed": speed,
            }

            # Determine synthesis mode
            if instruct and prompt_audio:
                # Instruct mode (instruction-based synthesis)
                payload["mode"] = "instruct"
                payload["instruct"] = instruct
                payload["prompt_audio"] = prompt_audio
                logger.info(f"🎤 Mode: instruct, instruction: {instruct[:30]}...")
                
            elif prompt_audio and prompt_text:
                # Zero-shot mode (voice cloning)
                payload["mode"] = "zero_shot"
                payload["prompt_audio"] = prompt_audio
                payload["prompt_text"] = prompt_text
                logger.info(f"🎤 Mode: zero_shot, cloning from: {prompt_audio}")
                
            else:
                # SFT mode (predefined speakers) - DEFAULT
                payload["mode"] = "sft"
                
                # Map language to default speaker if not provided
                if speaker_id:
                    payload["speaker_id"] = speaker_id
                elif language == "zh":
                    payload["speaker_id"] = DEFAULT_SPEAKERS["zh_female"]
                elif language == "en":
                    payload["speaker_id"] = DEFAULT_SPEAKERS["en_female"]
                elif language == "jp":
                    payload["speaker_id"] = DEFAULT_SPEAKERS["jp_male"]
                elif language == "ko":
                    payload["speaker_id"] = DEFAULT_SPEAKERS["ko_female"]
                elif language == "yue":
                    payload["speaker_id"] = DEFAULT_SPEAKERS["yue_female"]
                else:
                    # Default fallback
                    payload["speaker_id"] = DEFAULT_SPEAKERS["en_female"]
                
                logger.info(f"🎤 Mode: sft, speaker: {payload['speaker_id']}")

            # Send request to TTS service
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/tts/synthesize",
                    json=payload,
                    headers=self._headers(),
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(
                        f"✅ TTS published: {result.get('chunks_sent', 0)} chunks, "
                        f"{result.get('duration_ms', 0):.0f}ms"
                    )
                    return True
                else:
                    logger.error(
                        f"❌ TTS service error: {response.status_code} - {response.text[:200]}"
                    )
                    return False
                    
        except httpx.TimeoutException:
            logger.error(
                f"❌ TTS timeout after {self.timeout}s - "
                "service may be loading models or overloaded"
            )
            return False
            
        except httpx.ConnectError as e:
            logger.error(f"❌ Cannot connect to TTS service at {self.base_url}: {e}")
            return False
            
        except Exception as e:
            logger.error(f"❌ TTS error: {e}")
            return False

    async def list_speakers(self) -> Optional[Dict[str, Any]]:
        """List available SFT speakers from CosyVoice2"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/speakers",
                    headers=self._headers()
                )
                
                if response.status_code == 200:
                    return response.json()
                    
                logger.error(f"Failed to list speakers: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error listing speakers: {e}")
            return None

    async def health_check(self) -> bool:
        """Check if TTS service is healthy"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers=self._headers()
                )
                return response.status_code == 200
                
        except Exception:
            return False

    def get_default_speaker(self, language: str = "en") -> str:
        """Get default speaker for language"""
        if language == "zh":
            return DEFAULT_SPEAKERS["zh_female"]
        elif language == "jp":
            return DEFAULT_SPEAKERS["jp_male"]
        elif language == "ko":
            return DEFAULT_SPEAKERS["ko_female"]
        elif language == "yue":
            return DEFAULT_SPEAKERS["yue_female"]
        else:
            return DEFAULT_SPEAKERS["en_female"]


# Global service instance
tts_service = TTSService()