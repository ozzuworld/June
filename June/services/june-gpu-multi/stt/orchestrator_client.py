import asyncio
import logging
import os
from typing import Optional, Dict, Any
import httpx
from config import config

logger = logging.getLogger(__name__)

class OrchestratorClient:
    def __init__(self):
        self.base_url = config.ORCHESTRATOR_URL
        self.timeout = 10.0
        
        # Configure proxy for Tailscale userspace networking
        self.proxy_url = None
        if os.getenv('ALL_PROXY'):
            self.proxy_url = os.getenv('ALL_PROXY')
            logger.info(f"Using proxy for orchestrator client: {self.proxy_url}")
        elif os.path.exists('/etc/environment'):
            # Try to read proxy from environment file
            try:
                with open('/etc/environment', 'r') as f:
                    for line in f:
                        if line.startswith('ALL_PROXY='):
                            self.proxy_url = line.split('=', 1)[1].strip()
                            logger.info(f"Loaded proxy from /etc/environment: {self.proxy_url}")
                            break
            except Exception as e:
                logger.debug(f"Could not read proxy from /etc/environment: {e}")
    
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
            # Configure client with proxy if available
            client_kwargs = {"timeout": self.timeout}
            if self.proxy_url:
                # Use proxy for Tailscale connectivity
                client_kwargs["proxies"] = {
                    "http://": self.proxy_url,
                    "https://": self.proxy_url
                }
                logger.debug(f"Using proxy {self.proxy_url} for orchestrator connection")
            
            async with httpx.AsyncClient(**client_kwargs) as client:
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