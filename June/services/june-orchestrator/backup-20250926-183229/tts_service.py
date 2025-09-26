# June/services/june-orchestrator/tts_service.py
# Enhanced TTS Service Integration with Audio Response Pipeline

import asyncio
import logging
import os
import base64
import hashlib
import time
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from external_tts_client import ExternalTTSClient
from shared.auth import get_auth_service

logger = logging.getLogger(__name__)

class TTSProvider(Enum):
    EXTERNAL_OPENVOICE = "external_openvoice"
    LOCAL_TTS = "local_tts"  # For future expansion
    FALLBACK = "fallback"

@dataclass
class AudioResponse:
    """Container for TTS audio response"""
    audio_data: bytes
    content_type: str = "audio/wav"
    duration_ms: Optional[int] = None
    provider: str = "unknown"
    voice_id: str = "default"
    processing_time_ms: int = 0
    text_hash: str = ""
    cached: bool = False

class TTSService:
    """Enhanced TTS Service with caching, fallback, and audio pipeline"""
    
    def __init__(self):
        self.external_tts_url = os.getenv("EXTERNAL_TTS_URL", "http://localhost:8001")
        self.auth_client = get_auth_service()
        self.external_client = None
        self.audio_cache = {}  # Simple in-memory cache
        self.cache_ttl = 3600  # 1 hour
        self.max_cache_size = 100
        
        # TTS Configuration
        self.default_voice = os.getenv("TTS_DEFAULT_VOICE", "default")
        self.default_speed = float(os.getenv("TTS_DEFAULT_SPEED", "1.0"))
        self.default_language = os.getenv("TTS_DEFAULT_LANGUAGE", "EN")
        
        # Quality settings
        self.enable_caching = os.getenv("TTS_ENABLE_CACHING", "true").lower() == "true"
        self.enable_fallback = os.getenv("TTS_ENABLE_FALLBACK", "true").lower() == "true"
        
        logger.info(f"🎵 TTS Service initialized - External URL: {self.external_tts_url}")
    
    async def initialize(self) -> bool:
        """Initialize TTS service and test connections"""
        try:
            # Initialize external TTS client
            if self.external_tts_url:
                self.external_client = ExternalTTSClient(
                    base_url=self.external_tts_url,
                    auth_client=self.auth_client
                )
                
                # Test connection
                if await self.external_client.health_check():
                    logger.info("✅ External TTS service connected successfully")
                    return True
                else:
                    logger.warning("⚠️ External TTS service not available")
            
            return False
            
        except Exception as e:
            logger.error(f"❌ TTS service initialization failed: {e}")
            return False
    
    def _generate_text_hash(self, text: str, voice: str, speed: float, language: str) -> str:
        """Generate cache key for TTS request"""
        cache_string = f"{text}|{voice}|{speed}|{language}"
        return hashlib.md5(cache_string.encode()).hexdigest()
    
    def _is_cache_valid(self, cache_entry: Dict) -> bool:
        """Check if cache entry is still valid"""
        if not self.enable_caching:
            return False
        
        cache_time = cache_entry.get("timestamp", 0)
        return time.time() - cache_time < self.cache_ttl
    
    def _cleanup_cache(self):
        """Remove expired entries and maintain cache size"""
        if not self.enable_caching:
            return
        
        current_time = time.time()
        
        # Remove expired entries
        expired_keys = [
            key for key, entry in self.audio_cache.items()
            if current_time - entry.get("timestamp", 0) >= self.cache_ttl
        ]
        
        for key in expired_keys:
            del self.audio_cache[key]
        
        # Limit cache size (remove oldest entries)
        if len(self.audio_cache) > self.max_cache_size:
            # Sort by timestamp and remove oldest
            sorted_entries = sorted(
                self.audio_cache.items(),
                key=lambda x: x[1].get("timestamp", 0)
            )
            
            keys_to_remove = [item[0] for item in sorted_entries[:len(self.audio_cache) - self.max_cache_size]]
            for key in keys_to_remove:
                del self.audio_cache[key]
        
        logger.debug(f"Cache cleanup: {len(self.audio_cache)} entries remaining")
    
    async def synthesize_speech_for_response(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        language: Optional[str] = None,
        user_preferences: Dict = None
    ) -> AudioResponse:
        """Main method to convert AI response text to speech"""
        
        start_time = time.time()
        
        # Apply defaults and user preferences
        voice = voice or (user_preferences or {}).get("preferred_voice") or self.default_voice
        speed = speed or (user_preferences or {}).get("speech_speed") or self.default_speed
        language = language or (user_preferences or {}).get("language") or self.default_language
        
        # Input validation
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        text = text.strip()
        
        # Generate cache key
        text_hash = self._generate_text_hash(text, voice, speed, language)
        
        # Check cache first
        if self.enable_caching and text_hash in self.audio_cache:
            cache_entry = self.audio_cache[text_hash]
            if self._is_cache_valid(cache_entry):
                logger.info(f"🎵 TTS Cache hit for: '{text[:50]}...'")
                
                return AudioResponse(
                    audio_data=cache_entry["audio_data"],
                    content_type=cache_entry["content_type"],
                    duration_ms=cache_entry.get("duration_ms"),
                    provider=cache_entry["provider"],
                    voice_id=voice,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    text_hash=text_hash,
                    cached=True
                )
        
        # Try external TTS service first
        audio_response = None
        
        if self.external_client:
            try:
                logger.info(f"🎵 Generating speech via external TTS: '{text[:50]}...'")
                
                audio_data = await self.external_client.synthesize_speech(
                    text=text,
                    voice=voice,
                    speed=speed,
                    language=language
                )
                
                audio_response = AudioResponse(
                    audio_data=audio_data,
                    content_type="audio/wav",
                    provider=TTSProvider.EXTERNAL_OPENVOICE.value,
                    voice_id=voice,
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    text_hash=text_hash,
                    cached=False
                )
                
                logger.info(f"✅ External TTS success: {len(audio_data)} bytes in {audio_response.processing_time_ms}ms")
                
            except Exception as e:
                logger.error(f"❌ External TTS failed: {e}")
                
                if not self.enable_fallback:
                    raise RuntimeError(f"TTS synthesis failed: {e}")
        
        # Fallback to simple TTS if external fails
        if not audio_response and self.enable_fallback:
            audio_response = await self._fallback_tts(text, voice, speed, language, text_hash, start_time)
        
        if not audio_response:
            raise RuntimeError("All TTS providers failed")
        
        # Cache the result
        if self.enable_caching:
            self.audio_cache[text_hash] = {
                "audio_data": audio_response.audio_data,
                "content_type": audio_response.content_type,
                "duration_ms": audio_response.duration_ms,
                "provider": audio_response.provider,
                "timestamp": time.time()
            }
            
            # Cleanup cache periodically
            if len(self.audio_cache) % 10 == 0:  # Every 10 additions
                self._cleanup_cache()
        
        return audio_response
    
    async def _fallback_tts(self, text: str, voice: str, speed: float, language: str, text_hash: str, start_time: float) -> AudioResponse:
        """Fallback TTS using basic text-to-speech (placeholder implementation)"""
        logger.info(f"🎵 Using fallback TTS for: '{text[:50]}...'")
        
        # This is a placeholder - in reality you'd implement a basic TTS
        # For now, we'll create a simple response
        try:
            # You could integrate with:
            # - gTTS (Google Text-to-Speech)
            # - pyttsx3 (offline TTS)
            # - Azure Speech Services
            # - AWS Polly
            
            # Placeholder: Create a minimal audio response
            placeholder_audio = b"\x00" * 1024  # Minimal WAV-like placeholder
            
            return AudioResponse(
                audio_data=placeholder_audio,
                content_type="audio/wav",
                provider=TTSProvider.FALLBACK.value,
                voice_id=voice,
                processing_time_ms=int((time.time() - start_time) * 1000),
                text_hash=text_hash,
                cached=False
            )
            
        except Exception as e:
            logger.error(f"❌ Fallback TTS also failed: {e}")
            return None
    
    async def clone_voice_for_response(
        self,
        text: str,
        reference_audio_bytes: bytes,
        language: Optional[str] = None
    ) -> AudioResponse:
        """Generate speech using voice cloning"""
        
        start_time = time.time()
        language = language or self.default_language
        
        if not self.external_client:
            raise RuntimeError("Voice cloning requires external TTS service")
        
        try:
            logger.info(f"🎤 Voice cloning for: '{text[:50]}...'")
            
            audio_data = await self.external_client.clone_voice(
                text=text,
                reference_audio_bytes=reference_audio_bytes,
                language=language
            )
            
            audio_response = AudioResponse(
                audio_data=audio_data,
                content_type="audio/wav",
                provider=f"{TTSProvider.EXTERNAL_OPENVOICE.value}_clone",
                voice_id="cloned",
                processing_time_ms=int((time.time() - start_time) * 1000),
                text_hash=hashlib.md5(text.encode()).hexdigest(),
                cached=False
            )
            
            logger.info(f"✅ Voice cloning success: {len(audio_data)} bytes in {audio_response.processing_time_ms}ms")
            return audio_response
            
        except Exception as e:
            logger.error(f"❌ Voice cloning failed: {e}")
            raise RuntimeError(f"Voice cloning failed: {e}")
    
    async def get_available_voices(self, language: str = None) -> Dict[str, Any]:
        """Get available voices from TTS service"""
        language = language or self.default_language
        
        if self.external_client:
            try:
                return await self.external_client.get_available_voices(language)
            except Exception as e:
                logger.error(f"❌ Failed to get voices: {e}")
        
        # Return fallback voices
        return {
            "voices": [
                {"id": "default", "name": "Default Voice", "language": language},
                {"id": "fallback", "name": "Fallback Voice", "language": language}
            ],
            "default": "default"
        }
    
    async def get_service_status(self) -> Dict[str, Any]:
        """Get comprehensive TTS service status"""
        status = {
            "service_name": "TTS Service",
            "external_tts_url": self.external_tts_url,
            "cache_enabled": self.enable_caching,
            "fallback_enabled": self.enable_fallback,
            "cache_size": len(self.audio_cache),
            "cache_max_size": self.max_cache_size,
            "default_settings": {
                "voice": self.default_voice,
                "speed": self.default_speed,
                "language": self.default_language
            }
        }
        
        # Test external service
        if self.external_client:
            try:
                external_status = self.external_client.get_status()
                external_health = await self.external_client.health_check()
                
                status["external_service"] = {
                    **external_status,
                    "health_check_passed": external_health
                }
            except Exception as e:
                status["external_service"] = {
                    "error": str(e),
                    "health_check_passed": False
                }
        else:
            status["external_service"] = {"status": "not_configured"}
        
        return status

# Global TTS service instance
_tts_service = None

def get_tts_service() -> TTSService:
    """Get global TTS service instance"""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service

async def initialize_tts_service() -> bool:
    """Initialize global TTS service"""
    service = get_tts_service()
    return await service.initialize()