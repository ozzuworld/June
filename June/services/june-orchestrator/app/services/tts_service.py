"""CosyVoice2 TTS Service Client - Enhanced

Official CosyVoice2 integration for June Orchestrator.
CosyVoice2 uses zero-shot and cross-lingual synthesis (NO SFT mode).

Reference: https://github.com/FunAudioLLM/CosyVoice
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
        
        # Debug: Log DNS resolution and network info at startup
        self._log_network_debug()

    def _log_network_debug(self):
        """Log network and DNS information for debugging"""
        try:
            logger.info("="*80)
            logger.info("🔍 TTS SERVICE NETWORK DEBUG INFORMATION")
            logger.info("="*80)
            
            # Parse the base URL
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            hostname = parsed.hostname or parsed.netloc
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            
            logger.info(f"📋 Configuration:")
            logger.info(f"   Base URL: {self.base_url}")
            logger.info(f"   Scheme: {parsed.scheme}")
            logger.info(f"   Hostname: {hostname}")
            logger.info(f"   Port: {port}")
            logger.info(f"   Path: {parsed.path}")
            
            # Try to resolve DNS
            if hostname:
                try:
                    logger.info(f"\n🌐 DNS Resolution for '{hostname}':")
                    ip_addresses = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
                    for family, socktype, proto, canonname, sockaddr in ip_addresses:
                        logger.info(f"   ✅ Resolved to: {sockaddr[0]}:{sockaddr[1]} (Family: {family})")
                except socket.gaierror as dns_error:
                    logger.error(f"   ❌ DNS resolution failed: {dns_error}")
                except Exception as e:
                    logger.error(f"   ❌ DNS lookup error: {e}")
            
            # Get local network info
            try:
                local_hostname = socket.gethostname()
                local_ip = socket.gethostbyname(local_hostname)
                logger.info(f"\n🏠 Local Network Info:")
                logger.info(f"   Local Hostname: {local_hostname}")
                logger.info(f"   Local IP: {local_ip}")
            except Exception as e:
                logger.error(f"   ❌ Local network info error: {e}")
            
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"❌ Network debug logging failed: {e}")

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
        request_start_time = time.time()
        
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
            
            # Construct full URL
            full_url = f"{self.base_url}/api/tts/synthesize"
            
            # DEBUG: Log complete request details
            logger.info("="*80)
            logger.info("🚀 TTS REQUEST DEBUG")
            logger.info("="*80)
            logger.info(f"📍 Full URL: {full_url}")
            logger.info(f"🔗 Base URL: {self.base_url}")
            logger.info(f"📝 Endpoint: /api/tts/synthesize")
            logger.info(f"⏱️  Timeout: {self.timeout}s")
            logger.info(f"\n📦 Request Headers:")
            headers = self._headers()
            for key, value in headers.items():
                if key.lower() == 'authorization':
                    logger.info(f"   {key}: Bearer ****** (hidden)")
                else:
                    logger.info(f"   {key}: {value}")
            logger.info(f"\n📋 Request Payload:")
            logger.info(json.dumps(payload, indent=2))
            logger.info(f"\n🔌 Attempting connection...")
            
            # Try to resolve the hostname before making request
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            hostname = parsed.hostname or parsed.netloc
            if hostname:
                try:
                    resolved_ip = socket.gethostbyname(hostname)
                    logger.info(f"✅ DNS resolved '{hostname}' to: {resolved_ip}")
                except Exception as dns_err:
                    logger.error(f"❌ DNS resolution failed for '{hostname}': {dns_err}")
            
            connection_start = time.time()

            # Send request to TTS service
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"🔄 Sending POST request...")
                
                response = await client.post(
                    full_url,
                    json=payload,
                    headers=headers,
                )
                
                connection_time = (time.time() - connection_start) * 1000
                logger.info(f"⏱️  Connection time: {connection_time:.2f}ms")
                
                # Log response details
                logger.info(f"\n📨 RESPONSE RECEIVED:")
                logger.info(f"   Status Code: {response.status_code}")
                logger.info(f"   Reason: {response.reason_phrase}")
                logger.info(f"\n📋 Response Headers:")
                for key, value in response.headers.items():
                    logger.info(f"   {key}: {value}")
                
                logger.info(f"\n📄 Response Body (first 500 chars):")
                response_text = response.text[:500]
                logger.info(f"   {response_text}")
                
                if response.status_code == 200:
                    result = response.json()
                    chunks = result.get('chunks_sent', 0)
                    duration = result.get('synthesis_time_ms', 0)
                    total_time = (time.time() - request_start_time) * 1000
                    logger.info(f"\n✅ TTS SUCCESS:")
                    logger.info(f"   Chunks sent: {chunks}")
                    logger.info(f"   Synthesis time: {duration:.0f}ms")
                    logger.info(f"   Total request time: {total_time:.0f}ms")
                    logger.info("="*80)
                    return True
                elif response.status_code == 503:
                    logger.error(f"\n❌ TTS service unavailable (503) - may be loading models")
                    logger.error("="*80)
                    return False
                else:
                    error_detail = response.text[:200]
                    logger.error(f"\n❌ TTS service error: {response.status_code}")
                    logger.error(f"   Detail: {error_detail}")
                    logger.error("="*80)
                    return False
                    
        except httpx.TimeoutException as timeout_err:
            total_time = (time.time() - request_start_time) * 1000
            logger.error("="*80)
            logger.error(f"⏱️  TIMEOUT ERROR after {total_time:.0f}ms")
            logger.error(f"   Configured timeout: {self.timeout}s")
            logger.error(f"   Target URL: {self.base_url}/api/tts/synthesize")
            logger.error(f"   Error: {timeout_err}")
            logger.error("   Possible causes:")
            logger.error("   - TTS service is not responding")
            logger.error("   - TTS service is overloaded")
            logger.error("   - Network connectivity issues")
            logger.error("   - Firewall blocking the connection")
            logger.error("="*80)
            return False
            
        except httpx.ConnectError as conn_err:
            total_time = (time.time() - request_start_time) * 1000
            logger.error("="*80)
            logger.error(f"🔌 CONNECTION ERROR after {total_time:.0f}ms")
            logger.error(f"   Target URL: {self.base_url}/api/tts/synthesize")
            logger.error(f"   Error type: {type(conn_err).__name__}")
            logger.error(f"   Error message: {conn_err}")
            logger.error("   Possible causes:")
            logger.error("   - TTS service is not running")
            logger.error("   - Wrong hostname or port")
            logger.error("   - Network routing issues")
            logger.error("   - Service not listening on expected port")
            
            # Try to ping the host
            from urllib.parse import urlparse
            parsed = urlparse(self.base_url)
            hostname = parsed.hostname or parsed.netloc
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            
            if hostname:
                logger.error(f"\n🔍 Connection diagnostics for {hostname}:{port}:")
                try:
                    # Try DNS resolution
                    ip = socket.gethostbyname(hostname)
                    logger.error(f"   ✅ DNS resolves to: {ip}")
                    
                    # Try to connect to the port
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    result = sock.connect_ex((hostname, port))
                    sock.close()
                    
                    if result == 0:
                        logger.error(f"   ✅ Port {port} is open")
                        logger.error(f"   ⚠️  Port is open but HTTP request failed - check if service is running correctly")
                    else:
                        logger.error(f"   ❌ Port {port} is closed or unreachable")
                        logger.error(f"   ⚠️  Service may not be listening on this port")
                        
                except socket.gaierror:
                    logger.error(f"   ❌ DNS resolution failed for {hostname}")
                except Exception as diag_err:
                    logger.error(f"   ❌ Diagnostics failed: {diag_err}")
            
            logger.error("="*80)
            return False
            
        except Exception as e:
            total_time = (time.time() - request_start_time) * 1000
            logger.error("="*80)
            logger.error(f"❌ UNEXPECTED ERROR after {total_time:.0f}ms")
            logger.error(f"   Error type: {type(e).__name__}")
            logger.error(f"   Error message: {e}")
            logger.error(f"   Target URL: {self.base_url}/api/tts/synthesize")
            logger.error("="*80)
            logger.error(f"Full traceback:", exc_info=True)
            return False

    async def health_check(self) -> Dict[str, Any]:
        """Check if TTS service is healthy and get status
        
        Returns:
            Dictionary with health status and service info
        """
        try:
            logger.info(f"🏥 Health check: {self.base_url}/health")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers=self._headers()
                )
                
                logger.info(f"   Status: {response.status_code}")
                
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
            logger.error(f"❌ Health check failed: {e}")
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
