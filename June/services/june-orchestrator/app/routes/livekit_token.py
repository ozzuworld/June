"""LiveKit token generation routes (LiveKit SDK-based, explicit Body binding)"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Body
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
async def generate_livekit_token(
    body: LiveKitTokenRequest = Body(...),  # Explicit body binding for flat JSON
    current_user = Depends(get_current_user),
):
    """Generate a LiveKit JWT using LiveKit's Python SDK with VideoGrants.
    Expects a flat JSON body: {"roomName": "...", "participantName": "..."}
    """
    try:
        user_sub = current_user.get("sub", body.participantName)
        logger.info(f"🎫 Generating LiveKit token for user {user_sub} in room {body.roomName}")

        grants = lk_api.VideoGrants(
            room_join=True,
            room=body.roomName,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )

        at = (
            lk_api.AccessToken(
                api_key=config.livekit.api_key,
                api_secret=config.livekit.api_secret,
            )
            .with_identity(body.participantName)
            .with_grants(grants)
        )
        if body.metadata:
            at = at.with_metadata(body.metadata)

        token = at.to_jwt()

        livekit_url = config.livekit.ws_url
        if livekit_url.startswith("ws://"):
            livekit_url = livekit_url.replace("ws://", "wss://")
        livekit_url = livekit_url.replace(":7880", "")

        logger.info(f"✅ LiveKit token generated for participant {body.participantName}")
        return LiveKitTokenResponse(
            token=token,
            roomName=body.roomName,
            participantName=body.participantName,
            livekitUrl=livekit_url,
        )
    except Exception as e:
        logger.exception("Failed to generate LiveKit token")
        raise HTTPException(status_code=500, detail=f"Failed to generate LiveKit token: {e}")
