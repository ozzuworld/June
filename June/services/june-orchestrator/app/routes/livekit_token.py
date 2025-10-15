"""LiveKit token generation routes (LiveKit SDK-based, flat body)"""
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
async def generate_livekit_token(
    model: LiveKitTokenRequest,  # Accept flat JSON body (no wrapper key)
    current_user = Depends(get_current_user),
):
    """Generate a LiveKit JWT using LiveKit's Python SDK with VideoGrants.
    Expects a flat JSON body: {"roomName": "...", "participantName": "..."}
    """
    try:
        user_sub = current_user.get("sub", model.participantName)
        logger.info(f"🎫 Generating LiveKit token for user {user_sub} in room {model.roomName}")

        grants = lk_api.VideoGrants(
            room_join=True,
            room=model.roomName,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )

        at = (
            lk_api.AccessToken(
                api_key=config.livekit.api_key,
                api_secret=config.livekit.api_secret,
            )
            .with_identity(model.participantName)
            .with_grants(grants)
        )
        if model.metadata:
            at = at.with_metadata(model.metadata)

        token = at.to_jwt()

        livekit_url = config.livekit.ws_url
        if livekit_url.startswith("ws://"):
            livekit_url = livekit_url.replace("ws://", "wss://")
        livekit_url = livekit_url.replace(":7880", "")

        logger.info(f"✅ LiveKit token generated for participant {model.participantName}")
        return LiveKitTokenResponse(
            token=token,
            roomName=model.roomName,
            participantName=model.participantName,
            livekitUrl=livekit_url,
        )
    except Exception as e:
        logger.exception("Failed to generate LiveKit token")
        raise HTTPException(status_code=500, detail=f"Failed to generate LiveKit token: {e}")
