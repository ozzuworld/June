"""Session management - business logic with LiveKit integration"""
import uuid
import logging
from typing import Dict, Optional
from datetime import datetime

from .services.livekit_service import livekit_service

logger = logging.getLogger(__name__)


class Session:
    """Business session with LiveKit integration"""
    def __init__(self, user_id: str, room_name: Optional[str] = None):
        self.session_id = str(uuid.uuid4())
        self.user_id = user_id
        self.room_name = room_name or f"room-{user_id}-{uuid.uuid4().hex[:8]}"
        self.created_at = datetime.utcnow()
        self.status = "created"
        self.conversation_history = []
        self.livekit_room_sid = None
        self.access_token = None
    
    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "room_name": self.room_name,
            "livekit_room_sid": self.livekit_room_sid,
            "access_token": self.access_token,
            "created_at": self.created_at.isoformat(),
            "status": self.status
        }


class SessionManager:
    """Manage business sessions with LiveKit integration"""
    
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
    
    async def create_session(self, user_id: str, room_name: Optional[str] = None) -> Session:
        """Create new business session with LiveKit room"""
        try:
            session = Session(user_id, room_name)
            
            # Create LiveKit room
            room_info = await livekit_service.create_room(
                room_name=session.room_name,
                max_participants=10
            )
            
            # Store room SID
            session.livekit_room_sid = room_info["room_sid"]
            
            # Generate access token for the user
            session.access_token = livekit_service.generate_access_token(
                room_name=session.room_name,
                participant_name=user_id,
                permissions={
                    "can_publish": True,
                    "can_subscribe": True,
                    "can_publish_data": True,
                    "hidden": False,
                    "recorder": False
                }
            )
            
            session.status = "active"
            self.sessions[session.session_id] = session
            
            logger.info(f"✅ Created session: {session.session_id} for user: {user_id} with LiveKit room: {session.room_name}")
            return session
            
        except Exception as e:
            logger.error(f"Failed to create session for user {user_id}: {e}")
            session.status = "failed"
            raise
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete session and cleanup LiveKit room"""
        session = self.get_session(session_id)
        if not session:
            return False
        
        try:
            # Delete LiveKit room
            if session.room_name:
                await livekit_service.delete_room(session.room_name)
            
            # Remove from sessions
            del self.sessions[session_id]
            
            logger.info(f"🗑️ Deleted session: {session_id} and LiveKit room: {session.room_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False
    
    def add_to_history(self, session_id: str, role: str, content: str):
        """Add message to conversation history"""
        session = self.get_session(session_id)
        if session:
            session.conversation_history.append({
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat()
            })
    
    async def get_room_participants(self, session_id: str) -> list:
        """Get participants in the session's LiveKit room"""
        session = self.get_session(session_id)
        if not session or not session.room_name:
            return []
        
        try:
            return await livekit_service.list_participants(session.room_name)
        except Exception as e:
            logger.error(f"Failed to get participants for session {session_id}: {e}")
            return []
    
    async def remove_participant(self, session_id: str, participant_identity: str) -> bool:
        """Remove a participant from the session's room"""
        session = self.get_session(session_id)
        if not session or not session.room_name:
            return False
        
        try:
            return await livekit_service.remove_participant(
                session.room_name, 
                participant_identity
            )
        except Exception as e:
            logger.error(f"Failed to remove participant {participant_identity} from session {session_id}: {e}")
            return False
    
    def generate_guest_token(self, session_id: str, guest_name: str) -> Optional[str]:
        """Generate access token for a guest user"""
        session = self.get_session(session_id)
        if not session or not session.room_name:
            return None
        
        try:
            return livekit_service.generate_access_token(
                room_name=session.room_name,
                participant_name=guest_name,
                permissions={
                    "can_publish": True,
                    "can_subscribe": True,
                    "can_publish_data": False,
                    "hidden": False,
                    "recorder": False
                }
            )
        except Exception as e:
            logger.error(f"Failed to generate guest token for {guest_name} in session {session_id}: {e}")
            return None


# Global instance
session_manager = SessionManager()