"""
Conversation Manager - Tracks participants, rooms, and LiveKit state

Responsibilities:
- Track who is in which room
- Map session_id to LiveKit participant identity
- Monitor audio track availability
- Provide room state to skills (Mockingbird)
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Set
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ParticipantState(str, Enum):
    """Participant connection states"""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


@dataclass
class ParticipantInfo:
    """Information about a room participant"""
    identity: str
    session_id: str
    name: Optional[str]
    joined_at: datetime
    state: ParticipantState = ParticipantState.CONNECTING
    audio_track_sid: Optional[str] = None
    is_publishing_audio: bool = False
    is_speaking: bool = False
    last_audio_at: Optional[datetime] = None


@dataclass
class RoomState:
    """State of a LiveKit room"""
    room_name: str
    participants: Dict[str, ParticipantInfo] = field(default_factory=dict)  # identity -> info
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def get_participant_by_session(self, session_id: str) -> Optional[ParticipantInfo]:
        """Find participant by session_id"""
        for p in self.participants.values():
            if p.session_id == session_id:
                return p
        return None
    
    def get_audio_tracks(self, session_id: str) -> list[str]:
        """Get audio track SIDs for a session"""
        participant = self.get_participant_by_session(session_id)
        if participant and participant.audio_track_sid:
            return [participant.audio_track_sid]
        return []
    
    def get_connected_count(self) -> int:
        """Get count of connected participants"""
        return sum(1 for p in self.participants.values() if p.state == ParticipantState.CONNECTED)


class ConversationManager:
    """
    Manages conversation state, participants, and LiveKit room tracking
    
    This is the central source of truth for:
    - Who is in which room
    - Session ID to participant identity mapping
    - Audio track availability
    - Participant publishing state
    """
    
    def __init__(self):
        self.rooms: Dict[str, RoomState] = {}  # room_name -> state
        self.session_to_room: Dict[str, str] = {}  # session_id -> room_name
        self.session_to_identity: Dict[str, str] = {}  # session_id -> identity
        logger.info("✅ ConversationManager initialized")
    
    def register_participant(
        self, 
        room_name: str, 
        session_id: str, 
        identity: Optional[str] = None,
        name: Optional[str] = None
    ) -> ParticipantInfo:
        """
        Register a participant joining a room
        
        Args:
            room_name: LiveKit room name
            session_id: Session identifier
            identity: LiveKit participant identity (defaults to session_id)
            name: Display name
        
        Returns:
            ParticipantInfo object
        """
        # Create room if it doesn't exist
        if room_name not in self.rooms:
            self.rooms[room_name] = RoomState(
                room_name=room_name,
                created_at=datetime.utcnow()
            )
            logger.info(f"🏠 Created room state: '{room_name}'")
        
        # Default identity to session_id if not provided
        if identity is None:
            identity = session_id
        
        # Check if participant already exists
        if identity in self.rooms[room_name].participants:
            logger.debug(f"👤 Participant {identity} already registered in '{room_name}'")
            return self.rooms[room_name].participants[identity]
        
        # Create participant
        participant = ParticipantInfo(
            identity=identity,
            session_id=session_id,
            name=name or identity,
            joined_at=datetime.utcnow(),
            state=ParticipantState.CONNECTING
        )
        
        self.rooms[room_name].participants[identity] = participant
        self.session_to_room[session_id] = room_name
        self.session_to_identity[session_id] = identity
        
        logger.info(
            f"👤 Registered: {identity} (session: {session_id[:8]}...) "
            f"in room '{room_name}'"
        )
        
        return participant
    
    def mark_participant_connected(self, room_name: str, identity: str):
        """Mark participant as fully connected"""
        if room_name in self.rooms and identity in self.rooms[room_name].participants:
            participant = self.rooms[room_name].participants[identity]
            participant.state = ParticipantState.CONNECTED
            logger.info(f"✅ Participant {identity} connected in '{room_name}'")
    
    def update_audio_track(
        self, 
        room_name: str, 
        identity: str, 
        track_sid: str,
        is_publishing: bool = True
    ):
        """Update participant's audio track info"""
        if room_name in self.rooms and identity in self.rooms[room_name].participants:
            participant = self.rooms[room_name].participants[identity]
            participant.audio_track_sid = track_sid
            participant.is_publishing_audio = is_publishing
            participant.last_audio_at = datetime.utcnow()
            
            logger.info(
                f"🎤 Audio track for {identity} in '{room_name}': "
                f"{track_sid} (publishing={is_publishing})"
            )
        else:
            logger.warning(
                f"⚠️ Cannot update audio track for unknown participant: "
                f"{identity} in '{room_name}'"
            )
    
    def get_room_state(self, room_name: str) -> Optional[RoomState]:
        """Get current state of a room"""
        return self.rooms.get(room_name)
    
    def get_participant_info(self, session_id: str) -> Optional[ParticipantInfo]:
        """Get participant info by session_id"""
        room_name = self.session_to_room.get(session_id)
        if room_name and room_name in self.rooms:
            return self.rooms[room_name].get_participant_by_session(session_id)
        return None
    
    def get_participant_identity(self, session_id: str) -> Optional[str]:
        """Get LiveKit participant identity for a session"""
        return self.session_to_identity.get(session_id)
    
    def is_participant_in_room(self, session_id: str, room_name: str) -> bool:
        """Check if participant is in room"""
        room = self.get_room_state(room_name)
        if not room:
            return False
        return room.get_participant_by_session(session_id) is not None
    
    def is_participant_publishing_audio(self, session_id: str) -> bool:
        """Check if participant is publishing audio"""
        participant = self.get_participant_info(session_id)
        return participant is not None and participant.is_publishing_audio
    
    def remove_participant(self, room_name: str, identity: str):
        """Remove participant from room"""
        if room_name in self.rooms and identity in self.rooms[room_name].participants:
            participant = self.rooms[room_name].participants[identity]
            session_id = participant.session_id
            
            # Mark as disconnected first
            participant.state = ParticipantState.DISCONNECTED
            
            # Remove from mappings
            del self.rooms[room_name].participants[identity]
            
            if session_id in self.session_to_room:
                del self.session_to_room[session_id]
            
            if session_id in self.session_to_identity:
                del self.session_to_identity[session_id]
            
            logger.info(f"👋 Removed: {identity} from room '{room_name}'")
            
            # Clean up empty rooms
            if not self.rooms[room_name].participants:
                del self.rooms[room_name]
                logger.info(f"🧹 Cleaned up empty room '{room_name}'")
        else:
            logger.warning(
                f"⚠️ Cannot remove unknown participant: {identity} from '{room_name}'"
            )
    
    def get_stats(self) -> Dict:
        """Get conversation manager statistics"""
        total_participants = sum(
            len(room.participants) for room in self.rooms.values()
        )
        connected_participants = sum(
            room.get_connected_count() for room in self.rooms.values()
        )
        
        return {
            "total_rooms": len(self.rooms),
            "total_participants": total_participants,
            "connected_participants": connected_participants,
            "rooms": {
                name: {
                    "participants": len(room.participants),
                    "connected": room.get_connected_count()
                }
                for name, room in self.rooms.items()
            }
        }
    
    def clear_session(self, session_id: str):
        """Clear all data for a session"""
        room_name = self.session_to_room.get(session_id)
        identity = self.session_to_identity.get(session_id)
        
        if room_name and identity:
            self.remove_participant(room_name, identity)
        
        # Clean up any remaining mappings
        if session_id in self.session_to_room:
            del self.session_to_room[session_id]
        if session_id in self.session_to_identity:
            del self.session_to_identity[session_id]
