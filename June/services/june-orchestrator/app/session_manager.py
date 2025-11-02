"""Phase 1: Backward-compatible session manager using clean architecture

This file maintains the same interface as the original session_manager
but uses the new clean architecture underneath. This allows existing
code to work without changes during Phase 1.
"""
import logging
from typing import Dict, Optional, List, Any
from datetime import datetime

from .models.domain import Session, SessionStats
from .core.dependencies import get_session_service

logger = logging.getLogger(__name__)


class SessionManagerV2:
    """Backward-compatible wrapper around clean SessionService
    
    This class maintains the same interface as the original session_manager
    but uses the new clean architecture underneath.
    """
    
    def __init__(self):
        # Use dependency injection to get the clean service
        self._session_service = None
        logger.info("✅ SessionManager initialized (Phase 1 clean architecture)")
    
    def _get_service(self):
        """Lazy load the session service"""
        if self._session_service is None:
            self._session_service = get_session_service()
        return self._session_service
    
    async def create_session(self, user_id: str, room_name: Optional[str] = None) -> 'SessionWrapper':
        """Create new session - backward compatible"""
        session = await self._get_service()._create_session(user_id, room_name)
        return SessionWrapper(session)
    
    async def get_or_create_session_for_room(self, room_name: str, user_id: str) -> 'SessionWrapper':
        """Get existing session for room or create new one - KEY METHOD FOR WEBHOOKS"""
        session = await self._get_service().get_or_create_for_room(room_name, user_id)
        return SessionWrapper(session)
    
    def get_session(self, session_id: str) -> Optional['SessionWrapper']:
        """Get session by ID"""
        session = self._get_service().get_session(session_id)
        return SessionWrapper(session) if session else None
    
    def get_session_by_room(self, room_name: str) -> Optional['SessionWrapper']:
        """Get session by room name"""
        session = self._get_service().get_session_by_room(room_name)
        return SessionWrapper(session) if session else None
    
    def get_user_sessions(self, user_id: str) -> List['SessionWrapper']:
        """Get all sessions for a user"""
        sessions = self._get_service().get_user_sessions(user_id)
        return [SessionWrapper(session) for session in sessions]
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session and cleanup mappings"""
        return self._get_service().delete_session(session_id)
    
    def add_to_history(
        self, 
        session_id: str, 
        role: str, 
        content: str,
        metadata: Optional[Dict] = None
    ):
        """Add message to conversation history with metadata"""
        self._get_service().add_message(session_id, role, content, metadata)
    
    def update_session_metrics(
        self, 
        session_id: str, 
        tokens_used: int = 0, 
        response_time_ms: int = 0
    ):
        """Update session metrics"""
        self._get_service().update_session_metrics(session_id, tokens_used, response_time_ms)
    
    def cleanup_expired_sessions(self, timeout_hours: int = 24) -> int:
        """Remove expired sessions"""
        return self._get_service().cleanup_expired_sessions(timeout_hours)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get session manager statistics - backward compatible format"""
        stats = self._get_service().get_stats()
        
        # Convert to original dict format for backward compatibility
        return {
            "active_sessions": stats.active_sessions,
            "active_rooms": stats.active_rooms,
            "total_sessions_created": stats.total_sessions_created,
            "total_messages": stats.total_messages,
            "total_tokens": stats.total_tokens,
            "avg_messages_per_session": stats.avg_messages_per_session,
            "active_skills": stats.active_skills,
            "skills_in_use": stats.skills_in_use
        }
    
    async def generate_guest_token(self, session_id: str, guest_name: str) -> Optional[str]:
        """Generate access token for a guest user"""
        return await self._get_service().generate_guest_token(session_id, guest_name)


class SessionWrapper:
    """Wrapper around clean Session model for backward compatibility
    
    This provides the same interface as the old Session class
    but uses the new clean domain model underneath.
    """
    
    def __init__(self, session: Session):
        self._session = session
    
    # Expose properties for backward compatibility
    @property
    def session_id(self) -> str:
        return self._session.id
    
    @property
    def user_id(self) -> str:
        return self._session.user_id
    
    @property
    def room_name(self) -> str:
        return self._session.room_name
    
    @property
    def access_token(self) -> Optional[str]:
        return self._session.access_token
    
    @access_token.setter
    def access_token(self, value: str):
        self._session.access_token = value
    
    @property
    def created_at(self) -> datetime:
        return self._session.created_at
    
    @property
    def last_activity(self) -> datetime:
        return self._session.last_activity
    
    @property
    def status(self) -> str:
        return self._session.status
    
    @property
    def conversation_history(self) -> List[Dict]:
        """Return conversation history in old format for backward compatibility"""
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "metadata": msg.metadata
            }
            for msg in self._session.messages
        ]
    
    @property
    def message_count(self) -> int:
        return self._session.message_count
    
    @property
    def total_tokens_used(self) -> int:
        return self._session.total_tokens_used
    
    @property
    def skill_session(self):
        return self._session.skill_session
    
    # Methods for backward compatibility
    def update_activity(self):
        """Update last activity timestamp"""
        self._session.update_activity()
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add message to conversation history with metadata"""
        self._session.add_message(role, content, metadata)
    
    def get_recent_history(self, max_messages: Optional[int] = None) -> List[Dict]:
        """Get recent conversation history"""
        return self._session.get_recent_history(max_messages)
    
    def should_summarize(self) -> bool:
        """Check if conversation should be summarized"""
        return self._session.should_summarize()
    
    def is_expired(self, timeout_hours: int = 24) -> bool:
        """Check if session has expired"""
        return self._session.is_expired(timeout_hours)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for backward compatibility"""
        # Import here to avoid circular imports
        try:
            from .services.livekit_service import livekit_service
            livekit_url = livekit_service.get_connection_info().get("livekit_url", "")
        except ImportError:
            # Fallback if the old service doesn't exist
            from .core.dependencies import get_livekit_client
            livekit_client = get_livekit_client()
            livekit_url = livekit_client.get_connection_info().get("livekit_url", "")
        
        return {
            "session_id": self._session.id,
            "user_id": self._session.user_id,
            "room_name": self._session.room_name,
            "access_token": self._session.access_token,
            "created_at": self._session.created_at.isoformat(),
            "last_activity": self._session.last_activity.isoformat(),
            "status": self._session.status,
            "message_count": self._session.message_count,
            "total_tokens": self._session.total_tokens_used,
            "livekit_url": livekit_url,
            "skill_state": {
                "active_skill": self._session.skill_session.active_skill,
                "context": self._session.skill_session.context,
                "turn_count": self._session.skill_session.turn_count,
                "activated_at": self._session.skill_session.activated_at.isoformat() if self._session.skill_session.activated_at else None,
                "waiting_for_input": self._session.skill_session.waiting_for_input
            }
        }


# Create backward-compatible global instance
session_manager = SessionManagerV2()

logger.info("✅ Phase 1: Backward-compatible session manager initialized")
logger.info("✨ Using clean architecture with dependency injection")
logger.info("🔄 Original session_manager interface preserved for compatibility")