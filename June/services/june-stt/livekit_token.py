import os
import asyncio
import logging
import httpx
from livekit import rtc
from config import config

logger = logging.getLogger(__name__)

async def get_livekit_token(identity: str, max_retries: int = 3) -> tuple[str, str]:
    """Get LiveKit token with retry logic"""
    base = os.getenv("ORCHESTRATOR_URL", getattr(config, "ORCHESTRATOR_URL", "http://june-orchestrator.june-services.svc.cluster.local:8080"))
    url = f"{base}/api/livekit/token"
    
    for attempt in range(max_retries):
        try:
            timeout = 5.0 + (attempt * 2.0)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.info(f"Getting LiveKit token (attempt {attempt + 1}/{max_retries})")
                
                r = await client.post(url, json={"service_identity": identity})
                r.raise_for_status()
                
                data = r.json()
                ws_url = data.get("ws_url") or getattr(config, "LIVEKIT_WS_URL", "wss://livekit.ozzu.world")
                token = data["token"]
                
                logger.info("LiveKit token received")
                return ws_url, token
                
        except httpx.ConnectTimeout as e:
            logger.warning(f"Connection timeout (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = 2.0 * (attempt + 1)
                await asyncio.sleep(wait_time)
            else:
                raise ConnectionError(f"Cannot reach orchestrator after {max_retries} attempts") from e
                
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error: {e.response.status_code}")
            raise
            
        except Exception as e:
            logger.error(f"Error getting LiveKit token: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1.0)
            else:
                raise
    
    raise RuntimeError(f"Failed to get LiveKit token after {max_retries} attempts")

async def connect_room_as_subscriber(room: rtc.Room, identity: str, max_retries: int = 3) -> None:
    """Connect to LiveKit room with retry logic"""
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Connecting to LiveKit as {identity} (attempt {attempt + 1}/{max_retries})")
            
            ws_url, token = await get_livekit_token(identity, max_retries=2)
            await room.connect(ws_url, token)
            
            logger.info(f"Connected to LiveKit room as {identity}")
            return
            
        except ConnectionError as e:
            logger.error(f"Connection error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = 3.0 * (attempt + 1)
                await asyncio.sleep(wait_time)
            else:
                raise
                
        except Exception as e:
            logger.error(f"LiveKit connection error: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2.0)
            else:
                raise
    
    raise RuntimeError(f"Failed to connect to LiveKit room after {max_retries} attempts")