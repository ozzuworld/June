from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from livekit import api
import os
import logging
import json
import time
import socket

logger = logging.getLogger(__name__)
router = APIRouter()

class SessionCreateRequest(BaseModel):
    user_id: str
    room_name: str

class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    room_name: str
    access_token: str  # LiveKit JWT token
    livekit_url: str   # LiveKit server URL


def _resolve_dns(host: str):
    try:
        start = time.time()
        addr = socket.gethostbyname(host)
        ms = int((time.time() - start) * 1000)
        logger.info(f"[LK DEBUG] DNS resolve host={host} ip={addr} in {ms}ms")
        return addr
    except Exception as e:
        logger.error(f"[LK DEBUG] DNS resolve failed host={host}: {e}")
        return None

@router.post("/", response_model=SessionResponse)
async def create_session(request: SessionCreateRequest):
    """
    Create a new session and generate LiveKit access token with deep debug logs
    """
    try:
        # Get LiveKit credentials from environment
        livekit_api_key = os.getenv("LIVEKIT_API_KEY")
        livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")
        livekit_url = os.getenv("LIVEKIT_WS_URL", "wss://livekit.ozzu.world")

        # Structured debug: environment snapshot (safe)
        logger.info(
            json.dumps({
                "event": "livekit.session.request",
                "user_id": request.user_id,
                "room_name": request.room_name,
                "env": {
                    "LIVEKIT_WS_URL": livekit_url,
                    "LIVEKIT_API_KEY_set": bool(livekit_api_key),
                    "LIVEKIT_API_SECRET_set": bool(livekit_api_secret),
                }
            })
        )

        if not livekit_api_key or not livekit_api_secret:
            logger.error("[LK DEBUG] LiveKit credentials not configured")
            raise HTTPException(
                status_code=500,
                detail="LiveKit credentials not configured"
            )

        # Resolve DNS of LiveKit host
        try:
            if livekit_url.startswith("ws"):
                host = livekit_url.split("://", 1)[1].split("/", 1)[0].split(":")[0]
                _resolve_dns(host)
        except Exception as e:
            logger.warning(f"[LK DEBUG] Could not parse/resolve LiveKit host from URL {livekit_url}: {e}")

        # Generate unique session ID
        import uuid
        session_id = str(uuid.uuid4())

        # Create LiveKit access token
        grants = api.VideoGrants(
            room_join=True,
            room=request.room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        )
        token = (
            api.AccessToken(livekit_api_key, livekit_api_secret)
            .with_identity(request.user_id)
            .with_name(request.user_id)
            .with_grants(grants)
            .to_jwt()
        )

        # Log token metadata only (never full secret)
        logger.info(
            json.dumps({
                "event": "livekit.session.issued",
                "session_id": session_id,
                "user_id": request.user_id,
                "room_name": request.room_name,
                "livekit_url": livekit_url,
                "token_len": len(token),
                "token_prefix": token[:16],
                "token_suffix": token[-16:],
            })
        )

        return SessionResponse(
            session_id=session_id,
            user_id=request.user_id,
            room_name=request.room_name,
            access_token=token,
            livekit_url=livekit_url
        )

    except Exception as e:
        logger.error(f"[LK DEBUG] Failed to create session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create session: {str(e)}"
        )
