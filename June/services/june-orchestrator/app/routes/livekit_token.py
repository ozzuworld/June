"""LiveKit token generation routes"""
import logging
import time
import jwt
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from ..config import config
from ..dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


class LiveKitTokenRequest(BaseModel):
    """LiveKit token request model"""
    roomName: str
    participantName: str
    metadata: Optional[str] = None


class LiveKitTokenResponse(BaseModel):
    """LiveKit token response model"""
    token: str
    roomName: str
    participantName: str
    livekitUrl: Optional[str] = None
    sessionId: Optional[str] = None


@router.post("/token", response_model=LiveKitTokenResponse)
async def generate_livekit_token(
    request: LiveKitTokenRequest,
    current_user=Depends(get_current_user)
):
    """Generate LiveKit JWT token for authenticated user"""
    try:
        logger.info(f"🎫 Generating LiveKit token for user {current_user.get('sub', 'unknown')} in room {request.roomName}")
        
        # Create JWT payload for LiveKit
        payload = {
            "iss": config.livekit.api_key,
            "sub": current_user.get("sub", request.participantName),
            "aud": "livekit",
            "exp": int(time.time()) + 3600,  # 1 hour expiration
            "video": {
                "room": request.roomName,
                "roomJoin": True,
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": True,
            },
            # Optional: Add user metadata
            "metadata": request.metadata or f"{{\"user_id\": \"{current_user.get('sub')}\", \"email\": \"{current_user.get('email')}\"}}" 
        }
        
        # Generate JWT token
        token = jwt.encode(
            payload, 
            config.livekit.api_secret, 
            algorithm="HS256"
        )
        
        logger.info(f"✅ Generated LiveKit token for room {request.roomName}, participant {request.participantName}")
        
        # Generate session ID (you can customize this logic)
        session_id = f"session_{int(time.time())}_{current_user.get('sub', 'unknown')[:8]}"
        
        return LiveKitTokenResponse(
            token=token,
            roomName=request.roomName,
            participantName=request.participantName,
            livekitUrl=config.livekit.ws_url.replace("ws://", "wss://").replace(":7880", ""),  # Convert to public URL
            sessionId=session_id
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to generate LiveKit token: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate LiveKit token: {str(e)}"
        )