from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from livekit import api
import os
import logging

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

@router.post("/", response_model=SessionResponse)
async def create_session(request: SessionCreateRequest):
    """
    Create a new session and generate LiveKit access token
    """
    try:
        # Get LiveKit credentials from environment
        livekit_api_key = os.getenv("LIVEKIT_API_KEY")
        livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")
        livekit_url = os.getenv("LIVEKIT_WS_URL", "wss://livekit.ozzu.world")
        
        if not livekit_api_key or not livekit_api_secret:
            logger.error("LiveKit credentials not configured")
            raise HTTPException(
                status_code=500, 
                detail="LiveKit credentials not configured"
            )
        
        # Generate unique session ID
        import uuid
        session_id = str(uuid.uuid4())
        
        # Create LiveKit access token
        token = (
            api.AccessToken(livekit_api_key, livekit_api_secret)
            .with_identity(request.user_id)
            .with_name(request.user_id)
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=request.room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                )
            )
            .to_jwt()
        )
        
        logger.info(
            f"Generated LiveKit token for user={request.user_id}, "
            f"room={request.room_name}, session={session_id}"
        )
        
        return SessionResponse(
            session_id=session_id,
            user_id=request.user_id,
            room_name=request.room_name,
            access_token=token,
            livekit_url=livekit_url
        )
        
    except Exception as e:
        logger.error(f"Failed to create session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create session: {str(e)}"
        )