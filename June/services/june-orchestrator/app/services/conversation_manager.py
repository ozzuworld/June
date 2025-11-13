"""
Enhanced Conversation Manager for June Orchestrator
Phase 1 Implementation - UPDATED

Integrates:
- Dialogue State Tracking (DST)
- Intent recognition
- Slot extraction
- Context management
- Participant tracking (existing)
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field

# Import existing participant tracking
from dataclasses import dataclass
from enum import Enum

# Import new Phase 1 components
from .dialogue_state import (
    DialogueState,
    Intent,
    ConversationContext,
    ConversationTurn
)
from .intent_classifier import IntentClassifier
from .slot_extractor import SlotExtractor

logger = logging.getLogger(__name__)


# ===== EXISTING CLASSES (Keep these for backward compatibility) =====

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


# ===== ENHANCED CONVERSATION MANAGER =====

class EnhancedConversationManager:
    """
    Enhanced conversation manager with Dialogue State Tracking
    
    Combines:
    - Existing participant/room tracking (backward compatible)
    - NEW: Intent recognition
    - NEW: Slot extraction
    - NEW: Context management
    - NEW: Dialogue state tracking
    """
    
    def __init__(self):
        # ===== EXISTING: Participant tracking =====
        self.rooms: Dict[str, RoomState] = {}
        self.session_to_room: Dict[str, str] = {}
        self.session_to_identity: Dict[str, str] = {}
        
        # ===== NEW: Conversation context tracking =====
        self.conversation_contexts: Dict[str, ConversationContext] = {}
        
        # ===== NEW: AI components =====
        self.intent_classifier = IntentClassifier()
        self.slot_extractor = SlotExtractor()
        
        logger.info("✅ Enhanced ConversationManager initialized")
        logger.info("   - Participant tracking: ✓")
        logger.info("   - Intent classification: ✓")
        logger.info("   - Slot extraction: ✓")
        logger.info("   - Context management: ✓")
    
    # ========================================
    # EXISTING METHODS (Backward compatible)
    # ========================================
    
    def register_participant(
        self, 
        room_name: str, 
        session_id: str, 
        identity: Optional[str] = None,
        name: Optional[str] = None
    ) -> ParticipantInfo:
        """Register a participant (EXISTING - unchanged)"""
        if room_name not in self.rooms:
            self.rooms[room_name] = RoomState(
                room_name=room_name,
                created_at=datetime.utcnow()
            )
            logger.info(f"🏠 Created room state: '{room_name}'")
        
        if identity is None:
            identity = session_id
        
        if identity in self.rooms[room_name].participants:
            logger.debug(f"👤 Participant {identity} already registered in '{room_name}'")
            return self.rooms[room_name].participants[identity]
        
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
        """Mark participant as connected (EXISTING - unchanged)"""
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
        """Update audio track (EXISTING - unchanged)"""
        if room_name in self.rooms and identity in self.rooms[room_name].participants:
            participant = self.rooms[room_name].participants[identity]
            participant.audio_track_sid = track_sid
            participant.is_publishing_audio = is_publishing
            participant.last_audio_at = datetime.utcnow()
            
            logger.info(
                f"🎤 Audio track for {identity} in '{room_name}': "
                f"{track_sid} (publishing={is_publishing})"
            )
    
    def get_room_state(self, room_name: str) -> Optional[RoomState]:
        """Get room state (EXISTING - unchanged)"""
        return self.rooms.get(room_name)
    
    def get_participant_info(self, session_id: str) -> Optional[ParticipantInfo]:
        """Get participant info (EXISTING - unchanged)"""
        room_name = self.session_to_room.get(session_id)
        if room_name and room_name in self.rooms:
            return self.rooms[room_name].get_participant_by_session(session_id)
        return None
    
    def get_participant_identity(self, session_id: str) -> Optional[str]:
        """Get participant identity (EXISTING - unchanged)"""
        return self.session_to_identity.get(session_id)
    
    def is_participant_in_room(self, session_id: str, room_name: str) -> bool:
        """Check if participant is in room (EXISTING - unchanged)"""
        room = self.get_room_state(room_name)
        if not room:
            return False
        return room.get_participant_by_session(session_id) is not None
    
    def is_participant_publishing_audio(self, session_id: str) -> bool:
        """Check if publishing audio (EXISTING - unchanged)"""
        participant = self.get_participant_info(session_id)
        return participant is not None and participant.is_publishing_audio
    
    def remove_participant(self, room_name: str, identity: str):
        """Remove participant (EXISTING - unchanged)"""
        if room_name in self.rooms and identity in self.rooms[room_name].participants:
            participant = self.rooms[room_name].participants[identity]
            session_id = participant.session_id
            
            participant.state = ParticipantState.DISCONNECTED
            del self.rooms[room_name].participants[identity]
            
            if session_id in self.session_to_room:
                del self.session_to_room[session_id]
            if session_id in self.session_to_identity:
                del self.session_to_identity[session_id]
            
            logger.info(f"👋 Removed: {identity} from room '{room_name}'")
            
            if not self.rooms[room_name].participants:
                del self.rooms[room_name]
                logger.info(f"🧹 Cleaned up empty room '{room_name}'")
    
    # ========================================
    # NEW METHODS: Dialogue State Tracking
    # ========================================
    
    def process_user_input(
        self, 
        session_id: str, 
        text: str,
        audio_features: Optional[Dict] = None
    ) -> ConversationContext:
        """
        Process user input with intent recognition and state tracking
        
        This is the main entry point for the enhanced conversation system.
        
        Args:
            session_id: Session identifier
            text: User's text input
            audio_features: Optional audio features (for future use)
            
        Returns:
            Updated ConversationContext
        """
        # Get or create context
        context = self.get_or_create_context(session_id)
        
        # 1. Classify intent
        intent = self.intent_classifier.classify(text, context)
        logger.info(
            f"🎯 Intent: {intent.name} "
            f"(confidence: {intent.confidence:.2f})"
        )
        
        # 2. Extract slots
        extracted_slots = self.slot_extractor.extract(
            text, 
            intent,
            existing_slots=context.filled_slots
        )
        
        if extracted_slots:
            logger.info(f"📋 Extracted slots: {extracted_slots}")
            for slot_name, slot_value in extracted_slots.items():
                context.add_slot(slot_name, slot_value)
        
        # 3. Update context
        context.update_intent(intent)
        
        # 4. Determine dialogue state
        new_state = self._determine_dialogue_state(context, intent)
        context.update_state(new_state)
        
        # 5. Check for context switches
        if self._is_context_switch(text, context):
            topic = self._extract_topic(text, intent)
            context.switch_topic(topic)
        
        # 6. Update conversation style
        self._update_conversation_style(text, context)
        
        # 7. Add user turn to history
        context.add_turn(
            role="user",
            content=text,
            intent=intent,
            metadata={
                "audio_features": audio_features
            }
        )
        
        logger.debug(f"Context updated: {context.get_stats()}")
        
        return context
    
    def add_assistant_response(
        self,
        session_id: str,
        response: str,
        metadata: Optional[Dict] = None
    ):
        """
        Add assistant response to conversation context
        
        Args:
            session_id: Session identifier
            response: Assistant's response text
            metadata: Optional metadata (tools used, latency, etc.)
        """
        context = self.get_or_create_context(session_id)
        
        context.add_turn(
            role="assistant",
            content=response,
            metadata=metadata or {}
        )
        
        logger.debug(f"Added assistant response to context ({len(response)} chars)")
    
    def get_or_create_context(self, session_id: str) -> ConversationContext:
        """Get or create conversation context for session"""
        if session_id not in self.conversation_contexts:
            self.conversation_contexts[session_id] = ConversationContext(
                session_id=session_id
            )
            logger.info(f"📝 Created conversation context for {session_id[:8]}...")
        
        return self.conversation_contexts[session_id]
    
    def get_context(self, session_id: str) -> Optional[ConversationContext]:
        """Get existing conversation context"""
        return self.conversation_contexts.get(session_id)
    
    def _determine_dialogue_state(
        self, 
        context: ConversationContext, 
        intent: Intent
    ) -> DialogueState:
        """
        Determine dialogue state based on intent and context
        
        State machine logic for conversation flow
        """
        # Greetings
        if intent.name == "greeting":
            return DialogueState.GREETING
        
        # Farewells
        if intent.name == "farewell":
            return DialogueState.CLOSING
        
        # Check if we need to fill slots
        missing_slots = self.slot_extractor.get_missing_slots(
            intent,
            context.filled_slots
        )
        
        if missing_slots:
            context.pending_slots = missing_slots
            return DialogueState.SLOT_FILLING
        
        # Check if intent needs confirmation
        if self._needs_confirmation(intent):
            return DialogueState.CONFIRMATION
        
        # Check if we need clarification
        if not intent.is_confident():
            return DialogueState.CLARIFICATION
        
        # Ready to execute
        if intent.is_confident() and not missing_slots:
            return DialogueState.EXECUTION
        
        # Default: general conversation
        return DialogueState.GENERAL_CONVERSATION
    
    def _needs_confirmation(self, intent: Intent) -> bool:
        """Check if intent requires confirmation"""
        # Critical intents should be confirmed
        critical_intents = {
            "mockingbird_enable",
            "mockingbird_disable"
        }
        
        return intent.name in critical_intents and intent.confidence < 0.95
    
    def _is_context_switch(
        self, 
        text: str, 
        context: ConversationContext
    ) -> bool:
        """Detect if user is switching topics"""
        # Simple heuristic: different intent family
        if not context.current_intent:
            return False
        
        # Check for explicit topic switches
        topic_switch_phrases = [
            "actually",
            "wait",
            "never mind",
            "instead",
            "let's talk about",
            "change of plans"
        ]
        
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in topic_switch_phrases)
    
    def _extract_topic(self, text: str, intent: Intent) -> str:
        """Extract topic from text"""
        # Use intent domain as topic
        if intent.domain:
            return intent.domain
        
        # Use intent name as fallback
        return intent.name
    
    def _update_conversation_style(
        self, 
        text: str, 
        context: ConversationContext
    ):
        """Learn user's conversation style"""
        text_lower = text.lower()
        
        # Detect formal style
        formal_indicators = ["please", "kindly", "would you", "could you"]
        formal_score = sum(1 for phrase in formal_indicators if phrase in text_lower)
        
        # Detect casual style
        casual_indicators = ["hey", "yeah", "cool", "awesome", "gotcha"]
        casual_score = sum(1 for phrase in casual_indicators if phrase in text_lower)
        
        # Update style
        if formal_score > casual_score:
            context.conversation_style = "formal"
        elif casual_score > formal_score:
            context.conversation_style = "casual"
        # else: keep current style
    
    def clear_session(self, session_id: str):
        """Clear all data for a session"""
        # Clear context
        if session_id in self.conversation_contexts:
            del self.conversation_contexts[session_id]
            logger.info(f"🗑️ Cleared context for {session_id[:8]}...")
        
        # Clear participant tracking
        room_name = self.session_to_room.get(session_id)
        identity = self.session_to_identity.get(session_id)
        
        if room_name and identity:
            self.remove_participant(room_name, identity)
        
        # Clean up mappings
        if session_id in self.session_to_room:
            del self.session_to_room[session_id]
        if session_id in self.session_to_identity:
            del self.session_to_identity[session_id]
    
    def get_stats(self) -> Dict:
        """Get comprehensive statistics"""
        # Participant stats
        total_participants = sum(
            len(room.participants) for room in self.rooms.values()
        )
        connected_participants = sum(
            room.get_connected_count() for room in self.rooms.values()
        )
        
        # Context stats
        total_contexts = len(self.conversation_contexts)
        active_intents = sum(
            1 for ctx in self.conversation_contexts.values()
            if ctx.current_intent and ctx.current_intent.is_confident()
        )
        
        # Dialogue state distribution
        state_distribution = {}
        for ctx in self.conversation_contexts.values():
            state = ctx.current_state
            state_distribution[state] = state_distribution.get(state, 0) + 1
        
        return {
            "rooms": {
                "total": len(self.rooms),
                "participants": total_participants,
                "connected": connected_participants
            },
            "conversations": {
                "total_contexts": total_contexts,
                "active_intents": active_intents,
                "state_distribution": state_distribution
            },
            "intents_available": len(self.intent_classifier.get_available_intents())
        }


# Alias for backward compatibility
ConversationManager = EnhancedConversationManager