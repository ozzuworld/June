"""Session management routes - simplified for LiveKit auto-management"""
import logging
from fastapi import APIRouter, HTTPException

from ..models import (
    SessionCreate, 
    SessionResponse, 
    GuestTokenRequest,
    GuestTokenResponse
)
from ..session_manager import session_manager
from ..config import config

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=SessionResponse)
def create_session(request: SessionCreate):
    """Create new business session with LiveKit access token
    
    LiveKit will automatically:
    - Create the room when first participant connects
    - Handle all participant management
    - Clean up when room becomes empty
    """
    try:
        session = session_manager.create_session(
            user_id=request.user_id,
            room_name=request.room_name
        )
        
        return SessionResponse(**session.to_dict())
        
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    """Get session information with LiveKit connection details"""
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return SessionResponse(**session.to_dict())


@router.delete("/{session_id}")
def delete_session(session_id: str):
    """Delete business session
    
    LiveKit room will be automatically cleaned up when participants leave.
    """
    success = session_manager.delete_session(session_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "status": "deleted", 
        "session_id": session_id,
        "note": "LiveKit room will auto-cleanup when empty"
    }


@router.get("/{session_id}/history")
def get_conversation_history(session_id: str):
    """Get conversation history"""
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session_id,
        "history": session.conversation_history
    }


@router.post("/{session_id}/guest-token", response_model=GuestTokenResponse)
def generate_guest_token(session_id: str, request: GuestTokenRequest):
    """Generate access token for a guest user
    
    Guest will automatically join the existing LiveKit room.
    """
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