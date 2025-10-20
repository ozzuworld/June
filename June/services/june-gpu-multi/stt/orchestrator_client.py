import asyncio
import logging
from typing import Optional, Dict, Any
import httpx
from config import config

logger = logging.getLogger(__name__)

class OrchestratorClient:
    def __init__(self):
        self.base_url = config.ORCHESTRATOR_URL
        self.timeout = 10.0
    
    async def send_transcript(self, 
                            transcript_id: str,
                            user_id: str, 
                            text: str,
                            language: Optional[str] = None,
                            timestamp: Optional[str] = None,
                            room_name: str = "ozzu-main") -> bool:
        """Send transcript to orchestrator webhook"""
        if not self.base_url:
            logger.warning("No orchestrator URL configured")
            return False
            
        payload = {
            "transcript_id": transcript_id,
            "user_id": user_id,
            "text": text,
            "language": language,
            "timestamp": timestamp,
            "room_name": room_name
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                headers = {}
                if config.BEARER_TOKEN:
                    headers["Authorization"] = f"Bearer {config.BEARER_TOKEN}"
                    
                response = await client.post(
                    f"{self.base_url}/api/webhooks/transcript",
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info(f"Transcript sent successfully: {text[:50]}...")
                    return True
                else:
                    logger.warning(f"Orchestrator webhook failed: {response.status_code} {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to send transcript to orchestrator: {e}")
            return False

# Global client instance
orchestrator_client = OrchestratorClient()