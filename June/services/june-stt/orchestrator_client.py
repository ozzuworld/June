"""
Simplified orchestrator client - no over-engineering
"""
import os
import asyncio
import logging
from typing import Dict, Any

import httpx

from config import config

logger = logging.getLogger(__name__)

class SimpleOrchestratorClient:
    """
    Simple orchestrator client without over-engineering
    """
    def __init__(self):
        self.base_url = config.ORCHESTRATOR_URL
        self.service_token = config.STT_SERVICE_TOKEN
        self.enabled = config.ORCHESTRATOR_ENABLED
        
        logger.info(f"Orchestrator client: {self.base_url} (enabled: {self.enabled})")
    
    async def notify_transcript(self, transcript_data: Dict[str, Any]) -> bool:
        """
        Simple notification - fire and forget
        """
        if not self.enabled:
            return True
            
        try:
            webhook_url = f"{self.base_url}/v1/stt/webhook"
            
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "june-stt/4.0.0"
            }
            
            if self.service_token:
                headers["Authorization"] = f"Bearer {self.service_token}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    webhook_url,
                    json=transcript_data,
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ Notified orchestrator: {transcript_data['transcript_id']}")
                    return True
                else:
                    logger.warning(f"⚠️ Orchestrator returned {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Orchestrator notification failed: {e}")
            return False

# Global client instance
orchestrator_client = SimpleOrchestratorClient()
