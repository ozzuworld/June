import os
import asyncio
import logging
import httpx
from livekit import rtc
from config import config

logger = logging.getLogger("june-tts")

async def get_livekit_token(identity: str, room_name: str = "ozzu-main", max_retries: int = 2) -> tuple[str, str]:
    """Get LiveKit token with resilience: new payload + dual-path fallback"""
    base = os.getenv("ORCHESTRATOR_URL", getattr(config, "ORCHESTRATOR_URL", "http://api.ozzu.world"))
    paths = ["/api/livekit/token", "/token"]

    last_err = None
    for attempt in range(max_retries):
        for path in paths:
            url = f"{base}{path}"
            try:
                timeout = 5.0 + attempt  # small backoff per attempt
                async with httpx.AsyncClient(timeout=timeout) as client:
                    payload = {"roomName": room_name, "participantName": identity}
                    logger.info(f"Requesting LiveKit token from {url} (attempt {attempt+1}/{max_retries}) payload={payload}")
                    r = await client.post(url, json=payload)
                    r.raise_for_status()
                    data = r.json()
                    ws_url = data.get("livekitUrl") or data.get("ws_url") or getattr(config, "LIVEKIT_WS_URL", "wss://livekit.ozzu.world")
                    token = data["token"]
                    logger.info("LiveKit token received for TTS")
                    return ws_url, token
            except Exception as e:
                last_err = e
                logger.warning(f"Token request failed at {url}: {e}")
        if attempt < max_retries - 1:
            await asyncio.sleep(1.0 + attempt)
    raise RuntimeError(f"TTS failed to get LiveKit token after {max_retries} attempts: {last_err}")

async def connect_room_as_publisher(room: rtc.Room, identity: str, room_name: str = "ozzu-main") -> None:
    ws_url, token = await get_livekit_token(identity, room_name=room_name)
    await room.connect(ws_url, token)
