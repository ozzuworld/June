"""
Skill Orchestrator - Routes intents to skills or general chat

Phase 1: Basic routing with fallback to Gemini
Phase 2: Confirmation flows and skill registry
"""
import logging
from typing import Any, Optional, Dict
from dataclasses import dataclass
from enum import Enum

from app.services.dialogue_state import ConversationContext, Intent, DialogueState
from app.services.mockingbird_skill import MockingbirdSkill, MockingbirdState
from app.services.response_generator import ResponseGenerator

logger = logging.getLogger(__name__)


class OrchestrationState(Enum):
    """State machine for orchestration flow"""
    IDLE = "idle"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_SLOTS = "awaiting_slots"
    EXECUTING = "executing"


@dataclass
class OrchestrationResult:
    """Result of intent orchestration"""
    handled: bool
    response: Optional[str] = None
    should_speak: bool = True
    skill_activated: bool = False
    error: Optional[str] = None


# ===== PHASE 2: CRITICAL SKILLS REQUIRING CONFIRMATION =====
CRITICAL_SKILLS: Dict[str, str] = {
    "mockingbird_enable": "This will clone your voice from the conversation. Are you sure you want to proceed?",
    "mockingbird_disable": "This will switch back to my default voice. Would you like to continue?",
}


class SkillOrchestrator:
    """
    Routes intents to appropriate skills or general chat.

    Phase 1: Direct intent-to-skill mapping
    Future phases will add: skill registry, confirmation flows, slot filling
    """

    def __init__(self, session_id: str):
        """
        Initialize orchestrator for a session.

        Args:
            session_id: Unique session identifier
        """
        self.session_id = session_id
        self.mockingbird = MockingbirdSkill()

        # ===== Phase 2: Confirmation state tracking =====
        self.state = OrchestrationState.IDLE
        self.pending_intent: Optional[str] = None
        self.pending_context: Optional[ConversationContext] = None
        self.pending_room_name: Optional[str] = None

        # ===== Phase 3: Response generation =====
        self.response_generator = ResponseGenerator()

        # Intent to handler mapping
        self.intent_handlers = {
            "mockingbird_enable": self._handle_mockingbird_enable,
            "mockingbird_disable": self._handle_mockingbird_disable,
            "mockingbird_status": self._handle_mockingbird_status,
            "greeting": self._handle_greeting,
            "farewell": self._handle_farewell,
            "help": self._handle_help,
            "thank_you": self._handle_thank_you,
        }

        logger.info(f"SkillOrchestrator initialized for session: {session_id}")

    async def route_intent(
        self,
        session_id: str,
        room_name: str,
        context: ConversationContext,
        original_text: str,
        assistant: Any  # SimpleVoiceAssistant instance
    ) -> OrchestrationResult:
        """
        Route intent to appropriate handler.

        Args:
            session_id: Session identifier
            room_name: LiveKit room name
            context: ConversationContext from ConversationManager.process_user_input()
            original_text: Original user text
            assistant: SimpleVoiceAssistant instance (for fallback)

        Returns:
            OrchestrationResult with response and metadata
        """
        # ===== Phase 2: Check if we're awaiting confirmation =====
        if self.state == OrchestrationState.AWAITING_CONFIRMATION:
            logger.info(f"📋 Awaiting confirmation, checking user response: '{original_text}'")
            return await self._handle_confirmation_response(
                original_text=original_text,
                assistant=assistant,
                session_id=session_id,
                room_name=room_name
            )

        # Extract intent from context
        intent_obj = context.current_intent
        if not intent_obj:
            # No intent classified, fall back to general chat
            logger.info("No intent classified, falling back to general chat")
            await assistant.handle_transcript(
                session_id=session_id,
                room_name=room_name,
                text=original_text,
                detected_language=context.user_profile.get("preferred_language", "en"),
                bypass_intent_classification=True
            )
            return OrchestrationResult(handled=True, should_speak=False)

        intent_name = intent_obj.name
        confidence = intent_obj.confidence

        logger.info(
            f"Routing intent for session {session_id}: "
            f"intent={intent_name}, confidence={confidence:.2f}, text='{original_text}'"
        )

        # Check if we have a handler for this intent
        if intent_name in self.intent_handlers:
            # High confidence intent - handle directly
            if confidence >= 0.7:
                # ===== Phase 2: Check if intent requires confirmation =====
                if intent_name in CRITICAL_SKILLS and not self._is_confirmation_phrase(original_text):
                    logger.info(f"⚠️ Critical skill requires confirmation: {intent_name}")
                    return await self._request_confirmation(
                        intent_name=intent_name,
                        context=context,
                        room_name=room_name
                    )

                try:
                    logger.info(f"Executing handler for intent: {intent_name}")
                    result = await self.intent_handlers[intent_name](
                        context=context,
                        room_name=room_name
                    )

                    # Send response to TTS if handled and should speak
                    if result.handled and result.should_speak and result.response:
                        logger.info(f"Sending response to TTS: {result.response[:50]}...")

                        # Get language from user profile
                        language = context.user_profile.get("preferred_language", "en")

                        await assistant.send_to_tts(
                            session_id=session_id,
                            room_name=room_name,
                            text=result.response,
                            language=language
                        )

                    return result

                except Exception as e:
                    logger.error(f"Error handling intent {intent_name}: {e}", exc_info=True)
                    # Return error result
                    return OrchestrationResult(
                        handled=True,
                        response="I'm sorry, I encountered an error processing that request.",
                        should_speak=True,
                        error=str(e)
                    )

            else:
                logger.info(
                    f"Intent confidence too low ({confidence:.2f} < 0.7), "
                    f"falling back to general chat"
                )

        # No handler or low confidence - fall back to general chat
        logger.info(f"Falling back to general chat for: '{original_text}'")

        try:
            await assistant.handle_transcript(
                session_id=session_id,
                room_name=room_name,
                text=original_text,
                detected_language=context.user_profile.get("preferred_language", "en"),
                bypass_intent_classification=True  # We already classified
            )

            return OrchestrationResult(
                handled=True,
                should_speak=False  # Assistant handles TTS
            )

        except Exception as e:
            logger.error(f"Error in fallback to general chat: {e}", exc_info=True)
            return OrchestrationResult(
                handled=False,
                error=str(e)
            )

    # ==================== MOCKINGBIRD INTENT HANDLERS ====================

    async def _handle_mockingbird_enable(
        self,
        context: ConversationContext,
        room_name: str
    ) -> OrchestrationResult:
        """
        Handle mockingbird enable intent.

        Args:
            context: Conversation context with intent and slots
            room_name: LiveKit room name

        Returns:
            OrchestrationResult
        """
        logger.info(f"Enabling mockingbird for session {self.session_id}")

        try:
            # Check current state
            status = self.mockingbird.get_status(self.session_id)
            current_state = status.get("state")

            logger.info(f"Current mockingbird state: {current_state}")

            # Handle different states
            if current_state == MockingbirdState.ACTIVE:
                return OrchestrationResult(
                    handled=True,
                    response="Mockingbird is already active. I'm already using your cloned voice!",
                    skill_activated=False
                )

            if current_state in [MockingbirdState.CAPTURING, MockingbirdState.CLONING]:
                return OrchestrationResult(
                    handled=True,
                    response="Mockingbird is already in progress. Please wait while I process your voice...",
                    skill_activated=False
                )

            # Enable mockingbird
            result = await self.mockingbird.enable(self.session_id, room_name)

            if result.get("success"):
                logger.info("Mockingbird enabled successfully")
                return OrchestrationResult(
                    handled=True,
                    response=(
                        "Activating mockingbird! Please speak for about 8 seconds "
                        "so I can clone your voice. Just talk naturally - tell me "
                        "about your day or read something."
                    ),
                    skill_activated=True
                )
            else:
                error = result.get("error", "Unknown error")
                logger.error(f"Failed to enable mockingbird: {error}")
                return OrchestrationResult(
                    handled=True,
                    response=f"Sorry, I couldn't activate mockingbird: {error}",
                    skill_activated=False,
                    error=error
                )

        except Exception as e:
            logger.error(f"Exception enabling mockingbird: {e}", exc_info=True)
            return OrchestrationResult(
                handled=True,
                response="Sorry, I encountered an error activating mockingbird. Please try again.",
                skill_activated=False,
                error=str(e)
            )

    async def _handle_mockingbird_disable(
        self,
        context: ConversationContext,
        room_name: str
    ) -> OrchestrationResult:
        """
        Handle mockingbird disable intent.

        Args:
            context: Conversation context with intent and slots
            room_name: LiveKit room name

        Returns:
            OrchestrationResult
        """
        logger.info(f"Disabling mockingbird for session {self.session_id}")

        try:
            result = await self.mockingbird.disable(self.session_id)

            if result.get("success"):
                logger.info("Mockingbird disabled successfully")
                return OrchestrationResult(
                    handled=True,
                    response="I've switched back to my default voice. How does this sound?",
                    skill_activated=False
                )
            else:
                logger.info("Mockingbird was not active")
                return OrchestrationResult(
                    handled=True,
                    response="Mockingbird wasn't active, so I'm already using my default voice.",
                    skill_activated=False
                )

        except Exception as e:
            logger.error(f"Exception disabling mockingbird: {e}", exc_info=True)
            return OrchestrationResult(
                handled=True,
                response="Sorry, I had trouble changing voices.",
                skill_activated=False,
                error=str(e)
            )

    async def _handle_mockingbird_status(
        self,
        context: ConversationContext,
        room_name: str
    ) -> OrchestrationResult:
        """
        Handle mockingbird status check intent.

        Args:
            context: Conversation context with intent and slots
            room_name: LiveKit room name

        Returns:
            OrchestrationResult
        """
        logger.info(f"Checking mockingbird status for session {self.session_id}")

        try:
            status = self.mockingbird.get_status(self.session_id)
            state = status.get("state")

            logger.info(f"Mockingbird status: {state}")

            # State-specific responses
            responses = {
                MockingbirdState.INACTIVE: (
                    "Mockingbird is not active. I'm using my default voice. "
                    "Would you like me to clone your voice?"
                ),
                MockingbirdState.AWAITING_SAMPLE: (
                    "Mockingbird is waiting for you to speak so I can clone your voice."
                ),
                MockingbirdState.CAPTURING: (
                    "I'm currently recording your voice sample. Keep speaking..."
                ),
                MockingbirdState.CLONING: (
                    "I'm processing your voice clone. This will just take a moment..."
                ),
                MockingbirdState.ACTIVE: (
                    "Mockingbird is active! I'm using your cloned voice right now."
                ),
                MockingbirdState.ERROR: (
                    "Mockingbird encountered an error. Would you like to try again?"
                )
            }

            response = responses.get(state, "I'm not sure what mockingbird's status is.")

            return OrchestrationResult(
                handled=True,
                response=response,
                skill_activated=False
            )

        except Exception as e:
            logger.error(f"Exception checking mockingbird status: {e}", exc_info=True)
            return OrchestrationResult(
                handled=True,
                response="I'm having trouble checking the mockingbird status.",
                skill_activated=False,
                error=str(e)
            )

    # ==================== GENERAL INTENT HANDLERS ====================

    async def _handle_greeting(
        self,
        context: ConversationContext,
        room_name: str
    ) -> OrchestrationResult:
        """
        Handle greeting intent.

        Args:
            context: Conversation context with intent and slots
            room_name: LiveKit room name

        Returns:
            OrchestrationResult
        """
        logger.info(f"Handling greeting for session {self.session_id}")

        # ===== Phase 3: Use response generator for time-aware greetings =====
        greeting = self.response_generator.generate_greeting(context)

        return OrchestrationResult(
            handled=True,
            response=greeting,
            skill_activated=False
        )

    async def _handle_farewell(
        self,
        context: ConversationContext,
        room_name: str
    ) -> OrchestrationResult:
        """
        Handle farewell intent.

        Args:
            context: Conversation context with intent and slots
            room_name: LiveKit room name

        Returns:
            OrchestrationResult
        """
        logger.info(f"Handling farewell for session {self.session_id}")

        return OrchestrationResult(
            handled=True,
            response="Goodbye! Feel free to come back anytime.",
            skill_activated=False
        )

    async def _handle_help(
        self,
        context: ConversationContext,
        room_name: str
    ) -> OrchestrationResult:
        """
        Handle help intent.

        Args:
            context: Conversation context with intent and slots
            room_name: LiveKit room name

        Returns:
            OrchestrationResult
        """
        logger.info(f"Handling help request for session {self.session_id}")

        help_text = (
            "I'm June, your AI assistant! I can have conversations with you, "
            "answer questions, and use special skills. "
            "For example, you can ask me to enable 'mockingbird' to clone your voice, "
            "or just chat with me about anything you'd like to know."
        )

        return OrchestrationResult(
            handled=True,
            response=help_text,
            skill_activated=False
        )

    async def _handle_thank_you(
        self,
        context: ConversationContext,
        room_name: str
    ) -> OrchestrationResult:
        """
        Handle thank you intent.

        Args:
            context: Conversation context with intent and slots
            room_name: LiveKit room name

        Returns:
            OrchestrationResult
        """
        logger.info(f"Handling thank you for session {self.session_id}")

        return OrchestrationResult(
            handled=True,
            response="You're welcome! Let me know if you need anything else.",
            skill_activated=False
        )

    # ==================== PHASE 2: CONFIRMATION FLOW METHODS ====================

    def _is_confirmation_phrase(self, text: str) -> bool:
        """
        Check if text is a confirmation/affirmation phrase.

        Args:
            text: User text to check

        Returns:
            True if text appears to be confirming
        """
        text_lower = text.lower().strip()

        # Affirmative patterns
        affirmatives = [
            "yes", "yeah", "yep", "yup", "sure", "ok", "okay",
            "alright", "go ahead", "proceed", "continue", "do it",
            "affirmative", "correct", "right", "absolutely", "definitely"
        ]

        # Check if text starts with or contains affirmatives
        for affirm in affirmatives:
            if text_lower == affirm or text_lower.startswith(affirm + " "):
                return True

        return False

    def _is_negative_phrase(self, text: str) -> bool:
        """
        Check if text is a negative/rejection phrase.

        Args:
            text: User text to check

        Returns:
            True if text appears to be rejecting
        """
        text_lower = text.lower().strip()

        # Negative patterns
        negatives = [
            "no", "nope", "nah", "never mind", "nevermind", "cancel",
            "stop", "don't", "negative", "not now", "maybe later",
            "i changed my mind", "abort"
        ]

        for negative in negatives:
            if text_lower == negative or negative in text_lower:
                return True

        return False

    async def _request_confirmation(
        self,
        intent_name: str,
        context: ConversationContext,
        room_name: str
    ) -> OrchestrationResult:
        """
        Request confirmation from user for a critical skill.

        Args:
            intent_name: The intent requiring confirmation
            context: Conversation context
            room_name: LiveKit room name

        Returns:
            OrchestrationResult with confirmation prompt
        """
        logger.info(f"📋 Requesting confirmation for intent: {intent_name}")

        # Store pending intent info
        self.state = OrchestrationState.AWAITING_CONFIRMATION
        self.pending_intent = intent_name
        self.pending_context = context
        self.pending_room_name = room_name

        # Get confirmation message
        confirmation_message = CRITICAL_SKILLS.get(
            intent_name,
            "Are you sure you want to do this?"
        )

        return OrchestrationResult(
            handled=True,
            response=confirmation_message,
            should_speak=True,
            skill_activated=False
        )

    async def _handle_confirmation_response(
        self,
        original_text: str,
        assistant: Any,
        session_id: str,
        room_name: str
    ) -> OrchestrationResult:
        """
        Handle user's response to confirmation prompt.

        Args:
            original_text: User's response text
            assistant: Assistant instance
            session_id: Session ID
            room_name: Room name

        Returns:
            OrchestrationResult
        """
        if self._is_confirmation_phrase(original_text):
            # User confirmed - execute pending intent
            logger.info(f"✅ User confirmed intent: {self.pending_intent}")

            intent_name = self.pending_intent
            context = self.pending_context
            pending_room = self.pending_room_name

            # Reset state
            self.state = OrchestrationState.IDLE
            self.pending_intent = None
            self.pending_context = None
            self.pending_room_name = None

            # Execute the handler
            try:
                result = await self.intent_handlers[intent_name](
                    context=context,
                    room_name=pending_room
                )

                # Send response to TTS if needed
                if result.handled and result.should_speak and result.response:
                    language = context.user_profile.get("preferred_language", "en")
                    await assistant.send_to_tts(
                        session_id=session_id,
                        room_name=room_name,
                        text=result.response,
                        language=language
                    )

                return result

            except Exception as e:
                logger.error(f"Error executing confirmed intent: {e}", exc_info=True)
                return OrchestrationResult(
                    handled=True,
                    response="Sorry, I encountered an error. Please try again.",
                    error=str(e)
                )

        elif self._is_negative_phrase(original_text):
            # User declined
            logger.info(f"❌ User declined intent: {self.pending_intent}")

            # Reset state
            self.state = OrchestrationState.IDLE
            self.pending_intent = None
            self.pending_context = None
            self.pending_room_name = None

            return OrchestrationResult(
                handled=True,
                response="Okay, I've canceled that. What would you like to do instead?"
            )

        else:
            # Unclear response - ask again
            logger.info(f"❓ Unclear confirmation response: '{original_text}'")

            return OrchestrationResult(
                handled=True,
                response="I didn't catch that. Please say 'yes' to proceed or 'no' to cancel."
            )
