"""Session management - simplified to focus on business logic only"""
import uuid
import logging
from typing import Dict, Optional
from datetime import datetime

from .services.livekit_service import livekit_service

logger = logging.getLogger(__name__)


class Session:
    """Business session - LiveKit handles all WebRTC complexities"""
    def __init__(self, user_id: str, room_name: Optional[str] = None):
        self.session_id = str(uuid.uuid4())
        self.user_id = user_id
        self.room_name = room_name or f"room-{user_id}-{uuid.uuid4().hex[:8]}"
        self.created_at = datetime.utcnow()
        self.status = "active"  # Business logic status, not WebRTC status
        self.conversation_history = []
        self.access_token = None
    
    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "room_name": self.room_name,
            "access_token": self.access_token,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "livekit_url": livekit_service.get_connection_info()["livekit_url"]
        }


class SessionManager:
    """Manage business sessions - let LiveKit handle WebRTC lifecycle
    
    This manager focuses on business logic only:
    - User session tracking
    - Conversation history
    - Access token generation
    
    LiveKit automatically handles:
    - Room creation/deletion
    - Participant management
    - Media track lifecycle
    - Connection state management
    """
    
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
    
    def create_session(self, user_id: str, room_name: Optional[str] = None) -> Session:
        """Create new business session with LiveKit access token
        
        No need to create LiveKit room - it will be created automatically
        when the first participant connects with this token.
        """
        try:
            session = Session(user_id, room_name)
            
            # Generate access token - LiveKit handles everything else
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
            
            self.sessions[session.session_id] = session
            
            logger.info(f"✅ Created session: {session.session_id} for user: {user_id}")
            logger.info(f"📝 Room '{session.room_name}' will be auto-created by LiveKit")
            return session
            
        except Exception as e:
            logger.error(f"Failed to create session for user {user_id}: {e}")
            session.status = "failed"
            raise
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    def delete_session(self, session_id: str) -> bool:
        """Delete business session
        
        No need to cleanup LiveKit room - it will be automatically
        deleted when the last participant leaves.
        """
        session = self.get_session(session_id)
        if not session:
            return False
        
        try:
            # Remove from business logic
            del self.sessions[session_id]
            
            logger.info(f"🗑️ Deleted session: {session_id}")
            logger.info(f"📝 LiveKit will auto-cleanup room '{session.room_name}' when empty")
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
    
    def generate_guest_token(self, session_id: str, guest_name: str) -> Optional[str]:
        """Generate access token for a guest user
        
        Guest will join the same LiveKit room automatically.
        """
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
                    "can_publish_data": False,  # Guests can't send data
                    "hidden": False,
                    "recorder": False
                }
            )
        except Exception as e:
            logger.error(f"Failed to generate guest token for {guest_name} in session {session_id}: {e}")
            return None


# Global instance
session_manager = SessionManager()