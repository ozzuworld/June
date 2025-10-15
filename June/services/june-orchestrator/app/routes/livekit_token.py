"""LiveKit token generation routes (LiveKit SDK-based)"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from livekit import api as lk_api

from ..config import config
from ..dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

class LiveKitTokenRequest(BaseModel):
    roomName: str
    participantName: str
    metadata: Optional[str] = None

class LiveKitTokenResponse(BaseModel):
    token: str
    roomName: str
    participantName: str
    livekitUrl: Optional[str] = None

@router.post("/token", response_model=LiveKitTokenResponse)
async def generate_livekit_token(livekit_req: LiveKitTokenRequest, current_user=Depends(get_current_user)):
    """Generate a LiveKit JWT using LiveKit's Python SDK with VideoGrants.
    Expects a flat JSON body (roomName, participantName)."""
    try:
        user_sub = current_user.get("sub", livekit_req.participantName)
        logger.info(f"🎫 Generating LiveKit token for user {user_sub} in room {livekit_req.roomName}")

        # Build grants
        grants = lk_api.VideoGrants(
            room_join=True,
            room=livekit_req.roomName,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )

        # Build token with identity and optional metadata
        at = (
            lk_api.AccessToken(
                api_key=config.livekit.api_key,
                api_secret=config.livekit.api_secret,
            )
            .with_identity(livekit_req.participantName)
            .with_grants(grants)
        )
        if livekit_req.metadata:
            at = at.with_metadata(livekit_req.metadata)

        token = at.to_jwt()

        # Prefer wss URL if configured; otherwise, transform ws:// to wss:// for public use
        livekit_url = config.livekit.ws_url
        if livekit_url.startswith("ws://"):
            livekit_url = livekit_url.replace("ws://", "wss://")
        # If your internal URL includes :7880 but your public URL is on default TLS port, trim as needed.
        livekit_url = livekit_url.replace(":7880", "")

        logger.info(f"✅ LiveKit token generated for participant {livekit_req.participantName}")
        return LiveKitTokenResponse(
            token=token,
            roomName=livekit_req.roomName,
            participantName=livekit_req.participantName,
            livekitUrl=livekit_url,
        )
    except Exception as e:
        logger.exception("Failed to generate LiveKit token")
        raise HTTPException(status_code=500, detail=f"Failed to generate LiveKit token: {e}")
