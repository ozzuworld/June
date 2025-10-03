# June/services/june-orchestrator/tts_client.py
# TTS Client for external TTS service with service-to-service auth

import os
import base64
import time
import asyncio
from typing import Optional, Dict, Any
import logging
import httpx
from fastapi import HTTPException

from service_auth import get_service_auth_headers

logger = logging.getLogger(__name__)


class TTSClient:
    def __init__(self):
        self.tts_url = os.getenv("TTS_SERVICE_URL", "http://localhost:8000")
        self.timeout = httpx.Timeout(30.0, connect=5.0)
        self.default_voice = os.getenv("TTS_DEFAULT_VOICE", "default")
        self.default_speed = float(os.getenv("TTS_DEFAULT_SPEED", "1.0"))
        self.default_language = os.getenv("TTS_DEFAULT_LANGUAGE", "EN")
        
    async def synthesize_speech(
        self,
        text: str,
        voice: str = None,
        speed: float = None,
        language: str = None,
        reference_audio_b64: Optional[str] = None
    ) -> Dict[str, Any]:
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        voice = voice or self.default_voice
        speed = speed or self.default_speed
        language = language or self.default_language
        
        try:
            if reference_audio_b64:
                audio_data = await self._synthesize_with_cloning(
                    text, reference_audio_b64, speed, language
                )
            else:
                audio_data = await self._synthesize_standard(
                    text, voice, speed, language
                )

            return {
                "audio_data": audio_data,
                "content_type": "audio/wav",
                "size_bytes": len(audio_data),
                "voice": voice,
                "speed": speed,
                "language": language,
                "generated_at": time.time()
            }
            
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")
    
    async def _synthesize_standard(
        self, 
        text: str, 
        voice: str, 
        speed: float, 
        language: str
    ) -> bytes:
        """Standard TTS synthesis with service authentication"""
        
        # Get service auth headers
        auth_headers = await get_service_auth_headers()
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.tts_url}/v1/tts",
                json={
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "language": language,
                    "format": "wav"
                },
                headers={
                    **auth_headers,
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"TTS service returned {response.status_code}: {response.text}")
            
            return response.content
    
    async def _synthesize_with_cloning(
        self, 
        text: str, 
        reference_audio_b64: str, 
        speed: float, 
        language: str
    ) -> bytes:
        """Voice cloning synthesis with service authentication"""
        
        # Get service auth headers
        auth_headers = await get_service_auth_headers()
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.tts_url}/tts/generate",
                json={
                    "text": text,
                    "reference_b64": reference_audio_b64,
                    "language": language.lower(),
                    "speed": speed,
                    "volume": 1.0,
                    "pitch": 0.0,
                    "format": "wav"
                },
                headers={
                    **auth_headers,
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code != 200:
                raise Exception(f"TTS cloning service returned {response.status_code}: {response.text}")
            
            return response.content
    
    async def get_status(self) -> Dict[str, Any]:
        try:
            # Get service auth headers
            auth_headers = await get_service_auth_headers()
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(
                    f"{self.tts_url}/healthz",
                    headers=auth_headers
                )
                
                if response.status_code == 200:
                    return {"available": True, "url": self.tts_url, "authenticated": True}
                else:
                    return {"available": False, "error": f"Status check failed: {response.status_code}"}
                    
        except Exception as e:
            logger.warning(f"TTS status check failed: {e}")
            return {"available": False, "error": str(e)}


_tts_client: Optional[TTSClient] = None


def get_tts_client() -> TTSClient:
    global _tts_client
    if _tts_client is None:
        _tts_client = TTSClient()
    return _tts_client