import os
import asyncio
import logging
import httpx
from livekit import rtc
from config import config

logger = logging.getLogger(__name__)

async def get_livekit_token(identity: str, max_retries: int = 3) -> tuple[str, str]:
    """Get LiveKit token with retry logic and better error handling"""
    # Standardized: prefer env ORCHESTRATOR_URL, fallback to config.ORCHESTRATOR_URL, then service DNS
    base = os.getenv("ORCHESTRATOR_URL", getattr(config, "ORCHESTRATOR_URL", "http://june-orchestrator.june-services.svc.cluster.local:8080"))
    url = f"{base}/api/livekit/token"
    
    for attempt in range(max_retries):
        try:
            # Increase timeout progressively with retries
            timeout = 5.0 + (attempt * 2.0)  # 5s, 7s, 9s
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                logger.info(f"🔌 Attempting to get LiveKit token from orchestrator (attempt {attempt + 1}/{max_retries})")
                logger.debug(f"📡 Orchestrator URL: {url}")
                
                r = await client.post(url, json={"service_identity": identity})
                r.raise_for_status()
                
                data = r.json()
                ws_url = data.get("ws_url") or getattr(config, "LIVEKIT_WS_URL", "wss://livekit.ozzu.world")
                token = data["token"]
                
                logger.info(f"✅ Got LiveKit token successfully on attempt {attempt + 1}")
                logger.debug(f"🔗 WebSocket URL: {ws_url}")
                
                return ws_url, token
                
        except httpx.ConnectTimeout as e:
            logger.warning(f"⏰ Connection timeout to orchestrator (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = 2.0 * (attempt + 1)  # Progressive backoff: 2s, 4s, 6s
                logger.info(f"⏳ Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"❌ Failed to connect to orchestrator after {max_retries} attempts")
                raise ConnectionError(f"Cannot reach orchestrator at {base} after {max_retries} attempts") from e
                
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ HTTP error from orchestrator: {e.response.status_code} {e.response.text}")
            raise
            
        except Exception as e:
            logger.error(f"❌ Unexpected error getting LiveKit token: {e}")
            if attempt < max_retries - 1:
                wait_time = 1.0
                logger.info(f"⏳ Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                raise
    
    # Should not reach here
    raise RuntimeError(f"Failed to get LiveKit token after {max_retries} attempts")


async def connect_room_as_subscriber(room: rtc.Room, identity: str, max_retries: int = 3) -> None:
    """Connect to LiveKit room with enhanced error handling and retries"""
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🚀 Connecting to LiveKit room as {identity} (attempt {attempt + 1}/{max_retries})")
            
            # Get token with retries
            ws_url, token = await get_livekit_token(identity, max_retries=2)
            
            # Connect to room
            logger.info(f"🔗 Connecting to LiveKit: {ws_url}")
            await room.connect(ws_url, token)
            
            logger.info(f"✅ Successfully connected to LiveKit room as {identity}")
            return
            
        except ConnectionError as e:
            logger.error(f"🔌 Connection error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = 3.0 * (attempt + 1)  # 3s, 6s, 9s
                logger.info(f"⏳ Retrying room connection in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"❌ Failed to connect to LiveKit after {max_retries} attempts")
                raise
                
        except Exception as e:
            logger.error(f"❌ Unexpected LiveKit connection error: {e}")
            if attempt < max_retries - 1:
                wait_time = 2.0
                logger.info(f"⏳ Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                raise
    
    # Should not reach here
    raise RuntimeError(f"Failed to connect to LiveKit room after {max_retries} attempts")