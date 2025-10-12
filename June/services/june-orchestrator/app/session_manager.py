"""Session management - business logic only"""
import uuid
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class Session:
    """Business session (NOT WebRTC session)"""
    def __init__(self, user_id: str, room_name: Optional[str] = None):
        self.session_id = str(uuid.uuid4())
        self.user_id = user_id
        self.room_name = room_name or f"room-{user_id}"
        self.room_id = abs(hash(self.room_name)) % 10000
        self.janus_room_id = self.room_id  # Janus will create this
        self.created_at = datetime.utcnow()
        self.status = "active"
        self.conversation_history = []
    
    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "room_id": self.room_id,
            "janus_room_id": self.janus_room_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status
        }


class SessionManager:
    """Manage business sessions"""
    
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
    
    def create_session(self, user_id: str, room_name: Optional[str] = None) -> Session:
        """Create new business session"""
        session = Session(user_id, room_name)
        self.sessions[session.session_id] = session
        
        logger.info(f"✅ Created session: {session.session_id} for user: {user_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"🗑️ Deleted session: {session_id}")
            return True
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


# Global instance
session_manager = SessionManager()