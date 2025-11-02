"""Clean session management service - Phase 1 refactor"""
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from collections import defaultdict

from ...models.domain import Session, SessionStats
from ..external.livekit import LiveKitClient

logger = logging.getLogger(__name__)


class SessionService:
    """Clean session management with functional approach"""
    
    def __init__(self, livekit_client: Optional[LiveKitClient] = None):
        self._sessions: Dict[str, Session] = {}
        self._room_mappings: Dict[str, str] = {}  # room_name -> session_id
        self._user_sessions: Dict[str, List[str]] = defaultdict(list)  # user_id -> [session_ids]
        self._livekit_client = livekit_client
        
        # Metrics
        self.total_sessions_created = 0
        self.total_messages_processed = 0
        
        logger.info("✅ SessionService initialized with clean architecture")
    
    async def get_or_create_for_room(self, room_name: str, user_id: str) -> Session:
        """Get existing session for room or create new one - KEY METHOD FOR WEBHOOKS"""
        # Check if room already has a session
        session_id = self._room_mappings.get(room_name)
        
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.update_activity()
            logger.info(f"🔄 Reusing session {session_id[:8]}... for room {room_name}")
            return session
        
        # Create new session for this room
        logger.info(f"🆕 Creating new session for room {room_name}")
        return await self._create_session(user_id, room_name)
    
    async def _create_session(self, user_id: str, room_name: Optional[str] = None) -> Session:
        """Create new session with LiveKit access token"""
        try:
            session = Session.create(user_id, room_name)
            
            # Generate LiveKit token if client available
            if self._livekit_client:
                session.access_token = await self._livekit_client.generate_access_token(
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
            
            # Store session and mappings
            self._sessions[session.id] = session
            self._room_mappings[session.room_name] = session.id
            self._user_sessions[user_id].append(session.id)
            
            self.total_sessions_created += 1
            
            logger.info(f"✅ Created session: {session.id[:8]}... for user: {user_id}")
            logger.info(f"📝 Room '{session.room_name}' mapped to session")
            return session
            
        except Exception as e:
            logger.error(f"Failed to create session for user {user_id}: {e}")
            raise
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        return self._sessions.get(session_id)
    
    def get_session_by_room(self, room_name: str) -> Optional[Session]:
        """Get session by room name"""
        session_id = self._room_mappings.get(room_name)
        if session_id:
            return self._sessions.get(session_id)
        return None
    
    def get_user_sessions(self, user_id: str) -> List[Session]:
        """Get all sessions for a user"""
        session_ids = self._user_sessions.get(user_id, [])
        return [self._sessions[sid] for sid in session_ids if sid in self._sessions]
    
    def add_message(
        self, 
        session_id: str, 
        role: str, 
        content: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Add message to conversation history with metadata"""
        session = self.get_session(session_id)
        if session:
            session.add_message(role, content, metadata)
            self.total_messages_processed += 1
            
            # Check if we should summarize
            if session.should_summarize():
                logger.info(f"⚠️ Session {session_id[:8]}... has {len(session.messages)} messages - consider summarizing")
            return True
        return False
    
    def update_session_metrics(
        self, 
        session_id: str, 
        tokens_used: int = 0, 
        response_time_ms: int = 0
    ) -> bool:
        """Update session metrics"""
        session = self.get_session(session_id)
        if session:
            session.update_metrics(tokens_used, response_time_ms)
            return True
        return False
    
    def delete_session(self, session_id: str) -> bool:
        """Delete session and cleanup mappings"""
        session = self.get_session(session_id)
        if not session:
            return False
        
        try:
            # Remove from all mappings
            if session.room_name in self._room_mappings:
                del self._room_mappings[session.room_name]
            
            if session.user_id in self._user_sessions:
                self._user_sessions[session.user_id].remove(session.id)
                # Clean up empty user session lists
                if not self._user_sessions[session.user_id]:
                    del self._user_sessions[session.user_id]
            
            del self._sessions[session_id]
            
            logger.info(f"🗑️ Deleted session: {session_id[:8]}...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False
    
    def cleanup_expired_sessions(self, timeout_hours: int = 24) -> int:
        """Remove expired sessions"""
        expired_ids = []
        for session_id, session in self._sessions.items():
            if session.is_expired(timeout_hours):
                expired_ids.append(session_id)
        
        cleaned_count = 0
        for session_id in expired_ids:
            if self.delete_session(session_id):
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"🧹 Cleaned up {cleaned_count} expired sessions")
        
        return cleaned_count
    
    def get_stats(self) -> SessionStats:
        """Get session manager statistics"""
        active_sessions = len(self._sessions)
        active_rooms = len(self._room_mappings)
        
        total_messages = sum(s.message_count for s in self._sessions.values())
        total_tokens = sum(s.total_tokens_used for s in self._sessions.values())
        
        # Skill statistics
        active_skills = sum(1 for s in self._sessions.values() if s.skill_session.is_active())
        skill_distribution = defaultdict(int)
        for session in self._sessions.values():
            if session.skill_session.active_skill:
                skill_distribution[session.skill_session.active_skill] += 1
        
        return SessionStats(
            active_sessions=active_sessions,
            active_rooms=active_rooms,
            total_sessions_created=self.total_sessions_created,
            total_messages=total_messages,
            total_tokens=total_tokens,
            avg_messages_per_session=total_messages / active_sessions if active_sessions > 0 else 0,
            active_skills=active_skills,
            skills_in_use=dict(skill_distribution)
        )
    
    async def generate_guest_token(self, session_id: str, guest_name: str) -> Optional[str]:
        """Generate access token for a guest user"""
        session = self.get_session(session_id)
        if not session or not session.room_name or not self._livekit_client:
            return None
        
        try:
            return await self._livekit_client.generate_access_token(
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