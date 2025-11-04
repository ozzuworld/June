import os
import asyncio
import logging
import httpx
from livekit import rtc
from config import config

logger = logging.getLogger(__name__)

async def get_livekit_token(identity: str, room_name: str = "ozzu-main", max_retries: int = 3) -> tuple[str, str]:
    """Get LiveKit token with retry logic (updated payload + single known-good path)"""
    base = os.getenv("ORCHESTRATOR_URL", getattr(config, "ORCHESTRATOR_URL", "http://june-orchestrator.june-services.svc.cluster.local:8080"))

    # Standardize on the working endpoint to avoid 404 noise and retries
    paths = ["/token"]

    last_err = None
    for attempt in range(max_retries):
        for path in paths:
            url = f"{base}{path}"
            try:
                timeout = 5.0 + (attempt * 2.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    logger.info(f"Getting LiveKit token from {url} (attempt {attempt + 1}/{max_retries})")
                    payload = {"roomName": room_name, "participantName": identity}
                    r = await client.post(url, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    ws_url = data.get("livekitUrl") or data.get("ws_url") or getattr(config, "LIVEKIT_WS_URL", "wss://livekit.ozzu.world")
                    token = data["token"]
                    logger.info("LiveKit token received")
                    return ws_url, token
            except Exception as e:
                last_err = e
                logger.warning(f"Token request failed at {url}: {e}")
        if attempt < max_retries - 1:
            await asyncio.sleep(2.0 * (attempt + 1))

    raise RuntimeError(f"Failed to get LiveKit token after {max_retries} attempts: {last_err}")

async def connect_room_as_subscriber(room: rtc.Room, identity: str, room_name: str = "ozzu-main", max_retries: int = 3) -> None:
    """Connect to LiveKit room with retry logic"""
    for attempt in range(max_retries):
        try:
            logger.info(f"Connecting to LiveKit as {identity} (attempt {attempt + 1}/{max_retries})")
            ws_url, token = await get_livekit_token(identity, room_name=room_name, max_retries=2)
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
