"""LiveKit token generation routes (direct JSON parsing with timing logs)"""
import logging
import time
from fastapi import APIRouter, HTTPException, Depends, Request
from livekit import api as lk_api

from ..config import config
from ..dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/token")
async def generate_livekit_token(
    request: Request,
    current_user = Depends(get_current_user),
):
    t0 = time.time()
    logger.info("[TOKEN REQ] Entered route, starting parse…")
    try:
        body = await request.json()
        logger.info(f"[TOKEN REQ] Parsed body: {body!r}")
        logger.info(f"[TOKEN REQ] current_user: {current_user!r}")
        logger.info(f"[TOKEN REQ] elapsed after parse: {time.time()-t0:.3f}s")

        room_name = body.get("roomName")
        participant_name = body.get("participantName")
        metadata = body.get("metadata")

        if not room_name or not participant_name:
            raise HTTPException(status_code=400, detail="roomName and participantName are required")

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

        logger.info(f"[TOKEN REQ] Success; total elapsed: {time.time()-t0:.3f}s")
        return {
            "token": token,
            "roomName": room_name,
            "participantName": participant_name,
            "livekitUrl": livekit_url,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[TOKEN REQ] Generation failed")
        raise HTTPException(status_code=500, detail=f"Failed to generate LiveKit token: {e}")
