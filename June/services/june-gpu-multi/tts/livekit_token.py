import os
import asyncio
import logging
from typing import Optional
from livekit import api, rtc
from config import config

logger = logging.getLogger(__name__)

async def get_token_from_orchestrator(participant_identity: str) -> str:
    """Get LiveKit token from orchestrator service"""
    import httpx
    
    orchestrator_url = config.ORCHESTRATOR_URL or "http://june-orchestrator.june-services.svc.cluster.local:8080"
    
    payload = {
        "participant_identity": participant_identity,
        "room_name": config.ROOM_NAME or "ozzu-main"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{orchestrator_url}/api/livekit/token",
            json=payload,
            headers={"Authorization": f"Bearer {config.BEARER_TOKEN}"} if config.BEARER_TOKEN else {}
        )
        response.raise_for_status()
        data = response.json()
        return data["token"]

async def connect_room_as_publisher(room: rtc.Room, participant_identity: str):
    """Connect to LiveKit room as publisher using orchestrator token"""
    try:
        token = await get_token_from_orchestrator(participant_identity)
        
        livekit_url = config.LIVEKIT_WS_URL or "ws://livekit-livekit-server.june-services.svc.cluster.local:80"
        
        await room.connect(livekit_url, token)
        logger.info(f"Connected to LiveKit room as {participant_identity}")
        
    except Exception as e:
        logger.error(f"Failed to connect to LiveKit room: {e}")
        raise