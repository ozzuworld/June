# June/services/june-orchestrator/external_tts_client.py
# FIXED: Enhanced external TTS client with proper error handling, health checks, and security

import httpx
import logging
import base64
import asyncio
import time
from typing import Optional, Dict, Any
import ssl

logger = logging.getLogger(__name__)

class ExternalTTSClient:
    """Enhanced client for external OpenVoice TTS service with IDP authentication"""
    
    def __init__(self, base_url: str, auth_client):
        self.base_url = base_url.rstrip('/')
        self.auth_client = auth_client
        self.is_available = True
        self.last_health_check = 0
        self.health_check_interval = 60  # Check every minute
        self.request_timeout = 30.0
        self.max_retries = 2
        
        # Validate URL format
        if not self.base_url.startswith(('http://', 'https://')):
            raise ValueError(f"Invalid TTS URL format: {self.base_url}")
        
        # Warn about HTTP in production
        if self.base_url.startswith('http://') and 'localhost' not in self.base_url:
            logger.warning("⚠️ Using HTTP for external TTS service - consider HTTPS for production")
        
        logger.info(f"🔧 External TTS client initialized: {self.base_url}")
    
    async def health_check(self) -> bool:
        """Check if external TTS service is available and responsive"""
        now = time.time()
        
        # Use cached result if recent
        if now - self.last_health_check < self.health_check_interval:
            return self.is_available
        
        try:
            # Create SSL context for secure connections
            ssl_context = ssl.create_default_context()
            
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0),
                verify=ssl_context if self.base_url.startswith('https://') else False
            ) as client:
                
                # Try to get a health/status endpoint first
                health_endpoints = ['/health', '/healthz', '/status', '/v1/status']
                
                for endpoint in health_endpoints:
                    try:
                        response = await client.get(f"{self.base_url}{endpoint}")
                        if response.status_code == 200:
                            self.is_available = True
                            self.last_health_check = now
                            logger.debug(f"✅ External TTS health check passed via {endpoint}")
                            return True
                    except Exception:
                        continue
                
                # If no health endpoint, try a simple HEAD request to base URL
                try:
                    response = await client.head(self.base_url)
                    self.is_available = response.status_code < 500
                    self.last_health_check = now
                    logger.debug(f"✅ External TTS basic connectivity check: {response.status_code}")
                    return self.is_available
                except Exception:
                    pass
                
                # Mark as unavailable
                self.is_available = False
                self.last_health_check = now
                logger.warning("⚠️ External TTS service health check failed")
                return False
                
        except Exception as e:
            self.is_available = False
            self.last_health_check = now
            logger.warning(f"⚠️ External TTS health check error: {e}")
            return False
    
    async def _make_authenticated_request(
        self, 
        method: str, 
        endpoint: str, 
        **kwargs
    ) -> httpx.Response:
        """Make authenticated request with proper error handling and security"""
        
        # Ensure we have authentication
        if not self.auth_client:
            raise RuntimeError("Authentication client not available")
        
        full_url = f"{self.base_url}{endpoint}"
        
        # Create SSL context for HTTPS
        ssl_context = ssl.create_default_context()
        
        # Set up request kwargs with security headers
        request_kwargs = {
            "timeout": httpx.Timeout(self.request_timeout),
            "verify": ssl_context if self.base_url.startswith('https://') else False,
            **kwargs
        }
        
        # Add security headers
        headers = request_kwargs.get("headers", {})
        headers.update({
            "User-Agent": "June-Orchestrator/1.0.0",
            "Accept": "application/json, audio/*",
            "X-Request-ID": f"june-{int(time.time() * 1000)}"
        })
        request_kwargs["headers"] = headers
        
        # Retry logic
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.auth_client.make_authenticated_request(
                    method, full_url, **request_kwargs
                )
                
                # Log successful request
                logger.debug(f"External TTS request: {method} {endpoint} -> {response.status_code}")
                return response
                
            except httpx.TimeoutException as e:
                last_exception = e
                logger.warning(f"External TTS timeout (attempt {attempt + 1}/{self.max_retries + 1}): {endpoint}")
                if attempt < self.max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))  # Exponential backoff
                    
            except httpx.HTTPStatusError as e:
                # Don't retry on client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    logger.error(f"External TTS client error: {e.response.status_code} - {e.response.text}")
                    raise
                
                last_exception = e
                logger.warning(f"External TTS server error (attempt {attempt + 1}/{self.max_retries + 1}): {e.response.status_code}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    
            except Exception as e:
                last_exception = e
                logger.warning(f"External TTS request error (attempt {attempt + 1}/{self.max_retries + 1}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
        
        # All retries failed
        raise RuntimeError(f"External TTS service failed after {self.max_retries + 1} attempts: {last_exception}")
        
    async def synthesize_speech(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        language: str = "EN"
    ) -> bytes:
        """Call external OpenVoice TTS service with enhanced error handling"""
        
        # Input validation
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        if len(text) > 5000:  # Reasonable limit
            raise ValueError("Text too long (max 5000 characters)")
        
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Speed must be between 0.5 and 2.0")
        
        # Check service availability
        if not await self.health_check():
            raise RuntimeError("External TTS service is not available")
        
        try:
            logger.info(f"🎵 Calling external TTS: '{text[:50]}...' (voice: {voice}, speed: {speed})")
            
            # Prepare request payload
            tts_payload = {
                "text": text.strip(),
                "voice": voice,
                "speed": speed,
                "language": language.upper(),
                "format": "wav",  # Request specific format
                "quality": "high"  # Request high quality
            }
            
            response = await self._make_authenticated_request(
                "POST",
                "/v1/tts",
                json=tts_payload,
                headers={"Content-Type": "application/json"}
            )
            
            response.raise_for_status()
            
            # Validate response
            if not response.content:
                raise RuntimeError("External TTS returned empty response")
            
            # Check if response is actually audio
            content_type = response.headers.get("content-type", "")
            if not any(audio_type in content_type.lower() for audio_type in ["audio", "octet-stream"]):
                logger.warning(f"Unexpected content type from TTS service: {content_type}")
            
            audio_data = response.content
            logger.info(f"✅ External TTS success: {len(audio_data)} bytes, content-type: {content_type}")
            
            return audio_data
            
        except ValueError as e:
            # Re-raise validation errors
            raise e
        except Exception as e:
            logger.error(f"❌ External TTS synthesis failed: {e}")
            raise RuntimeError(f"External TTS synthesis failed: {str(e)}")
    
    async def clone_voice(
        self,
        text: str,
        reference_audio_bytes: bytes,
        language: str = "EN"
    ) -> bytes:
        """Call external voice cloning service with enhanced validation"""
        
        # Input validation
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        if not reference_audio_bytes:
            raise ValueError("Reference audio cannot be empty")
        
        if len(reference_audio_bytes) < 1000:  # Minimum reasonable audio size
            raise ValueError("Reference audio too small (minimum 1KB)")
        
        if len(reference_audio_bytes) > 50 * 1024 * 1024:  # 50MB limit
            raise ValueError("Reference audio too large (maximum 50MB)")
        
        # Check service availability
        if not await self.health_check():
            raise RuntimeError("External TTS service is not available")
        
        try:
            logger.info(f"🎤 Voice cloning request: '{text[:50]}...' ({len(reference_audio_bytes)} bytes audio)")
            
            # Encode audio for transmission
            audio_b64 = base64.b64encode(reference_audio_bytes).decode('utf-8')
            
            clone_payload = {
                "text": text.strip(),
                "reference_audio": audio_b64,
                "language": language.upper(),
                "format": "wav",
                "quality": "high"
            }
            
            response = await self._make_authenticated_request(
                "POST",
                "/v1/clone",
                json=clone_payload,
                headers={"Content-Type": "application/json"},
                timeout=httpx.Timeout(60.0)  # Voice cloning takes longer
            )
            
            response.raise_for_status()
            
            # Validate response
            if not response.content:
                raise RuntimeError("External TTS returned empty cloned audio")
            
            audio_data = response.content
            logger.info(f"✅ Voice cloning success: {len(audio_data)} bytes")
            
            return audio_data
            
        except ValueError as e:
            # Re-raise validation errors
            raise e
        except Exception as e:
            logger.error(f"❌ Voice cloning failed: {e}")
            raise RuntimeError(f"Voice cloning service failed: {str(e)}")
    
    async def get_available_voices(self, language: str = "EN") -> Dict[str, Any]:
        """Get list of available voices from external service"""
        try:
            response = await self._make_authenticated_request(
                "GET",
                f"/v1/voices?language={language.upper()}"
            )
            
            response.raise_for_status()
            
            voices_data = response.json()
            logger.info(f"✅ Retrieved {len(voices_data.get('voices', []))} voices for {language}")
            
            return voices_data
            
        except Exception as e:
            logger.error(f"❌ Failed to get available voices: {e}")
            return {"voices": ["default"], "error": str(e)}
    
    def get_status(self) -> Dict[str, Any]:
        """Get current client status"""
        return {
            "service_url": self.base_url,
            "is_available": self.is_available,
            "last_health_check": self.last_health_check,
            "health_check_age": time.time() - self.last_health_check,
            "max_retries": self.max_retries,
            "request_timeout": self.request_timeout,
            "using_https": self.base_url.startswith('https://'),
            "auth_available": self.auth_client is not None
        }