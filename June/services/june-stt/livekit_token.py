import os
import httpx
from livekit import rtc
from config import config

async def get_livekit_token(identity: str) -> tuple[str, str]:
    base = os.getenv("ORCHESTRATOR_URL", config.ORCHESTRATOR_URL or "http://june-orchestrator:8080")
    url = f"{base}/livekit/token"
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(url, json={"service_identity": identity})
        r.raise_for_status()
        data = r.json()
        return data.get("ws_url") or config.LIVEKIT_WS_URL, data["token"]

async def connect_room_as_subscriber(room: rtc.Room, identity: str) -> None:
    ws_url, token = await get_livekit_token(identity)
    await room.connect(ws_url, token)
