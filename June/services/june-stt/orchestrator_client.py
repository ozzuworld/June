# June/services/june-stt/orchestrator_client.py
"""
Orchestrator Client for STT Service
Sends transcribed text to orchestrator for AI processing
"""

import os
import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


class ExternalOrchestratorClient:
    """
    Client for communicating with June Orchestrator service
    
    Flow:
    1. STT transcribes user's speech to text
    2. This client sends the transcript to orchestrator
    3. Orchestrator processes with AI and generates response
    """
    
    def __init__(self):
        # Kubernetes service name (set in K8s deployment)
        self.base_url = os.getenv("ORCHESTRATOR_URL", "http://june-orchestrator.june-services.svc.cluster.local:8080")

        
        # STT webhook endpoint on orchestrator
        self.webhook_path = os.getenv("ORCHESTRATOR_WEBHOOK_PATH", "/v1/stt/webhook")
        
        # Service authentication token (set in K8s secret)
        self.service_token = os.getenv("STT_SERVICE_TOKEN", "")
        
        # Connection settings
        self.timeout = httpx.Timeout(
            connect=5.0,
            read=float(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "10")),
            write=5.0,
            pool=5.0
        )
        
        # Feature flag
        self.enabled = os.getenv("ENABLE_ORCHESTRATOR_NOTIFICATIONS", "true").lower() == "true"
        
        # Retry settings
        self.max_retries = int(os.getenv("ORCHESTRATOR_MAX_RETRIES", "3"))
        self.retry_delay = float(os.getenv("ORCHESTRATOR_RETRY_DELAY", "1.0"))
        
        logger.info(f"📡 Orchestrator client initialized")
        logger.info(f"   Base URL: {self.base_url}")
        logger.info(f"   Webhook: {self.webhook_path}")
        logger.info(f"   Enabled: {self.enabled}")
        logger.info(f"   Authenticated: {bool(self.service_token)}")
    
    async def notify_transcript(self, transcript_data: Dict[str, Any]) -> bool:
        """
        Send transcript notification to orchestrator
        
        Args:
            transcript_data: Dictionary containing:
                - transcript_id: str (unique ID)
                - user_id: str (who spoke)
                - text: str (what they said - THIS IS KEY!)
                - language: Optional[str] (detected language)
                - confidence: Optional[float] (transcription confidence)
                - processing_time_ms: int (how long transcription took)
                - metadata: Dict[str, Any] (additional info)
        
        Returns:
            bool: True if notification succeeded, False otherwise
        """
        if not self.enabled:
            logger.debug("Orchestrator notifications disabled")
            return True
        
        # Build webhook URL
        webhook_url = f"{self.base_url}{self.webhook_path}"
        
        # Prepare notification payload
        notification = {
            "transcript_id": transcript_data["transcript_id"],
            "user_id": transcript_data["user_id"],
            "text": transcript_data["text"],  # WHAT THE USER SAID
            "language": transcript_data.get("language"),
            "confidence": transcript_data.get("confidence"),
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "processing_time_ms": transcript_data.get("processing_time_ms"),
                "service": "june-stt",
                "service_version": "3.1.0",
                **transcript_data.get("metadata", {})
            }
        }
        
        logger.info("="*70)
        logger.info(f"📤 SENDING TRANSCRIPT TO ORCHESTRATOR")
        logger.info(f"   URL: {webhook_url}")
        logger.info(f"   Transcript ID: {notification['transcript_id']}")
        logger.info(f"   User ID: {notification['user_id']}")
        logger.info(f"   User said: '{notification['text'][:100]}...'")
        logger.info(f"   Language: {notification.get('language', 'unknown')}")
        logger.info(f"   Confidence: {notification.get('confidence', 0.0):.2f}")
        logger.info("="*70)
        
        # Try sending with retries
        for attempt in range(self.max_retries):
            try:
                # Prepare headers with service authentication
                headers = {
                    "Content-Type": "application/json",
                    "User-Agent": "june-stt/3.1.0",
                    "X-Service-Source": "june-stt",
                    "X-Transcript-ID": notification['transcript_id']
                }
                
                # Add authentication if token available
                if self.service_token:
                    headers["Authorization"] = f"Bearer {self.service_token}"
                    logger.debug("🔐 Service authentication token added")
                else:
                    logger.warning("⚠️ No service token configured - request may be rejected")
                
                # Send request
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug(f"Attempt {attempt + 1}/{self.max_retries}")
                    
                    response = await client.post(
                        webhook_url,
                        json=notification,
                        headers=headers
                    )
                    
                    # Handle response
                    if response.status_code == 200:
                        result = response.json()
                        
                        logger.info("✅ ORCHESTRATOR RECEIVED TRANSCRIPT")
                        logger.info(f"   Status: {result.get('status', 'unknown')}")
                        
                        # Log AI response if included
                        if 'ai_response' in result:
                            ai_text = result['ai_response']
                            logger.info(f"   AI Response: '{ai_text[:100]}...'")
                        
                        if 'processing_time_ms' in result:
                            logger.info(f"   Processing time: {result['processing_time_ms']}ms")
                        
                        logger.info("="*70)
                        return True
                    
                    elif response.status_code in [401, 403]:
                        # Authentication error - don't retry
                        logger.error(f"❌ Authentication failed: {response.status_code}")
                        logger.error(f"   Response: {response.text[:200]}")
                        return False
                    
                    elif response.status_code == 404:
                        # Endpoint not found - don't retry
                        logger.error(f"❌ Orchestrator endpoint not found: {webhook_url}")
                        logger.error("   Check ORCHESTRATOR_WEBHOOK_PATH configuration")
                        return False
                    
                    elif response.status_code >= 500:
                        # Server error - retry
                        logger.warning(f"⚠️ Orchestrator server error: {response.status_code}")
                        logger.warning(f"   Response: {response.text[:200]}")
                        
                        if attempt < self.max_retries - 1:
                            delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                            logger.info(f"   Retrying in {delay}s...")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            logger.error(f"❌ Max retries reached")
                            return False
                    
                    else:
                        # Other error
                        logger.error(f"❌ Unexpected response: {response.status_code}")
                        logger.error(f"   Response: {response.text[:200]}")
                        return False
            
            except httpx.ConnectTimeout:
                logger.warning(f"⚠️ Connection timeout to orchestrator (attempt {attempt + 1})")
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    logger.error("❌ Connection timeout - orchestrator unreachable")
                    return False
            
            except httpx.ReadTimeout:
                logger.warning(f"⚠️ Read timeout from orchestrator (attempt {attempt + 1})")
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    logger.error("❌ Read timeout - orchestrator not responding")
                    return False
            
            except httpx.HTTPError as e:
                logger.error(f"❌ HTTP error: {e}")
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    return False
            
            except Exception as e:
                logger.error(f"❌ Unexpected error sending transcript: {e}")
                logger.exception(e)
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                else:
                    return False
        
        # If we get here, all retries failed
        logger.error(f"❌ Failed to notify orchestrator after {self.max_retries} attempts")
        return False
    
    async def test_connectivity(self) -> Dict[str, Any]:
        """
        Test connectivity to orchestrator service
        
        Returns:
            Dict with connectivity status and details
        """
        logger.info("🔍 Testing orchestrator connectivity...")
        
        result = {
            "orchestrator_url": self.base_url,
            "webhook_path": self.webhook_path,
            "full_url": f"{self.base_url}{self.webhook_path}",
            "notifications_enabled": self.enabled,
            "authenticated": bool(self.service_token),
            "reachable": False,
            "healthy": False,
            "error": None
        }
        
        try:
            # Test health endpoint first
            health_url = f"{self.base_url}/healthz"
            
            headers = {}
            if self.service_token:
                headers["Authorization"] = f"Bearer {self.service_token}"
            
            timeout = httpx.Timeout(5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.debug(f"Testing health endpoint: {health_url}")
                
                response = await client.get(health_url, headers=headers)
                
                result["reachable"] = True
                
                if response.status_code == 200:
                    result["healthy"] = True
                    
                    try:
                        health_data = response.json()
                        result["orchestrator_info"] = {
                            "status": health_data.get("status"),
                            "service": health_data.get("service"),
                            "version": health_data.get("version"),
                            "ai_available": health_data.get("ai_available")
                        }
                        logger.info(f"✅ Orchestrator is healthy")
                        logger.info(f"   Version: {health_data.get('version')}")
                        logger.info(f"   AI available: {health_data.get('ai_available')}")
                    except:
                        pass
                else:
                    result["error"] = f"Health check returned {response.status_code}"
                    logger.warning(f"⚠️ Health check returned {response.status_code}")
        
        except httpx.ConnectTimeout:
            result["error"] = "Connection timeout"
            logger.error(f"❌ Connection timeout - orchestrator unreachable at {self.base_url}")
        
        except httpx.ConnectError as e:
            result["error"] = f"Connection error: {str(e)}"
            logger.error(f"❌ Connection error: {e}")
        
        except Exception as e:
            result["error"] = f"Unexpected error: {str(e)}"
            logger.error(f"❌ Unexpected error: {e}")
        
        return result


# Global orchestrator client instance
_orchestrator_client: Optional[ExternalOrchestratorClient] = None


def get_orchestrator_client() -> ExternalOrchestratorClient:
    """
    Get the global orchestrator client instance (singleton pattern)
    
    Returns:
        ExternalOrchestratorClient instance
    """
    global _orchestrator_client
    
    if _orchestrator_client is None:
        _orchestrator_client = ExternalOrchestratorClient()
    
    return _orchestrator_client


async def send_transcript_to_orchestrator(transcript_data: Dict[str, Any]) -> bool:
    """
    Convenience function to send transcript to orchestrator
    
    Args:
        transcript_data: Transcript information
        
    Returns:
        bool: True if successful
    """
    client = get_orchestrator_client()
    return await client.notify_transcript(transcript_data)


async def test_orchestrator_connection() -> Dict[str, Any]:
    """
    Convenience function to test orchestrator connectivity
    
    Returns:
        Dict with test results
    """
    client = get_orchestrator_client()
    return await client.test_connectivity()


# Module initialization
logger.info("📦 Orchestrator client module loaded")