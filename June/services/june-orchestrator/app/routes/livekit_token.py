"""LiveKit token generation routes (LiveKit SDK-based, anonymous Body binding)"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Body
from livekit import api as lk_api

from ..config import config
from ..dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/token")
async def generate_livekit_token(
    body = Body(...),                 # Anonymous body binding to accept flat JSON
    current_user = Depends(get_current_user),
):
    """Generate a LiveKit JWT using LiveKit's Python SDK with VideoGrants.
    Expects a flat JSON body: {"roomName": "...", "participantName": "..."}
    """
    try:
        room_name = body.get("roomName")
        participant_name = body.get("participantName")
        metadata = body.get("metadata")

        if not room_name or not participant_name:
            raise HTTPException(status_code=400, detail="roomName and participantName are required")

        user_sub = current_user.get("sub", participant_name)
        logger.info(f"🎫 Generating LiveKit token for user {user_sub} in room {room_name}")

        grants = lk_api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )

        at = (
            lk_api.AccessToken(
                api_key=config.livekit.api_key,
                api_secret=config.livekit.api_secret,
            )
            .with_identity(participant_name)
            .with_grants(grants)
        )
        if metadata:
            at = at.with_metadata(metadata)

        token = at.to_jwt()

        livekit_url = config.livekit.ws_url
        if livekit_url.startswith("ws://"):
            livekit_url = livekit_url.replace("ws://", "wss://")
        livekit_url = livekit_url.replace(":7880", "")

        logger.info(f"✅ LiveKit token generated for participant {participant_name}")
        return {
            "token": token,
            "roomName": room_name,
            "participantName": participant_name,
            "livekitUrl": livekit_url,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to generate LiveKit token")
        raise HTTPException(status_code=500, detail=f"Failed to generate LiveKit token: {e}")
