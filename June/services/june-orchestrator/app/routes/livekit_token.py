"""LiveKit token generation routes (fixed for proper JWT format)"""
import logging
import time
import datetime
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

        # Create video grants according to LiveKit specification
        grants = lk_api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
        
        # Create access token with explicit TTL to avoid scientific notation issues
        # Standard 6-hour TTL to match LiveKit best practices
        ttl = datetime.timedelta(hours=6)
        
        at = (
            lk_api.AccessToken(
                api_key=config.livekit.api_key,
                api_secret=config.livekit.api_secret,
            )
            .with_identity(str(participant_name))  # Ensure string format
            .with_name(str(participant_name))      # Add name claim
            .with_ttl(ttl)                         # Explicit TTL
            .with_grants(grants)
        )
        
        if metadata:
            at = at.with_metadata(str(metadata))

        # Generate token
        token = at.to_jwt()
        
        # Log token for debugging (first 50 chars)
        logger.info(f"[TOKEN REQ] Generated token: {token[:50]}...")
        
        # Return LiveKit URL exactly as configured - no transformations
        livekit_url = config.livekit.ws_url

        logger.info(f"[TOKEN REQ] Success; total elapsed: {time.time()-t0:.3f}s")
        
        response_data = {
            "token": token,
            "roomName": str(room_name),
            "participantName": str(participant_name),
            "livekitUrl": livekit_url,
        }
        
        logger.info(f"[TOKEN REQ] Response data: {response_data}")
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[TOKEN REQ] Generation failed")
        raise HTTPException(status_code=500, detail=f"Failed to generate LiveKit token: {e}")