#!/usr/bin/env python3
"""
LiveKit Token Management
Handles token retrieval and room connection
"""

import os
import asyncio
import logging
import httpx
from livekit import rtc
from config import config

logger = logging.getLogger("cosyvoice2-tts")


async def get_livekit_token(
    identity: str,
    room_name: str = "ozzu-main",
    max_retries: int = 3
) -> tuple[str, str]:
    """
    Get LiveKit token from orchestrator service
    
    Args:
        identity: Participant identity
        room_name: Room to join
        max_retries: Maximum retry attempts
        
    Returns:
        tuple: (ws_url, token)
    """
    
    base_url = os.getenv(
        "ORCHESTRATOR_URL",
        "http://api.ozzu.world"
    )
    
    # Try multiple endpoints
    endpoints = ["/api/livekit/token", "/token"]
    
    last_error = None
    
    for attempt in range(max_retries):
        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            
            try:
                timeout = 5.0 + attempt  # Incremental backoff
                
                async with httpx.AsyncClient(timeout=timeout) as client:
                    payload = {
                        "roomName": room_name,
                        "participantName": identity
                    }
                    
                    logger.info(
                        f"Requesting LiveKit token from {url} "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    
                    data = response.json()
                    
                    # Extract WebSocket URL and token
                    ws_url = (
                        data.get("livekitUrl") or
                        data.get("ws_url") or
                        config.livekit.ws_url
                    )
                    token = data["token"]
                    
                    logger.info(f"✅ LiveKit token received for {identity}")
                    return ws_url, token
                    
            except Exception as e:
                last_error = e
                logger.warning(f"Token request failed at {url}: {e}")
        
        # Wait before retry
        if attempt < max_retries - 1:
            await asyncio.sleep(1.0 + attempt)
    
    raise RuntimeError(
        f"Failed to get LiveKit token after {max_retries} attempts: {last_error}"
    )


async def connect_room_as_publisher(
    room: rtc.Room,
    identity: str,
    room_name: str = "ozzu-main"
) -> None:
    """
    Connect to LiveKit room as audio publisher
    
    Args:
        room: LiveKit Room instance
        identity: Participant identity
        room_name: Room to join
    """
    
    ws_url, token = await get_livekit_token(identity, room_name)
    
    logger.info(f"🔗 Connecting to LiveKit room: {room_name}")
    await room.connect(ws_url, token)
    logger.info(f"✅ Connected to room: {room_name}")