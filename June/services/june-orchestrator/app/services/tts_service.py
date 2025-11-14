"""Chatterbox TTS Service Client - PostgreSQL Voice Integration

MIGRATION: Fish Speech → Chatterbox (Resemble AI)
- MIT License (truly open-source, commercial use allowed)
- 23 languages supported (multilingual model)
- Emotion control via exaggeration parameter
- Beats ElevenLabs in blind tests (63.75% preference)
- Uses voice cloning from reference audio (10-30s recommended)

API COMPATIBILITY:
- Same endpoints as previous TTS services
- Same voice management (PostgreSQL)
- Enhanced: Emotion intensity control (exaggeration: 0.0-2.0)
- Enhanced: Voice adherence control (cfg_weight: 0.0-1.0)
- Enhanced: Language selection for multilingual model

KEY FEATURES:
1. ✅ Truly open-source (MIT License, no user limits)
2. ✅ 23 language support with zero-shot voice cloning
3. ✅ Emotion/exaggeration control for expressive speech
4. ✅ Production-grade quality
5. ✅ No commercial restrictions
"""
import logging
import os
import socket
import time
import httpx
from typing import Optional, Dict, Any, List
import json

from ..config import config

logger = logging.getLogger(__name__)

SERVICE_AUTH_TOKEN = os.getenv("SERVICE_AUTH_TOKEN", "")


class TTSService:
    """Chatterbox TTS service client with PostgreSQL voice storage

    Chatterbox uses voice cloning from reference audio (10-30s recommended).
    Supports emotion control via exaggeration parameter (0.0-2.0).
    Multilingual model supports 23 languages.
    Each voice has a unique voice_id stored in PostgreSQL.
    """

    def __init__(self):
        self.base_url = config.services.tts_base_url

        # ✅ OPTIMIZED: Increased timeout with separate components
        self.timeout = httpx.Timeout(
            connect=10.0,   # Connection timeout - OK
            read=120.0,     # ← Chatterbox may take longer than Fish Speech
            write=10.0,     # Write timeout - OK
            pool=None       # No pool timeout
        )

        logger.info(f"✅ Chatterbox TTS service initialized: {self.base_url}")
        logger.info(f"⏱️  Timeout config: connect=10s, read=120s, write=10s")
        logger.info(f"🎭 Emotion support: exaggeration control (0.0-2.0)")
        logger.info(f"🌍 Languages: 23 languages supported")
        self._log_network_debug()

    def _log_network_debug(self):
        """Log network and DNS information for debugging"""
        try:
            logger.info("="*80)
            logger.info("🔍 CHATTERBOX TTS SERVICE NETWORK DEBUG")
            logger.info("="*80)
            
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            hostname = parsed.hostname or parsed.netloc
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            
            logger.info(f"📋 Configuration:")
            logger.info(f"   Base URL: {self.base_url}")
            logger.info(f"   Hostname: {hostname}")
            logger.info(f"   Port: {port}")
            
            if hostname:
                try:
                    logger.info(f"\n🌐 DNS Resolution for '{hostname}':")
                    ip_addresses = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
                    for family, socktype, proto, canonname, sockaddr in ip_addresses:
                        logger.info(f"   ✅ Resolved to: {sockaddr[0]}:{sockaddr[1]}")
                except Exception as e:
                    logger.error(f"   ❌ DNS resolution failed: {e}")
            
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"❌ Network debug failed: {e}")

    def _headers(self) -> Dict[str, str]:
        """Build request headers with authentication"""
        headers = {"Content-Type": "application/json"}
        if SERVICE_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {SERVICE_AUTH_TOKEN}"
        return headers

    async def publish_to_room(
        self,
        room_name: str,
        text: str,
        voice_id: str = "default",
        streaming: bool = True,
        exaggeration: float = 0.5,
        language: str = "en",
    ) -> bool:
        """
        Publish Chatterbox TTS audio to LiveKit room

        Supports emotion control via exaggeration parameter.
        Supports 23 languages via language parameter.

        Args:
            room_name: LiveKit room name
            text: Text to synthesize
            voice_id: Voice ID from PostgreSQL database
            streaming: Legacy parameter (kept for compatibility)
            exaggeration: Emotion intensity 0.0=flat, 0.5=normal, 2.0=very expressive
            language: Language code (en, es, fr, de, it, pt, ru, ja, ko, zh, ar, hi, etc.)

        Returns:
            True if successful, False otherwise
        """
        request_start_time = time.time()
        
        try:
            if not text or len(text.strip()) == 0:
                logger.warning("Empty text provided to XTTS")
                return False

            if len(text) > 1000:
                logger.warning(f"Text too long ({len(text)} chars), truncating to 1000")
                text = text[:1000]

            logger.info(f"📢 Chatterbox TTS request for room '{room_name}': {text[:50]}...")
            logger.info(f"📊 Text length: {len(text)} chars")

            # Chatterbox payload format (backward compatible with previous services)
            payload = {
                "text": text,
                "room_name": room_name,
                "voice_id": voice_id,
                "language": language,
                "exaggeration": exaggeration,
            }

            logger.info(f"🎤 Voice: {voice_id}, Language: {language}, Exaggeration: {exaggeration}")

            full_url = f"{self.base_url}/api/tts/synthesize"

            logger.info("="*80)
            logger.info("🚀 CHATTERBOX TTS REQUEST")
            logger.info(f"📍 URL: {full_url}")
            logger.info(f"📦 Payload: {json.dumps(payload, indent=2)}")
            
            connection_start = time.time()

            # ✅ Use configured timeout (now 90s read)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"🔄 Sending POST request...")
                
                response = await client.post(
                    full_url,
                    json=payload,
                    headers=self._headers(),
                )
                
                connection_time = (time.time() - connection_start) * 1000
                logger.info(f"⏱️  Connection: {connection_time:.2f}ms")
                
                logger.info(f"\n📨 RESPONSE:")
                logger.info(f"   Status: {response.status_code}")
                logger.info(f"   Body: {response.text[:500]}")
                
                if response.status_code == 200:
                    result = response.json()
                    total_time = (time.time() - request_start_time) * 1000
                    logger.info(f"\n✅ CHATTERBOX TTS SUCCESS:")
                    logger.info(f"   Model: {result.get('mode', 'chatterbox')}")
                    logger.info(f"   Type: {result.get('model_type', 'multilingual')}")
                    logger.info(f"   Synthesis: {result.get('total_time_ms', 0):.0f}ms")
                    logger.info(f"   Total: {total_time:.0f}ms")
                    logger.info("="*80)
                    return True
                elif response.status_code == 503:
                    logger.error(f"\n❌ Chatterbox TTS unavailable (503)")
                    logger.error("="*80)
                    return False
                else:
                    logger.error(f"\n❌ Chatterbox TTS error: {response.status_code}")
                    logger.error(f"   Detail: {response.text[:200]}")
                    logger.error("="*80)
                    return False
                    
        except httpx.TimeoutException as e:
            total = (time.time() - request_start_time) * 1000
            logger.error("="*80)
            logger.error(f"⏱️  TIMEOUT after {total:.0f}ms: {e}")
            logger.error(f"   Text length: {len(text)} chars")
            logger.error(f"   Text preview: '{text[:100]}...'")
            logger.error("="*80)
            return False
            
        except httpx.ConnectError as e:
            logger.error("="*80)
            logger.error(f"🔌 CONNECTION ERROR: {e}")
            logger.error("="*80)
            return False
            
        except Exception as e:
            logger.error("="*80)
            logger.error(f"❌ UNEXPECTED ERROR: {e}", exc_info=True)
            logger.error("="*80)
            return False

    async def clone_voice(
        self,
        voice_id: str,
        voice_name: str,
        audio_file_path: str
    ) -> Dict[str, Any]:
        """
        Clone a voice and store in PostgreSQL

        Chatterbox recommends 10-30 seconds of clear reference audio.

        Args:
            voice_id: Unique identifier for the voice
            voice_name: Human-readable name
            audio_file_path: Path to reference audio (10-30s recommended, WAV/MP3/FLAC/M4A)

        Returns:
            Response dict with status and details
        """
        try:
            logger.info(f"🎭 Cloning voice '{voice_id}' from {audio_file_path}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                with open(audio_file_path, 'rb') as f:
                    files = {'file': (os.path.basename(audio_file_path), f)}
                    data = {
                        'voice_id': voice_id,
                        'voice_name': voice_name
                    }
                    
                    response = await client.post(
                        f"{self.base_url}/api/voices/clone",
                        files=files,
                        data=data,
                        headers={"Authorization": f"Bearer {SERVICE_AUTH_TOKEN}"} if SERVICE_AUTH_TOKEN else {}
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        logger.info(f"✅ Voice '{voice_id}' cloned successfully")
                        return result
                    else:
                        logger.error(f"❌ Voice cloning failed: {response.status_code}")
                        return {"status": "error", "detail": response.text}
                        
        except Exception as e:
            logger.error(f"❌ Voice cloning error: {e}")
            return {"status": "error", "detail": str(e)}

    async def list_voices(self) -> List[Dict[str, Any]]:
        """
        List all available voices from PostgreSQL
        
        Returns:
            List of voice dicts with id, name, size, timestamps
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/voices",
                    headers=self._headers()
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("voices", [])
                else:
                    logger.error(f"Failed to list voices: {response.status_code}")
                    return []
                    
        except Exception as e:
            logger.error(f"Error listing voices: {e}")
            return []

    async def get_voice_info(self, voice_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed info about a specific voice
        
        Args:
            voice_id: Voice identifier
            
        Returns:
            Voice info dict or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/voices/{voice_id}",
                    headers=self._headers()
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    logger.warning(f"Voice '{voice_id}' not found")
                    return None
                else:
                    logger.error(f"Failed to get voice info: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting voice info: {e}")
            return None

    async def delete_voice(self, voice_id: str) -> bool:
        """
        Delete a voice from PostgreSQL
        
        Args:
            voice_id: Voice to delete
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(
                    f"{self.base_url}/api/voices/{voice_id}",
                    headers=self._headers()
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Voice '{voice_id}' deleted")
                    return True
                else:
                    logger.error(f"Failed to delete voice: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error deleting voice: {e}")
            return False

    async def health_check(self) -> Dict[str, Any]:
        """Check Chatterbox TTS service health"""
        try:
            logger.info(f"🏥 Health check: {self.base_url}/health")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers=self._headers()
                )

                if response.status_code == 200:
                    return {
                        "healthy": True,
                        "service": "chatterbox_tts",
                        "details": response.json()
                    }
                else:
                    return {
                        "healthy": False,
                        "service": "chatterbox_tts",
                        "error": f"HTTP {response.status_code}"
                    }

        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            return {
                "healthy": False,
                "service": "chatterbox_tts",
                "error": str(e)
            }

    async def get_stats(self) -> Optional[Dict[str, Any]]:
        """Get Chatterbox TTS service statistics"""
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