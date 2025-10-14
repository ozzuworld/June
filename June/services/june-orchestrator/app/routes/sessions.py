"""Session management routes with LiveKit integration"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from typing import List

from ..models import (
    SessionCreate, 
    SessionResponse, 
    ParticipantInfo, 
    RoomInfo,
    GuestTokenRequest,
    GuestTokenResponse
)
from ..session_manager import session_manager
from ..config import config

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=SessionResponse)
async def create_session(request: SessionCreate):
    """Create new business session with LiveKit room"""
    try:
        session = await session_manager.create_session(
            user_id=request.user_id,
            room_name=request.room_name
        )
        
        return SessionResponse(**session.to_dict())
        
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Get session information"""
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return SessionResponse(**session.to_dict())


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete session and cleanup LiveKit room"""
    success = await session_manager.delete_session(session_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"status": "deleted", "session_id": session_id}


@router.get("/{session_id}/history")
async def get_conversation_history(session_id: str):
    """Get conversation history"""
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session_id,
        "history": session.conversation_history
    }


@router.get("/{session_id}/participants", response_model=List[ParticipantInfo])
async def get_session_participants(session_id: str):
    """Get participants in the session's LiveKit room"""
    try:
        participants = await session_manager.get_room_participants(session_id)
        return [ParticipantInfo(**p) for p in participants]
    except Exception as e:
        logger.error(f"Failed to get participants for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}/participants/{participant_identity}")
async def remove_participant(session_id: str, participant_identity: str):
    """Remove a participant from the session's room"""
    try:
        success = await session_manager.remove_participant(session_id, participant_identity)
        
        if not success:
            raise HTTPException(status_code=404, detail="Participant not found or session not found")
        
        return {
            "status": "removed", 
            "session_id": session_id, 
            "participant": participant_identity
        }
    except Exception as e:
        logger.error(f"Failed to remove participant {participant_identity}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/guest-token", response_model=GuestTokenResponse)
async def generate_guest_token(session_id: str, request: GuestTokenRequest):
    """Generate access token for a guest user"""
    try:
        # Validate session exists
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Generate guest token
        access_token = session_manager.generate_guest_token(session_id, request.guest_name)
        
        if not access_token:
            raise HTTPException(status_code=500, detail="Failed to generate guest token")
        
        return GuestTokenResponse(
            access_token=access_token,
            room_name=session.room_name,
            livekit_ws_url=config.livekit.ws_url,
            guest_name=request.guest_name
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate guest token: {e}")
        raise HTTPException(status_code=500, detail=str(e))