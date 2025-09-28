# June/services/june-stt/orchestrator_client.py - External service communication
import os
import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import json

import httpx
from fastapi import HTTPException

from shared.auth import get_auth_service

logger = logging.getLogger(__name__)

class ExternalOrchestratorClient:
    """Client for communicating with external orchestrator service"""
    
    def __init__(self):
        self.base_url = os.getenv("ORCHESTRATOR_URL", "https://api.allsafe.world")
        self.webhook_path = os.getenv("ORCHESTRATOR_WEBHOOK_PATH", "/v1/stt/webhook")
        self.timeout = httpx.Timeout(
            connect=5.0, 
            read=float(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "10"))
        )
        self.enabled = os.getenv("ENABLE_ORCHESTRATOR_NOTIFICATIONS", "true").lower() == "true"
        self.max_retries = 3
        self.retry_delay = 1.0  # seconds
    
    async def notify_transcript(self, transcript_data: Dict[str, Any]) -> bool:
        """
        Send transcript notification to external orchestrator
        
        Args:
            transcript_data: Transcript information including:
                - transcript_id: str
                - user_id: str
                - text: str
                - language: Optional[str]
                - confidence: Optional[float]
                - processing_time_ms: int
                - metadata: Dict[str, Any]
        
        Returns:
            bool: True if notification was successful
        """
        if not self.enabled:
            logger.debug("Orchestrator notifications disabled")
            return True
        
        webhook_url = f"{self.base_url}{self.webhook_path}"
        
        # Prepare notification payload
        notification = {
            "transcript_id": transcript_data["transcript_id"],
            "user_id": transcript_data["user_id"],
            "text": transcript_data["text"],
            "timestamp": datetime.utcnow().isoformat(),
            "source": "june-stt-external",
            "metadata": {
                "language": transcript_data.get("language"),
                "confidence": transcript_data.get("confidence"),
                "processing_time_ms": transcript_data.get("processing_time_ms"),
                "service_version": "2.0.0",
                **transcript_data.get("metadata", {})
            }
        }
        
        # Try notification with retries
        for attempt in range(self.max_retries):
            try:
                # Get service token for authentication
                auth_service = get_auth_service()
                service_token = await auth_service.get_service_token()
                
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {service_token}",
                    "User-Agent": "june-stt-external/2.0.0",
                    "X-Service-Source": "june-stt"
                }
                
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug(f"Sending notification to {webhook_url} (attempt {attempt + 1})")
                    
                    response = await client.post(
                        webhook_url,
                        json=notification,
                        headers=headers
                    )
                    
                    if response.status_code in [200, 201, 202]:
                        logger.info(f"✅ Orchestrator notified successfully for transcript {transcript_data['transcript_id']}")
                        return True
                    elif response.status_code in [401, 403]:
                        logger.error(f"❌ Authentication failed for orchestrator notification: {response.status_code}")
                        return False  # Don't retry auth failures
                    else:
                        logger.warning(f"⚠️ Orchestrator notification failed: {response.status_code} - {response.text}")
                        
                        # Don't retry for client errors (4xx)
                        if 400 <= response.status_code < 500:
                            return False
                        
                        # Retry for server errors (5xx)
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
                            continue
                        
                        return False
                        
            except httpx.ConnectTimeout:
                logger.warning(f"⚠️ Connection timeout to orchestrator (attempt {attempt + 1})")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                return False
                
            except httpx.HTTPError as e:
                logger.error(f"❌ HTTP error notifying orchestrator: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                return False
                
            except Exception as e:
                logger.error(f"❌ Unexpected error notifying orchestrator: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                return False
        
        logger.error(f"❌ Failed to notify orchestrator after {self.max_retries} attempts")
        return False
    
    async def test_connectivity(self) -> Dict[str, Any]:
        """Test connectivity to orchestrator service"""
        health_url = f"{self.base_url}/healthz"
        
        try:
            # Test without authentication first
            timeout = httpx.Timeout(5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(health_url)
                
                result = {
                    "orchestrator_url": self.base_url,
                    "reachable": True,
                    "status_code": response.status_code,
                    "webhook_notifications_enabled": self.enabled
                }
                
                if response.status_code == 200:
                    result["orchestrator_healthy"] = True
                    try:
                        health_data = response.json()
                        result["orchestrator_info"] = health_data
                    except:
                        pass
                else:
                    result["orchestrator_healthy"] = False
                
                # Test authentication
                try:
                    auth_service = get_auth_service()
                    service_token = await auth_service.get_service_token()
                    result["authentication"] = "working"
                except Exception as e:
                    result["authentication"] = f"failed: {str(e)}"
                
                return result
                
        except httpx.ConnectTimeout:
            return {
                "orchestrator_url": self.base_url,
                "reachable": False,
                "error": "connection_timeout",
                "webhook_notifications_enabled": self.enabled
            }
        except httpx.HTTPError as e:
            return {
                "orchestrator_url": self.base_url,
                "reachable": False,
                "error": f"http_error: {str(e)}",
                "webhook_notifications_enabled": self.enabled
            }
        except Exception as e:
            return {
                "orchestrator_url": self.base_url,
                "reachable": False,
                "error": f"unexpected_error: {str(e)}",
                "webhook_notifications_enabled": self.enabled
            }

# Global orchestrator client
_orchestrator_client: Optional[ExternalOrchestratorClient] = None

def get_orchestrator_client() -> ExternalOrchestratorClient:
    """Get global orchestrator client instance"""
    global _orchestrator_client
    if _orchestrator_client is None:
        _orchestrator_client = ExternalOrchestratorClient()
    return _orchestrator_client