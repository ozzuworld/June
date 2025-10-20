"""Session management - Enhanced with memory and room mapping"""
import uuid
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from collections import defaultdict

from .services.livekit_service import livekit_service

logger = logging.getLogger(__name__)


class Session:
    """Business session with full conversation memory"""
    def __init__(self, user_id: str, room_name: Optional[str] = None):
        self.session_id = str(uuid.uuid4())
        self.user_id = user_id
        self.room_name = room_name or f"room-{user_id}-{uuid.uuid4().hex[:8]}"
        self.created_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.status = "active"
        self.conversation_history: List[Dict] = []
        self.access_token = None
        
        # Enhanced metrics
        self.message_count = 0
        self.total_tokens_used = 0
        self.avg_response_time_ms = 0
        
        # Context management
        self.context_summary = None  # For long conversations
        self.max_history_messages = 20  # Keep recent 20 messages
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.utcnow()
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add message to conversation history with metadata"""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        })
        self.message_count += 1
        self.update_activity()
    
    def get_recent_history(self, max_messages: Optional[int] = None) -> List[Dict]:
        """Get recent conversation history"""
        max_msg = max_messages or self.max_history_messages
        
        # Always include context summary if it exists
        history = []
        if self.context_summary:
            history.append({
                "role": "system",
                "content": self.context_summary
            })
        
        # Add recent messages
        recent = self.conversation_history[-max_msg:]
        history.extend(recent)
        
        return history
    
    def should_summarize(self) -> bool:
        """Check if conversation should be summarized"""
        return len(self.conversation_history) > self.max_history_messages
    
    def is_expired(self, timeout_hours: int = 24) -> bool:
        """Check if session has expired"""
        expiry_time = self.last_activity + timedelta(hours=timeout_hours)
        return datetime.utcnow() > expiry_time
    
    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "room_name": self.room_name,
            "access_token": self.access_token,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "status": self.status,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens_used,
            "livekit_url": livekit_service.get_connection_info()["livekit_url"]
        }


class SessionManager:
    """Enhanced session manager with room mapping and memory"""
    
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self.room_to_session: Dict[str, str] = {}  # room_name -> session_id
        self.user_sessions: Dict[str, List[str]] = defaultdict(list)  # user_id -> [session_ids]
        
        # Metrics
        self.total_sessions_created = 0
        self.total_messages_processed = 0
        
        logger.info("✅ Session Manager initialized with memory support")
    
    def create_session(self, user_id: str, room_name: Optional[str] = None) -> Session:
        """Create new session with LiveKit access token"""
        try:
            session = Session(user_id, room_name)
            
            # Generate LiveKit token
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
            
            # Store session
            self.sessions[session.session_id] = session
            self.room_to_session[session.room_name] = session.session_id
            self.user_sessions[user_id].append(session.session_id)
            
            self.total_sessions_created += 1
            
            logger.info(f"✅ Created session: {session.session_id} for user: {user_id}")
            logger.info(f"📝 Room '{session.room_name}' mapped to session")
            return session
            
        except Exception as e:
            logger.error(f"Failed to create session for user {user_id}: {e}")
            raise
    
    def get_or_create_session_for_room(self, room_name: str, user_id: str) -> Session:
        """Get existing session for room or create new one
        
        THIS IS THE KEY METHOD FOR WEBHOOKS!
        """
        # Check if room already has a session
        session_id = self.room_to_session.get(room_name)
        
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            session.update_activity()
            logger.info(f"🔄 Reusing session {session_id} for room {room_name}")
            return session
        
        # Create new session for this room
        logger.info(f"🆕 Creating new session for room {room_name}")
        return self.create_session(user_id, room_name)
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        return self.sessions.get(session_id)
    
    def get_session_by_room(self, room_name: str) -> Optional[Session]:
        """Get session by room name"""
        session_id = self.room_to_session.get(room_name)
        if session_id:
            return self.sessions.get(session_id)
        return None
    
    def get_user_sessions(self, user_id: str) -> List[Session]:
        """Get all sessions for a user"""
        session_ids = self.user_sessions.get(user_id, [])
        return [self.sessions[sid] for sid in session_ids if sid in self.sessions]
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session and cleanup mappings"""
        session = self.get_session(session_id)
        if not session:
            return False
        
        try:
            # Remove from all mappings
            if session.room_name in self.room_to_session:
                del self.room_to_session[session.room_name]
            
            if session.user_id in self.user_sessions:
                self.user_sessions[session.user_id].remove(session_id)
            
            del self.sessions[session_id]
            
            logger.info(f"🗑️ Deleted session: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False
    
    def add_to_history(
        self, 
        session_id: str, 
        role: str, 
        content: str,
        metadata: Optional[Dict] = None
    ):
        """Add message to conversation history with metadata"""
        session = self.get_session(session_id)
        if session:
            session.add_message(role, content, metadata)
            self.total_messages_processed += 1
            
            # Check if we should summarize
            if session.should_summarize():
                logger.info(f"⚠️ Session {session_id} has {len(session.conversation_history)} messages - consider summarizing")
    
    def update_session_metrics(
        self, 
        session_id: str, 
        tokens_used: int = 0, 
        response_time_ms: int = 0
    ):
        """Update session metrics"""
        session = self.get_session(session_id)
        if session:
            session.total_tokens_used += tokens_used
            
            # Update average response time
            if response_time_ms > 0:
                if session.avg_response_time_ms == 0:
                    session.avg_response_time_ms = response_time_ms
                else:
                    # Running average
                    session.avg_response_time_ms = int(
                        (session.avg_response_time_ms + response_time_ms) / 2
                    )
    
    def cleanup_expired_sessions(self, timeout_hours: int = 24):
        """Remove expired sessions"""
        expired = []
        for session_id, session in self.sessions.items():
            if session.is_expired(timeout_hours):
                expired.append(session_id)
        
        for session_id in expired:
            self.delete_session(session_id)
        
        if expired:
            logger.info(f"🧹 Cleaned up {len(expired)} expired sessions")
        
        return len(expired)
    
    def get_stats(self) -> Dict:
        """Get session manager statistics"""
        active_sessions = len(self.sessions)
        active_rooms = len(self.room_to_session)
        
        total_messages = sum(s.message_count for s in self.sessions.values())
        total_tokens = sum(s.total_tokens_used for s in self.sessions.values())
        
        return {
            "active_sessions": active_sessions,
            "active_rooms": active_rooms,
            "total_sessions_created": self.total_sessions_created,
            "total_messages": total_messages,
            "total_tokens": total_tokens,
            "avg_messages_per_session": total_messages / active_sessions if active_sessions > 0 else 0
        }
    
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