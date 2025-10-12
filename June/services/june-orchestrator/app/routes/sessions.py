"""Session management routes"""
import logging
from fastapi import APIRouter, HTTPException

from ..models import SessionCreate, SessionResponse
from ..session_manager import session_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=SessionResponse)
async def create_session(request: SessionCreate):
    """Create new business session"""
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
async def get_session(session_id: str):
    """Get session information"""
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return SessionResponse(**session.to_dict())


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete session"""
    success = session_manager.delete_session(session_id)
    
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