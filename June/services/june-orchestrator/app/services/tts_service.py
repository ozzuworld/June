"""CosyVoice2 TTS Service Client - Enhanced

Official CosyVoice2 integration for June Orchestrator.
Supports three synthesis modes:
1. SFT (Supervised Fine-Tuning) - Predefined speakers (fastest, most stable)
2. Zero-Shot - Voice cloning from reference audio
3. Instruct - Natural language control of speech characteristics

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

# CosyVoice2 default speakers (SFT mode)
# These are built into the CosyVoice2-0.5B model
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
    """CosyVoice2 TTS service client
    
    This client communicates with the june-tts service which runs CosyVoice2.
    CosyVoice2 is a multilingual speech synthesis model supporting:
    - Multiple languages (Chinese, English, Japanese, Korean, Cantonese)
    - Voice cloning from short audio samples
    - Natural language instructions for speech control
    - Streaming synthesis for low latency
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
        speaker_id: Optional[str] = None,
        prompt_audio: Optional[str] = None,
        prompt_text: Optional[str] = None,
        instruct: Optional[str] = None,
        speed: float = 1.0,
        streaming: bool = True,
    ) -> bool:
        """
        Publish TTS audio to LiveKit room using CosyVoice2
        
        Mode Selection (automatic based on parameters):
        1. Instruct mode: Provide both 'instruct' and 'prompt_audio'
        2. Zero-shot mode: Provide both 'prompt_audio' and 'prompt_text'
        3. SFT mode: Default, uses predefined 'speaker_id'
        
        Args:
            room_name: LiveKit room name to publish audio to
            text: Text to synthesize (max 1000 chars recommended)
            language: Language code (en, zh, jp, ko, yue)
            speaker_id: SFT mode speaker ID (e.g., "中文女", "英文男")
            prompt_audio: Path to reference audio for zero-shot/instruct
            prompt_text: Transcript of prompt_audio (for zero-shot)
            instruct: Natural language instruction (e.g., "Speak slowly and cheerfully")
            speed: Speech speed multiplier (0.5-2.0)
            streaming: Enable streaming synthesis for lower latency
            
        Returns:
            True if successful, False otherwise
            
        Examples:
            # SFT mode (predefined speaker)
            await tts.publish_to_room(
                room_name="room123",
                text="Hello world",
                language="en",
                speaker_id="英文女"
            )
            
            # Zero-shot mode (voice cloning)
            await tts.publish_to_room(
                room_name="room123",
                text="Hello in cloned voice",
                prompt_audio="path/to/reference.wav",
                prompt_text="Reference audio transcript"
            )
            
            # Instruct mode (controlled synthesis)
            await tts.publish_to_room(
                room_name="room123",
                text="Hello with emotion",
                prompt_audio="path/to/reference.wav",
                instruct="Speak with excitement and energy"
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

            # Build request payload based on mode
            payload = {
                "text": text,
                "room_name": room_name,
                "streaming": streaming,
                "speed": max(0.5, min(2.0, speed)),  # Clamp to valid range
            }

            # Determine synthesis mode (priority: instruct > zero_shot > sft)
            if instruct and prompt_audio:
                # Instruct mode: Natural language control
                payload["mode"] = "instruct"
                payload["instruct"] = instruct
                payload["prompt_audio"] = prompt_audio
                logger.info(f"🎤 Mode: instruct, instruction: '{instruct[:50]}...'")
                
            elif prompt_audio and prompt_text:
                # Zero-shot mode: Voice cloning
                payload["mode"] = "zero_shot"
                payload["prompt_audio"] = prompt_audio
                payload["prompt_text"] = prompt_text
                logger.info(f"🎤 Mode: zero_shot, cloning from: {prompt_audio}")
                
            else:
                # SFT mode: Predefined speakers (DEFAULT and most stable)
                payload["mode"] = "sft"
                
                # Auto-select speaker based on language if not provided
                if speaker_id:
                    payload["speaker_id"] = speaker_id
                else:
                    payload["speaker_id"] = self._get_default_speaker_for_language(language)
                
                logger.info(f"🎤 Mode: sft, speaker: {payload['speaker_id']}, lang: {language}")

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
                    duration = result.get('duration_ms', 0)
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

    def _get_default_speaker_for_language(self, language: str) -> str:
        """Get default speaker for language"""
        language_mapping = {
            "zh": DEFAULT_SPEAKERS["zh_female"],
            "en": DEFAULT_SPEAKERS["en_female"],
            "jp": DEFAULT_SPEAKERS["jp_male"],
            "ko": DEFAULT_SPEAKERS["ko_female"],
            "yue": DEFAULT_SPEAKERS["yue_female"],
        }
        return language_mapping.get(language, DEFAULT_SPEAKERS["en_female"])

    async def list_speakers(self) -> Optional[Dict[str, Any]]:
        """List available SFT speakers from CosyVoice2 service
        
        Returns:
            Dictionary of available speakers or None if request fails
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/speakers",
                    headers=self._headers()
                )
                
                if response.status_code == 200:
                    return response.json()
                    
                logger.error(f"Failed to list speakers: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error listing speakers: {e}")
            return None

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

    def get_default_speaker(self, language: str = "en") -> str:
        """Get default speaker ID for language
        
        Args:
            language: Language code
            
        Returns:
            CosyVoice2 speaker ID
        """
        return self._get_default_speaker_for_language(language)


# Global service instance
tts_service = TTSService()