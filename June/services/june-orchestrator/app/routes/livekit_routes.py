"""
LiveKit Endpoints
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends

from ..models import LiveKitTokenRequest, LiveKitTokenResponse
from ..dependencies import simple_auth
from ..livekit import livekit_manager, livekit_config

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/token", response_model=LiveKitTokenResponse)
async def create_token(
    request: LiveKitTokenRequest,
    auth_data: dict = Depends(simple_auth)
):
    """Create LiveKit access token"""
    try:
        if not livekit_config.is_configured:
            raise HTTPException(
                status_code=503,
                detail="LiveKit not configured"
            )
        
        token = await livekit_manager.create_token(
            user_id=request.user_id,
            room_name=request.room_name,
            metadata=auth_data
        )
        
        room_name = request.room_name or f"{livekit_config.default_room_name}-{request.user_id}"
        
        # Convert ws:// to wss:// for external access
        external_url = livekit_config.url.replace("ws://", "wss://")
        
        return LiveKitTokenResponse(
            token=token,
            url=external_url,
            room_name=room_name
        )
        
    except Exception as e:
        logger.error(f"Token creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rooms")
async def list_rooms():
    """List active LiveKit rooms"""
    try:
        if not livekit_config.is_configured:
            raise HTTPException(
                status_code=503,
                detail="LiveKit not configured"
            )
        
        rooms = await livekit_manager.list_rooms()
        return {"rooms": rooms}
        
    except Exception as e:
        logger.error(f"Failed to list rooms: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rooms/{room_name}")
async def get_room(room_name: str):
    """Get room information"""
    try:
        if not livekit_config.is_configured:
            raise HTTPException(
                status_code=503,
                detail="LiveKit not configured"
            )
        
        room = await livekit_manager.get_room(room_name)
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        return room
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get room: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rooms/{room_name}")
async def delete_room(room_name: str):
    """Delete a room"""
    try:
        if not livekit_config.is_configured:
            raise HTTPException(
                status_code=503,
                detail="LiveKit not configured"
            )
        
        success = await livekit_manager.delete_room(room_name)
        
        if not success:
            raise HTTPException(status_code=404, detail="Room not found")
        
        return {"message": "Room deleted", "room_name": room_name}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete room: {e}")
        raise HTTPException(status_code=500, detail=str(e))